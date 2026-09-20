"""state に足す文脈の取り口（05-state構築 3.2）。

段階1で「取れないもの」（market_cache 由来）と「取れるもの」（events 由来）で
境目が違うので、プロトコルを2つに分ける。実装を差し替えるのは `cli`。
"""

from typing import Protocol, Sequence

from ..common.timeutil import jst_day, parse_utc
from ..store import queries

# market_context の項目（schema の required と同じ順）。オブジェクト自体は必ず置く
MARKET_CONTEXT_KEYS: tuple[str, ...] = (
    "prev_close", "market_cap_jpy", "return_20d_vs_topix", "avg_turnover_20d_jpy",
)


class MarketContextProvider(Protocol):
    """market_cache（ADR 017）由来。段階1（market_cache.enabled=false）では全項目 null。"""

    source: str                    # completeness.sources["market_context"]（"null" / "db"）

    def market_context(
        self, code5: str, anchor_utc: str, session: str
    ) -> tuple[dict, list[str]]:
        """(market_context の dict, 欠損項目のパス)。"""
        ...


class DisclosureContext(Protocol):
    """events / xbrl 由来。段階1でも取れる。"""

    def recent_titles(self, code5: str, before_utc: str, days: int) -> list[str]:
        """`"YYYY-MM-DD 表題"` の配列。anchor より厳密に前のものだけ（4.7）。"""
        ...

    def forecast_context(self, code5: str, event_ids: Sequence[int]) -> dict | None:
        """前回予想・前期実績（要件 F2-3）。取れなければ None。"""
        ...


class NullMarketContext:
    """段階1。4項目すべて null を返し、全部を欠損として報告する。"""

    source = "null"

    def market_context(
        self, code5: str, anchor_utc: str, session: str
    ) -> tuple[dict, list[str]]:
        return (
            {key: None for key in MARKET_CONTEXT_KEYS},
            [f"market_context.{key}" for key in MARKET_CONTEXT_KEYS],
        )


class DbDisclosureContext:
    """`events` から取れる文脈（直近の開示と XBRL）。"""

    def __init__(self, conn) -> None:
        self._conn = conn

    def recent_titles(self, code5: str, before_utc: str, days: int) -> list[str]:
        """同一銘柄の直近 days 日の表題。公表時刻が before より厳密に前のものだけ（4.7）。"""
        return [
            f"{jst_day(parse_utc(row['published_at']))} {row['title']}"
            for row in queries.recent_titles(self._conn, code5, before_utc, days)
        ]

    def forecast_context(self, code5: str, event_ids: Sequence[int]) -> dict | None:
        """XBRL からの抽出範囲が未決（task 005）なので、段階1では常に None。"""
        return None
