# Architecture

## Pipeline

Crossfire follows a linear pipeline:

```
Load -> Validate (fail-fast) -> Generate corpus -> Cross-evaluate -> Classify -> Report
```

## Module overview

### Orchestration

- **`analyzer.py`** — Coordinates the full pipeline. Entry point for programmatic use.
- **`cli.py`** — Click CLI with `scan`, `compare`, `validate`, `generate-corpus`, `evaluate`, `evaluate-git`, `diff` commands.

### Core pipeline

- **`regex.py`** — Regex compilation with optional RE2 acceleration. Tries `google-re2` first (Thompson NFA, 10-100x faster), falls back to stdlib `re` per-pattern for PCRE-only features (backreferences, lookahead).
- **`loader.py`** — Format-agnostic rule loading (JSON/YAML/CSV/TOML) with fail-fast validation. Delegates to plugins for tool-specific formats. Uses `regex.py` for compilation.
- **`generator.py`** — Corpus generation via `rstr` + fallback. Generates positive and negative samples per rule, with per-rule timeout and deduplication. Parallelized across rules for large rule sets.
- **`evaluator.py`** — Parallel cross-rule regex evaluation (NxN match matrix). Uses `ProcessPoolExecutor` with corpus-chunked parallelism (each worker gets all rules + a corpus slice). Uses `regex.py` for compilation in workers.
- **`classifier.py`** — Relationship classification (duplicate/subset/superset/overlap/disjoint), clustering with keep/drop recommendations, Wilson score confidence intervals.
- **`reporter.py`** — Output rendering (JSON/table/CSV/summary) with quality insights.

### Quality and evaluation

- **`quality.py`** — Per-rule quality scoring: specificity, false positive potential, unique coverage, broad pattern detection, pattern complexity (via regex AST).
- **`confidence.py`** — Wilson score confidence intervals for overlap proportions.
- **`corpus.py`** — Real-world corpus loading (JSONL + git history), labeled evaluation (precision/recall/F1), differential analysis (coverage drift).

### Data model

- **`models.py`** — Core dataclasses: `Rule`, `CorpusEntry`, `OverlapResult`, `AnalysisReport`.
- **`errors.py`** — `CrossfireError`, `ValidationError`, `LoadError`, `GenerationError`.
- **`logging.py`** — Structured logging (text + JSON formats).

### Plugin system

- **`plugins/__init__.py`** — Plugin registry with `RuleAdapter` protocol and entry_point discovery.
- **`plugins/gitleaks.py`** — GitLeaks `.gitleaks.toml` adapter.
- **`plugins/semgrep.py`** — Semgrep YAML adapter (extracts `pattern-regex`).
- **`plugins/yara.py`** — YARA `.yar` adapter (regex strings from `strings:` section).
- **`plugins/sigma.py`** — Sigma YAML adapter (`|re` modifier patterns).
- **`plugins/snort.py`** — Snort/Suricata `.rules` adapter (`pcre` patterns).

## Key design decisions

- **Fail-fast by default**: Invalid regex, empty pattern, duplicate names cause immediate failure. `--skip-invalid` for lenient mode.
- **Corpus-based, not structural**: Generates strings from regexes and tests empirically. Handles any Python `re` feature.
- **`rstr`** for string generation (BSD license), not exrex (AGPL).
- **`ProcessPoolExecutor`** for parallel evaluation — regexes re-compiled in workers since Pattern objects aren't serializable. Corpus-chunked (not rule-chunked) to minimize serialization overhead.
- **Optional RE2**: `google-re2` used when installed for 10-100x faster matching. Automatic per-pattern fallback to stdlib `re`.
- **Type-safe**: mypy strict mode enforced across the entire codebase.
