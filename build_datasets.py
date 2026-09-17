#!/usr/bin/env python3
"""
build_datasets.py — derive the quant_eval public corpus (D1-D7) from publication bundles.

Implements PBH_quant_eval_Dataset_Specification_v4.

GOVERNING CONSTRAINT
--------------------
No byte of any run bundle is modified or copied verbatim where it carries a
confidential field. Sanitization is achieved by FIELD SELECTION during derivation:
`app`, `backend`, `class`, `allowed_root`, and `modal://` path strings are never
selected. All source `checksums.json` digests therefore remain valid and are
republished as the provenance record.

USAGE
-----
    python3 build_datasets.py --bundles-file corpus_runs.txt \
                              --hardware-map hardware_map.txt --dry-run
    python3 build_datasets.py --bundles-file corpus_runs.txt \
                              --hardware-map hardware_map.txt \
                              --lineage calibration_lineage.txt \
                              --doi-map reserved_dois.json

HARDWARE DECLARATION (REQUIRED)
-------------------------------
--hardware-map is mandatory and the build aborts without it. The source bundles
record the execution substrate but not the accelerator class that ran each lane
of a pair. Corpus v1.0.0 shipped D7 without it, and two runs whose full-weight
and quantized lanes executed on different accelerators were presented as though
quantization alone produced their wall-time ratios. An omission that silent
must be fatal, not defaultable.
    python3 build_datasets.py --allowlist runs.txt       # explicit run selection
    python3 build_datasets.py --runs-root PATH --out PATH
    python3 build_datasets.py --exclude RUN_ID [--exclude RUN_ID ...]

RUN SELECTION
-------------
REQUIRED for publication: name the run folders explicitly with --bundle or
--bundles-file. Publication status is an owner decision that no manifest field
records, so the script never infers which of several eligible runs to use.
The build record then states which runs were used rather than which rule
selected them, which is what a published corpus should be able to say.
Paths may point at the run folder or at its publication/ subfolder, and may be
absolute or relative to --runs-root. Explicit selection bypasses discovery;
discovery still runs to disclose eligible runs that were not selected.

Eligibility is not selection. A run stays `publication_status: eligible`
forever, and no manifest field records which run the owner reviewed and deemed
publishable. If discovery finds several eligible runs sharing one
model-precision pair, the build ABORTS and asks to be told; it never chooses.
Runs not selected are simply not included; calibration runs that informed a
published run are disclosed by identifier via --lineage.

Defaults are the Windows/WSL layout:
    runs root : /mnt/e/QUANT_EVAL/runs/<MODEL_DIR>/<RUN_ID>/publication/
    output    : /mnt/e/QUANT_EVAL/datasets/quant_eval_public_corpus/

DOIs
----
Zenodo issues two DOIs per record: a CONCEPT DOI that always resolves to the
latest version, and a VERSION DOI frozen to one deposit. Both are used, for
different jobs:

  concept  -> "cite this dataset" in the card header, BibTeX, CITATION.cff,
              and the LICENCE attribution. Cards are living surfaces on HF and
              Kaggle and must not hard-code a superseded deposit.
  version  -> stated alongside as "this exact deposit", for anyone whose
              reported numbers must stay verifiable against the object cited.

A concept DOI does not exist until the first version is published, so the first
deposit may carry version DOIs only and be rebuilt once the concept DOI exists.

OUTPUT LAYOUT
------------
One folder per dataset, each independently depositable, each carrying its own
README.md (HF/Kaggle card with YAML frontmatter), LICENSE, and CITATION.cff:

    <out>/README.md              corpus overview
    <out>/LICENSE                CC BY 4.0
    <out>/build_manifest.json    digests, verification counts, DOI map
    <out>/D1_.../               data + data_dictionary + checksums + card
    ...
    <out>/D7_.../

EXIT CODES
----------
    0  success
    1  usage / no eligible bundles found
    2  integrity failure (checksum mismatch or statistic mismatch)
    3  sanitization failure (a forbidden token reached an output file)

Standard library only.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sys
from collections import Counter, OrderedDict
from datetime import datetime, timezone

csv.field_size_limit(min(sys.maxsize, 2**31 - 1))

SPEC_VERSION = "PBH_quant_eval_Dataset_Specification_v4"
BUILDER_VERSION = "build_datasets.py 2.5.0"

DEFAULT_RUNS_ROOT = "/mnt/e/QUANT_EVAL/runs"
DEFAULT_OUT_ROOT = "/mnt/e/QUANT_EVAL/datasets/quant_eval_public_corpus"

FAMILIES = ["json", "json_multistep", "mcq", "mixed_brief_json",
            "stateful_followup", "toolcall", "toolcall_only", "fuzz"]

# ---- sanitization -----------------------------------------------------------
# Telemetry keys never selected (Modal deployment internals).
TELEMETRY_EXCLUDE_KEYS = {"app", "backend", "class"}
# Any output containing these is a build failure, not a warning.
FORBIDDEN_PATTERNS = [
    re.compile(r"modal://"),
    re.compile(r'"allowed_root"'),
    re.compile(r"[A-Za-z]:\\\\"),
    re.compile(r"/mnt/[a-z]/"),
    re.compile(r"/home/[A-Za-z0-9_.-]+/"),
    re.compile(r"\b(sk-|hf_|ghp_)[A-Za-z0-9]{10,}"),
    re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
]

# ---- accelerator display names ----------------------------------------------
# Tokens not listed here are emitted verbatim rather than guessed at.
ACCELERATOR_DISPLAY = {
    "nvidia_geforce_rtx_4090": "NVIDIA GeForce RTX 4090",
    "nvidia_a100_40gb": "NVIDIA A100-40GB",
    "nvidia_a100_80gb": "NVIDIA A100-80GB",
    "nvidia_a10g": "NVIDIA A10G",
    "nvidia_l4": "NVIDIA L4",
    "nvidia_l40s": "NVIDIA L40S",
    "nvidia_h100": "NVIDIA H100",
    "nvidia_t4": "NVIDIA T4",
}


def accel_display(token):
    return ACCELERATOR_DISPLAY.get(token, token)


DATASETS = OrderedDict([
    ("D1", "quant_eval_behavioral_per_case_results"),
    ("D2", "quant_eval_throughput_telemetry"),
    ("D3", "quant_eval_golden_oracle_fixtures"),
    ("D4", "quant_eval_run_provenance"),
    ("D5", "quant_eval_paired_degradation_statistics"),
    ("D6", "quant_eval_family_pass_rates"),
    ("D7", "quant_eval_efficiency_and_footprint"),
])


# ============================================================ helpers
def log(msg=""):
    print(msg, flush=True)


def die(code, msg):
    log("")
    log("FAILED: " + msg)
    sys.exit(code)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def truthy(v):
    return str(v).strip().lower() in ("true", "1", "yes")


def dig(obj, *keys, default=None):
    """Nested get that tolerates a missing intermediate."""
    cur = obj
    for k in keys:
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur


def scalar(v, default=""):
    """Unwrap the {'status':..,'value':..} pattern used in decoding_conditions."""
    if isinstance(v, dict):
        if v.get("status") in ("unsupported", "not_applicable", "unset"):
            return default
        return v.get("value", default) if v.get("value") is not None else default
    return v if v is not None else default


def status_of(v, default=""):
    return v.get("status", default) if isinstance(v, dict) else default


def write_csv(path, fieldnames, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)
    return len(rows)


# ============================================================ discovery
def discover(runs_root, excludes):
    """Find every publication/ bundle and keep only publication-eligible runs."""
    found, skipped = [], []
    if not os.path.isdir(runs_root):
        die(1, "runs root does not exist: %s" % runs_root)

    for model_dir in sorted(os.listdir(runs_root)):
        mpath = os.path.join(runs_root, model_dir)
        if not os.path.isdir(mpath):
            continue
        for run_dir in sorted(os.listdir(mpath)):
            bundle = os.path.join(mpath, run_dir, "publication")
            manifest = os.path.join(bundle, "run_manifest.json")
            if not os.path.isfile(manifest):
                continue
            try:
                m = load_json(manifest)
            except Exception as exc:
                skipped.append((run_dir, "unreadable run_manifest.json: %s" % exc))
                continue

            run_id = m.get("run_id", run_dir)
            reasons = []
            if run_id in excludes:
                reasons.append("excluded by --exclude")
            if m.get("publication_status") != "eligible":
                reasons.append("publication_status=%r" % m.get("publication_status"))
            if dig(m, "release_validation", "status") != "passed":
                reasons.append("release_validation=%r"
                               % dig(m, "release_validation", "status"))
            blockers = dig(m, "publication_decision", "blockers", default=[])
            if blockers:
                reasons.append("blockers=%r" % (blockers,))

            if reasons:
                skipped.append((run_id, "; ".join(reasons)))
            else:
                found.append({"run_id": run_id, "dir": bundle,
                              "model_dir": model_dir, "manifest": m})

    found.sort(key=lambda b: b["run_id"])
    return found, skipped


RUN_DT = re.compile(r"(\d{8})_(\d{6})$")


def run_datetime(run_id, manifest):
    """Ordering key for supersession.

    Uses the YYYYMMDD_HHMMSS suffix of run_id, which is uniform across the
    corpus. `timestamp` is not used for ordering: it appears in at least two
    formats across harness versions and would sort incorrectly.
    """
    m = RUN_DT.search(run_id)
    if m:
        return m.group(1) + m.group(2)
    return str(manifest.get("timestamp", ""))


def load_explicit_bundles(paths, runs_root):
    """Build the bundle list from folders named on the command line.

    Each path may be the run folder (…/<RUN_ID>) or the bundle itself
    (…/<RUN_ID>/publication); either way ONLY the publication/ subdirectory is
    read. Relative paths resolve against --runs-root.
    Eligibility fields are reported as advisory only. The owner decides what is
    publishable; quant_eval's status fields do not. Naming a folder is the
    decision, and this function obeys it.
    """
    bundles, seen = [], set()
    for raw in paths:
        cand = raw if os.path.isabs(raw) else os.path.join(runs_root, raw)
        cand = os.path.normpath(cand)
        # publication/ is the ONLY directory this script may read. A run
        # folder also carries an internal run_manifest.json and other internal
        # artifacts; those are not client-facing and are never touched.
        bundle = (cand if os.path.basename(cand) == "publication"
                  else os.path.join(cand, "publication"))
        if not os.path.isdir(bundle):
            die(1, "no publication/ directory at %s — only the sanitized "
                   "publication bundle may be read" % bundle)
        for required in ("run_manifest.json", "checksums.json"):
            if not os.path.isfile(os.path.join(bundle, required)):
                die(1, "%s is missing %s — not a complete publication bundle"
                    % (bundle, required))
        if bundle in seen:
            log("  note: %s named more than once, using it once" % raw)
            continue
        seen.add(bundle)
        m = load_json(os.path.join(bundle, "run_manifest.json"))
        run_id = m.get("run_id", os.path.basename(os.path.dirname(bundle)))
        flags = []
        if m.get("publication_status") != "eligible":
            flags.append("publication_status=%r" % m.get("publication_status"))
        if dig(m, "release_validation", "status") != "passed":
            flags.append("release_validation=%r"
                         % dig(m, "release_validation", "status"))
        if dig(m, "publication_decision", "blockers", default=[]):
            flags.append("blockers present")
        log("  SELECT   %-52s %s" % (run_id,
                                     "" if not flags else
                                     "(advisory: " + "; ".join(flags) + ")"))
        bundles.append({"run_id": run_id, "dir": bundle,
                        "model_dir": os.path.basename(
                            os.path.dirname(os.path.dirname(bundle))),
                        "manifest": m})
    if not bundles:
        die(1, "no bundles named")
    bundles.sort(key=lambda b: b["run_id"])

    groups = {}
    for b in bundles:
        groups.setdefault(pair_key(b["manifest"]), []).append(b)
    for (model, quants), members in sorted(groups.items()):
        if len(members) > 1:
            log("")
            log("  NOTE: %d selected runs share the pair %s %s: %s"
                % (len(members), model, "+".join(quants),
                   ", ".join(b["run_id"] for b in members)))
            log("  They will be pooled as siblings. This is what you asked for; "
                "confirm it is intended.")
    return bundles


def parse_lineage(path):
    """Parse the calibration lineage declaration.

    Format:
        [PUBLISHED_RUN_ID]
        CALIBRATION_RUN_ID
        CALIBRATION_RUN_ID
    Blank lines and # comments ignored. Calibration runs are never published;
    this records that they existed and which published run they informed.
    """
    lineage, current = {}, None
    if not path:
        return lineage
    with open(path, encoding="utf-8") as f:
        for lineno, raw in enumerate(f, 1):
            line = raw.split("#", 1)[0].strip()
            if not line:
                continue
            if line.startswith("[") and line.endswith("]"):
                current = line[1:-1].strip()
                lineage.setdefault(current, [])
            elif current is None:
                die(1, "%s:%d: calibration run listed before any "
                       "[PUBLISHED_RUN_ID] header" % (path, lineno))
            else:
                lineage[current].append(line)
    return lineage


def parse_hardware_map(path):
    """Parse the accelerator declaration.

    Format, whitespace separated, one run per line:
        RUN_ID    BASELINE_ACCELERATOR    QUANTIZED_ACCELERATOR
    Blank lines and # comments ignored, including trailing comments.

    These values are DECLARED by the owner, not recorded by the harness: the
    publication bundles do not capture accelerator class. `hardware_matched_pair`
    is computed from the two tokens and is never declared, so it cannot disagree
    with them.
    """
    hw = {}
    if not path:
        return hw
    with open(path, encoding="utf-8") as f:
        for lineno, raw in enumerate(f, 1):
            line = raw.split("#", 1)[0].strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) != 3:
                die(1, "%s:%d: expected 3 whitespace-separated fields "
                       "(run_id baseline_accelerator quantized_accelerator), "
                       "got %d: %r" % (path, lineno, len(parts), line))
            rid, base, quant = parts
            if rid in hw:
                die(1, "%s:%d: run_id %s declared more than once"
                       % (path, lineno, rid))
            hw[rid] = {"baseline": base, "quantized": quant}
    return hw


def verify_hardware_map(bundles, hw, path):
    """Abort unless every selected run has a declared accelerator pair.

    This gate exists because its absence is exactly how corpus v1.0.0 shipped a
    misleading D7. A missing accelerator is not a warning condition.
    """
    if not path:
        die(1, "--hardware-map is required. The bundles do not record "
               "accelerator class, and D7 must not be built without it. "
               "See HARDWARE DECLARATION in the module docstring.")
    missing = [b["run_id"] for b in bundles if b["run_id"] not in hw]
    if missing:
        die(1, "hardware map %s is missing %d selected run(s):\n  %s"
               % (path, len(missing), "\n  ".join(missing)))
    selected = {b["run_id"] for b in bundles}
    extra = sorted(set(hw) - selected)
    for rid in extra:
        log("  NOTE: hardware map declares %s, which is not in this corpus" % rid)
    n_unmatched = 0
    for b in bundles:
        e = hw[b["run_id"]]
        matched = e["baseline"] == e["quantized"]
        if not matched:
            n_unmatched += 1
        log("  %-52s %s %s %s" %
            (b["run_id"], e["baseline"],
             "==" if matched else "!=", e["quantized"]))
    log("  %d run(s) declared, %d with lanes on different accelerators"
        % (len(bundles), n_unmatched))
    return n_unmatched


def pair_key(manifest):
    """Identity of the model-precision comparison a run performs."""
    model = dig(manifest, "license_provenance", "model_id",
                default=manifest.get("model_id", ""))
    quants = manifest.get("quant_types_requested") or []
    if isinstance(quants, dict):
        quants = list(quants.values())
    return (model, tuple(sorted(str(q) for q in quants)))


def resolve_selection(bundles, mode, allowlist):
    """Confirm the discovered set contains no duplicate model-precision pair.

    Eligibility is not selection. A run stays publication-eligible forever, and
    nothing in any manifest records which run the owner deemed publishable.
    This function never chooses between siblings; it aborts and asks.
    """
    if allowlist:
        keep = [b for b in bundles if b["run_id"] in allowlist]
        drop = [(b["run_id"], "not in allowlist") for b in bundles
                if b["run_id"] not in allowlist]
        missing = allowlist - {b["run_id"] for b in bundles}
        if missing:
            die(1, "allowlist names run(s) not found or not eligible: %s"
                % sorted(missing))
        return keep, drop

    groups = {}
    for b in bundles:
        groups.setdefault(pair_key(b["manifest"]), []).append(b)

    conflicts = {k: v for k, v in groups.items() if len(v) > 1}
    if not conflicts:
        return bundles, []

    log("")
    log("  MULTIPLE ELIGIBLE RUNS FOR THE SAME MODEL-PRECISION PAIR:")
    for (model, quants), members in sorted(conflicts.items()):
        log("    %s  %s" % (model, "+".join(quants)))
        for b in sorted(members, key=lambda x: x["run_id"]):
            log("        %s   run_datetime=%s"
                % (b["run_id"], run_datetime(b["run_id"], b["manifest"])))

    log("")
    log("  Pooling these as siblings would multiply-count the same comparison,")
    log("  and no field in a manifest records which run you deemed publishable.")
    log("  Name the runs explicitly:")
    log("    --bundles-file FILE          run/publication folder per line")
    log("    --bundle PATH                repeatable")
    log("    --allowlist FILE             run_id per line")
    die(1, "ambiguous run selection — refusing to guess")


# ============================================================ verification
CHECKSUM_META_KEYS = {"algorithm", "schema_version", "generated_at",
                      "generated_at_utc", "run_id", "version_tag", "note"}


def normalize_checksums(cks, run_id):
    """Return {filename: {"digest": str, "bytes": int|None}} from any of the
    checksums.json shapes emitted across harness versions.

    Shapes handled:
      {"files": {name: {"digest":.., "bytes":..}}}      schema_version 1
      {"files": {name: "<hex>"}}
      {name: {"digest"|"sha256":.., "bytes":..}}        flat, meta keys skipped
      {name: "<hex>"}                                   flat
    """
    hexdigest = re.compile(r"^[0-9a-fA-F]{64}$")

    def entry(v):
        if isinstance(v, str):
            return {"digest": v, "bytes": None} if hexdigest.match(v) else None
        if isinstance(v, dict):
            d = v.get("digest") or v.get("sha256") or v.get("hash")
            if isinstance(d, str) and hexdigest.match(d):
                return {"digest": d, "bytes": v.get("bytes", v.get("size"))}
        return None

    for container in ("files", "checksums", "artifacts"):
        if isinstance(cks.get(container), dict):
            out = {}
            for name, v in cks[container].items():
                e = entry(v)
                if e:
                    out[name] = e
            if out:
                return out, container

    out = {}
    for name, v in cks.items():
        if name in CHECKSUM_META_KEYS or not isinstance(name, str):
            continue
        e = entry(v)
        if e:
            out[name] = e
    if out:
        return out, "flat"

    die(2, "%s: unrecognized checksums.json shape; top-level keys are %s"
        % (run_id, sorted(cks.keys())))


def verify_checksums(bundles):
    """Every file listed in each bundle's checksums.json must match."""
    total = bad = 0
    shapes = Counter()
    for b in bundles:
        # Hard invariant: only the sanitized publication bundle is ever read.
        if os.path.basename(os.path.normpath(b["dir"])) != "publication":
            die(1, "refusing to read %s — only a publication/ directory may be "
                   "used as a source" % b["dir"])
        cpath = os.path.join(b["dir"], "checksums.json")
        if not os.path.isfile(cpath):
            die(2, "%s has no checksums.json" % b["run_id"])
        cks = load_json(cpath)
        files, shape = normalize_checksums(cks, b["run_id"])
        shapes[shape] += 1
        b["checksums"] = cks
        b["checksum_files"] = files
        for name, meta in files.items():
            fpath = os.path.join(b["dir"], name)
            total += 1
            if not os.path.isfile(fpath):
                bad += 1
                log("    MISSING  %s / %s" % (b["run_id"], name))
                continue
            digest = sha256_file(fpath)
            size = os.path.getsize(fpath)
            size_ok = (meta["bytes"] is None or size == meta["bytes"])
            if digest != meta["digest"] or not size_ok:
                bad += 1
                log("    MISMATCH %s / %s" % (b["run_id"], name))
    if len(shapes) > 1:
        log("  note: checksums.json shapes across bundles: %s"
            % dict(shapes))
    log("  checksums verified: %d/%d" % (total - bad, total))
    if bad:
        die(2, "%d checksum failures — refusing to build" % bad)
    return total


