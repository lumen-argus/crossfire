"""Snort/Suricata IDS rule adapter.

Extracts regex patterns from `pcre` keywords in Snort/Suricata rules.
Only `pcre` keywords contain regex — `content` keywords use literal
string matching and are skipped.

Rule format: action protocol src_ip src_port -> dst_ip dst_port (options)
PCRE format: pcre:"/pattern/modifiers";
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

log = logging.getLogger("crossfire.plugins.snort")

# Match pcre:"/pattern/modifiers";
_PCRE_PATTERN = re.compile(r'pcre\s*:\s*"/((?:[^/\\]|\\.)*)/(.*?)"')

# Match rule header for metadata
_RULE_HEADER = re.compile(r"^(alert|drop|reject|pass|log)\s+", re.MULTILINE)

# Extract msg:"..." from options
_MSG_PATTERN = re.compile(r'msg\s*:\s*"([^"]*)"')

# Extract sid:N from options
_SID_PATTERN = re.compile(r"sid\s*:\s*(\d+)")

# Extract classtype:... from options
_CLASSTYPE_PATTERN = re.compile(r"classtype\s*:\s*([^;]+)")

# Extract priority:N from options
_PRIORITY_PATTERN = re.compile(r"priority\s*:\s*(\d+)")


class SnortAdapter:
    """Adapter for Snort/Suricata .rules files."""

    @property
    def name(self) -> str:
        return "snort"

    def can_load(self, path: str) -> bool:
        p = Path(path)
        if p.suffix.lower() != ".rules":
            return False
        try:
            with open(p, errors="replace") as f:
                content = f.read(4096)
            return bool(_RULE_HEADER.search(content)) and "pcre" in content
        except OSError:
            return False

    def load(self, path: str) -> list[dict[str, object]]:
        results: list[dict[str, object]] = []

        with open(path, errors="replace") as f:
            for line_num, line in enumerate(f, start=1):
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if not _RULE_HEADER.match(line):
                    continue

                converted = self._convert_rule(line, line_num, path)
                results.extend(converted)

        log.info("Snort adapter: loaded %d PCRE patterns from %s", len(results), path)
        return results

    def _convert_rule(
        self,
        line: str,
        line_num: int,
        path: str,
    ) -> list[dict[str, object]]:
        """Extract PCRE patterns from a Snort rule line."""
        pcre_matches = _PCRE_PATTERN.findall(line)
        if not pcre_matches:
            return []

        # Extract metadata from rule options
        msg_m = _MSG_PATTERN.search(line)
        sid_m = _SID_PATTERN.search(line)
        classtype_m = _CLASSTYPE_PATTERN.search(line)
        priority_m = _PRIORITY_PATTERN.search(line)

        msg = msg_m.group(1) if msg_m else ""
        sid = sid_m.group(1) if sid_m else str(line_num)
        classtype = classtype_m.group(1).strip() if classtype_m else ""
        priority = int(priority_m.group(1)) if priority_m else 3

        severity = self._priority_to_severity(priority)

        metadata: dict[str, object] = {}
        if msg:
            metadata["message"] = msg
        if classtype:
            metadata["classtype"] = classtype

        tags: list[str] = []
        if classtype:
            tags.append(classtype)

        results: list[dict[str, object]] = []
        for i, (pattern, modifiers) in enumerate(pcre_matches):
            # Unescape forward slashes
            pattern = pattern.replace("\\/", "/")

            name = f"sid:{sid}" if len(pcre_matches) == 1 else f"sid:{sid}_pcre{i + 1}"

            pcre_meta = dict(metadata)
            if modifiers:
                pcre_meta["pcre_modifiers"] = modifiers

            results.append(
                {
                    "name": name,
                    "pattern": pattern,
                    "detector": "ids",
                    "severity": severity,
                    "tags": list(tags),
                    "metadata": pcre_meta,
                }
            )

        return results

    def _priority_to_severity(self, priority: int) -> str:
        """Map Snort priority (1=highest) to severity."""
        if priority <= 1:
            return "critical"
        if priority <= 2:
            return "high"
        if priority <= 3:
            return "medium"
        return "low"
