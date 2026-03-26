"""Plugin system for format adapters.

Crossfire discovers adapters via two mechanisms:
1. Built-in adapters in this package (e.g., gitleaks)
2. External adapters registered via entry_points(group="crossfire.adapters")

Each adapter implements the RuleAdapter protocol.
"""

from __future__ import annotations

import logging
from typing import Protocol

from crossfire.models import Rule

log = logging.getLogger("crossfire.plugins")


class RuleAdapter(Protocol):
    """Protocol for format-specific rule adapters."""

    @property
    def name(self) -> str:
        """Short name for this adapter (e.g., 'gitleaks')."""
        ...

    @property
    def extensions(self) -> list[str]:
        """File extensions this adapter handles (e.g., ['.toml'])."""
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


def register_adapter(adapter: RuleAdapter) -> None:
    """Register a format adapter."""
    _adapters.append(adapter)
    log.info("Registered adapter: %s (extensions: %s)", adapter.name, adapter.extensions)


def get_adapters() -> list[RuleAdapter]:
    """Get all registered adapters (built-in + external)."""
    return list(_adapters)


def find_adapter(path: str) -> RuleAdapter | None:
    """Find an adapter that can load the given file."""
    for adapter in _adapters:
        if adapter.can_load(path):
            return adapter
    return None


def discover_external_adapters() -> None:
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
    register_adapter(GitleaksAdapter())


# Auto-register on import
_register_builtin_adapters()
discover_external_adapters()
