"""設定ファイルと秘密の読み込み（詳細設計 02-設定.md）。

YAML を型付きの不変オブジェクトにして渡すだけで、設定値の意味は解釈しない。
版つきファイル（entry_rules / filters / trading_calendar）は作成後に変更しない。
秘密は環境変数からだけ読み、repr にも出さない。
"""

import functools
import os
import re
from datetime import date, time, timedelta
from pathlib import Path
from typing import Annotated, Literal, Mapping

import yaml
from pydantic import BaseModel, ConfigDict, StrictStr, StringConstraints, ValidationError

from .common.errors import ConfigError
from .common.versions import version_from_filename

# "18:30"。YAML では必ずクォートする（18:30 は 60進数の 1110 と解釈される）
HHMM = Annotated[StrictStr, StringConstraints(pattern=r"^\d{2}:\d{2}$")]

# low_priority_titles の並び順に対応する key（02-設定 4.3）
LOW_PRIORITY_KEYS: tuple[str, ...] = ("growth_plan", "cg_report")

SECRET_NAMES: tuple[str, ...] = ("TYPESAFE_API_KEY", "JQUANTS_REFRESH_TOKEN", "NTFY_TOPIC")

ENV_CONFIG = "JEVFWD_CONFIG"
DEFAULT_SETTINGS_PATH = Path("config/settings.yaml")


@functools.lru_cache(maxsize=2048)
def _compiled(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern)


def _search_any(patterns: tuple[str, ...] | list[str], text: str) -> bool:
    return any(_compiled(p).search(text) for p in patterns)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)


# --- settings.yaml --------------------------------------------------------

class PathsCfg(_Strict):
    config_dir: str = "config"
    contracts_dir: str = "docs/contracts"


class StorageCfg(_Strict):
    db_path: str = "data/db/jevfwd.sqlite"
    raw_pdf_dir: str = "data/raw/pdf"
    raw_pdf_retention_days: int = 30            # ADR 018


class FetchCfg(_Strict):
    interval_sec: int = 60
    pdf_retries: int = 3
    list_lookback_days: int = 1


class BundleCfg(_Strict):
    window_sec: int = 300
    grace_sec: int = 120
    scan_lookback_sec: int = 259200             # ADR 022
    supersede_deadline_sec: int = 3600
    max_supersede_depth: int = 2
    max_per_cycle: int = 200
    catchup_factor: int = 10
    poll_sec: int = 30
    stuck_margin_sec: int = 600                 # grace_sec にこれを足した滞留は障害（04-束ね 5章）


class JudgeCfg(_Strict):
    api_base_url: str = "https://api.typesafe.ai"
    models: list[str] = ["jev-latest", "jev-preview"]
    timeout_sec: int = 10
    retries: int = 3
    delayed_threshold_sec: int = 300            # ADR 009
    max_state_chars: int = 40000
    question_version: str = "v2"
    state_version: str = "v2"


class MarketCfg(_Strict):
    session_open: HHMM = "09:00"
    session_close: HHMM = "15:00"
    pre_open_from: HHMM = "08:00"
    tz: str = "Asia/Tokyo"


class DigestCfg(_Strict):
    runs: list[HHMM] = ["18:30", "07:30"]       # ADR 010
    tz: str = "Asia/Tokyo"


class MarketCacheCfg(_Strict):
    enabled: bool = False                       # 段階1は無効（ADR 017）
    run_at: HHMM = "06:30"
    topix_source: str | None = None             # task 003


class StateCfg(_Strict):
    max_secondary_bodies: int = 2
    excerpt_chars: int = 2000
    max_excerpts: int = 4
    recent_days: int = 30
    report_min_chars: int = 50000
    report_min_headings: int = 5


class MonitorCfg(_Strict):
    heartbeat_sec: int = 60
    missing_beats_alert: int = 3
    disk_alert_pct: int = 80
    daily_cost_limit_jpy: int | None = None     # task 004


