"""SHA-256。版ファイルの凍結と PDF の重複排除に使う（ADR 004・020）。"""

import hashlib
from pathlib import Path

_CHUNK = 1 << 20


def sha256_hex(data: bytes) -> str:
    """バイト列の SHA-256（16進小文字64桁）。"""
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str | Path) -> str:
    """ファイルのバイト列の SHA-256。テキストとして読み直さない。"""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(_CHUNK):
            h.update(chunk)
    return h.hexdigest()
