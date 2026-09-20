"""接続・PRAGMA・トランザクション境界・前進のみのマイグレーション（01-凍結ログ 3.1）。

sqlite3 を import してよいのは store だけ（00-共通規約 8章）。他モジュールは
db.IntegrityError / db.OperationalError の別名で例外を捕まえる。
"""

import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from ..common.errors import SchemaMismatchError, StoreError
from . import queries

CURRENT_SCHEMA_VERSION: int = 1

FROZEN_TABLES: tuple[str, ...] = (
    "events", "bundles", "judgments", "answers", "heartbeat",
    "ledger", "question_versions", "state_versions", "my_calls",
)

EXPECTED_TRIGGER_COUNT: int = len(FROZEN_TABLES) * 2  # UPDATE と DELETE で1本ずつ

# store 以外のモジュールは sqlite3 を import しないので、この別名を使う
IntegrityError = sqlite3.IntegrityError
OperationalError = sqlite3.OperationalError
ProgrammingError = sqlite3.ProgrammingError

# 値の根拠は 01-凍結ログ 6章（変更は ADR）
_PRAGMAS: tuple[tuple[str, str], ...] = (
    ("journal_mode", "WAL"),
    ("foreign_keys", "ON"),
    ("recursive_triggers", "ON"),
    ("synchronous", "FULL"),
    ("busy_timeout", "5000"),
)
_BUSY_TIMEOUT_SEC = 5.0
_MIGRATION_RE = re.compile(r"([0-9]{3})_[a-z0-9_]+\.sql")


def _open(path: str | Path) -> sqlite3.Connection:
    """PRAGMA を設定した接続を返す（スキーマ版は検査しない）。"""
    conn = sqlite3.connect(str(path), isolation_level=None, timeout=_BUSY_TIMEOUT_SEC)
    conn.row_factory = sqlite3.Row
    for key, value in _PRAGMAS:
        conn.execute(f"PRAGMA {key}={value}")
    return conn


def connect(path: str | Path) -> sqlite3.Connection:
    """接続してスキーマ版とトリガー本数を検査する。自動マイグレーションはしない。"""
    if not Path(path).exists():
        raise SchemaMismatchError(f"DB がありません: {path}。jevfwd init-db を実行")
    conn = _open(path)
    try:
        version = queries.current_schema_version(conn)
        if version != CURRENT_SCHEMA_VERSION:
            raise SchemaMismatchError(
                f"schema_version={version}、期待={CURRENT_SCHEMA_VERSION}: {path}。"
                "jevfwd init-db を実行"
            )
        found = conn.execute(
            "SELECT count(*) AS n FROM sqlite_master "
            "WHERE type='trigger' AND name GLOB 'trg_*'"
        ).fetchone()["n"]
        if found != EXPECTED_TRIGGER_COUNT:
            raise StoreError(
                f"追記専用トリガーが {found} 本（期待 {EXPECTED_TRIGGER_COUNT}）: {path}。"
                "DB が改変されています"
            )
    except BaseException:
        conn.close()
        raise
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """BEGIN IMMEDIATE … COMMIT。例外なら ROLLBACK。入れ子は不可。

    WAL では「SELECT してから書く」遅延 BEGIN が他プロセスのコミット後に即失敗し、
    busy_timeout が効かない。書き込みは必ずこの中で行う。
    """
    if conn.in_transaction:
        raise ProgrammingError("transaction() の入れ子は不可")
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


def _load_scripts() -> dict[int, str]:
    """版 -> SQL 本文。1 は schema.sql、2 以降は migrations/NNN_*.sql。"""
    base = Path(__file__).parent
    scripts: dict[int, str] = {1: (base / "schema.sql").read_text(encoding="utf-8")}
    found: dict[int, Path] = {}
    for path in sorted((base / "migrations").glob("*.sql")):
        m = _MIGRATION_RE.fullmatch(path.name)
        if m is None:
            raise StoreError(f"マイグレーションのファイル名が規約外: {path.name}")
        number = int(m.group(1))
        if number < 2:
            raise StoreError(f"マイグレーションの番号は 002 から: {path.name}")
        if number in found:
            raise StoreError(f"マイグレーションの番号が重複: {path.name} と {found[number].name}")
        found[number] = path
        scripts[number] = path.read_text(encoding="utf-8")
    expected = 2
    for number in sorted(found):
        if number != expected:
            raise StoreError(f"マイグレーションの番号が欠番: {expected:03d} が無い")
        expected += 1
    if max(scripts) != CURRENT_SCHEMA_VERSION:
        raise StoreError(
            f"CURRENT_SCHEMA_VERSION={CURRENT_SCHEMA_VERSION} だが版 {max(scripts)} の SQL がある"
        )
    return scripts


def migrate(path: str | Path) -> int:
    """schema_version を現在の版まで前進させ、適用後の版を返す。冪等。"""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    scripts = _load_scripts()
    conn = _open(path)
    try:
        while True:
            conn.execute("BEGIN IMMEDIATE")      # 版の読み取りをロック下で行う
            try:
                version = queries.current_schema_version(conn)
            finally:
                conn.execute("COMMIT")
            if version > CURRENT_SCHEMA_VERSION:
                raise SchemaMismatchError(
                    f"DB の版 {version} がコードの版 {CURRENT_SCHEMA_VERSION} より新しい: {path}"
                )
            if version == CURRENT_SCHEMA_VERSION:
                return version
            try:
                # 各スクリプトは自身の中で BEGIN IMMEDIATE … COMMIT を持つ
                conn.executescript(scripts[version + 1])
            except sqlite3.OperationalError:
                if queries.current_schema_version(conn) > version:
                    continue                      # 他プロセスが先に適用した
                raise
    finally:
        conn.close()