def verify_statistics(bundles):
    """Recompute every family x runner pass rate from the raw CSV."""
    checked = bad = 0
    for b in bundles:
        rollup = load_json(os.path.join(b["dir"], "rollup.json"))
        gates = load_json(os.path.join(b["dir"],
                                       "data_dictionary.json"))["headline_family_gates"]
        rows = list(csv.DictReader(open(os.path.join(b["dir"],
                                                     "comparison_results.csv"),
                                        newline="", encoding="utf-8")))
        b["rollup"] = rollup
        b["gates"] = gates
        for runner in rollup["by_runner_family"]:
            for fam in FAMILIES:
                sel = [r for r in rows
                       if r["family"] == fam and r["runner"] == runner]
                if not sel:
                    continue
                rate = sum(1 for r in sel
                           if all(truthy(r[c]) for c in gates[fam])) / len(sel)
                expected = rollup["by_runner_family"][runner][fam]["pass_rate"]
                checked += 1
                if abs(rate - expected) > 1e-9:
                    bad += 1
                    log("    STAT MISMATCH %s %s %s: rollup=%.9f recomputed=%.9f"
                        % (b["run_id"], runner, fam, expected, rate))
    log("  pass rates recomputed from raw CSV: %d/%d match" % (checked - bad, checked))
    if bad:
        die(2, "%d statistic mismatches — refusing to build" % bad)
    return checked


# ============================================================ D1
def decoding_index(manifest):
    """(runner -> decoding columns) for the D1 append and D4 flatten."""
    dc = manifest.get("decoding_conditions", {})
    temps = set()
    for fam_cfg in dc.get("families", {}).values():
        t = fam_cfg.get("temperature", dig(fam_cfg, "stage1", "temperature"))
        if t is not None:
            temps.add(t)
    temperature = temps.pop() if len(temps) == 1 else ";".join(
        str(t) for t in sorted(temps))

    out = {}
    for runner, cfg in dc.get("runner_effective_conditions", {}).items():
        out[runner] = {
            "decode_temperature": temperature,
            "decode_seed_status": status_of(cfg.get("seed"), ""),
            "decode_context_size": scalar(cfg.get("context_size")),
            "decode_top_p": scalar(cfg.get("top_p")),
            "decode_top_k": scalar(cfg.get("top_k")),
            "execution_substrate": ("modal_llama_cpp" if "modal" in runner.lower()
                                    else "local_llama_cpp"),
        }
    return out


APPENDED = ["decode_temperature", "decode_seed_status", "decode_context_size",
            "decode_top_p", "decode_top_k", "execution_substrate"]


