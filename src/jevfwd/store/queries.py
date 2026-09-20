"""凍結ログの読み取り（01-凍結ログ 3.4）。

このモジュールは書き込みの SQL を含まない（テスト T01-12 がソースを検査する）。
M3 以降に必要な読み取りは、そのマイルストーンで足す。
"""

import sqlite3
from datetime import timedelta
from typing import Collection, Sequence

from ..common.timeutil import parse_utc, to_utc_str

# IN 句に並べる最大数（SQLite の変数上限 999 に余裕を持たせる）
_CHUNK = 500

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


# --- M3（04-束ね・05-state構築）で追加した読み取り ---------------------------

def max_event_id(conn: sqlite3.Connection) -> int:
    """採番済みの最大 event_id。行が無ければ 0。"""
    row = conn.execute("SELECT max(event_id) AS v FROM events").fetchone()
    if row is None or row["v"] is None:
        return 0
    return int(row["v"])


def events_after(
    conn: sqlite3.Connection, event_id: int, limit: int
) -> list[sqlite3.Row]:
    """event_id より後の events を昇順で。body_text は選ばない（束ねは本文を見ない）。"""
    return list(
        conn.execute(
            "SELECT event_id, code, company, title, published_at, received_at, pdf_status "
            "FROM events WHERE event_id > ? ORDER BY event_id LIMIT ?",
            (event_id, limit),
        ).fetchall()
    )


def events_by_ids(
    conn: sqlite3.Connection, event_ids: Collection[int]
) -> list[sqlite3.Row]:
    """指定した event_id の行を昇順で（既存 bundle の member を読み直すときに使う）。"""
    found: dict[int, sqlite3.Row] = {}
    ids = list(event_ids)
    for start in range(0, len(ids), _CHUNK):
        chunk = ids[start:start + _CHUNK]
        placeholders = ", ".join("?" * len(chunk))
        for row in conn.execute(
            "SELECT event_id, code, company, title, published_at, received_at, pdf_status "
            f"FROM events WHERE event_id IN ({placeholders})",
            chunk,
        ).fetchall():
            found[int(row["event_id"])] = row
    return [found[i] for i in sorted(found)]


def event_bodies(
    conn: sqlite3.Connection, event_ids: Sequence[int]
) -> dict[int, str | None]:
    """event_id -> body_text。存在しない id はキーに入らない（05-state構築 が使う）。"""
    bodies: dict[int, str | None] = {}
    ids = list(event_ids)
    for start in range(0, len(ids), _CHUNK):
        chunk = ids[start:start + _CHUNK]
        placeholders = ", ".join("?" * len(chunk))
        for row in conn.execute(
            f"SELECT event_id, body_text FROM events WHERE event_id IN ({placeholders})",
            chunk,
        ).fetchall():
            bodies[int(row["event_id"])] = row["body_text"]
    return bodies


def bundles_since(conn: sqlite3.Connection, anchor_from: str) -> list[sqlite3.Row]:
    """anchor_published_at >= ? の bundles を bundle_id 昇順で。superseded な行も含む。"""
    return list(
        conn.execute(
            "SELECT * FROM bundles WHERE anchor_published_at >= ? ORDER BY bundle_id",
            (anchor_from,),
        ).fetchall()
    )


def min_uncovered_event_id(
    conn: sqlite3.Connection, covered: Collection[int], since: str
) -> int | None:
    """published_at >= since の events のうち covered に無い最小の event_id。無ければ None。"""
    known = frozenset(covered)
    cursor = conn.execute(
        "SELECT event_id FROM events WHERE published_at >= ? ORDER BY event_id",
        (since,),
    )
    for row in cursor:
        event_id = int(row["event_id"])
        if event_id not in known:
            return event_id
    return None


def recent_titles(
    conn: sqlite3.Connection, code: str, before: str, days: int
) -> list[sqlite3.Row]:
    """before より前（同時刻は含めない）で before - days 以降の開示を published_at 昇順で。"""
    since = to_utc_str(parse_utc(before) - timedelta(days=days))
    return list(
        conn.execute(
            "SELECT event_id, title, published_at FROM events "
            "WHERE code = ? AND published_at < ? AND published_at >= ? "
            "ORDER BY published_at, event_id",
            (code, before, since),
        ).fetchall()
    )


def bundles_with_full_judgment(
    conn: sqlite3.Connection, bundle_ids: Collection[int]
) -> frozenset[int]:
    """purpose='full' の judgments を持つ bundle_id の集合（04-束ね 4.9-5 の歯止め）。"""
    found: set[int] = set()
    ids = list(bundle_ids)
    for start in range(0, len(ids), _CHUNK):
        chunk = ids[start:start + _CHUNK]
        placeholders = ", ".join("?" * len(chunk))
        for row in conn.execute(
            f"SELECT DISTINCT bundle_id FROM judgments "
            f"WHERE purpose = 'full' AND bundle_id IN ({placeholders})",
            chunk,
        ).fetchall():
            found.add(int(row["bundle_id"]))
    return frozenset(found)
