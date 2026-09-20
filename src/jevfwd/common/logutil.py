"""ログの初期化と秘密のマスク（00-共通規約 7章）。

stdout のみ（Docker logs が拾う）。時刻は UTC。秘密の値はマスクしてから出す。
"""

import logging
import sys
import time
from typing import Iterable

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"
DATE_FORMAT = "%Y-%m-%dT%H:%M:%S+00:00"
HANDLER_NAME = "jevfwd-stdout"
MIN_SECRET_LEN = 4  # 短すぎる値は誤爆するのでマスクしない
MASK = "***"


class SecretMaskFilter(logging.Filter):
    """レコードの本文に秘密の値が含まれていたら '***' に置き換える。"""

    def __init__(self, secrets: Iterable[str] = ()) -> None:
        super().__init__()
        values = {s for s in secrets if isinstance(s, str) and len(s) >= MIN_SECRET_LEN}
        self.secrets: tuple[str, ...] = tuple(sorted(values, key=len, reverse=True))

    def filter(self, record: logging.LogRecord) -> bool:
        if not self.secrets:
            return True
        message = record.getMessage()
        if not any(s in message for s in self.secrets):
            return True
        for s in self.secrets:
            message = message.replace(s, MASK)
        record.msg = message
        record.args = None
        return True


def setup_logging(level: str = "INFO", secrets: Iterable[str] = ()) -> None:
    """ルートロガーに stdout ハンドラと SecretMaskFilter を付ける。2回呼んでも重複しない。"""
    root = logging.getLogger()
    handler = None
    for h in root.handlers:
        if getattr(h, "name", None) == HANDLER_NAME:
            handler = h
            break
    if handler is None:
        handler = logging.StreamHandler(sys.stdout)
        handler.set_name(HANDLER_NAME)
        root.addHandler(handler)
    elif isinstance(handler, logging.StreamHandler):
        handler.setStream(sys.stdout)

    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)
    formatter.converter = time.gmtime
    handler.setFormatter(formatter)

    mask = SecretMaskFilter(secrets)
    for target in (handler, root):
        for existing in list(target.filters):
            if isinstance(existing, SecretMaskFilter):
                target.removeFilter(existing)
        target.addFilter(mask)

    root.setLevel(level)
