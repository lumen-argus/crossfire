"""Regex compilation with optional RE2 acceleration.

Every pattern is validated against Python's stdlib `re` — that's the lowest
common denominator, since `ProcessPoolExecutor` workers recompile from
pattern strings with stdlib `re` by design. When the pattern is stdlib-valid
and google-re2 is installed, the RE2-compiled form is returned for faster
matching (10-100x for compatible patterns); otherwise the stdlib form is
returned. RE2 cannot handle backreferences, lookahead/lookbehind, or other
PCRE-only features — those patterns fall through to stdlib.

Install RE2 support: pip install crossfire-rules[re2]
"""

from __future__ import annotations

import logging
import re

from crossfire.models import CompiledPattern

log = logging.getLogger("crossfire.regex")

try:
    import re2

    _RE2_AVAILABLE = True
except ImportError:
    _RE2_AVAILABLE = False


def is_re2_available() -> bool:
    """Check if google-re2 is installed."""
    return _RE2_AVAILABLE


def compile(pattern: str) -> CompiledPattern:
    """Compile a regex pattern, using RE2 when available and compatible.

    Patterns are *always* validated against stdlib `re` as well, even when RE2
    succeeds. This is the single place that enforces the loader's contract to
    downstream workers: `ProcessPoolExecutor` workers (generator, evaluator on
    macOS/Windows) recompile patterns with stdlib `re` by design — importing
    the `crossfire` package in workers adds ~20ms each under spawn — so any
    pattern the loader accepts must be stdlib-compilable. RE2 has a strictly
    different grammar (e.g. it accepts non-leading `(?i)` flags that stdlib
    `re` rejects on Python 3.11+), and letting such a pattern through the
    loader would abort the whole worker pool later regardless of
    `--skip-invalid`.

    Args:
        pattern: Regex pattern string.

    Returns:
        Compiled pattern object (re2.Pattern or re.Pattern). RE2 is returned
        when available and it accepts the pattern; otherwise the stdlib
        compiled form is returned.

    Raises:
        re.error: If stdlib `re` cannot compile the pattern. Callers (today,
            only the loader) translate this into `ValidationError` and honor
            `--skip-invalid`.
    """
    # Validate stdlib first so the caller sees a stdlib `re.error` for bad
    # patterns even when RE2 would have accepted them. We hang on to the
    # compiled form so the RE2-unavailable / RE2-rejects path doesn't
    # redundantly compile again.
    stdlib_compiled = re.compile(pattern)

    if _RE2_AVAILABLE:
        try:
            return re2.compile(pattern)  # type: ignore[no-any-return]
        except Exception:
            log.debug("RE2 cannot compile pattern (falling back to re): %r", pattern)
    return stdlib_compiled
