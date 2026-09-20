"""04-束ね 8章の受入テスト（T04-01〜35）。

fixture の TDnet 一覧（TSV）から `EventView` を組み、`now` は常に引数で与える。
DB を使うテストは `db.migrate` した実ファイルに events を入れてから `run_once` を呼ぶ。
"""

import hashlib
import json
from datetime import timedelta

import pytest

from conftest import CONFIG_DIR, FIXTURES, load_tdnet_tsv, read_fixture, split_disclosures
from test_settings import CALENDAR_V1_SHA

from jevfwd import settings as settings_mod
from jevfwd.bundle import runner
from jevfwd.bundle.grouper import (
    Coverage,
    EventView,
    ExistingBundle,
    logical_docs_of,
    plan_bundles,
    primary_of,
    session_of,
)
from jevfwd.common.errors import ConfigError, JevfwdError
from jevfwd.common.timeutil import jst_minute_to_utc_str, parse_utc, to_utc_str
from jevfwd.store import db, queries, repo
from jevfwd.store.rows import NewEvent, NewStateVersion

LIST_17 = FIXTURES / "tdnet_list_2026-09-17.tsv"
LIST_14 = FIXTURES / "tdnet_list_2026-09-14_16.tsv"
ROWS_17 = load_tdnet_tsv(LIST_17)
ROWS_14 = load_tdnet_tsv(LIST_14)

EMPTY = Coverage(covered=frozenset(), bundles=())
UTC = "2026-09-17T08:30:00+00:00"


# --- ヘルパ ---------------------------------------------------------------

@pytest.fixture
def cfg():
    return settings_mod.load_settings(CONFIG_DIR / "settings.yaml")


@pytest.fixture
def filters_v1():
    return settings_mod.load_filters(CONFIG_DIR / "filters.v1.yaml")


@pytest.fixture
def calendar_v1():
    return settings_mod.load_calendar(CONFIG_DIR / "trading_calendar.v1.yaml")


@pytest.fixture
def conn(db_path):
    db.migrate(db_path)
    connection = db.connect(db_path)
    yield connection
    connection.close()


def pick(rows, code, time_, *, date_=None, contains=None):
    """一覧から (コード, 時刻) の行を一覧の並び順のまま取り出す。"""
    out = [r for r in rows if r.code == code and r.time == time_]
    if date_ is not None:
        out = [r for r in out if r.date == date_]
    if contains is not None:
        out = [r for r in out if contains in r.title]
    return out


def views(rows, *, start_id=1, lag_sec=30, pdf_status="ok"):
    """TSV の行を EventView にする。event_id は渡した順（到着順）に振る。"""
    out = []
    for offset, row in enumerate(rows):
        published = jst_minute_to_utc_str(row.date, row.time)
        received = to_utc_str(parse_utc(published) + timedelta(seconds=lag_sec))
        out.append(
            EventView(
                event_id=start_id + offset,
                code=row.code,
                company=row.company,
                title=row.title,
                published_at=published,
                received_at=received,
                pdf_status=pdf_status,
            )
        )
    return out


def synthetic(event_id, title, *, code="99990", company="テスト", at=UTC, lag_sec=30,
              pdf_status="ok"):
    return EventView(
        event_id=event_id,
        code=code,
        company=company,
        title=title,
        published_at=at,
        received_at=to_utc_str(parse_utc(at) + timedelta(seconds=lag_sec)),
        pdf_status=pdf_status,
    )


def settled(events, cfg, extra_sec=0):
    """全 event の猶予が明けた時刻。"""
    latest = max(parse_utc(e.received_at) for e in events)
    return latest + timedelta(seconds=cfg.bundle.grace_sec + extra_sec)


def title_of(events, event_id):
    return {e.event_id: e for e in events}[event_id].title


