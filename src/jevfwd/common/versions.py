"""版文字列（'v1' 'v2'）とファイル名の対応（00-共通規約 5章、ADR 020）。"""

import re
from pathlib import Path

from .errors import ConfigError

_VERSION_RE = re.compile(r"v([1-9][0-9]*)")


def version_from_filename(path: str | Path, stem: str) -> str:
    """'<stem>.vN.(json|yaml)' から 'vN' を取り出す。合わなければ ConfigError。"""
    name = Path(path).name
    m = re.fullmatch(rf"{re.escape(stem)}\.(v[0-9]+)\.(json|yaml)", name)
    if m is None:
        raise ConfigError(f"版つきファイル名ではない（{stem}.vN.json / .yaml）: {name}")
    return validate_version(m.group(1))


def validate_version(version: str) -> str:
    """'v' + 正の整数か検証してそのまま返す。"""
    if not isinstance(version, str) or _VERSION_RE.fullmatch(version) is None:
        raise ConfigError(f"版は 'v' と正の整数: {version!r}")
    return version


def version_number(version: str) -> int:
    """版の比較用の数値。'v10' > 'v9' を成り立たせる。"""
    return int(validate_version(version)[1:])
