"""02-設定 8.1 の受入テスト（T02-01〜23、T02-35〜41）。"""

import hashlib
import json
from datetime import date, time
from pathlib import Path

import pytest
import yaml

from conftest import CONFIG_DIR, CONTRACTS_DIR, FIXTURES, load_tdnet_tsv, read_fixture
from jevfwd.common.errors import ConfigError
from jevfwd.settings import (
    Calendar,
    Secrets,
    Settings,
    load_calendar,
    load_entry_rules,
    load_filters,
    load_settings,
    resolve_settings_path,
)

# 版つきファイルの SHA-256（2026-09-20 に作成直後へ記録。以後このファイルは変更しない。02-設定 4.7）
ENTRY_RULES_V1_SHA = "71a93088e9ba5bcb9398eae27991277d0b16af9ac6684c8f799ba395cb0cdf36"
FILTERS_V1_SHA = "97cde499211804b4006b25786bae963f44524dca4d71995f11f0f0145ad86420"
CALENDAR_V1_SHA = "7d90c803d386ebedaf37e6a96efccdabd22c1b21f49e273e3af748ed88e25f7a"

LIST_0917 = FIXTURES / "tdnet_list_2026-09-17.tsv"
LIST_0914 = FIXTURES / "tdnet_list_2026-09-14_16.tsv"


@pytest.fixture(scope="module")
def filters():
    return load_filters(CONFIG_DIR / "filters.v1.yaml")


@pytest.fixture(scope="module")
def calendar():
    return load_calendar(CONFIG_DIR / "trading_calendar.v1.yaml")


def _title(path: Path, needle: str, code: str | None = None) -> str:
    """fixture の一覧から表題を1つ取る（行番号ではなく内容で引く）。"""
    for row in load_tdnet_tsv(path):
        if needle in row.title and (code is None or row.code == code):
            return row.title
    raise AssertionError(f"{path.name} に {needle!r}（code={code}）が無い")


def _write(path: Path, data: dict) -> Path:
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return path


# --- settings.yaml --------------------------------------------------------

def test_settings_yaml_loads_with_documented_values():
    """T02-01: リポジトリの settings.yaml が読め、文書どおりの値になる。"""
    s = load_settings(CONFIG_DIR / "settings.yaml")
    assert s.judge.delayed_threshold_sec == 300
    assert s.bundle.grace_sec == 120
    assert s.digest.runs == ["18:30", "07:30"]
    assert s.market_cache.enabled is False
    assert s.storage.db_path == "data/db/jevfwd.sqlite"


def test_settings_defaults_equal_repo_file():
    """T02-02: 既定値と運用ファイルを一致させておく。"""
    assert Settings() == load_settings(CONFIG_DIR / "settings.yaml")


def test_settings_unknown_key_rejected_with_path(tmp_path):
    """T02-03: 未知のキーはキーのパス付きで拒否する。"""
    path = _write(tmp_path / "settings.yaml", {"market": {"sesion_open": "09:00"}})
    with pytest.raises(ConfigError, match=r"market\.sesion_open"):
        load_settings(path)


def test_settings_missing_nested_key_uses_default(tmp_path):
    """T02-04: 入れ子の一部だけ書いても残りは既定値。"""
    path = _write(tmp_path / "settings.yaml", {"judge": {"timeout_sec": 5}})
    s = load_settings(path)
    assert s.judge.timeout_sec == 5
    assert s.judge.retries == 3


def test_unquoted_hhmm_rejected(tmp_path):
    """T02-05: クォートしない 18:30 は 60進数の int になるので弾く。"""
    path = tmp_path / "settings.yaml"
    path.write_text('digest:\n  runs: [18:30, "07:30"]\n', encoding="utf-8")
    assert yaml.safe_load(path.read_text(encoding="utf-8"))["digest"]["runs"][0] == 1110
    with pytest.raises(ConfigError) as err:
        load_settings(path)
    assert "digest.runs.0" in str(err.value) and "クォート" in str(err.value)


def test_hhmm_pattern_enforced(tmp_path):
    """T02-06: 'HH:MM' の形（1桁の時は不可）。"""
    path = _write(tmp_path / "settings.yaml", {"market": {"session_open": "9:00"}})
    with pytest.raises(ConfigError, match=r"\\d\{2\}:\\d\{2\}"):
        load_settings(path)


