# Supported Formats

Crossfire auto-detects format by file content — just pass the file:

```bash
crossfire compare gitleaks.toml semgrep.yaml yara_rules.yar community.json
```

| Format | Extensions | Tool |
|--------|-----------|------|
| JSON | `.json` | Any (native format, custom rules) |
| YAML | `.yaml`, `.yml` | Any |
| CSV | `.csv` | Any (`name` and `pattern` columns) |
| GitLeaks | `.toml` | [GitLeaks](https://github.com/gitleaks/gitleaks) |
| Semgrep | `.yaml` | [Semgrep](https://semgrep.dev) (`pattern-regex` rules) |
| YARA | `.yar`, `.yara` | [YARA](https://virustotal.github.io/yara/) (regex strings) |
| Sigma | `.yaml` | [Sigma](https://sigmahq.io) (`\|re` modifier fields) |
| Snort/Suricata | `.rules` | [Snort](https://www.snort.org) / [Suricata](https://suricata.io) (`pcre` patterns) |

## Native format (JSON/YAML/CSV)

Rules need at minimum a `name` and `pattern` field:

```json
[
  {"name": "aws_key", "pattern": "AKIA[0-9A-Z]{16}"},
  {"name": "slack_token", "pattern": "xoxb-[0-9]{11}-[0-9]{11}-[a-zA-Z0-9]{24}"}
]
```

## Custom field names

If your rules use different field names:

```bash
crossfire scan rules.json --field-mapping '{"name": "rule_id", "pattern": "regex"}'
```

Default mappings: `name`/`id`/`rule_name` and `pattern`/`regex`/`regexp`.

## Adding a new format

Crossfire uses a plugin system for format adapters. See [Contributing](../development/contributing.md) for how to add support for a new tool.
