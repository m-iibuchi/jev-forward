"""01-凍結ログ 8章の受入テスト（T01-01〜27）。追記専用であることを DB とコードの両方で確かめる。"""

import hashlib
import inspect
import re
import sqlite3
import time
from pathlib import Path

import pytest

from conftest import CONFIG_DIR, REPO_ROOT, read_fixture
from jevfwd.common.errors import ConfigError, SchemaMismatchError, StoreError
from jevfwd.store import db, freeze, queries, repo, rows

U = "2026-09-17T08:30:00+00:00"
V = "2026-09-17T09:00:00+00:00"
SHA_A = hashlib.sha256(b"a").hexdigest()
SHA_B = hashlib.sha256(b"b").hexdigest()


@pytest.fixture
def conn(db_path):
    db.migrate(db_path)
    connection = db.connect(db_path)
    yield connection
    connection.close()


def _event(conn, **kw):
    base = dict(code="35600", title="業績予想の修正に関するお知らせ", published_at=U,
                received_at=U, pdf_status="none")
    base.update(kw)
    return repo.insert_event(conn, rows.NewEvent(**base))


def _bundle(conn, event_id, **kw):
    base = dict(code="35600", anchor_published_at=U, session="after_close",
                primary_event_id=event_id, event_ids_json=f"[{event_id}]",
                logical_docs_json="[]", bundle_role="normal", created_at=U)
    base.update(kw)
    return repo.insert_bundle(conn, rows.NewBundle(**base))


def seed(conn) -> dict[str, int]:
    """9 つの凍結テーブルに1行ずつ入れる（外部キーの順に）。"""
    ids: dict[str, int] = {}
    with db.transaction(conn):
        repo.insert_question_version(conn, rows.NewQuestionVersion("v2", "{}", SHA_A, U))
        repo.insert_state_version(conn, rows.NewStateVersion("v2", "{}", SHA_B, U))
        ids["event"] = _event(conn, pdf_status="ok", pdf_sha256=SHA_A)
        ids["bundle"] = _bundle(conn, ids["event"], state_version="v2")
        ids["judgment"] = repo.insert_judgment(conn, rows.NewJudgment(
            bundle_id=ids["bundle"], purpose="full", model="jev-latest",
            question_version="v2", request_json="{}", requested_at=U))
        ids["answer"] = repo.insert_answer(conn, rows.NewAnswer(
            judgment_id=ids["judgment"], question_id="direction", qtype="choice", value="up"))
        ids["heartbeat"] = repo.insert_heartbeat(conn, rows.NewHeartbeat(ts=U, process="fetcher", ok=1))
        ids["ledger"] = repo.insert_ledger_entry(conn, rows.NewLedgerEntry(
            day="2026-09-17", rows_added=1, prev_hash="0" * 64, chain_hash="1" * 64,
            schema_version=1, detail_json="{}", computed_at=U))
        ids["my_call"] = repo.insert_my_call(conn, rows.NewMyCall(
            bundle_id=ids["bundle"], decision="buy", decided_at=U))
    return ids


# --- スキーマと接続 -------------------------------------------------------

def test_migrate_creates_schema_with_18_triggers(db_path):
    """T01-01: schema.sql が適用され、トリガー18本・テーブル14個になる。"""
    assert db.migrate(db_path) == 1
    conn = db.connect(db_path)
    triggers = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='trigger' AND name GLOB 'trg_*'"
    ).fetchall()
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT GLOB 'sqlite_*'"
    ).fetchall()
    assert len(triggers) == 18
    assert len(tables) == 14
    conn.close()


def test_connect_sets_pragmas(conn):
    """T01-02: WAL・外部キー・再帰トリガー・synchronous=FULL・busy_timeout。"""
    def pragma(name):
        return conn.execute(f"PRAGMA {name}").fetchone()[0]

    assert pragma("journal_mode") == "wal"
    assert pragma("foreign_keys") == 1
    assert pragma("recursive_triggers") == 1
    assert pragma("synchronous") == 2
    assert pragma("busy_timeout") == 5000
    assert conn.isolation_level is None


