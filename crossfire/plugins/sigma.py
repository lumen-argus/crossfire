"""Sigma rule YAML format adapter.

Sigma rules describe log event detection using field-value matchers.
Most Sigma detection logic uses string matching with wildcards, not
raw regexes. This adapter extracts the `re` modifier patterns which
are explicit regexes.

Detection fields with `|re` modifier contain regex patterns:
  detection:
    selection:
      CommandLine|re: 'pattern.*here'
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

log = logging.getLogger("crossfire.plugins.sigma")

_SEVERITY_MAP = {
    "critical": "critical",
    "high": "high",
    "medium": "medium",
    "low": "low",
    "informational": "low",
}


class SigmaAdapter:
    """Adapter for Sigma YAML rule files."""

    @property
    def name(self) -> str:
        return "sigma"

    def can_load(self, path: str) -> bool:
        p = Path(path)
        if p.suffix.lower() not in (".yaml", ".yml"):
            return False
        try:
            with open(p, "r", errors="replace") as f:
                content = f.read(2048)
            return "detection:" in content and ("logsource:" in content or "title:" in content)
        except OSError:
            return False

    def load(self, path: str) -> list[dict[str, object]]:
        with open(path) as f:
            data = yaml.safe_load(f)

        if not isinstance(data, dict):
            log.warning("Invalid Sigma rule format in %s", path)
            return []

        # Sigma files can contain a single rule (dict) or multiple (list via ---separators)
        # yaml.safe_load returns the first document only
        results = self._convert_rule(data, path)

        if results:
            log.info("Sigma adapter: loaded %d regex patterns from %s", len(results), path)
        else:
            log.debug("Sigma rule %s has no regex patterns (|re modifiers)", path)

        return results

    def _convert_rule(
        self, rule: dict[str, Any], path: str,
    ) -> list[dict[str, object]]:
        """Extract regex patterns from a Sigma rule."""
        rule_id = rule.get("id", rule.get("title", ""))
        if not rule_id:
            log.warning("Sigma rule in %s has no 'id' or 'title', skipping", path)
            return []

        title = rule.get("title", rule_id)
        level = rule.get("level", "medium")
        severity = _SEVERITY_MAP.get(level, "medium")

        tags = rule.get("tags", [])
        if not isinstance(tags, list):
            tags = []

        detection = rule.get("detection", {})
        if not isinstance(detection, dict):
            return []

        metadata: dict[str, object] = {
            "title": title,
            "sigma_id": rule.get("id", ""),
        }
        if rule.get("description"):
            metadata["description"] = rule["description"]
        if rule.get("logsource"):
            metadata["logsource"] = rule["logsource"]
        if rule.get("status"):
            metadata["status"] = rule["status"]

        # Extract regex patterns from detection fields with |re modifier
        regexes = self._extract_regexes(detection)
        if not regexes:
            return []

        results: list[dict[str, object]] = []
        for i, (field_name, pattern) in enumerate(regexes):
            name = f"{rule_id}:{field_name}_{i+1}" if len(regexes) > 1 else str(rule_id)
            field_meta = dict(metadata)
            field_meta["sigma_field"] = field_name

            results.append({
                "name": name,
                "pattern": pattern,
                "detector": "sigma",
                "severity": severity,
                "tags": [str(t) for t in tags],
                "metadata": field_meta,
            })

        return results

    def _extract_regexes(
        self, detection: dict[str, Any],
    ) -> list[tuple[str, str]]:
        """Extract regex patterns from detection block.

        Looks for field names ending with |re modifier.
        Returns list of (field_name, regex_pattern).
        """
        regexes: list[tuple[str, str]] = []

        for key, value in detection.items():
            if key in ("condition", "timeframe"):
                continue

            if isinstance(value, dict):
                for field, patterns in value.items():
                    if "|re" in field:
                        base_field = field.split("|")[0]
                        if isinstance(patterns, list):
                            for p in patterns:
                                regexes.append((base_field, str(p)))
                        elif isinstance(patterns, str):
                            regexes.append((base_field, patterns))
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        for field, patterns in item.items():
                            if "|re" in field:
                                base_field = field.split("|")[0]
                                if isinstance(patterns, list):
                                    for p in patterns:
                                        regexes.append((base_field, str(p)))
                                elif isinstance(patterns, str):
                                    regexes.append((base_field, patterns))

        return regexes