def insert_events(conn, events):
    """views の順に events へ追記する（event_id は採番順＝渡した順）。"""
    with db.transaction(conn):
        for e in events:
            repo.insert_event(
                conn,
                NewEvent(
                    code=e.code,
                    company=e.company,
                    title=e.title,
                    published_at=e.published_at,
                    received_at=e.received_at,
                    pdf_status=e.pdf_status,
                ),
            )


def bundle_rows(conn):
    return list(conn.execute("SELECT * FROM bundles ORDER BY bundle_id").fetchall())


def existing(bundle_id, code, anchor, event_ids, primary, *, role="normal",
             skip_reason=None, flags=(), depth=0, judged=False):
    return ExistingBundle(
        bundle_id=bundle_id,
        code=code,
        anchor_published_at=anchor,
        event_ids=frozenset(event_ids),
        primary_event_id=primary,
        bundle_role=role,
        skip_reason=skip_reason,
        flags=tuple(flags),
        supersede_depth=depth,
        has_full_judgment=judged,
    )


# --- fixture の読み取り ----------------------------------------------------

def test_tsv_loader_rejoins_wrapped_rows():
    """T04-01: XBRL で折り返された行を1件に戻して190件になる。"""
    assert len(ROWS_17) == 190
    wrapped = ROWS_17[7]                            # 一覧9行目（XBRL つき）
    assert (wrapped.time, wrapped.code, wrapped.company) == ("17:30", "35600", "ほぼ日")
    assert wrapped.title == "業績予想の修正に関するお知らせ"
    assert wrapped.xbrl is True


@pytest.mark.parametrize(
    "name,expected",
    [
        ("4935_liberta_3days_bundle.txt", 4),
        ("6497_hamai_3core.txt", 3),
        ("8894_revolution_3bundle.txt", 3),
    ],
)
def test_split_disclosures_on_fixtures(name, expected):
    """T04-02: 本文つき fixture が「各位」の1行前で正しく分かれる。"""
    parts = split_disclosures(read_fixture(name))
    assert len(parts) == expected
    for part in parts:
        assert "年" in part.splitlines()[0]          # 各件の先頭は日付行


# --- 猶予と窓 -------------------------------------------------------------

def test_grace_not_elapsed_yields_no_plan(cfg, filters_v1, calendar_v1):
    """T04-03: 猶予（120秒）が明けるまで計画を作らない。"""
    events = views(pick(ROWS_17, "35600", "17:30"))
    base = parse_utc(events[0].received_at)
    early = plan_bundles(events, EMPTY, base + timedelta(seconds=119), cfg, filters_v1, calendar_v1)
    assert early == []
    ready = plan_bundles(events, EMPTY, base + timedelta(seconds=120), cfg, filters_v1, calendar_v1)
    assert len(ready) == 1


def test_hobonichi_four_events_one_bundle(cfg, filters_v1, calendar_v1):
    """T04-04: 同一銘柄・同時刻の4件が1 bundle・4論理開示になる。"""
    events = views(pick(ROWS_17, "35600", "17:30"))
    plans = plan_bundles(events, EMPTY, settled(events, cfg), cfg, filters_v1, calendar_v1)
    assert len(plans) == 1
    plan = plans[0]
    assert plan.code == "35600"
    assert plan.event_ids == (1, 2, 3, 4)
    assert len(plan.logical_docs) == 4
    assert title_of(events, plan.primary_event_id) == "業績予想の修正に関するお知らせ"
    assert plan.session == "after_close"
    assert plan.bundle_role == "normal"
    assert plan.skip_reason is None


# --- 論理開示（連番） ------------------------------------------------------

def test_chubu_sequence_merges_into_one_logical_doc(cfg, filters_v1, calendar_v1):
    """T04-05: （１／３）〜（３／３）が1論理開示にまとまる。"""
    events = views(pick(ROWS_14, "95020", "08:00"))
    plans = plan_bundles(events, EMPTY, settled(events, cfg), cfg, filters_v1, calendar_v1)
    assert len(plans) == 1
    docs = plans[0].logical_docs
    assert len(docs) == 1
    assert docs[0].title.endswith("調査報告書の公表")
    assert docs[0].event_ids == (1, 2, 3)


