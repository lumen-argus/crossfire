"""Tests for corpus generation."""

from __future__ import annotations

import multiprocessing
import re
import threading

import pytest

from crossfire.errors import GenerationError
from crossfire.generator import CorpusGenerator
from crossfire.models import Rule


def _make_rule(name: str, pattern: str) -> Rule:
    return Rule(name=name, pattern=pattern, compiled=re.compile(pattern))


class TestPositiveGeneration:
    def test_generates_matching_strings(self):
        gen = CorpusGenerator(samples_per_rule=20, negative_samples=0, seed=42)
        rule = _make_rule("digits", r"\d{8}")
        entries = gen.generate([rule])
        positive = [e for e in entries if not e.is_negative]
        assert len(positive) >= 10
        for e in positive:
            assert rule.compiled.search(e.text), f"'{e.text}' should match {rule.pattern}"

    def test_generates_requested_count(self):
        gen = CorpusGenerator(samples_per_rule=30, negative_samples=0, seed=42)
        rule = _make_rule("hex", r"[0-9a-f]{16}")
        entries = gen.generate([rule])
        positive = [e for e in entries if not e.is_negative]
        assert len(positive) == 30

    def test_all_entries_linked_to_source(self):
        gen = CorpusGenerator(samples_per_rule=10, negative_samples=5, seed=42)
        rule = _make_rule("test", r"[a-z]{10}")
        entries = gen.generate([rule])
        for e in entries:
            assert e.source_rule == "test"

    def test_respects_max_length(self):
        gen = CorpusGenerator(
            samples_per_rule=20,
            negative_samples=0,
            max_string_length=32,
            seed=42,
        )
        rule = _make_rule("long", r"[a-zA-Z0-9]{10,100}")
        entries = gen.generate([rule])
        for e in entries:
            assert len(e.text) <= 32

    def test_deduplicates_within_rule(self):
        gen = CorpusGenerator(samples_per_rule=50, negative_samples=0, seed=42)
        rule = _make_rule("hex", r"[0-9a-f]{16}")
        entries = gen.generate([rule])
        texts = [e.text for e in entries if not e.is_negative]
        # All entries should be unique (set removes duplicates)
        assert len(set(texts)) == len(texts)


class TestNegativeGeneration:
    def test_generates_negatives(self):
        gen = CorpusGenerator(samples_per_rule=20, negative_samples=10, seed=42)
        rule = _make_rule("digits", r"^\d{8}$")
        entries = gen.generate([rule])
        negatives = [e for e in entries if e.is_negative]
        assert len(negatives) > 0
        for e in negatives:
            assert not rule.compiled.search(e.text), (
                f"Negative '{e.text}' should NOT match {rule.pattern}"
            )

    def test_no_negatives_when_zero(self):
        gen = CorpusGenerator(samples_per_rule=20, negative_samples=0, seed=42)
        rule = _make_rule("test", r"\d{4}")
        entries = gen.generate([rule])
        negatives = [e for e in entries if e.is_negative]
        assert len(negatives) == 0


class TestMultipleRules:
    def test_generates_for_all_rules(self):
        gen = CorpusGenerator(samples_per_rule=10, negative_samples=0, seed=42)
        rules = [
            _make_rule("rule_a", r"[a-z]{10}"),
            _make_rule("rule_b", r"\d{10}"),
            _make_rule("rule_c", r"[A-Z]{5}-\d{5}"),
        ]
        entries = gen.generate(rules)
        sources = {e.source_rule for e in entries}
        assert sources == {"rule_a", "rule_b", "rule_c"}

    def test_entries_per_rule(self):
        gen = CorpusGenerator(samples_per_rule=15, negative_samples=5, seed=42)
        rules = [
            _make_rule("a", r"[a-z]{10}"),
            _make_rule("b", r"\d{10}"),
        ]
        entries = gen.generate(rules)
        for rule_name in ("a", "b"):
            positive = [e for e in entries if e.source_rule == rule_name and not e.is_negative]
            assert len(positive) >= 10


# A pattern where rstr.xeger reliably raises (ValueError: empty range in
# randint) — the quantifier on the second `[a-f0-9]` range creates a length
# rstr's sampler can't satisfy. Used by tests that need "genuinely
# unsynthesizable" behavior. Same shape as the real `cloudflare_origin_ca_key`
# gitleaks rule that motivated this test strategy.
_UNSYNTHESIZABLE_PATTERN = r"\b(v1\.0-[a-f0-9]{24}-[a-f0-9]{146})(?:[\x60'\"\s;]|\\[nr]|$)"


