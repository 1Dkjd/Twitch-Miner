from __future__ import annotations

import logging
from collections.abc import Callable, Iterable


class RedactFilter(logging.Filter):
    """Replace secrets in log messages. Attach to every handler."""

    def __init__(self, secrets: Callable[[], Iterable[str]]):
        super().__init__()
        self._secrets = secrets

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        for s in self._secrets():
            if s:
                msg = msg.replace(s, "***")
        record.msg, record.args = msg, None
        return True
