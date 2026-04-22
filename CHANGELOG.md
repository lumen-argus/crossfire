# Changelog

All notable changes to Crossfire will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.9] - 2026-04-22

### Added

- **Sample diversity warning.** The generator already raises on *count* failures (fewer than `min_valid_samples` survived) but was silent when rstr produced many copies of a single degenerate shape — the exact failure mode behind the 0.2.7 `kubernetes_secret_yaml` report (27 samples / ~10 unique middles, all sharing one core). `CorpusGenerator.generate` now runs a parent-side pass after corpus collection: for each rule, it computes the number of unique middle-50-char slices across the positive samples and logs a WARNING when the ratio falls below `0.4` (minimum 10 samples, otherwise the ratio is noise). Middle slices specifically — stage-2 padding fans random bytes onto both ends of every base match, so prefix/suffix-based uniqueness looks high even when every sample derives from a single degenerate base. Runs parent-side so warnings fire under both sequential and parallel backends (spawn workers don't forward logs). Callers who only want the metric (not the warning) can filter the `crossfire.generator` logger at their end. On the lumen-argus 90-rule community corpus, 0.2.9 fires zero diversity warnings — 0.2.8's non-greedy fix already landed the real behavior fix; this pass is the caller-visible surface so future silent regressions get caught immediately. Threshold chosen empirically: catches the pre-0.2.8 `kubernetes_secret_yaml` regression (0.37) while leaving inherently narrow patterns like `inst_tag` (16/30 = 0.53) above the line. Regression coverage: `tests/test_generator.py::TestDiversityMetric`.

### Changed

- **CI lint now runs under every supported Python version.** The lint job was pinned to 3.12; mypy's output depends on the running interpreter's stubs and stdlib, so a "fine on 3.12" result was no guarantee on 3.13 or 3.14 — stale `# type: ignore` pragmas would silently pass CI and surface only when a contributor upgraded Python locally (which is what happened on 0.2.8 with the rstr `_handle_state` method-assign check). The `lint` job now runs the same Ruff + mypy strict pass under matrix `["3.12", "3.13", "3.14"]`. Test matrix also extended to 3.14. Pyproject classifiers updated to declare 3.14 support — local has been clean on 3.14 for several releases, just hadn't been formally declared.

## [0.2.8] - 2026-04-21

### Fixed

- **Non-greedy quantifiers no longer get sampled like greedy ones.** `sre_parse` tags `{m,n}?`, `*?`, and `+?` as `min_repeat` and the greedy forms as `max_repeat`; upstream rstr (3.2.x) dispatches both through the same handler and draws the repeat count uniformly from `[m, n]` — throwing away the non-greedy semantics. For patterns with wide non-greedy holes like `(?s:.){0,200}?`, rstr generated ~100 random chars in the gap (with `.` sampled from `string.printable`, including `\v`/`\x0c`/`\n`). The result (a) bore no resemblance to what the regex would actually match against real text — the re engine fills non-greedy regions with the minimum the surrounding anchors allow — and (b) blew past `max_string_length=256`, so ~99% of rstr calls got filtered out, the few survivors all shared one degenerate shape, and stage-2 mutational padding then fanned that single base into a whole corpus of near-duplicates. `crossfire.generator` now patches `rstr.xeger.Xeger._handle_state` at module import: when the opcode is `min_repeat`, we emit exactly `start_range` repetitions — the semantically correct minimum, matching how the re engine behaves. `max_repeat` still goes through `_handle_repeat` (with the `{N>100}` cap fix from 0.2.7). Measured effect on the real-world `kubernetes_secret_yaml` gitleaks rule (the 0.2.7 degenerate-sample report): from 27 samples / ~10 shared middles to 30 samples / 29 unique middles at `samples_per_rule=30`, `max_string_length=256`. This resolves the last 0.2.7 known limitation — all 6 rules in the lumen-argus community.json regression set now produce real, diverse coverage. Regression coverage: `tests/test_generator.py::TestNonGreedyRepeat`.

## [0.2.7] - 2026-04-21

### Fixed

- **`rstr.xeger` `{N}` bug for N > 100 patched in-process.** Upstream rstr 3.2.x has `STAR_PLUS_LIMIT = 100` intended to bound unbounded quantifiers (`*`, `+`), but the cap applies unconditionally to fixed-count repetitions too: for `{146}`, sre_parse passes `start=146, end=146`; rstr computes `min(146, 100) = 100` and then calls `random.randint(146, 100)` — which raises `ValueError: empty range in randint(146, 100)` because start > end. The real-world gitleaks rule `cloudflare_origin_ca_key` (pattern `\b(v1\.0-[a-f0-9]{24}-[a-f0-9]{146})…`) hits this. `crossfire.generator` now monkeypatches `rstr.xeger.Xeger._handle_repeat` at module import: the cap only applies when it still leaves `end_range >= start_range`, preserving the original intent for `*`/`+`/large ranges while letting fixed-count repetitions above 100 produce their exact count. With this patch, `cloudflare_origin_ca_key` produces 30/30 matching samples — strings of the correct `v1.0-<24 hex>-<146 hex>` shape. Regression coverage: `tests/test_generator.py::TestRstrRepeatPatch`. The patch stays until a fixed rstr release is out and our floor bumps past it.

### Known limitation

- **`kubernetes_secret_yaml` samples have low diversity.** The rule now loads, validates, and generates 30 samples under default settings, but the middle portion of each sample (the `data:…kind: secret` span generated by `(?s:.){0,100}?` wildcards) is mostly identical control-char garbage across samples. rstr fills `.` with `string.printable` (including `\v`, `\x0c`, etc.); combined with the lazy wildcard, the per-sample diversity is low and carries little signal for downstream overlap/quality analysis. Fixing this needs either a rule-aware sampler or a structured-input generator (e.g. YAML), both out of scope for this release. Pointed out by the lumen-argus team; tracked as a future enhancement.

## [0.2.6] - 2026-04-21

### Added

- **Mutational corpus augmentation** (pipeline stage 2). After `rstr.xeger` produces the minimal matches for a pattern, each base match is padded with random prefix/suffix context and re-validated. This is the standard mutational-fuzzing move (AFL/libFuzzer style) and mirrors how real corpora look — the matched substring embedded in surrounding text — so literal-heavy but unanchored rules now produce the full `samples_per_rule` instead of 1-5. Rules like `-----BEGIN OPENSSH PRIVATE KEY-----`, `-----BEGIN (?:RSA|EC|DSA|OPENSSH)?PRIVATE KEY-----`, and `(?i)\[INST\]` go from 1-5 samples to 30 samples at default settings. Fully-anchored narrow patterns (`^literal$`) remain at their intrinsic minimum — padding breaks the anchor so re-validation rejects the candidates, as expected.

### Fixed

- **`rstr.xeger` exceptions no longer abort sampling.** The rstr loop used to `break` on the first exception; some gitleaks-style patterns raise intermittently (~40-50% of calls) but would otherwise produce plenty of valid output. The loop now continues through exceptions, so patterns like `atlassian_api_token` that previously generated zero samples (first call threw, loop exited) now generate the full `samples_per_rule`.
- **Narrow-match-language rules no longer false-fail `min_valid_samples`.** Combined with mutational augmentation above, rules whose regex has an inherently small match set now reach the sample target through padding instead of tripping the hard failure path. Downstream impact for `lumen-argus/community.json` (90-rule set): 5 of the 6 previously-regressing rules now generate 30/30 samples (`ssh_private_key`, `private_key_pem`, `inst_tag`, `atlassian_api_token`, `kubernetes_secret_yaml`). Only `cloudflare_origin_ca_key` remains skipped under `skip_invalid=True` — its `{146}` fixed-repetition clause trips rstr's internal sampler (`randint(146, 100)` → `ValueError`), and with zero base matches the padding stage has nothing to augment. A sampler that handles large fixed-count repetitions would recover it; out of scope for this release. (Correction: the originally-published 0.2.6 CHANGELOG claimed `kubernetes_secret_yaml` also remained skipped — that was wrong, based on an intermediate diagnostic test run before stage 2 padding was wired in. On 0.2.6 as shipped, padding expands the single rstr base match into the full sample target for that rule.)

## [0.2.5] - 2026-04-21

### Fixed

- **Generator no longer fails on broad `\s`/`\S`/`\w`-class patterns when `google-re2` is installed.** `rstr.xeger` builds on stdlib `sre_parse`, but the generator validated synthesized samples against `rule.compiled` — which is an RE2 pattern when `google-re2` is available. RE2's character classes are narrower than stdlib's (RE2 `\s` = `[\t\n\f\r ]`, while stdlib also matches `\v` and Unicode whitespace), so self-consistent rstr output got rejected and broad patterns like `(?:secret|password|token|key)\s*[=:]\s*\S+` produced "only 1 valid samples (minimum: 10)". Generator now compiles a stdlib-`re` validator per rule at generation time — safe unconditionally because `crossfire.regex.compile` already guarantees every loaded pattern is stdlib-compilable. Resolves the "Known issue" disclosed in 0.2.3 (5 CLI/plugin tests that regressed with `google-re2` installed) and the `community.json` corpus-generation regression reported downstream (6 rules including `ssh_private_key`, `private_key_pem`, `atlassian_api_token`). Regression test added in `tests/test_generator.py::TestCharClassSemanticDrift`.

## [0.2.4] - 2026-04-21

### Fixed

- **`crossfire.__version__` and `crossfire --version` now report the real installed version.** In 0.2.3 the distribution metadata was `0.2.3` but `crossfire/__init__.py` still hardcoded `__version__ = "0.2.2"`, so `crossfire --version` and the `AnalysisReport.crossfire_version` field reported the stale string. Source: `crossfire/__init__.py` now resolves `__version__` via `importlib.metadata.version("crossfire-rules")`, making `pyproject.toml` the single source of truth and eliminating this class of drift. Added a regression test (`tests/test_version.py`) asserting `__version__` equals the distribution metadata at runtime. Cosmetic in 0.2.3 — no functional behavior changed.

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