def test_resolve_settings_path_precedence():
    """T02-07: --config > $JEVFWD_CONFIG > config/settings.yaml。"""
    env = {"JEVFWD_CONFIG": "/y/b.yaml"}
    assert resolve_settings_path("/x/a.yaml", env) == Path("/x/a.yaml")
    assert resolve_settings_path(None, env) == Path("/y/b.yaml")
    assert resolve_settings_path(None, {}) == Path("config/settings.yaml")


def test_missing_settings_file_raises(tmp_path):
    """T02-08: 無いファイルはパス付きで ConfigError。"""
    missing = tmp_path / "none.yaml"
    with pytest.raises(ConfigError, match="none.yaml"):
        load_settings(missing)


# --- entry_rules ----------------------------------------------------------

def test_entry_rules_v1_values():
    """T02-09: 事前宣言の数値がそのまま入っている（ADR 005・006・011・012）。"""
    r = load_entry_rules(CONFIG_DIR / "entry_rules.v1.yaml")
    assert r.entry.direction_up_min == 0.80
    assert r.entry.confidence_min == 0.60
    assert r.entry.market_cap_max_jpy == 100_000_000_000
    assert r.entry.avg_turnover_20d_min_jpy == 100_000_000
    assert r.entry.pre_return_20d_vs_topix_max == 0.10
    assert r.entry.max_new_positions_per_day == 3
    assert r.exit.time_exit_days == 20
    assert r.exit.stop_loss == -0.08
    assert r.exit.day1_fade == "record_only"
    assert r.sizing.position_pct == 0.05
    assert r.sizing.max_positions == 10
    assert r.cost.commission_roundtrip == 0.001
    assert r.cost.slippage == 0.002


def test_version_must_match_filename(tmp_path):
    """T02-10: ファイル名の版と中の version が食い違ったら読まない。"""
    body = (CONFIG_DIR / "entry_rules.v1.yaml").read_text(encoding="utf-8")
    as_v2 = tmp_path / "entry_rules.v2.yaml"
    as_v2.write_text(body, encoding="utf-8")
    with pytest.raises(ConfigError, match="v1"):
        load_entry_rules(as_v2)
    unversioned = tmp_path / "rules.yaml"
    unversioned.write_text(body, encoding="utf-8")
    with pytest.raises(ConfigError):
        load_entry_rules(unversioned)


# --- filters --------------------------------------------------------------

def test_filters_v1_regexes_compile(filters):
    """T02-11: filters.v1.yaml が読め、全パターンがコンパイルできる。"""
    assert filters.exclude_name_prefixes == ["Ｅ－", "Ｎ－", "Ｒ－", "Ｉ－"]
    assert filters.tob_titles == ["公開買付", "ＭＢＯ", "MBO", "株式交換"]


def test_filters_invalid_regex_rejected(tmp_path):
    """T02-12: 壊れた正規表現は読み込み時に場所つきで落とす。"""
    data = yaml.safe_load((CONFIG_DIR / "filters.v1.yaml").read_text(encoding="utf-8"))
    data["exclude_titles"] = ["("]
    path = _write(tmp_path / "filters.v1.yaml", data)
    with pytest.raises(ConfigError, match=r"exclude_titles\[0\]"):
        load_filters(path)


def test_title_excluded_one_etf_and_tdnet_daily(filters):
    """T02-13: 約款変更・収益分配金・日々の開示事項は判定しない。"""
    terms = read_fixture("1369_one_etf_terms.txt").splitlines()[7].strip()
    assert filters.title_excluded(terms) is True
    assert filters.title_excluded(_title(LIST_0914, "収益分配金")) is True
    assert filters.title_excluded(_title(LIST_0914, "日々の開示事項")) is True
    assert filters.title_excluded("借入に関するお知らせ") is False


def test_title_low_priority_growth_plan(filters):
    """T02-14: 成長可能性・CG報告書は重要度低下（除外ではない）。"""
    growth = read_fixture("9227_microwave_growth_plan.txt").splitlines()[0].strip()
    assert growth == "事業計画及び成長可能性に関する事項"
    assert filters.title_low_priority(growth) is True
    assert filters.title_excluded(growth) is False
    assert filters.title_low_priority("コーポレート・ガバナンスに関する報告書") is True
    assert filters.title_low_priority("業績予想の修正に関するお知らせ") is False


def test_title_is_tob_on_three_fixtures(filters):
    """T02-15: 公開買付・株式交換を拾い、決算期変更は拾わない。"""
    for needle, path in [
        ("公開買付けの開始", LIST_0917),          # フェローテック（買付者側）
        ("賛同の意見表明", LIST_0914),            # レオパレス（対象者側）
        ("賛同の表明", LIST_0917),                # 日本抵抗器製作所（対象者側）
        ("株式交換比率の決定", LIST_0917),
    ]:
        assert filters.title_is_tob(_title(path, needle)) is True, needle
    hobonichi = read_fixture("3560_hobonichi_fiscal_year_change.txt").splitlines()[7].strip()
    assert "決算期" in hobonichi
    assert filters.title_is_tob(hobonichi) is False


