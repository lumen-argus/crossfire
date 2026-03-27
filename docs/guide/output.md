# Output Formats

```bash
crossfire scan rules.json --format table    # Human-readable (default)
crossfire scan rules.json --format json     # Machine-readable for CI
crossfire scan rules.json --format csv      # Spreadsheet-friendly
crossfire scan rules.json --format summary  # One-line summary
```

## Table (default)

The default human-readable format. Shows duplicates, subsets, overlaps, clusters, and quality insights in a structured report.

## JSON

Machine-readable output for CI pipelines and programmatic consumption. Includes:

- All pairwise overlap results with confidence intervals (95% Wilson score CI)
- Per-rule quality metrics (specificity, complexity, unique coverage)
- Cluster information with keep/drop recommendations
- Full configuration and timing metadata

```bash
crossfire scan rules.json --format json --output report.json
```

## CSV

One row per overlapping pair. Spreadsheet-friendly for further analysis.

Columns: `rule_a`, `rule_b`, `source_a`, `source_b`, `overlap_a_to_b`, `overlap_b_to_a`, `jaccard`, `relationship`, `recommendation`, `reason`.

## Summary

A single-paragraph summary. Useful for CI log output:

```
Analyzed 142 rules from 1 file(s). Found 3 duplicate pair(s), 5 subset pair(s),
and 2 partial overlap(s) across 3 cluster(s). Recommendation: drop 7 rule(s),
review 3 rule(s). 2 broad pattern(s), 4 fully redundant rule(s).
```

## Writing to a file

All formats support `--output`:

```bash
crossfire scan rules.json --format json --output report.json
```
