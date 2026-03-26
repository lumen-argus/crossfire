"""YARA rule file adapter.

Parses .yar/.yara files to extract regex strings from the `strings:` section.
Only regex patterns (delimited by `/`) are extracted — text strings and hex
strings are skipped since they're not regex-comparable.

Each YARA regex string becomes a separate Crossfire rule named
`{rule_name}:{string_id}`.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

log = logging.getLogger("crossfire.plugins.yara")

# Match: $identifier = /pattern/modifiers
_REGEX_STRING = re.compile(
    r'^\s*(\$\w+)\s*=\s*/((?:[^/\\]|\\.)*)/(.*?)$'
)

# Match: rule name : tags {
_RULE_START = re.compile(
    r'^\s*rule\s+(\w+)(?:\s*:\s*([\w\s]+))?\s*\{?\s*$'
)


class YaraAdapter:
    """Adapter for YARA .yar/.yara rule files."""

    @property
    def name(self) -> str:
        return "yara"

    def can_load(self, path: str) -> bool:
        p = Path(path)
        if p.suffix.lower() not in (".yar", ".yara"):
            return False
        try:
            with open(p, "r", errors="replace") as f:
                content = f.read(2048)
            return "rule " in content and "strings:" in content
        except OSError:
            return False

    def load(self, path: str) -> list[dict[str, object]]:
        with open(path, "r", errors="replace") as f:
            content = f.read()

        results: list[dict[str, object]] = []
        rules = self._parse_rules(content, path)

        for rule_name, meta, regex_strings in rules:
            for string_id, pattern, modifiers in regex_strings:
                name = f"{rule_name}:{string_id}"
                severity = str(meta.get("severity", "medium"))

                tags_raw = meta.get("tags", [])
                tags = tags_raw if isinstance(tags_raw, list) else []

                metadata: dict[str, object] = {}
                if modifiers:
                    metadata["yara_modifiers"] = modifiers
                for k, v in meta.items():
                    if k not in ("severity", "tags"):
                        metadata[k] = v

                results.append({
                    "name": name,
                    "pattern": pattern,
                    "detector": "secrets",
                    "severity": severity,
                    "tags": tags,
                    "metadata": metadata,
                })

        log.info("YARA adapter: loaded %d regex patterns from %s", len(results), path)
        return results

    def _parse_rules(
        self, content: str, path: str,
    ) -> list[tuple[str, dict[str, Any], list[tuple[str, str, str]]]]:
        """Parse YARA rules from file content.

        Returns list of (rule_name, metadata_dict, regex_strings).
        regex_strings is list of (string_id, pattern, modifiers).
        """
        rules: list[tuple[str, dict[str, Any], list[tuple[str, str, str]]]] = []
        lines = content.splitlines()

        current_rule = ""
        current_meta: dict[str, Any] = {}
        current_strings: list[tuple[str, str, str]] = []
        section = ""  # "", "meta", "strings", "condition"
        in_block_comment = False

        for line in lines:
            stripped = line.strip()

            # Handle block comments
            if in_block_comment:
                if "*/" in stripped:
                    in_block_comment = False
                    stripped = stripped[stripped.index("*/") + 2:].strip()
                    if not stripped:
                        continue
                else:
                    continue

            if "/*" in stripped:
                before = stripped[:stripped.index("/*")].strip()
                if before:
                    stripped = before
                else:
                    if "*/" not in stripped[stripped.index("/*") + 2:]:
                        in_block_comment = True
                    continue

            # Skip line comments
            if stripped.startswith("//"):
                continue
            if "//" in stripped:
                stripped = stripped[:stripped.index("//")].strip()

            # Skip empty lines, imports, includes
            if not stripped or stripped.startswith("import ") or stripped.startswith("include "):
                continue

            # Rule start
            m = _RULE_START.match(stripped)
            if m:
                # Save previous rule if any
                if current_rule and current_strings:
                    rules.append((current_rule, current_meta, current_strings))

                current_rule = m.group(1)
                rule_tags = m.group(2)
                current_meta = {}
                if rule_tags:
                    current_meta["tags"] = rule_tags.split()
                current_strings = []
                section = ""
                continue

            # Section headers
            if stripped == "meta:" or stripped.startswith("meta:"):
                section = "meta"
                continue
            if stripped == "strings:" or stripped.startswith("strings:"):
                section = "strings"
                continue
            if stripped == "condition:" or stripped.startswith("condition:"):
                section = "condition"
                continue

            # Closing brace — end of rule
            if stripped == "}":
                if current_rule and current_strings:
                    rules.append((current_rule, current_meta, current_strings))
                current_rule = ""
                current_meta = {}
                current_strings = []
                section = ""
                continue

            # Parse meta section
            if section == "meta" and "=" in stripped:
                key, _, value = stripped.partition("=")
                key = key.strip()
                value = value.strip().strip('"')
                if value.lower() in ("true", "false"):
                    current_meta[key] = value.lower() == "true"
                else:
                    try:
                        current_meta[key] = int(value)
                    except ValueError:
                        current_meta[key] = value

            # Parse strings section — extract regex patterns
            if section == "strings":
                rm = _REGEX_STRING.match(stripped)
                if rm:
                    string_id = rm.group(1).lstrip("$")
                    pattern = rm.group(2)
                    modifiers = rm.group(3).strip()
                    # Unescape forward slashes
                    pattern = pattern.replace("\\/", "/")
                    current_strings.append((string_id, pattern, modifiers))

        # Handle last rule
        if current_rule and current_strings:
            rules.append((current_rule, current_meta, current_strings))

        return rules
