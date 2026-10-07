# Copyright 2026 PBH Applied Systems, LLC
# SPDX-License-Identifier: Apache-2.0
"""Checks against a downloaded copy of the published corpus.

Set QE_CORPUS_DATA to the folder holding the datasets (see docs/reproduce.md);
every test here is skipped when it is unset or the needed file is absent.

    QE_CORPUS_DATA=~/quant_eval_corpus python -m unittest discover -s tests -v
"""
import os
import unittest

from qe_corpus import Corpus, FAMILIES
from qe_corpus.paired import (all_paired, compare_to_d5, cells_from_d5,
                              significance_counts, lane_pass_counts, d1_run_ids)
from qe_corpus.stats import wilson_interval
from qe_corpus.verify import sha256_file, canonical_fixture_hash

DATA = os.environ.get("QE_CORPUS_DATA")

# Whitepaper 2, Tables 5 and 6: (degraded, improved, not significant) at p < 0.05.
WP2_COUNTS = {
    "Mistral_Nemo_Instruct_2407_20260814_030505": (5, 1, 2),   # Mistral-Nemo Q4_K_M
    "Mistral_Nemo_Instruct_2407_20260815_113254": (0, 0, 8),   # Mistral-Nemo Q5_K_M
    "Mistral_Nemo_Instruct_2407_20260816_084553": (0, 0, 8),   # Mistral-Nemo Q8_0
    "Qwen2.5_7B_Instruct_20260814_234822": (2, 2, 4),          # Qwen2.5-7B Q4_K_M
    "Qwen2.5_14B_Instruct_1M_20260815_220633": (1, 3, 4),      # Qwen2.5-14B-1M Q4_K_M
    "Qwen2.5_32B_Instruct_20260815_081051": (0, 0, 8),         # Qwen2.5-32B Q4_K_M
}

# D3 card / Whitepaper 2 section 8.2: the published fixture file.
D3_FILE_SHA256 = "0673b5e5c0fb1b7ba4bdc8c9aa985104260db183453c5708aff14c87823edb97"
D3_CANONICAL_SHA256 = "b7dd9258ca64c434eb57d32199e610c558a9e24cd0402e419de7ae72624e0cb8"
D3_BYTES = 2733585


def corpus_or_skip(test, *keys):
    if not DATA:
        test.skipTest("QE_CORPUS_DATA not set")
    c = Corpus(DATA)
    for k in keys:
        if not c.has(k):
            test.skipTest("%s not present under QE_CORPUS_DATA" % k)
    return c


class D5Internal(unittest.TestCase):
    """D5's published p-values and deltas follow from its own discordance counts."""

    def test_every_cell(self):
        c = corpus_or_skip(self, "D5")
        rows = c.d5()
        per_run = cells_from_d5(rows)
        diffs = []
        for cells in per_run.values():
            diffs += compare_to_d5(cells, rows)
        self.assertEqual(diffs, [])
        self.assertEqual(sum(len(v) for v in per_run.values()), len(rows))
        for r in rows:
            self.assertEqual(int(r["both_pass"]) + int(r["both_fail"]) +
                             int(r["runner_a_only_pass"]) + int(r["runner_b_only_pass"]),
                             int(r["paired_n"]))

    def test_wp2_table_counts(self):
        c = corpus_or_skip(self, "D5")
        per_run = cells_from_d5(c.d5())
        common = set(per_run) & set(WP2_COUNTS)
        if not common:
            self.skipTest("D5 does not contain the six Whitepaper 2 runs")
        for rid in common:
            self.assertEqual(significance_counts(per_run[rid], 0.05), WP2_COUNTS[rid], rid)


class D5D6Consistency(unittest.TestCase):
    def test_lane_counts_and_wilson(self):
        c = corpus_or_skip(self, "D5", "D6")
        d6 = {(r["run_id"], r["runner"], r["family"]): r for r in c.d6()}
        for r in c.d5():
            for lane, only in (("runner_a", "runner_a_only_pass"),
                               ("runner_b", "runner_b_only_pass")):
                k = int(r["both_pass"]) + int(r[only])
                row = d6[(r["run_id"], r[lane], r["family"])]
                self.assertEqual(int(row["pass_count"]), k)
                self.assertEqual(int(row["n"]), int(r["paired_n"]))
                self.assertAlmostEqual(float(row["pass_rate"]), k / int(row["n"]), places=12)
                lo, hi = wilson_interval(k, int(row["n"]))
                self.assertAlmostEqual(float(row["pass_rate_ci_low"]), lo, places=12)
                self.assertAlmostEqual(float(row["pass_rate_ci_high"]), hi, places=12)


class D1ReproducesD5(unittest.TestCase):
    """The tier-two check: D5 and D6 recomputed from D1 per-case rows."""

    def test_all_cells(self):
        c = corpus_or_skip(self, "D1", "D5")
        d5 = c.d5()
        runs = {r["run_id"] for r in d5}
        in_d1 = set(d1_run_ids(c))
        self.assertTrue(runs <= in_d1,
                        "D1 lacks rows for run(s) in D5: %s — this D1 is not the "
                        "published file" % sorted(runs - in_d1))
        ours = all_paired(c, runs=runs)
        matched, diffs = 0, []
        for rid in sorted(runs):
            d = compare_to_d5(ours[rid], d5)
            diffs += [(rid,) + x for x in d]
            matched += sum(1 for cell in ours[rid]
                           if not any(x[0] == cell.family for x in d))
        print("\nD1 -> D5: %d of %d run x family cells match" % (matched, len(d5)))
        self.assertEqual(diffs, [])
        self.assertEqual(matched, len(d5))

    def test_d6_from_d1(self):
        c = corpus_or_skip(self, "D1", "D6")
        d6 = c.d6()
        runs = {r["run_id"] for r in d6}
        in_d1 = set(d1_run_ids(c))
        self.assertTrue(runs <= in_d1, "D1 lacks rows for run(s) in D6: %s"
                        % sorted(runs - in_d1))
        for rid in sorted(runs):
            counts = lane_pass_counts(c, rid)
            for r in (x for x in d6 if x["run_id"] == rid):
                k, n = counts[(r["runner"], r["family"])]
                self.assertEqual((k, n), (int(r["pass_count"]), int(r["n"])),
                                 (rid, r["runner"], r["family"]))


class FixtureIdentity(unittest.TestCase):
    def test_published_fixture_file(self):
        c = corpus_or_skip(self, "D3")
        p = c.find("golden_oracle_fixtures.json")
        import json
        with open(p, encoding="utf-8") as f:
            obj = json.load(f)
        self.assertEqual(os.path.getsize(p), D3_BYTES)
        self.assertEqual(sha256_file(p), D3_FILE_SHA256)
        self.assertEqual(canonical_fixture_hash(obj), D3_CANONICAL_SHA256)
        n = sum(len(v) for k, v in obj.items() if k.endswith("_cases"))
        self.assertEqual(n, 1600)
        self.assertEqual(len(FAMILIES), 8)


if __name__ == "__main__":
    unittest.main()
