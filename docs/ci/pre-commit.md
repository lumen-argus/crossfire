# Pre-commit Hooks

Crossfire provides two pre-commit hooks to catch rule issues before they're committed.

## Setup

Add to your `.pre-commit-config.yaml`:

```yaml
repos:
  - repo: https://github.com/lumen-argus/crossfire
    rev: v0.1.0
    hooks:
      - id: crossfire-scan
        args: ["--format", "summary", "--samples", "30"]
      - id: crossfire-validate
```

## Available hooks

### crossfire-scan

Runs overlap analysis on changed rule files. Useful for catching duplicates early.

The `--samples 30` argument reduces the sample count for faster pre-commit execution. Use higher values in CI for more accurate results.

### crossfire-validate

Validates regex syntax in rule files. Fast — no corpus generation, just syntax checking.
