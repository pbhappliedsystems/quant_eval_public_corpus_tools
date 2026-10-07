# Copyright 2026 PBH Applied Systems, LLC
# SPDX-License-Identifier: Apache-2.0
"""Recompute the per-family paired table (D5 quantities) from D1 per-case rows.

Procedure (Whitepaper 2, section 8.3): for one run and one family, apply the
family's published gate conjunction to each D1 row, join the two lanes on
case_id, and classify each case as both pass / both fail / full-weight only /
quantized only. The delta and the exact McNemar test follow from those counts.
"""
from collections import defaultdict

from .constants import DEFAULT_GATES, FAMILIES
from .corpus import CorpusError
from .stats import PairedCell


def truthy(v):
    """Same rule the corpus builder uses for gate columns."""
    return str(v).strip().lower() in ("true", "1", "yes")


def family_gates(corpus=None):
    """Gate conjunction per family: from D6 `gating_signals` when available,
    otherwise the published defaults. Returns (gates, source, conflicts)."""
    if corpus is None or not corpus.has("D6"):
        return dict(DEFAULT_GATES), "built-in (Whitepaper 2 Table 1)", []
    gates, conflicts = {}, []
    for r in corpus.d6():
        sig = [s.strip() for s in r["gating_signals"].split(" AND ") if s.strip()]
        fam = r["family"]
        if fam in gates and gates[fam] != sig:
            conflicts.append((fam, gates[fam], sig))
        gates.setdefault(fam, sig)
    for fam, sig in gates.items():
        if fam in DEFAULT_GATES and DEFAULT_GATES[fam] != sig:
            conflicts.append((fam, DEFAULT_GATES[fam], sig))
    for fam in DEFAULT_GATES:
        gates.setdefault(fam, list(DEFAULT_GATES[fam]))
    return gates, "D6 gating_signals", conflicts


def lane_runners(corpus, run_id, runners_seen):
    """(full-weight runner, quantized runner) for a run.

    Uses D4 baseline_runner / quantized_runner when D4 is present; otherwise the
    runner-name prefix (`full_weight_*` / `quantized_*`) used throughout the corpus.
    """
    if corpus is not None and corpus.has("D4"):
        for r in corpus.provenance():
            if r["run_id"] == run_id and r.get("baseline_runner") and r.get("quantized_runner"):
                return r["baseline_runner"], r["quantized_runner"]
    a = [x for x in runners_seen if x.startswith("full_weight")]
    b = [x for x in runners_seen if x.startswith("quantized")]
    if len(a) == 1 and len(b) == 1:
        return a[0], b[0]
    raise CorpusError("cannot tell the full-weight and quantized lanes apart for "
                      "%s (runners: %s)" % (run_id, sorted(runners_seen)))


def collect_outcomes(rows, run_id, gates):
    """{family: {runner: {case_id: bool}}} for one run."""
    out = defaultdict(lambda: defaultdict(dict))
    for r in rows:
        if r["run_id"] != run_id:
            continue
        fam = r["family"]
        if fam not in gates:
            raise CorpusError("no gate definition for family %r" % fam)
        cid = r["case_id"]
        lane = out[fam][r["runner"]]
        if cid in lane:
            raise CorpusError("duplicate row %s / %s / %s / %s"
                              % (run_id, r["runner"], fam, cid))
        missing = [s for s in gates[fam] if s not in r]
        if missing:
            raise CorpusError("D1 lacks gate column(s) %s" % ", ".join(missing))
        lane[cid] = all(truthy(r[s]) for s in gates[fam])
    return out


def paired_from_outcomes(run_id, outcomes, runner_a, runner_b):
    cells = []
    order = [f for f in FAMILIES if f in outcomes] + sorted(
        f for f in outcomes if f not in FAMILIES)
    for fam in order:
        A = outcomes[fam].get(runner_a, {})
        B = outcomes[fam].get(runner_b, {})
        shared = set(A) & set(B)
        bp = bf = ao = bo = 0
        for cid in shared:
            pa, pb = A[cid], B[cid]
            if pa and pb:
                bp += 1
            elif not pa and not pb:
                bf += 1
            elif pa:
                ao += 1
            else:
                bo += 1
        cells.append(PairedCell(run_id, fam, runner_a, runner_b, len(shared),
                                bp, bf, ao, bo))
    return cells


