"""03-CLI 8章の受入テスト（T03-01〜22）。"""

import json
import logging
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import CONFIG_DIR, CONTRACTS_DIR, REPO_ROOT
from test_bundle import ROWS_17, insert_events, pick, views

from jevfwd import cli
from jevfwd.common.logutil import HANDLER_NAME
from jevfwd.common.timeutil import is_utc_str
from jevfwd.store import db, freeze, queries

V1_SHA = "14a8baac5898235be756d1c4265fc39541adf13108d9bbc04a445cabf65bd2e7"
V2_SHA = "3f7b661012e0ab94c22f3012bb76a72cc2a03cd086e26b5208fc5b6455f6bcb0"
U = "2026-09-17T08:30:00+00:00"
SUBCOMMANDS = (
    "init-db", "fetch", "bundle", "judge", "heartbeat", "digest",
    "market-cache", "score", "paper", "report", "freeze-questions", "freeze-state",
)


@pytest.fixture(autouse=True)
def _clean_logging():
    """テスト間でロガーのハンドラを持ち越さない。"""
    yield
    root = logging.getLogger()
    for handler in [h for h in root.handlers if getattr(h, "name", None) == HANDLER_NAME]:
        root.removeHandler(handler)
    for f in list(root.filters):
        root.removeFilter(f)


def _write_cfg(tmp_path: Path, contracts_dir: Path | None = None, extra: str = "") -> str:
    path = tmp_path / "settings.yaml"
    path.write_text(
        "paths:\n"
        f"  config_dir: {CONFIG_DIR}\n"
        f"  contracts_dir: {contracts_dir or tmp_path / 'contracts'}\n"
        "storage:\n"
        f"  db_path: {tmp_path / 'db.sqlite'}\n" + extra,
        encoding="utf-8",
    )
    return str(path)


@pytest.fixture
def cfg(tmp_path) -> str:
    return _write_cfg(tmp_path)


@pytest.fixture
def run(capsys):
    """main([...]) を呼び (戻り値, stdout, stderr) を返す。argparse の SystemExit も拾う。"""
    def _run(*args):
        try:
            code = cli.main(list(args))
        except SystemExit as e:                       # --help / --version / 引数エラー
            code = e.code if isinstance(e.code, int) else 1
        captured = capsys.readouterr()
        return code, captured.out, captured.err
    return _run


def _count(tmp_path: Path, table: str) -> int:
    path = tmp_path / "db.sqlite"
    if not path.exists():
        return 0
    conn = db.connect(path)
    try:
        return queries.count_rows(conn, table)
    finally:
        conn.close()


# --- 引数とサブコマンド ---------------------------------------------------

def test_help_lists_all_subcommands(run):
    """T03-01: 未実装のものも含めて12のサブコマンドが --help に出る。"""
    code, out, _ = run("--help")
    assert code == 0
    for name in SUBCOMMANDS:
        assert name in out, name


def test_unknown_subcommand_exit_2(run):
    """T03-02: 知らないサブコマンドは引数エラー。"""
    code, _, err = run("frobnicate")
    assert code == 2
    assert "invalid choice" in err


def test_no_subcommand_exit_2(run):
    """T03-03: サブコマンド無しは引数エラー。"""
    assert run()[0] == 2


@pytest.mark.parametrize("name,milestone,doc", cli.STUBS, ids=[s[0] for s in cli.STUBS])
def test_stub_subcommands_exit_1_with_milestone(run, cfg, name, milestone, doc):
    """T03-04: 未実装は黙って成功せず、どのマイルストーンで実装するかを言う。"""
    # M3 で bundle を実装したのでスタブは8本（03-CLI 3.7）
    assert len(cli.STUBS) == 8 and "bundle" not in {s[0] for s in cli.STUBS}
    code, out, err = run("--config", cfg, name)
    assert code == 1
    assert "未実装" in err and milestone in err
    assert out == ""


