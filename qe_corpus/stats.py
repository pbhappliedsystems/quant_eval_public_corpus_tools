# Copyright 2026 PBH Applied Systems, LLC
# SPDX-License-Identifier: Apache-2.0
"""Textbook statistics used by the corpus: exact McNemar test, Wilson interval."""
import math
from dataclasses import dataclass, asdict, field
from fractions import Fraction
from math import comb

from .constants import Z95


def mcnemar_exact_p(b, c):
    """Two-sided exact McNemar p-value for discordant counts b and c.

    Under H0 the b + c discordant pairs split as Binomial(n = b + c, 1/2):

        p = min(1, 2 * sum_{i=0}^{min(b, c)} C(n, i) / 2^n),   p = 1 when n = 0.

    Computed in exact rational arithmetic and converted to float once.
    """
    b, c = int(b), int(c)
    if b < 0 or c < 0:
        raise ValueError("discordant counts must be non-negative")
    n = b + c
    if n == 0:
        return 1.0
    tail = sum(comb(n, i) for i in range(min(b, c) + 1))
    return float(min(Fraction(1), Fraction(2 * tail, 2 ** n)))


def wilson_interval(k, n, z=Z95):
    """Wilson score interval for k successes in n trials."""
    if n <= 0:
        raise ValueError("n must be positive")
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return centre - half, centre + half


@dataclass
class PairedCell:
    """One run x family paired comparison (the D5 quantities recomputed)."""
    run_id: str
    family: str
    runner_a: str            # full-weight lane
    runner_b: str            # quantized lane
    paired_n: int
    both_pass: int
    both_fail: int
    runner_a_only_pass: int  # b
    runner_b_only_pass: int  # c
    pass_rate_a: float = field(init=False)
    pass_rate_b: float = field(init=False)
    delta: float = field(init=False)
    disagreements: int = field(init=False)
    disagreement_rate: float = field(init=False)
    mcnemar_p_value: float = field(init=False)

    def __post_init__(self):
        n = self.paired_n
        a_pass = self.both_pass + self.runner_a_only_pass
        b_pass = self.both_pass + self.runner_b_only_pass
        self.pass_rate_a = a_pass / n if n else float("nan")
        self.pass_rate_b = b_pass / n if n else float("nan")
        self.delta = (b_pass - a_pass) / n if n else float("nan")
        self.disagreements = self.runner_a_only_pass + self.runner_b_only_pass
        self.disagreement_rate = self.disagreements / n if n else float("nan")
        self.mcnemar_p_value = mcnemar_exact_p(self.runner_a_only_pass,
                                               self.runner_b_only_pass)

    def direction(self, alpha=0.05):
        """'degraded', 'improved' or 'n.s.' at the given threshold."""
        if not self.mcnemar_p_value < alpha:
            return "n.s."
        if self.delta < 0:
            return "degraded"
        if self.delta > 0:
            return "improved"
        return "n.s."

    def as_dict(self):
        return asdict(self)
