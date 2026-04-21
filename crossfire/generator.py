"""Corpus generation from regex patterns."""

from __future__ import annotations

import logging
import multiprocessing
import os
import random
import re
import string
import time
import zlib
from concurrent.futures import Future, ProcessPoolExecutor, as_completed
from typing import Any

import rstr
from rstr.xeger import STAR_PLUS_LIMIT as _RSTR_STAR_PLUS_LIMIT
from rstr.xeger import Xeger as _RstrXeger

from crossfire.errors import GenerationError
from crossfire.models import CorpusEntry, Rule


def _patched_handle_repeat(self: Any, start_range: int, end_range: int, value: str) -> str:
    """Patched version of `rstr.xeger.Xeger._handle_repeat`.

    Upstream rstr (3.2.x) caps the repeat count unconditionally:

        end_range = min((end_range, STAR_PLUS_LIMIT))

    `STAR_PLUS_LIMIT = 100` is meant to bound *unbounded* quantifiers
    (`*`, `+`, huge `{N,M}` ranges) so synthetic strings don't blow up.
    The cap is applied to fixed-count repetitions too: for `{146}`,
    sre_parse passes `start=146, end=146`; rstr computes `min(146, 100)
    = 100` and then calls `random.randint(146, 100)`, which raises
    `ValueError: empty range in randint(146, 100)` because start > end.
    The real-world gitleaks rule `cloudflare_origin_ca_key` hits this.

    Fix: only cap `end_range` when the cap still leaves
    `end_range >= start_range`. Preserves the original intent for
    `*`/`+`/large ranges while allowing fixed-count repetitions above
    the cap to produce their exact count. Tracked upstream as a rstr
    bug; remove this patch once a fixed release is out and our floor
    bumps past it.
    """
    if end_range > _RSTR_STAR_PLUS_LIMIT:
        end_range = max(_RSTR_STAR_PLUS_LIMIT, start_range)
    times = self._random.randint(start_range, end_range)
    # Outer `_` because the inner generator's `i` shadows it; `i` there
    # iterates over the repeat operand's AST nodes, matching upstream rstr.
    result = ["".join(self._handle_state(i) for i in value) for _ in range(times)]
    return "".join(result)


# setattr (not direct assignment) avoids mypy's method-assign error
# without an ignore that warn_unused_ignores flips on newer Python versions.
setattr(_RstrXeger, "_handle_repeat", _patched_handle_repeat)  # noqa: B010

# We default to "spawn" rather than "fork" because forking from a multi-threaded
# parent process is unsafe: child processes inherit memory but only the calling
# thread, leaving any locks held by other parent threads permanently locked in
# the child. Embedders that call CorpusGenerator from inside a thread (e.g.
# background workers, web servers) hit this as silent ProcessPoolExecutor
# shutdown deadlocks. Spawn is slightly slower at startup (each worker re-imports
# the module) but is safe in every host configuration. CPython 3.14 deprecates
# fork as the default for the same reason.
_DEFAULT_MP_CONTEXT = "spawn"

# A worker that does not return a result within this many seconds is considered
# hung; we cancel it and surface a GenerationError so the parallel coordinator
# never blocks the host process forever.
_PER_WORKER_TIMEOUT_S = 60.0

# Auto-parallel kicks in at this rule count when `parallel` is left unset.
_AUTO_PARALLEL_THRESHOLD = 8

log = logging.getLogger("crossfire.generator")


