# quant_eval_public_corpus_tools

Derivation tooling for the **quant_eval public corpus** — a per-case behavioral
evaluation of full-weight and quantized large language models across eight
agent-relevant task families, with paired statistical testing and published
ground truth.

This repository publishes the *contract*, not the harness. It contains the code
that derives the public corpus from sanitized publication bundles, so every
column operation is inspectable without distributing the evaluation engine.

**Corpus DOI (all versions):** [10.5281/zenodo.22009419](https://doi.org/10.5281/zenodo.22009419)

## Why this repository exists

The corpus is designed to be checked rather than trusted. Its integrity chain
has three links:

1. **Source digests** — `source_bundle_checksums.json` republishes, verbatim,
   the SHA-256 and byte length of every file in every source bundle. Shipped
   with every dataset.
2. **Derivation** — this repository. Without it, a reader can verify the inputs
   and the outputs but has no way to check that the outputs follow from the
   inputs.
3. **Output digests** — `build_manifest.json` records a SHA-256 and byte count
   for every published file.

## Contents

| File | Purpose |
|---|---|
| `build_datasets.py` | Derives the seven datasets and the corpus record from publication bundles. Standard library only. |
| `make_figures.py` | Generates the four corpus figures from harness rollups. No plotted value is recomputed, smoothed, or fitted. |
| `figures/*.svg` | Vector figures for print and the whitepaper. PNG versions ship inside the datasets that reference them. |
| `corpus_runs.txt` | The explicit list of published runs. Selection is declared, never inferred. |
| `calibration_lineage.txt` | Internal calibration runs recorded against the published run each informed. Calibration runs are not published; only their identifiers are disclosed. |
| `reserved_dois.json` | Concept and version DOIs per dataset, embedded into the generated cards at build time. |

## Usage

```bash
python3 build_datasets.py --bundles-file corpus_runs.txt --dry-run

python3 build_datasets.py --bundles-file corpus_runs.txt \
                          --lineage calibration_lineage.txt \
                          --figures figures \
                          --doi-map reserved_dois.json
```

`--dry-run` discovers and verifies without writing. The build **aborts** rather
than warns on any source digest mismatch, any pass rate that fails to recompute
from raw rows, or any forbidden token reaching an output file.

Only the sanitized `publication/` subdirectory of a run folder is ever read.

## The datasets

| | Dataset | Contents | Size |
|---|---|---|---|
| D0 | Public Corpus | Corpus record, licence, citation, build manifest | — |
| D1 | Per-case behavioral results | Raw outputs, scored signals, decoding conditions | 19,200 rows |
| D2 | Throughput telemetry | One record per generation call | 27,370 records |
| D3 | Golden oracle fixtures | Locked fixtures with deterministic ground truth | 1,600 cases |
| D4 | Run provenance | Model identity, contracts, artifact digests, lineage | 6 rows |
| D5 | Paired degradation statistics | Paired deltas, McNemar tests, cluster adjustment | 48 rows |
| D6 | Family pass rates | Pass rates with Wilson intervals and gate definitions | 96 rows |
| D7 | Efficiency and footprint | Compression and observed wall-time ratios | 6 rows |

Deposited on Zenodo, mirrored to Hugging Face and Kaggle. D5 and D6 are
recomputable in full from D1 using the gate definitions published in
`data_dictionary.json`. D2, D4, and D7 are harness-recorded and traceable
through the source-bundle digests rather than recomputable.

## Licence

Code is licensed under **Apache-2.0** — see `LICENSE`.

The figures under `figures/` are part of the quant_eval public corpus and are
licensed under **CC BY 4.0**, consistent with the datasets they appear in.

This corpus describes third-party models and redistributes no model weights.
Each evaluated model remains under its own licence, recorded per run in the run
provenance dataset (D4).

## Citation

```bibtex
@dataset{pbh_quant_eval_corpus,
  author    = {Hill, Patrick},
  title     = {quant_eval Public Corpus},
  publisher = {PBH Applied Systems, LLC},
  year      = {2026},
  doi       = {10.5281/zenodo.22009419},
  license   = {CC-BY-4.0}
}
```

---

PBH Applied Systems, LLC · [ORCID 0009-0008-3662-1681](https://orcid.org/0009-0008-3662-1681)
