"""問い版 JSON の解釈と主語の埋め込み（詳細設計 02-設定 3.2、ADR 002）。

問いの文言は一切変えない。置換するのは {subject}（と主語固定文の中の {company} {code}）だけ。
設定は読まない純関数（版の文字列と JSON 文字列を受け取る）。
"""

import json
from dataclasses import dataclass
from pathlib import Path

from ..common.errors import ConfigError, JudgeError
from ..common.versions import version_from_filename

SUBJECT_PLACEHOLDER = "{subject}"
META_PREFIX = "_"
QTYPES = ("noul", "score", "choice")
SCORE_CRITERIA_LEN = 5
NOUL_KEYS = frozenset({"true", "false"})


@dataclass(frozen=True)
class Question:
    id: str
    type: str                                # noul / score / choice
    instructions: str
    criteria: dict[str, str] | list[str]     # choice / noul は dict、score は list


@dataclass(frozen=True)
class QuestionSet:
    version: str
    subject_prefix: str | None               # _subject_prefix（v1 は None）
    meta: dict[str, object]
    questions: tuple[Question, ...]          # ファイル内の出現順


def _check_question_shape(qid: str, q: object) -> None:
    if not isinstance(q, dict):
        raise ConfigError(f"{qid}: 問いは object")
    missing = {"type", "instructions", "criteria"} - set(q)
    if missing:
        raise ConfigError(f"{qid}: {sorted(missing)} が無い")
    if set(q) - {"type", "instructions", "criteria"}:
        raise ConfigError(f"{qid}: 余分なキー {sorted(set(q) - {'type', 'instructions', 'criteria'})}")
    if q["type"] not in QTYPES:
        raise ConfigError(f"{qid}: type={q['type']!r} は {QTYPES} のいずれか")
    if not isinstance(q["instructions"], str) or not q["instructions"]:
        raise ConfigError(f"{qid}: instructions が空")
    criteria = q["criteria"]
    if q["type"] == "score":
        if not isinstance(criteria, list) or len(criteria) != SCORE_CRITERIA_LEN:
            raise ConfigError(f"{qid}: score の criteria は {SCORE_CRITERIA_LEN} 要素の配列")
        if not all(isinstance(c, str) for c in criteria):
            raise ConfigError(f"{qid}: score の criteria は文字列の配列")
        return
    if not isinstance(criteria, dict) or not all(isinstance(v, str) for v in criteria.values()):
        raise ConfigError(f"{qid}: {q['type']} の criteria は文字列の mapping")
    if q["type"] == "noul" and set(criteria) != NOUL_KEYS:
        raise ConfigError(f"{qid}: noul の criteria のキーは {sorted(NOUL_KEYS)}")


def parse(text: str, version: str) -> QuestionSet:
    """問い版 JSON を解釈する。DB の question_versions.json からもファイルからも同じ関数。"""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ConfigError(f"問い版 {version}: JSON が読めません: {e}") from e
    if not isinstance(data, dict):
        raise ConfigError(f"問い版 {version}: トップレベルは object")
    meta = {k: v for k, v in data.items() if k.startswith(META_PREFIX)}
    if "_version" in meta and meta["_version"] != version:
        raise ConfigError(f"_version={meta['_version']} がファイル名の版 {version} と一致しない")
    subject_prefix = meta.get("_subject_prefix")
    if subject_prefix is not None and not isinstance(subject_prefix, str):
        raise ConfigError("_subject_prefix は文字列")
    questions: list[Question] = []
    for qid, q in data.items():
        if qid.startswith(META_PREFIX):
            continue
        _check_question_shape(qid, q)
        if SUBJECT_PLACEHOLDER in q["instructions"] and subject_prefix is None:
            raise ConfigError(f"{qid}: {SUBJECT_PLACEHOLDER} があるのに _subject_prefix が無い")
        questions.append(Question(qid, q["type"], q["instructions"], q["criteria"]))
    if not questions:
        raise ConfigError(f"問い版 {version}: 問いが1つも無い")
    return QuestionSet(version, subject_prefix, meta, tuple(questions))


def load_file(path: str | Path) -> QuestionSet:
    """`config/questions.vN.json` を読む。版はファイル名から取る。"""
    path = Path(path)
    version = version_from_filename(path, "questions")
    if not path.exists():
        raise ConfigError(f"問い版ファイルがありません: {path}")
    return parse(path.read_text(encoding="utf-8"), version)


def render(qs: QuestionSet, company: str, code: str) -> dict[str, dict]:
    """TypeSafe の questions 形式にする。主語を埋めるだけで文言は変えない（ADR 002）。"""
    if len(code) != 4:
        raise ValueError(f"code は表示用4文字（common.codes.display_code）: {code!r}")
    if not company:
        raise ValueError("company が空（問いの主語が空になる）")
    subject = (qs.subject_prefix or "").replace("{company}", company).replace("{code}", code)
    out: dict[str, dict] = {}
    for q in qs.questions:
        instructions = q.instructions.replace(SUBJECT_PLACEHOLDER, subject)
        if "{" in instructions:
            raise ConfigError(f"{q.id}: 未知のプレースホルダが残っている: {instructions[:60]}")
        out[q.id] = {"type": q.type, "instructions": instructions, "criteria": q.criteria}
    return out


def render_from_db(conn, version: str, company: str, code: str) -> dict[str, dict]:
    """凍結済みの版から問いを作る。未凍結なら JudgeError（ADR 020）。M4 の judge が使う。"""
    from ..store import queries

    row = queries.get_question_version(conn, version)
    if row is None:
        raise JudgeError(f"問い版 {version} は未凍結。jevfwd freeze-questions --version {version}")
    return render(parse(row["json"], version), company, code)
