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

from crossfire.errors import GenerationError
from crossfire.models import CorpusEntry, Rule

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

    Uses rstr as the primary generator with a manual fallback for patterns
    that rstr cannot handle. All generated strings are validated against
    the source rule's compiled regex before inclusion.
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

    def _generate_positive(self, rule: Rule, validator: re.Pattern[str]) -> list[str]:
        """Generate matching strings for a rule using rstr with fallback."""
        # Attempt count: generate more than needed to account for validation failures
        attempt_count = self.samples_per_rule * 3
        strings: set[str] = set()
        deadline = time.monotonic() + self.generation_timeout_s

        # Strategy 1: rstr.xeger
        rstr_ok = True
        for _ in range(attempt_count):
            if time.monotonic() > deadline:
                break
            if len(strings) >= self.samples_per_rule:
                break
            try:
                s = rstr.xeger(rule.pattern)
                if len(s) <= self.max_string_length and validator.search(s):
                    strings.add(s)
            except Exception:
                rstr_ok = False
                break

        if not rstr_ok or len(strings) < self.min_valid_samples:
            if not rstr_ok:
                log.info(
                    "Rule '%s': rstr.xeger failed, using fallback generator",
                    rule.name,
                )
            # Strategy 2: fallback generator
            self._fallback_generate(rule, strings, deadline, validator)

        return list(strings)

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
