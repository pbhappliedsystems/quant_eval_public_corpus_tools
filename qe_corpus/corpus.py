# Copyright 2026 PBH Applied Systems, LLC
# SPDX-License-Identifier: Apache-2.0
"""Locate and read the published corpus files from a local folder.

The folder may hold the Zenodo/Hugging Face layout (one sub-folder per dataset,
e.g. ``D1_quant_eval_behavioral_per_case_results/``), a flat folder of the
downloaded files, or a single dataset folder. Files are found by their
published names.
"""
import csv
import hashlib
import json
import os
import sys

from .constants import DATASET_FILES, DATASET_FOLDERS

csv.field_size_limit(min(sys.maxsize, 2 ** 31 - 1))

# Data files whose names are unique across the corpus.
UNIQUE = {
    "D1": "quant_eval_behavioral_per_case_results.csv",
    "D2": "quant_eval_throughput_telemetry.jsonl",
    "D3": "golden_oracle_fixtures.json",
    "D3x": "fixture_version_crosswalk.csv",
    "D4": "quant_eval_run_provenance.csv",
    "D4l": "calibration_lineage.csv",
    "D5": "quant_eval_paired_degradation_statistics.csv",
    "D6": "quant_eval_family_pass_rates.csv",
    "D7": "quant_eval_efficiency_and_footprint.csv",
    "D0m": "build_manifest.json",
}


class CorpusError(Exception):
    pass


def _digest(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class Corpus:
    """Read-only view of a downloaded copy of the corpus."""

    def __init__(self, root):
        self.root = os.path.abspath(root)
        if not os.path.isdir(self.root):
            raise CorpusError("not a directory: %s" % root)
        self._index = {}
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
            for fn in filenames:
                self._index.setdefault(fn, []).append(os.path.join(dirpath, fn))

    # ------------------------------------------------------------ locating
    def find(self, filename, dataset=None):
        """Path of a published file, or None if it is not present."""
        hits = self._index.get(filename, [])
        if len(hits) > 1:
            folder = DATASET_FOLDERS.get(dataset or "")
            pref = [h for h in hits
                    if folder and os.path.basename(os.path.dirname(h)) == folder]
            if filename in UNIQUE.values() and len({_digest(h) for h in hits}) > 1:
                raise CorpusError("%s appears %d times with different contents "
                                  "under %s; point --data at one copy of the corpus"
                                  % (filename, len(hits), self.root))
            return (pref or hits)[0]
        return hits[0] if hits else None

    def all_paths(self, filename):
        return list(self._index.get(filename, []))

    def has(self, key):
        return self.find(UNIQUE[key], key[:2]) is not None

    def require(self, key):
        p = self.find(UNIQUE[key], key[:2])
        if p is None:
            raise CorpusError("%s not found under %s" % (UNIQUE[key], self.root))
        return p

    # ------------------------------------------------------------ reading
    @staticmethod
    def _csv(path):
        with open(path, newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))

    def iter_d1(self):
        """Stream D1 rows as dicts (19,200 rows; avoids holding raw outputs)."""
        with open(self.require("D1"), newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                yield row

    def d1_header(self):
        with open(self.require("D1"), newline="", encoding="utf-8") as f:
            return next(csv.reader(f))

    def iter_d2(self):
        with open(self.require("D2"), encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    yield json.loads(line)

    def fixtures(self):
        with open(self.require("D3"), encoding="utf-8") as f:
            return json.load(f)

    def crosswalk(self):
        return self._csv(self.require("D3x"))

    def provenance(self):
        return self._csv(self.require("D4"))

    def lineage(self):
        return self._csv(self.require("D4l"))

    def d5(self):
        return self._csv(self.require("D5"))

    def d6(self):
        return self._csv(self.require("D6"))

    def d7(self):
        return self._csv(self.require("D7"))

    def build_manifest(self):
        with open(self.require("D0m"), encoding="utf-8") as f:
            return json.load(f)

    def source_bundle_checksums(self):
        """All copies of source_bundle_checksums.json, parsed (one per dataset)."""
        out = []
        for p in self.all_paths("source_bundle_checksums.json"):
            try:
                with open(p, encoding="utf-8") as f:
                    out.append((p, json.load(f)))
            except (ValueError, UnicodeDecodeError):
                out.append((p, None))
        return out

    def dataframe(self, key):
        """A dataset as a pandas DataFrame (requires the optional pandas extra)."""
        try:
            import pandas as pd
        except ImportError as exc:  # pragma: no cover
            raise CorpusError("pandas is not installed; pip install "
                              "'quant-eval-corpus-tools[pandas]'") from exc
        path = self.require(key)
        if path.endswith(".jsonl"):
            return pd.read_json(path, lines=True)
        return pd.read_csv(path, dtype=str, keep_default_na=False)

    def present(self):
        """{dataset_id: [published data files found]}"""
        out = {}
        for did, names in DATASET_FILES.items():
            got = [n for n in names if self._index.get(n)]
            if got:
                out[did] = got
        return out
