"""00-共通規約 14.1 の受入テスト（T00-01〜12）。"""

import logging
from datetime import date, datetime, timezone

import pytest

from conftest import CONFIG_DIR, FIXTURES, load_tdnet_tsv
from jevfwd.common.codes import display_code, validate_tdnet_code
from jevfwd.common.errors import ConfigError, JevfwdError, SchemaMismatchError, StoreError
from jevfwd.common.hashing import sha256_file, sha256_hex
from jevfwd.common.jsonutil import canonical
from jevfwd.common.logutil import HANDLER_NAME, setup_logging
from jevfwd.common.timeutil import (
    JST,
    format_jst,
    is_utc_str,
    jst_day,
    jst_minute_to_utc_str,
    now_utc,
    parse_utc,
    to_utc_str,
)
from jevfwd.common.versions import version_from_filename

QUESTIONS_V1_SHA = "14a8baac5898235be756d1c4265fc39541adf13108d9bbc04a445cabf65bd2e7"
QUESTIONS_V2_SHA = "3f7b661012e0ab94c22f3012bb76a72cc2a03cd086e26b5208fc5b6455f6bcb0"


def test_to_utc_str_format():
    """T00-01: JST の aware な datetime が UTC 文字列になり、書式判定が効く。"""
    assert to_utc_str(datetime(2026, 9, 17, 17, 30, tzinfo=JST)) == "2026-09-17T08:30:00+00:00"
    assert is_utc_str("2026-09-17T08:30:00+00:00") is True
    assert is_utc_str("2026-09-17T08:30:00Z") is False
    assert is_utc_str("2026-09-17 08:30:00") is False


def test_to_utc_str_rejects_naive():
    """T00-02: naive な datetime は保存できない。"""
    with pytest.raises(ValueError):
        to_utc_str(datetime(2026, 9, 17, 8, 30))


def test_parse_utc_roundtrip_and_jst():
    """T00-03: 往復変換と JST 表示。'Z' 終端は受け付けない。"""
    dt = parse_utc("2026-09-17T08:30:00+00:00")
    assert dt.tzinfo == timezone.utc
    assert to_utc_str(dt) == "2026-09-17T08:30:00+00:00"
    assert format_jst(dt) == "2026-09-17 17:30 JST"
    assert jst_day(dt) == "2026-09-17"
    with pytest.raises(ValueError):
        parse_utc("2026-09-17T08:30:00Z")


def test_jst_minute_to_utc_str_from_tdnet_list():
    """T00-04: TDnet 一覧の分単位の時刻を UTC にする。日付をまたぐ場合も。"""
    rows = load_tdnet_tsv(FIXTURES / "tdnet_list_2026-09-17.tsv")
    first = rows[0]
    assert first.time == "19:00"
    assert "エネチェンジ" in first.company
    assert jst_minute_to_utc_str("2026-09-17", first.time) == "2026-09-17T10:00:00+00:00"
    assert jst_minute_to_utc_str(date(2026, 9, 17), "23:45") == "2026-09-17T14:45:00+00:00"
    assert jst_minute_to_utc_str("2026-09-17", "08:00") == "2026-09-16T23:00:00+00:00"


def test_now_utc_has_no_microseconds():
    """T00-05: 現在時刻は UTC・秒精度。"""
    dt = now_utc()
    assert dt.microsecond == 0
    assert dt.tzinfo == timezone.utc


def test_display_code():
    """T00-06: 5文字目が 0 のときだけ4文字にする。"""
    assert display_code("35600") == "3560"
    assert display_code("590A0") == "590A"
    assert display_code("13264") == "13264"
    assert display_code("89600") == "8960"


@pytest.mark.parametrize("bad", ["3560", "356000", "35６0０", "3560a"])
def test_validate_tdnet_code(bad):
    """T00-07: 5文字・英数字大文字以外は ValueError。"""
    assert validate_tdnet_code("35600") == "35600"
    with pytest.raises(ValueError):
        validate_tdnet_code(bad)


def test_canonical_json_stable():
    """T00-08: キー順が違っても同じ文字列。配列順は保つ。"""
    a = {"b": 1, "a": [1, {"d": 2, "c": "日本"}]}
    b = {"a": [1, {"c": "日本", "d": 2}], "b": 1}
    assert canonical(a) == canonical(b) == '{"a":[1,{"c":"日本","d":2}],"b":1}'


def test_sha256_file_matches_adr020():
    """T00-09: 問い版ファイルの SHA-256 が ADR 020 の値と一致する。"""
    v1 = CONFIG_DIR / "questions.v1.json"
    v2 = CONFIG_DIR / "questions.v2.json"
    assert sha256_file(v1) == QUESTIONS_V1_SHA
    assert sha256_file(v2) == QUESTIONS_V2_SHA
    assert sha256_hex(v2.read_bytes()) == QUESTIONS_V2_SHA


def test_version_from_filename():
    """T00-10: 版つきファイル名から版を取り出す。合わなければ ConfigError。"""
    assert version_from_filename("config/questions.v2.json", "questions") == "v2"
    assert version_from_filename("config/entry_rules.v10.yaml", "entry_rules") == "v10"
    for name, stem in [
        ("questions.json", "questions"),
        ("questions.2.json", "questions"),
        ("filters.v1.yaml", "entry_rules"),
    ]:
        with pytest.raises(ConfigError):
            version_from_filename(name, stem)


def test_error_hierarchy():
    """T00-11: 例外の親子関係。"""
    assert issubclass(SchemaMismatchError, StoreError)
    assert issubclass(SchemaMismatchError, JevfwdError)
    assert issubclass(ConfigError, JevfwdError)
    assert not issubclass(ConfigError, StoreError)


def test_secret_mask_filter(capsys):
    """T00-12: 秘密の値はマスクされ、短い値はそのまま。ハンドラは重複しない。"""
    root = logging.getLogger()
    for handler in [h for h in root.handlers if getattr(h, "name", None) == HANDLER_NAME]:
        root.removeHandler(handler)
    try:
        setup_logging("DEBUG", ["sk-test-XYZ"])
        setup_logging("DEBUG", ["sk-test-XYZ"])
        assert len([h for h in root.handlers if getattr(h, "name", None) == HANDLER_NAME]) == 1
        logger = logging.getLogger("jevfwd.test")
        logger.info("key=%s ok", "sk-test-XYZ")
        logger.info("short %s", "ab")
        out = capsys.readouterr().out
        assert "sk-test-XYZ" not in out
        assert "key=*** ok" in out
        assert "short ab" in out
    finally:
        for handler in [h for h in root.handlers if getattr(h, "name", None) == HANDLER_NAME]:
            root.removeHandler(handler)
        for f in list(root.filters):
            root.removeFilter(f)