def test_chubu_sequence_order_is_stable_when_out_of_order(cfg, filters_v1):
    """T04-06: 到着順が前後しても連結順は連番順のまま。"""
    rows = pick(ROWS_14, "95020", "08:00")
    shuffled = views([rows[2], rows[0], rows[1]])    # (3/3), (1/3), (2/3) の順に到着
    docs = logical_docs_of(shuffled, filters_v1)
    assert len(docs) == 1
    assert docs[0].event_ids == (2, 3, 1)


def test_sequence_total_mismatch_not_merged(cfg, filters_v1, calendar_v1):
    """T04-07: 連番の分母が食い違えば束ねず sequence_mismatch を付ける。"""
    events = [
        synthetic(1, "基準地震動に係る調査報告書の公表（１／３）"),
        synthetic(2, "基準地震動に係る調査報告書の公表（２／４）"),
    ]
    plans = plan_bundles(events, EMPTY, settled(events, cfg), cfg, filters_v1, calendar_v1)
    assert len(plans) == 1
    assert len(plans[0].logical_docs) == 2
    assert "sequence_mismatch" in plans[0].flags


def test_chubu_0800_is_pre_open(cfg, filters_v1, calendar_v1):
    """T04-08: 08:00 の開示は pre_open。"""
    events = views(pick(ROWS_14, "95020", "08:00"))
    plans = plan_bundles(events, EMPTY, settled(events, cfg), cfg, filters_v1, calendar_v1)
    assert plans[0].session == "pre_open"


def test_liberta_same_title_two_events_stay_separate(cfg, filters_v1, calendar_v1):
    """T04-09: 連番の無い同一表題は別の論理開示（ADR 004）。"""
    rows = pick(ROWS_17, "49350", "16:00")
    assert len(rows) == 2 and rows[0].title == rows[1].title
    events = views(rows)
    plans = plan_bundles(events, EMPTY, settled(events, cfg), cfg, filters_v1, calendar_v1)
    assert len(plans) == 1
    assert len(plans[0].logical_docs) == 2
    assert plans[0].session == "after_close"
    assert "sequence_mismatch" not in plans[0].flags


# --- 主開示 ---------------------------------------------------------------

def test_hamai_primary_is_forecast_revision(cfg, filters_v1, calendar_v1):
    """T04-10: 訂正6件・決算短信・意見不表明より業績予想の差異・修正が上位。"""
    events = views(pick(ROWS_14, "64970", "14:00"))
    assert len(events) == 10
    plans = plan_bundles(events, EMPTY, settled(events, cfg), cfg, filters_v1, calendar_v1)
    assert len(plans) == 1
    assert title_of(events, plans[0].primary_event_id) == (
        "2026年12月期第2四半期連結業績予想と実績との差異及び通期連結業績予想の修正に関するお知らせ"
    )
    assert plans[0].session == "intraday"


def test_primary_rank_total_order(filters_v1):
    """T04-34: rank は 予想修正 < 不祥事 < 資本政策 < 決算短信 < other < 訂正・事務。"""
    titles = [
        "業績予想の修正に関するお知らせ",
        "特別調査委員会の設置および委員選任に関するお知らせ",
        "資本業務提携に関するお知らせ",
        "2026年12月期第2四半期（中間期）決算短信〔日本基準〕（連結）",
        "株主優待制度の新設に関するお知らせ",          # どの patterns にも一致しない
        "臨時株主総会招集のための基準日設定に関するお知らせ",   # 訂正・事務（task 022）
    ]
    ranks = [filters_v1.primary_rank(t) for t in titles]
    assert ranks == sorted(ranks) and len(set(ranks)) == len(ranks)
    assert filters_v1.primary_rank(titles[5]) == 6      # other（5）ではない
    # 同順位は published_at → event_id
    same = [synthetic(2, titles[0]), synthetic(1, titles[0], at=UTC)]
    docs = logical_docs_of(same, filters_v1)
    assert primary_of(docs, {e.event_id: e for e in same}) == 1


