"""Structured logging configuration for Crossfire."""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime


class TextFormatter(logging.Formatter):
    """Human-readable log format."""

    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created, tz=UTC).strftime("%Y-%m-%d %H:%M:%S")
        return f"{ts} [{record.levelname}] {record.name}: {record.getMessage()}"


class JsonFormatter(logging.Formatter):
    """Structured JSON log format."""

    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        entry: dict[str, object] = {
            "ts": ts,
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info and record.exc_info[1]:
            entry["exception"] = str(record.exc_info[1])
        return json.dumps(entry, default=str)


def setup_logging(
    level: str = "warning",
    log_file: str | None = None,
    log_format: str = "text",
) -> None:
    """Configure logging for Crossfire.

    Args:
        level: Log level name (debug, info, warning, error).
        log_file: Optional file path for log output (in addition to stderr).
        log_format: Format style - 'text' for human-readable, 'json' for structured.
    """
    root = logging.getLogger("crossfire")
    root.setLevel(getattr(logging, level.upper(), logging.WARNING))

    # Remove any existing handlers
    root.handlers.clear()

    formatter: logging.Formatter = JsonFormatter() if log_format == "json" else TextFormatter()

    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setFormatter(formatter)
    root.addHandler(stderr_handler)

    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