class Settings(_Strict):
    paths: PathsCfg = PathsCfg()
    storage: StorageCfg = StorageCfg()
    fetch: FetchCfg = FetchCfg()
    bundle: BundleCfg = BundleCfg()
    judge: JudgeCfg = JudgeCfg()
    market: MarketCfg = MarketCfg()
    digest: DigestCfg = DigestCfg()
    market_cache: MarketCacheCfg = MarketCacheCfg()
    monitor: MonitorCfg = MonitorCfg()
    state: StateCfg = StateCfg()
    entry_rules_version: str = "v1"
    filters_version: str = "v1"
    calendar_version: str = "v1"

    def entry_rules_path(self) -> Path:
        """`<config_dir>/entry_rules.<entry_rules_version>.yaml`"""
        return Path(self.paths.config_dir) / f"entry_rules.{self.entry_rules_version}.yaml"

    def filters_path(self) -> Path:
        """`<config_dir>/filters.<filters_version>.yaml`"""
        return Path(self.paths.config_dir) / f"filters.{self.filters_version}.yaml"

    def calendar_path(self) -> Path:
        """`<config_dir>/trading_calendar.<calendar_version>.yaml`"""
        return Path(self.paths.config_dir) / f"trading_calendar.{self.calendar_version}.yaml"

    def questions_path(self, version: str | None = None) -> Path:
        """`<config_dir>/questions.<version>.json`。既定は judge.question_version。"""
        return Path(self.paths.config_dir) / f"questions.{version or self.judge.question_version}.json"

    def state_schema_path(self, version: str | None = None) -> Path:
        """`<contracts_dir>/state.<version>.schema.json`。既定は judge.state_version。"""
        return Path(self.paths.contracts_dir) / f"state.{version or self.judge.state_version}.schema.json"


# --- entry_rules.vN.yaml --------------------------------------------------

class EntryCfg(_Strict):
    direction_up_min: float
    confidence_min: float
    market_cap_max_jpy: int
    avg_turnover_20d_min_jpy: int
    pre_return_20d_vs_topix_max: float
    max_new_positions_per_day: int


class ExitCfg(_Strict):
    time_exit_days: int
    stop_loss: float
    thesis_broken_categories: list[str]         # 意味の確定は task 015
    day1_fade: Literal["record_only", "enabled"]


class SizingCfg(_Strict):
    position_pct: float
    max_positions: int


class CostCfg(_Strict):
    commission_roundtrip: float
    slippage: float


class EntryRules(_Strict):
    version: str
    entry: EntryCfg
    exit: ExitCfg
    sizing: SizingCfg
    cost: CostCfg


# --- filters.vN.yaml ------------------------------------------------------

class PriorityEntry(_Strict):
    key: str
    rank: int
    patterns: list[str]


class Filters(_Strict):
    """表題・社名・コードの分類規則。bundle_role の決定そのものは bundle/filters.py（M3）。"""

    version: str
    exclude_name_prefixes: list[str]
    market_name_prefixes: list[str]
    market_map: dict[str, str]
    exclude_code_patterns: list[str]
    exclude_titles: list[str]
    low_priority_titles: list[str]
    tob_titles: list[str]
    tob_target_titles: list[str]
    tob_exclude_titles: list[str]
    sequence_patterns: list[str]
    primary_priority: list[PriorityEntry]
    default_rank: int

    def strip_market_prefix(self, company: str) -> str:
        """市場区分の接頭辞（Ｐ－ Ｓ－ Ｇ－）を社名から剥がす。"""
        for prefix in self.market_name_prefixes:
            if company.startswith(prefix):
                return company[len(prefix):]
        return company

    def market_of_company(self, company: str) -> str | None:
        """社名接頭辞から市場区分を引く（段階1の issuer.market）。無ければ None。"""
        for prefix, market in self.market_map.items():
            if company.startswith(prefix):
                return market
        return None

    def has_excluded_name_prefix(self, company: str) -> bool:
        """ETF / ETN / REIT / インフラファンドの社名接頭辞か。"""
        return any(company.startswith(p) for p in self.exclude_name_prefixes)

    def code_excluded(self, code: str) -> bool:
        """コードだけで判定できる除外（5文字目 4 の ETF）。"""
        return _search_any(self.exclude_code_patterns, code)

    def title_excluded(self, title: str) -> bool:
        """表題で除外する開示か（判定しない）。"""
        return _search_any(self.exclude_titles, title)

    def title_low_priority(self, title: str) -> bool:
        """判定はするがダイジェストから外す開示か（ADR 019）。"""
        return self.low_priority_key(title) is not None

    def low_priority_key(self, title: str) -> str | None:
        """一致した low_priority のキー（growth_plan / cg_report）。"""
        for i, pattern in enumerate(self.low_priority_titles):
            if _compiled(pattern).search(title):
                return LOW_PRIORITY_KEYS[i]
        return None

    def title_is_tob(self, title: str) -> bool:
        """TOB・MBO・株式交換の開示か。打ち消しパターンに一致したら False（ADR 023）。"""
        if _search_any(self.tob_exclude_titles, title):
            return False
        return _search_any(self.tob_titles, title)

    def title_is_tob_target(self, title: str) -> bool:
        """TOB の対象者側か。束ね例外を適用するのはこれだけ（ADR 023）。"""
        return self.title_is_tob(title) and _search_any(self.tob_target_titles, title)

    def strip_sequence(self, title: str) -> tuple[str, str | None]:
        """(連番を除いた表題, 一致した連番文字列 or None)。連番は表題末尾（ADR 016）。"""
        for pattern in self.sequence_patterns:
            m = _compiled(pattern).search(title)
            if m is not None:
                return title[: m.start()].rstrip(), m.group(0)
        return (title, None)

    def primary_rank(self, title: str) -> int:
        """主開示の優先順。最初に一致した entry の rank、無ければ default_rank（04-束ね 4.4）。"""
        for entry in self.primary_priority:
            if _search_any(entry.patterns, title):
                return entry.rank
        return self.default_rank