# --- TOB ------------------------------------------------------------------

def test_leopalace_tob_split(cfg, filters_v1, calendar_v1):
    """T04-11: 対象者側 TOB を単独 bundle にし、残りを tob_attached にする。"""
    events = views(pick(ROWS_14, "88480", "20:00"))
    assert len(events) == 3
    plans = plan_bundles(events, EMPTY, settled(events, cfg), cfg, filters_v1, calendar_v1)
    assert [p.bundle_role for p in plans] == ["tob_primary", "tob_attached"]
    assert plans[0].event_ids == (1,)
    assert plans[1].event_ids == (2, 3)
    # 無配も事業譲渡も rank 1（forecast_revision）なので event_id の小さい方（task 023）
    assert title_of(events, plans[1].primary_event_id).startswith("2027年３月期の中間配当")
    assert plans[0].supersedes_id is None and plans[1].supersedes_id is None


def test_ferrotec_buyer_side_stays_normal(cfg, filters_v1, calendar_v1):
    """T04-12: 買付者側は束ね例外を適用せず normal + tob_buyer。"""
    events = views(pick(ROWS_17, "68900", "16:00"))
    plans = plan_bundles(events, EMPTY, settled(events, cfg), cfg, filters_v1, calendar_v1)
    assert len(plans) == 1
    assert plans[0].bundle_role == "normal"
    assert "tob_buyer" in plans[0].flags


def test_nihon_teikoki_target_side_is_tob_primary(cfg, filters_v1, calendar_v1):
    """T04-13: 対象者側（賛同の表明・応募推奨）は tob_primary。"""
    events = views(pick(ROWS_17, "69770", "16:00"))
    plans = plan_bundles(events, EMPTY, settled(events, cfg), cfg, filters_v1, calendar_v1)
    assert plans[0].bundle_role == "tob_primary"
    assert title_of(events, plans[0].primary_event_id).endswith("賛同の表明及び応募推奨のお知らせ")
    assert plans[1].bundle_role == "tob_attached"    # 同時刻の無配
    assert "tob_buyer" not in plans[0].flags


def test_minkabu_tob_false_positive_excluded(cfg, filters_v1, calendar_v1):
    """T04-14: 「公開買付けに準ずる行為」は TOB として扱わない。"""
    events = views(pick(ROWS_17, "44360", "17:00"))
    assert len(events) == 8
    plans = plan_bundles(events, EMPTY, settled(events, cfg), cfg, filters_v1, calendar_v1)
    assert len(plans) == 1
    assert plans[0].bundle_role == "normal"
    assert "tob_buyer" not in plans[0].flags
    # rank 1（予想修正）が rank 3（資本業務提携）より上（task 023）
    assert title_of(events, plans[0].primary_event_id).startswith("通期連結業績予想の修正")


# --- 除外・重要度低下 ------------------------------------------------------

def test_one_etf_excluded_by_title(cfg, filters_v1, calendar_v1):
    """T04-15: 社名接頭辞にもコードにも掛からない ETF を表題で除外する。"""
    rows = pick(ROWS_17, "13690", "15:30")
    assert len(rows) == 1
    assert not filters_v1.has_excluded_name_prefix(rows[0].company)
    assert not filters_v1.code_excluded(rows[0].code)
    assert rows[0].title in read_fixture("1369_one_etf_terms.txt")
    events = views(rows)
    plans = plan_bundles(events, EMPTY, settled(events, cfg), cfg, filters_v1, calendar_v1)
    assert plans[0].bundle_role == "excluded"
    assert plans[0].skip_reason == "excluded_title"


