# Quality Metrics

Beyond pairwise overlap, Crossfire assesses each rule individually.

## Specificity

Does this rule match random strings? Crossfire generates random strings and tests each rule against them. Low specificity (matching >90% of random strings) indicates an overly broad pattern.

## Unique coverage

Do any test strings match *only* this rule? If a rule has zero unique coverage, everything it matches is already caught by other rules — it's fully redundant.

## Broad pattern detection

Rules that overlap with 5 or more other rules are flagged as broad patterns. These are common sources of duplicate findings (e.g., a `generic_secret` rule that overlaps with 15 specific secret rules).

## Pattern complexity

The regex AST (abstract syntax tree) node count. Informational — higher complexity doesn't necessarily mean better or worse, but very simple patterns (e.g., `.*`) are likely too broad.

## Quality flags

Each rule can receive one or more flags:

- **Low specificity** — matches >90% of random strings
- **Broad pattern** — overlaps with 5+ rules
- **Zero unique coverage** — fully redundant
- **High complexity** — >50 AST nodes

These flags appear in the JSON output and in the Quality Insights section of the table report.
