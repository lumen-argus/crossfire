"""Tests for confidence interval calculations."""

from __future__ import annotations

from crossfire.confidence import ci_width, is_confident, recommend_samples, wilson_interval


class TestWilsonInterval:
    def test_perfect_match(self):
        """All matches → CI close to (1.0, 1.0)."""
        lower, upper = wilson_interval(50, 50)
        assert lower > 0.9
        assert upper == 1.0

    def test_no_match(self):
        """Zero matches → CI close to (0.0, 0.0)."""
        lower, upper = wilson_interval(0, 50)
        assert lower == 0.0
        assert upper < 0.1

    def test_half_match(self):
        """50% match → CI centered around 0.5."""
        lower, upper = wilson_interval(25, 50)
        assert 0.3 < lower < 0.5
        assert 0.5 < upper < 0.7

    def test_empty_total(self):
        lower, upper = wilson_interval(0, 0)
        assert lower == 0.0
        assert upper == 0.0

    def test_ci_narrows_with_more_samples(self):
        """More samples → narrower CI."""
        _, upper_small = wilson_interval(8, 10)
        lower_small, _ = wilson_interval(8, 10)
        width_small = upper_small - lower_small

        _, upper_large = wilson_interval(80, 100)
        lower_large, _ = wilson_interval(80, 100)
        width_large = upper_large - lower_large

        assert width_large < width_small

    def test_99_percent_confidence(self):
        """99% CI is wider than 95%."""
        w95 = ci_width(25, 50, confidence=0.95)
        w99 = ci_width(25, 50, confidence=0.99)
        assert w99 > w95

    def test_bounds_between_0_and_1(self):
        """Bounds should always be in [0, 1]."""
        for matches, total in [(0, 10), (5, 10), (10, 10), (1, 100), (99, 100)]:
            lower, upper = wilson_interval(matches, total)
            assert 0.0 <= lower <= upper <= 1.0


class TestIsConfident:
    def test_clearly_above_threshold(self):
        # 48/50 = 0.96, CI lower bound should be > 0.8
        assert is_confident(48, 50, threshold=0.8)

    def test_clearly_below_threshold(self):
        assert not is_confident(20, 50, threshold=0.8)

    def test_borderline(self):
        # 40/50 = 0.8, but CI lower bound will be < 0.8
        assert not is_confident(40, 50, threshold=0.8)

    def test_high_threshold_needs_more_evidence(self):
        assert not is_confident(45, 50, threshold=0.95)


class TestCiWidth:
    def test_small_sample(self):
        w = ci_width(5, 10)
        assert w > 0.2  # Wide CI for small samples

    def test_large_sample(self):
        w = ci_width(500, 1000)
        assert w < 0.1  # Narrow CI for large samples

    def test_zero(self):
        assert ci_width(0, 0) == 0.0


class TestRecommendSamples:
    def test_recommends_more_for_narrow_target(self):
        n_wide = recommend_samples(25, 50, target_width=0.2)
        n_narrow = recommend_samples(25, 50, target_width=0.05)
        assert n_narrow > n_wide

    def test_minimum_10(self):
        assert recommend_samples(0, 0) >= 10

    def test_extreme_proportion(self):
        # All matches → low variance → fewer samples needed
        n = recommend_samples(50, 50, target_width=0.1)
        assert n <= 50