def test_strip_sequence_on_chubu_three_parts(filters):
    """T02-16: 連番（１／３）を表題末尾から外す。全角・半角・【1】・（その２）。"""
    parts = [r.title for r in load_tdnet_tsv(LIST_0914)
             if r.code == "95020" and "調査報告書の公表" in r.title]
    assert len(parts) == 3
    stripped = {filters.strip_sequence(t)[0] for t in parts}
    assert len(stripped) == 1
    assert stripped.pop().endswith("調査報告書の公表")
    assert [filters.strip_sequence(t)[1] for t in parts] == ["（１／３）", "（２／３）", "（３／３）"]
    assert filters.strip_sequence("調査報告書の公表(2/3)")[1] == "(2/3)"
    assert filters.strip_sequence("資料【1】")[1] == "【1】"
    assert filters.strip_sequence("説明資料（その２）")[1] == "（その２）"
    assert filters.strip_sequence("借入に関するお知らせ") == ("借入に関するお知らせ", None)


def test_name_prefix_and_code_patterns_on_tdnet_list(filters):
    """T02-17: 社名接頭辞とコードで除外・市場区分を判定する。"""
    assert filters.strip_market_prefix("Ｇ－エネチェンジ") == "エネチェンジ"
    assert filters.has_excluded_name_prefix("Ｇ－エネチェンジ") is False
    assert filters.has_excluded_name_prefix("Ｒ－ユナイテド") is True
    assert filters.code_excluded("13264") is True
    assert filters.code_excluded("41690") is False
    assert filters.code_excluded("590A0") is False


def test_versioned_yaml_sha256_frozen():
    """T02-18: 版つき YAML は作成後に変更しない（SHA-256 で検知）。"""
    for name, expected in [
        ("entry_rules.v1.yaml", ENTRY_RULES_V1_SHA),
        ("filters.v1.yaml", FILTERS_V1_SHA),
    ]:
        assert hashlib.sha256((CONFIG_DIR / name).read_bytes()).hexdigest() == expected, name


def test_filters_primary_rank_order(filters):
    """T02-35: 主開示の優先順（業績予想 < 不祥事 < 資本政策 < 決算短信 < 未知 < 訂正）。"""
    forecast = _title(LIST_0917, "業績予想の修正")
    misconduct = _title(LIST_0914, "調査報告書の公表")
    capital = _title(LIST_0917, "資本業務提携")
    earnings = _title(LIST_0914, "決算短信")
    unknown = "臨時株主総会招集のための基準日設定に関するお知らせ"
    correction = _title(LIST_0914, "定款の一部変更")
    ranks = [filters.primary_rank(t) for t in (forecast, misconduct, capital, earnings)]
    assert ranks == [1, 2, 3, 4]
    assert filters.primary_rank(unknown) == 6      # 「基準日設定」は correction のパターン
    assert filters.primary_rank("株主優待制度の新設に関するお知らせ") == filters.default_rank == 5
    assert filters.primary_rank(correction) == 6


def test_filters_tob_target_vs_buyer(filters):
    """T02-36: 束ね例外は対象者側だけ。誤検知は打ち消す（ADR 023）。"""
    buyer = _title(LIST_0917, "公開買付けの開始", code="68900")       # フェローテック
    target_a = _title(LIST_0917, "賛同の表明", code="69770")          # 日本抵抗器製作所
    target_b = _title(LIST_0914, "賛同の意見表明", code="88480")      # レオパレス
    assert filters.title_is_tob_target(buyer) is False
    assert filters.title_is_tob(buyer) is True
    assert filters.title_is_tob_target(target_a) is True
    assert filters.title_is_tob_target(target_b) is True
    minkabu = _title(LIST_0917, "準ずる行為", code="44360")
    kakaku = _title(LIST_0914, "一部変更に関するお知らせ", code="46890")
    assert filters.title_is_tob(minkabu) is False
    assert filters.title_is_tob(kakaku) is False


def test_filters_market_map(filters):
    """T02-37: 市場区分は社名接頭辞から。表に無い接頭辞は None。"""
    assert filters.market_of_company("Ｇ－エネチェンジ") == "東証グロース"
    assert filters.market_of_company("Ｒ－ユナイテド") is None
    assert filters.market_of_company("ほぼ日") is None


