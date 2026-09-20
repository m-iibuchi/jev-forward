"""`python -m jevfwd.cli <subcommand>` と console script `jevfwd` の入口（詳細設計 03-CLI.md）。

引数解釈・設定の読み込み・DB 接続・終了コードの変換だけを行う。業務処理は各モジュールの関数を呼ぶ。
未実装のサブコマンドは「未実装（Mx で実装）」と言って終了コード 1 で止まる（黙って何もしない、を無くす）。
"""

import argparse
import functools
import json
import sys
from importlib import metadata
from pathlib import Path

from .common.errors import ConfigError, JevfwdError, SchemaMismatchError
from .common.hashing import sha256_hex
from .common.logutil import setup_logging
from .common.timeutil import now_utc, to_utc_str
from .judge import questions
from .settings import Secrets, Settings, load_settings, resolve_settings_path
from .store import db, freeze

PROG = "jevfwd"
LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2          # argparse 既定
EXIT_SCHEMA = 3         # init-db が必要（supervisord が再起動ループを止める判断に使う）
EXIT_INTERRUPTED = 130

# 未実装のサブコマンド：(名前, マイルストーン, 詳細設計)。実装したらここから外す
STUBS: tuple[tuple[str, str, str | None], ...] = (
    ("fetch", "M2", "docs/detailed/06-取得.md"),
    ("heartbeat", "M2", "docs/detailed/06-取得.md"),
    ("bundle", "M3", "docs/detailed/04-束ね.md と 05-state構築.md"),
    ("judge", "M4", "docs/detailed/07-判定.md"),
    ("market-cache", "M6", "docs/detailed/09-市場データ.md"),
    ("score", "M6", "docs/detailed/10-採点.md"),
    ("digest", "M7", "docs/detailed/11-ダイジェスト模擬執行.md"),
    ("paper", "M7", "docs/detailed/11-ダイジェスト模擬執行.md"),
    ("report", "M8", None),
)


def _version() -> str:
    try:
        return metadata.version("jevfwd")
    except metadata.PackageNotFoundError:      # 未インストール（ソースから直接実行）
        return "0.0.0+unknown"


def build_parser() -> argparse.ArgumentParser:
    """サブコマンドを全部登録した parser（未実装のものも --help に出す）。"""
    parser = argparse.ArgumentParser(prog=PROG, description="Jev判定フォワードテスト基盤")
    parser.add_argument("--config", help="settings.yaml の場所（既定は $JEVFWD_CONFIG か config/settings.yaml）")
    parser.add_argument("--log-level", default="INFO", choices=LOG_LEVELS)
    parser.add_argument("--version", action="version", version=f"{PROG} {_version()}")
    sub = parser.add_subparsers(dest="cmd", required=True, metavar="<subcommand>")

    sub.add_parser("init-db", help="schema を現在版まで前進させる（冪等）").set_defaults(func=cmd_init_db)

    fq = sub.add_parser("freeze-questions", help="問い版を question_versions に凍結する")
    fq.add_argument("--version", required=True, dest="ver", help="vN")
    fq.add_argument("--file", help="既定は <config_dir>/questions.vN.json")
    fq.set_defaults(func=cmd_freeze_questions)

    fs = sub.add_parser("freeze-state", help="state の JSON Schema を state_versions に凍結する")
    fs.add_argument("--version", required=True, dest="ver", help="vN")
    fs.add_argument("--file", help="既定は <contracts_dir>/state.vN.schema.json")
    fs.set_defaults(func=cmd_freeze_state)

    for name, milestone, doc in STUBS:
        stub = sub.add_parser(name, help=f"{milestone} で実装")
        stub.set_defaults(func=functools.partial(cmd_stub, name=name, milestone=milestone, doc=doc))
    return parser


def main(argv: list[str] | None = None) -> int:
    """終了コードを返す。sys.exit するのは __main__ と console script だけ。"""
    args = build_parser().parse_args(argv)
    secrets = Secrets.from_env()
    setup_logging(args.log_level, secrets.values())
    try:
        settings = load_settings(resolve_settings_path(args.config))
        return args.func(args, settings)
    except SchemaMismatchError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return EXIT_SCHEMA
    except NotImplementedError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return EXIT_ERROR
    except JevfwdError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return EXIT_ERROR
    except db.IntegrityError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return EXIT_ERROR
    except KeyboardInterrupt:
        return EXIT_INTERRUPTED


def cmd_init_db(args: argparse.Namespace, settings: Settings) -> int:
    """DB を作り、schema を現在版まで前進させる。"""
    version = db.migrate(settings.storage.db_path)
    print(f"schema_version={version} path={settings.storage.db_path}")
    return EXIT_OK


def _read_version_file(path: Path) -> tuple[str, str]:
    """(本文, ファイルバイト列の sha256)。BOM つきや UTF-8 でないものは ConfigError。"""
    if not path.exists():
        raise ConfigError(f"版ファイルがありません: {path}")
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as e:
        raise ConfigError(f"{path}: UTF-8（BOM なし）で保存してください") from e
    if text.startswith("﻿") or text.encode("utf-8") != raw:
        raise ConfigError(f"{path}: UTF-8（BOM なし）で保存してください")
    return text, sha256_hex(raw)


def _print_frozen(kind: str, status: str, version: str, sha: str, ts: str) -> None:
    label = "frozen" if status == "frozen" else "already frozen"
    print(f"{label} {kind}={version} sha256={sha} frozen_at={ts}")


def cmd_freeze_questions(args: argparse.Namespace, settings: Settings) -> int:
    """問い版ファイルを凍結する（ADR 020）。本文はそのまま保存する。"""
    path = Path(args.file) if args.file else settings.questions_path(args.ver)
    text, sha = _read_version_file(path)
    questions.parse(text, args.ver)                  # 形と _version の検証。失敗は DB に触らない
    conn = db.connect(settings.storage.db_path)      # 未初期化なら SchemaMismatchError
    try:
        status, sha, ts = freeze.freeze_version(
            conn, table="question_versions", version=args.ver,
            text=text, sha256=sha, now=to_utc_str(now_utc()))
    finally:
        conn.close()
    _print_frozen("question_version", status, args.ver, sha, ts)
    return EXIT_OK


def cmd_freeze_state(args: argparse.Namespace, settings: Settings) -> int:
    """state の JSON Schema を凍結する。"""
    path = Path(args.file) if args.file else settings.state_schema_path(args.ver)
    text, sha = _read_version_file(path)
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as e:
        raise ConfigError(f"{path}: JSON が読めません: {e}") from e
    if not isinstance(doc, dict) or "$schema" not in doc:
        raise ConfigError(f"{path}: JSON Schema（object、$schema あり）ではない")
    conn = db.connect(settings.storage.db_path)
    try:
        status, sha, ts = freeze.freeze_version(
            conn, table="state_versions", version=args.ver,
            text=text, sha256=sha, now=to_utc_str(now_utc()))
    finally:
        conn.close()
    _print_frozen("state_version", status, args.ver, sha, ts)
    return EXIT_OK


def cmd_stub(args: argparse.Namespace, settings: Settings, *, name: str, milestone: str,
             doc: str | None) -> int:
    """未実装のサブコマンド。黙って成功しない。"""
    where = f"{milestone} で実装。{doc}" if doc else f"{milestone} で実装"
    raise NotImplementedError(f"サブコマンド {name} は未実装（{where}）")


if __name__ == "__main__":
    sys.exit(main())
