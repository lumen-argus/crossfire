# GitHub Action

Crossfire provides a GitHub Action for CI integration.

## Basic usage

```yaml
- uses: lumen-argus/crossfire@v1
  with:
    rules: rules/*.json
    threshold: "0.8"
    fail-on-duplicate: "true"
```

## Inputs

| Input | Required | Default | Description |
|-------|----------|---------|-------------|
| `rules` | Yes | | Glob pattern for rule files |
| `command` | No | `scan` | Command to run (`scan`, `compare`, `validate`) |
| `threshold` | No | `0.8` | Overlap threshold |
| `fail-on-duplicate` | No | `false` | Fail if duplicates found |
| `format` | No | `summary` | Output format |
| `crossfire-version` | No | `latest` | Crossfire version to install |

## Example: Compare on pull request

```yaml
name: Rule overlap check
on: [pull_request]

jobs:
  crossfire:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: lumen-argus/crossfire@v1
        with:
          rules: rules/*.json
          command: compare
          fail-on-duplicate: "true"
          format: summary
```