def test_connect_refuses_uninitialized_db(tmp_path):
    """T01-03: DB が無い・空のときは init-db を促す。"""
    missing = tmp_path / "none.sqlite"
    with pytest.raises(SchemaMismatchError, match="init-db"):
        db.connect(missing)
    empty = tmp_path / "empty.sqlite"
    sqlite3.connect(str(empty)).close()
    with pytest.raises(SchemaMismatchError, match="init-db"):
        db.connect(empty)


def test_connect_refuses_newer_schema(db_path):
    """T01-04: DB の版がコードより新しければ止まる（古いコードで新しい DB を開かない）。"""
    db.migrate(db_path)
    raw = sqlite3.connect(str(db_path))
    raw.execute("INSERT INTO schema_version (version, applied_at) VALUES (99, ?)", (U,))
    raw.commit()
    raw.close()
    with pytest.raises(SchemaMismatchError):
        db.connect(db_path)
    with pytest.raises(SchemaMismatchError):
        db.migrate(db_path)


def test_connect_refuses_when_trigger_dropped(db_path):
    """T01-05: 追記専用トリガーが外されていたら起動しない（ADR 014）。"""
    db.migrate(db_path)
    raw = sqlite3.connect(str(db_path))
    raw.execute("DROP TRIGGER trg_events_no_update")
    raw.commit()
    raw.close()
    with pytest.raises(StoreError, match="17"):
        db.connect(db_path)


def test_migrate_is_idempotent(db_path):
    """T01-06: migrate を2回呼んでも版は1行のまま。"""
    assert db.migrate(db_path) == 1
    assert db.migrate(db_path) == 1
    conn = db.connect(db_path)
    assert queries.count_rows(conn, "schema_version") == 1
    conn.close()


# --- 追記専用 -------------------------------------------------------------

UPDATES = [
    ("events", "UPDATE events SET title = 'x'"),
    ("bundles", "UPDATE bundles SET session = 'intraday'"),
    ("judgments", "UPDATE judgments SET model = 'x'"),
    ("answers", "UPDATE answers SET value = 'down'"),
    ("heartbeat", "UPDATE heartbeat SET note = 'x'"),
    ("ledger", "UPDATE ledger SET rows_added = 2"),
    ("question_versions", "UPDATE question_versions SET json = 'x'"),
    ("state_versions", "UPDATE state_versions SET spec = 'x'"),
    ("my_calls", "UPDATE my_calls SET decision = 'skip'"),
]


@pytest.mark.parametrize("table,sql", UPDATES)
def test_update_rejected_on_all_frozen_tables(conn, table, sql):
    """T01-07: 9テーブルすべてで UPDATE がトリガーに落とされる。"""
    seed(conn)
    with pytest.raises(db.IntegrityError, match=f"append-only: {table}"):
        conn.execute(sql)


@pytest.mark.parametrize("table", [t for t, _ in UPDATES])
def test_delete_rejected_on_all_frozen_tables(conn, table):
    """T01-08: 9テーブルすべてで DELETE がトリガーに落とされる。"""
    seed(conn)
    with pytest.raises(db.IntegrityError, match=f"append-only: {table}"):
        conn.execute(f"DELETE FROM {table}")


def test_insert_or_replace_rejected_on_all_frozen_tables(conn):
    """T01-09: INSERT OR REPLACE は暗黙の DELETE がトリガーに掛かり、元の行が残る。"""
    ids = seed(conn)
    with pytest.raises(db.IntegrityError, match="append-only: events"):
        conn.execute(
            "INSERT OR REPLACE INTO events "
            "(event_id, code, title, published_at, received_at, pdf_status) "
            "VALUES (?, '99999', 'すり替え', ?, ?, 'none')",
            (ids["event"], U, U),
        )
    row = conn.execute("SELECT code, title FROM events WHERE event_id = ?", (ids["event"],)).fetchone()
    assert row["code"] == "35600" and "すり替え" not in row["title"]
    with pytest.raises(db.IntegrityError, match="append-only: my_calls"):
        conn.execute(
            "INSERT OR REPLACE INTO my_calls (my_call_id, bundle_id, decision, decided_at) "
            "VALUES (?, ?, 'skip', ?)",
            (ids["my_call"], ids["bundle"], U),
        )


