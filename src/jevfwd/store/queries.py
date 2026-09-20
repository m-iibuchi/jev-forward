"""凍結ログの読み取り（01-凍結ログ 3.4）。

このモジュールは書き込みの SQL を含まない（テスト T01-12 がソースを検査する）。
M3 以降に必要な読み取りは、そのマイルストーンで足す。
"""

import sqlite3
from typing import Sequence

# count_rows に渡してよいテーブル名（識別子を SQL に埋めるため許可リストにする）
_COUNTABLE: frozenset[str] = frozenset(
    {
        "events", "bundles", "judgments", "answers", "heartbeat",
        "ledger", "question_versions", "state_versions", "my_calls",
        "listed_master", "prices", "outcomes", "paper_trades", "schema_version",
    }
)


def current_schema_version(conn: sqlite3.Connection) -> int:
    """適用済みの最大の schema_version。テーブルが無ければ 0。"""
    exists = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
    ).fetchone()
    if exists is None:
        return 0
    row = conn.execute("SELECT max(version) AS v FROM schema_version").fetchone()
    if row is None or row["v"] is None:
        return 0
    return int(row["v"])


def count_rows(conn: sqlite3.Connection, table: str) -> int:
    """行数。未知のテーブル名は ValueError（識別子は許可リストのみ）。"""
    if table not in _COUNTABLE:
        raise ValueError(f"数えられないテーブル: {table!r}")
    return int(conn.execute(f"SELECT count(*) AS n FROM {table}").fetchone()["n"])


def get_question_version(conn: sqlite3.Connection, version: str) -> sqlite3.Row | None:
    """凍結済みの問い版1行。未凍結なら None。"""
    return conn.execute(
        "SELECT * FROM question_versions WHERE version = ?", (version,)
    ).fetchone()


def get_state_version(conn: sqlite3.Connection, version: str) -> sqlite3.Row | None:
    """凍結済みの state 版1行。未凍結なら None。"""
    return conn.execute(
        "SELECT * FROM state_versions WHERE version = ?", (version,)
    ).fetchone()


def recent_heartbeat(
    conn: sqlite3.Connection, process: str, limit: int = 3
) -> list[sqlite3.Row]:
    """直近の heartbeat を ts 降順で。同一秒の複数行は heartbeat_id 降順で並べる。"""
    return list(
        conn.execute(
            "SELECT * FROM heartbeat WHERE process = ? "
            "ORDER BY ts DESC, heartbeat_id DESC LIMIT ?",
            (process, limit),
        ).fetchall()
    )


def current_bundle(conn: sqlite3.Connection, bundle_id: int) -> sqlite3.Row | None:
    """supersedes_id の連鎖を子方向へ辿り、後続に指されていない最新の bundle を返す。"""
    row = conn.execute(
        "SELECT * FROM bundles WHERE bundle_id = ?", (bundle_id,)
    ).fetchone()
    while row is not None:
        nxt = conn.execute(
            "SELECT * FROM bundles WHERE supersedes_id = ? ORDER BY bundle_id LIMIT 1",
            (row["bundle_id"],),
        ).fetchone()
        if nxt is None:
            return row
        row = nxt
    return None


def is_superseded(conn: sqlite3.Connection, bundle_id: int) -> bool:
    """この bundle を指す後続があるか（あれば主分析・採点の対象から外す）。"""
    row = conn.execute(
        "SELECT 1 AS hit FROM bundles WHERE supersedes_id = ? LIMIT 1", (bundle_id,)
    ).fetchone()
    return row is not None


def question_versions(conn: sqlite3.Connection) -> Sequence[sqlite3.Row]:
    """凍結済みの問い版を version 昇順で（`freeze-questions` の確認用）。"""
    return list(conn.execute("SELECT * FROM question_versions ORDER BY version").fetchall())
