"""02-設定 8.2 の受入テスト（T02-24〜34）。問いの文言は変えず主語だけを埋める（ADR 002）。"""

import hashlib
import json

import pytest

from conftest import CONFIG_DIR, read_fixture
from jevfwd.common.errors import ConfigError, JudgeError
from jevfwd.judge.questions import load_file, parse, render, render_from_db
from jevfwd.store import db, repo, rows

QUESTIONS_V1 = CONFIG_DIR / "questions.v1.json"
QUESTIONS_V2 = CONFIG_DIR / "questions.v2.json"
V1_SHA = "14a8baac5898235be756d1c4265fc39541adf13108d9bbc04a445cabf65bd2e7"
V2_SHA = "3f7b661012e0ab94c22f3012bb76a72cc2a03cd086e26b5208fc5b6455f6bcb0"
SUBJECT_HOBONICHI = "判定対象は、この開示の発行者である株式会社ほぼ日（証券コード3560）自身の株価。"


def _minimal(**over) -> str:
    data = {
        "_version": "v9",
        "_subject_prefix": "判定対象は{company}（証券コード{code}）。",
        "direction": {
            "type": "choice",
            "instructions": "{subject} 反応は。",
            "criteria": {"up": "上", "down": "下"},
        },
    }
    data.update(over)
    return json.dumps(data, ensure_ascii=False)


def test_question_files_sha256_frozen():
    """T02-24: 問い版ファイルは不変（ADR 020）。"""
    assert hashlib.sha256(QUESTIONS_V1.read_bytes()).hexdigest() == V1_SHA
    assert hashlib.sha256(QUESTIONS_V2.read_bytes()).hexdigest() == V2_SHA


def test_load_v2_separates_meta_and_questions():
    """T02-25: メタと問いを分け、出現順を保つ。"""
    qs = load_file(QUESTIONS_V2)
    assert qs.version == "v2"
    assert set(qs.meta) == {"_version", "_frozen_at", "_notes", "_subject_prefix"}
    assert [q.id for q in qs.questions] == [
        "direction", "impact", "routine", "surprise", "transient", "conditional", "category"
    ]
    assert "{company}" in qs.subject_prefix and "{code}" in qs.subject_prefix


def test_render_v2_hobonichi():
    """T02-26: 7問すべての冒頭に主語固定文が入り、プレースホルダが残らない。"""
    qs = load_file(QUESTIONS_V2)
    out = render(qs, "株式会社ほぼ日", "3560")
    raw = json.loads(QUESTIONS_V2.read_text(encoding="utf-8"))
    assert len(out) == 7
    for qid, q in out.items():
        assert q["instructions"].startswith(SUBJECT_HOBONICHI), qid
        assert "{" not in q["instructions"], qid
        assert set(q) == {"type", "instructions", "criteria"}
        assert q["criteria"] == raw[qid]["criteria"]
    assert not any(k.startswith("_") for k in out)


def test_render_v2_ferrotec_uses_given_company():
    """T02-27: 主語は呼び出し引数だけで決まる（取り違えを持ち込まない）。"""
    out = render(load_file(QUESTIONS_V2), "株式会社フェローテック", "6890")
    assert "フェローテック" in read_fixture("6890_ferrotec_tob_buyer_full.txt")
    for q in out.values():
        assert "株式会社フェローテック（証券コード6890）" in q["instructions"]
        assert "ほぼ日" not in q["instructions"]


def test_render_v1_is_identity():
    """T02-28: v1 は主語固定文が無いので、そのままの形で出る。"""
    qs = load_file(QUESTIONS_V1)
    assert qs.subject_prefix is None
    assert render(qs, "X", "0000") == json.loads(QUESTIONS_V1.read_text(encoding="utf-8"))


def test_render_rejects_five_char_code():
    """T02-29: 表示用の4文字コードを渡す（5文字は呼び出し側の誤り）。"""
    with pytest.raises(ValueError):
        render(load_file(QUESTIONS_V2), "株式会社ほぼ日", "35600")


def test_parse_from_db_text_equals_load_file():
    """T02-30: DB に生のまま入れた本文からでも同じ結果になる。"""
    text = QUESTIONS_V2.read_text(encoding="utf-8")
    assert parse(text, "v2") == load_file(QUESTIONS_V2)
    assert hashlib.sha256(text.encode("utf-8")).hexdigest() == V2_SHA


def test_parse_rejects_version_mismatch():
    """T02-31: _version とファイル名の版が食い違ったら読まない。"""
    text = QUESTIONS_V2.read_text(encoding="utf-8")
    with pytest.raises(ConfigError, match="_version=v2"):
        parse(text, "v3")


@pytest.mark.parametrize("broken", [
    _minimal(direction={"type": "text", "instructions": "x", "criteria": {}}),
    _minimal(impact={"type": "score", "instructions": "x", "criteria": {"a": "b"}}),
    _minimal(routine={"type": "noul", "instructions": "x", "criteria": {"false": "b"}}),
    json.dumps({"_version": "v9", "direction": {"type": "choice", "instructions": "{subject} x",
                                                "criteria": {"up": "u"}}}, ensure_ascii=False),
    "{壊れた JSON",
], ids=["unknown_type", "score_not_list", "noul_missing_true", "subject_without_prefix", "bad_json"])
def test_parse_rejects_bad_shape(broken):
    """T02-32: 型・criteria の形・主語固定文の欠落・JSON 構文エラー。"""
    with pytest.raises(ConfigError):
        parse(broken, "v9")


def test_render_detects_unknown_placeholder():
    """T02-33: instructions の {company} は置換しない（未知のプレースホルダとして落とす）。"""
    qs = parse(_minimal(direction={"type": "choice", "instructions": "{subject} {company} は…",
                                   "criteria": {"up": "u"}}), "v9")
    with pytest.raises(ConfigError, match="プレースホルダ"):
        render(qs, "ほぼ日", "3560")


def test_render_from_db_requires_frozen_version(db_path):
    """T02-34: 未凍結の版では問いを組まない（ADR 020）。"""
    db.migrate(db_path)
    conn = db.connect(db_path)
    try:
        with pytest.raises(JudgeError, match="freeze-questions"):
            render_from_db(conn, "v2", "株式会社ほぼ日", "3560")
        text = QUESTIONS_V2.read_text(encoding="utf-8")
        with db.transaction(conn):
            repo.insert_question_version(conn, rows.NewQuestionVersion(
                "v2", text, V2_SHA, "2026-09-17T08:30:00+00:00"))
        assert render_from_db(conn, "v2", "株式会社ほぼ日", "3560") == render(
            load_file(QUESTIONS_V2), "株式会社ほぼ日", "3560")
    finally:
        conn.close()
