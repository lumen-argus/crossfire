# Crossfire

**Find duplicate and overlapping regex rules before they create duplicate alerts.**

If you maintain detection rules for secret scanning, DLP, SAST, YARA, or IDS — you probably have rules that fire on the same input. Crossfire finds them.

```
$ crossfire scan my_rules.json

========================================================================
  Crossfire Analysis Report
  Rules: 142 from 1 file(s) | Corpus: 4,260 strings | Time: 3.2s
========================================================================

  Duplicates (3 pairs)
  Rule A                    Rule B                     Jaccard Recommendation
  aws_key_v1                aws_key_v2                   1.00      Keep A
  slack_hook                slack_webhook_url            0.94      Keep A
  npm_token                 npm_auth_token               1.00      Keep A

  Subsets (5 pairs)
  Subset Rule               Superset Rule               A->B %
  stripe_sk_live            generic_secret                 98%
  github_pat_v2             github_token                  100%

  Quality Insights
  Broad patterns (2):
    generic_secret           overlaps with 15 rules
    email                    overlaps with 27 rules

  Summary: Drop 7 rules, review 3, 2 broad patterns
```

## The Problem

Detection rule sets grow over time. Different team members add rules independently. You merge rules from upstream projects. Eventually:

- Multiple rules match the same secret (duplicate findings)
- Broad rules like `generic_secret` silently cover what specific rules already catch
- Nobody knows which rules to remove without breaking coverage

**No existing tool solves this.** Regex equivalence is undecidable for real-world patterns (anchors, lookahead, backreferences). YARA dedup tools only find exact matches. Secret scanners handle duplicates at the output level — too late.

## How Crossfire Works

Crossfire uses a **corpus-based approach**: generate synthetic strings from each rule's regex, test every rule against every string, and measure overlap empirically.

```
Load rules → Validate regexes → Generate test strings → Cross-evaluate → Classify → Report
```

This handles any regex feature Python supports — anchors, lookahead, backreferences, Unicode. No structural analysis limitations.

## Install

```bash
pip install crossfire-rules
```

For **10-100x faster regex matching** on large rule sets, install with RE2 support:

```bash
# macOS
brew install re2
pip install crossfire-rules[re2]

# Ubuntu/Debian
sudo apt-get install -y libre2-dev
pip install crossfire-rules[re2]
```

RE2 is optional — Crossfire works fine without it using Python's stdlib `re`. RE2 accelerates patterns that don't use backreferences or lookahead (most DLP/secret-scanning rules). Incompatible patterns automatically fall back to `re` per-pattern.

Or install from source:

```bash
git clone https://github.com/lumen-argus/crossfire.git
cd crossfire
pip install -e .
```

Requires Python 3.11+.

## Commands

### Scan — find duplicates within a file

```bash
crossfire scan rules.json
```

"Do I have redundant rules?"

### Compare — find overlaps between files

```bash
crossfire compare community.json pro.json vendor_rules.json
```

"Which rules overlap across my rule sets?"

### Validate — check regex syntax

```bash
crossfire validate rules.json
```

"Are all my regexes valid?" Fast — no corpus generation, just syntax check.

### Evaluate — test rules against real data

```bash
# Test against a JSONL corpus
crossfire evaluate rules.json --corpus chat_logs.jsonl

# Test against git history
crossfire evaluate-git rules.json --repo /path/to/repo --max-commits 500
```

"Which rules actually fire on real data? Which rules co-fire on the same input?"

If your corpus has labels, Crossfire computes precision, recall, and F1 per rule:

```jsonl
{"text": "AKIAIOSFODNN7EXAMPLE", "label": "aws_key"}
{"text": "xoxb-123-456-abc", "label": "slack_token"}
```

### Diff — compare rule behavior across environments

```bash
crossfire diff rules.json --corpus-a production.jsonl --corpus-b staging.jsonl
```

"Do my rules behave differently across environments?" Flags rules with >5% match rate divergence.

## Supported Formats

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

### Custom field names

If your rules use different field names:

```bash
crossfire scan rules.json --field-mapping '{"name": "rule_id", "pattern": "regex"}'
```

Default mappings: `name`/`id`/`rule_name` and `pattern`/`regex`/`regexp`.

## Use Cases

### Audit your rule set for redundancy

Over time, detection rules accumulate from different sources — hand-written, imported from vendors, merged from open-source projects. Run a scan to find what's redundant:

```bash
crossfire scan all_rules.json --format table
```

Drop rules with zero unique coverage. Review broad patterns that overlap with many specific rules.

### Compare community vs commercial rules

If you maintain both a free and a paid rule set, check for overlap before shipping:

```bash
crossfire compare community.json pro_rules.json --fail-on-duplicate
```

Use the JSON report to automate exclusion in your build pipeline — replace name-based dedup with overlap-based dedup.

### Prevent duplicate rules in CI

Add Crossfire to your CI pipeline so new rules that duplicate existing ones fail the build:

```bash
crossfire compare rules/*.json --fail-on-duplicate --format summary
```

Or use the pre-commit hook to catch duplicates before they're even committed.

### Cross-tool rule comparison

Migrating from GitLeaks to Semgrep? Merging YARA rules from a threat intel feed? Compare across formats:

```bash
crossfire compare gitleaks.toml semgrep_rules.yaml vendor_yara.yar
```

Find which rules are already covered and which are unique to each tool.

### Validate rules from third-party sources

Before importing rules from an external source, check they're valid and not duplicating what you already have:

```bash
# Syntax check first
crossfire validate vendor_rules.json

# Then check for overlap with your existing rules
crossfire compare your_rules.json vendor_rules.json
```

### Test rules against real data

Synthetic overlap analysis tells you rules *could* co-fire. Real corpus testing tells you they *do*:

