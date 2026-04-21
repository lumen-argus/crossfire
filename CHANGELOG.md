# Changelog

All notable changes to Crossfire will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.3] - 2026-04-21

### Changed

- **Minimum Python bumped to 3.12** (was 3.11). CI now tests 3.12 and 3.13.

### Fixed

- **`--skip-invalid` now catches stdlib-incompatible patterns at load time, in one place.** The loader compiles via `crossfire.regex` (RE2 when available), which historically accepted patterns that Python's `re` rejects — notably non-leading global flags like `(?i)` mid-pattern in some gitleaks TOMLs. Because `ProcessPoolExecutor` workers recompile patterns with stdlib `re` by design (importing the `crossfire` package in workers adds ~20ms each under spawn), such a rule would load fine, then abort the whole worker pool later with `re.PatternError` — regardless of `--skip-invalid`. `crossfire.regex.compile` now validates every pattern against stdlib `re` before returning the RE2-compiled form, so asymmetric patterns are rejected at load time with the loader's standard `ValidationError` (fail-fast, or WARNING + skip under `--skip-invalid`). Downstream stages (generator, evaluator) can assume stdlib-compatibility for every rule they receive. The per-worker `re.error` handler in `_generate_for_rule_worker` remains as defense-in-depth for library callers who construct `Rule` objects without going through the loader.

### Known issue

- When `google-re2` is installed, a handful of CLI/plugin tests (`test_scan_overlapping`, `test_scan_table_format`, `test_fail_on_duplicate`, `test_output_to_file`, `test_scan_gitleaks_rules`) can fail with "only N valid samples" on broad `\s*`/`\S+` patterns. This is a separate bug: the generator uses `rstr` (stdlib-sre grammar) to synthesize strings but validates them against the loader's RE2-compiled pattern, and RE2's `\s`/`\S` semantics diverge enough from stdlib that most generated strings are rejected. The fix is generator-local (validate with a stdlib-compiled copy during generation, or swap the sampler) and unrelated to the load-time asymmetry above.

## [0.2.2] - 2026-04-21

### Fixed

- **Subset findings against catch-all rules no longer recommend dropping the specific rule.** When a superset rule is a catch-all (umbrella pattern like `generic_secret`), dropping the specific subset (e.g. `terraform_cloud_token`) loses the downstream label and degrades alert quality in DLP/SIEM pipelines. Classifier now auto-detects catch-alls — a rule overlapping with more than `catch_all_threshold` (default 5) other rules, or one explicitly tagged via `metadata["catch_all"] = True` — and flips the recommendation to `keep_both`. Rules can opt out of auto-detection with `metadata["catch_all"] = False`. ([crossfire-rules#9](https://github.com/lumen-argus/crossfire/issues/9))

### Added

- **`OverlapResult.downstream_label_loss: bool`** — true when acting on the recommendation would drop the more specific rule (i.e. `SUBSET`+`keep_a` or `SUPERSET`+`keep_b`). Surfaced in JSON and CSV output so CI gates can filter findings by actual label-loss risk rather than treating all subset pairs equally.
- **`Classifier(catch_all_threshold=...)`** constructor parameter (default 5).

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