def test_etf_code_and_prefix_excluded(cfg, filters_v1, calendar_v1):
    """T04-16: 5文字目 4 のコードと Ｒ－ の社名接頭辞は excluded_instrument。"""
    rows = pick(ROWS_14, "13264", "12:15", date_="2026-09-16") + pick(ROWS_14, "89600", "16:00")
    assert len(rows) == 2
    events = views(rows)
    plans = plan_bundles(events, EMPTY, settled(events, cfg), cfg, filters_v1, calendar_v1)
    assert len(plans) == 2
    assert {p.bundle_role for p in plans} == {"excluded"}
    assert {p.skip_reason for p in plans} == {"excluded_instrument"}


def test_partial_title_exclusion_does_not_exclude_bundle(cfg, filters_v1, calendar_v1):
    """T04-17: 表題での除外は全論理開示が一致したときだけ（4.5 の 3）。"""
    events = [
        synthetic(1, "投資信託約款の変更に関するお知らせ"),
        synthetic(2, "業績予想の修正に関するお知らせ"),
    ]
    plans = plan_bundles(events, EMPTY, settled(events, cfg), cfg, filters_v1, calendar_v1)
    assert len(plans) == 1
    assert plans[0].bundle_role == "normal"
    assert plans[0].skip_reason is None


def test_microwave_low_priority_flag(cfg, filters_v1, calendar_v1):
    """T04-18: 成長可能性資料は判定するが low_priority:growth_plan を付ける。"""
    rows = pick(ROWS_17, "92270", "17:30")
    assert len(rows) == 1
    assert read_fixture("9227_microwave_growth_plan.txt").splitlines()[0] == rows[0].title
    events = views(rows)
    plans = plan_bundles(events, EMPTY, settled(events, cfg), cfg, filters_v1, calendar_v1)
    assert plans[0].bundle_role == "normal"
    assert "low_priority:growth_plan" in plans[0].flags


def test_revolution_not_excluded_in_stage1(cfg, filters_v1, calendar_v1):
    """T04-19: 段階1では特別注意銘柄を除外しない（listed_master は M6。4.6）。"""
    rows = pick(ROWS_17, "88940", "16:00")
    assert len(rows) == 3
    assert rows[0].title in read_fixture("8894_revolution_3bundle.txt")
    events = views(rows)
    plans = plan_bundles(events, EMPTY, settled(events, cfg), cfg, filters_v1, calendar_v1)
    assert len(plans) == 1
    assert plans[0].bundle_role == "normal"
    assert plans[0].skip_reason is None


# --- session とカレンダー ---------------------------------------------------

@pytest.mark.parametrize(
    "day,hhmm,expected",
    [
        ("2026-09-17", "17:30", "after_close"),
        ("2026-09-14", "08:00", "pre_open"),
        ("2026-09-14", "14:00", "intraday"),
        ("2026-09-19", "08:30", "after_close"),      # 土曜
        ("2026-09-23", "10:00", "after_close"),      # 秋分の日
    ],
)
def test_session_five_cases(cfg, calendar_v1, day, hhmm, expected):
    """T04-20: 非営業日を先に見るので土曜 08:30 は pre_open にならない。"""
    assert session_of(jst_minute_to_utc_str(day, hhmm), cfg.market, calendar_v1) == expected


def test_calendar_without_holidays_misclassifies(cfg):
    """T04-21: 祝日表が無いと秋分の日が intraday になる（版付き表が要る理由）。"""
    naive = settings_mod.Calendar(version="test", years=[2026], holidays={2026: []})
    assert session_of(jst_minute_to_utc_str("2026-09-23", "10:00"), cfg.market, naive) == "intraday"


def test_calendar_out_of_range_raises(calendar_v1):
    """T04-22: 収録年の外は黙って平日扱いにせず ConfigError。"""
    from datetime import date

    with pytest.raises(ConfigError):
        calendar_v1.is_business_day(date(2028, 1, 4))


def test_calendar_yaml_sha256_frozen():
    """T04-23: trading_calendar.v1.yaml は作成後に変更しない。"""
    sha = hashlib.sha256((CONFIG_DIR / "trading_calendar.v1.yaml").read_bytes()).hexdigest()
    assert sha == CALENDAR_V1_SHA