UPSERTS = [
    ("events",
     "INSERT INTO events (code, title, published_at, received_at, pdf_status, pdf_sha256) "
     "VALUES ('35600', 't', :u, :u, 'ok', :sha) "
     "ON CONFLICT (pdf_sha256) DO UPDATE SET title = 'x'"),
    ("answers",
     "INSERT INTO answers (judgment_id, question_id, qtype) VALUES (:judgment, 'direction', 'choice') "
     "ON CONFLICT (judgment_id, question_id) DO UPDATE SET value = 'x'"),
    ("ledger",
     "INSERT INTO ledger (day, rows_added, prev_hash, chain_hash, schema_version, detail_json, computed_at) "
     "VALUES ('2026-09-17', 9, :zero, :one, 1, '{}', :u) "
     "ON CONFLICT (day) DO UPDATE SET rows_added = 9"),
    ("question_versions",
     "INSERT INTO question_versions (version, json, sha256, frozen_at) VALUES ('v2', 'x', :sha, :u) "
     "ON CONFLICT (version) DO UPDATE SET json = 'x'"),
    ("state_versions",
     "INSERT INTO state_versions (version, spec, sha256, frozen_at) VALUES ('v2', 'x', :sha, :u) "
     "ON CONFLICT (version) DO UPDATE SET spec = 'x'"),
    ("my_calls",
     "INSERT INTO my_calls (bundle_id, decision, decided_at) VALUES (:bundle, 'skip', :u) "
     "ON CONFLICT (bundle_id, decided_at) DO UPDATE SET decision = 'skip'"),
]


@pytest.mark.parametrize("table,sql", UPSERTS)
def test_upsert_rejected_on_all_frozen_tables(conn, table, sql):
    """T01-10: UNIQUE を持つ表への upsert も append-only で落ちる。"""
    ids = seed(conn)
    params = {"u": U, "sha": SHA_A, "zero": "0" * 64, "one": "1" * 64,
              "judgment": ids["judgment"], "bundle": ids["bundle"]}
    with pytest.raises(db.IntegrityError, match=f"append-only: {table}"):
        conn.execute(sql, params)


def test_repo_exposes_only_inserts():
    """T01-11: repo の公開名は insert_ だけ。書き換えの SQL トークンを持たない。"""
    public = {name for name in dir(repo) if not name.startswith("_")}
    assert public == set(repo.__all__)
    assert all(name.startswith("insert_") for name in public)
    source = "\n".join(
        line for line in inspect.getsource(repo).splitlines()
        if not line.lstrip().startswith("#")
    )
    assert re.search(r"\b(UPDATE|DELETE|REPLACE|ON CONFLICT)\b", source) is None


def test_queries_has_no_write_tokens():
    """T01-12: queries は読み取りだけ。"""
    assert re.search(r"\b(INSERT|UPDATE|DELETE|REPLACE)\b", inspect.getsource(queries)) is None


# --- 列の制約 -------------------------------------------------------------

def test_pdf_sha256_unique_but_null_repeatable(conn):
    """T01-13: 同一表題でも PDF が違えば別 event。取得失敗（NULL）は何行でも入る。"""
    body = read_fixture("4935_liberta_3days_bundle.txt")
    title = "借入に関するお知らせ"
    with db.transaction(conn):
        for sha in (SHA_A, SHA_B):
            _event(conn, code="49350", title=title, pdf_status="ok", pdf_sha256=sha,
                   body_text=body, body_chars=len(body))
        for _ in range(2):
            _event(conn, code="49350", title=title, pdf_status="failed", pdf_sha256=None)
    assert queries.count_rows(conn, "events") == 4
    with pytest.raises(db.IntegrityError, match="UNIQUE"):
        with db.transaction(conn):
            _event(conn, code="49350", title=title, pdf_status="ok", pdf_sha256=SHA_A)
    assert queries.count_rows(conn, "events") == 4


def test_large_body_text_roundtrip(conn):
    """T01-14: 28万字の報告書を本文のまま往復できる（バイト数と文字数を取り違えない）。"""
    text = read_fixture("9502_chubu_report_full.txt")
    assert len(text) == 283_113
    with db.transaction(conn):
        event_id = _event(conn, code="95020", title="調査報告書の公表（１／３）",
                          pdf_status="ok", pdf_sha256=SHA_A, body_text=text, body_chars=len(text))
    row = conn.execute("SELECT body_text, body_chars FROM events WHERE event_id = ?", (event_id,)).fetchone()
    assert row["body_text"] == text
    assert row["body_chars"] == 283_113


