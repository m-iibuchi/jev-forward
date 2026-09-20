"""証券コード。DB は TDnet の5文字、Jev への表示は4文字（00-共通規約 4章）。"""

import re

_CODE_RE = re.compile(r"[0-9A-Z]{5}")


def validate_tdnet_code(code: str) -> str:
    """TDnet 一覧の5文字コードか検証してそのまま返す。違えば ValueError。"""
    if not isinstance(code, str) or _CODE_RE.fullmatch(code) is None:
        raise ValueError(f"TDnet のコードは英数字大文字5文字: {code!r}")
    return code


def display_code(code5: str) -> str:
    """表示用コード。5文字目が '0'（普通株）なら4文字、それ以外はそのまま5文字。"""
    validate_tdnet_code(code5)
    return code5[:4] if code5[4] == "0" else code5