# --- 仕掛かりと作り直し ----------------------------------------------------

def test_coverage_prevents_rebundling_on_restart(conn, cfg, filters_v1, calendar_v1):
    """T04-24: 確定済みの events は再起動しても再束ねされない（4.9-1）。"""
    events = views(pick(ROWS_17, "35600", "17:30"))
    insert_events(conn, events)
    now = settled(events, cfg)
    assert len(runner.run_once(conn, now, cfg, filters_v1, calendar_v1, lambda p: None)) == 1
    coverage = runner.load_coverage(conn, now, cfg)
    assert coverage.covered == frozenset({1, 2, 3, 4})
    assert plan_bundles(events, coverage, now, cfg, filters_v1, calendar_v1) == []


def test_late_event_supersedes_when_primary_changes(conn, cfg, filters_v1, calendar_v1):
    """T04-25: 主開示が変わる遅れ到着は superseding bundle になる（4.9-2b）。"""
    rows = pick(ROWS_17, "35600", "17:30")
    first = views(rows[1:])                          # 予想修正を除いた3件
    insert_events(conn, first)
    now1 = settled(first, cfg)
    old_ids = runner.run_once(conn, now1, cfg, filters_v1, calendar_v1, lambda p: None)
    assert len(old_ids) == 1

    late = views([rows[0]], start_id=4, lag_sec=200)  # 業績予想の修正が遅れて到着
    insert_events(conn, late)
    now2 = settled(late, cfg)
    new_ids = runner.run_once(conn, now2, cfg, filters_v1, calendar_v1, lambda p: None)
    assert len(new_ids) == 1

    new_row = conn.execute("SELECT * FROM bundles WHERE bundle_id = ?", (new_ids[0],)).fetchone()
    assert new_row["supersedes_id"] == old_ids[0]
    assert new_row["primary_event_id"] == 4
    assert json.loads(new_row["event_ids_json"]) == [1, 2, 3, 4]
    assert queries.current_bundle(conn, old_ids[0])["bundle_id"] == new_ids[0]


def test_late_event_without_meaning_change_is_independent(conn, cfg, filters_v1, calendar_v1):
    """T04-26: 意味が変わらない遅れ到着は独立 bundle ＋ late_arrival（4.9-2）。"""
    rows = pick(ROWS_17, "35600", "17:30")
    first = views(rows[:3])                          # 予想修正を含む3件
    insert_events(conn, first)
    runner.run_once(conn, settled(first, cfg), cfg, filters_v1, calendar_v1, lambda p: None)

    late = views([rows[3]], start_id=4, lag_sec=200)  # 定款の一部変更（rank 6）
    insert_events(conn, late)
    new_ids = runner.run_once(
        conn, settled(late, cfg), cfg, filters_v1, calendar_v1, lambda p: None
    )
    assert len(new_ids) == 1
    row = conn.execute("SELECT * FROM bundles WHERE bundle_id = ?", (new_ids[0],)).fetchone()
    assert row["supersedes_id"] is None
    assert "late_arrival" in json.loads(row["flags_json"])
    assert json.loads(row["event_ids_json"]) == [4]


def test_supersede_deadline_and_depth(cfg, filters_v1, calendar_v1):
    """T04-27: 期限切れと深さ超過はどちらも独立 bundle（4.9-3・4.9-4）。"""
    prev_events = [synthetic(1, "業績予想の修正に関するお知らせ")]
    late = synthetic(2, "資本業務提携に関するお知らせ", lag_sec=40)
    coverage = Coverage(
        covered=frozenset({1}),
        bundles=(existing(10, "99990", UTC, {1}, 1),),
    )
    over_deadline = parse_utc(UTC) + timedelta(seconds=cfg.bundle.supersede_deadline_sec + 1)
    plans = plan_bundles(
        prev_events + [late], coverage, over_deadline, cfg, filters_v1, calendar_v1
    )
    assert len(plans) == 1
    assert plans[0].supersedes_id is None
    assert "late_arrival" in plans[0].flags
    assert "supersede_capped" not in plans[0].flags

    deep = Coverage(
        covered=frozenset({1}),
        bundles=(existing(10, "99990", UTC, {1}, 1, depth=cfg.bundle.max_supersede_depth),),
    )
    in_time = parse_utc(late.received_at) + timedelta(seconds=cfg.bundle.grace_sec)
    plans = plan_bundles(prev_events + [late], deep, in_time, cfg, filters_v1, calendar_v1)
    assert len(plans) == 1
    assert plans[0].supersedes_id is None
    assert "supersede_capped" in plans[0].flags