class TestFailFast:
    def test_generation_failure_raises(self):
        """When rstr can't synthesize and the fallback can't match either,
        generation fails with GenerationError."""
        gen = CorpusGenerator(
            samples_per_rule=20,
            min_valid_samples=10,
            negative_samples=0,
            generation_timeout_s=0.5,
            seed=42,
        )
        rule = _make_rule("unsynth", _UNSYNTHESIZABLE_PATTERN)
        with pytest.raises(GenerationError, match=r"only .* valid samples"):
            gen.generate([rule])

    def test_generation_failure_skip(self):
        """skip_invalid=True turns the generation failure into a silent drop."""
        gen = CorpusGenerator(
            samples_per_rule=20,
            min_valid_samples=10,
            negative_samples=0,
            generation_timeout_s=0.5,
            seed=42,
        )
        rule = _make_rule("unsynth", _UNSYNTHESIZABLE_PATTERN)
        entries = gen.generate([rule], skip_invalid=True)
        assert len(entries) == 0


class TestMutationalAugmentation:
    """Stage 2 of the corpus pipeline: pad minimal rstr matches with random
    context and re-validate. Real corpora contain the pattern embedded in
    surrounding text (mutational fuzzing style), so a literal-heavy but
    unanchored rule should still produce the full `samples_per_rule`.

    Motivated by lumen-argus community.json rules (`ssh_private_key`,
    `private_key_pem`, `inst_tag`) producing only 1-5 samples on 0.2.5
    because rstr deduplicated to the minimal match language.
    """

    def test_unanchored_literal_gets_full_sample_count_via_padding(self):
        """A literal pattern with no anchors should produce samples_per_rule
        variants by padding the base match with random context."""
        gen = CorpusGenerator(
            samples_per_rule=30,
            min_valid_samples=10,
            negative_samples=0,
            seed=42,
        )
        base = "-----BEGIN OPENSSH PRIVATE KEY-----"
        rule = _make_rule("literal", base)
        entries = gen.generate([rule])
        positives = [e for e in entries if not e.is_negative]
        assert len(positives) == 30, f"expected 30 padded variants, got {len(positives)}"
        # Every sample contains the literal and still validates.
        for e in positives:
            assert base in e.text
            assert rule.compiled.search(e.text)
        # And meaningful diversity — at least half should be unique padded forms.
        assert len({e.text for e in positives}) >= 15

    def test_short_alternation_expands_via_padding(self):
        """A 5-alternative pattern produces 5 base matches; padding expands
        each into many context-varied samples."""
        gen = CorpusGenerator(
            samples_per_rule=30,
            min_valid_samples=10,
            negative_samples=0,
            seed=42,
        )
        pattern = r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----"
        rule = _make_rule("alt", pattern)
        entries = gen.generate([rule])
        positives = [e for e in entries if not e.is_negative]
        assert len(positives) == 30
        for e in positives:
            assert re.search(pattern, e.text)

    def test_case_insensitive_literal_expands_via_padding(self):
        """`(?i)\\[INST\\]` — padding introduces variety even though the
        pattern's core match language is just case permutations of [INST]."""
        gen = CorpusGenerator(
            samples_per_rule=30,
            min_valid_samples=10,
            negative_samples=0,
            seed=42,
        )
        rule = _make_rule("inst", r"(?i)\[INST\]")
        entries = gen.generate([rule])
        positives = [e for e in entries if not e.is_negative]
        assert len(positives) == 30
        for e in positives:
            assert re.search(r"(?i)\[INST\]", e.text)

    def test_fully_anchored_pattern_stays_at_minimal_set(self):
        """`^literal$` cannot be padded — padding would push the match past
        the anchors and re-validation would fail. The generator legitimately
        yields only the single possible match; with `min_valid_samples=10`
        above that, generation fails hard, and that's correct behavior."""
        gen = CorpusGenerator(
            samples_per_rule=30,
            min_valid_samples=10,
            negative_samples=0,
            seed=42,
        )
        rule = _make_rule("anchored", r"^exact-anchored-literal$")
        with pytest.raises(GenerationError, match=r"only 1 valid samples"):
            gen.generate([rule])

    def test_fully_anchored_narrow_skipped_with_skip_invalid(self):
        """Same rule, but skip_invalid=True turns the GenerationError into a
        silent drop — the downstream analysis keeps going on the remaining
        rules."""
        gen = CorpusGenerator(
            samples_per_rule=30,
            min_valid_samples=10,
            negative_samples=0,
            seed=42,
        )
        rule = _make_rule("anchored", r"^exact-anchored-literal$")
        entries = gen.generate([rule], skip_invalid=True)
        assert entries == []

    def test_padded_samples_feed_downstream_overlap_detection(self):
        """A narrow rule's padded samples should still enable overlap
        detection — the padded strings are valid matches of the rule, so
        any broader rule that also matches them will be picked up."""
        gen = CorpusGenerator(
            samples_per_rule=20,
            min_valid_samples=10,
            negative_samples=0,
            seed=42,
        )
        narrow = _make_rule("narrow", r"unique-marker-xyz-123")
        broad = _make_rule("broad_contains_marker", r"unique-marker-\w+")
        entries = gen.generate([narrow, broad])
        narrow_samples = [e.text for e in entries if e.source_rule == "narrow"]
        assert len(narrow_samples) == 20
        # Every narrow sample must also be matched by the broader rule —
        # that's how overlap analysis would detect the relationship.
        for text in narrow_samples:
            assert broad.compiled.search(text)


