"""Semgrep YAML format adapter.

Handles Semgrep rule files, extracting regex patterns from:
- pattern-regex (top-level)
- patterns[].pattern-regex (AND combinations)
- pattern-either[].pattern-regex (OR combinations)

Non-regex rules (AST-based `pattern` field) are skipped since they
aren't comparable as regex overlap.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

log = logging.getLogger("crossfire.plugins.semgrep")

_SEVERITY_MAP = {
    "ERROR": "critical",
    "WARNING": "high",
    "INFO": "medium",
}


class SemgrepAdapter:
    """Adapter for Semgrep YAML rule files."""

    @property
    def name(self) -> str:
        return "semgrep"

    def can_load(self, path: str) -> bool:
        p = Path(path)
        if p.suffix.lower() not in (".yaml", ".yml"):
            return False
        try:
            with open(p, "r", errors="replace") as f:
                content = f.read(2048)
            return "rules:" in content and "pattern-regex" in content
        except OSError:
            return False

    def load(self, path: str) -> list[dict[str, object]]:
        with open(path) as f:
            data = yaml.safe_load(f)

        if not isinstance(data, dict) or "rules" not in data:
            log.warning("No 'rules' key found in %s", path)
            return []

        results: list[dict[str, object]] = []
        for idx, rule in enumerate(data["rules"], start=1):
            converted = self._convert_rule(rule, idx, path)
            results.extend(converted)

        log.info("Semgrep adapter: loaded %d regex rules from %s", len(results), path)
        return results

    def _convert_rule(
        self, rule: dict[str, Any], idx: int, path: str,
    ) -> list[dict[str, object]]:
        """Extract regex patterns from a Semgrep rule.

        A single Semgrep rule can contain multiple regex patterns
        (via patterns/pattern-either), so this returns a list.
        """
        rule_id = rule.get("id", "")
        if not rule_id:
            log.warning("Semgrep rule #%d in %s has no 'id', skipping", idx, path)
            return []

        severity = _SEVERITY_MAP.get(rule.get("severity", ""), "medium")
        tags_raw = rule.get("metadata", {}).get("technology", [])
        tags = tags_raw if isinstance(tags_raw, list) else []

        metadata: dict[str, object] = {}
        if rule.get("message"):
            metadata["message"] = rule["message"]
        if rule.get("metadata"):
            metadata["semgrep_metadata"] = rule["metadata"]
        if rule.get("languages"):
            metadata["languages"] = rule["languages"]

        regexes = self._extract_regexes(rule)
        if not regexes:
            return []

        results: list[dict[str, object]] = []
        if len(regexes) == 1:
            results.append({
                "name": rule_id,
                "pattern": regexes[0],
                "detector": "secrets",
                "severity": severity,
                "tags": tags,
                "metadata": metadata,
            })
        else:
            # Multiple regexes in one rule — create sub-rules
            for i, regex in enumerate(regexes):
                results.append({
                    "name": f"{rule_id}_{i+1}",
                    "pattern": regex,
                    "detector": "secrets",
                    "severity": severity,
                    "tags": tags,
                    "metadata": metadata,
                })

        return results

    def _extract_regexes(self, rule: dict[str, Any]) -> list[str]:
        """Extract all regex patterns from a rule."""
        regexes: list[str] = []

        # Top-level pattern-regex
        if "pattern-regex" in rule:
            regexes.append(str(rule["pattern-regex"]))

        # patterns (AND combination)
        for item in rule.get("patterns", []):
            if isinstance(item, dict) and "pattern-regex" in item:
                regexes.append(str(item["pattern-regex"]))

        # pattern-either (OR combination)
        for item in rule.get("pattern-either", []):
            if isinstance(item, dict) and "pattern-regex" in item:
                regexes.append(str(item["pattern-regex"]))

        return regexes