def test_provisional_pdf_arrival_supersedes(cfg, filters_v1, calendar_v1):
    """T04-28: 表題のみの bundle に本文つき event が届いたら作り直す（4.8）。"""
    title = "業績予想の修正に関するお知らせ"
    provisional = synthetic(1, title, pdf_status="failed")
    full = synthetic(2, title, lag_sec=90)
    coverage = Coverage(
        covered=frozenset({1}),
        bundles=(existing(10, "99990", UTC, {1}, 1, flags=("event_note:表題のみ", "catchup")),),
    )
    now = parse_utc(UTC) + timedelta(seconds=cfg.bundle.grace_sec + 90)
    plans = plan_bundles([provisional, full], coverage, now, cfg, filters_v1, calendar_v1)
    assert len(plans) == 1
    assert plans[0].supersedes_id == 10
    assert plans[0].event_ids == (1, 2)
    assert "supersedes:provisional" in plans[0].flags
    assert "event_note:表題のみ" in plans[0].flags     # 人の注記は引き継ぐ（ADR 027）
    assert "catchup" not in plans[0].flags             # その周期の事実は引き継がない


def test_catchup_flag_on_backlog(cfg, filters_v1, calendar_v1):
    """T04-29: 公表から grace_sec × catchup_factor を過ぎた確定は catchup。"""
    now = parse_utc(UTC) + timedelta(hours=2)
    event = EventView(
        event_id=1, code="99990", company="テスト",
        title="業績予想の修正に関するお知らせ",
        published_at=UTC,
        received_at=to_utc_str(now - timedelta(seconds=130)),
        pdf_status="ok",
    )
    plans = plan_bundles([event], EMPTY, now, cfg, filters_v1, calendar_v1)
    assert len(plans) == 1
    assert "catchup" in plans[0].flags


def test_max_per_cycle_caps_plans(cfg, filters_v1, calendar_v1):
    """T04-30: 1周期で確定させるのは max_per_cycle 件まで。"""
    events = [
        synthetic(i + 1, "業績予想の修正に関するお知らせ", code=f"{1000 + i}0")
        for i in range(300)
    ]
    plans = plan_bundles(events, EMPTY, settled(events, cfg), cfg, filters_v1, calendar_v1)
    assert len(plans) == cfg.bundle.max_per_cycle


def test_version_flags_recorded(cfg, filters_v1, calendar_v1):
    """T04-31: どの版の規則で分類したかを flags に残す。"""
    events = views(pick(ROWS_17, "35600", "17:30"))
    plans = plan_bundles(events, EMPTY, settled(events, cfg), cfg, filters_v1, calendar_v1)
    assert "filters:v1" in plans[0].flags
    assert "calendar:v1" in plans[0].flags


# --- run_once -------------------------------------------------------------

def test_run_once_inserts_and_is_idempotent(conn, cfg, filters_v1, calendar_v1):
    """T04-32: 2回呼んでも bundles の行は増えない（state 列は NULL）。"""
    events = views(pick(ROWS_17, "35600", "17:30"))
    insert_events(conn, events)
    now = settled(events, cfg)
    first = runner.run_once(conn, now, cfg, filters_v1, calendar_v1, lambda p: None)
    assert len(first) == 1
    row = bundle_rows(conn)[0]
    assert row["state_json"] is None and row["state_version"] is None
    assert row["state_chars"] is None and row["state_completeness_json"] is None

    second = runner.run_once(conn, now, cfg, filters_v1, calendar_v1, lambda p: None)
    assert second == []
    assert queries.count_rows(conn, "bundles") == 1