# --- trading_calendar.vN.yaml ---------------------------------------------

class Calendar(_Strict):
    """東証の営業日（ADR 025）。bundle / state / score / digest が引数で受け取る。"""

    version: str
    years: list[int]
    holidays: dict[int, list[str]]              # 年 -> "MM-DD"
    half_days: dict[str, HHMM] = {}             # "YYYY-MM-DD" -> 引け時刻

    def _check_year(self, day: date) -> None:
        if day.year not in self.years:
            raise ConfigError(
                f"trading_calendar {self.version} は {min(self.years)}-{max(self.years)} のみ収録。"
                f"{day.isoformat()} は判定できない"
            )

    def is_business_day(self, day: date) -> bool:
        """土日と holidays を除く。収録年の外は ConfigError（黙って平日扱いにしない）。"""
        self._check_year(day)
        if day.weekday() >= 5:
            return False
        return day.strftime("%m-%d") not in self.holidays.get(day.year, [])

    def close_time(self, day: date, default_close: time) -> time:
        """半日立会ならその引け時刻、通常日は default_close。"""
        self._check_year(day)
        hhmm = self.half_days.get(day.isoformat())
        if hhmm is None:
            return default_close
        hour, minute = hhmm.split(":")
        return time(int(hour), int(minute))

    def next_business_day(self, day: date) -> date:
        """翌営業日（採点の起点日）。"""
        nxt = day + timedelta(days=1)
        while not self.is_business_day(nxt):
            nxt += timedelta(days=1)
        return nxt

    def prev_business_day(self, day: date) -> date:
        """前営業日（直前終値の基準日）。"""
        prev = day - timedelta(days=1)
        while not self.is_business_day(prev):
            prev -= timedelta(days=1)
        return prev


# --- 読み込み -------------------------------------------------------------

def _load_yaml(path: Path) -> dict:
    if not Path(path).exists():
        raise ConfigError(f"設定ファイルがありません: {path}")
    try:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise ConfigError(f"{path}: YAML が読めません: {e}") from e
    if not isinstance(data, dict):
        raise ConfigError(f"{path}: トップレベルは mapping")
    return data


def _validate(model: type[BaseModel], data: dict, path: Path):
    try:
        return model.model_validate(data)
    except ValidationError as e:
        locs = "; ".join(
            ".".join(str(x) for x in err["loc"]) + ": " + err["msg"] for err in e.errors()
        )
        hint = "（\"HH:MM\" はクォートが必要）" if any(
            err["type"] == "string_type" for err in e.errors()
        ) else ""
        raise ConfigError(f"{path}: {locs}{hint}") from e


def _check_version(found: str, from_name: str, path: Path) -> None:
    if found != from_name:
        raise ConfigError(f"{path}: version={found} がファイル名の版 {from_name} と一致しない")


def resolve_settings_path(cli_arg: str | None = None, env: Mapping[str, str] = os.environ) -> Path:
    """--config > $JEVFWD_CONFIG > config/settings.yaml。"""
    if cli_arg:
        return Path(cli_arg)
    from_env = env.get(ENV_CONFIG)
    if from_env:
        return Path(from_env)
    return DEFAULT_SETTINGS_PATH


