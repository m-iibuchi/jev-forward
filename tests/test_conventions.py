"""00-共通規約 14.2 の受入テスト（T00-13〜19）。規約をコードで守らせる。"""

import ast
import re
from pathlib import Path

import pytest

from conftest import CONFIG_DIR, SRC_DIR

PACKAGE_DIR = SRC_DIR / "jevfwd"

# 00-共通規約 8章のモジュール境界表。行（from）が列（to）を import してよい
ALLOWED: dict[str, set[str]] = {
    "common": {"common"},
    "settings": {"common", "settings"},
    "store": {"common", "store"},
    "market": {"common", "settings", "store", "market"},
    "fetch": {"common", "settings", "store", "fetch"},
    "bundle": {"common", "settings", "store", "bundle"},
    "state": {"common", "settings", "store", "market", "state"},
    "judge": {"common", "settings", "store", "judge"},
    "monitor": {"common", "settings", "store", "monitor"},
    "digest": {"common", "settings", "store", "market", "digest"},
    "score": {"common", "settings", "store", "market", "score"},
    "paper": {"common", "settings", "store", "paper"},
    "cli": {
        "common", "settings", "store", "market", "fetch", "bundle", "state",
        "judge", "monitor", "digest", "score", "paper", "cli",
    },
}

FORBIDDEN_SQLITE = [
    r"\bRETURNING\b",       # SQLite 3.35
    r"\bSTRICT\b",          # 3.37
    r"->>",                 # 3.38
    r"INSERT\s+OR\s+REPLACE",
    r"INSERT\s+OR\s+IGNORE",
    r"ON\s+CONFLICT",
]


def _python_files() -> list[Path]:
    return sorted(PACKAGE_DIR.rglob("*.py"))


def _strip_comments(text: str, marker: str) -> str:
    return "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith(marker)
    )


def _module_parts(path: Path) -> tuple[str, ...]:
    return path.relative_to(PACKAGE_DIR).with_suffix("").parts


def _top_of(path: Path) -> str:
    parts = _module_parts(path)
    return "root" if parts == ("__init__",) else parts[0]


def _imported_tops(path: Path, tree: ast.AST) -> set[str]:
    parts = _module_parts(path)
    pkg = list(parts[:-1]) if parts[-1] == "__init__" else list(parts[:-1])
    if parts[-1] == "__init__":
        pkg = list(parts[:-1])
    tops: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "jevfwd" or alias.name.startswith("jevfwd."):
                    rest = alias.name.split(".")[1:]
                    if rest:
                        tops.add(rest[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                module = node.module or ""
                if not module.startswith("jevfwd"):
                    continue
                rest = module.split(".")[1:]
                tops.update([rest[0]] if rest else [a.name.split(".")[0] for a in node.names])
                continue
            base = pkg[: len(pkg) - (node.level - 1)] if node.level > 1 else list(pkg)
            resolved = base + (node.module.split(".") if node.module else [])
            if resolved:
                tops.add(resolved[0])
            else:
                tops.update(a.name.split(".")[0] for a in node.names)
    return tops


@pytest.mark.parametrize("pattern", FORBIDDEN_SQLITE)
def test_no_forbidden_sqlite_features(pattern):
    """T00-13: SQLite 3.31 で使えない構文を書かない（コメント行は除く）。"""
    hits = []
    for path in _python_files() + sorted(PACKAGE_DIR.rglob("*.sql")):
        marker = "--" if path.suffix == ".sql" else "#"
        body = _strip_comments(path.read_text(encoding="utf-8"), marker)
        if re.search(pattern, body, re.IGNORECASE):
            hits.append(str(path.relative_to(SRC_DIR)))
    assert hits == [], f"{pattern} を使っている: {hits}"


def test_import_boundaries():
    """T00-14: モジュール境界表（00-共通規約 8章）に無い import が無い。"""
    tops = {_top_of(p) for p in _python_files()} - {"root"}
    assert tops <= set(ALLOWED), f"境界表に無いトップレベル: {sorted(tops - set(ALLOWED))}"
    violations = []
    for path in _python_files():
        src = _top_of(path)
        if src == "root":
            continue
        for dst in _imported_tops(path, ast.parse(path.read_text(encoding="utf-8"))):
            if dst not in ALLOWED[src]:
                violations.append(f"{path.relative_to(SRC_DIR)}: {src} -> {dst}")
    assert violations == []


def test_sqlite3_only_in_store():
    """T00-15: sqlite3 を import してよいのは store だけ。"""
    hits = [
        str(p.relative_to(SRC_DIR))
        for p in _python_files()
        if re.search(r"^\s*(import sqlite3|from sqlite3)", p.read_text(encoding="utf-8"), re.M)
        and _top_of(p) != "store"
    ]
    assert hits == []


@pytest.mark.parametrize("token", ["datetime.now(", "datetime.utcnow(", "time.time("])
def test_no_datetime_now_in_business_modules(token):
    """T00-16: 現在時刻を読むのは common/timeutil.py だけ。"""
    hits = [
        str(p.relative_to(SRC_DIR))
        for p in _python_files()
        if token in p.read_text(encoding="utf-8")
        and p.relative_to(PACKAGE_DIR).as_posix() != "common/timeutil.py"
    ]
    assert hits == []


@pytest.mark.parametrize("token", ["os.environ", "os.getenv"])
def test_no_os_environ_outside_settings(token):
    """T00-17: 環境変数を読むのは settings.py だけ。"""
    hits = [
        str(p.relative_to(SRC_DIR))
        for p in _python_files()
        if token in p.read_text(encoding="utf-8")
        and p.relative_to(PACKAGE_DIR).as_posix() != "settings.py"
    ]
    assert hits == []


def test_every_module_has_docstring():
    """T00-18: すべてのモジュール（__init__.py を含む）に責務の docstring。"""
    missing = [
        str(p.relative_to(SRC_DIR))
        for p in _python_files()
        if not ast.get_docstring(ast.parse(p.read_text(encoding="utf-8")))
    ]
    assert missing == []


def test_versioned_config_files_unchanged():
    """T00-19: 版つき設定ファイルの一覧（削除・改名の検知）。SHA は T02-18 / T02-24。"""
    expected = {"questions.v1.json", "questions.v2.json"}   # セッション 1b で *.v1.yaml を足す
    found = {p.name for p in CONFIG_DIR.glob("*.v*.json")} | {
        p.name for p in CONFIG_DIR.glob("*.v*.yaml")
    }
    assert found == expected
