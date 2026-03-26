"""Crossfire error types."""

from __future__ import annotations


class CrossfireError(Exception):
    """Base exception for all Crossfire errors."""


class ValidationError(CrossfireError):
    """Raised when rule validation fails (invalid regex, empty pattern, duplicate name)."""

    def __init__(self, message: str, rule_name: str = "", file: str = "", entry: int = 0) -> None:
        self.rule_name = rule_name
        self.file = file
        self.entry = entry
        super().__init__(message)


class LoadError(CrossfireError):
    """Raised when a rules file cannot be loaded (bad format, missing file)."""


class GenerationError(CrossfireError):
    """Raised when corpus generation fails for a rule."""

    def __init__(self, message: str, rule_name: str = "") -> None:
        self.rule_name = rule_name
        super().__init__(message)
