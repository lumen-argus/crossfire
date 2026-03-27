# Quick Start

## 1. Check your rules are valid

```bash
crossfire validate rules.json
```

## 2. Find duplicates within a file

```bash
crossfire scan rules.json
```

## 3. Compare rules across files

```bash
crossfire compare community.json pro_rules.json vendor_rules.json
```

## 4. Test rules against real data

```bash
crossfire evaluate rules.json --corpus production_samples.jsonl
```

## What to do with the results

- **Duplicates**: drop the lower-priority rule
- **Subsets**: the superset rule covers everything — consider if the specific rule adds value
- **Overlaps**: review manually — may be intentional
- **Broad patterns**: rules overlapping with 5+ others deserve scrutiny
- **Zero unique coverage**: the rule is fully redundant and can be safely removed
