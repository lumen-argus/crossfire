# Changelog

All notable changes to Crossfire will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.1] - 2026-04-10

### Fixed

- **Parallel generator hang when called from a multi-threaded host process.**
  `CorpusGenerator._generate_parallel` previously used `multiprocessing.get_context("fork")` on Linux. Forking from a multi-threaded parent is unsafe — the child inherits parent memory but only the calling thread, leaving any locks held by other parent threads permanently locked in the child. Embedders that called `generate()` from a `threading.Thread` (background workers, web servers) hit this as silent `ProcessPoolExecutor` shutdown deadlocks where every individual rule completed but the pool never finished. The default `mp_context` is now `"spawn"`, which is safe in every host configuration. CPython 3.14 deprecates fork as the default for the same reason. ([crossfire-rules#1](https://github.com/lumen-argus/crossfire/issues/1))
- **Per-worker timeout in parallel generation.** A single hung worker can no longer block the pool's shutdown indefinitely. Each future is bounded by `per_worker_timeout_s` (default 60s); on timeout the worker is treated as a generation failure for that rule and the pool moves on. The whole batch is also bounded by `per_worker_timeout_s * len(rules)`.

### Added

- **`parallel` parameter on `CorpusGenerator.__init__()` and `generate()`** to override the auto-detected parallel/sequential mode. `None` (default) preserves existing behavior (parallel iff `len(rules) >= 8`). `False` forces sequential — recommended when calling from a multi-threaded host process even with the spawn fix, since `ProcessPoolExecutor` startup re-imports the module per worker and adds latency that isn't worth it for small/medium rule sets.
- **`mp_context` parameter** on `CorpusGenerator.__init__()`. Defaults to `"spawn"`. CLI users running crossfire single-process can set `"fork"` to skip the per-worker re-import cost.
- **`per_worker_timeout_s` parameter** on `CorpusGenerator.__init__()`. Default 60s.
- **Lifecycle log lines** in parallel mode: `"Spawning N worker(s) for M rules"`, `"Shutting down worker pool"`, `"Worker pool shutdown complete"`. Makes hangs immediately visible: if you don't see "shutdown complete" after "Shutting down", the pool is wedged.

### Changed

- **`mp_context` default is now `"spawn"`** (previously `"fork"` on Linux). Behavior change for CLI users on Linux: worker startup is slightly slower (one re-import per worker), but generation is now safe regardless of host process state. Pass `mp_context="fork"` to opt back into the old behavior for single-process invocations.

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
