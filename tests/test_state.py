"""05-state構築 8章の受入テスト（T05-01〜07、T05-09〜25）。

T05-08（`DbMarketContext` の直前終値）は M6 に送った（task 025）。
本文 fixture は `read_text(encoding="utf-8")` で読む（4.3。CRLF が LF になる）。
"""

import json
from datetime import timedelta

import pytest
from schema_check import assert_valid, validate

from conftest import CONFIG_DIR, CONTRACTS_DIR, FIXTURES, read_fixture, split_disclosures
from test_bundle import ROWS_14, ROWS_17, insert_events, pick, synthetic

from jevfwd import settings as settings_mod
from jevfwd.common.errors import JevfwdError
from jevfwd.common.timeutil import jst_minute_to_utc_str, parse_utc, to_utc_str
from jevfwd.state import truncate
from jevfwd.state.builder import DocInput, IssuerInput, build_state, join_bodies
from jevfwd.state.context import MARKET_CONTEXT_KEYS, DbDisclosureContext, NullMarketContext
from jevfwd.store import db

SCHEMA = json.loads((CONTRACTS_DIR / "state.v2.schema.json").read_text(encoding="utf-8"))
HOBONICHI_AT = jst_minute_to_utc_str("2026-09-17", "17:30")


@pytest.fixture
def cfg():
    return settings_mod.load_settings(CONFIG_DIR / "settings.yaml")


@pytest.fixture
def filters_v1():
    return settings_mod.load_filters(CONFIG_DIR / "filters.v1.yaml")


@pytest.fixture
def conn(db_path):
    db.migrate(db_path)
    connection = db.connect(db_path)
    yield connection
    connection.close()


class StubDisclosure:
    """DB を使わないテスト用の DisclosureContext。"""

    def __init__(self, titles=(), forecast=None):
        self._titles = list(titles)
        self._forecast = forecast

    def recent_titles(self, code5, before_utc, days):
        return list(self._titles)

    def forecast_context(self, code5, event_ids):
        return self._forecast


def blocks(name, min_chars=200):
    """本文 fixture を開示ごとに分ける（短すぎる断片は捨てる）。"""
    return [p for p in split_disclosures(read_fixture(name)) if len(p) > min_chars]


def build(
    docs,
    cfg,
    *,
    code5="35600",
    company="株式会社ほぼ日",
    market=None,
    anchor=HOBONICHI_AT,
    session="after_close",
    disc=None,
    market_ctx=None,
):
    return build_state(
        issuer=IssuerInput(code5=code5, company=company, market=market, event_ids=(1,)),
        anchor_published_at=anchor,
        session=session,
        docs=docs,
        market_ctx=market_ctx or NullMarketContext(),
        disc_ctx=disc or StubDisclosure(),
        cfg=cfg,
    )


def hobonichi_docs(filters_v1):
    """ほぼ日4件。本文があるのは決算期変更の1件だけ（他は PDF 未取得）。"""
    body = read_fixture("3560_hobonichi_fiscal_year_change.txt")
    docs = []
    for row in pick(ROWS_17, "35600", "17:30"):
        has_body = row.title.startswith("決算期（事業年度の末日）の変更")
        docs.append(
            DocInput(
                title=row.title,
                body=body if has_body else None,
                rank=filters_v1.primary_rank(row.title),
            )
        )
    return docs


# --- schema ---------------------------------------------------------------

