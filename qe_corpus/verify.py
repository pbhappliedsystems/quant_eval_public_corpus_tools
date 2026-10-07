# Copyright 2026 PBH Applied Systems, LLC
# SPDX-License-Identifier: Apache-2.0
"""Integrity checks (Whitepaper 2, section 8.2, tier one).

1. Output digests: every file listed in D0's build_manifest.json `outputs`
   that is present locally must match its SHA-256 and byte count.
2. Fixture identity: the D3 fixture file's SHA-256 and canonical content hash
   must match the crosswalk and a digest recorded in source_bundle_checksums.json.
3. Optional: a publication bundle (for example one downloaded from a model
   repository) checked against its own checksums.json.
"""
import hashlib
import json
import os
import re

HEX64 = re.compile(r"^[0-9a-fA-F]{64}$")


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical_fixture_hash(obj):
    """SHA-256 over the fixture object with the top-level `version` key removed,
    serialized with sorted keys, compact separators, UTF-8 (the published recipe)."""
    stripped = {k: v for k, v in obj.items() if k != "version"}
    blob = json.dumps(stripped, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def _locate(corpus, rel):
    """Local path for a build_manifest `outputs` key, or None."""
    direct = os.path.join(corpus.root, rel)
    if os.path.isfile(direct):
        return direct
    parts = rel.replace("\\", "/").split("/")
    if len(parts) == 2:
        folder, name = parts
        for p in corpus.all_paths(name):
            if os.path.basename(os.path.dirname(p)) == folder:
                return p
        # A single dataset downloaded on its own (e.g. a Hugging Face or Kaggle
        # mirror) has no D-folder: accept the file at the root of --data.
        if os.path.basename(corpus.root) == folder or _single_dataset(corpus, folder):
            p = os.path.join(corpus.root, name)
            if os.path.isfile(p):
                return p
    return None


def _single_dataset(corpus, folder):
    # true when --data is a flat download of exactly the dataset named by folder
    marker = {
        "D1_quant_eval_behavioral_per_case_results": "quant_eval_behavioral_per_case_results.csv",
        "D2_quant_eval_throughput_telemetry": "quant_eval_throughput_telemetry.jsonl",
        "D3_quant_eval_golden_oracle_fixtures": "golden_oracle_fixtures.json",
        "D4_quant_eval_run_provenance": "quant_eval_run_provenance.csv",
        "D5_quant_eval_paired_degradation_statistics": "quant_eval_paired_degradation_statistics.csv",
        "D6_quant_eval_family_pass_rates": "quant_eval_family_pass_rates.csv",
        "D7_quant_eval_efficiency_and_footprint": "quant_eval_efficiency_and_footprint.csv",
    }.get(folder)
    return bool(marker) and os.path.isfile(os.path.join(corpus.root, marker))


def verify_outputs(corpus, manifest):
    """[(rel, status, detail)] for every entry in build_manifest outputs."""
    results = []
    for rel, meta in sorted(manifest.get("outputs", {}).items()):
        p = _locate(corpus, rel)
        if p is None:
            results.append((rel, "missing", "not present locally"))
            continue
        size = os.path.getsize(p)
        digest = sha256_file(p)
        want_d, want_b = meta.get("sha256"), meta.get("bytes")
        if digest == want_d and (want_b is None or size == want_b):
            results.append((rel, "ok", digest[:16]))
        else:
            results.append((rel, "MISMATCH",
                            "sha256 %s.. bytes %d, manifest %s.. bytes %s"
                            % (digest[:16], size, str(want_d)[:16], want_b)))
    return results


def verify_fixture(corpus):
    """Checks on the D3 fixture file. Returns [(check, status, detail)]."""
    path = corpus.find("golden_oracle_fixtures.json")
    if path is None:
        return [("fixture file", "missing", "golden_oracle_fixtures.json not present")]
    out = []
    file_sha = sha256_file(path)
    try:
        with open(path, encoding="utf-8") as f:
            obj = json.load(f)
        canon = canonical_fixture_hash(obj)
    except ValueError as exc:
        return [("fixture file", "MISMATCH", "not valid JSON: %s" % exc)]
    out.append(("fixture file sha256", "info", file_sha))
    out.append(("fixture canonical content sha256", "info", canon))

    if corpus.find("fixture_version_crosswalk.csv"):
        rows = corpus.crosswalk()
        pub = [r for r in rows if str(r.get("is_published_file", "")).lower() == "true"]
        if pub:
            ok = any(r["fixtures_sha256"] == file_sha for r in pub)
            out.append(("crosswalk: published file digest", "ok" if ok else "MISMATCH",
                        "matches is_published_file row" if ok else
                        "no is_published_file row carries this digest"))
        canons = {r.get("canonical_content_sha256") for r in rows}
        ok = canons == {canon}
        out.append(("crosswalk: canonical hash on every run", "ok" if ok else "MISMATCH",
                    "%d run rows" % len(rows)))
    else:
        out.append(("crosswalk", "missing", "fixture_version_crosswalk.csv not present"))

    if corpus.has("D4"):
        runs = [r["run_id"] for r in corpus.provenance()
                if r.get("fixtures_sha256") == file_sha]
        out.append(("D4: fixture digest recorded by a run", "ok" if runs else "MISMATCH",
                    ", ".join(runs) if runs else "no D4 row carries this digest"))

    seen = False
    docs = [(p, doc) for p, doc in corpus.source_bundle_checksums()
            if isinstance(doc, dict) and isinstance(doc.get("bundles"), dict)]
    if not docs:
        out.append(("source_bundle_checksums", "missing",
                    "no parseable source_bundle_checksums.json present"))
        return out
    for p, doc in docs:
        for run_id, cks in doc.get("bundles", {}).items():
            files = cks.get("files", cks) if isinstance(cks, dict) else {}
            e = files.get("golden_oracle_fixtures.json") if isinstance(files, dict) else None
            d = e.get("digest") or e.get("sha256") if isinstance(e, dict) else e
            if d == file_sha:
                seen = True
        if seen:
            break
    out.append(("source_bundle_checksums: fixture digest recorded",
                "ok" if seen else "MISMATCH",
                "digest found in a source bundle record" if seen else
                "digest not found in any source_bundle_checksums.json"))
    return out


def normalize_checksums(cks):
    """{filename: (digest, bytes|None)} from a bundle checksums.json.

    Accepts {"files": {...}} (schema_version 1) and the older flat shapes."""
    meta = {"algorithm", "schema_version", "generated_at", "generated_at_utc",
            "run_id", "version_tag", "note"}

    def entry(v):
        if isinstance(v, str):
            return (v, None) if HEX64.match(v) else None
        if isinstance(v, dict):
            d = v.get("digest") or v.get("sha256") or v.get("hash")
            if isinstance(d, str) and HEX64.match(d):
                return (d, v.get("bytes", v.get("size")))
        return None

    for container in ("files", "checksums", "artifacts"):
        if isinstance(cks.get(container), dict):
            got = {k: entry(v) for k, v in cks[container].items()}
            got = {k: v for k, v in got.items() if v}
            if got:
                return got
    got = {k: entry(v) for k, v in cks.items() if k not in meta}
    return {k: v for k, v in got.items() if v}


def verify_bundle(bundle_dir):
    """Check a publication bundle folder against its checksums.json."""
    cpath = os.path.join(bundle_dir, "checksums.json")
    if not os.path.isfile(cpath):
        return [("checksums.json", "missing", bundle_dir)]
    with open(cpath, encoding="utf-8") as f:
        files = normalize_checksums(json.load(f))
    out = []
    for name, (digest, size) in sorted(files.items()):
        p = os.path.join(bundle_dir, name)
        if not os.path.isfile(p):
            out.append((name, "missing", "listed in checksums.json"))
            continue
        ok = sha256_file(p) == digest.lower() and (size is None or os.path.getsize(p) == size)
        out.append((name, "ok" if ok else "MISMATCH", digest[:16]))
    return out
