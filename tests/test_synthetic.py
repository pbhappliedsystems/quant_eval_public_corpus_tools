# Copyright 2026 PBH Applied Systems, LLC
# SPDX-License-Identifier: Apache-2.0
"""End-to-end tests on a small synthetic corpus written to a temp folder.

The synthetic files follow the published column layout; their values are
invented and carry no information about any real run.
"""
import contextlib
import csv
import hashlib
import io
import json
import os
import random
import tempfile
import unittest

from qe_corpus import Corpus, paired_table
from qe_corpus.cli import main
from qe_corpus.constants import DEFAULT_GATES, FAMILIES, FIXTURE_KEYS
from qe_corpus.paired import compare_to_d5, all_paired, lane_pass_counts
from qe_corpus.stats import mcnemar_exact_p, wilson_interval
from qe_corpus.verify import canonical_fixture_hash

RUN = "Synthetic_Model_20990101_000000"
RA, RB = "full_weight_llama_cpp", "quantized_llama_cpp"
N = 40


def sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def write_csv(path, fields, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def build(root, tamper_d5=False):
    rnd = random.Random(7)
    gate_cols = sorted({s for g in DEFAULT_GATES.values() for s in g})
    d1, truth = [], {}
    for fam in FAMILIES:
        for i in range(N):
            cid = "%s_case_%03d" % (fam, i)
            for rn, bias in ((RA, 0.6), (RB, 0.45)):
                ok = rnd.random() < bias
                row = {"run_id": RUN, "runner": rn, "family": fam, "case_id": cid,
                       "output_raw": "x"}
                for col in gate_cols:
                    row[col] = ""
                for s in DEFAULT_GATES[fam]:
                    row[s] = "1"
                if not ok:  # fail exactly one gate
                    row[rnd.choice(DEFAULT_GATES[fam])] = "0"
                truth[(rn, fam, cid)] = ok
                d1.append(row)
    write_csv(os.path.join(root, "D1_quant_eval_behavioral_per_case_results",
                           "quant_eval_behavioral_per_case_results.csv"),
              ["run_id", "runner", "family", "case_id", "output_raw"] + gate_cols, d1)

    d5, d6 = [], []
    for fam in FAMILIES:
        bp = bf = ao = bo = 0
        for i in range(N):
            cid = "%s_case_%03d" % (fam, i)
            a, b = truth[(RA, fam, cid)], truth[(RB, fam, cid)]
            bp += a and b
            bf += (not a) and (not b)
            ao += a and not b
            bo += b and not a
        if tamper_d5 and fam == "mcq":
            bp, ao = bp + 1, ao - 1
        d5.append({"run_id": RUN, "family": fam, "runner_a": RA, "runner_b": RB,
                   "paired_n": N, "both_pass": bp, "both_fail": bf,
                   "runner_a_only_pass": ao, "runner_b_only_pass": bo,
                   "disagreements": ao + bo, "disagreement_rate": (ao + bo) / N,
                   "pass_rate_delta_runner_b_minus_runner_a": (bo - ao) / N,
                   "mcnemar_p_value": mcnemar_exact_p(ao, bo),
                   "mcnemar_discordant_pairs": ao + bo})
        for rn, k in ((RA, bp + ao), (RB, bp + bo)):
            lo, hi = wilson_interval(k, N)
            d6.append({"run_id": RUN, "runner": rn, "family": fam, "n": N,
                       "pass_count": k, "pass_rate": k / N, "pass_rate_ci_low": lo,
                       "pass_rate_ci_high": hi,
                       "gating_signals": " AND ".join(DEFAULT_GATES[fam])})
    write_csv(os.path.join(root, "D5_quant_eval_paired_degradation_statistics",
                           "quant_eval_paired_degradation_statistics.csv"),
              list(d5[0].keys()) + ["delta_ci_low", "delta_ci_high"],
              [dict(r, delta_ci_low=-0.1, delta_ci_high=0.1) for r in d5])
    write_csv(os.path.join(root, "D6_quant_eval_family_pass_rates",
                           "quant_eval_family_pass_rates.csv"), list(d6[0].keys()), d6)
    d4_path = os.path.join(root, "D4_quant_eval_run_provenance",
                           "quant_eval_run_provenance.csv")
    write_csv(d4_path,
              ["run_id", "model_id", "baseline_quant_type", "quantized_quant_type",
               "baseline_runner", "quantized_runner", "execution_substrate",
               "fixtures_sha256"],
              [{"run_id": RUN, "model_id": "example/model", "baseline_quant_type": "gguf_f16",
                "quantized_quant_type": "gguf_q4_k_m", "baseline_runner": RA,
                "quantized_runner": RB, "execution_substrate": "local_llama_cpp",
                "fixtures_sha256": "PLACEHOLDER"}])
    write_csv(os.path.join(root, "D7_quant_eval_efficiency_and_footprint",
                           "quant_eval_efficiency_and_footprint.csv"),
              ["run_id", "baseline_bytes", "quantized_bytes", "compression_ratio",
               "size_reduction_fraction", "observed_wall_time_ratio",
               "wall_time_direction", "baseline_accelerator", "quantized_accelerator"],
              [{"run_id": RUN, "baseline_bytes": 100, "quantized_bytes": 30,
                "compression_ratio": 100 / 30, "size_reduction_fraction": 0.7,
                "observed_wall_time_ratio": 2.0, "wall_time_direction": "speedup",
                "baseline_accelerator": "nvidia_t4", "quantized_accelerator": "nvidia_t4"}])

    # D3: minimal fixture object with the published top-level layout
    fx = {"version": "vX", "fixture_schema_version": "0"}
    for fam, key in FIXTURE_KEYS.items():
        cases = [{"case_id": "%s_case_%03d" % (fam, i), "difficulty": "foundation"}
                 for i in range(N)]
        fx[key] = {c["case_id"]: c for c in cases} if fam == "json" else cases
    d3 = os.path.join(root, "D3_quant_eval_golden_oracle_fixtures")
    os.makedirs(d3)
    fpath = os.path.join(d3, "golden_oracle_fixtures.json")
    with open(fpath, "w", encoding="utf-8") as f:
        json.dump(fx, f)
    fsha = sha(fpath)
    write_csv(os.path.join(d3, "fixture_version_crosswalk.csv"),
              ["run_id", "fixtures_sha256", "fixture_version_label",
               "canonical_content_sha256", "is_published_file"],
              [{"run_id": RUN, "fixtures_sha256": fsha, "fixture_version_label": "vX",
                "canonical_content_sha256": canonical_fixture_hash(fx),
                "is_published_file": "true"}])
    with open(d4_path, encoding="utf-8") as f:
        d4_text = f.read().replace("PLACEHOLDER", fsha)
    with open(d4_path, "w", encoding="utf-8", newline="") as f:
        f.write(d4_text)
    sbc = {"algorithm": "sha256", "bundles": {RUN: {"algorithm": "sha256", "schema_version": 1,
           "files": {"golden_oracle_fixtures.json": {"digest": fsha,
                                                     "bytes": os.path.getsize(fpath)}}}}}
    with open(os.path.join(d3, "source_bundle_checksums.json"), "w") as f:
        json.dump(sbc, f)

    # D0: build manifest over every file written so far
    outputs = {}
    for dirpath, _, files in os.walk(root):
        for fn in files:
            p = os.path.join(dirpath, fn)
            outputs[os.path.relpath(p, root).replace(os.sep, "/")] = {
                "sha256": sha(p), "bytes": os.path.getsize(p)}
    d0 = os.path.join(root, "D0_quant_eval_public_corpus")
    os.makedirs(d0)
    with open(os.path.join(d0, "build_manifest.json"), "w") as f:
        json.dump({"outputs": outputs}, f)
    return truth


def run_cli(*argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
        code = main(list(argv))
    return code, buf.getvalue()


class Synthetic(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.truth = build(self.root)
        self.c = Corpus(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_paired_matches_d5(self):
        cells = paired_table(self.c, RUN)
        self.assertEqual([x.family for x in cells], FAMILIES)
        self.assertEqual(compare_to_d5(cells, self.c.d5()), [])
        self.assertEqual(all_paired(self.c)[RUN][0].as_dict(), cells[0].as_dict())

    def test_lane_counts_match_d6(self):
        counts = lane_pass_counts(self.c, RUN)
        for r in self.c.d6():
            k, n = counts[(r["runner"], r["family"])]
            self.assertEqual((k, n), (int(r["pass_count"]), int(r["n"])))

    def test_cli_paired_check(self):
        code, out = run_cli("--data", self.root, "paired", "--run", RUN, "--check")
        self.assertEqual(code, 0, out)
        self.assertIn("all 8 families match", out)

    def test_cli_detects_d5_difference(self):
        tmp = tempfile.TemporaryDirectory()
        build(tmp.name, tamper_d5=True)
        code, out = run_cli("--data", tmp.name, "paired", "--run", RUN, "--check")
        tmp.cleanup()
        self.assertEqual(code, 1)
        self.assertIn("mcq both_pass", out)

    def test_cli_summary_and_significance(self):
        code, out = run_cli("--data", self.root, "summary")
        self.assertEqual(code, 0)
        self.assertIn("runs: 1", out)
        code, out = run_cli("--data", self.root, "significance", "--source", "d5")
        self.assertEqual(code, 0)
        self.assertIn(RUN, out)

    def test_verify_ok_then_tampered(self):
        code, out = run_cli("--data", self.root, "verify")
        self.assertEqual(code, 0, out)
        p = self.c.find("quant_eval_family_pass_rates.csv")
        with open(p, "a") as f:
            f.write("\n")
        code, out = run_cli("--data", self.root, "verify")
        self.assertEqual(code, 1)
        self.assertIn("MISMATCH", out)

    def test_figure_inputs(self):
        out_dir = os.path.join(self.root, "figin")
        code, _ = run_cli("--data", self.root, "figure-inputs", "--out", out_dir)
        self.assertEqual(code, 0)
        with open(os.path.join(out_dir, RUN, "publication", "rollup.json")) as f:
            r = json.load(f)
        self.assertEqual(sorted(r), ["efficiency", "paired_runner_comparison", "run_id"])
        self.assertEqual(sorted(r["paired_runner_comparison"]), sorted(FAMILIES))


if __name__ == "__main__":
    unittest.main()