def test_excluded_bundle_requires_skip_reason(conn):
    """T01-15: excluded と skip_reason は同時にだけ立つ（ETF の約款変更で確認）。"""
    title = read_fixture("1369_one_etf_terms.txt").splitlines()[7].strip()
    assert "投資信託約款" in title
    with db.transaction(conn):
        event_id = _event(conn, code="13694", title=title)
        _bundle(conn, event_id, code="13694", bundle_role="excluded",
                skip_reason="excluded_instrument")
    for role, reason in [("excluded", None), ("normal", "excluded_title")]:
        with pytest.raises(db.IntegrityError, match="CHECK constraint failed"):
            with db.transaction(conn):
                _bundle(conn, event_id, code="13694", bundle_role=role, skip_reason=reason)


def _bad_code(conn, ids):
    _event(conn, code="3560")


def _bad_published(conn, ids):
    _event(conn, published_at="2026-09-17T08:30:00Z")


def _bad_received(conn, ids):
    _event(conn, received_at="2026-09-17T08:30:00")


def _bad_pdf_status(conn, ids):
    _event(conn, pdf_status="missing")


def _bad_session(conn, ids):
    _bundle(conn, ids["event"], session="noon")


def _bad_role(conn, ids):
    _bundle(conn, ids["event"], bundle_role="low")


def _bad_purpose(conn, ids):
    repo.insert_judgment(conn, rows.NewJudgment(
        bundle_id=ids["bundle"], purpose="retry", model="jev-latest",
        question_version="v2", request_json="{}", requested_at=U))


def _bad_qtype(conn, ids):
    repo.insert_answer(conn, rows.NewAnswer(
        judgment_id=ids["judgment"], question_id="impact", qtype="text"))


def _bad_decision(conn, ids):
    repo.insert_my_call(conn, rows.NewMyCall(bundle_id=ids["bundle"], decision="hold", decided_at=V))


def _bad_ok(conn, ids):
    repo.insert_heartbeat(conn, rows.NewHeartbeat(ts=U, process="fetcher", ok=2))


def _bad_day(conn, ids):
    repo.insert_ledger_entry(conn, rows.NewLedgerEntry(
        day="2026/09/17", rows_added=1, prev_hash="0" * 64, chain_hash="1" * 64,
        schema_version=1, detail_json="{}", computed_at=U))


def _bad_sha(conn, ids):
    repo.insert_question_version(conn, rows.NewQuestionVersion("v3", "{}", "a" * 63, U))


@pytest.mark.parametrize("case", [
    _bad_code, _bad_published, _bad_received, _bad_pdf_status, _bad_session, _bad_role,
    _bad_purpose, _bad_qtype, _bad_decision, _bad_ok, _bad_day, _bad_sha,
], ids=lambda f: f.__name__)
def test_check_constraints_reject_invalid_values(conn, case):
    """T01-16: 列挙値・時刻書式・コード長・0/1 フラグ・SHA 長の CHECK が効く。"""
    ids = seed(conn)
    with pytest.raises(db.IntegrityError, match="CHECK constraint failed"):
        with db.transaction(conn):
            case(conn, ids)


def test_fixture_bundle_via_synthetic_event(conn):
    """T01-17: 週次再判定の合成行は source='fixture'。未知の source は入らない（ADR 015）。"""
    text = read_fixture("3560_hobonichi_fiscal_year_change.txt")
    with db.transaction(conn):
        event_id = _event(conn, source="fixture", pdf_status="none",
                          body_text=text, body_chars=len(text))
        _bundle(conn, event_id, bundle_role="fixture")
    assert queries.count_rows(conn, "bundles") == 1
    with pytest.raises(db.IntegrityError, match="CHECK constraint failed"):
        with db.transaction(conn):
            _event(conn, source="playground")


