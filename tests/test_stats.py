# Copyright 2026 PBH Applied Systems, LLC
# SPDX-License-Identifier: Apache-2.0
"""Unit tests for the textbook statistics. No corpus download needed."""
import unittest
from fractions import Fraction
from math import comb

from qe_corpus.stats import mcnemar_exact_p, wilson_interval, PairedCell


def brute_force_p(b, c):
    """Two-sided exact binomial test by summing every outcome at most as
    likely as the observed one (equals the doubled tail for p = 1/2)."""
    n = b + c
    if n == 0:
        return 1.0
    probs = [Fraction(comb(n, i), 2 ** n) for i in range(n + 1)]
    obs = probs[b]
    return float(min(Fraction(1), sum(p for p in probs if p <= obs)))


class McNemar(unittest.TestCase):
    def test_no_discordant_pairs(self):
        self.assertEqual(mcnemar_exact_p(0, 0), 1.0)

    def test_known_values(self):
        self.assertEqual(mcnemar_exact_p(2, 4), 0.6875)          # 44/64
        self.assertEqual(mcnemar_exact_p(0, 10), 2 / 1024)
        self.assertEqual(mcnemar_exact_p(1, 9), 22 / 1024)
        self.assertEqual(mcnemar_exact_p(5, 5), 1.0)             # capped at 1

    def test_symmetric(self):
        for b in range(0, 15):
            for c in range(0, 15):
                self.assertEqual(mcnemar_exact_p(b, c), mcnemar_exact_p(c, b))

    def test_matches_brute_force(self):
        for b in range(0, 25):
            for c in range(0, 25):
                self.assertAlmostEqual(mcnemar_exact_p(b, c), brute_force_p(b, c),
                                       places=14)

    def test_rejects_negative(self):
        with self.assertRaises(ValueError):
            mcnemar_exact_p(-1, 2)


class Wilson(unittest.TestCase):
    def test_published_d6_row(self):
        # D6: Mistral-Nemo Q4_K_M run, full-weight lane, json: 83 / 200,
        # published interval 0.34894285449757567 .. 0.4842608509865596
        lo, hi = wilson_interval(83, 200)
        self.assertAlmostEqual(lo, 0.34894285449757567, places=15)
        self.assertAlmostEqual(hi, 0.4842608509865596, places=15)

    def test_bounds(self):
        lo, hi = wilson_interval(0, 200)
        self.assertAlmostEqual(lo, 0.0, places=15)
        lo, hi = wilson_interval(200, 200)
        self.assertAlmostEqual(hi, 1.0, places=15)


class Cell(unittest.TestCase):
    def test_derived_fields(self):
        # D5: Mistral-Nemo Q4_K_M run, json family
        c = PairedCell("r", "json", "a", "b", 200, 81, 113, 2, 4)
        self.assertEqual(c.pass_rate_a, 83 / 200)
        self.assertEqual(c.pass_rate_b, 85 / 200)
        self.assertEqual(c.delta, 0.01)
        self.assertEqual(c.disagreements, 6)
        self.assertEqual(c.disagreement_rate, 0.03)
        self.assertEqual(c.mcnemar_p_value, 0.6875)
        self.assertEqual(c.direction(), "n.s.")

    def test_direction(self):
        self.assertEqual(PairedCell("r", "f", "a", "b", 200, 100, 50, 30, 5).direction(),
                         "degraded")
        self.assertEqual(PairedCell("r", "f", "a", "b", 200, 100, 50, 5, 30).direction(),
                         "improved")


if __name__ == "__main__":
    unittest.main()
