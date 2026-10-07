# Copyright 2026 PBH Applied Systems, LLC
# SPDX-License-Identifier: Apache-2.0
"""qe-corpus: command-line reader for the quant_eval public corpus.

    qe-corpus --data DIR summary
    qe-corpus --data DIR paired --run RUN_ID [--check]
    qe-corpus --data DIR significance [--source d1|d5] [--alpha 0.05]
    qe-corpus --data DIR verify [--bundle PUBLICATION_DIR ...]
    qe-corpus --data DIR figure-inputs --out DIR

--data defaults to $QE_CORPUS_DATA, then the current directory.
"""
import argparse
import json
import os
import sys
from collections import Counter, defaultdict

from . import __version__
from .constants import FAMILIES, FIXTURE_KEYS, CONCEPT_DOIS
from .corpus import Corpus, CorpusError
from .paired import (family_gates, paired_table, all_paired, compare_to_d5,
                     cells_from_d5, significance_counts)
from .verify import verify_outputs, verify_fixture, verify_bundle
from .figure_inputs import write_figure_inputs


def _p(x):
    return "%.4g" % x if x >= 1e-4 else "%.3e" % x


def cmd_summary(c, args):
    out = {"data": c.root, "present": c.present()}
    runs = {}
    if c.has("D4"):
        for r in c.provenance():
            runs[r["run_id"]] = {"model_id": r["model_id"],
                                 "baseline": r["baseline_quant_type"],
                                 "quantized": r["quantized_quant_type"],
                                 "substrate": r["execution_substrate"],
                                 "source": "D4"}
    elif c.has("D5"):
        for r in c.d5():
            runs.setdefault(r["run_id"], {"model_id": r["model_id"],
                                          "baseline": r["baseline_quant_type"],
                                          "quantized": r["quantized_quant_type"],
                                          "substrate": "", "source": "D5"})
    if c.has("D1"):
        cnt = Counter()
        lanes = defaultdict(set)
        for r in c.iter_d1():
            cnt[(r["run_id"], r["family"])] += 1
            lanes[r["run_id"]].add(r["runner"])
        d1 = defaultdict(dict)
        for (rid, fam), n in cnt.items():
            d1[rid][fam] = n
        out["d1_rows"] = sum(cnt.values())
        out["d1_rows_per_run_family"] = {k: dict(v) for k, v in d1.items()}
        out["d1_runners"] = {k: sorted(v) for k, v in lanes.items()}
        for rid in d1:
            runs.setdefault(rid, {"source": "D1 only"})
    if c.has("D3"):
        fx = c.fixtures()
        out["d3_cases_per_family"] = {
            fam: len(fx.get(key, {})) for fam, key in FIXTURE_KEYS.items()}
        out["d3_version_label"] = fx.get("version")
        out["d3_fixture_schema_version"] = fx.get("fixture_schema_version")
    if c.has("D2"):
        ev = Counter(rec.get("event") for rec in c.iter_d2())
        out["d2_records"] = sum(ev.values())
        out["d2_events"] = dict(ev)
    for key, name in (("D5", "d5_rows"), ("D6", "d6_rows"), ("D7", "d7_rows")):
        if c.has(key):
            out[name] = len(getattr(c, key.lower())())
    out["runs"] = runs
    warn = []
    if "d1_rows_per_run_family" in out and (c.has("D4") or c.has("D5")):
        ref = ({r["run_id"] for r in c.provenance()} if c.has("D4")
               else {r["run_id"] for r in c.d5()})
        extra = sorted(set(out["d1_rows_per_run_family"]) - ref)
        lack = sorted(ref - set(out["d1_rows_per_run_family"]))
        if extra:
            warn.append("D1 has run_id(s) absent from %s: %s"
                        % ("D4" if c.has("D4") else "D5", ", ".join(extra)))
        if lack:
            warn.append("D1 has no rows for: %s" % ", ".join(lack))
    out["warnings"] = warn
    out["models"] = sorted({v.get("model_id") for v in runs.values() if v.get("model_id")})
    if args.json:
        print(json.dumps(out, indent=2, sort_keys=True))
        return 0

    print("quant_eval public corpus — %s" % c.root)
    print("datasets present: %s" % ", ".join(
        "%s(%s)" % (k, ",".join(v)) for k, v in sorted(out["present"].items())) or "none")
    print("")
    print("runs: %d   models: %d   families: %d" % (len(runs), len(out["models"]),
                                                   len(FAMILIES)))
    for rid, r in sorted(runs.items()):
        print("  %-48s %-40s %s -> %s  %s" % (rid, r.get("model_id", ""),
                                             r.get("baseline", ""),
                                             r.get("quantized", ""),
                                             r.get("substrate", "")))
    if "d1_rows" in out:
        print("")
        print("D1 per-case rows: %d" % out["d1_rows"])
        print("  %-48s %s" % ("run_id", "  ".join("%6s" % f[:6] for f in FAMILIES)))
        for rid, fams in sorted(out["d1_rows_per_run_family"].items()):
            print("  %-48s %s" % (rid, "  ".join("%6d" % fams.get(f, 0) for f in FAMILIES)))
        print("  (rows = cases x 2 lanes)")
    if "d3_cases_per_family" in out:
        print("")
        print("D3 fixture cases (version %s, fixture schema %s): %d"
              % (out["d3_version_label"], out["d3_fixture_schema_version"],
                 sum(out["d3_cases_per_family"].values())))
        for fam, n in out["d3_cases_per_family"].items():
            print("  %-20s %d" % (fam, n))
    if "d2_records" in out:
        print("")
        print("D2 telemetry records: %d  %s" % (out["d2_records"], out["d2_events"]))
    for name in ("d5_rows", "d6_rows", "d7_rows"):
        if name in out:
            print("%s: %d" % (name.replace("_", " ").upper().replace(" ROWS", " rows"), out[name]))
    for w in warn:
        print("WARNING: " + w)
    return 0


