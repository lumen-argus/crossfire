"""Rule loading with format detection and fail-fast validation."""

from __future__ import annotations

import csv
import json
import logging
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

import yaml

from crossfire.errors import LoadError, ValidationError
from crossfire.models import Rule

log = logging.getLogger("crossfire.loader")

# Default field name mappings: external name → internal field
DEFAULT_NAME_FIELDS = ("name", "id", "rule_name", "rule_id")
DEFAULT_PATTERN_FIELDS = ("pattern", "regex", "regexp", "re")
DEFAULT_DETECTOR_FIELDS = ("detector", "type", "category")
DEFAULT_SEVERITY_FIELDS = ("severity", "level")


def _find_field(entry: dict[str, Any], candidates: tuple[str, ...]) -> str | None:
    """Find the first matching field name in an entry."""
    for field_name in candidates:
        if field_name in entry:
            return str(entry[field_name])
    return None


def _detect_format(path: Path) -> str:
    """Detect file format by extension."""
    suffix = path.suffix.lower()
    if suffix == ".json":
        return "json"
    if suffix in (".yaml", ".yml"):
        return "yaml"
    if suffix == ".csv":
        return "csv"
    if suffix == ".toml":
        return "toml"
    raise LoadError(f"Unsupported file format: {suffix} (file: {path})")


def _load_json(path: Path) -> list[dict[str, Any]]:
    """Load rules from JSON file."""
    with open(path) as f:
        data: Any = json.load(f)
    if isinstance(data, list):
        return cast(list[dict[str, Any]], data)
    if isinstance(data, dict) and "rules" in data:
        return cast(list[dict[str, Any]], data["rules"])
    raise LoadError(f"JSON must be an array or object with 'rules' key: {path}")


def _load_yaml(path: Path) -> list[dict[str, Any]]:
    """Load rules from YAML file."""
    with open(path) as f:
        data: Any = yaml.safe_load(f)
    if isinstance(data, list):
        return cast(list[dict[str, Any]], data)
    if isinstance(data, dict) and "rules" in data:
        return cast(list[dict[str, Any]], data["rules"])
    raise LoadError(f"YAML must be a list or mapping with 'rules' key: {path}")


def _load_csv(path: Path) -> list[dict[str, Any]]:
    """Load rules from CSV file."""
    with open(path) as f:
        reader = csv.DictReader(f)
        return list(reader)


def _load_toml(path: Path) -> list[dict[str, Any]]:
    """Load rules from TOML file (GitLeaks format)."""
    try:
        import tomllib
    except ImportError:
        try:
            import tomli as tomllib
        except ImportError as err:
            raise LoadError(
                f"TOML support requires Python 3.11+ or 'tomli' package: {path}"
            ) from err
    with open(path, "rb") as f:
        data = tomllib.load(f)
    if "rules" in data:
        return cast(list[dict[str, Any]], data["rules"])
    raise LoadError(f"TOML must have a [[rules]] section: {path}")


_LOADERS = {
    "json": _load_json,
    "yaml": _load_yaml,
    "csv": _load_csv,
    "toml": _load_toml,
}