def test_judgment_requires_frozen_question_version(conn):
    """T01-18: 未凍結の問い版では判定を残せない（ADR 020 を DB でも担保）。"""
    ids = seed(conn)
    with db.transaction(conn):
        repo.insert_judgment(conn, rows.NewJudgment(
            bundle_id=ids["bundle"], purpose="full", model="jev-preview",
            question_version="v2", request_json="{}", requested_at=U))
    with pytest.raises(db.IntegrityError, match="FOREIGN KEY"):
        with db.transaction(conn):
            repo.insert_judgment(conn, rows.NewJudgment(
                bundle_id=ids["bundle"], purpose="full", model="jev-latest",
                question_version="v9", request_json="{}", requested_at=U))


def test_answers_unique_per_question(conn):
    """T01-19: 1判定に同じ問いの答えは1つだけ。"""
    ids = seed(conn)
    with db.transaction(conn):
        second = repo.insert_answer(conn, rows.NewAnswer(
            judgment_id=ids["judgment"], question_id="impact", qtype="score", probability=0.5))
    assert second == ids["answer"] + 1
    with pytest.raises(db.IntegrityError, match="UNIQUE"):
        with db.transaction(conn):
            repo.insert_answer(conn, rows.NewAnswer(
                judgment_id=ids["judgment"], question_id="direction", qtype="choice", value="down"))


def test_heartbeat_allows_same_second_rows(conn):
    """T01-20: 同一秒に同じプロセスが2行書ける（再起動連発を事実として残す）。"""
    with db.transaction(conn):
        repo.insert_heartbeat(conn, rows.NewHeartbeat(ts=U, process="fetcher", ok=1))
        repo.insert_heartbeat(conn, rows.NewHeartbeat(ts=U, process="fetcher", ok=0, note="再起動"))
    recent = queries.recent_heartbeat(conn, "fetcher", 3)
    assert len(recent) == 2
    assert [r["ok"] for r in recent] == [0, 1]
    assert [r["ts"] for r in recent] == [U, U]


def test_supersedes_fk_and_current_bundle(conn):
    """T01-21: 訂正は supersedes_id で繋ぐ。現在の bundle は連鎖の末尾。"""
    ids = seed(conn)
    a = ids["bundle"]
    with db.transaction(conn):
        b = _bundle(conn, ids["event"], supersedes_id=a)
    with pytest.raises(db.IntegrityError, match="FOREIGN KEY"):
        with db.transaction(conn):
            _bundle(conn, ids["event"], supersedes_id=999)
    assert queries.current_bundle(conn, a)["bundle_id"] == b
    assert queries.current_bundle(conn, b)["bundle_id"] == b
    assert queries.is_superseded(conn, a) is True
    assert queries.is_superseded(conn, b) is False


# --- 並行アクセス ---------------------------------------------------------

def test_concurrent_writer_waits_then_fails(conn, db_path):
    """T01-22: 書き込みが競合したら待って失敗する（黙って捨てない）。"""
    other = db.connect(db_path)
    other.execute("PRAGMA busy_timeout=200")
    try:
        with db.transaction(conn):
            repo.insert_heartbeat(conn, rows.NewHeartbeat(ts=U, process="fetcher", ok=1))
            started = time.monotonic()
            with pytest.raises(db.OperationalError, match="locked"):
                with db.transaction(other):
                    repo.insert_heartbeat(other, rows.NewHeartbeat(ts=U, process="bundler", ok=1))
            elapsed = time.monotonic() - started
        assert elapsed >= 0.15
        with db.transaction(other):
            repo.insert_heartbeat(other, rows.NewHeartbeat(ts=U, process="bundler", ok=1))
        assert queries.count_rows(other, "heartbeat") == 2
    finally:
        other.close()