def build_d1(bundles, outdir):
    header = None
    total = 0
    path = os.path.join(outdir, DATASETS["D1"] + ".csv")
    with open(path, "w", newline="", encoding="utf-8") as fout:
        writer = None
        for b in bundles:
            didx = decoding_index(b["manifest"])
            src = os.path.join(b["dir"], "comparison_results.csv")
            with open(src, newline="", encoding="utf-8") as fin:
                reader = csv.DictReader(fin)
                if header is None:
                    header = list(reader.fieldnames)
                    writer = csv.DictWriter(fout, fieldnames=header + APPENDED,
                                            extrasaction="ignore")
                    writer.writeheader()
                elif list(reader.fieldnames) != header:
                    die(2, "%s CSV header differs from the first bundle — "
                           "pooling requires an identical 140-column header"
                           % b["run_id"])
                for row in reader:
                    row.update(didx.get(row["runner"], {k: "" for k in APPENDED}))
                    writer.writerow(row)
                    total += 1
    return path, total, len(header) + len(APPENDED)


# ============================================================ D2
def build_d2(bundles, outdir):
    union, total = set(), 0
    records = []
    for b in bundles:
        src = os.path.join(b["dir"], "throughput_telemetry.jsonl")
        if not os.path.isfile(src):
            log("    note: %s has no throughput_telemetry.jsonl" % b["run_id"])
            continue
        with open(src, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                had_mnt = "max_new_tokens" in rec
                rec = {k: v for k, v in rec.items()
                       if k not in TELEMETRY_EXCLUDE_KEYS}
                rec["max_new_tokens_recorded"] = had_mnt
                rec.setdefault("run_id", b["run_id"])
                union.update(rec.keys())
                records.append(rec)
                total += 1

    path = os.path.join(outdir, DATASETS["D2"] + ".jsonl")
    ordered = sorted(union)
    with open(path, "w", encoding="utf-8") as f:
        for rec in records:
            # emit the full union schema; absent field -> explicit null
            f.write(json.dumps({k: rec.get(k, None) for k in ordered},
                               sort_keys=True) + "\n")
    return path, total, len(ordered), ordered


# ============================================================ D3
def canonical_fixture_hash(obj):
    """SHA-256 over the fixture object with `version` removed, sorted keys,
    compact separators. Publishing this lets a third party verify the
    equivalence claim instead of trusting it."""
    stripped = {k: v for k, v in obj.items() if k != "version"}
    blob = json.dumps(stripped, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def build_d3(bundles, outdir, lineage):
    """Publish the fixture set byte-for-byte, plus the version crosswalk.

    The file is COPIED, never re-serialized: a reviewer's first check is that
    the published fixture file hashes to a value the corpus records, and a
    re-serialized file cannot satisfy that.
    """
    import shutil
    classes, crosswalk = {}, []
    for b in bundles:
        fpath = os.path.join(b["dir"], "golden_oracle_fixtures.json")
        obj = load_json(fpath)
        file_sha = sha256_file(fpath)
        canon = canonical_fixture_hash(obj)
        classes.setdefault(canon, []).append(
            {"bundle": b, "path": fpath, "file_sha": file_sha,
             "label": obj.get("version", ""), "obj": obj})
        crosswalk.append({
            "run_id": b["run_id"],
            "fixtures_sha256": file_sha,
            "fixture_version_label": obj.get("version", ""),
            "fixture_schema_version": obj.get("fixture_schema_version", ""),
            "evaluation_contract_id": b["manifest"].get("evaluation_contract_id", ""),
            "fixture_split": b["manifest"].get("fixture_split", ""),
            "canonical_content_sha256": canon,
            "is_published_file": "false",
        })

    if len(classes) != 1:
        log("")
        log("  WARNING: fixtures are NOT content-equivalent across runs;")
        log("  %d distinct content classes. Publishing one file per class."
            % len(classes))

    written = []
    for canon, members in sorted(classes.items()):
        # Choose the file to publish: most common version label, then newest run.
        labels = Counter(m["label"] for m in members)
        top_label = labels.most_common(1)[0][0]
        pick = max((m for m in members if m["label"] == top_label),
                   key=lambda m: run_datetime(m["bundle"]["run_id"],
                                              m["bundle"]["manifest"]))
        name = ("golden_oracle_fixtures.json" if len(classes) == 1
                else "golden_oracle_fixtures__%s.json" % canon[:12])
        out = os.path.join(outdir, name)
        shutil.copyfile(pick["path"], out)          # byte-exact
        assert sha256_file(out) == pick["file_sha"]
        for row in crosswalk:
            if (row["canonical_content_sha256"] == canon
                    and row["fixtures_sha256"] == pick["file_sha"]):
                row["is_published_file"] = "true"
        cases = sum(len(v) for k, v in pick["obj"].items()
                    if k.endswith("_cases") and hasattr(v, "__len__"))
        written.append({"path": out, "cases": cases, "canonical": canon,
                        "file_sha": pick["file_sha"], "label": pick["label"],
                        "from_run": pick["bundle"]["run_id"],
                        "labels_in_class": dict(labels)})

    cw_path = os.path.join(outdir, "fixture_version_crosswalk.csv")
    write_csv(cw_path, ["run_id", "fixtures_sha256", "fixture_version_label",
                        "fixture_schema_version", "evaluation_contract_id",
                        "fixture_split", "canonical_content_sha256",
                        "is_published_file"], crosswalk)

    # ---- ISSUE 3/4: calibration lineage, declared by the owner ----
    lin_path = os.path.join(outdir, "calibration_lineage.csv")
    lin_rows = []
    for b in bundles:
        for cal in lineage.get(b["run_id"], []):
            lin_rows.append({"published_run_id": b["run_id"],
                             "calibration_run_id": cal,
                             "role": "internal_calibration_evidence",
                             "published": "false"})
    write_csv(lin_path, ["published_run_id", "calibration_run_id", "role",
                         "published"], lin_rows)

    return written, cw_path, lin_path, len(crosswalk), len(lin_rows)


# ============================================================ D4
D4_FIELDS = [
    "run_id", "model_id", "canonical_upstream_model_id", "adapter_id",
    "adapter_reason", "version_tag", "evaluation_contract_id", "scoring_contract",
    "prompt_contract", "fixture_construction_contract", "fixtures_sha256",
    "fixture_version_label", "fixture_split", "profile", "run_purpose",
    "promotion_status", "publication_status", "release_validation_status",
    "seed", "fixture_generation_seed", "timestamp",
    "baseline_quant_type", "quantized_quant_type", "baseline_runner",
    "quantized_runner", "execution_substrate",
    "decode_temperature", "decode_seed_status", "decode_context_size",
    "decode_top_p", "decode_top_k",
    "license", "spdx_license_id", "commercial_use_status",
    "baseline_artifact_sha256", "baseline_artifact_bytes",
    "quantized_artifact_sha256", "quantized_artifact_bytes",
    "upstream_revision", "upstream_revision_status", "rows",
]


def build_d4(bundles, outdir, fixture_labels):
    rows = []
    for b in bundles:
        m, rollup = b["manifest"], b["rollup"]
        lp = m.get("license_provenance", {})
        ec = m.get("evaluation_contract", {})
        rc = dig(rollup, "efficiency", "runtime_comparison", default={})
        foot = dig(rollup, "efficiency", "artifact_footprint", default=[{}])[0]
        didx = decoding_index(m)

        base_runner = rc.get("baseline_runner", "")
        quant_runner = rc.get("quantized_runner", "")
        dec = didx.get(quant_runner) or didx.get(base_runner) or {}

        # artifact_identity carries `path`, which is a modal:// URI on Modal runs.
        # It is NEVER selected. Only sha256/bytes/kind are taken.
        arts = {a.get("quant_type", a.get("kind", "")): a
                for a in lp.get("artifact_identity", [])}
        base_art = arts.get(foot.get("baseline_kind"), {})
        quant_art = arts.get(foot.get("quant_type"), {})

        rows.append({
            "run_id": b["run_id"],
            "model_id": lp.get("model_id", m.get("model_id", "")),
            "canonical_upstream_model_id": lp.get("canonical_upstream_model_id", ""),
            "adapter_id": m.get("adapter_id", ""),
            "adapter_reason": m.get("adapter_reason", ""),
            "version_tag": m.get("version_tag", ""),
            "evaluation_contract_id": m.get("evaluation_contract_id", ""),
            "scoring_contract": ec.get("scoring_contract", ""),
            "prompt_contract": ec.get("prompt_contract", ""),
            "fixture_construction_contract": ec.get("fixture_construction_contract", ""),
            "fixtures_sha256": rollup.get("fixtures_sha256", ""),
            "fixture_version_label": fixture_labels.get(b["run_id"], ""),
            "fixture_split": m.get("fixture_split", ""),
            "profile": m.get("profile", ""),
            "run_purpose": m.get("run_purpose", ""),
            "promotion_status": m.get("promotion_status", ""),
            "publication_status": m.get("publication_status", ""),
            "release_validation_status": dig(m, "release_validation", "status",
                                             default=""),
            "seed": m.get("seed", ""),
            "fixture_generation_seed": m.get("fixture_generation_seed", ""),
            "timestamp": m.get("timestamp", ""),
            "baseline_quant_type": foot.get("baseline_kind", ""),
            "quantized_quant_type": foot.get("quant_type", ""),
            "baseline_runner": base_runner,
            "quantized_runner": quant_runner,
            "execution_substrate": dec.get("execution_substrate", ""),
            "decode_temperature": dec.get("decode_temperature", ""),
            "decode_seed_status": dec.get("decode_seed_status", ""),
            "decode_context_size": dec.get("decode_context_size", ""),
            "decode_top_p": dec.get("decode_top_p", ""),
            "decode_top_k": dec.get("decode_top_k", ""),
            "license": lp.get("license", ""),
            "spdx_license_id": lp.get("spdx_license_id", ""),
            "commercial_use_status": lp.get("commercial_use_status", ""),
            "baseline_artifact_sha256": base_art.get("sha256", ""),
            "baseline_artifact_bytes": base_art.get("bytes", ""),
            "quantized_artifact_sha256": quant_art.get("sha256", ""),
            "quantized_artifact_bytes": quant_art.get("bytes", ""),
            "upstream_revision": dig(lp, "weight_lineage", "upstream_revision",
                                     default=""),
            "upstream_revision_status": dig(lp, "weight_lineage",
                                            "upstream_revision_status", default=""),
            "rows": dig(m, "release_validation", "rows", default=""),
        })
    path = os.path.join(outdir, DATASETS["D4"] + ".csv")
    return path, write_csv(path, D4_FIELDS, rows), len(D4_FIELDS)


# ============================================================ D5
D5_FIELDS = [
    "run_id", "model_id", "baseline_quant_type", "quantized_quant_type", "family",
    "runner_a", "runner_b", "paired_n", "both_pass", "both_fail",
    "runner_a_only_pass", "runner_b_only_pass", "disagreements",
    "disagreement_rate", "pass_rate_delta_runner_b_minus_runner_a",
    "delta_ci_low", "delta_ci_high", "delta_ci_level", "delta_ci_method",
    "mcnemar_p_value", "mcnemar_discordant_pairs", "mcnemar_alternative",
    "discriminating", "cluster_adjusted_method",
    "cluster_adjusted_effective_paired_n", "cluster_adjusted_delta",
    "cluster_adjusted_delta_ci_low", "cluster_adjusted_delta_ci_high",
]


def build_d5(bundles, outdir):
    rows = []
    for b in bundles:
        rollup = b["rollup"]
        foot = dig(rollup, "efficiency", "artifact_footprint", default=[{}])[0]
        model_id = dig(rollup, "license_provenance", "model_id",
                       default=b["manifest"].get("model_id", ""))
        for fam in FAMILIES:
            P = dig(rollup, "paired_runner_comparison", fam)
            if not P:
                continue
            ci = P.get("pass_rate_delta_ci", {})
            mc = P.get("mcnemar_exact", {})
            ca = P.get("cluster_adjusted") or {}
            cci = ca.get("delta_ci", {}) if isinstance(ca, dict) else {}
            rows.append({
                "run_id": b["run_id"], "model_id": model_id,
                "baseline_quant_type": foot.get("baseline_kind", ""),
                "quantized_quant_type": foot.get("quant_type", ""),
                "family": fam,
                "runner_a": P.get("runner_a", ""), "runner_b": P.get("runner_b", ""),
                "paired_n": P.get("paired_n", ""),
                "both_pass": P.get("both_pass", ""),
                "both_fail": P.get("both_fail", ""),
                "runner_a_only_pass": P.get("runner_a_only_pass", ""),
                "runner_b_only_pass": P.get("runner_b_only_pass", ""),
                "disagreements": P.get("disagreements", ""),
                "disagreement_rate": P.get("disagreement_rate", ""),
                "pass_rate_delta_runner_b_minus_runner_a":
                    P.get("pass_rate_delta_runner_b_minus_runner_a", ""),
                "delta_ci_low": ci.get("low", ""), "delta_ci_high": ci.get("high", ""),
                "delta_ci_level": ci.get("level", ""),
                "delta_ci_method": ci.get("method", ""),
                "mcnemar_p_value": mc.get("p_value", ""),
                "mcnemar_discordant_pairs": mc.get("discordant_pairs", ""),
                "mcnemar_alternative": mc.get("alternative", ""),
                "discriminating": P.get("discriminating", ""),
                "cluster_adjusted_method": ca.get("method", ""),
                "cluster_adjusted_effective_paired_n":
                    ca.get("effective_paired_n", ""),
                "cluster_adjusted_delta":
                    ca.get("delta_runner_b_minus_runner_a", ""),
                "cluster_adjusted_delta_ci_low": cci.get("low", ""),
                "cluster_adjusted_delta_ci_high": cci.get("high", ""),
            })
    path = os.path.join(outdir, DATASETS["D5"] + ".csv")
    return path, write_csv(path, D5_FIELDS, rows), len(D5_FIELDS)


# ============================================================ D6
D6_FIELDS = ["run_id", "model_id", "runner", "quant_type", "family", "role",
             "n", "pass_n", "pass_count", "pass_rate", "pass_rate_ci_low",
             "pass_rate_ci_high", "pass_rate_ci_level", "pass_rate_ci_method",
             "gating_signals", "metric_status"]


def build_d6(bundles, outdir):
    rows = []
    for b in bundles:
        rollup, gates = b["rollup"], b["gates"]
        model_id = dig(rollup, "license_provenance", "model_id",
                       default=b["manifest"].get("model_id", ""))
        foot = dig(rollup, "efficiency", "artifact_footprint", default=[{}])[0]
        rc = dig(rollup, "efficiency", "runtime_comparison", default={})
        qmap = {rc.get("baseline_runner", ""): foot.get("baseline_kind", ""),
                rc.get("quantized_runner", ""): foot.get("quant_type", "")}
        for runner, fams in rollup["by_runner_family"].items():
            for fam in FAMILIES:
                F = fams.get(fam)
                if not F:
                    continue
                ci = F.get("pass_rate_ci", {})
                rows.append({
                    "run_id": b["run_id"], "model_id": model_id,
                    "runner": runner, "quant_type": qmap.get(runner, ""),
                    "family": fam, "role": F.get("role", ""),
                    "n": F.get("n", ""), "pass_n": F.get("pass_n", ""),
                    "pass_count": F.get("pass_count", ""),
                    "pass_rate": F.get("pass_rate", ""),
                    "pass_rate_ci_low": ci.get("low", ""),
                    "pass_rate_ci_high": ci.get("high", ""),
                    "pass_rate_ci_level": ci.get("level", ""),
                    "pass_rate_ci_method": ci.get("method", ""),
                    "gating_signals": " AND ".join(gates.get(fam, [])),
                    "metric_status": F.get("metric_status", ""),
                })
    path = os.path.join(outdir, DATASETS["D6"] + ".csv")
    return path, write_csv(path, D6_FIELDS, rows), len(D6_FIELDS)


# ============================================================ D7
D7_FIELDS = ["run_id", "model_id", "baseline_kind", "quant_type",
             "baseline_bytes", "quantized_bytes", "compression_ratio",
             "size_reduction_fraction", "measurement_scope", "excludes",
             "baseline_runner", "quantized_runner", "execution_substrate",
             "baseline_accelerator", "quantized_accelerator",
             "hardware_matched_pair",
             "baseline_tokens_per_second", "quantized_tokens_per_second",
             "observed_wall_time_ratio", "wall_time_direction",
             "throughput_ratio", "token_volume_cost_proxy_ratio",
             "monetary_cost_ratio_status", "artifact_footprint_status",
             "hardware_backend_scope"]


SCOPE_MATCHED = ("both lanes executed on {hw}; "
                 "ratio is a precision comparison")
SCOPE_UNMATCHED = ("baseline executed on {b}, quantized executed on {q}; "
                   "ratio reflects an accelerator change and is not a "
                   "precision comparison")


def build_d7(bundles, outdir, hw_map):
    rows = []
    for b in bundles:
        rollup = b["rollup"]
        eff = rollup.get("efficiency", {})
        foot = (eff.get("artifact_footprint") or [{}])[0]
        rc = eff.get("runtime_comparison", {})
        hm = rc.get("headline_runtime_metric", {})
        val = hm.get("value", "")
        direction = hm.get("direction") or (
            "speedup" if isinstance(val, (int, float)) and val >= 1.0
            else "slowdown" if isinstance(val, (int, float)) else "")
        tv = rc.get("token_volume_cost_proxy", {})
        mc = rc.get("monetary_cost_ratio", {})
        quant_runner = rc.get("quantized_runner", "")
        # Declared, not harness-recorded; verify_hardware_map has already
        # guaranteed the entry exists for every selected run.
        hw_entry = hw_map[b["run_id"]]
        hw_base, hw_quant = hw_entry["baseline"], hw_entry["quantized"]
        hw_matched = hw_base == hw_quant
        scope = (SCOPE_MATCHED.format(hw=accel_display(hw_base)) if hw_matched
                 else SCOPE_UNMATCHED.format(b=accel_display(hw_base),
                                             q=accel_display(hw_quant)))
        rows.append({
            "run_id": b["run_id"],
            "model_id": dig(rollup, "license_provenance", "model_id", default=""),
            "baseline_kind": foot.get("baseline_kind", ""),
            "quant_type": foot.get("quant_type", ""),
            "baseline_bytes": foot.get("baseline_bytes", ""),
            "quantized_bytes": foot.get("quantized_bytes", ""),
            "compression_ratio": foot.get("compression_ratio", ""),
            "size_reduction_fraction": foot.get("size_reduction_fraction", ""),
            "measurement_scope": foot.get("measurement_scope", ""),
            "excludes": ";".join(foot.get("excludes", [])),
            "baseline_runner": rc.get("baseline_runner", ""),
            "quantized_runner": quant_runner,
            "execution_substrate": ("modal_llama_cpp" if "modal" in quant_runner.lower()
                                    else "local_llama_cpp"),
            "baseline_accelerator": hw_base,
            "quantized_accelerator": hw_quant,
            "hardware_matched_pair": "true" if hw_matched else "false",
            "baseline_tokens_per_second": rc.get("baseline_tokens_per_second", ""),
            "quantized_tokens_per_second": rc.get("quantized_tokens_per_second", ""),
            "observed_wall_time_ratio": val,
            "wall_time_direction": direction,
            "throughput_ratio": rc.get("throughput_ratio_quantized_over_baseline", ""),
            "token_volume_cost_proxy_ratio": (tv.get("value", "")
                                              if isinstance(tv, dict) else tv),
            "monetary_cost_ratio_status": (mc.get("status", "")
                                           if isinstance(mc, dict) else mc),
            "artifact_footprint_status": eff.get("artifact_footprint_status", ""),
            # Replaces the bundle's own string, which said "the recorded
            # hardware" while recording none. That phrasing is what made the
            # v1.0.0 omission invisible.
            "hardware_backend_scope": scope,
        })
    path = os.path.join(outdir, DATASETS["D7"] + ".csv")
    return path, write_csv(path, D7_FIELDS, rows), len(D7_FIELDS)


# ============================================================ provenance
def build_provenance(bundles, outdir):
    """Republish every source checksums.json verbatim — the integrity chain."""
    payload = {
        "note": ("Verbatim source-bundle digests. No bundle file was modified. "
                 "Sanitization is by field selection during derivation."),
        "algorithm": "sha256",
        "bundles": {b["run_id"]: b["checksums"] for b in bundles},
    }
    path = os.path.join(outdir, "source_bundle_checksums.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, sort_keys=True)
    return path


def build_data_dictionary(bundles, outdir):
    """Build the published dictionary as a true UNION across bundles.

    Excluded telemetry keys are dropped. Fields added by derivation are
    documented explicitly so the published dictionary describes the published
    files, not any single source bundle.
    """
    union, order, notes = {}, {}, []
    meta = None
    for b in bundles:
        d = load_json(os.path.join(b["dir"], "data_dictionary.json"))
        if meta is None:
            meta = {k: v for k, v in d.items() if k != "datasets"}
        for ds, fields in d["datasets"].items():
            union.setdefault(ds, {})
            order.setdefault(ds, [])
            for f in fields:
                name = f["name"]
                if ds == "throughput_telemetry.jsonl" and name in TELEMETRY_EXCLUDE_KEYS:
                    continue
                if name not in union[ds]:
                    union[ds][name] = dict(f)
                    union[ds][name]["first_documented_in_run"] = b["run_id"]
                    order[ds].append(name)
                    if b is not bundles[0]:
                        notes.append((b["run_id"], ds, name))

    # Spec §12 (v3): authoritative applicability string for this field.
    fixed = union.get("comparison_results.csv", {}).get(
        "best_of_k_selected_output_raw")
    if fixed:
        fixed["applicability"] = ("json_multistep_rows_where_"
                                  "best_of_k_k_is_greater_than_1")

    # Fields created by derivation.
    for name, desc in [
        ("decode_temperature", "Sampling temperature for this run, from "
         "run_manifest decoding_conditions.families."),
        ("decode_seed_status", "'applied' where the backend honoured a seed; "
         "'unsupported' where the deployed method signature accepts none."),
        ("decode_context_size", "Effective context size for this runner."),
        ("decode_top_p", "Effective top_p for this runner."),
        ("decode_top_k", "Effective top_k. Empty means backend_default_unpinned: "
         "the parameter was not passed and the backend default applies. This is "
         "not a missing measurement."),
        ("execution_substrate", "local_llama_cpp or modal_llama_cpp."),
    ]:
        union.setdefault("comparison_results.csv", {})[name] = {
            "name": name, "applicability": "all_rows",
            "data_type": "string", "evidence_role": "run_condition",
            "empty_value_meaning": "see description",
            "gate_membership": [], "description": desc,
            "added_by": "derivation",
        }
        order["comparison_results.csv"].append(name)

    union.setdefault("throughput_telemetry.jsonl", {})["max_new_tokens_recorded"] = {
        "name": "max_new_tokens_recorded", "applicability": "all_records",
        "data_type": "boolean", "evidence_role": "provenance",
        "empty_value_meaning": "not_applicable", "gate_membership": [],
        "description": ("true where the source run emitted max_new_tokens; false "
                        "where the run predates the field. Distinguishes 'not "
                        "recorded in this run' from 'recorded as empty', which a "
                        "bare null cannot express."),
        "added_by": "derivation",
    }
    order["throughput_telemetry.jsonl"].append("max_new_tokens_recorded")

    out = dict(meta or {})
    out["datasets"] = {ds: [union[ds][n] for n in order[ds]] for ds in union}
    out["_derived_note"] = (
        "Union dictionary for the pooled corpus, built by " + BUILDER_VERSION +
        ". Telemetry keys " + ", ".join(sorted(TELEMETRY_EXCLUDE_KEYS)) +
        " are excluded by field selection and are absent from both the data and "
        "this dictionary. Fields marked added_by=derivation do not exist in any "
        "source bundle.")
    path = os.path.join(outdir, "data_dictionary.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, sort_keys=True)
    counts = {ds: len(order[ds]) for ds in order}
    return path, counts, notes


# ============================================================ packaging

DATASET_FILES = {
    "D1": {"data": ["quant_eval_behavioral_per_case_results.csv"],
           "extra": ["data_dictionary.json", "source_bundle_checksums.json"]},
    "D2": {"data": ["quant_eval_throughput_telemetry.jsonl"],
           "extra": ["data_dictionary.json", "source_bundle_checksums.json"]},
    "D3": {"data": ["golden_oracle_fixtures.json",
                    "fixture_version_crosswalk.csv"],
           "extra": ["source_bundle_checksums.json"]},
    "D4": {"data": ["quant_eval_run_provenance.csv",
                    "calibration_lineage.csv"],
           "extra": ["source_bundle_checksums.json"]},
    "D5": {"data": ["quant_eval_paired_degradation_statistics.csv"],
           "extra": ["source_bundle_checksums.json"]},
    "D6": {"data": ["quant_eval_family_pass_rates.csv"],
           "extra": ["source_bundle_checksums.json"]},
    "D7": {"data": ["quant_eval_efficiency_and_footprint.csv"],
           "extra": ["source_bundle_checksums.json"]},
}

DATASET_DESC = {
    "D0": ("Public Corpus",
           "The corpus-level record: overview, licence, citation metadata, and "
           "the build manifest listing a SHA-256 and byte count for every "
           "published file across all seven datasets. Deposit this record to "
           "obtain a single citable identifier for the corpus as a whole; the "
           "seven datasets each declare `isPartOf` this record."),
    "D1": ("Per-case behavioral results",
           "One row per evaluation case per runner: the raw model output, every "
           "scored signal, per-case timing, expected/got pairs, the oracle "
           "trace, the fuzz audit envelope, and the decoding conditions under "
           "which the row was produced. Every aggregate statistic published in "
           "the other datasets is recomputable from this file."),
    "D2": ("Throughput telemetry",
           "One record per generation call across all published runs, pooled "
           "into a single union schema. Carries token counts, timing, and the "
           "token-count source per call."),
    "D3": ("Golden oracle fixtures",
           "The locked evaluation fixture set — 1,600 cases across eight agent "
           "task families with their deterministic ground truth — plus the "
           "crosswalk mapping every run's recorded fixture hash and version "
           "label to the published file."),
    "D4": ("Run provenance",
           "One row per published run: model identity, contract identifiers, "
           "fixture hash, decoding conditions, licence, and the SHA-256 and "
           "byte size of both weight artifacts. Accompanied by the calibration "
           "lineage that informed each published run."),
    "D5": ("Paired degradation statistics",
           "One row per run per task family: the paired pass-rate difference "
           "with a 95% confidence interval, the two-sided exact McNemar test, "
           "the full discordance breakdown, and a semantic-cluster-adjusted "
           "delta and interval."),
    "D6": ("Family pass rates",
           "One row per run per runner per task family: pass count, pass rate, "
           "Wilson confidence interval, and the exact gating signal "
           "conjunction used to compute it."),
    "D7": ("Efficiency and footprint",
           "One row per published run: stored weight artifact bytes before and "
           "after quantization, compression ratio, observed evaluation "
           "wall-time ratio with an explicit direction label, and token "
           "throughput."),
}

# The one tabular file HF's viewer should load. Everything else in a folder is
# documentation or provenance and must not be auto-discovered as a data split.
VIEWER_FILE = {
    "D1": "quant_eval_behavioral_per_case_results.csv",
    "D2": "quant_eval_throughput_telemetry.jsonl",
    "D3": "fixture_version_crosswalk.csv",
    "D4": "quant_eval_run_provenance.csv",
    "D5": "quant_eval_paired_degradation_statistics.csv",
    "D6": "quant_eval_family_pass_rates.csv",
    "D7": "quant_eval_efficiency_and_footprint.csv",
}

# Figures placed on dataset cards. PNG only: HF and Kaggle Markdown do not
# render SVG dependably. Copied into the folder so each repo is self-contained.
FIGURES = {
    "D1": [("fig2_precision_cliff_cost_benefit.png",
            "Scatter plot of storage saved versus F16 against the number of "
            "task families significantly degraded, for three quantization "
            "precisions of Mistral-Nemo-Instruct-2407. Q8_0 and Q5_K_M sit at "
            "zero families degraded; Q4_K_M jumps to six families degraded for "
            "a small additional storage saving.",
            "**Storage saving against measured behavioral cost.** Q5_K_M banks "
            "64.4% of the F16 footprint with zero families significantly "
            "degraded; Q4_K_M adds 5.1 percentage points of saving and breaks "
            "six of eight families. The dashed line joins measured points and "
            "is not a fitted model. Every value is recomputable from this "
            "dataset together with the efficiency and footprint dataset (D7).")],
    "D5": [("fig1_precision_curve_mistral_nemo.png",
            "Dot-and-whisker plot of paired pass-rate differences for "
            "Mistral-Nemo-Instruct-2407 across eight agent task families at "
            "three quantization precisions. Q4_K_M shows large negative "
            "differences in six families; Q5_K_M and Q8_0 cluster at zero with "
            "no significant differences.",
            "**Paired pass-rate difference (quantized minus full weight) with "
            "95% confidence intervals**, Mistral-Nemo-Instruct-2407, n = 200 "
            "paired cases per family. Solid markers indicate two-sided exact "
            "McNemar p < 0.05. Families significant: Q4_K_M 6 of 8; Q5_K_M 0 "
            "of 8; Q8_0 0 of 8. The shape is a discontinuity, not a gradient."),
           ("fig3_qwen_scale_ladder.png",
            "Dot-and-whisker plot of paired pass-rate differences at Q4_K_M "
            "for three Qwen2.5 models at 7B, 14B-1M, and 32B parameters across "
            "eight agent task families. The 7B and 14B-1M models each show four "
            "significant differences; the 32B model shows none.",
            "**Paired pass-rate difference at Q4_K_M versus each model's own "
            "F16 baseline**, n = 200 paired cases per family. Solid markers "
            "indicate McNemar p < 0.05. **CONFOUNDED:** 7B ran on local "
            "llama.cpp with a fixed seed; 14B-1M and 32B ran on Modal, which "
            "records seed status `unsupported`. Scale and substrate are not "
            "separated by this corpus, and this figure must not be read as a "
            "clean parameter-scale effect.")],
    "D7": [("fig4_wall_time_ratio_six_pairs.png",
            "Horizontal bar chart of observed evaluation wall-time ratios for "
            "six model-precision pairs. Four local llama.cpp pairs exceed "
            "parity at 2.704, 2.564, 1.985, and 1.714 times; two Modal pairs "
            "fall below parity at 0.961 and 0.854 times, shown hatched.",
            "**Observed evaluation wall-time ratio (full weight divided by "
            "quantized)** for all six published pairs. Hatched bars fall below "
            "parity — the quantized run was slower. Observed harness wall time "
            "on the recorded hardware and backends; not a controlled "
            "throughput benchmark and not a general claim about quantization "
            "performance at any precision on any hardware.")],
}

# Kaggle renders this beneath the title as its own indexed field.
KAGGLE_SUBTITLE = {
    "D0": "Behavioral evaluation of quantized LLMs across eight agent task families",
    "D1": "19,200 per-case outcomes from paired full-weight vs quantized LLM evaluations",
    "D2": "27,370 generation-call timing records across six paired precision comparisons",
    "D3": "1,600 locked agent-task fixtures with deterministic ground truth",
    "D4": "Run provenance for six paired full-weight vs quantized model evaluations",
    "D5": "Paired McNemar tests of quantization degradation across eight task families",
    "D6": "Per-family pass rates with Wilson intervals for six model-precision pairs",
    "D7": "Compression ratios and measured wall-time ratios for six quantized model pairs",
}

HF_TAGS = ["quantization", "large-language-models", "gguf", "agent-evaluation",
           "tool-calling", "behavioral-evaluation", "mcnemar", "llama-cpp",
           "model-evaluation", "reproducibility"]

LICENSE_TEXT = """quant_eval Public Corpus
Copyright (c) 2026 PBH Applied Systems, LLC

This work is licensed under the Creative Commons Attribution 4.0 International
License (CC BY 4.0).

SPDX-License-Identifier: CC-BY-4.0

You are free to:
  - Share:  copy and redistribute the material in any medium or format
  - Adapt:  remix, transform, and build upon the material
for any purpose, including commercially.

Under the following term:
  - Attribution: You must give appropriate credit, provide a link to the
    licence, and indicate if changes were made. You may do so in any reasonable
    manner, but not in any way that suggests the licensor endorses you or your
    use.

No additional restrictions: you may not apply legal terms or technological
measures that legally restrict others from doing anything the licence permits.

The full legal code is available at:
  https://creativecommons.org/licenses/by/4.0/legalcode

SUGGESTED ATTRIBUTION
  Hill, Patrick. "{title}". PBH Applied Systems, LLC, 2026.
  Licensed under CC BY 4.0.{doi_line}

NOTE ON THE EVALUATED MODELS
  This corpus describes the behaviour of third-party language models. It does
  not redistribute model weights. Each evaluated model remains under its own
  licence, recorded per run in the run provenance dataset.
"""


def corpus_readme(stats, runs, concept, version, dataset_stats):
    """Root README for the corpus as a whole."""
    L = []
    A = L.append
    A("# quant_eval Public Corpus")
    A("")
    A("A per-case behavioral evaluation of full-weight and quantized large "
      "language models across eight agent-relevant task families, with paired "
      "statistical testing and published ground truth.")
    A("")
    A("Seven datasets, each deposited and citable independently:")
    A("")
    A("| | Dataset | Contents | Size |")
    A("|---|---|---|---:|")
    for did in sorted(DATASET_FILES):
        title, _ = DATASET_DESC[did]
        st = dataset_stats.get(did, {})
        size = st.get("size_label") or (
            "%s rows" % _fmt_int(st["rows"]) if st.get("rows") else "—")
        A("| %s | `%s` | %s | %s |" % (did, DATASETS[did], title, size))
    A("")
    A("## Scope")
    A("")
    A("| Run | Model | Baseline | Quantized | Substrate |")
    A("|---|---|---|---|---|")
    for r in runs:
        A("| `%s` | %s | %s | %s | %s |"
          % (r["run_id"], r["model_id"], r["baseline_quant_type"],
             r["quantized_quant_type"],
             "Modal" if r["execution_substrate"].startswith("modal") else "local"))
    A("")
    A("## Why it exists")
    A("")
    A("Quantized model cards state a compression ratio and stop. They do not "
      "say what the quantized model stops being able to do. This corpus "
      "measures that directly: identical fixtures, identical cases, a paired "
      "test per task family, and every per-case row published so the "
      "aggregates can be recomputed by anyone.")
    A("")
    A("## Verification")
    A("")
    A("- All %d source-bundle file digests verified before the build."
      % stats["n_checksums"])
    A("- All %d family x runner pass rates independently recomputed from the "
      "raw per-case rows and matched to the harness rollups." % stats["n_stats"])
    A("- Every published output carries a SHA-256 in `build_manifest.json`.")
    A("- **The paired degradation statistics (D5) and family pass rates (D6) "
      "datasets are recomputable in full from the per-case results dataset "
      "(D1)** using the gate definitions in `data_dictionary.json`.")
    A("- Run provenance (D4), efficiency and footprint (D7), and throughput "
      "telemetry (D2) are **not** derived from per-case rows. They are "
      "harness-recorded at run time and carried through unchanged, so they are "
      "traceable through the bundle digests rather than recomputable from D1.")
    A("")
    A("## Licence")
    A("")
    A("CC BY 4.0. Commercial use permitted; attribution required. No model "
      "weights are redistributed; each evaluated model remains under its own "
      "licence, recorded per run.")
    A("")
    cite = "Hill, Patrick. \"quant_eval Public Corpus\". PBH Applied Systems, " \
           "LLC, 2026. Licensed under CC BY 4.0."
    if concept:
        cite += "\n\nDOI (all versions): %s" % concept
    if version:
        cite += "\n\nDOI (this version): %s" % version
    A(cite)
    A("")
    return "\n".join(L) + "\n"


def normalize_doi(entry):
    """Accept either a bare string or {"concept":..., "version":...}.

    A bare string is treated as the CONCEPT DOI, because that is the one a
    citing author should use: it always resolves to the latest version.
    Returns (concept, version), either of which may be "".
    """
    if not entry:
        return "", ""
    if isinstance(entry, str):
        return entry, ""
    if isinstance(entry, dict):
        return (entry.get("concept", "") or "", entry.get("version", "") or "")
    die(1, "--doi-map entries must be a string or an object with "
           "'concept' and/or 'version'; got %r" % (entry,))


def doi_note(concept, version):
    """One-line plain-text attribution suffix for LICENSE files."""
    bits = []
    if concept:
        bits.append("DOI (all versions): %s" % concept)
    if version:
        bits.append("DOI (this version): %s" % version)
    return ("\n  " + "\n  ".join(bits)) if bits else ""


def citation_cff(title, concept, version):
    L = ["cff-version: 1.2.0",
         "message: If you use this dataset, please cite it.",
         "type: dataset",
         "title: >-",
         "  quant_eval %s" % title,
         "authors:",
         "  - family-names: Hill",
         "    given-names: Patrick",
         "    affiliation: PBH Applied Systems, LLC",
         "license: CC-BY-4.0",
         "year: 2026"]
    # `doi` is the concept DOI: it is what a citing author should resolve.
    if concept:
        L.append("doi: %s" % concept)
    elif version:
        L.append("doi: %s" % version)
    ids = []
    if concept:
        ids += ["  - type: doi", "    value: %s" % concept,
                "    description: Concept DOI, always resolves to the latest "
                "version"]
    if version:
        ids += ["  - type: doi", "    value: %s" % version,
                "    description: Version DOI, frozen to this exact deposit"]
    if ids:
        L += ["identifiers:"] + ids
    return "\n".join(L) + "\n"


def _fmt_int(n):
    return "{:,}".format(n)


KAGGLE_TITLE_MAX = 50
KAGGLE_SUBTITLE_MIN = 20
KAGGLE_SUBTITLE_MAX = 80


def kaggle_metadata(did, name, concept):
    """Kaggle dataset-metadata.json — the file `kaggle datasets create -p .`
    reads. Title carries the canonical name; subtitle is a separate indexed
    field rendered beneath it."""
    title, _ = DATASET_DESC[did]
    full_title = "quant_eval %s" % title
    sub = KAGGLE_SUBTITLE[did]
    if len(full_title) > KAGGLE_TITLE_MAX:
        die(1, "Kaggle title for %s is %d chars, limit %d: %r"
            % (did, len(full_title), KAGGLE_TITLE_MAX, full_title))
    if not (KAGGLE_SUBTITLE_MIN <= len(sub) <= KAGGLE_SUBTITLE_MAX):
        die(1, "Kaggle subtitle for %s is %d chars, must be %d-%d: %r"
            % (did, len(sub), KAGGLE_SUBTITLE_MIN, KAGGLE_SUBTITLE_MAX, sub))
    return json.dumps({
        "title": full_title,
        "subtitle": sub,
        "id": "pbhappliedsystems/%s" % name,
        "licenses": [{"name": "CC-BY-4.0"}],
        "description": ("See README.md. Part of the quant_eval public corpus"
                        + (" — %s" % concept if concept else "") + "."),
        "resources": [],
    }, indent=2) + "\n"


def dataset_card(did, name, stats, runs, concept, version, fixture_info,
                 figures=()):
    """HF/Kaggle-ready dataset card. YAML frontmatter is HF's; the body renders
    correctly on HF, Kaggle, GitHub, and Zenodo."""
    title, blurb = DATASET_DESC[did]
    files = DATASET_FILES[did]
    rows = stats.get("rows")
    cols = stats.get("cols")

    size_cat = ("n<1K" if (rows or 0) < 1000 else
                "1K<n<10K" if rows < 10000 else
                "10K<n<100K" if rows < 100000 else "100K<n<1M")

    fm = ["---",
          "license: cc-by-4.0",
          "language:",
          "- en",
          "pretty_name: >-",
          "  quant_eval %s" % title,
          "size_categories:",
          "- %s" % size_cat,
          "tags:"]
    fm += ["- %s" % t for t in HF_TAGS]
    fm += ["annotations_creators:",
           "- machine-generated",
           "source_datasets:",
           "- original",
           "configs:",
           "- config_name: default",
           "  data_files:",
           "  - split: train",
           "    path: %s" % VIEWER_FILE[did],
           "---", ""]

    L = fm
    A = L.append
    A("# quant_eval — %s" % title)
    A("")
    A("**%s**" % blurb)
    A("")
    A("Part of the quant_eval public corpus: a per-case behavioral evaluation "
      "of full-weight and quantized large language models across eight "
      "agent-relevant task families, with paired statistical testing.")
    A("")
    if concept or version:
        if concept:
            A("**Cite this dataset:** [%s](https://doi.org/%s) — concept DOI, "
              "always resolves to the latest version." % (concept, concept))
        if version:
            A("**This exact deposit:** [%s](https://doi.org/%s) — version DOI, "
              "frozen. Cite this one where reported numbers must stay "
              "verifiable against the object referenced." % (version, version))
        A("")

    A("## What this file contains")
    A("")
    A("| File | Rows | Columns |")
    A("|---|---:|---:|")
    for f in files["data"]:
        st = stats.get("per_file", {}).get(f, {})
        A("| `%s` | %s | %s |" % (f,
                                  _fmt_int(st["rows"]) if st.get("rows") is not None else "—",
                                  st.get("cols", "—")))
    A("")
    if files["extra"]:
        A("Supporting files: " + ", ".join("`%s`" % f for f in files["extra"]) + ".")
        A("")

    A("## Corpus scope")
    A("")
    A("| Run | Model | Baseline | Quantized | Substrate | Licence |")
    A("|---|---|---|---|---|---|")
    for r in runs:
        A("| `%s` | %s | %s | %s | %s | %s |"
          % (r["run_id"], r["model_id"], r["baseline_quant_type"],
             r["quantized_quant_type"],
             "Modal" if r["execution_substrate"].startswith("modal") else "local",
             r["license"]))
    A("")
    A("Every run evaluates a full-weight baseline and a quantized variant of "
      "the same model against the identical locked fixture set, case for case. "
      "Statistical comparison is paired: the two-sided exact McNemar test on "
      "per-case outcomes, with Wilson intervals on the rates.")
    A("")

    if figures:
        A("## Figures")
        A("")
        for fn, alt, cap in figures:
            A("![%s](%s)" % (alt, fn))
            A("")
            A(cap)
            A("")
        A("Figures are generated directly from the harness rollups by the "
          "published build tooling; no plotted value is recomputed, smoothed, "
          "or fitted.")
        A("")

    A("## Columns")
    A("")
    for f in files["data"]:
        cd = stats.get("columns", {}).get(f)
        if not cd:
            continue
        A("### `%s`" % f)
        A("")
        A("```")
        for i in range(0, len(cd), 3):
            A("  " + "  ".join("%-44s" % c for c in cd[i:i + 3]).rstrip())
        A("```")
        A("")
    if did in ("D1", "D2"):
        A("`data_dictionary.json`, included here, documents every field: applicability, "
          "data type, evidence role, gate membership, the meaning of an empty "
          "value, and observed population counts. **An empty cell is not "
          "automatically a missing measurement** — several fields are "
          "conditional on task family, and their empty-value meaning is "
          "recorded explicitly.")
        A("")

    A("## Verification")
    A("")
    A("This corpus is derived from sanitized publication bundles produced by "
      "the quant_eval harness. It is designed to be checked rather than "
      "trusted:")
    A("")
    ck_where = ("`source_bundle_checksums.json`, included here,"
                if "source_bundle_checksums.json" in files["extra"]
                else "`source_bundle_checksums.json`, published with every "
                     "dataset in this corpus,")
    A("- %s republishes, verbatim, the SHA-256 digest and byte length of every "
      "file in every source bundle. No source file was modified." % ck_where)
    A("- Before this file was written, the builder verified all "
      "%d source-file digests and independently recomputed all %d family x "
      "runner pass rates from the raw per-case rows, matching the harness "
      "rollups exactly." % (stats["n_checksums"], stats["n_stats"]))
    dd_where = ("`data_dictionary.json`, included here"
                if "data_dictionary.json" in files["extra"]
                else "`data_dictionary.json`, published with the per-case "
                     "results dataset (D1) and the throughput telemetry "
                     "dataset (D2)")
    if did in ("D5", "D6"):
        A("- **Every row in this file is recomputable from the per-case results "
          "dataset (D1)** using the gate definitions in %s. The pass counts, "
          "rates, and full discordance breakdown follow directly from the "
          "per-case outcomes; no intermediate artifact is required." % dd_where)
    elif did == "D1":
        A("- Every aggregate published in the paired degradation statistics "
          "dataset (D5) and the family pass rates dataset (D6) is recomputable "
          "from this file using the gate definitions in %s." % dd_where)
    elif did == "D7":
        A("- The figures here are **not** derived from the per-case results "
          "dataset. Stored-artifact byte counts and observed wall time are "
          "recorded by the harness at run time and are carried through from "
          "the source bundles unchanged; they are traceable through the "
          "bundle digests above, not recomputable from per-case rows. "
          "Pass-rate aggregates, which are recomputable, live in the paired "
          "degradation statistics (D5) and family pass rates (D6) datasets.")
    elif did == "D4":
        A("- The fields here are run-level metadata carried through from the "
          "source bundles unchanged, not statistics derived from per-case "
          "rows. They are traceable through the bundle digests above. "
          "Recomputable aggregates live in the paired degradation statistics "
          "(D5) and family pass rates (D6) datasets, both derived from the "
          "per-case results dataset (D1).")
    else:
        A("- Aggregates published elsewhere in this corpus — the paired "
          "degradation statistics (D5) and family pass rates (D6) datasets — "
          "are recomputable from the per-case results dataset (D1) using the "
          "gate definitions in %s." % dd_where)
    A("")
    if did == "D3" and fixture_info:
        A("### Fixture identity")
        A("")
        A("The published fixture file is a **byte-exact copy** of the file used "
          "in run `%s`." % fixture_info["from_run"])
        A("")
        A("- File SHA-256: `%s`" % fixture_info["file_sha"])
        A("- Canonical content SHA-256: `%s`" % fixture_info["canonical"])
        A("")
        A("Across the published runs the fixture file appears under more than "
          "one SHA-256 and more than one version label. A full structural "
          "comparison of all cases shows the only differing key is the "
          "top-level `version` string; all cases, all oracle expectations, and "
          "all trace hashes are identical. The canonical content hash is taken "
          "over the fixture object with `version` removed, serialized with "
          "sorted keys and compact separators, so the equivalence can be "
          "reproduced rather than taken on trust. "
          "`fixture_version_crosswalk.csv` maps every run to its recorded "
          "hash and label, and flags which file is published here.")
        A("")

    A("## Limits you should know before using this")
    A("")
    A("- **Decoding conditions are not uniform across models.** Temperature "
      "follows each publisher's own model card, so cross-model comparison of "
      "absolute pass rates is confounded. Within-run pairing is unaffected, "
      "which is what the paired test requires. The conditions are published "
      "per row and per run so they can be filtered on.")
    A("- **Runs on the Modal substrate record `seed` status `unsupported`**, "
      "because the deployed method signature accepts no seed parameter. This "
      "records a configuration fact, not a determinism fact: repeat runs of "
      "the same model, version and fixture set produced identical output. "
      "Local runs applied a fixed seed explicitly.")
    if did == "D7":
        A("- **Pairs whose two lanes ran on different accelerators are not "
          "precision comparisons.** `hardware_matched_pair` is the field to "
          "filter on: `true` means both lanes used the same accelerator class "
          "and the wall-time ratio is a precision comparison, `false` means "
          "they did not and it is not. Filter before comparing anything. This "
          "is the single most important limit in this dataset.")
        A("- **The accelerator fields are declared, not harness-recorded.** "
          "The publication bundles do not capture accelerator class, so these "
          "values come from a declaration published with the build tooling. "
          "They are traceable to that declaration rather than to a bundle "
          "digest, and the distinction is deliberate.")
    A("- **Runtime figures are observed harness wall time** on the recorded "
      "hardware and backends. They are not a controlled throughput benchmark "
      "and not a general claim about quantization performance at any precision "
      "on any hardware. Direction is published as an explicit label because "
      "not every measured pair is a speedup.")
    A("- **The fuzz family is an adaptive trajectory** evaluated from identical "
      "starting fixtures. Its paired test compares complete case outcomes, not "
      "identical post-divergence prompts.")
    if did == "D4":
        missing = [r for r in runs if not r.get("upstream_revision")]
        if missing:
            reasons = sorted({r.get("upstream_revision_status", "")
                              for r in missing if r.get("upstream_revision_status")})
            A("- **`upstream_revision` is empty for %d of %d runs** (%s). Where "
              "present, it is the exact upstream repository revision the "
              "evaluated weights were converted from. Where empty, "
              "`upstream_revision_status` records why — in this corpus, %s. "
              "This is a documented absence, not a dropped measurement: weight "
              "identity for those runs is still established exactly, by the "
              "artifact SHA-256 recorded in this file, but not tied to a named "
              "upstream commit."
              % (len(missing), len(runs),
                 ", ".join("`%s`" % r["run_id"] for r in missing),
                 " and ".join("`%s`" % x for x in reasons) if reasons
                 else "see that column"))
    cal_where = ("`calibration_lineage.csv`, included here"
                 if "calibration_lineage.csv" in files["data"]
                 else "`calibration_lineage.csv`, published in the run "
                      "provenance dataset (D4)")
    A("- **Calibration runs are not published.** Runs that informed a published "
      "run are disclosed by identifier in %s, so the record is complete "
      "without releasing provisional numbers." % cal_where)
    A("")

    A("## Citation")
    A("")
    A("```bibtex")
    A("@dataset{pbh_quant_eval_%s," % did.lower())
    A("  author    = {Hill, Patrick},")
    A("  title     = {quant_eval %s}," % title)
    A("  publisher = {PBH Applied Systems, LLC},")
    A("  year      = {2026},")
    if concept:
        A("  doi       = {%s}," % concept)
    elif version:
        A("  doi       = {%s}," % version)
    if version:
        A("  note      = {Version DOI: %s}," % version)
    A("  license   = {CC-BY-4.0}")
    A("}")
    A("```")
    A("")
    A("## Licence")
    A("")
    A("Creative Commons Attribution 4.0 International (CC BY 4.0). "
      "See `LICENSE`. Commercial use is permitted; attribution is required.")
    A("")
    A("This corpus describes third-party models and redistributes no model "
      "weights. Each evaluated model remains under its own licence, recorded "
      "per run in the run provenance dataset.")
    A("")
    A("---")
    A("")
    A("Produced by %s from quant_eval publication bundles. "
      "Built %s." % (BUILDER_VERSION, stats["built_at"][:10]))
    return "\n".join(L) + "\n"


# ============================================================ sanitization gate
# Excluded telemetry keys, detected structurally as JSON keys.
EXCLUDED_KEY_PATTERN = re.compile(r'"(app|backend|class)"\s*:')


def sanitization_gate(paths):
    """Abort the build if any forbidden token reached an output file.

    Two checks: the FORBIDDEN_PATTERNS regexes on every output, plus a
    structural check that no excluded telemetry key survived into a JSONL
    output. The second exists because the excluded keys carry ordinary-looking
    values that no path or secret regex would catch.
    """
    hits = []
    for p in paths:
        if p.endswith(".jsonl"):
            with open(p, "r", encoding="utf-8", errors="replace") as f:
                for lineno, line in enumerate(f, 1):
                    m = EXCLUDED_KEY_PATTERN.search(line)
                    if m:
                        hits.append((p, lineno,
                                     "excluded telemetry key %r" % m.group(1)))
                        break
    for p in paths:
        with open(p, "r", encoding="utf-8", errors="replace") as f:
            for lineno, line in enumerate(f, 1):
                for pat in FORBIDDEN_PATTERNS:
                    if pat.search(line):
                        hits.append((p, lineno, pat.pattern))
                        break
                if len(hits) > 20:
                    break
    if hits:
        log("")
        log("  SANITIZATION FAILURES:")
        for p, ln, pat in hits[:20]:
            log("    %s:%d matched %s" % (os.path.basename(p), ln, pat))
        die(3, "%d forbidden tokens reached the output — build rejected" % len(hits))
    log("  sanitization gate: clean across %d output files" % len(paths))


# ============================================================ main
def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--runs-root", default=DEFAULT_RUNS_ROOT)
    ap.add_argument("--out", default=DEFAULT_OUT_ROOT)
    ap.add_argument("--exclude", action="append", default=[],
                    help="run_id to exclude; repeatable")
    ap.add_argument("--bundle", action="append", default=[],
                    help="explicit run folder or publication folder to include; "
                         "repeatable. Bypasses discovery.")
    ap.add_argument("--bundles-file",
                    help="file of run/publication folder paths, one per line; "
                         "# comments allowed. Bypasses discovery.")
    ap.add_argument("--figures",
                    help="directory of generated figure PNGs; when supplied, "
                         "figures are copied into the datasets that reference "
                         "them and rendered on their cards")
    ap.add_argument("--lineage",
                    help="calibration lineage declaration; see parse_lineage")
    ap.add_argument("--hardware-map", dest="hardware_map",
                    help="REQUIRED. Accelerator declaration, one line per run: "
                         "RUN_ID BASELINE_ACCELERATOR QUANTIZED_ACCELERATOR. "
                         "The build aborts if absent or if any selected run is "
                         "missing. See parse_hardware_map.")
    ap.add_argument("--doi-map",
                    help="JSON mapping 'corpus' and D1..D7 to reserved DOIs. "
                         "Each value is either a string (treated as the "
                         "concept DOI) or an object with 'concept' and/or "
                         "'version'.")
    ap.add_argument("--allowlist",
                    help="file of run_ids to include, one per line")
    ap.add_argument("--dry-run", action="store_true",
                    help="discover and verify, write nothing")
    args = ap.parse_args()
    args.lineage_map = parse_lineage(args.lineage)
    args.hw_map = parse_hardware_map(args.hardware_map)
    args.doi = load_json(args.doi_map) if args.doi_map else {}
    args.selection_mode = ("explicit" if (args.bundle or args.bundles_file)
                           else "discovery_strict")

    started = datetime.now(timezone.utc).isoformat()
    log("=" * 78)
    log("quant_eval public corpus derivation — %s" % BUILDER_VERSION)
    log("spec: %s" % SPEC_VERSION)
    log("runs root: %s" % args.runs_root)
    log("output:    %s" % args.out)
    log("=" * 78)

    explicit = list(args.bundle)
    if args.bundles_file:
        with open(args.bundles_file, encoding="utf-8") as f:
            for ln in f:
                ln = ln.split("#", 1)[0].strip()   # strip trailing comments
                if ln:
                    explicit.append(ln)

    log("")
    if explicit:
        log("[1/6] EXPLICIT SELECTION (%d folder(s) named; discovery bypassed)"
            % len(explicit))
        bundles = load_explicit_bundles(explicit, args.runs_root)
        skipped = []
        log("  %d run(s) selected" % len(bundles))
        log("")
        log("[2/6] INTEGRITY — source bundle checksums")
        n_ck = verify_checksums(bundles)
        log("")
        log("[3/6] INTEGRITY — recompute every pass rate from raw CSV")
        n_stat = verify_statistics(bundles)
        log("")
        log("[3b/6] DECLARATION — accelerator per lane")
        verify_hardware_map(bundles, args.hw_map, args.hardware_map)
        return _continue(args, bundles, skipped, n_ck, n_stat, started)

    log("[1/6] DISCOVERY")
    bundles, skipped = discover(args.runs_root, set(args.exclude))
    for b in bundles:
        log("  INCLUDE  %s" % b["run_id"])
    for rid, reason in skipped:
        log("  SKIP     %-52s %s" % (rid, reason))
    if not bundles:
        die(1, "no publication-eligible bundles found under %s" % args.runs_root)
    log("  %d eligible run(s), %d skipped by filter" % (len(bundles), len(skipped)))

    allow = set()
    if args.allowlist:
        with open(args.allowlist, encoding="utf-8") as f:
            allow = {ln.strip() for ln in f
                     if ln.strip() and not ln.startswith("#")}
    bundles, dropped = resolve_selection(bundles, "strict", allow)
    for rid, reason in dropped:
        log("  DROP     %-52s %s" % (rid, reason))
    skipped = skipped + dropped
    log("  %d run(s) selected for the corpus" % len(bundles))

    log("")
    log("[2/6] INTEGRITY — source bundle checksums")
    n_ck = verify_checksums(bundles)

    log("")
    log("[3/6] INTEGRITY — recompute every pass rate from raw CSV")
    n_stat = verify_statistics(bundles)

    log("")
    log("[3b/6] DECLARATION — accelerator per lane")
    verify_hardware_map(bundles, args.hw_map, args.hardware_map)

    return _continue(args, bundles, skipped, n_ck, n_stat, started)


def _continue(args, bundles, skipped, n_ck, n_stat, started):
    if args.dry_run:
        log("")
        log("DRY RUN — verification passed, nothing written.")
        return

    os.makedirs(args.out, exist_ok=True)
    log("")
    log("[4/6] BUILD")
    written = []

    p, rows, cols = build_d1(bundles, args.out)
    log("  D1 %-46s %7d rows x %d cols" % (os.path.basename(p), rows, cols))
    written.append(p)
    d1_rows = rows

    p, recs, nkeys, keys = build_d2(bundles, args.out)
    log("  D2 %-46s %7d records x %d fields" % (os.path.basename(p), recs, nkeys))
    written.append(p)

    fx, cw, lin, n_cw, n_lin = build_d3(bundles, args.out, args.lineage_map)
    for f in fx:
        log("  D3 %-46s %7d cases   file=%s" %
            (os.path.basename(f["path"]), f["cases"], f["file_sha"][:16]))
        log("     byte-exact copy from %s, version label %s (labels in class: %s)"
            % (f["from_run"], f["label"], f["labels_in_class"]))
    log("  D3 %-46s %7d rows" % (os.path.basename(cw), n_cw))
    log("  D3 %-46s %7d rows" % (os.path.basename(lin), n_lin))
    written += [f["path"] for f in fx] + [cw, lin]

    labels = {r["run_id"]: r["fixture_version_label"]
              for r in csv.DictReader(open(cw, newline="", encoding="utf-8"))}
    fixture_info = fx[0] if len(fx) == 1 else None

    for tag, fn in (("D4", build_d4), ("D5", build_d5),
                    ("D6", build_d6), ("D7", build_d7)):
        if tag == "D4":
            p, rows, cols = fn(bundles, args.out, labels)
        elif tag == "D7":
            p, rows, cols = fn(bundles, args.out, args.hw_map)
        else:
            p, rows, cols = fn(bundles, args.out)
        log("  %s %-46s %7d rows x %d cols" % (tag, os.path.basename(p), rows, cols))
        written.append(p)

    prov = build_provenance(bundles, args.out)
    log("  -- %-46s %7d bundles" % (os.path.basename(prov), len(bundles)))
    written.append(prov)

    dd, dd_counts, dd_notes = build_data_dictionary(bundles, args.out)
    log("  -- %-46s %s" % (os.path.basename(dd),
                           " ".join("%s=%d" % (k.split(".")[0], v)
                                    for k, v in sorted(dd_counts.items()))))
    written.append(dd)
    for rid, ds, name in dd_notes:
        log("     union: %s contributed %s.%s" % (rid, ds, name))

    log("")
    log("[5/7] SANITIZATION GATE")
    sanitization_gate([p for p in written if p.endswith((".csv", ".jsonl", ".json"))])

    # ---------------------------------------------------- packaging
    log("")
    log("[6/7] PACKAGE — one folder per dataset")
    import shutil
    stats = {"n_checksums": n_ck, "n_stats": n_stat, "built_at": started}
    runs = list(csv.DictReader(open(
        os.path.join(args.out, "quant_eval_run_provenance.csv"),
        newline="", encoding="utf-8")))

    def file_stats(path):
        if path.endswith(".csv"):
            with open(path, newline="", encoding="utf-8") as f:
                rd = csv.reader(f)
                hdr = next(rd)
                n = sum(1 for _ in rd)
            return {"rows": n, "cols": len(hdr), "columns": hdr}
        if path.endswith(".jsonl"):
            n = 0
            keys = []
            with open(path, encoding="utf-8") as f:
                for i, line in enumerate(f):
                    if line.strip():
                        n += 1
                        if i == 0:
                            keys = sorted(json.loads(line).keys())
            return {"rows": n, "cols": len(keys), "columns": keys}
        return {"rows": None, "cols": None, "columns": None}

    dataset_stats, packaged = {}, []
    for did in sorted(DATASET_FILES):
        spec = DATASET_FILES[did]
        folder = os.path.join(args.out, "%s_%s" % (did, DATASETS[did]))
        os.makedirs(folder, exist_ok=True)
        per_file, columns, total_rows, first_cols = {}, {}, 0, None
        for fn in spec["data"]:
            src = os.path.join(args.out, fn)
            if not os.path.exists(src):
                continue
            st = file_stats(src)
            per_file[fn] = st
            if st["columns"]:
                columns[fn] = st["columns"]
            if st["rows"] and first_cols is None:
                total_rows, first_cols = st["rows"], st["cols"]
            shutil.copyfile(src, os.path.join(folder, fn))
        for fn in spec["extra"]:
            src = os.path.join(args.out, fn)
            if os.path.exists(src):
                shutil.copyfile(src, os.path.join(folder, fn))

        if did == "D3" and fixture_info:
            per_file.setdefault("golden_oracle_fixtures.json", {})
            per_file["golden_oracle_fixtures.json"]["rows"] = \
                fixture_info["cases"]
            per_file["golden_oracle_fixtures.json"]["cols"] = "—"
            size_label = "%s cases" % _fmt_int(fixture_info["cases"])
            total_rows = fixture_info["cases"]
        else:
            size_label = None
        dstats = dict(stats)
        dstats.update({"rows": total_rows, "cols": first_cols,
                       "per_file": per_file, "columns": columns,
                       "size_label": size_label})
        dataset_stats[did] = dstats
        concept, version = normalize_doi(args.doi.get(did))
        figs = []
        for fn, alt, cap in FIGURES.get(did, []):
            src = os.path.join(args.figures, fn) if args.figures else None
            if src and os.path.isfile(src):
                shutil.copyfile(src, os.path.join(folder, fn))
                figs.append((fn, alt, cap))
            elif args.figures:
                log("     WARNING: figure %s not found in %s" % (fn, args.figures))
        card = dataset_card(did, DATASETS[did], dstats, runs, concept, version,
                            fixture_info, figs)
        with open(os.path.join(folder, "dataset-metadata.json"), "w",
                  encoding="utf-8") as f:
            f.write(kaggle_metadata(did, DATASETS[did], concept))
        title = DATASET_DESC[did][0]
        with open(os.path.join(folder, "README.md"), "w",
                  encoding="utf-8") as f:
            f.write(card)
        with open(os.path.join(folder, "LICENSE"), "w", encoding="utf-8") as f:
            f.write(LICENSE_TEXT.format(
                title="quant_eval " + title,
                doi_line=doi_note(concept, version)))
        with open(os.path.join(folder, "CITATION.cff"), "w",
                  encoding="utf-8") as f:
            f.write(citation_cff(title, concept, version))
        n_files = len(os.listdir(folder))
        fmark = ("%d figure%s" % (len(figs), "" if len(figs) == 1 else "s")
                 if figs else "no figures")
        dmark = ("concept+version" if concept and version else
                 "concept only" if concept else
                 "version only" if version else "no DOI supplied")
        log("  %s %-46s %d files   (%s, %s)"
            % (did, os.path.basename(folder), n_files, dmark, fmark))
        packaged += [os.path.join(folder, x) for x in os.listdir(folder)]

    corpus_concept, corpus_version = normalize_doi(args.doi.get("corpus"))

    # ---- D0: the corpus record, packaged like the seven datasets so it can be
    # deposited as its own citable object. The seven datasets declare
    # isPartOf against this record's concept DOI.
    d0 = os.path.join(args.out, "D0_quant_eval_public_corpus")
    os.makedirs(d0, exist_ok=True)
    corpus_md = corpus_readme(stats, runs, corpus_concept, corpus_version,
                              dataset_stats)
    corpus_license = LICENSE_TEXT.format(title="quant_eval Public Corpus",
                                         doi_line=doi_note(corpus_concept,
                                                           corpus_version))
    corpus_cff = citation_cff("Public Corpus", corpus_concept, corpus_version)
    for name, body in (("README.md", corpus_md),
                       ("LICENSE", corpus_license),
                       ("CITATION.cff", corpus_cff),
                       ("dataset-metadata.json",
                        kaggle_metadata("D0", "quant_eval_public_corpus",
                                        corpus_concept))):
        with open(os.path.join(d0, name), "w", encoding="utf-8") as f:
            f.write(body)
    shutil.copyfile(prov, os.path.join(d0, "source_bundle_checksums.json"))
    packaged += [os.path.join(d0, x) for x in os.listdir(d0)]
    log("  D0 %-46s %d files   (%s)"
        % (os.path.basename(d0), len(os.listdir(d0)) + 1,   # +1: manifest
           "concept+version" if corpus_concept and corpus_version else
           "concept only" if corpus_concept else
           "version only" if corpus_version else "no DOI supplied"))

    # Root copies remain as the browsing / repo-mirror view. D0 is the
    # depositable unit; the two are byte-identical by construction.
    with open(os.path.join(args.out, "README.md"), "w", encoding="utf-8") as f:
        f.write(corpus_md)
    with open(os.path.join(args.out, "LICENSE"), "w", encoding="utf-8") as f:
        f.write(corpus_license)
    with open(os.path.join(args.out, "CITATION.cff"), "w",
              encoding="utf-8") as f:
        f.write(corpus_cff)

    # Root-level staging copies are removed: each dataset folder is the
    # authoritative, independently depositable unit.
    staged = set()
    for spec in DATASET_FILES.values():
        staged.update(spec["data"])
        staged.update(spec["extra"])
    removed = 0
    for fn in sorted(staged):
        src = os.path.join(args.out, fn)
        if os.path.exists(src):
            os.remove(src)
            removed += 1
    written = [w for w in written
               if os.path.dirname(os.path.normpath(w)) != os.path.normpath(args.out)
               or os.path.basename(w) not in staged]
    log("  -- README.md, LICENSE, CITATION.cff mirrored at corpus root; "
        "%d staging copies removed" % removed)
    written += [os.path.join(args.out, "README.md"),
                os.path.join(args.out, "LICENSE"),
                os.path.join(args.out, "CITATION.cff")]

    log("")
    log("[5b/7] SANITIZATION GATE — generated cards")
    sanitization_gate([f for f in packaged if f.endswith((".md", "LICENSE",
                                                          ".cff"))]
                      + [os.path.join(args.out, "README.md"),
                         os.path.join(args.out, "CITATION.cff")])

    log("")
    log("[7/7] DIGESTS + BUILD MANIFEST")
    digests = {}
    for p in sorted(set(written) | set(packaged)):
        rel = os.path.relpath(p, args.out)
        digests[rel] = {"sha256": sha256_file(p), "bytes": os.path.getsize(p)}
    for rel in sorted(digests):
        if os.sep not in rel:
            log("  %-52s %s" % (rel, digests[rel]["sha256"][:16]))
    log("  (+ %d files inside dataset folders)"
        % sum(1 for r in digests if os.sep in r))

    manifest = {
        "spec_version": SPEC_VERSION,
        "builder_version": BUILDER_VERSION,
        "built_at_utc": started,
        "license": "CC-BY-4.0",
        "runs_included": [b["run_id"] for b in bundles],
        "runs_excluded": [{"run_id": r, "reason": s} for r, s in skipped],
        "selection_mode": args.selection_mode,
        "verification": {
            "source_files_checksum_verified": n_ck,
            "pass_rates_recomputed_and_matched": n_stat,
            "sanitization_gate": "passed",
        },
        "telemetry_excluded_keys": sorted(TELEMETRY_EXCLUDE_KEYS),
        "appended_columns_d1": APPENDED,
        "outputs": digests,
        "corpus_record": {"folder": "D0_quant_eval_public_corpus",
                          "doi_concept": normalize_doi(args.doi.get("corpus"))[0],
                          "doi_version": normalize_doi(args.doi.get("corpus"))[1],
                          "files": ["README.md", "LICENSE", "CITATION.cff",
                                    "dataset-metadata.json",
                                    "source_bundle_checksums.json",
                                    "build_manifest.json"],
                          "relation_targets": "D1-D7 declare isPartOf this "
                                              "record's concept DOI"},
        "datasets": {did: {"folder": "%s_%s" % (did, DATASETS[did]),
                           "doi_concept": normalize_doi(args.doi.get(did))[0],
                           "doi_version": normalize_doi(args.doi.get(did))[1],
                           "files": DATASET_FILES[did]["data"]
                                    + DATASET_FILES[did]["extra"]
                                    + ["README.md", "LICENSE", "CITATION.cff"]}
                     for did in sorted(DATASET_FILES)},
        "doi_corpus_concept": normalize_doi(args.doi.get("corpus"))[0],
        "doi_corpus_version": normalize_doi(args.doi.get("corpus"))[1],
        "calibration_runs_declared": sum(len(v)
                                         for v in args.lineage_map.values()),
    }
    mpath = os.path.join(args.out, "build_manifest.json")
    with open(mpath, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, sort_keys=True)
    # The manifest is the corpus record's integrity index; ship it in D0 too.
    shutil.copyfile(mpath, os.path.join(args.out,
                                        "D0_quant_eval_public_corpus",
                                        "build_manifest.json"))

    log("")
    log("=" * 78)
    log("BUILD OK — %d runs, %d per-case rows, %d files" %
        (len(bundles), d1_rows, len(written) + 1))
    log("manifest: %s" % mpath)
    log("=" * 78)


if __name__ == "__main__":
    main()
