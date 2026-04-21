"""Crossfire — Regex rule overlap analyzer."""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version

try:
    __version__ = _pkg_version("crossfire-rules")
except PackageNotFoundError:
    # Running from a source tree without the distribution installed
    # (e.g. `python -m crossfire` from a fresh clone). Uninstalled state is
    # not a supported deploy target, but we keep a well-known sentinel so
    # `crossfire --version` doesn't crash during that workflow.
    __version__ = "0.0.0+unknown"

__all__ = ["__version__"]
