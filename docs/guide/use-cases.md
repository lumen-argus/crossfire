# Use Cases

## Audit your rule set for redundancy

Over time, detection rules accumulate from different sources — hand-written, imported from vendors, merged from open-source projects. Run a scan to find what's redundant:

```bash
crossfire scan all_rules.json --format table
```

Drop rules with zero unique coverage. Review broad patterns that overlap with many specific rules.

## Compare community vs commercial rules

If you maintain both a free and a paid rule set, check for overlap before shipping:

```bash
crossfire compare community.json pro_rules.json --fail-on-duplicate
```

Use the JSON report to automate exclusion in your build pipeline — replace name-based dedup with overlap-based dedup.

## Prevent duplicate rules in CI

Add Crossfire to your CI pipeline so new rules that duplicate existing ones fail the build:

```bash
crossfire compare rules/*.json --fail-on-duplicate --format summary
```

Or use the [pre-commit hook](../ci/pre-commit.md) to catch duplicates before they're even committed.

## Cross-tool rule comparison

Migrating from GitLeaks to Semgrep? Merging YARA rules from a threat intel feed? Compare across formats:

```bash
crossfire compare gitleaks.toml semgrep_rules.yaml vendor_yara.yar
```

Find which rules are already covered and which are unique to each tool.

## Validate rules from third-party sources

Before importing rules from an external source, check they're valid and not duplicating what you already have:

```bash
# Syntax check first
crossfire validate vendor_rules.json

# Then check for overlap with your existing rules
crossfire compare your_rules.json vendor_rules.json
```

## Test rules against real data

Synthetic overlap analysis tells you rules *could* co-fire. Real corpus testing tells you they *do*:

```bash
# Test against a JSONL corpus of real findings
crossfire evaluate rules.json --corpus production_samples.jsonl

# Test against your repo's git history
crossfire evaluate-git rules.json --repo /path/to/repo --max-commits 500
```

See which rules actually fire, which co-fire on the same input, and which never fire at all.

## Measure rule quality with labeled data

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

## Detect coverage drift across environments

Rules that behave differently in production vs staging may indicate environment-specific issues:

```bash
crossfire diff rules.json --corpus-a production.jsonl --corpus-b staging.jsonl
```