def _print_cells(cells, alpha, d5_diffs=None):
    print("%-18s %5s %7s %7s %8s %4s %4s %11s  %s" % (
        "family", "n", "pass_fw", "pass_q", "delta", "b", "c", "mcnemar_p", "result"))
    for cl in cells:
        print("%-18s %5d %7.3f %7.3f %+8.3f %4d %4d %11s  %s" % (
            cl.family, cl.paired_n, cl.pass_rate_a, cl.pass_rate_b, cl.delta,
            cl.runner_a_only_pass, cl.runner_b_only_pass, _p(cl.mcnemar_p_value),
            cl.direction(alpha)))
    d, i, n = significance_counts(cells, alpha)
    print("at p < %g: %d degraded, %d improved, %d not significant" % (alpha, d, i, n))


def cmd_paired(c, args):
    gates, src, conflicts = family_gates(c)
    for fam, a, b in conflicts:
        print("warning: gate for %s differs: %s vs %s" % (fam, a, b), file=sys.stderr)
    cells = paired_table(c, args.run, gates)
    if args.json:
        print(json.dumps([x.as_dict() for x in cells], indent=2))
    else:
        print("run %s   lanes: %s (full weight) vs %s (quantized)"
              % (args.run, cells[0].runner_a, cells[0].runner_b))
        print("b = full-weight-only passes, c = quantized-only passes; "
              "gates from %s" % src)
        _print_cells(cells, args.alpha)
    if args.check:
        if not c.has("D5"):
            print("check: D5 not present", file=sys.stderr)
            return 2
        diffs = compare_to_d5(cells, c.d5())
        if diffs:
            print("check against D5: %d difference(s)" % len(diffs))
            for d in diffs:
                print("  %s %s: recomputed %s, D5 %s" % d)
            return 1
        print("check against D5: all %d families match (counts exact, delta 1e-12, "
              "p-value relative 1e-9)" % len(cells))
    return 0


def cmd_significance(c, args):
    if args.source == "d5":
        per_run = cells_from_d5(c.d5())
        src = "D5 discordance counts"
    else:
        per_run = all_paired(c)
        src = "D1 per-case rows"
    models = {}
    if c.has("D4"):
        models = {r["run_id"]: (r["model_id"], r["quantized_quant_type"])
                  for r in c.provenance()}
    print("families significant at p < %g (exact McNemar), from %s" % (args.alpha, src))
    print("%-48s %-38s %-14s %8s %8s %5s" % ("run_id", "model", "quantized",
                                              "degraded", "improved", "n.s."))
    for rid in sorted(per_run):
        d, i, n = significance_counts(per_run[rid], args.alpha)
        m, q = models.get(rid, ("", ""))
        print("%-48s %-38s %-14s %8d %8d %5d" % (rid, m, q, d, i, n))
    return 0