def test_low_priority_key(filters):
    """T02-38: low_priority のキーはリストの順で growth_plan / cg_report。"""
    assert filters.low_priority_key("事業計画及び成長可能性に関する事項") == "growth_plan"
    assert filters.low_priority_key("コーポレート・ガバナンスに関する報告書") == "cg_report"
    assert filters.low_priority_key("業績予想の修正に関するお知らせ") is None


# --- カレンダー -----------------------------------------------------------

def test_calendar_v1_business_days(calendar):
    """T02-39: 土日と祝日を休みにする（2026-09-22 は国民の休日）。"""
    assert calendar.is_business_day(date(2026, 9, 17)) is True
    assert calendar.is_business_day(date(2026, 9, 19)) is False     # 土
    assert calendar.is_business_day(date(2026, 9, 22)) is False     # 国民の休日
    assert calendar.is_business_day(date(2026, 9, 23)) is False     # 秋分の日
    assert calendar.next_business_day(date(2026, 9, 18)) == date(2026, 9, 24)
    assert calendar.prev_business_day(date(2026, 9, 24)) == date(2026, 9, 18)
    assert calendar.close_time(date(2026, 9, 17), time(15, 0)) == time(15, 0)


def test_calendar_out_of_range_and_sha(calendar):
    """T02-40: 収録年の外は黙って平日扱いにしない。ファイルは不変。"""
    with pytest.raises(ConfigError, match="2028-01-04"):
        calendar.is_business_day(date(2028, 1, 4))
    sha = hashlib.sha256((CONFIG_DIR / "trading_calendar.v1.yaml").read_bytes()).hexdigest()
    assert sha == CALENDAR_V1_SHA


def test_calendar_without_holidays_is_weekend_only():
    """祝日表が無いカレンダー（テスト用の代用品）は土日だけ休み。"""
    plain = Calendar(version="test", years=[2026], holidays={2026: []})
    assert plain.is_business_day(date(2026, 9, 23)) is True


# --- その他 ---------------------------------------------------------------

def test_secrets_from_env_and_masked():
    """T02-19: 値は require で取れるが repr には出ない。"""
    secrets = Secrets.from_env({"TYPESAFE_API_KEY": "sk-test-XYZ"})
    assert secrets.require("TYPESAFE_API_KEY") == "sk-test-XYZ"
    assert "sk-test-XYZ" not in repr(secrets)
    assert "sk-test-XYZ" not in str(secrets)
    assert "TYPESAFE_API_KEY=set" in repr(secrets)
    assert "NTFY_TOPIC=unset" in repr(secrets)
    assert secrets.values() == {"sk-test-XYZ"}


def test_secrets_missing_raises_name_only():
    """T02-20: 未設定のときのメッセージは変数名だけ。"""
    secrets = Secrets.from_env({})
    with pytest.raises(ConfigError, match="NTFY_TOPIC"):
        secrets.require("NTFY_TOPIC")
    assert secrets.get("NTFY_TOPIC") is None


def test_secrets_unknown_name_rejected():
    """T02-21: SECRET_NAMES 以外は受け付けない。"""
    with pytest.raises(ValueError):
        Secrets.from_env({}).require("FOO")


def test_settings_paths_helpers():
    """T02-22: 版つきファイルのパスは設定から組み立てる。"""
    s = Settings()
    assert s.entry_rules_path() == Path("config/entry_rules.v1.yaml")
    assert s.filters_path() == Path("config/filters.v1.yaml")
    assert s.calendar_path() == Path("config/trading_calendar.v1.yaml")
    assert s.questions_path() == Path("config/questions.v2.json")
    assert s.questions_path("v1") == Path("config/questions.v1.json")
    assert s.state_schema_path() == Path("docs/contracts/state.v2.schema.json")


def test_settings_schema_json_matches_model():
    """T02-23: docs/contracts/settings.schema.json は Settings から生成したもの。"""
    stored = json.loads((CONTRACTS_DIR / "settings.schema.json").read_text(encoding="utf-8"))
    assert stored == Settings.model_json_schema()


def test_state_cfg_defaults():
    """T02-41: M3 で足した設定項目の既定値。"""
    s = load_settings(CONFIG_DIR / "settings.yaml")
    assert s.state.max_secondary_bodies == 2
    assert s.state.excerpt_chars == 2000
    assert s.state.recent_days == 30
    assert s.bundle.scan_lookback_sec == 259200
    assert s.calendar_version == "v1"
