"""Regex compilation with optional RE2 acceleration.

Tries google-re2 first (10-100x faster for compatible patterns),
falls back to Python's re module for patterns using backreferences,
lookahead, or other PCRE-only features.

Install RE2 support: pip install crossfire-rules[re2]
"""

from __future__ import annotations

import logging
import re

log = logging.getLogger("crossfire.regex")

try:
    import re2

    _RE2_AVAILABLE = True
except ImportError:
    _RE2_AVAILABLE = False


def is_re2_available() -> bool:
    """Check if google-re2 is installed."""
    return _RE2_AVAILABLE


def compile(pattern: str) -> re.Pattern[str]:
    """Compile a regex pattern, using RE2 when available and compatible.

    Args:
        pattern: Regex pattern string.

    Returns:
        Compiled pattern object (re2.Pattern or re.Pattern).

    Raises:
        re.error: If the pattern is invalid in both RE2 and re.
    """
    if _RE2_AVAILABLE:
        try:
            return re2.compile(pattern)  # type: ignore[no-any-return]
        except Exception:
            log.debug("RE2 cannot compile pattern (falling back to re): %r", pattern)
    return re.compile(pattern)