def test_version_flag(run):
    """T03-05: --version は jevfwd 0.1.0。"""
    code, out, _ = run("--version")
    assert code == 0
    assert out.startswith("jevfwd 0.1.0")


# --- init-db --------------------------------------------------------------

def test_init_db_creates_and_is_idempotent(run, cfg, tmp_path):
    """T03-06: 冪等。トリガー18本と schema_version 1行ができる。"""
    for _ in range(2):
        code, out, _ = run("--config", cfg, "init-db")
        assert code == 0
        assert "schema_version=1" in out
    assert _count(tmp_path, "schema_version") == 1
    conn = db.connect(tmp_path / "db.sqlite")
    try:
        triggers = conn.execute(
            "SELECT count(*) AS n FROM sqlite_master WHERE type='trigger' AND name GLOB 'trg_*'"
        ).fetchone()["n"]
    finally:
        conn.close()
    assert triggers == 18


def test_missing_config_exit_1(run):
    """T03-18: 設定ファイルが無ければパス付きで落とす。"""
    code, _, err = run("--config", "/nonexistent.yaml", "init-db")
    assert code == 1
    assert "/nonexistent.yaml" in err


def test_env_config_used_when_flag_absent(run, cfg, tmp_path, monkeypatch):
    """T03-19: --config が無ければ $JEVFWD_CONFIG を見る。"""
    monkeypatch.setenv("JEVFWD_CONFIG", cfg)
    assert run("init-db")[0] == 0
    assert (tmp_path / "db.sqlite").exists()


# --- freeze-questions -----------------------------------------------------

def test_freeze_questions_before_init_db_exit_3(run, cfg, tmp_path):
    """T03-07: DB が無ければ終了コード3（init-db を促す）。"""
    code, _, err = run("--config", cfg, "freeze-questions", "--version", "v2")
    assert code == 3
    assert "init-db" in err


def test_freeze_questions_v2_inserts_row(run, cfg, tmp_path):
    """T03-08: 本文をそのまま凍結し、1行の key=value で報告する（事前宣言に貼る行）。"""
    run("--config", cfg, "init-db")
    code, out, _ = run("--config", cfg, "freeze-questions", "--version", "v2")
    assert code == 0
    assert out.startswith(f"frozen question_version=v2 sha256={V2_SHA} frozen_at=")
    assert _count(tmp_path, "question_versions") == 1
    conn = db.connect(tmp_path / "db.sqlite")
    try:
        row = queries.get_question_version(conn, "v2")
    finally:
        conn.close()
    assert row["json"] == (CONFIG_DIR / "questions.v2.json").read_text(encoding="utf-8")
    assert is_utc_str(row["frozen_at"])


def test_freeze_questions_rerun_is_noop(run, cfg, tmp_path):
    """T03-09: 2回目は already frozen。frozen_at は1回目のまま。"""
    run("--config", cfg, "init-db")
    _, first, _ = run("--config", cfg, "freeze-questions", "--version", "v2")
    code, second, _ = run("--config", cfg, "freeze-questions", "--version", "v2")
    assert code == 0
    assert second.startswith("already frozen question_version=v2")
    assert second.split("frozen_at=")[1] == first.split("frozen_at=")[1]
    assert _count(tmp_path, "question_versions") == 1


def test_freeze_questions_v1_too(run, cfg):
    """T03-10: v1（主語固定文なし）も凍結できる。"""
    run("--config", cfg, "init-db")
    code, out, _ = run("--config", cfg, "freeze-questions", "--version", "v1")
    assert code == 0
    assert f"sha256={V1_SHA}" in out