def paired_table(corpus, run_id, gates=None):
    """Recompute the eight per-family paired cells of one run from D1."""
    if gates is None:
        gates, _, _ = family_gates(corpus)
    outcomes = collect_outcomes(corpus.iter_d1(), run_id, gates)
    if not outcomes:
        raise CorpusError("run %s has no rows in D1" % run_id)
    runners = {rn for fam in outcomes.values() for rn in fam}
    ra, rb = lane_runners(corpus, run_id, runners)
    return paired_from_outcomes(run_id, outcomes, ra, rb)


def d1_run_ids(corpus):
    return sorted({r["run_id"] for r in corpus.iter_d1()})


def all_paired(corpus, gates=None, runs=None):
    """Paired cells for every run in D1 (or only `runs`), one streaming pass."""
    if gates is None:
        gates, _, _ = family_gates(corpus)
    per_run = defaultdict(list)
    for r in corpus.iter_d1():
        if runs is not None and r["run_id"] not in runs:
            continue
        per_run[r["run_id"]].append({k: r[k] for k in
                                     ("run_id", "runner", "family", "case_id")}
                                    | {s: r.get(s, "") for f in gates
                                       for s in gates[f]})
    out = {}
    for run_id, rows in per_run.items():
        outcomes = collect_outcomes(rows, run_id, gates)
        runners = {rn for fam in outcomes.values() for rn in fam}
        ra, rb = lane_runners(corpus, run_id, runners)
        out[run_id] = paired_from_outcomes(run_id, outcomes, ra, rb)
    return out


def lane_pass_counts(corpus, run_id, gates=None):
    """{(runner, family): (pass_count, n)} from D1 — the D6 quantities."""
    if gates is None:
        gates, _, _ = family_gates(corpus)
    outcomes = collect_outcomes(corpus.iter_d1(), run_id, gates)
    return {(rn, fam): (sum(1 for v in cases.values() if v), len(cases))
            for fam, lanes in outcomes.items() for rn, cases in lanes.items()}


def compare_to_d5(cells, d5_rows, p_rel_tol=1e-9, abs_tol=1e-12):
    """Compare recomputed cells with published D5 rows.

    Counts must match exactly; delta and disagreement rate to `abs_tol`;
    the McNemar p-value to relative tolerance `p_rel_tol` (D5 stores the
    harness's floating-point value, which differs from the exact rational in
    the last few bits). Returns a list of (family, field, ours, published).
    """
    pub = {(r["run_id"], r["family"]): r for r in d5_rows}
    diffs = []
    for c in cells:
        r = pub.get((c.run_id, c.family))
        if r is None:
            diffs.append((c.family, "row", "present", "absent in D5"))
            continue
        for fld, ours in (("paired_n", c.paired_n), ("both_pass", c.both_pass),
                          ("both_fail", c.both_fail),
                          ("runner_a_only_pass", c.runner_a_only_pass),
                          ("runner_b_only_pass", c.runner_b_only_pass),
                          ("disagreements", c.disagreements),
                          ("mcnemar_discordant_pairs", c.disagreements)):
            if int(float(r[fld])) != ours:
                diffs.append((c.family, fld, ours, r[fld]))
        for fld, ours in (("runner_a", c.runner_a), ("runner_b", c.runner_b)):
            if r[fld] != ours:
                diffs.append((c.family, fld, ours, r[fld]))
        for fld, ours in (("pass_rate_delta_runner_b_minus_runner_a", c.delta),
                          ("disagreement_rate", c.disagreement_rate)):
            if abs(float(r[fld]) - ours) > abs_tol:
                diffs.append((c.family, fld, ours, r[fld]))
        pp = float(r["mcnemar_p_value"])
        if abs(pp - c.mcnemar_p_value) > p_rel_tol * max(abs(pp), 1e-300):
            diffs.append((c.family, "mcnemar_p_value", c.mcnemar_p_value, r["mcnemar_p_value"]))
    return diffs


def cells_from_d5(d5_rows):
    """PairedCell objects rebuilt from D5's own discordance counts."""
    out = defaultdict(list)
    for r in d5_rows:
        out[r["run_id"]].append(PairedCell(
            r["run_id"], r["family"], r["runner_a"], r["runner_b"],
            int(r["paired_n"]), int(r["both_pass"]), int(r["both_fail"]),
            int(r["runner_a_only_pass"]), int(r["runner_b_only_pass"])))
    return dict(out)


def significance_counts(cells, alpha=0.05):
    """(degraded, improved, not significant) over a run's family cells."""
    dirs = [c.direction(alpha) for c in cells]
    return dirs.count("degraded"), dirs.count("improved"), dirs.count("n.s.")
