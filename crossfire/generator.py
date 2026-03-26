"""Corpus generation from regex patterns."""

from __future__ import annotations

import logging
import random
import re
import signal
import string
import time
from typing import Optional

import rstr

from crossfire.errors import GenerationError
from crossfire.models import CorpusEntry, Rule

log = logging.getLogger("crossfire.generator")


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
        seed: Optional[int] = None,
        min_valid_samples: int = 10,
    ) -> None:
        self.samples_per_rule = samples_per_rule
        self.negative_samples = negative_samples
        self.max_string_length = max_string_length
        self.generation_timeout_s = generation_timeout_s
        self.min_valid_samples = min_valid_samples

        if seed is not None:
            random.seed(seed)
            log.info("Random seed set to %d", seed)

    def generate(
        self,
        rules: list[Rule],
        *,
        skip_invalid: bool = False,
    ) -> list[CorpusEntry]:
        """Generate corpus entries for all rules.

        Args:
            rules: List of rules to generate strings for.
            skip_invalid: If True, skip rules that fail generation instead of raising.

        Returns:
            List of CorpusEntry objects.

        Raises:
            GenerationError: If a rule fails generation and skip_invalid is False.
        """
        t0 = time.monotonic()
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

        duration = time.monotonic() - t0
        log.info(
            "Corpus generation complete: %d strings for %d rules in %.1fs%s",
            len(all_entries),
            len(rules),
            duration,
            f" ({skipped} skipped)" if skipped else "",
        )
        return all_entries

    def _generate_for_rule(self, rule: Rule) -> list[CorpusEntry]:
        """Generate corpus entries for a single rule."""
        positive = self._generate_positive(rule)

        if len(positive) < self.min_valid_samples:
            raise GenerationError(
                f"Rule '{rule.name}': only {len(positive)} valid samples "
                f"(minimum: {self.min_valid_samples}). Pattern may be too "
                f"restrictive for synthetic generation.",
                rule_name=rule.name,
            )

        negative = self._generate_negative(rule, positive)

        log.debug(
            "Rule '%s': generated %d positive, %d negative strings",
            rule.name,
            len(positive),
            len(negative),
        )

        entries = [
            CorpusEntry(text=s, source_rule=rule.name, is_negative=False)
            for s in positive
        ]
        entries.extend(
            CorpusEntry(text=s, source_rule=rule.name, is_negative=True)
            for s in negative
        )
        return entries

    def _generate_positive(self, rule: Rule) -> list[str]:
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
                if len(s) <= self.max_string_length and rule.compiled.search(s):
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
            self._fallback_generate(rule, strings, deadline)

        return list(strings)

    def _fallback_generate(
        self,
        rule: Rule,
        strings: set[str],
        deadline: float,
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
                if len(s) <= self.max_string_length and rule.compiled.search(s):
                    strings.add(s)

    def _generate_negative(self, rule: Rule, positive: list[str]) -> list[str]:
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
            if candidate and not rule.compiled.search(candidate):
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
