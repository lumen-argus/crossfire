"""Guard: `crossfire.__version__` must agree with the installed distribution.

Previously (<= 0.2.3), `__version__` was a hardcoded string in
`crossfire/__init__.py`. It drifted from `pyproject.toml` on the 0.2.3 release
— the wheel shipped as 0.2.3 but `crossfire --version` printed 0.2.2. This
test pins the contract that `pyproject.toml` is the single source of truth.
"""

from __future__ import annotations

import re
from importlib.metadata import version as pkg_version

import crossfire


def test_version_matches_distribution_metadata() -> None:
    assert crossfire.__version__ == pkg_version("crossfire-rules"), (
        "__version__ drift detected. Do not hardcode the version in "
        "crossfire/__init__.py — bump pyproject.toml instead."
    )


def test_version_is_a_real_semver_not_the_uninstalled_sentinel() -> None:
    # `0.0.0+unknown` is the sentinel returned when the package isn't
    # installed (pure source tree). CI always installs via `pip install -e .`,
    # so the sentinel showing up here would mean the package's entry in
    # site-packages is broken.
    assert crossfire.__version__ != "0.0.0+unknown"
    assert re.match(r"^\d+\.\d+\.\d+", crossfire.__version__), (
        f"Expected semver; got {crossfire.__version__!r}"
    )