def test_schema_file_is_valid_json_schema():
    """T05-01: state.v2.schema.json は draft 2020-12 の object で $defs を持つ。"""
    assert isinstance(SCHEMA, dict)
    assert SCHEMA["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert SCHEMA["type"] == "object"
    assert "state_completeness" in SCHEMA["$defs"]


def test_basic_design_example_is_valid():
    """T05-02: 基本設計 3.3 の例（省略記号を実値にしたもの）が schema で valid。"""
    example = {
        "issuer": {
            "company": "株式会社ほぼ日", "code": "3560",
            "market": "東証グロース", "role": "発行者",
        },
        "published_at": "2026-09-17T17:30:00+09:00",
        "market_context": {
            "prev_close": 4530, "market_cap_jpy": 11000000000,
            "return_20d_vs_topix": 0.021, "avg_turnover_20d_jpy": 45000000,
        },
        "forecast_context": {
            "prior_forecast": {"net_sales_jpy": 6000000000},
            "prev_year_actual": {"net_sales_jpy": 5800000000},
        },
        "recent_disclosures_30d": ["2026-08-29 自己株式の取得に関するお知らせ"],
        "same_time_disclosures": [
            "連結決算への移行に伴う2026年８月期連結業績予想の公表に関するお知らせ",
            "決算期（事業年度の末日）の変更及びこれに伴う定款の一部変更に関するお知らせ",
            "定款の一部変更（取締役の任期変更）に関するお知らせ",
        ],
        "primary": {"title": "業績予想の修正に関するお知らせ", "body": "（本文）"},
        "secondary": [
            {"title": "連結決算への移行に伴う…", "body": "（本文）"},
            {"title": "決算期（事業年度の末日）の変更…", "body": None},
        ],
        "other_titles": ["定款の一部変更（取締役の任期変更）に関するお知らせ"],
        "state_version": "v2",
    }
    assert_valid(example, SCHEMA)


# --- 形（ほぼ日） ----------------------------------------------------------

def test_hobonichi_state_shape(cfg, filters_v1):
    """T05-03: 4件の bundle が schema で valid になり、主開示以外が3件並ぶ。"""
    result = build(hobonichi_docs(filters_v1), cfg)
    assert validate(result.state, SCHEMA) == []
    state = result.state
    assert state["issuer"]["code"] == "3560"
    assert state["issuer"]["role"] == "発行者"
    assert state["published_at"] == "2026-09-17T17:30:00+09:00"
    assert len(state["same_time_disclosures"]) == 3
    assert state["primary"]["title"] == "業績予想の修正に関するお知らせ"


def test_display_code_is_four_chars(cfg, filters_v1):
    """T05-04: DB の5文字コードを state に持ち込まない。"""
    result = build(hobonichi_docs(filters_v1), cfg)
    assert result.state["issuer"]["code"] == "3560"
    assert "35600" not in result.state_json


def test_market_from_name_prefix(cfg, filters_v1):
    """T05-05: 段階1の issuer.market は TDnet の社名接頭辞から埋める（4.2）。"""
    raw = "Ｇ－ミンカブ"
    minkabu = build(
        [DocInput(title="資本業務提携に関するお知らせ", body="本文", rank=3)],
        cfg,
        code5="44360",
        company=filters_v1.strip_market_prefix(raw),
        market=filters_v1.market_of_company(raw),
    )
    assert minkabu.state["issuer"]["market"] == "東証グロース"
    assert minkabu.state["issuer"]["company"] == "ミンカブ"
    assert "issuer.market" not in minkabu.completeness["missing"]

    hobonichi = build(hobonichi_docs(filters_v1), cfg)   # 接頭辞なし
    assert hobonichi.state["issuer"]["market"] is None
    assert "issuer.market" in hobonichi.completeness["missing"]


def test_null_market_context_records_missing(cfg, filters_v1):
    """T05-06: 段階1は4項目とも null。キーは必ず置き、欠損として記録する。"""
    result = build(hobonichi_docs(filters_v1), cfg)
    market = result.state["market_context"]
    assert set(market) == set(MARKET_CONTEXT_KEYS)
    assert all(value is None for value in market.values())
    for key in MARKET_CONTEXT_KEYS:
        assert f"market_context.{key}" in result.completeness["missing"]
    assert result.completeness["sources"]["market_context"] == "null"


def test_recent_disclosures_excludes_same_minute(conn, cfg):
    """T05-07: 同時刻の開示は入れない（先読みと二重計上の防止。4.7）。"""
    anchor = parse_utc(HOBONICHI_AT)
    events = [
        synthetic(1, "同時刻の開示", code="35600", at=to_utc_str(anchor)),
        synthetic(2, "1分前の開示", code="35600", at=to_utc_str(anchor - timedelta(minutes=1))),
        synthetic(3, "31日前の開示", code="35600", at=to_utc_str(anchor - timedelta(days=31))),
    ]
    insert_events(conn, events)
    result = build(
        [DocInput(title="同時刻の開示", body="本文", rank=1)],
        cfg,
        disc=DbDisclosureContext(conn),
    )
    assert result.state["recent_disclosures_30d"] == ["2026-09-17 1分前の開示"]


# --- 論理開示の並び --------------------------------------------------------

def test_liberta_two_same_title_docs_in_state(cfg, filters_v1):
    """T05-09: 同一表題でも別の開示として本文を2つ並べる（ADR 004）。"""
    rows = pick(ROWS_17, "49350", "16:00")
    bodies = blocks("4935_liberta_3days_bundle.txt")[2:4]
    docs = [
        DocInput(title=row.title, body=body, rank=filters_v1.primary_rank(row.title))
        for row, body in zip(rows, bodies)
    ]
    result = build(docs, cfg, code5="49350", company="リベルタ")
    state = result.state
    assert state["primary"]["title"] == state["secondary"][0]["title"]
    assert state["primary"]["body"] != state["secondary"][0]["body"]
    assert state["other_titles"] == []
    assert validate(state, SCHEMA) == []


def test_secondary_bodies_capped_at_two(cfg):
    """T05-10: 全文を載せるのは max_secondary_bodies 件まで。残りは表題だけ。"""
    bodies = blocks("6497_hamai_3core.txt")
    docs = [
        DocInput(title=f"ハマイの開示{i}", body=bodies[i % len(bodies)], rank=i + 1)
        for i in range(5)
    ]
    result = build(docs, cfg, code5="64970", company="ハマイ")
    assert len(result.state["secondary"]) == cfg.state.max_secondary_bodies
    assert result.state["other_titles"] == ["ハマイの開示3", "ハマイの開示4"]


def test_sequence_docs_concatenated_in_order(cfg, filters_v1):
    """T05-25: 連番の本文は logical_docs の順（１／３→３／３）に連結する。"""
    rows = pick(ROWS_14, "95020", "08:00")
    parts = [f"（{i + 1}分割目の本文）" for i in range(len(rows))]
    stripped, _ = filters_v1.strip_sequence(rows[0].title)
    doc = DocInput(title=stripped, body=join_bodies(parts), rank=filters_v1.primary_rank(stripped))
    result = build([doc], cfg, code5="95020", company="中部電力")
    body = result.state["primary"]["body"]
    assert [body.index(part) for part in parts] == sorted(body.index(part) for part in parts)
    assert body.count("\n\n") >= 2


# --- 切り詰め -------------------------------------------------------------

def test_short_state_not_truncated(cfg, filters_v1):
    """T05-11: 予算内なら何もしない。"""
    result = build(hobonichi_docs(filters_v1), cfg)
    assert result.completeness["truncate"]["applied"] is False
    assert "truncated" not in result.flags
    assert result.state_chars == len(result.state_json)


def test_chubu_report_fits_budget(cfg, filters_v1):
    """T05-12: 283,113字の報告書でも送信 JSON が 40,000 字に収まる。"""
    result = _chubu_result(cfg, filters_v1)
    assert result.state_chars <= cfg.judge.max_state_chars
    assert len(json.dumps(result.state, ensure_ascii=False)) <= cfg.judge.max_state_chars
    assert "truncated" in result.flags


def test_chubu_excerpts_are_the_real_chapters(cfg, filters_v1):
    """T05-13: 抜粋は実物の章（原因分析・再発防止策の提言・結語）。"""
    result = _chubu_result(cfg, filters_v1)
    excerpts = result.state["primary"]["excerpts"]
    headings = [e["heading"] for e in excerpts]
    # 「第4 …地震動評価及び…認定した事実」は章題の末尾に語が無いので落ちる（task 026）
    assert headings == ["第6 原因分析", "第7 再発防止策の提言", "第8 結語"]
    body = {e["heading"]: e["text"] for e in excerpts}
    assert body["第6 原因分析"].startswith("中部電力は、上記第 4 のとおり")
    assert result.completeness["truncate"]["excerpt_headings"] == headings
    assert result.completeness["truncate"]["report_like"] is True


def test_chapter_heading_false_positives_rejected(cfg):
    """T05-14: 「第 1 回…」「第一原子力…」を見出しに数えない（4.5）。"""
    body = read_fixture("9502_chubu_report_full.txt")
    headings = [text for _, text in truncate.chapter_headings(body)]
    assert len(headings) == 8
    assert headings[0] == "第1 調査の概要" and headings[-1] == "第8 結語"
    for wrong in ("第 1 回", "第 624 回", "第一原子力", "第 6（"):
        assert not any(h.startswith(wrong) for h in headings)


def test_leopalace_bundle_truncated(cfg, filters_v1):
    """T05-15: 落とした secondary の本文の件数がレポートと一致する。"""
    parts = blocks("8848_leopalace_tob_target_bundle_full.txt")
    assert len(parts) == 4
    docs = [
        DocInput(title=f"レオパレスの開示{i}", body=part, rank=i + 1)
        for i, part in enumerate(parts)
    ]
    result = build(docs, cfg, code5="88480", company="レオパレス２１")
    assert result.state_chars <= cfg.judge.max_state_chars
    dropped = sum(1 for s in result.state["secondary"] if s["body"] is None)
    assert dropped == result.completeness["truncate"]["secondary_bodies_dropped"]
    assert dropped > 0


def test_truncate_is_not_report_like_for_press_release(cfg):
    """T05-16: スライド資料は報告書型ではない（excerpts を作らない）。"""
    body = read_fixture("9227_microwave_growth_plan.txt")
    assert len(body) < cfg.state.report_min_chars
    assert truncate.is_report_like(body, cfg.state) is False


def test_escaping_accounted_in_budget(cfg):
    """T05-17: エスケープで膨らむぶんを測り直す（1回の引き算で済ませない）。"""
    budget = 3000
    small = cfg.model_copy(
        update={"judge": cfg.judge.model_copy(update={"max_state_chars": budget})}
    )
    body = '"\n' * 1200                                   # 生は 2,400 字、JSON では約 4,800 字
    assert len(body) < budget
    result = build([DocInput(title="引用だらけの開示", body=body, rank=1)], small)
    assert len(json.dumps(result.state, ensure_ascii=False)) <= budget
    assert result.state_chars <= budget
    assert "truncated" in result.flags


def test_truncate_raises_when_not_converging(cfg):
    """T05-18: 外枠だけで超える予算なら JevfwdError（黙って送らない）。"""
    tiny = cfg.model_copy(
        update={"judge": cfg.judge.model_copy(update={"max_state_chars": 50})}
    )
    with pytest.raises(JevfwdError):
        build([DocInput(title="業績予想の修正に関するお知らせ", body="本文" * 100, rank=1)], tiny)


def test_formfeed_normalized(cfg):
    """T05-19: 改ページは空行にする（4.3）。"""
    result = build([DocInput(title="改ページのある開示", body="前\f後", rank=1)], cfg)
    body = result.state["primary"]["body"]
    assert "\f" not in body
    assert body == "前\n\n後"


def test_crlf_fixture_read_convention():
    """T05-20: fixture は read_text で読む（read_bytes().decode() だと \\r が残る）。"""
    path = FIXTURES / "9502_chubu_report_full.txt"
    assert len(path.read_text(encoding="utf-8")) == 283113
    assert len(path.read_bytes().decode("utf-8")) == 291498


def test_provisional_only_when_no_body(cfg, filters_v1):
    """T05-21: 本文が1件も無ければ暫定判定の印を付ける（ADR 015・024）。"""
    docs = [
        DocInput(title=row.title, body=None, rank=filters_v1.primary_rank(row.title))
        for row in pick(ROWS_17, "35600", "17:30")
    ]
    result = build(docs, cfg)
    assert "provisional_only" in result.flags
    assert result.state["primary"]["body"] == ""
    assert validate(result.state, SCHEMA) == []


def test_completeness_matches_schema_def(cfg, filters_v1):
    """T05-22: completeness は $defs/state_completeness で valid。"""
    result = build(hobonichi_docs(filters_v1), cfg)
    assert_valid(result.completeness, SCHEMA["$defs"]["state_completeness"])
    assert result.completeness["rules"]["state_version"] == "v2"
    assert result.completeness["rules"]["truncate_rev"] == truncate.TRUNCATE_REV


def test_state_json_is_stored_raw(cfg, filters_v1):
    """T05-23: state_json はキー順を変えずそのまま保存する（★6）。"""
    result = build(hobonichi_docs(filters_v1), cfg)
    assert result.state_chars == len(result.state_json)
    assert json.loads(result.state_json) == result.state
    assert json.dumps(result.state, ensure_ascii=False) == result.state_json


def test_empty_company_rejected(cfg):
    """T05-24: 社名が空なら問いの主語が作れない（ADR 002）。"""
    with pytest.raises(ValueError):
        build([DocInput(title="開示", body="本文", rank=1)], cfg, company="")


def _chubu_result(cfg, filters_v1):
    """中部電力の調査報告書を主開示にした state。"""
    rows = pick(ROWS_14, "95020", "08:00")
    stripped, _ = filters_v1.strip_sequence(rows[0].title)
    docs = [
        DocInput(
            title=stripped,
            body=read_fixture("9502_chubu_report_full.txt"),
            rank=filters_v1.primary_rank(stripped),
        ),
        DocInput(title="代表取締役の異動について", body="（短い本文）", rank=6),
    ]
    return build(
        docs, cfg, code5="95020", company="中部電力",
        anchor=jst_minute_to_utc_str("2026-09-14", "08:00"), session="pre_open",
    )