def test_run_once_reports_stuck_events(conn, cfg, filters_v1, calendar_v1):
    """T04-33: 滞留した未カバー event は heartbeat(ok=0) に残す。"""
    slow = cfg.model_copy(
        update={"bundle": cfg.bundle.model_copy(update={"max_per_cycle": 1})}
    )
    events = [
        synthetic(1, "業績予想の修正に関するお知らせ", code="99990"),
        synthetic(2, "業績予想の修正に関するお知らせ", code="99980"),
    ]
    insert_events(conn, events)
    now = parse_utc(events[0].received_at) + timedelta(
        seconds=cfg.bundle.grace_sec + cfg.bundle.stuck_margin_sec + 1
    )
    ids = runner.run_once(conn, now, slow, filters_v1, calendar_v1, lambda p: None)
    assert len(ids) == 1
    beats = queries.recent_heartbeat(conn, "bundler", limit=3)
    assert len(beats) == 1
    assert beats[0]["ok"] == 0
    assert beats[0]["queue_depth"] >= 1
    assert "bundler stuck" in beats[0]["note"]


class StubState:
    """05-state構築 の StateResult の代用（この時点では state/ は未実装）。"""

    def __init__(self, state_json, state_chars, completeness, flags):
        self.state_json = state_json
        self.state = json.loads(state_json)
        self.state_chars = state_chars
        self.completeness = completeness
        self.flags = flags


def test_run_once_stores_injected_state_and_survives_state_error(
    conn, cfg, filters_v1, calendar_v1
):
    """T04-35: 注入された state を保存し、失敗しても行は残す（task 017）。"""
    with db.transaction(conn):
        repo.insert_state_version(
            conn,
            NewStateVersion(version="v2", spec="{}", sha256="0" * 64, frozen_at=UTC),
        )
    hobonichi = views(pick(ROWS_17, "35600", "17:30"))
    etf = views(pick(ROWS_17, "13690", "15:30"), start_id=5)
    leopalace = views(pick(ROWS_14, "88480", "20:00"), start_id=6)
    insert_events(conn, leopalace)                   # 公表順（09-14 → 09-17）に入れる
    insert_events(conn, etf)
    insert_events(conn, hobonichi)

    seen = []

    def state_of(plan):
        seen.append(plan.code)
        if plan.code == "88480":
            raise JevfwdError("切り詰めが収束しない")
        return StubState('{"x":1}', 7, {"issuer": True}, ("truncated",))

    now = parse_utc(hobonichi[0].received_at) + timedelta(seconds=cfg.bundle.grace_sec)
    ids = runner.run_once(conn, now, cfg, filters_v1, calendar_v1, state_of)
    assert len(ids) == 4                             # ほぼ日・ETF・TOB 2件

    assert seen.count("13690") == 0                  # excluded では呼ばない
    assert seen.count("35600") == 1
    assert seen.count("88480") == 2                  # tob_primary と tob_attached

    rows = {r["code"]: r for r in bundle_rows(conn) if r["code"] != "88480"}
    hobo = rows["35600"]
    assert hobo["state_json"] == '{"x":1}'
    assert hobo["state_version"] == "v2"
    assert hobo["state_chars"] == 7
    assert "truncated" in json.loads(hobo["flags_json"])
    assert json.loads(hobo["state_completeness_json"]) == {"issuer": True}

    assert rows["13690"]["state_json"] is None       # excluded は state を持たない

    failed = [r for r in bundle_rows(conn) if r["code"] == "88480"]
    assert len(failed) == 2
    for row in failed:
        assert row["state_json"] is None and row["state_version"] is None
        assert "state_error:JevfwdError" in json.loads(row["flags_json"])
