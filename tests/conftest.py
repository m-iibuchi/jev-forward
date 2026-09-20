"""テスト共通のヘルパ（00-共通規約 13章、04-束ね 8章）。

fixture は必ず read_text(encoding="utf-8") で読む（CRLF がユニバーサル改行で LF になる）。
"""

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"
CONFIG_DIR = REPO_ROOT / "config"
SRC_DIR = REPO_ROOT / "src"
CONTRACTS_DIR = REPO_ROOT / "docs" / "contracts"

# 開示本文の区切り。「各位」と「各 位」が混在する
_KAKUI_RE = re.compile(r"各\s*位\s*")
_DATE_HEADER_RE = re.compile(r"([0-9]{1,2})/([0-9]{1,2})（.+?）")
_RECORD_RE = re.compile(r"([0-9]{1,2}:[0-9]{2})\t(.*)", re.DOTALL)
_LIST_NAME_RE = re.compile(r"tdnet_list_([0-9]{4})-([0-9]{2})-([0-9]{2})(?:_([0-9]{2}))?\.tsv")


def read_fixture(name: str) -> str:
    """fixture を UTF-8 で読む（CRLF は LF になる）。"""
    return (FIXTURES / name).read_text(encoding="utf-8")


def split_disclosures(text: str) -> list[str]:
    """複数文書を連結した fixture を1件ずつに分ける（「各位」の行の1行前で切る）。"""
    lines = text.splitlines()
    cuts = [max(i - 1, 0) for i, line in enumerate(lines) if _KAKUI_RE.fullmatch(line)]
    if not cuts:
        return [text]
    cuts = sorted(set(cuts))
    if cuts[0] != 0:
        cuts.insert(0, 0)
    bounds = cuts + [len(lines)]
    return ["\n".join(lines[a:b]) for a, b in zip(bounds, bounds[1:]) if a < b]


@dataclass(frozen=True, slots=True)
class TdnetRow:
    """TDnet 新着一覧の1行（表をコピーした TSV から復元したもの）。"""

    date: str          # JST 暦日 YYYY-MM-DD
    time: str          # HH:MM
    code: str          # 5文字
    company: str
    title: str
    xbrl: bool
    market: str | None


def load_tdnet_tsv(path: str | Path) -> list[TdnetRow]:
    """TDnet 一覧の TSV を読む。XBRL 付きの行は折返しを再結合し、日付見出しで暦日を切り替える。"""
    path = Path(path)
    m = _LIST_NAME_RE.fullmatch(path.name)
    if m is None:
        raise ValueError(f"tdnet_list_YYYY-MM-DD[_DD].tsv ではない: {path.name}")
    year = int(m.group(1))
    current = date(year, int(m.group(2)), int(m.group(3)))

    rows: list[TdnetRow] = []
    head: str | None = None
    tail: list[str] = []

    def flush() -> None:
        if head is None:
            return
        fields = head.split("\t")
        rest = fields[4:] + [part for line in tail for part in line.split("\t")]
        cleaned = [p.strip() for p in rest if p.strip() and p.strip() != "　"]
        rows.append(
            TdnetRow(
                date=current.isoformat(),
                time=fields[0],
                code=fields[1],
                company=fields[2],
                title=fields[3],
                xbrl=any(p == "XBRL" for p in cleaned),
                market=next((p for p in cleaned if p != "XBRL"), None),
            )
        )

    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        header = _DATE_HEADER_RE.fullmatch(line.strip())
        if header is not None:
            flush()
            head, tail = None, []
            current = date(year, int(header.group(1)), int(header.group(2)))
            continue
        if line.startswith("時刻\t"):
            continue
        record = _RECORD_RE.fullmatch(line)
        if record is not None and record.group(2).count("\t") >= 2:
            flush()
            head, tail = line, []
        elif head is not None:
            tail.append(line)
    flush()
    return rows


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    """テスト用の DB ファイル。:memory: は WAL にならないので使わない。"""
    return tmp_path / "t.sqlite"
