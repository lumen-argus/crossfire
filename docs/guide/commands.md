# Commands

## scan

Find duplicates and overlaps within one or more rule files.

```bash
crossfire scan rules.json
crossfire scan rules.json --format table --threshold 0.9
```

"Do I have redundant rules?"

## compare

Find overlaps between multiple rule files, with optional priority mapping.

```bash
crossfire compare community.json pro.json vendor_rules.json
crossfire compare --priority "curated.json=100,community.json=80" curated.json community.json
```

"Which rules overlap across my rule sets?"

## validate

Check regex syntax without running the full analysis.

```bash
crossfire validate rules.json
crossfire validate rules.json --skip-invalid
```

"Are all my regexes valid?" Fast — no corpus generation, just syntax check.

## evaluate

Test rules against a real-world JSONL corpus.

```bash
crossfire evaluate rules.json --corpus chat_logs.jsonl
```

"Which rules actually fire on real data? Which rules co-fire on the same input?"

If your corpus has labels, Crossfire computes precision, recall, and F1 per rule:

```jsonl
{"text": "AKIAIOSFODNN7EXAMPLE", "label": "aws_key"}
{"text": "xoxb-123-456-abc", "label": "slack_token"}
```

## evaluate-git

Test rules against a repository's git history.

```bash
crossfire evaluate-git rules.json --repo /path/to/repo --max-commits 500
```

Extracts added/modified lines from recent commits and tests rules against them.

## generate-corpus

Export the generated test strings for debugging or external use.

```bash
crossfire generate-corpus rules.json -o corpus.json
```

## diff

Compare rule behavior across two corpora. Flags rules with >5% match rate divergence.

```bash
crossfire diff rules.json --corpus-a production.jsonl --corpus-b staging.jsonl
```

"Do my rules behave differently across environments?"