def load_settings(path: Path) -> Settings:
    """settings.yaml を読む（版なし。運用で変えてよい唯一の設定）。"""
    return _validate(Settings, _load_yaml(path), path)


def load_entry_rules(path: Path) -> EntryRules:
    """entry_rules.vN.yaml を読む。version がファイル名と違えば ConfigError。"""
    rules = _validate(EntryRules, _load_yaml(path), path)
    _check_version(rules.version, version_from_filename(path, "entry_rules"), path)
    return rules


_REGEX_KEYS = (
    "exclude_code_patterns", "exclude_titles", "low_priority_titles",
    "tob_titles", "tob_target_titles", "tob_exclude_titles", "sequence_patterns",
)


def load_filters(path: Path) -> Filters:
    """filters.vN.yaml を読む。正規表現は読み込み時にコンパイルして検証する。"""
    filters = _validate(Filters, _load_yaml(path), path)
    _check_version(filters.version, version_from_filename(path, "filters"), path)
    for key in _REGEX_KEYS:
        for i, pattern in enumerate(getattr(filters, key)):
            try:
                _compiled(pattern)
            except re.error as e:
                raise ConfigError(f"{path}: {key}[{i}] の正規表現が不正: {e}") from e
    for entry in filters.primary_priority:
        for i, pattern in enumerate(entry.patterns):
            try:
                _compiled(pattern)
            except re.error as e:
                raise ConfigError(
                    f"{path}: primary_priority[{entry.key}].patterns[{i}] の正規表現が不正: {e}"
                ) from e
    if len(filters.low_priority_titles) > len(LOW_PRIORITY_KEYS):
        raise ConfigError(
            f"{path}: low_priority_titles が {len(filters.low_priority_titles)} 件あるが "
            f"key は {len(LOW_PRIORITY_KEYS)} 件（settings.LOW_PRIORITY_KEYS と 02-設定 4.3 に追記する）"
        )
    return filters


_MMDD_RE = re.compile(r"[0-9]{2}-[0-9]{2}")


def load_calendar(path: Path) -> Calendar:
    """trading_calendar.vN.yaml を読む。日付の書式と収録年を検証する。"""
    calendar = _validate(Calendar, _load_yaml(path), path)
    _check_version(calendar.version, version_from_filename(path, "trading_calendar"), path)
    for year, days in calendar.holidays.items():
        if year not in calendar.years:
            raise ConfigError(f"{path}: holidays に years 外の年 {year} がある")
        for i, day in enumerate(days):
            if _MMDD_RE.fullmatch(day) is None:
                raise ConfigError(f"{path}: holidays[{year}][{i}] が 'MM-DD' ではない: {day!r}")
            try:
                date(year, int(day[:2]), int(day[3:]))
            except ValueError as e:
                raise ConfigError(f"{path}: holidays[{year}][{i}] は存在しない日付: {day!r}") from e
    return calendar


# --- 秘密 -----------------------------------------------------------------

class Secrets:
    """環境変数から読む秘密。値は require / get でだけ取れ、repr には出ない。"""

    __slots__ = ("_values",)

    def __init__(self, values: Mapping[str, str | None]) -> None:
        self._values: dict[str, str | None] = {
            name: (values.get(name) or None) for name in SECRET_NAMES
        }

    @classmethod
    def from_env(cls, env: Mapping[str, str] = os.environ) -> "Secrets":
        """環境変数から読む（`.env` は読まない。compose か `set -a; source .env`）。"""
        return cls({name: env.get(name) for name in SECRET_NAMES})

    def _check_name(self, name: str) -> None:
        if name not in SECRET_NAMES:
            raise ValueError(f"秘密の名前ではない: {name!r}（{', '.join(SECRET_NAMES)}）")

    def require(self, name: str) -> str:
        """未設定なら ConfigError（メッセージに値は含めない）。"""
        self._check_name(name)
        value = self._values[name]
        if value is None:
            raise ConfigError(f"環境変数 {name} が未設定")
        return value

    def get(self, name: str) -> str | None:
        """未設定なら None。"""
        self._check_name(name)
        return self._values[name]

    def values(self) -> frozenset[str]:
        """設定済みの値の集合（ログのマスク用）。"""
        return frozenset(v for v in self._values.values() if v)

    def __repr__(self) -> str:
        state = ", ".join(
            f"{name}={'set' if self._values[name] else 'unset'}" for name in SECRET_NAMES
        )
        return f"Secrets({state})"

    __str__ = __repr__