def test_freeze_questions_mismatch_exit_1_no_insert(run, cfg, tmp_path):
    """T03-11: 同じ版で本文が違えば拒否し、DB は変えない（版ファイルは不変）。"""
    run("--config", cfg, "init-db")
    run("--config", cfg, "freeze-questions", "--version", "v2")
    original = (CONFIG_DIR / "questions.v2.json").read_text(encoding="utf-8")
    tampered = tmp_path / "questions.v2.json"
    tampered.write_text(original.replace("v1からの変更", "v1からの変更 "), encoding="utf-8")
    code, _, err = run("--config", cfg, "freeze-questions", "--version", "v2",
                       "--file", str(tampered))
    assert code == 1
    assert "凍結済み" in err and V2_SHA in err
    assert _count(tmp_path, "question_versions") == 1
    conn = db.connect(tmp_path / "db.sqlite")
    try:
        assert queries.get_question_version(conn, "v2")["json"] == original
    finally:
        conn.close()


def test_freeze_questions_missing_file_exit_1(run, cfg, tmp_path):
    """T03-12: 無い版ファイルはパス付きで落とし、行は作らない。"""
    run("--config", cfg, "init-db")
    code, _, err = run("--config", cfg, "freeze-questions", "--version", "v9")
    assert code == 1
    assert "questions.v9.json" in err
    assert _count(tmp_path, "question_versions") == 0


def test_freeze_questions_version_mismatch_exit_1(run, cfg, tmp_path):
    """T03-13: ファイル名の版と _version が食い違えば DB に触らない。"""
    run("--config", cfg, "init-db")
    copy = tmp_path / "questions.v3.json"
    copy.write_text((CONFIG_DIR / "questions.v2.json").read_text(encoding="utf-8"), encoding="utf-8")
    code, _, err = run("--config", cfg, "freeze-questions", "--version", "v3", "--file", str(copy))
    assert code == 1
    assert "_version=v2" in err
    assert _count(tmp_path, "question_versions") == 0


def test_freeze_questions_bom_rejected(run, cfg, tmp_path):
    """T03-14: BOM つきは受け付けない（生保存した本文がファイルと一致しなくなる）。"""
    run("--config", cfg, "init-db")
    bom = tmp_path / "questions.v2.json"
    bom.write_bytes("﻿".encode("utf-8") + (CONFIG_DIR / "questions.v2.json").read_bytes())
    code, _, err = run("--config", cfg, "freeze-questions", "--version", "v2", "--file", str(bom))
    assert code == 1
    assert "BOM" in err
    assert _count(tmp_path, "question_versions") == 0


def test_freeze_concurrent_conflict_surfaces_as_already(run, cfg, monkeypatch):
    """T03-20: 並行凍結で先を越されたときは already frozen として 0 を返す。"""
    run("--config", cfg, "init-db")
    monkeypatch.setattr(freeze, "freeze_version",
                        lambda *a, **kw: ("already", V2_SHA, U))
    code, out, _ = run("--config", cfg, "freeze-questions", "--version", "v2")
    assert code == 0
    assert out.startswith("already frozen question_version=v2")


# --- freeze-state ---------------------------------------------------------

def test_freeze_state_v2_real_schema(run, tmp_path):
    """T03-15: 実物の state.v2.schema.json を本文のまま凍結できる。"""
    cfg = _write_cfg(tmp_path, contracts_dir=CONTRACTS_DIR)
    run("--config", cfg, "init-db")
    code, out, _ = run("--config", cfg, "freeze-state", "--version", "v2")
    assert code == 0
    assert out.startswith("frozen state_version=v2 sha256=")
    conn = db.connect(tmp_path / "db.sqlite")
    try:
        row = queries.get_state_version(conn, "v2")
    finally:
        conn.close()
    assert row["spec"] == (CONTRACTS_DIR / "state.v2.schema.json").read_text(encoding="utf-8")
    assert run("--config", cfg, "freeze-state", "--version", "v2")[1].startswith("already frozen")


