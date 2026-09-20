"""版ファイルの凍結（ADR 020）。CLI の freeze-questions / freeze-state が使う。

同じ版を二度凍結しても行は増やさない。本文が違えば ConfigError にして DB に触らない。
"""

import sqlite3

from ..common.errors import ConfigError
from . import db, queries, repo, rows

# テーブル -> (queries の取得関数名, repo の追記関数名, 行の型)。
# 関数は呼び出し時に getattr で解決する（テストが queries を差し替えられるように）。
_OPS: dict[str, tuple[str, str, type]] = {
    "question_versions": ("get_question_version", "insert_question_version", rows.NewQuestionVersion),
    "state_versions": ("get_state_version", "insert_state_version", rows.NewStateVersion),
}


def freeze_version(
    conn: sqlite3.Connection,
    *,
    table: str,
    version: str,
    text: str,
    sha256: str,
    now: str,
) -> tuple[str, str, str]:
    """版の本文を凍結する。返り値は (status, sha256, frozen_at)。status は frozen / already。"""
    if table not in _OPS:
        raise ValueError(f"凍結できないテーブル: {table!r}")
    getter_name, inserter_name, row_type = _OPS[table]
    for attempt in (1, 2):
        try:
            with db.transaction(conn):
                getter = getattr(queries, getter_name)
                row = getter(conn, version)
                if row is None:
                    inserter = getattr(repo, inserter_name)
                    inserter(conn, row_type(version, text, sha256, now))
                    return ("frozen", sha256, now)
                if row["sha256"] == sha256:
                    return ("already", sha256, row["frozen_at"])
                raise ConfigError(
                    f"{table} {version} は sha256={row['sha256']} で凍結済み。"
                    f"ファイルは {sha256}。版ファイルを変更してはいけない（新しい版を作る）"
                )
        except db.IntegrityError:
            if attempt == 2:
                raise          # 並行凍結の衝突が2回続くのは異常
    raise AssertionError("unreachable")
