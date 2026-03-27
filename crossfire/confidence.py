"""Statistical confidence intervals for overlap measurements."""

from __future__ import annotations

import logging
import math

log = logging.getLogger("crossfire.confidence")


def wilson_interval(
    matches: int,
    total: int,
    confidence: float = 0.95,
) -> tuple[float, float]:
    """Compute Wilson score confidence interval for a binomial proportion.

    More accurate than the normal approximation for small sample sizes and
    extreme proportions (near 0 or 1).

    Args:
        matches: Number of successes (corpus strings matched).
        total: Total number of trials (corpus size).
        confidence: Confidence level (default 0.95 for 95% CI).

    Returns:
        (lower_bound, upper_bound) as floats in [0.0, 1.0].
    """
    if total == 0:
        return (0.0, 0.0)

    # Z-score for the confidence level
    # Common values: 0.90→1.645, 0.95→1.96, 0.99→2.576
    z = _z_score(confidence)
    n = total
    p_hat = matches / n

    denominator = 1 + z * z / n
    center = p_hat + z * z / (2 * n)
    radicand = (p_hat * (1 - p_hat) + z * z / (4 * n)) / n
    spread = z * math.sqrt(max(0.0, radicand))

    lower = max(0.0, (center - spread) / denominator)
    upper = min(1.0, (center + spread) / denominator)

    return (round(lower, 4), round(upper, 4))


def is_confident(
    matches: int,
    total: int,
    threshold: float = 0.8,
    confidence: float = 0.95,
) -> bool:
    """Check if the overlap proportion confidently exceeds a threshold.

    Returns True if the lower bound of the CI is >= threshold.
    This is a conservative check — we're confident the true overlap
    is at least as high as the threshold.
    """
    lower, _ = wilson_interval(matches, total, confidence)
    return lower >= threshold


def ci_width(matches: int, total: int, confidence: float = 0.95) -> float:
    """Compute the width of the confidence interval.

    Useful for determining if more samples are needed.
    Width > 0.3 suggests insufficient sample size.
    """
    lower, upper = wilson_interval(matches, total, confidence)
    return round(upper - lower, 4)


def recommend_samples(
    matches: int,
    total: int,
    target_width: float = 0.1,
    confidence: float = 0.95,
) -> int:
    """Estimate the number of samples needed for a target CI width.

    Uses the normal approximation formula: n = (z/w)^2 * p*(1-p) * 4

    Args:
        matches: Current number of matches.
        total: Current total samples.
        target_width: Desired CI width (default 0.1 = ±5%).
        confidence: Confidence level.

    Returns:
        Recommended sample count (minimum 10).
    """
    if total == 0:
        return max(10, int(100 / target_width))

    z = _z_score(confidence)
    p_hat = matches / total
    # Variance is maximized at p=0.5, use observed p for better estimate
    variance = p_hat * (1 - p_hat)
    if variance == 0:
        # All matches or no matches — minimal samples needed
        return max(10, total)

    n = math.ceil(4 * (z / target_width) ** 2 * variance)
    return max(10, n)


_Z_LOOKUP = {0.90: 1.6449, 0.95: 1.9600, 0.99: 2.5758}


def _z_score(confidence: float) -> float:
    """Approximate z-score for common confidence levels.

    Uses a lookup for common values, falls back to rational approximation
    for others.
    """
    for level, z in _Z_LOOKUP.items():
        if abs(confidence - level) < 0.001:
            return z

    # Approximation using rational function (Abramowitz & Stegun 26.2.23)
    # For the upper tail: P(Z > z) = (1 - confidence) / 2
    p = (1 - confidence) / 2
    if p <= 0 or p >= 0.5:
        return 1.96  # fallback to 95%

    t = math.sqrt(-2 * math.log(p))
    # Rational approximation coefficients
    c0, c1, c2 = 2.515517, 0.802853, 0.010328
    d1, d2, d3 = 1.432788, 0.189269, 0.001308
    z = t - (c0 + c1 * t + c2 * t * t) / (1 + d1 * t + d2 * t * t + d3 * t * t * t)
    return round(z, 4)
