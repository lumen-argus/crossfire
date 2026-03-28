# Configuration

## Configuration file

All CLI options can be set in `crossfire.yaml`:

```yaml
threshold: 0.8
samples_per_rule: 50
seed: 42
workers: 8
format: json
fail_on_duplicate: true
log_level: warning
```

Place this file in the directory where you run crossfire.

## Fail-fast validation

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

## Exit codes

| Code | Meaning |
|------|---------|
| `0` | Clean — no duplicates found |
| `1` | Duplicates found (with `--fail-on-duplicate`) |
| `2` | Input error (invalid file, bad regex) |
| `3` | Runtime error |

## Performance tuning

### RE2 regex acceleration

Install with RE2 support for 10-100x faster regex matching:

```bash
brew install re2           # macOS
pip install crossfire-rules[re2]
```

Crossfire automatically uses RE2 for compatible patterns and falls back to Python's `re` for patterns using backreferences or lookahead. No configuration needed — check the log output to confirm:

```
Analysis started: 3 file(s), regex engine: RE2 + re fallback
```

### Workers

Control parallel worker count with `--workers` or the `CROSSFIRE_WORKERS` environment variable:

```bash
crossfire scan rules.json --workers 8
# or
export CROSSFIRE_WORKERS=8
crossfire scan rules.json
```

Default is auto (CPU count).

## Logging

```bash
crossfire scan rules.json --log-level debug          # Verbose output
crossfire scan rules.json --log-format json           # Structured JSON logs
crossfire scan rules.json --log-file crossfire.log    # Write logs to file
```
