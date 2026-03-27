"""Tests for logging configuration."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from crossfire.logging import setup_logging


class TestSetupLogging:
    def test_sets_level(self):
        setup_logging(level="debug")
        logger = logging.getLogger("crossfire")
        assert logger.level == logging.DEBUG

    def test_sets_warning_level(self):
        setup_logging(level="warning")
        logger = logging.getLogger("crossfire")
        assert logger.level == logging.WARNING

    def test_text_formatter(self):
        setup_logging(level="info", log_format="text")
        logger = logging.getLogger("crossfire")
        assert len(logger.handlers) >= 1

    def test_json_formatter(self):
        setup_logging(level="info", log_format="json")
        logger = logging.getLogger("crossfire")
        handler = logger.handlers[0]
        record = logging.LogRecord("crossfire.test", logging.INFO, "", 0, "test message", (), None)
        output = handler.formatter.format(record)
        data = json.loads(output)
        assert data["msg"] == "test message"
        assert data["level"] == "INFO"
        assert data["logger"] == "crossfire.test"

    def test_log_file(self, tmp_path: Path):
        log_path = str(tmp_path / "test.log")
        setup_logging(level="info", log_file=log_path)
        logger = logging.getLogger("crossfire")
        logger.info("file test")
        # Flush handlers
        for h in logger.handlers:
            h.flush()
        assert Path(log_path).exists()
        content = Path(log_path).read_text()
        assert "file test" in content

    def test_clears_existing_handlers(self):
        setup_logging(level="info")
        logger = logging.getLogger("crossfire")
        initial_count = len(logger.handlers)
        setup_logging(level="debug")
        # Should not accumulate handlers
        assert len(logger.handlers) <= initial_count
