"""GitLeaks TOML format adapter.

Handles the GitLeaks `.gitleaks.toml` rule format, mapping fields to
Crossfire's rule model. GitLeaks uses Go RE2 regex dialect which lacks
lookahead/lookbehind — most patterns work directly with Python's `re`.

Key mappings:
  - id → name
  - regex → pattern
  - description → description (stored in metadata)
  - tags → tags
  - entropy → metadata.entropy
  - secretGroup → metadata.secret_group
  - keywords → metadata.keywords
  - allowlists → metadata.allowlists (preserved for reference)
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

log = logging.getLogger("crossfire.plugins.gitleaks")

# GitLeaks uses Go RE2 which doesn't support these Python regex features.
# We warn but don't fail — most patterns still work.
_RE2_INCOMPATIBLE = re.compile(r"\(\?[<!=]")  # lookahead/lookbehind


class GitleaksAdapter:
    """Adapter for GitLeaks .gitleaks.toml rule files."""

    @property
    def name(self) -> str:
        return "gitleaks"

    def can_load(self, path: str) -> bool:
        """Check if this is a GitLeaks TOML file.

        Returns True for .toml files that contain [[rules]] sections.
        Reads only the first 2KB to avoid loading large files.
        """
        p = Path(path)
        if p.suffix.lower() != ".toml":
            return False

        try:
            with open(p, errors="replace") as f:
                content = f.read(2048)
            return "[[rules]]" in content and ("regex" in content or "id" in content)
        except OSError:
            return False

    def load(self, path: str) -> list[dict[str, object]]:
        """Load rules from a GitLeaks TOML file.

        Returns a list of dicts with Crossfire-compatible field names.
        """
        data = self._parse_toml(path)
        raw_rules = data.get("rules", [])

        if not raw_rules:
            log.warning("No [[rules]] found in %s", path)
            return []

        results: list[dict[str, object]] = []
        for idx, rule in enumerate(raw_rules, start=1):
            converted = self._convert_rule(rule, idx, path)
            if converted:
                results.append(converted)

        log.info(
            "GitLeaks adapter: loaded %d rules from %s (%d total in file)",
            len(results),
            path,
            len(raw_rules),
        )
        return results

    def _parse_toml(self, path: str) -> dict[str, Any]:
        """Parse TOML file."""
        try:
            import tomllib
        except ImportError:
            try:
                import tomli as tomllib
            except ImportError as err:
                raise ImportError("TOML support requires Python 3.11+ or 'tomli' package") from err
        with open(path, "rb") as f:
            return tomllib.load(f)  # type: ignore[no-any-return]

    def _convert_rule(
        self,
        rule: dict[str, Any],
        idx: int,
        path: str,
    ) -> dict[str, object] | None:
        """Convert a GitLeaks rule dict to Crossfire format."""
        rule_id = rule.get("id", "")
        if not rule_id:
            log.warning("GitLeaks rule #%d in %s has no 'id', skipping", idx, path)
            return None

        regex = rule.get("regex", "")
        if not regex:
            log.warning("GitLeaks rule '%s' in %s has no 'regex', skipping", rule_id, path)
            return None

        # Warn about Python-incompatible RE2 patterns
        if _RE2_INCOMPATIBLE.search(regex):
            log.debug(
                "GitLeaks rule '%s': pattern uses lookahead/lookbehind "
                "(not RE2-native, may have been added for Python-based forks)",
                rule_id,
            )

        # Map severity from entropy/tags heuristic
        severity = self._infer_severity(rule)

        # Build metadata with GitLeaks-specific fields
        metadata: dict[str, object] = {}
        if rule.get("description"):
            metadata["description"] = rule["description"]
        if "entropy" in rule:
            metadata["entropy"] = rule["entropy"]
        if "secretGroup" in rule:
            metadata["secret_group"] = rule["secretGroup"]
        if rule.get("keywords"):
            metadata["keywords"] = rule["keywords"]
        if rule.get("path"):
            metadata["path_filter"] = rule["path"]
        if rule.get("allowlists"):
            metadata["allowlists"] = rule["allowlists"]

        tags = rule.get("tags", [])
        if not isinstance(tags, list):
            tags = []

        return {
            "name": rule_id,
            "pattern": regex,
            "detector": "secrets",
            "severity": severity,
            "tags": tags,
            "metadata": metadata,
        }

    def _infer_severity(self, rule: dict[str, Any]) -> str:
        """Infer severity from GitLeaks rule properties.

        GitLeaks doesn't have explicit severity, so we infer:
        - entropy >= 3.5 → likely high-confidence → critical
        - entropy >= 2.0 → medium confidence → high
        - Has keywords → targeted detection → high
        - Default → medium
        """
        entropy = rule.get("entropy", 0)
        has_keywords = bool(rule.get("keywords"))

        if entropy >= 3.5:
            return "critical"
        if entropy >= 2.0 or has_keywords:
            return "high"
        return "medium"
