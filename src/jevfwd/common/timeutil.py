"""時刻の変換と検証。保存は UTC の秒精度、表示だけ JST（00-共通規約 3章）。

業務関数は現在時刻を引数で受ける。現在時刻を読むのはこのモジュールだけ。
"""

import re
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

# DDL の GLOB CHECK と同じ書式（'YYYY-MM-DDTHH:MM:SS+00:00'）
UTC_FMT_GLOB = "[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]+00:00"
JST = ZoneInfo("Asia/Tokyo")

_UTC_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\+00:00")
_HHMM_RE = re.compile(r"([0-9]{2}):([0-9]{2})")


def now_utc() -> datetime:
    """現在時刻（UTC、マイクロ秒は 0）。"""
    return datetime.now(timezone.utc).replace(microsecond=0)


def to_utc_str(dt: datetime) -> str:
    """aware な datetime を保存用の UTC 文字列にする。naive は ValueError。"""
    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        raise ValueError(f"naive な datetime は保存できない（tz を付ける）: {dt!r}")
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat(timespec="seconds")


def is_utc_str(value: object) -> bool:
    """保存用の UTC 文字列か。'Z' 終端・空白区切り・ミリ秒つきは False。"""
    return isinstance(value, str) and _UTC_RE.fullmatch(value) is not None


def parse_utc(s: str) -> datetime:
    """保存用の UTC 文字列を datetime にする。書式違反は ValueError。"""
    if not is_utc_str(s):
        raise ValueError(f"UTC 文字列の書式違反: {s!r}")
    return datetime.fromisoformat(s)


def to_jst(dt: datetime) -> datetime:
    """aware な datetime を JST にする（表示用）。"""
    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        raise ValueError(f"naive な datetime は変換できない: {dt!r}")
    return dt.astimezone(JST)


def format_jst(dt: datetime) -> str:
    """'YYYY-MM-DD HH:MM JST'。通知・ダイジェストの表示に使う。"""
    return to_jst(dt).strftime("%Y-%m-%d %H:%M JST")


def jst_day(dt: datetime) -> str:
    """JST の暦日 'YYYY-MM-DD'（ledger.day や prices.date の書式）。"""
    return to_jst(dt).strftime("%Y-%m-%d")


def jst_minute_to_utc_str(day: date | str, hhmm: str) -> str:
    """JST の暦日と 'HH:MM'（TDnet 一覧の分単位の公表時刻）を UTC 文字列にする。"""
    d = date.fromisoformat(day) if isinstance(day, str) else day
    m = _HHMM_RE.fullmatch(hhmm)
    if m is None:
        raise ValueError(f"'HH:MM' ではない: {hhmm!r}")
    hour, minute = int(m.group(1)), int(m.group(2))
    if hour > 23 or minute > 59:
        raise ValueError(f"時刻の範囲外: {hhmm!r}")
    return to_utc_str(datetime(d.year, d.month, d.day, hour, minute, tzinfo=JST))