def test_committed_rows_visible_to_other_connection(conn, db_path):
    """T01-23: コミット前は見えず、コミット後は別接続から見える。"""
    reader = db.connect(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        repo.insert_heartbeat(conn, rows.NewHeartbeat(ts=U, process="fetcher", ok=1))
        assert queries.count_rows(reader, "heartbeat") == 0
        conn.execute("COMMIT")
        assert queries.count_rows(reader, "heartbeat") == 1
    finally:
        reader.close()


def test_repo_does_not_commit(conn):
    """T01-24: repo は commit しない。例外なら巻き戻る。入れ子の transaction は不可。"""
    with pytest.raises(RuntimeError):
        with db.transaction(conn):
            repo.insert_heartbeat(conn, rows.NewHeartbeat(ts=U, process="fetcher", ok=1))
            raise RuntimeError("途中で失敗")
    assert queries.count_rows(conn, "heartbeat") == 0
    with db.transaction(conn):
        with pytest.raises(db.ProgrammingError):
            with db.transaction(conn):
                pass


def test_migration_files_are_well_formed():
    """T01-25: マイグレーションは 002 から欠番なく、行を書き換えない（M1 では0件）。"""
    directory = Path(db.__file__).parent / "migrations"
    assert directory.is_dir()
    files = sorted(directory.glob("*.sql"))
    numbers = []
    for path in files:
        m = re.fullmatch(r"([0-9]{3})_[a-z0-9_]+\.sql", path.name)
        assert m is not None, path.name
        numbers.append(int(m.group(1)))
        text = path.read_text(encoding="utf-8").strip()
        assert text.startswith("BEGIN IMMEDIATE;")
        assert text.endswith("COMMIT;")
        assert len(re.findall(r"INSERT INTO schema_version", text)) == 1
        body = "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("--"))
        assert re.search(r"\b(UPDATE|DELETE)\b", body, re.IGNORECASE) is None
    assert numbers == list(range(2, 2 + len(numbers)))
    assert set(db._load_scripts()) == {1} | set(numbers)


# --- 版の凍結 -------------------------------------------------------------

def test_freeze_version_inserts_then_noop_then_rejects(conn):
    """T01-26: 同じ版は1行だけ。本文が違えば拒否して DB に触らない（ADR 020）。"""
    path = CONFIG_DIR / "questions.v2.json"
    text = path.read_text(encoding="utf-8")
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    assert freeze.freeze_version(conn, table="question_versions", version="v2",
                                 text=text, sha256=sha, now=U) == ("frozen", sha, U)
    assert freeze.freeze_version(conn, table="question_versions", version="v2",
                                 text=text, sha256=sha, now=V) == ("already", sha, U)
    other = text.replace("状況", "状況 ", 1)
    other_sha = hashlib.sha256(other.encode("utf-8")).hexdigest()
    with pytest.raises(ConfigError) as err:
        freeze.freeze_version(conn, table="question_versions", version="v2",
                              text=other, sha256=other_sha, now=V)
    assert sha in str(err.value) and other_sha in str(err.value)
    assert queries.count_rows(conn, "question_versions") == 1
    assert queries.get_question_version(conn, "v2")["json"] == text


def test_freeze_version_retries_once_on_unique_conflict(conn, monkeypatch):
    """T01-27: 並行凍結で先を越されたら1回やり直し、already を返す。"""
    path = CONFIG_DIR / "questions.v2.json"
    text = path.read_text(encoding="utf-8")
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    with db.transaction(conn):
        repo.insert_question_version(conn, rows.NewQuestionVersion("v2", text, sha, U))

    real = queries.get_question_version
    calls = {"n": 0}

    def flaky(connection, version):
        calls["n"] += 1
        return None if calls["n"] == 1 else real(connection, version)

    monkeypatch.setattr(queries, "get_question_version", flaky)
    assert freeze.freeze_version(conn, table="question_versions", version="v2",
                                 text=text, sha256=sha, now=V) == ("already", sha, U)
    assert calls["n"] == 2

    monkeypatch.setattr(queries, "get_question_version", lambda connection, version: None)
    with pytest.raises(db.IntegrityError):
        freeze.freeze_version(conn, table="question_versions", version="v2",
                              text=text, sha256=sha, now=V)
    assert queries.count_rows(conn, "question_versions") == 1


def test_schema_sql_matches_design():
    """受入表の外（01-凍結ログ 9章の完了条件の自動化）：schema.sql が詳細設計 4.3 と一字一句一致する。"""
    doc = (REPO_ROOT / "docs" / "detailed" / "01-凍結ログ.md").read_text(encoding="utf-8")
    blocks = re.findall(r"```sql\n(.*?)```", doc, re.DOTALL)
    assert len(blocks) == 1
    actual = (Path(db.__file__).parent / "schema.sql").read_text(encoding="utf-8")
    assert actual == blocks[0]
