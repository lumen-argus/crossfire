# CLI Options Reference

## Global options

These options are available on all commands:

| Flag | Default | Description |
|------|---------|-------------|
| `--log-level` | `warning` | `debug`, `info`, `warning`, `error` |
| `--log-file` | None | Write logs to file |
| `--log-format` | `text` | `text` or `json` (structured) |

## scan / compare options

| Flag | Default | Description |
|------|---------|-------------|
| `--threshold` | `0.8` | Overlap % to classify as duplicate (0.0-1.0) |
| `--samples` | `50` | Test strings generated per rule |
| `--negative-samples` | `10` | Negative samples generated per rule |
| `--seed` | None | Random seed for reproducible results |
| `--workers` | auto | Parallel evaluation workers (0=auto) |
| `--format` | `table` | Output: `table`, `json`, `csv`, `summary` |
| `--output` / `-o` | stdout | Write report to file |
| `--skip-invalid` | off | Skip broken regexes instead of failing |
| `--fail-on-duplicate` | off | Exit code 1 if duplicates found |
| `--partition-by` | None | Only compare rules with same field value (e.g., `detector`) |

## compare-only options

| Flag | Default | Description |
|------|---------|-------------|
| `--priority` | by file order | Priority mapping (e.g., `curated.json=100,community.json=80`) |
| `--field-mapping` | None | Custom field name mapping as JSON |

## evaluate options

| Flag | Default | Description |
|------|---------|-------------|
| `--corpus` | required | JSONL corpus file to test rules against |
| `--corpus-field` | `text` | Field name for text content in JSONL |
| `--label-field` | `label` | Field name for ground-truth labels |
| `--redact-samples` | off | Don't include matched text in debug logs |

## evaluate-git options

| Flag | Default | Description |
|------|---------|-------------|
| `--repo` | required | Path to the git repository |
| `--max-commits` | `500` | Maximum number of commits to scan |

## diff options

| Flag | Default | Description |
|------|---------|-------------|
| `--corpus-a` | required | First JSONL corpus file |
| `--corpus-b` | required | Second JSONL corpus file |
| `--name-a` | `corpus_a` | Display name for first corpus |
| `--name-b` | `corpus_b` | Display name for second corpus |
| `--drift-threshold` | `0.05` | Minimum rate difference to flag as significant |