def _generate_for_rule_worker(
    rule_name: str,
    rule_pattern: str,
    samples_per_rule: int,
    negative_samples: int,
    max_string_length: int,
    generation_timeout_s: float,
    min_valid_samples: int,
    rule_seed: int | None,
) -> list[tuple[str, str, bool]]:
    """Generate corpus entries for a single rule in a worker process.

    Args:
        rule_name: Name of the rule.
        rule_pattern: Regex pattern string (compiled in-worker).
        samples_per_rule: Target positive samples.
        negative_samples: Target negative samples.
        max_string_length: Maximum generated string length.
        generation_timeout_s: Timeout per rule.
        min_valid_samples: Minimum valid samples before raising.
        rule_seed: Deterministic per-rule seed, or None.

    Returns:
        List of (text, source_rule, is_negative) tuples.

    Raises:
        GenerationError: If generation fails to produce enough samples.
    """
    import re

    if rule_seed is not None:
        random.seed(rule_seed)

    # Defense-in-depth: the loader's `crossfire.regex.compile` already rejects
    # any pattern stdlib `re` cannot compile, so this branch should be
    # unreachable when the Rule came from `load_rules`. It still matters for
    # library callers who construct Rule objects directly and feed them to
    # CorpusGenerator, bypassing the loader — without this guard their rogue
    # pattern would crash the worker pool and defeat skip_invalid.
    try:
        compiled = re.compile(rule_pattern)
    except re.error as exc:
        raise GenerationError(
            f"Rule '{rule_name}': pattern is not compilable by the stdlib re "
            f"module ({exc}). The loader normally catches this; if you built "
            f"this Rule directly, run `crossfire.regex.compile` on the pattern "
            f"first so load-time validation still applies.",
            rule_name=rule_name,
        ) from exc

    gen = CorpusGenerator(
        samples_per_rule=samples_per_rule,
        negative_samples=negative_samples,
        max_string_length=max_string_length,
        generation_timeout_s=generation_timeout_s,
        min_valid_samples=min_valid_samples,
    )
    rule = Rule(name=rule_name, pattern=rule_pattern, compiled=compiled)
    entries = gen._generate_for_rule(rule)
    return [(e.text, e.source_rule, e.is_negative) for e in entries]


