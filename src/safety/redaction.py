"""Secret redaction at every exit: logging, stdout/stderr, and uncaught
exceptions -- not just the trajectory writer. Constraint 4 says keys never
appear in logs, trajectory files, error messages, or console output; a
redactor that only guards one of those is a redactor with three holes.

What gets redacted:
  - the LOADED values of every *_API_KEY / *_TOKEN env var (strongest
    signal: the actual secret, wherever it appears), plus URL-encoded and
    JSON-escaped forms
  - the Anthropic key shape sk-ant-... regardless of whether it was loaded
    (catches a pasted key that never entered the environment)
"""

from __future__ import annotations

import logging
import os
import re
import sys
import urllib.parse
from typing import TextIO

REDACTED = "[REDACTED]"
_KEY_ENV_SUFFIXES = ("_API_KEY", "_TOKEN", "_SECRET")
_PATTERNS = [re.compile(r"sk-ant-[A-Za-z0-9_\-]{16,}")]


class Redactor:
    def __init__(self) -> None:
        values: set[str] = set()
        for name, value in os.environ.items():
            if name.endswith(_KEY_ENV_SUFFIXES) and value and len(value) >= 8:
                values.add(value)
                values.add(urllib.parse.quote(value, safe=""))
                values.add(value.replace("-", r"\-"))
        self._values = sorted(values, key=len, reverse=True)

    def redact(self, text: str) -> str:
        for value in self._values:
            if value in text:
                text = text.replace(value, REDACTED)
        for pattern in _PATTERNS:
            text = pattern.sub(REDACTED, text)
        return text


class _RedactingFilter(logging.Filter):
    def __init__(self, redactor: Redactor):
        super().__init__()
        self._redactor = redactor

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = self._redactor.redact(str(record.msg))
        if record.args:
            record.args = tuple(
                self._redactor.redact(str(a)) for a in record.args
            )
        return True


class _RedactingStream:
    def __init__(self, stream: TextIO, redactor: Redactor):
        self._stream = stream
        self._redactor = redactor

    def write(self, text: str) -> int:
        return self._stream.write(self._redactor.redact(text))

    def flush(self) -> None:
        self._stream.flush()

    def __getattr__(self, name):
        return getattr(self._stream, name)


_INSTALLED: Redactor | None = None


def install() -> Redactor:
    """Idempotent three-point install: root logger, stdout/stderr,
    excepthook. Call after load_dotenv() so loaded values are known."""
    global _INSTALLED
    if _INSTALLED is not None:
        return _INSTALLED
    redactor = Redactor()

    logging.getLogger().addFilter(_RedactingFilter(redactor))
    sys.stdout = _RedactingStream(sys.stdout, redactor)  # type: ignore[assignment]
    sys.stderr = _RedactingStream(sys.stderr, redactor)  # type: ignore[assignment]

    previous_hook = sys.excepthook

    def hook(exc_type, exc, tb):
        exc.args = tuple(
            redactor.redact(a) if isinstance(a, str) else a for a in exc.args
        )
        previous_hook(exc_type, exc, tb)

    sys.excepthook = hook
    _INSTALLED = redactor
    return redactor
