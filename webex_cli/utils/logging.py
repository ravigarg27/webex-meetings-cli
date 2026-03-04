from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone

from webex_cli.runtime import get_request_id
from webex_cli.utils.redaction import redact_string

_CONFIGURED_FORMAT: str | None = None


class _ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id()
        message = record.getMessage()
        record.msg = redact_string(message)
        record.args = ()
        return True


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "request_id": getattr(record, "request_id", None),
            "message": record.getMessage(),
        }
        return json.dumps(payload, default=str)


def _configure(log_format: str = "text") -> None:
    global _CONFIGURED_FORMAT
    if _CONFIGURED_FORMAT == log_format:
        return
    level_name = os.environ.get("WEBEX_LOG_LEVEL", "WARNING").upper()
    level = getattr(logging, level_name, logging.WARNING)
    root = logging.getLogger()
    root.handlers.clear()
    handler = logging.StreamHandler()
    if log_format == "json":
        handler.setFormatter(_JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s [%(request_id)s]: %(message)s")
        )
    handler.addFilter(_ContextFilter())
    root.addHandler(handler)
    root.setLevel(level)
    _CONFIGURED_FORMAT = log_format


def get_logger(name: str) -> logging.Logger:
    _configure()
    return logging.getLogger(name)


def configure_logging(log_format: str) -> None:
    _configure(log_format=log_format)