```bash
# Test against a JSONL corpus of real findings
crossfire evaluate rules.json --corpus production_samples.jsonl

# Test against your repo's git history
crossfire evaluate-git rules.json --repo /path/to/repo --max-commits 500
```

See which rules actually fire, which co-fire on the same input, and which never fire at all.

### Measure rule quality with labeled data

If you have labeled test data, Crossfire computes precision, recall, and F1 per rule:

```bash
crossfire evaluate rules.json --corpus labeled_test_data.jsonl
```

Corpus format — one JSON object per line with `text` and `label` fields:

```jsonl
{"text": "AKIAIOSFODNN7EXAMPLE", "label": "aws_key"}
{"text": "xoxb-123-456-abcdef", "label": "slack_token"}
{"text": "not a secret at all", "label": ""}
```

### Detect coverage drift across environments

Rules that behave differently in production vs staging may indicate environment-specific issues:

```bash
crossfire diff rules.json --corpus-a production.jsonl --corpus-b staging.jsonl
```

## Output Formats

```bash
crossfire scan rules.json --format table    # Human-readable (default)
crossfire scan rules.json --format json     # Machine-readable for CI
crossfire scan rules.json --format csv      # Spreadsheet-friendly
crossfire scan rules.json --format summary  # One-line summary
```

JSON output includes confidence intervals (95% Wilson score CI) on every overlap measurement and per-rule quality metrics.

## Relationship Types

Crossfire classifies every rule pair:

| Relationship | Meaning | Example |
|-------------|---------|---------|
| **Duplicate** | Both rules match >80% of each other's test strings | `aws_key_v1` and `aws_key_v2` |
| **Subset** | Rule A matches everything B matches, but not vice versa | `stripe_sk_live` is a subset of `generic_secret` |
| **Overlap** | Partial co-firing (20-80%) — worth investigating | `github_token` and `generic_api_key` |
| **Disjoint** | No meaningful overlap | `aws_key` and `email_address` |

### Recommendations

- **Duplicate**: drop the lower-priority rule (or review if equal priority)
- **Subset**: the superset rule covers everything — consider if the specific rule adds value
- **Overlap**: review manually — may be intentional

Priority is determined by file order (first file = highest) or explicit `--priority`:

```bash
crossfire compare --priority "curated.json=100,community.json=80,generated.json=50" \
  curated.json community.json generated.json
```

## Quality Insights

Beyond pairwise overlap, Crossfire assesses each rule individually:

- **Specificity**: does this rule match random strings? Low specificity = overly broad
- **Unique coverage**: do any test strings match *only* this rule? Zero = fully redundant
- **Broad pattern detection**: rules overlapping with 5+ others are flagged
- **Pattern complexity**: regex AST node count (informational)

## Fail-Fast Validation

By default, Crossfire fails immediately on the first invalid regex:

```
$ crossfire scan rules.json
ERROR: Rule 'broken_rule' has invalid regex: unbalanced parenthesis at position 12
  Pattern: [a-z(+
  File: rules.json, entry 47

Fix the pattern and retry. Use --skip-invalid to analyze remaining rules anyway.
```

Use `--skip-invalid` to continue despite broken rules (for third-party rule sets you can't fix):

```bash
crossfire scan vendor_rules.json --skip-invalid
```

## CI Integration

### GitHub Action

```yaml
- uses: lumen-argus/crossfire@v1
  with:
    rules: rules/*.json
    threshold: "0.8"
    fail-on-duplicate: "true"
```

### Pre-commit Hook

```yaml
repos:
  - repo: https://github.com/lumen-argus/crossfire
    rev: v0.1.0
    hooks:
      - id: crossfire-scan
        args: ["--format", "summary", "--samples", "30"]
      - id: crossfire-validate
```

### Any CI Pipeline

```bash
pip install crossfire-rules
crossfire compare rules/*.json --fail-on-duplicate --format summary
```

Exit codes: `0` = clean, `1` = duplicates found (`--fail-on-duplicate`), `2` = input error, `3` = runtime error.

## Options Reference

| Flag | Default | Description |
|------|---------|-------------|
| `--threshold` | `0.8` | Overlap % to classify as duplicate (0.0-1.0) |
| `--samples` | `50` | Test strings generated per rule |
| `--seed` | None | Random seed for reproducible results |
| `--workers` | auto | Parallel evaluation workers |
| `--format` | `table` | Output: `table`, `json`, `csv`, `summary` |
| `--output` | stdout | Write report to file |
| `--skip-invalid` | off | Skip broken regexes instead of failing |
| `--fail-on-duplicate` | off | Exit code 1 if duplicates found |
| `--partition-by` | None | Only compare rules with same field value (e.g., `detector`) |
| `--priority` | by file order | `file.json=100` priority mapping |
| `--log-level` | `warning` | `debug`, `info`, `warning`, `error` |
| `--log-file` | None | Write logs to file |
| `--log-format` | `text` | `text` or `json` (structured) |

## Configuration File

All options can be set in `crossfire.yaml`:

```yaml
threshold: 0.8
samples_per_rule: 50
seed: 42
workers: 8
format: json
fail_on_duplicate: true
log_level: warning
```

## Performance

Tested on 1,722 real detection rules (54 community + 1,668 commercial):

| Step | Time |
|------|------|
| Load + validate | <1s |
| Generate corpus (30 samples/rule) | ~26s |
| Cross-evaluate (72M regex matches) | ~3s |
| Classify + quality assessment | <1s |
| **Total** | **~30s** |

Results: 22 duplicates, 249 subsets, 82 overlaps, 18 clusters, 31 broad patterns, 240 fully redundant rules.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, coding standards, and how to add format adapters.

## License

MIT - see [LICENSE](LICENSE) for details.
