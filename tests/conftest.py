"""Shared test fixtures for Crossfire."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from crossfire.models import Rule

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES_DIR


@pytest.fixture
def sample_rules_path(fixtures_dir: Path) -> str:
    return str(fixtures_dir / "sample_rules.json")


@pytest.fixture
def overlapping_rules_path(fixtures_dir: Path) -> str:
    return str(fixtures_dir / "overlapping.json")


@pytest.fixture
def disjoint_rules_path(fixtures_dir: Path) -> str:
    return str(fixtures_dir / "disjoint.json")


@pytest.fixture
def sample_rules() -> list[Rule]:
    """A small set of rules for unit tests."""
    return [
        Rule(
            name="aws_key",
            pattern=r"AKIA[0-9A-Z]{16}",
            compiled=re.compile(r"AKIA[0-9A-Z]{16}"),
            source="test",
            detector="secrets",
            severity="critical",
            priority=10,
        ),
        Rule(
            name="slack_token",
            pattern=r"xoxb-[0-9]{11,13}-[0-9]{11,13}-[a-zA-Z0-9]{24}",
            compiled=re.compile(r"xoxb-[0-9]{11,13}-[0-9]{11,13}-[a-zA-Z0-9]{24}"),
            source="test",
            detector="secrets",
            severity="high",
            priority=10,
        ),
        Rule(
            name="email",
            pattern=r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
            compiled=re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"),
            source="test",
            detector="pii",
            severity="medium",
            priority=5,
        ),
    ]


@pytest.fixture
def duplicate_rules() -> list[Rule]:
    """Two rules with identical patterns (different names)."""
    pattern = r"AKIA[0-9A-Z]{16}"
    return [
        Rule(
            name="aws_key_v1",
            pattern=pattern,
            compiled=re.compile(pattern),
            source="file_a.json",
            priority=20,
        ),
        Rule(
            name="aws_key_v2",
            pattern=pattern,
            compiled=re.compile(pattern),
            source="file_b.json",
            priority=10,
        ),
    ]


@pytest.fixture
def tmp_rules_file(tmp_path: Path) -> callable:
    """Factory fixture for creating temporary rule files."""

    def _create(rules: list[dict], name: str = "rules.json") -> str:
        path = tmp_path / name
        with open(path, "w") as f:
            json.dump(rules, f)
        return str(path)

    return _create
