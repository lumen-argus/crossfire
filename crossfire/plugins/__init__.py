"""Plugin system for format adapters.

Crossfire discovers adapters via two mechanisms:
1. Built-in adapters in this package (e.g., gitleaks)
2. External adapters registered via entry_points(group="crossfire.adapters")

Each adapter implements the RuleAdapter protocol.
"""

from __future__ import annotations

import logging
from typing import Protocol

log = logging.getLogger("crossfire.plugins")


class RuleAdapter(Protocol):
    """Protocol for format-specific rule adapters."""

    @property
    def name(self) -> str:
        """Short name for this adapter (e.g., 'gitleaks')."""
        ...

    def can_load(self, path: str) -> bool:
        """Check if this adapter can load the given file."""
        ...

    def load(self, path: str) -> list[dict[str, object]]:
        """Load rules from the file as a list of dicts.

        Each dict must have at least 'name' and 'pattern' keys.
        Additional keys are passed through as metadata.
        """
        ...


_adapters: list[RuleAdapter] = []
_initialized = False


def register_adapter(adapter: RuleAdapter) -> None:
    """Register a format adapter. Skips if an adapter with the same name exists."""
    if any(a.name == adapter.name for a in _adapters):
        log.debug("Adapter '%s' already registered, skipping", adapter.name)
        return
    _adapters.append(adapter)
    log.info("Registered adapter: %s", adapter.name)


def get_adapters() -> list[RuleAdapter]:
    """Get all registered adapters (built-in + external)."""
    _ensure_initialized()
    return list(_adapters)


def find_adapter(path: str) -> RuleAdapter | None:
    """Find an adapter that can load the given file."""
    _ensure_initialized()
    for adapter in _adapters:
        if adapter.can_load(path):
            return adapter
    return None


def _ensure_initialized() -> None:
    """Lazy initialization — registers adapters on first use."""
    global _initialized
    if _initialized:
        return
    _initialized = True
    _register_builtin_adapters()
    _discover_external_adapters()


def _discover_external_adapters() -> None:
    """Discover and register adapters from entry_points."""
    try:
        from importlib.metadata import entry_points

        eps = entry_points(group="crossfire.adapters")
        for ep in eps:
            try:
                adapter_class = ep.load()
                adapter = adapter_class()
                register_adapter(adapter)
                log.info("Loaded external adapter: %s", ep.name)
            except Exception:
                log.warning("Failed to load adapter '%s'", ep.name, exc_info=True)
    except Exception:
        log.debug("Entry point discovery failed", exc_info=True)


def _register_builtin_adapters() -> None:
    """Register built-in adapters."""
    from crossfire.plugins.gitleaks import GitleaksAdapter
    from crossfire.plugins.semgrep import SemgrepAdapter
    from crossfire.plugins.sigma import SigmaAdapter
    from crossfire.plugins.snort import SnortAdapter
    from crossfire.plugins.yara import YaraAdapter

    register_adapter(GitleaksAdapter())
    register_adapter(SemgrepAdapter())
    register_adapter(SigmaAdapter())
    register_adapter(YaraAdapter())
    register_adapter(SnortAdapter())