def test_freeze_state_with_tmp_schema(run, cfg, tmp_path):
    """T03-16: 最小のスキーマでも同じ手順で凍結できる。"""
    contracts = tmp_path / "contracts"
    contracts.mkdir()
    schema = contracts / "state.v2.schema.json"
    schema.write_text(json.dumps(
        {"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object"}), encoding="utf-8")
    run("--config", cfg, "init-db")
    code, out, _ = run("--config", cfg, "freeze-state", "--version", "v2")
    assert code == 0 and out.startswith("frozen state_version=v2 sha256=")
    assert run("--config", cfg, "freeze-state", "--version", "v2")[1].startswith("already frozen")
    assert _count(tmp_path, "state_versions") == 1
    conn = db.connect(tmp_path / "db.sqlite")
    try:
        assert queries.get_state_version(conn, "v2")["spec"] == schema.read_text(encoding="utf-8")
    finally:
        conn.close()


@pytest.mark.parametrize("body", ["[]", "{}"], ids=["array", "no_schema_key"])
def test_freeze_state_rejects_non_schema(run, cfg, tmp_path, body):
    """T03-17: object かつ $schema があるものだけ凍結する。"""
    contracts = tmp_path / "contracts"
    contracts.mkdir(exist_ok=True)
    (contracts / "state.v2.schema.json").write_text(body, encoding="utf-8")
    run("--config", cfg, "init-db")
    code, _, err = run("--config", cfg, "freeze-state", "--version", "v2")
    assert code == 1
    assert "JSON Schema" in err
    assert _count(tmp_path, "state_versions") == 0


# --- 実行形態とログ -------------------------------------------------------

def test_module_entry_point():
    """T03-21: python -m jevfwd.cli でも動く。"""
    proc = subprocess.run([sys.executable, "-m", "jevfwd.cli", "--version"],
                          capture_output=True, text=True, cwd=REPO_ROOT)
    assert proc.returncode == 0
    assert proc.stdout.startswith("jevfwd 0.1.0")


def test_logging_masks_secrets(run, cfg, capsys, monkeypatch):
    """T03-22: --log-level DEBUG でも秘密は出ない。"""
    monkeypatch.setenv("TYPESAFE_API_KEY", "sk-test-XYZ")
    assert run("--config", cfg, "--log-level", "DEBUG", "init-db")[0] == 0
    logging.getLogger().info("key=%s", "sk-test-XYZ")
    out = capsys.readouterr().out
    assert "sk-test-XYZ" not in out
    assert "key=***" in out


# --- bundle（M3） ---------------------------------------------------------

def test_bundle_once_creates_bundle_with_state(run, tmp_path):
    """T03-23: fixture の events から bundle が1行でき、state_json が入る。"""
    # fixture の公表時刻（2026-09-17）は既定の scan_lookback_sec（3日）より古い
    cfg = _write_cfg(
        tmp_path, contracts_dir=CONTRACTS_DIR, extra="bundle:\n  scan_lookback_sec: 31536000\n"
    )
    run("--config", cfg, "init-db")
    run("--config", cfg, "freeze-state", "--version", "v2")   # state_version は外部キー
    conn = db.connect(tmp_path / "db.sqlite")
    try:
        insert_events(conn, views(pick(ROWS_17, "35600", "17:30")))
    finally:
        conn.close()

    code, out, err = run("--config", cfg, "bundle", "--once")
    assert code == 0, err
    assert out.startswith("bundles=1 ids=")

    conn = db.connect(tmp_path / "db.sqlite")
    try:
        row = conn.execute("SELECT * FROM bundles").fetchone()
    finally:
        conn.close()
    state = json.loads(row["state_json"])
    assert row["state_version"] == "v2"
    assert row["state_chars"] == len(row["state_json"])
    assert state["issuer"]["code"] == "3560"
    assert state["primary"]["title"] == "業績予想の修正に関するお知らせ"
    assert json.loads(row["state_completeness_json"])["rules"]["state_version"] == "v2"

    assert run("--config", cfg, "bundle", "--once")[1] == "bundles=0 ids=\n"
