"""本文の正規化と切り詰め（05-state構築 3.3・4.3〜4.5）。純関数だけ。

予算は**送信する JSON 文字列の長さ**で測る（ADR 026）。`ensure_ascii=False` でも
`"` と改行はエスケープされるので、1回の引き算では決まらない。測って削る。
"""

import json
import re

from ..common.errors import JevfwdError
from ..settings import StateCfg

# 切り詰め規則の改訂日。規則を変えたらここと state の版（v3）を一緒に上げる（4.4）
TRUNCATE_REV = "2026-09-20"

MAX_PASSES = 5                 # 収束しなければ JevfwdError（無限ループにしない）
MAX_HEADING_CHARS = 60         # 章見出しとみなす行の長さの上限（4.5）
MIN_LEADER_LINES = 20          # 目次のドットリーダー行がこれ以上なら報告書型（4.5）
_OVERSHOOT = 1.1               # エスケープぶんを見込んで多めに削る
_MARGIN = 32

HEADING = re.compile(r"^第[0-9０-９]+[ 　]\S")      # 第と数字の間に空白を入れない見出しだけ
LEADER = re.compile(r"\.{10,}|・{10,}|…{5,}")       # 目次のドットリーダー
PAGENO = re.compile(r"^[0-9]{1,3}$")                 # 章の前後に挟まる頁番号だけの行
SECTION_KEYS: tuple[str, ...] = ("原因", "評価", "結論", "結語", "再発防止", "提言")
# キーワードは章題の末尾側だけで探す。章の主題は終わりに来るので、長い章題の途中の語
# （「…地震動評価及び…認定した事実」）に誤爆しない（4.5、task 026）
SECTION_KEY_TAIL_CHARS = 12

_TRAILING_WS = re.compile(r"[ \t]+$", re.M)
_MANY_BLANKS = re.compile(r"\n{3,}")


def measure(state: dict) -> int:
    """送信する JSON 文字列の長さ（ADR 026）。"""
    return len(json.dumps(state, ensure_ascii=False))


def normalize_body(text: str) -> str:
    """改ページ `\\f` を空行に、行末空白を落とし、3連以上の空行を圧縮する（4.3）。"""
    out = text.replace("\f", "\n\n")
    out = _TRAILING_WS.sub("", out)
    out = _MANY_BLANKS.sub("\n\n", out)
    return out.strip()


def chapter_headings(body: str) -> list[tuple[int, str]]:
    """(行番号, 見出し) の配列。誤検知（`第 1 回…` `第一原子力…`）は拾わない（4.5）。"""
    return [
        (index, line.strip())
        for index, line in enumerate(body.splitlines())
        if HEADING.match(line) and len(line) < MAX_HEADING_CHARS
    ]


def is_report_like(body: str, cfg: StateCfg) -> bool:
    """調査報告書のような長い章立て文書か（4.5）。目次の見出し語では判定しない。"""
    if len(body) < cfg.report_min_chars:
        return False
    if len(chapter_headings(body)) >= cfg.report_min_headings:
        return True
    return sum(1 for line in body.splitlines() if LEADER.search(line)) >= MIN_LEADER_LINES


def extract_sections(body: str, cfg: StateCfg) -> list[dict]:
    """`SECTION_KEYS` を含む章の冒頭を抜く。`primary.body` は書き換えない（ADR 026）。"""
    lines = body.splitlines()
    headings = chapter_headings(body)
    sections: list[dict] = []
    for position, (index, heading) in enumerate(headings):
        if not any(key in heading[-SECTION_KEY_TAIL_CHARS:] for key in SECTION_KEYS):
            continue
        end = headings[position + 1][0] if position + 1 < len(headings) else len(lines)
        text = "\n".join(
            line for line in lines[index + 1:end] if PAGENO.fullmatch(line.strip()) is None
        )
        sections.append({"heading": heading, "text": text.strip()[: cfg.excerpt_chars]})
    return sections


def fit(state: dict, budget: int, cfg: StateCfg) -> tuple[dict, dict]:
    """budget（送信 JSON の文字数）に収まるまで縮める。返り値は (state, truncate レポート)。"""
    report = {
        "applied": False,
        "chars_before": measure(state),
        "chars_after": 0,
        "secondary_bodies_dropped": 0,
        "primary_body_cut_chars": 0,
        "excerpt_headings": [],
        "report_like": False,
    }
    if report["chars_before"] <= budget:
        report["chars_after"] = report["chars_before"]
        return state, report
    report["applied"] = True

    # 2. secondary の本文を rank の大きい順に表題のみへ落とす
    for index in range(len(state["secondary"]) - 1, -1, -1):
        if measure(state) <= budget:
            break
        if state["secondary"][index]["body"] is not None:
            state["secondary"][index]["body"] = None
            report["secondary_bodies_dropped"] += 1

    # 3. 報告書型なら章の抜粋を足す（ここで state は一度増える）
    body = state["primary"]["body"]
    if measure(state) > budget and is_report_like(body, cfg):
        report["report_like"] = True
        sections = extract_sections(body, cfg)[: cfg.max_excerpts]
        if sections:
            state["primary"]["excerpts"] = sections
            report["excerpt_headings"] = [s["heading"] for s in sections]

    # 4. primary.body を先頭優先で残し、末尾から削る。エスケープぶんは測り直す
    for _ in range(MAX_PASSES):
        over = measure(state) - budget
        if over <= 0:
            break
        current = state["primary"]["body"]
        cut = min(len(current), int(over * _OVERSHOOT) + _MARGIN)
        if cut == 0:
            break                                   # もう削るところが無い
        state["primary"]["body"] = current[: len(current) - cut]
        report["primary_body_cut_chars"] += cut

    if measure(state) > budget:
        raise JevfwdError(f"切り詰めが収束しない: {measure(state)} > {budget}")
    report["chars_after"] = measure(state)
    return state, report
