"""凍結ログへの追記だけを公開する（CLAUDE.md ルール1、ADR 014）。

公開名はすべて insert_ で始まる。行を書き換える手段はこのモジュールに存在しない。
呼び出し側が db.transaction() で囲む。制約違反はそのまま伝播させる。
"""

import dataclasses as _dataclasses
import sqlite3 as _sqlite3
from typing import Sequence as _Sequence

from . import rows as _rows

__all__ = [
    "insert_event",
    "insert_bundle",
    "insert_judgment",
    "insert_answer",
    "insert_answers",
    "insert_heartbeat",
    "insert_ledger_entry",
    "insert_question_version",
    "insert_state_version",
    "insert_my_call",
]


def _add(conn: _sqlite3.Connection, table: str, row: object) -> int:
    """1行追記して採番された id を返す。"""
    cols = [f.name for f in _dataclasses.fields(row)]
    placeholders = ", ".join("?" * len(cols))
    sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({placeholders})"
    cur = conn.execute(sql, [getattr(row, c) for c in cols])
    return int(cur.lastrowid)


def insert_event(conn: _sqlite3.Connection, row: _rows.NewEvent) -> int:
    """events に1行。返り値は event_id。"""
    return _add(conn, "events", row)


def insert_bundle(conn: _sqlite3.Connection, row: _rows.NewBundle) -> int:
    """bundles に1行。返り値は bundle_id。"""
    return _add(conn, "bundles", row)


def insert_judgment(conn: _sqlite3.Connection, row: _rows.NewJudgment) -> int:
    """judgments に1行。返り値は judgment_id。"""
    return _add(conn, "judgments", row)


def insert_answer(conn: _sqlite3.Connection, row: _rows.NewAnswer) -> int:
    """answers に1行。返り値は answer_id。"""
    return _add(conn, "answers", row)


def insert_answers(
    conn: _sqlite3.Connection, rows_: _Sequence[_rows.NewAnswer]
) -> list[int]:
    """answers に複数行。id を返すため1行ずつ追記する。"""
    return [_add(conn, "answers", r) for r in rows_]


def insert_heartbeat(conn: _sqlite3.Connection, row: _rows.NewHeartbeat) -> int:
    """heartbeat に1行。返り値は heartbeat_id。"""
    return _add(conn, "heartbeat", row)


def insert_ledger_entry(conn: _sqlite3.Connection, row: _rows.NewLedgerEntry) -> int:
    """ledger に1行。返り値は ledger_id。"""
    return _add(conn, "ledger", row)


def insert_question_version(
    conn: _sqlite3.Connection, row: _rows.NewQuestionVersion
) -> int:
    """question_versions に1行。返り値は question_version_id。"""
    return _add(conn, "question_versions", row)


def insert_state_version(conn: _sqlite3.Connection, row: _rows.NewStateVersion) -> int:
    """state_versions に1行。返り値は state_version_id。"""
    return _add(conn, "state_versions", row)


def insert_my_call(conn: _sqlite3.Connection, row: _rows.NewMyCall) -> int:
    """my_calls に1行。返り値は my_call_id。"""
    return _add(conn, "my_calls", row)