class TestIntermittentRstrFailures:
    """Some patterns make rstr throw on a fraction of calls — the generator
    must not `break` on the first exception, or we lose the useful output
    from the calls that would have succeeded.

    Motivated by the `atlassian_api_token` rule (42/90 rstr exceptions,
    but 48/90 successful matches when we kept trying).
    """

    def test_exception_on_some_attempts_does_not_stop_generation(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Simulate rstr raising every other call; generator must keep going."""
        import rstr as rstr_mod

        call_count = {"n": 0}
        real_xeger = rstr_mod.xeger

        def flaky_xeger(pattern: str) -> str:
            call_count["n"] += 1
            if call_count["n"] % 2 == 0:
                raise ValueError("simulated intermittent rstr failure")
            return real_xeger(pattern)

        monkeypatch.setattr(rstr_mod, "xeger", flaky_xeger)

        gen = CorpusGenerator(
            samples_per_rule=20,
            min_valid_samples=10,
            negative_samples=0,
            seed=42,
        )
        rule = _make_rule("flaky", r"[a-z]{10}")
        entries = gen.generate([rule])
        positives = [e for e in entries if not e.is_negative]
        # With half of attempts raising, we should still get plenty of samples.
        assert len(positives) >= 10

    def test_all_exceptions_falls_back_to_random_generation(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When rstr raises every time, the fallback generator must kick in
        and (for patterns that random ASCII can match) produce samples."""
        import rstr as rstr_mod

        def always_raise(pattern: str) -> str:
            raise ValueError("simulated total rstr failure")

        monkeypatch.setattr(rstr_mod, "xeger", always_raise)

        gen = CorpusGenerator(
            samples_per_rule=20,
            min_valid_samples=5,
            negative_samples=0,
            seed=42,
        )
        # Random ASCII can match `[a-z]+` easily.
        rule = _make_rule("random_matchable", r"[a-z]+")
        entries = gen.generate([rule])
        positives = [e for e in entries if not e.is_negative]
        assert len(positives) >= 5


class TestReproducibility:
    def test_same_seed_same_output(self):
        rule = _make_rule("test", r"[a-z]{10}")

        gen1 = CorpusGenerator(samples_per_rule=20, negative_samples=5, seed=42)
        entries1 = gen1.generate([rule])

        gen2 = CorpusGenerator(samples_per_rule=20, negative_samples=5, seed=42)
        entries2 = gen2.generate([rule])

        texts1 = [e.text for e in entries1]
        texts2 = [e.text for e in entries2]
        assert texts1 == texts2


class TestParallelGeneration:
    def test_parallel_generates_for_all_rules(self):
        """Parallel path (>= 8 rules) should produce entries for every rule."""
        gen = CorpusGenerator(samples_per_rule=10, negative_samples=0, seed=42)
        rules = [_make_rule(f"rule_{i}", rf"[a-z]{{{i + 3}}}") for i in range(10)]
        entries = gen.generate(rules)
        sources = {e.source_rule for e in entries}
        assert sources == {f"rule_{i}" for i in range(10)}

    def test_parallel_all_entries_valid(self):
        """Every entry from parallel generation must match its source rule."""
        gen = CorpusGenerator(samples_per_rule=15, negative_samples=0, seed=42)
        rules = [_make_rule(f"r{i}", rf"[a-z]{{{i + 3}}}") for i in range(10)]
        entries = gen.generate(rules)
        for entry in entries:
            rule = next(r for r in rules if r.name == entry.source_rule)
            assert rule.compiled.search(entry.text), f"'{entry.text}' should match {rule.pattern}"

    def test_parallel_reproducibility(self):
        """Same seed should produce identical output across runs."""
        rules = [_make_rule(f"r{i}", rf"[a-z]{{{i + 3}}}") for i in range(10)]

        gen1 = CorpusGenerator(samples_per_rule=10, negative_samples=0, seed=99)
        entries1 = gen1.generate(rules)

        gen2 = CorpusGenerator(samples_per_rule=10, negative_samples=0, seed=99)
        entries2 = gen2.generate(rules)

        # Group by rule and compare (order across rules may vary with as_completed)
        def _texts_by_rule(entries: list) -> dict:
            return {
                r.name: sorted(e.text for e in entries if e.source_rule == r.name) for r in rules
            }

        by_rule1 = _texts_by_rule(entries1)
        by_rule2 = _texts_by_rule(entries2)
        assert by_rule1 == by_rule2

    def test_parallel_skip_invalid(self):
        """Parallel path should respect skip_invalid."""
        gen = CorpusGenerator(
            samples_per_rule=20,
            min_valid_samples=10,
            negative_samples=0,
            generation_timeout_s=0.5,
            seed=42,
        )
        # Mix valid rules and one genuinely unsynthesizable rule to exceed threshold of 8
        rules = [_make_rule(f"ok_{i}", rf"[a-z]{{{i + 3}}}") for i in range(8)]
        rules.append(_make_rule("impossible", _UNSYNTHESIZABLE_PATTERN))
        entries = gen.generate(rules, skip_invalid=True)
        sources = {e.source_rule for e in entries}
        assert "impossible" not in sources
        assert len(sources) == 8


class TestParallelOverride:
    """Tests for the explicit `parallel` parameter and its safety properties."""

    def test_parallel_false_forces_sequential(self):
        """parallel=False must not spawn any child processes."""
        before = set(multiprocessing.active_children())
        gen = CorpusGenerator(samples_per_rule=10, negative_samples=0, seed=42, parallel=False)
        rules = [_make_rule(f"r{i}", rf"[a-z]{{{i + 3}}}") for i in range(20)]
        entries = gen.generate(rules)
        after = set(multiprocessing.active_children())
        assert after == before, "parallel=False unexpectedly spawned worker processes"
        assert {e.source_rule for e in entries} == {f"r{i}" for i in range(20)}

    def test_parallel_true_spawns_workers_even_for_small_set(self):
        """parallel=True should override the auto threshold."""
        gen = CorpusGenerator(
            samples_per_rule=15, min_valid_samples=5, negative_samples=0, seed=42, parallel=True
        )
        rules = [_make_rule(f"r{i}", rf"[a-z]{{{i + 3}}}") for i in range(3)]
        entries = gen.generate(rules)
        assert {e.source_rule for e in entries} == {f"r{i}" for i in range(3)}

    def test_per_call_parallel_override(self):
        """The `parallel` argument on generate() overrides the constructor setting."""
        gen = CorpusGenerator(
            samples_per_rule=15, min_valid_samples=5, negative_samples=0, seed=42, parallel=True
        )
        before = set(multiprocessing.active_children())
        rules = [_make_rule(f"r{i}", rf"[a-z]{{{i + 3}}}") for i in range(15)]
        entries = gen.generate(rules, parallel=False)
        after = set(multiprocessing.active_children())
        assert after == before
        assert {e.source_rule for e in entries} == {f"r{i}" for i in range(15)}

    def test_sequential_from_thread(self):
        """Regression: sequential mode must work when called from a worker thread.

        The previous parallel implementation used fork-from-thread, which deadlocked
        ProcessPoolExecutor shutdown in multi-threaded host processes. Sequential mode
        avoids the issue entirely. This test pins the contract.
        """
        result_holder: dict[str, object] = {}

        def _run() -> None:
            try:
                gen = CorpusGenerator(
                    samples_per_rule=10, negative_samples=0, seed=42, parallel=False
                )
                rules = [_make_rule(f"r{i}", rf"[a-z]{{{i + 3}}}") for i in range(20)]
                result_holder["entries"] = gen.generate(rules)
            except Exception as exc:
                result_holder["error"] = exc

        thread = threading.Thread(target=_run, name="test-sequential-from-thread")
        thread.start()
        thread.join(timeout=30)
        assert not thread.is_alive(), "sequential generation hung when called from a thread"
        assert "error" not in result_holder, f"unexpected error: {result_holder.get('error')!r}"
        entries = result_holder["entries"]
        assert {e.source_rule for e in entries} == {f"r{i}" for i in range(20)}  # type: ignore[union-attr]

    def test_invalid_mp_context_raises_clean_error(self):
        """A bogus mp_context should raise GenerationError with a clear message."""
        gen = CorpusGenerator(
            samples_per_rule=8,
            negative_samples=0,
            seed=42,
            parallel=True,
            mp_context="not-a-real-context",
        )
        rules = [_make_rule(f"r{i}", rf"[a-z]{{{i + 3}}}") for i in range(10)]
        with pytest.raises(GenerationError, match="Invalid mp_context"):
            gen.generate(rules)


class TestParallelTimeouts:
    """Tests for the per-worker and total-batch timeout paths.

    These use mocks instead of real subprocesses so they run in milliseconds and
    are deterministic. The real subprocess paths are exercised by
    TestParallelGeneration and TestSpawnContext.
    """

    @staticmethod
    def _make_rules(count: int) -> list[Rule]:
        return [_make_rule(f"r{i}", rf"[a-z]{{{i + 3}}}") for i in range(count)]

    @staticmethod
    def _patch_pool(monkeypatch: pytest.MonkeyPatch, fake_futures: list) -> None:
        """Wire up fakes so _generate_parallel sees our pre-built futures."""
        from unittest.mock import MagicMock

        from crossfire import generator as gen_mod

        future_iter = iter(fake_futures)
        fake_executor = MagicMock(name="fake_executor")
        fake_executor.__enter__ = MagicMock(return_value=fake_executor)
        fake_executor.__exit__ = MagicMock(return_value=False)
        fake_executor.submit.side_effect = lambda *args, **kwargs: next(future_iter)
        monkeypatch.setattr(gen_mod, "ProcessPoolExecutor", lambda *args, **kwargs: fake_executor)

    def test_per_worker_timeout_skip_invalid(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When a worker times out and skip_invalid=True, the rule is counted skipped."""
        from concurrent.futures import TimeoutError as FutureTimeoutError
        from unittest.mock import MagicMock

        from crossfire import generator as gen_mod

        rules = self._make_rules(10)
        fake_futures = [MagicMock(name=f"fut_{i}") for i in range(len(rules))]
        for f in fake_futures:
            f.result.side_effect = FutureTimeoutError("simulated worker hang")
        self._patch_pool(monkeypatch, fake_futures)
        monkeypatch.setattr(gen_mod, "as_completed", lambda futs, timeout=None: iter(fake_futures))

        gen = CorpusGenerator(
            samples_per_rule=10,
            min_valid_samples=5,
            negative_samples=0,
            seed=42,
            parallel=True,
            per_worker_timeout_s=0.1,
        )
        entries, skipped = gen._generate_parallel(rules, skip_invalid=True)
        assert entries == []
        assert skipped == len(rules), "every hung worker should count as skipped"

    def test_per_worker_timeout_raises_when_not_skipping(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When a worker times out and skip_invalid=False, generation fails fast."""
        from concurrent.futures import TimeoutError as FutureTimeoutError
        from unittest.mock import MagicMock

        from crossfire import generator as gen_mod

        rules = self._make_rules(5)
        fake_futures = [MagicMock(name=f"fut_{i}") for i in range(len(rules))]
        for f in fake_futures:
            f.result.side_effect = FutureTimeoutError("simulated worker hang")
        self._patch_pool(monkeypatch, fake_futures)
        monkeypatch.setattr(gen_mod, "as_completed", lambda futs, timeout=None: iter(fake_futures))

        gen = CorpusGenerator(
            samples_per_rule=10,
            min_valid_samples=5,
            negative_samples=0,
            seed=42,
            parallel=True,
            per_worker_timeout_s=0.1,
        )
        with pytest.raises(GenerationError, match="did not return within"):
            gen._generate_parallel(rules, skip_invalid=False)

    def test_batch_timeout_lists_pending_rules(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When the total batch deadline expires, the error names the pending rules."""
        from concurrent.futures import TimeoutError as FutureTimeoutError
        from unittest.mock import MagicMock

        from crossfire import generator as gen_mod

        rules = self._make_rules(8)
        fake_futures = [MagicMock(name=f"fut_{i}") for i in range(len(rules))]
        # Mark every future as not done so the error path lists them as pending.
        for f in fake_futures:
            f.done.return_value = False
        self._patch_pool(monkeypatch, fake_futures)

        def _as_completed_raises(futs: object, timeout: float | None = None) -> object:
            raise FutureTimeoutError("simulated batch timeout")

        monkeypatch.setattr(gen_mod, "as_completed", _as_completed_raises)

        gen = CorpusGenerator(
            samples_per_rule=10,
            min_valid_samples=5,
            negative_samples=0,
            seed=42,
            parallel=True,
            per_worker_timeout_s=0.1,
        )
        with pytest.raises(GenerationError, match="Parallel generation timed out") as exc_info:
            gen._generate_parallel(rules, skip_invalid=True)

        # The error message should list at least one pending rule name and the total count.
        msg = str(exc_info.value)
        assert "8 rule(s) still pending" in msg
        assert "r0" in msg

    def test_batch_timeout_truncates_long_pending_list(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The pending list in the error message caps at 5 names + ellipsis."""
        from concurrent.futures import TimeoutError as FutureTimeoutError
        from unittest.mock import MagicMock

        from crossfire import generator as gen_mod

        rules = self._make_rules(20)
        fake_futures = [MagicMock(name=f"fut_{i}") for i in range(len(rules))]
        for f in fake_futures:
            f.done.return_value = False
        self._patch_pool(monkeypatch, fake_futures)

        def _as_completed_raises(futs: object, timeout: float | None = None) -> object:
            raise FutureTimeoutError("simulated batch timeout")

        monkeypatch.setattr(gen_mod, "as_completed", _as_completed_raises)

        gen = CorpusGenerator(
            samples_per_rule=10,
            min_valid_samples=5,
            negative_samples=0,
            seed=42,
            parallel=True,
            per_worker_timeout_s=0.1,
        )
        with pytest.raises(GenerationError) as exc_info:
            gen._generate_parallel(rules, skip_invalid=True)

        msg = str(exc_info.value)
        assert "20 rule(s) still pending" in msg
        assert "..." in msg, "long pending lists should be truncated with an ellipsis"

    def test_parallel_generation_error_skip_invalid(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When a worker raises GenerationError and skip_invalid=True, the rule is skipped.

        TestParallelGeneration::test_parallel_skip_invalid exercises this with real
        subprocesses, but pytest-cov has known issues instrumenting parent-side handlers
        for exceptions that bubble up from multiprocessing workers. This mock-based test
        gives genuine coverage of the parent-side handler.
        """
        from unittest.mock import MagicMock

        from crossfire import generator as gen_mod

        rules = self._make_rules(5)
        fake_futures = [MagicMock(name=f"fut_{i}") for i in range(len(rules))]
        for i, f in enumerate(fake_futures):
            f.result.side_effect = GenerationError(
                f"simulated failure for rule r{i}", rule_name=f"r{i}"
            )
        self._patch_pool(monkeypatch, fake_futures)
        monkeypatch.setattr(gen_mod, "as_completed", lambda futs, timeout=None: iter(fake_futures))

        gen = CorpusGenerator(
            samples_per_rule=10,
            min_valid_samples=5,
            negative_samples=0,
            seed=42,
            parallel=True,
        )
        entries, skipped = gen._generate_parallel(rules, skip_invalid=True)
        assert entries == []
        assert skipped == len(rules)

    def test_parallel_generation_error_raises_when_not_skipping(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When a worker raises GenerationError and skip_invalid=False, it propagates."""
        from unittest.mock import MagicMock

        from crossfire import generator as gen_mod

        rules = self._make_rules(3)
        fake_futures = [MagicMock(name=f"fut_{i}") for i in range(len(rules))]
        for i, f in enumerate(fake_futures):
            f.result.side_effect = GenerationError(
                f"simulated failure for rule r{i}", rule_name=f"r{i}"
            )
        self._patch_pool(monkeypatch, fake_futures)
        monkeypatch.setattr(gen_mod, "as_completed", lambda futs, timeout=None: iter(fake_futures))

        gen = CorpusGenerator(
            samples_per_rule=10,
            min_valid_samples=5,
            negative_samples=0,
            seed=42,
            parallel=True,
        )
        with pytest.raises(GenerationError, match="simulated failure"):
            gen._generate_parallel(rules, skip_invalid=False)


class TestWorkerCompileFailure:
    """The worker re-compiles patterns with stdlib `re`. If the loader accepted
    a pattern via RE2 that stdlib can't compile (e.g. non-leading `(?i)`), the
    worker must surface that as a per-rule GenerationError so `--skip-invalid`
    can honor its promise — not crash the whole batch with `re.PatternError`.
    """

    @staticmethod
    def _bad_pattern_rule() -> Rule:
        # This test targets the worker's defense-in-depth branch: the loader
        # now rejects non-leading global flags at load time, so in normal use a
        # pattern like `(?i)foo(?i)bar` never reaches a worker. We bypass
        # `crossfire.regex.compile` (and therefore the loader's stdlib-first
        # validation) by stuffing a MagicMock into `compiled`, so only
        # `rule.pattern` — the string that the worker re-compiles with stdlib
        # `re` — carries the bad flag. That mirrors the one scenario the
        # defense-in-depth guard is there for: library callers who construct
        # `Rule` objects directly and skip `load_rules`. Test is stable whether
        # or not `google-re2` is installed.
        from unittest.mock import MagicMock

        return Rule(name="bad_flag", pattern=r"(?i)foo(?i)bar", compiled=MagicMock())

    def test_worker_translates_re_error_to_generation_error(self):
        """Unit test for the worker itself — no subprocesses."""
        from crossfire.generator import _generate_for_rule_worker

        with pytest.raises(GenerationError, match="not compilable by the stdlib re"):
            _generate_for_rule_worker(
                rule_name="bad_flag",
                rule_pattern=r"(?i)foo(?i)bar",
                samples_per_rule=10,
                negative_samples=0,
                max_string_length=256,
                generation_timeout_s=1.0,
                min_valid_samples=5,
                rule_seed=42,
            )

    def test_parallel_skip_invalid_survives_stdlib_incompatible_pattern(self):
        """End-to-end: a bad pattern in a parallel batch should be skipped, not crash."""
        gen = CorpusGenerator(
            samples_per_rule=15,
            min_valid_samples=5,
            negative_samples=0,
            generation_timeout_s=0.5,
            seed=42,
            parallel=True,
        )
        rules = [_make_rule(f"ok_{i}", rf"[a-z]{{{i + 3}}}") for i in range(8)]
        rules.append(self._bad_pattern_rule())
        entries = gen.generate(rules, skip_invalid=True)
        sources = {e.source_rule for e in entries}
        assert "bad_flag" not in sources
        assert sources == {f"ok_{i}" for i in range(8)}

    def test_parallel_raises_clean_error_without_skip_invalid(self):
        """Without skip_invalid, the failure surfaces as GenerationError — not raw re.error."""
        gen = CorpusGenerator(
            samples_per_rule=15,
            min_valid_samples=5,
            negative_samples=0,
            generation_timeout_s=0.5,
            seed=42,
            parallel=True,
        )
        rules = [_make_rule(f"ok_{i}", rf"[a-z]{{{i + 3}}}") for i in range(8)]
        rules.append(self._bad_pattern_rule())
        with pytest.raises(GenerationError, match="not compilable by the stdlib re"):
            gen.generate(rules, skip_invalid=False)


class TestCharClassSemanticDrift:
    """Regression guard for the rstr/RE2 `\\s`/`\\S`/`\\w` grammar mismatch.

    `rstr.xeger` is built on stdlib `sre_parse`, so it emits strings that
    are self-consistent against stdlib grammar. When `google-re2` is
    installed, the loader returns RE2-compiled patterns whose character
    classes are narrower (e.g. RE2 `\\s` = `[\\t\\n\\f\\r ]`, while stdlib
    `\\s` also matches `\\v` and Unicode whitespace). In 0.2.3, the
    generator validated with `rule.compiled`, so broad patterns like
    `(?:foo|bar)\\s*[=:]\\s*\\S+` produced ~1 sample out of 30 attempts —
    every rstr-synthesized match was rejected by RE2. Fixed by validating
    with a stdlib `re.compile` of the same pattern (safe because the
    loader guarantees stdlib-compilability).
    """

    @pytest.mark.skipif(
        not __import__("crossfire.regex", fromlist=["is_re2_available"]).is_re2_available(),
        reason="RE2/stdlib class drift is only observable when google-re2 is installed",
    )
    def test_broad_whitespace_pattern_generates_when_re2_compiled(self):
        """A pattern with `\\s*` and `\\S+` must produce enough samples when
        `rule.compiled` is an RE2 pattern. Vacuous without google-re2 since
        `cre.compile` would fall through to stdlib — the very engine the
        fix uses for validation — so the test is RE2-gated."""
        from crossfire import regex as cre

        pattern = r"(?:secret|password|token|key)\s*[=:]\s*\S+"
        rule = Rule(
            name="broad_whitespace",
            pattern=pattern,
            compiled=cre.compile(pattern),  # RE2 when google-re2 is installed
        )
        gen = CorpusGenerator(
            samples_per_rule=20,
            min_valid_samples=10,
            negative_samples=0,
            seed=42,
        )
        entries = gen.generate([rule])
        positive = [e for e in entries if not e.is_negative]
        assert len(positive) >= 10, (
            f"generator produced only {len(positive)} samples for broad "
            f"whitespace pattern; RE2/stdlib class drift likely regressed"
        )

    def test_generator_uses_stdlib_for_validation_not_rule_compiled(self):
        """White-box: inject a Rule whose `compiled` rejects everything, and
        confirm the generator ignores it for validation. If the generator
        ever goes back to using `rule.compiled`, this test flips red.
        """

        class RejectAll:
            # Match the `CompiledPattern` protocol (`search` + `match`) so the
            # mock is drop-in even if future generator code paths reach for
            # `.match`. Both return None == no match.
            def search(self, s: str) -> None:
                return None

            def match(self, s: str) -> None:
                return None

        rule = Rule(
            name="stdlib_validated",
            pattern=r"[a-z]{5}",
            compiled=RejectAll(),  # stdlib would have matched; this rejects
        )
        gen = CorpusGenerator(
            samples_per_rule=15,
            min_valid_samples=10,
            negative_samples=0,
            seed=42,
        )
        entries = gen.generate([rule])
        positive = [e for e in entries if not e.is_negative]
        assert len(positive) >= 10


class TestSpawnContext:
    """Verify that the default mp_context is the safe one."""

    def test_default_mp_context_is_spawn(self):
        gen = CorpusGenerator(samples_per_rule=10, negative_samples=0, seed=42)
        assert gen._mp_context == "spawn"

    def test_explicit_spawn_works(self):
        gen = CorpusGenerator(
            samples_per_rule=10, negative_samples=0, seed=42, parallel=True, mp_context="spawn"
        )
        rules = [_make_rule(f"r{i}", rf"[a-z]{{{i + 3}}}") for i in range(10)]
        entries = gen.generate(rules)
        assert {e.source_rule for e in entries} == {f"r{i}" for i in range(10)}

    @pytest.mark.skipif(
        not hasattr(multiprocessing, "get_all_start_methods")
        or "fork" not in multiprocessing.get_all_start_methods(),
        reason="fork start method not available on this platform",
    )
    def test_explicit_fork_still_works_for_single_process_callers(self):
        """CLI users on Linux can still opt into fork for faster worker startup."""
        gen = CorpusGenerator(
            samples_per_rule=10, negative_samples=0, seed=42, parallel=True, mp_context="fork"
        )
        rules = [_make_rule(f"r{i}", rf"[a-z]{{{i + 3}}}") for i in range(10)]
        entries = gen.generate(rules)
        assert {e.source_rule for e in entries} == {f"r{i}" for i in range(10)}


class TestEdgeCases:
    def test_anchored_pattern(self):
        gen = CorpusGenerator(samples_per_rule=20, negative_samples=0, seed=42)
        rule = _make_rule("anchored", r"^prefix_[a-z]{5}$")
        entries = gen.generate([rule])
        positive = [e for e in entries if not e.is_negative]
        assert len(positive) >= 10
        for e in positive:
            assert rule.compiled.search(e.text)

    def test_unicode_pattern(self):
        gen = CorpusGenerator(samples_per_rule=15, negative_samples=0, seed=42, min_valid_samples=5)
        rule = _make_rule("unicode", r"[a-zA-Z0-9]{10}")
        entries = gen.generate([rule])
        assert len([e for e in entries if not e.is_negative]) >= 5

    def test_alternation_pattern(self):
        gen = CorpusGenerator(samples_per_rule=20, negative_samples=0, seed=42)
        rule = _make_rule("alt", r"(foo|bar|baz)_\d{3}")
        entries = gen.generate([rule])
        positive = [e for e in entries if not e.is_negative]
        assert len(positive) >= 3  # at least 3 variants