def load_rules(
    path: str | Path,
    *,
    skip_invalid: bool = False,
    priority: int = 0,
    field_mapping: dict[str, str] | None = None,
) -> list[Rule]:
    """Load and validate rules from a file.

    Args:
        path: Path to the rules file.
        skip_invalid: If True, skip invalid rules with a warning instead of failing.
        priority: Priority value for rules from this file (higher = prefer to keep).
        field_mapping: Custom field name mapping (e.g., {"name": "id", "pattern": "regex"}).

    Returns:
        List of validated Rule objects.

    Raises:
        LoadError: If the file cannot be read or parsed.
        ValidationError: If a rule is invalid and skip_invalid is False.
    """
    path = Path(path)
    if not path.exists():
        raise LoadError(f"File not found: {path}")
    if not path.is_file():
        raise LoadError(f"Not a file: {path}")

    # Try plugin adapters first (e.g., GitLeaks TOML)
    from crossfire.plugins import find_adapter

    adapter = find_adapter(str(path))
    if adapter:
        log.info("Loading rules from %s (adapter: %s)", path, adapter.name)
        raw_entries = adapter.load(str(path))
    else:
        fmt = _detect_format(path)
        log.info("Loading rules from %s (format: %s)", path, fmt)
        raw_entries = _LOADERS[fmt](path)

    if not raw_entries:
        raise LoadError(f"No rules found in {path}")

    # Build field lookup with custom mapping overrides
    name_fields: tuple[str, ...] = DEFAULT_NAME_FIELDS
    pattern_fields: tuple[str, ...] = DEFAULT_PATTERN_FIELDS
    if field_mapping:
        if "name" in field_mapping:
            name_fields = (field_mapping["name"], *DEFAULT_NAME_FIELDS)
        if "pattern" in field_mapping:
            pattern_fields = (field_mapping["pattern"], *DEFAULT_PATTERN_FIELDS)

    rules: list[Rule] = []
    seen_names: set[str] = set()
    skipped = 0
    source = str(path)

    for idx, entry in enumerate(raw_entries, start=1):
        if not isinstance(entry, dict):
            _handle_invalid(
                ValidationError(
                    f"Entry {idx} in {path} is not a mapping (got {type(entry).__name__})",
                    file=source,
                    entry=idx,
                ),
                skip_invalid,
            )
            skipped += 1
            continue

        # Extract name
        name = _find_field(entry, name_fields)
        if not name:
            _handle_invalid(
                ValidationError(
                    f"Entry {idx} in {path} is missing a name field "
                    f"(tried: {', '.join(name_fields)})",
                    file=source,
                    entry=idx,
                ),
                skip_invalid,
            )
            skipped += 1
            continue

        # Check duplicate names
        if name in seen_names:
            _handle_invalid(
                ValidationError(
                    f"Duplicate rule name '{name}' in {path} (entry {idx}). "
                    f"Rule names must be unique within a file.",
                    rule_name=name,
                    file=source,
                    entry=idx,
                ),
                skip_invalid,
            )
            skipped += 1
            continue
        seen_names.add(name)

        # Extract pattern — check key existence separately from empty value
        pattern_key_found = any(k in entry for k in pattern_fields)
        pattern = _find_field(entry, pattern_fields)
        if not pattern_key_found:
            _handle_invalid(
                ValidationError(
                    f"Rule '{name}' in {path} (entry {idx}) is missing a pattern field "
                    f"(tried: {', '.join(pattern_fields)})",
                    rule_name=name,
                    file=source,
                    entry=idx,
                ),
                skip_invalid,
            )
            skipped += 1
            continue

        if not pattern or not pattern.strip():
            _handle_invalid(
                ValidationError(
                    f"Rule '{name}' in {path} (entry {idx}) has an empty pattern",
                    rule_name=name,
                    file=source,
                    entry=idx,
                ),
                skip_invalid,
            )
            skipped += 1
            continue

        # Compile regex
        try:
            compiled = re.compile(pattern)
        except re.error as e:
            _handle_invalid(
                ValidationError(
                    f"Rule '{name}' has invalid regex: {e}\n"
                    f"  Pattern: {pattern}\n"
                    f"  File: {path}, entry {idx}\n\n"
                    f"Fix the pattern and retry. Use --skip-invalid to analyze "
                    f"remaining rules anyway.",
                    rule_name=name,
                    file=source,
                    entry=idx,
                ),
                skip_invalid,
            )
            skipped += 1
            continue

        # Extract optional fields
        detector = _find_field(entry, DEFAULT_DETECTOR_FIELDS) or ""
        severity = _find_field(entry, DEFAULT_SEVERITY_FIELDS) or ""
        tags_raw = entry.get("tags", [])
        tags = tags_raw if isinstance(tags_raw, list) else []

        # Use adapter-provided metadata directly, or collect remaining fields
        if "metadata" in entry and isinstance(entry["metadata"], dict):
            metadata = entry["metadata"]
        else:
            known_keys = set(
                name_fields
                + pattern_fields
                + DEFAULT_DETECTOR_FIELDS
                + DEFAULT_SEVERITY_FIELDS
                + ("tags",)
            )
            metadata = {k: v for k, v in entry.items() if k not in known_keys}

        rules.append(
            Rule(
                name=name,
                pattern=pattern,
                compiled=compiled,
                source=source,
                detector=detector,
                severity=severity,
                tags=[str(t) for t in tags],
                priority=priority,
                metadata=metadata,
            )
        )

    if skipped and skip_invalid:
        log.warning("Loaded %d rules from %s (%d skipped)", len(rules), path, skipped)
    else:
        log.info("Loaded %d rules from %s", len(rules), path)

    if not rules:
        raise LoadError(f"No valid rules loaded from {path}")

    return rules


def _handle_invalid(error: ValidationError, skip_invalid: bool) -> None:
    """Either raise the error or log a warning."""
    if skip_invalid:
        log.warning("Skipping: %s", error)
    else:
        raise error


def load_multiple(
    paths: Sequence[str | Path],
    *,
    skip_invalid: bool = False,
    priorities: dict[str, int] | None = None,
    field_mapping: dict[str, str] | None = None,
) -> list[Rule]:
    """Load rules from multiple files.

    Args:
        paths: List of file paths to load.
        skip_invalid: If True, skip invalid rules with a warning instead of failing.
        priorities: Mapping of filename → priority. Files not in the mapping get priority
                    based on their position (first file = highest).
        field_mapping: Custom field name mapping.

    Returns:
        Combined list of Rule objects from all files.
    """
    all_rules: list[Rule] = []
    for idx, path in enumerate(paths):
        path = Path(path)
        if priorities and path.name in priorities:
            priority = priorities[path.name]
        elif priorities and str(path) in priorities:
            priority = priorities[str(path)]
        else:
            # First file gets highest default priority
            priority = (len(paths) - idx) * 10
        rules = load_rules(
            path,
            skip_invalid=skip_invalid,
            priority=priority,
            field_mapping=field_mapping,
        )
        all_rules.extend(rules)
    log.info("Total rules loaded: %d from %d files", len(all_rules), len(paths))
    return all_rules
