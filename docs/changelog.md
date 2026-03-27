# Changelog

All notable changes to Crossfire will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-03-26

### Added

- Core overlap analysis engine with corpus-based approach
  - `scan` command for finding internal duplicates within a file
  - `compare` command for cross-file overlap detection
  - `validate` command for regex syntax checking
  - `generate-corpus` command for exporting test strings
- Relationship classification: duplicate, subset, superset, overlap, disjoint
- Clustering of overlapping rules with keep/drop recommendations
- Priority-based recommendations (configurable per file)
- Wilson score 95% confidence intervals on all overlap measurements
- Per-rule quality scoring
  - Specificity (random string match rate)
  - False positive potential
  - Unique coverage
  - Pattern complexity (regex AST depth)
  - Broad pattern detection (rules overlapping with 5+ others)
- Real-world corpus evaluation
  - `evaluate` command for testing rules against JSONL corpus
  - `evaluate-git` command for testing rules against git history
  - Labeled evaluation with precision, recall, F1 per rule
  - Co-firing detection (rules firing on the same input)
- Differential analysis
  - `diff` command for comparing rule behavior across two corpora
  - Coverage drift detection (>5% match rate divergence)
- Format adapters with auto-detection
  - JSON (native format)
  - YAML
  - CSV
  - GitLeaks (.toml)
  - Semgrep (.yaml, pattern-regex rules)
  - YARA (.yar, regex strings)
  - Sigma (.yaml, |re modifier fields)
  - Snort/Suricata (.rules, pcre patterns)
- Plugin system for external format adapters via entry_points
- Output formats: table, JSON, CSV, summary
- Parallel evaluation via ProcessPoolExecutor
- Fail-fast validation with `--skip-invalid` opt-in
- Reproducible results with `--seed`
- Structured logging (text and JSON formats)
- GitHub Action for CI integration
- Pre-commit hooks (crossfire-scan, crossfire-validate)
- CI pipelines (test on Python 3.10-3.13, release to PyPI)