class CorpusGenerator:
    """Generates synthetic test strings from regex patterns.

    Pipeline (each stage runs only when the previous didn't reach
    `samples_per_rule`):

    1. `rstr.xeger` produces minimal matches from the pattern's AST — fast
       and precise when the pattern has inherent variability.
    2. Mutational augmentation pads every base match with random context
       and re-validates, AFL/libFuzzer style. This is what fills the corpus
       for literal-heavy but unanchored rules (e.g. `-----BEGIN OPENSSH
       PRIVATE KEY-----`) to the full `samples_per_rule`.
    3. Random-ASCII fallback as a last resort for patterns rstr can't parse
       at all; only productive on patterns broad enough that random strings
       happen to match.

    All samples are validated with stdlib `re` (the grammar rstr builds on),
    even when `rule.compiled` is an RE2 pattern. Patterns that are both
    fully-anchored (`^...$`, `\\A...\\Z`) AND have a small match language
    (e.g. `^literal$`) can't be augmented past their intrinsic minimum —
    padding breaks the anchors so re-validation rejects candidates — and
    will raise `GenerationError` unless the caller opts into `skip_invalid`.
    Fully-anchored patterns with large match spaces (e.g. `^[a-z]{5}$`)
    reach `samples_per_rule` from stage 1 alone.
    """

    def __init__(
        self,
        samples_per_rule: int = 50,
        negative_samples: int = 10,
        max_string_length: int = 256,
        generation_timeout_s: float = 2.0,
        seed: int | None = None,
        min_valid_samples: int = 10,
        parallel: bool | None = None,
        mp_context: str = _DEFAULT_MP_CONTEXT,
        per_worker_timeout_s: float = _PER_WORKER_TIMEOUT_S,
    ) -> None:
        """Configure a corpus generator.

        Args:
            samples_per_rule: Target positive samples per rule.
            negative_samples: Target near-miss negative samples per rule.
            max_string_length: Hard cap on generated string length.
            generation_timeout_s: Per-rule wall clock budget for sampling.
            seed: Master seed for reproducible runs (None = nondeterministic).
            min_valid_samples: Minimum positive samples required per rule.
            parallel: True = always use process pool. False = always sequential.
                None (default) = auto: parallel iff `len(rules) >= 8`.
                Pass False when calling from a multi-threaded host process to
                avoid the cost of worker startup; sequential is plenty fast for
                small/medium rule sets.
            mp_context: multiprocessing start method for the parallel pool.
                Defaults to "spawn", which is safe in every host configuration.
                Use "fork" only for single-threaded CLI invocations where you
                want to skip the per-worker re-import cost.
            per_worker_timeout_s: How long to wait for any single worker future
                to return before treating it as hung. Caps the worst-case
                shutdown wait if a worker deadlocks.
        """
        self.samples_per_rule = samples_per_rule
        self.negative_samples = negative_samples
        self.max_string_length = max_string_length
        self.generation_timeout_s = generation_timeout_s
        self.min_valid_samples = min_valid_samples
        self._seed = seed
        self._parallel = parallel
        self._mp_context = mp_context
        self._per_worker_timeout_s = per_worker_timeout_s

        if seed is not None:
            random.seed(seed)
            log.info("Random seed set to %d", seed)

    def generate(
        self,
        rules: list[Rule],
        *,
        skip_invalid: bool = False,
        parallel: bool | None = None,
    ) -> list[CorpusEntry]:
        """Generate corpus entries for all rules.

        Args:
            rules: List of rules to generate strings for.
            skip_invalid: If True, skip rules that fail generation instead of raising.
            parallel: Per-call override of the constructor `parallel` setting.
                None (default) defers to the constructor; True/False force the
                given mode for this call only.

        Returns:
            List of CorpusEntry objects.

        Raises:
            GenerationError: If a rule fails generation and skip_invalid is False.
        """
        t0 = time.monotonic()

        # Resolution order: explicit call argument > constructor setting > auto.
        effective_parallel = parallel if parallel is not None else self._parallel
        if effective_parallel is None:
            effective_parallel = len(rules) >= _AUTO_PARALLEL_THRESHOLD

        if effective_parallel:
            log.info(
                "Corpus generation: parallel mode (%d rules, mp_context=%s)",
                len(rules),
                self._mp_context,
            )
            all_entries, skipped = self._generate_parallel(rules, skip_invalid=skip_invalid)
        else:
            log.info("Corpus generation: sequential mode (%d rules)", len(rules))
            all_entries, skipped = self._generate_sequential(rules, skip_invalid=skip_invalid)

        duration = time.monotonic() - t0
        log.info(
            "Corpus generation complete: %d strings for %d rules in %.1fs%s",
            len(all_entries),
            len(rules),
            duration,
            f" ({skipped} skipped)" if skipped else "",
        )
        return all_entries

    def _generate_sequential(
        self,
        rules: list[Rule],
        *,
        skip_invalid: bool = False,
    ) -> tuple[list[CorpusEntry], int]:
        """Sequential generation for small rule sets."""
        all_entries: list[CorpusEntry] = []
        skipped = 0

        for rule in rules:
            try:
                entries = self._generate_for_rule(rule)
                all_entries.extend(entries)
            except GenerationError:
                if skip_invalid:
                    log.warning("Rule '%s': generation failed, skipping", rule.name)
                    skipped += 1
                else:
                    raise

        return all_entries, skipped

    def _generate_parallel(
        self,
        rules: list[Rule],
        *,
        skip_invalid: bool = False,
    ) -> tuple[list[CorpusEntry], int]:
        """Parallel generation using ProcessPoolExecutor.

        The pool uses the configured `mp_context` (default "spawn"). We bound
        every worker future with `_per_worker_timeout_s` so a single hung
        worker cannot block the pool's shutdown indefinitely.
        """
        from concurrent.futures import TimeoutError as FutureTimeoutError

        all_entries: list[CorpusEntry] = []
        skipped = 0
        n_workers = min(len(rules), os.cpu_count() or 4)

        try:
            ctx = multiprocessing.get_context(self._mp_context)
        except ValueError as exc:
            raise GenerationError(
                f"Invalid mp_context '{self._mp_context}': {exc}",
                rule_name="<config>",
            ) from exc

        log.info(
            "Spawning %d worker(s) for %d rules (mp_context=%s, per_worker_timeout=%.0fs)",
            n_workers,
            len(rules),
            self._mp_context,
            self._per_worker_timeout_s,
        )

        with ProcessPoolExecutor(max_workers=n_workers, mp_context=ctx) as executor:
            futures: dict[Future[Any], str] = {}
            for rule in rules:
                rule_seed = None
                if self._seed is not None:
                    rule_seed = (self._seed + zlib.crc32(rule.name.encode())) & 0x7FFFFFFF
                future = executor.submit(
                    _generate_for_rule_worker,
                    rule.name,
                    rule.pattern,
                    self.samples_per_rule,
                    self.negative_samples,
                    self.max_string_length,
                    self.generation_timeout_s,
                    self.min_valid_samples,
                    rule_seed,
                )
                futures[future] = rule.name

            try:
                for future in as_completed(
                    futures, timeout=self._per_worker_timeout_s * len(rules)
                ):
                    rule_name = futures[future]
                    try:
                        results = future.result(timeout=self._per_worker_timeout_s)
                        all_entries.extend(
                            CorpusEntry(text=text, source_rule=sr, is_negative=neg)
                            for text, sr, neg in results
                        )
                    except GenerationError:
                        if skip_invalid:
                            log.warning("Rule '%s': generation failed, skipping", rule_name)
                            skipped += 1
                        else:
                            raise
                    except FutureTimeoutError as exc:
                        msg = (
                            f"Rule '{rule_name}': worker did not return within "
                            f"{self._per_worker_timeout_s:.0f}s; treating as hung"
                        )
                        log.error(msg)
                        if skip_invalid:
                            skipped += 1
                        else:
                            raise GenerationError(msg, rule_name=rule_name) from exc
            except FutureTimeoutError as exc:
                # Total deadline exceeded — surface the unfinished rules.
                pending = [futures[f] for f in futures if not f.done()]
                msg = (
                    f"Parallel generation timed out: {len(pending)} rule(s) "
                    f"still pending after {self._per_worker_timeout_s * len(rules):.0f}s. "
                    f"Pending: {pending[:5]}{'...' if len(pending) > 5 else ''}"
                )
                log.error(msg)
                raise GenerationError(msg, rule_name="<batch>") from exc
            finally:
                log.info("Shutting down worker pool")

        log.info("Worker pool shutdown complete")
        return all_entries, skipped

    def _generate_for_rule(self, rule: Rule) -> list[CorpusEntry]:
        """Generate corpus entries for a single rule."""
        # Validate generated samples with stdlib `re`, not `rule.compiled`.
        # `rstr.xeger` is built on stdlib `sre_parse`, so samples it emits
        # are self-consistent against stdlib grammar. `rule.compiled` may
        # be an RE2 pattern (when google-re2 is installed), and RE2's
        # `\s`/`\S`/`\w` class definitions are narrower than stdlib's —
        # strings rstr considers valid matches get rejected by RE2, causing
        # broad patterns like `\s*...\S+` to fail generation entirely. The
        # loader guarantees every pattern is stdlib-compilable (see
        # `crossfire.regex.compile`), so this is safe unconditionally.
        validator = re.compile(rule.pattern)

        positive = self._generate_positive(rule, validator)

        if len(positive) < self.min_valid_samples:
            raise GenerationError(
                f"Rule '{rule.name}': only {len(positive)} valid samples "
                f"(minimum: {self.min_valid_samples}). Pattern may be too "
                f"restrictive for synthetic generation.",
                rule_name=rule.name,
            )

        negative = self._generate_negative(rule, positive, validator)

        log.debug(
            "Rule '%s': generated %d positive, %d negative strings",
            rule.name,
            len(positive),
            len(negative),
        )

        entries = [CorpusEntry(text=s, source_rule=rule.name, is_negative=False) for s in positive]
        entries.extend(
            CorpusEntry(text=s, source_rule=rule.name, is_negative=True) for s in negative
        )
        return entries

    # Corpus generation is a three-stage pipeline, each stage invoked only
    # when the previous one didn't reach `samples_per_rule`:
    #
    #   1. `rstr.xeger`  — derivation-based sampling from the pattern's AST.
    #                      Fast and precise for patterns with inherent
    #                      variability (charclasses, quantifiers, alternation).
    #                      For literal-heavy patterns it produces the same 1-5
    #                      strings repeatedly, since the match language itself
    #                      is small. Can also throw on features its parser
    #                      doesn't model (some escape/quantifier combinations).
    #
    #   2. Mutational augmentation — for every base match stage 1 produced,
    #                      wrap it in random context and re-validate. This
    #                      is the standard corpus-fuzzing move (AFL/libFuzzer
    #                      style): real-world strings matching a pattern
    #                      contain the match embedded in surrounding text, so
    #                      padding + re-validation generates realistic corpora
    #                      for literal-heavy but unanchored rules. When stage
    #                      1 already produced a diverse set (the pattern has
    #                      plenty of inherent variability), this stage is a
    #                      no-op. When the pattern is both fully-anchored and
    #                      narrow, padding breaks the anchor and candidates
    #                      fail re-validation — the set stays minimal and the
    #                      caller gets a GenerationError.
    #
    #   3. Random fallback — for patterns rstr couldn't parse at all and
    #                      that aren't anchored. Blind random ASCII; only
    #                      productive when the pattern is broad enough that
    #                      random strings happen to match.
    _RSTR_ATTEMPT_MULTIPLIER = 3
    _PAD_ATTEMPT_MULTIPLIER = 20
    _PAD_MAX_SIDE_LENGTH = 24
    _PAD_CHARSET = string.ascii_letters + string.digits + string.punctuation + " "

    def _generate_positive(self, rule: Rule, validator: re.Pattern[str]) -> list[str]:
        """Generate matching strings for a rule via rstr → padding → fallback."""
        strings: set[str] = set()
        deadline = time.monotonic() + self.generation_timeout_s

        rstr_attempts, rstr_matches = self._sample_via_rstr(rule, validator, strings, deadline)

        if len(strings) < self.samples_per_rule and strings:
            # Stage 2: mutational augmentation. Productive whenever rstr
            # produced any base matches — padding an anchored pattern just
            # won't produce new samples, the loop exits at its attempt cap.
            self._augment_with_padding(strings, validator, deadline)

        if len(strings) < self.min_valid_samples and rstr_attempts == 0:
            # Stage 3: rstr couldn't parse the pattern at all and stage 2
            # had nothing to augment. Random ASCII is a coarse last resort.
            log.info(
                "Rule '%s': rstr.xeger failed on all attempts, using random fallback",
                rule.name,
            )
            self._fallback_generate(rule, strings, deadline, validator)

        if rstr_attempts:
            match_rate = rstr_matches / rstr_attempts
            log.debug(
                "Rule '%s': rstr match rate %.0f%% (%d/%d), final corpus %d",
                rule.name,
                match_rate * 100,
                rstr_matches,
                rstr_attempts,
                len(strings),
            )

        return list(strings)

    def _sample_via_rstr(
        self,
        rule: Rule,
        validator: re.Pattern[str],
        strings: set[str],
        deadline: float,
    ) -> tuple[int, int]:
        """Stage 1: derivation-based sampling. Returns (non-raising attempts, matches)."""
        attempt_count = self.samples_per_rule * self._RSTR_ATTEMPT_MULTIPLIER
        attempts = 0
        matches = 0
        for _ in range(attempt_count):
            if time.monotonic() > deadline:
                break
            if len(strings) >= self.samples_per_rule:
                break
            try:
                s = rstr.xeger(rule.pattern)
            except Exception:
                # Some patterns make rstr throw intermittently (complex
                # character classes, unusual escapes). Keep trying — a
                # pattern may fail 40% of calls and succeed on 60%, still
                # giving plenty of useful output.
                continue
            attempts += 1
            if len(s) <= self.max_string_length and validator.search(s):
                matches += 1
                strings.add(s)
        return attempts, matches

    def _augment_with_padding(
        self,
        strings: set[str],
        validator: re.Pattern[str],
        deadline: float,
    ) -> None:
        """Stage 2: mutational augmentation — pad each base match with random
        context and keep the re-validated variants."""
        bases = list(strings)
        attempt_budget = self.samples_per_rule * self._PAD_ATTEMPT_MULTIPLIER
        for _ in range(attempt_budget):
            if time.monotonic() > deadline:
                break
            if len(strings) >= self.samples_per_rule:
                break
            base = random.choice(bases)
            prefix_len = random.randint(0, self._PAD_MAX_SIDE_LENGTH)
            suffix_len = random.randint(0, self._PAD_MAX_SIDE_LENGTH)
            prefix = "".join(random.choices(self._PAD_CHARSET, k=prefix_len))
            suffix = "".join(random.choices(self._PAD_CHARSET, k=suffix_len))
            candidate = prefix + base + suffix
            if len(candidate) <= self.max_string_length and validator.search(candidate):
                strings.add(candidate)

    def _fallback_generate(
        self,
        rule: Rule,
        strings: set[str],
        deadline: float,
        validator: re.Pattern[str],
    ) -> None:
        """Fallback string generation using random strings with guided mutations."""
        charset = string.ascii_letters + string.digits + string.punctuation + " "

        # Try random strings of varying lengths
        for length in (8, 16, 32, 64, 128):
            if time.monotonic() > deadline:
                break
            if len(strings) >= self.samples_per_rule:
                break
            for _ in range(self.samples_per_rule * 2):
                if time.monotonic() > deadline:
                    break
                if len(strings) >= self.samples_per_rule:
                    break
                s = "".join(random.choices(charset, k=length))
                if len(s) <= self.max_string_length and validator.search(s):
                    strings.add(s)

    def _generate_negative(
        self, rule: Rule, positive: list[str], validator: re.Pattern[str]
    ) -> list[str]:
        """Generate near-miss non-matching strings by mutating positive samples."""
        if not positive or self.negative_samples <= 0:
            return []

        negatives: set[str] = set()
        mutations = [
            self._truncate,
            self._swap_chars,
            self._remove_prefix,
            self._insert_noise,
        ]

        attempts = 0
        max_attempts = self.negative_samples * 10

        while len(negatives) < self.negative_samples and attempts < max_attempts:
            attempts += 1
            base = random.choice(positive)
            mutator = random.choice(mutations)
            candidate = mutator(base)

            # Negative sample must NOT match the source rule
            if candidate and not validator.search(candidate):
                negatives.add(candidate)

        return list(negatives)

    @staticmethod
    def _truncate(s: str) -> str:
        """Truncate string at a random position."""
        if len(s) <= 1:
            return ""
        pos = random.randint(1, len(s) - 1)
        return s[:pos]

    @staticmethod
    def _swap_chars(s: str) -> str:
        """Swap random characters in the string."""
        if len(s) <= 1:
            return s
        chars = list(s)
        count = max(1, len(s) // 4)
        for _ in range(count):
            pos = random.randint(0, len(chars) - 1)
            chars[pos] = random.choice(string.ascii_letters + string.digits)
        return "".join(chars)

    @staticmethod
    def _remove_prefix(s: str) -> str:
        """Remove a prefix from the string."""
        if len(s) <= 2:
            return ""
        cut = random.randint(1, len(s) // 2)
        return s[cut:]

    @staticmethod
    def _insert_noise(s: str) -> str:
        """Insert random characters at a random position."""
        if not s:
            return s
        pos = random.randint(0, len(s))
        noise = "".join(random.choices(string.ascii_letters, k=random.randint(1, 3)))
        return s[:pos] + noise + s[pos:]
