# Crossfire

Regex rule overlap analyzer for DLP, secret scanning, SAST, and IDS tools.

Crossfire detects duplicate, subset, and overlapping rules across detection
toolsets using corpus-based analysis. No existing tool does this — structural
regex analysis can't handle real-world patterns, and secret scanners only
deduplicate at the output level.

## Install

```bash
pip install crossfire
```

## Quick Start

```bash
# Check a single file for internal duplicates
crossfire scan rules.json

# Compare two rule sets for cross-file overlap
crossfire compare community.json pro.json

# Validate regex syntax
crossfire validate rules.json

# Test rules against real data
crossfire evaluate rules.json --corpus data.jsonl

# Test rules against git history
crossfire evaluate-git rules.json --repo /path/to/repo

# Compare rule behavior across two datasets
crossfire diff rules.json --corpus-a prod.jsonl --corpus-b staging.jsonl
```

## Supported Formats

Crossfire auto-detects format by file content:

| Format | Extensions | Tool |
|--------|-----------|------|
| JSON | `.json` | Any (Crossfire native, lumen-argus, custom) |
| YAML | `.yaml`, `.yml` | Any |
| CSV | `.csv` | Any |
| GitLeaks | `.toml` | [GitLeaks](https://github.com/gitleaks/gitleaks) |
| Semgrep | `.yaml` | [Semgrep](https://semgrep.dev) (pattern-regex rules) |
| YARA | `.yar`, `.yara` | [YARA](https://virustotal.github.io/yara/) |
| Sigma | `.yaml` | [Sigma](https://sigmahq.io) (|re modifier fields) |
| Snort | `.rules` | [Snort](https://www.snort.org) / [Suricata](https://suricata.io) (pcre patterns) |

Cross-tool comparison just works:

```bash
crossfire compare gitleaks.toml semgrep.yaml yara_rules.yar
```

## How It Works

1. **Load** rules from any supported format
2. **Validate** regexes (fail-fast by default)
3. **Generate** synthetic test strings from each regex pattern
4. **Cross-evaluate** every rule against every string
5. **Classify** relationships: duplicate, subset, overlap, disjoint
6. **Report** with quality insights, confidence intervals, and recommendations

## Output Formats

```bash
crossfire scan rules.json --format table    # Human-readable (default)
crossfire scan rules.json --format json     # Machine-readable (CI)
crossfire scan rules.json --format csv      # Spreadsheet
crossfire scan rules.json --format summary  # One-line summary
```

## CI Integration

### GitHub Action

```yaml
- uses: crossfire-tools/crossfire@v1
  with:
    rules: rules/*.json
    threshold: "0.8"
    fail-on-duplicate: "true"
```

### Pre-commit Hook

```yaml
repos:
  - repo: https://github.com/crossfire-tools/crossfire
    rev: v0.1.0
    hooks:
      - id: crossfire-scan
        args: ["--format", "summary", "--samples", "30"]
      - id: crossfire-validate
```

### CLI in CI Pipeline

```bash
pip install crossfire
crossfire compare rules/*.json --fail-on-duplicate --format summary
```

## Key Features

- **Fail-fast validation**: Invalid regex stops immediately with a clear error. Use `--skip-invalid` for lenient mode.
- **Confidence intervals**: Wilson score 95% CI on all overlap measurements. Warns when sample size is too low.
- **Quality scoring**: Per-rule specificity, false positive potential, unique coverage, pattern complexity.
- **Broad pattern detection**: Flags "umbrella" rules that overlap with many others.
- **Reproducible**: `--seed 42` produces identical results across runs.
- **Observable**: Structured logging (`--log-level debug --log-file crossfire.log`).

## Configuration

All CLI flags can be set in a `crossfire.yaml` config file:

```yaml
threshold: 0.8
samples_per_rule: 50
seed: 42
workers: 8
format: json
fail_on_duplicate: true
log_level: warning
```

## License

MIT
