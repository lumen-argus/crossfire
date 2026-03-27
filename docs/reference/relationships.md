# Relationship Types

Crossfire classifies every rule pair into one of four relationship types:

| Relationship | Meaning | Example |
|-------------|---------|---------|
| **Duplicate** | Both rules match >80% of each other's test strings | `aws_key_v1` and `aws_key_v2` |
| **Subset** | Rule A matches everything B matches, but not vice versa | `stripe_sk_live` is a subset of `generic_secret` |
| **Overlap** | Partial co-firing (20-80%) — worth investigating | `github_token` and `generic_api_key` |
| **Disjoint** | No meaningful overlap | `aws_key` and `email_address` |

## Recommendations

For each non-disjoint pair, Crossfire provides a recommendation:

- **Duplicate**: drop the lower-priority rule (or review if equal priority)
- **Subset**: the superset rule covers everything — consider if the specific rule adds value
- **Overlap**: review manually — may be intentional

## Priority

Priority determines which rule to keep when duplicates are found:

- Default: determined by file order (first file = highest)
- Explicit: use `--priority` to set per-file priority values

```bash
crossfire compare --priority "curated.json=100,community.json=80,generated.json=50" \
  curated.json community.json generated.json
```

Higher priority values are preferred.

## Clustering

When multiple rules overlap with each other, Crossfire groups them into clusters. Each cluster identifies the highest-priority rule to keep and which rules can be dropped.

## Confidence intervals

All overlap measurements include 95% Wilson score confidence intervals. If the CI is wide (>30%), Crossfire warns that you should increase `--samples` for more reliable classification.