def cmd_verify(c, args):
    bad = missing = 0
    manifest = None
    if c.has("D0m"):
        try:
            manifest = c.build_manifest()
        except ValueError:
            print("  MISMATCH  build_manifest.json is not valid JSON (not the published file)")
            bad += 1
    if manifest is not None:
        res = verify_outputs(c, manifest)
        ok = sum(1 for r in res if r[1] == "ok")
        bad += sum(1 for r in res if r[1] == "MISMATCH")
        missing += sum(1 for r in res if r[1] == "missing")
        print("build_manifest.json outputs: %d ok, %d mismatch, %d not present locally"
              % (ok, sum(1 for r in res if r[1] == "MISMATCH"),
                 sum(1 for r in res if r[1] == "missing")))
        for rel, st, det in res:
            if st != "ok" or args.verbose:
                print("  %-9s %s  %s" % (st, rel, det))
    elif not c.has("D0m"):
        print("build_manifest.json not found (it ships in D0, DOI %s); "
              "output digests not checked" % CONCEPT_DOIS["D0"])
    print("")
    for check, st, det in verify_fixture(c):
        print("  %-9s %s: %s" % (st, check, det))
        if st == "MISMATCH":
            bad += 1
    for b in args.bundle or []:
        print("")
        res = verify_bundle(b)
        print("bundle %s: %d ok, %d mismatch, %d missing" % (
            os.path.basename(os.path.normpath(b)) or b,
            sum(1 for r in res if r[1] == "ok"),
            sum(1 for r in res if r[1] == "MISMATCH"),
            sum(1 for r in res if r[1] == "missing")))
        for name, st, det in res:
            if st != "ok" or args.verbose:
                print("  %-9s %s  %s" % (st, name, det))
            if st != "ok":
                bad += 1
    if bad:
        print("\nVERIFY FAILED: %d problem(s)" % bad)
        return 1
    if args.strict and missing:
        print("\nVERIFY INCOMPLETE: %d listed file(s) not present (--strict)" % missing)
        return 1
    print("\nverify: no mismatches")
    return 0


def cmd_figure_inputs(c, args):
    for p in write_figure_inputs(c, args.out):
        print("wrote %s" % p)
    print("\nthen, from the repository root:\n"
          "  python3 make_figures.py --runs-root %s --bundles-file %s \\\n"
          "      --hardware-map %s --out figures_rebuilt"
          % (args.out, os.path.join(args.out, "corpus_runs.txt"),
             os.path.join(args.out, "hardware_map.txt")))
    return 0


def build_parser():
    ap = argparse.ArgumentParser(prog="qe-corpus", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", default=os.environ.get("QE_CORPUS_DATA", "."),
                    help="folder holding the downloaded datasets")
    ap.add_argument("--version", action="version", version="qe-corpus " + __version__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("summary", help="runs, models, families, case counts")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_summary)

    s = sub.add_parser("paired", help="recompute one run's paired table from D1")
    s.add_argument("--run", required=True)
    s.add_argument("--alpha", type=float, default=0.05)
    s.add_argument("--check", action="store_true", help="compare with D5; exit 1 on difference")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_paired)

    s = sub.add_parser("significance", help="degraded / improved / n.s. counts per run")
    s.add_argument("--source", choices=["d1", "d5"], default="d1")
    s.add_argument("--alpha", type=float, default=0.05)
    s.set_defaults(func=cmd_significance)

    s = sub.add_parser("verify", help="check files against the published digests")
    s.add_argument("--bundle", action="append",
                   help="also check a publication bundle folder against its checksums.json")
    s.add_argument("--strict", action="store_true",
                   help="fail when a file listed in build_manifest.json is absent")
    s.add_argument("-v", "--verbose", action="store_true")
    s.set_defaults(func=cmd_verify)

    s = sub.add_parser("figure-inputs",
                       help="write the reduced rollups make_figures.py reads, from D5 + D7")
    s.add_argument("--out", required=True)
    s.set_defaults(func=cmd_figure_inputs)
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return args.func(Corpus(args.data), args)
    except CorpusError as exc:
        print("qe-corpus: %s" % exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
