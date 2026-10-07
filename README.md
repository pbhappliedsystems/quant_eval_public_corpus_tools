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
| `make_figures.py` | Generates the four corpus figures from harness rollups. No plotted value is recomputed, smoothed, or fitted. Figure 4 reads the accelerator on each lane from `hardware_map.txt`. |
| `figures/` | The four figures, SVG (print and the whitepaper) and 200-dpi PNG (copied into the datasets that reference them by `--figures`). |
| `hardware_map.txt` | The accelerator on each lane of each run, declared by the author. The bundles do not record accelerator class, so `build_datasets.py` requires this file for D7 and `make_figures.py` requires it for Figure 4. |
| `corpus_runs.txt` | The explicit list of published runs. Selection is declared, never inferred. |
| `calibration_lineage.txt` | Internal calibration runs recorded against the published run each informed. Calibration runs are not published; only their identifiers are disclosed. |
| `reserved_dois.json` | Concept and version DOIs per dataset, embedded into the generated cards at build time. |

## Usage

```bash
python3 make_figures.py --bundles-file corpus_runs.txt \
                        --hardware-map hardware_map.txt --out figures

python3 build_datasets.py --bundles-file corpus_runs.txt \
                          --hardware-map hardware_map.txt --dry-run

python3 build_datasets.py --bundles-file corpus_runs.txt \
                          --lineage calibration_lineage.txt \
                          --hardware-map hardware_map.txt \
                          --figures figures \
                          --doi-map reserved_dois.json
```

Both scripts read run folders under `--runs-root` (default `/mnt/e/QUANT_EVAL/runs`).
`make_figures.py` needs matplotlib; `build_datasets.py` needs only the standard library.

`--dry-run` discovers and verifies without writing. The build **aborts** rather
than warns on any source digest mismatch, any pass rate that fails to recompute
from raw rows, or any forbidden token reaching an output file.

Only the sanitized `publication/` subdirectory of a run folder is ever read.

## Figure 4 and D7 v1.0.1

The two Modal pairs ran their full-weight lane on an A100 and their quantized lane
on an A10G, so their wall-time ratios below 1.0 measure the hardware difference, not
quantization. D7 v1.0.1 added `baseline_accelerator`, `quantized_accelerator` and
`hardware_matched_pair`, and Figure 4 now labels every bar with both lanes'
accelerators and hatches the hardware-unmatched pairs. Earlier versions of Figure 4
drew those two pairs as "slower under quantization"; that reading was wrong and is
withdrawn. Figure 2's annotation now states the share of Q4_K_M's storage saving that
Q5_K_M already delivers, computed from the rollups (earlier text said "two-thirds").

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

## Reading and recomputing the corpus: `qe-corpus`

`qe_corpus/` is a small reader and command-line tool for the *published* datasets.
It needs only the standard library (pandas optional) and contains no part of the
evaluation harness.

```bash
pip install .                                  # from a clone; installs `qe-corpus`
export QE_CORPUS_DATA=~/quant_eval_corpus      # folder holding the downloaded D0-D7

qe-corpus summary                              # runs, models, families, case counts
qe-corpus paired --run Mistral_Nemo_Instruct_2407_20260814_030505 --check
                                               # D5 cells recomputed from D1, compared with D5
qe-corpus significance                         # Whitepaper 2 Tables 5/6: degraded / improved / n.s.
qe-corpus verify                               # digests: build_manifest.json, fixture file, bundles
qe-corpus figure-inputs --out build/figure_inputs
                                               # inputs for make_figures.py rebuilt from D5 + D7
```

`paired` applies each family's gate conjunction (D6 `gating_signals`) to the D1 rows,
pairs the two lanes on `case_id`, and reports both pass rates, the delta, the
discordant counts b and c, and the exact two-sided McNemar p-value from the binomial.

Tests: `python -m unittest discover -s tests -v`. With `QE_CORPUS_DATA` set, they also
recompute all 48 D5 cells and 96 D6 pass counts from D1 and check Whitepaper 2's
Table 6 counts; without it those tests are skipped.

## Documentation and schemas

| File | Contents |
|---|---|
| [`docs/reproduce.md`](docs/reproduce.md) | Download, install, verify, recompute every recomputable table and the four figures, and what cannot be reproduced without the private harness. |
| [`docs/fixture_format.md`](docs/fixture_format.md) | Specification of `golden_oracle_fixtures.json` (D3): layout, every field per family, expected outputs, versioning crosswalk, checksums. |
| [`schemas/rollup.schema.json`](schemas/rollup.schema.json) | JSON Schema (draft 2020-12) for a publication bundle's `rollup.json`, covering the fields the public tooling reads. |
| [`schemas/run_manifest.schema.json`](schemas/run_manifest.schema.json) | JSON Schema for `run_manifest.json`, covering the fields the public tooling reads. |
| [`schemas/checksums.schema.json`](schemas/checksums.schema.json) | JSON Schema for a bundle's `checksums.json` (also the per-run objects in `source_bundle_checksums.json`). |
| [`qe_corpus/`](qe_corpus), [`pyproject.toml`](pyproject.toml) | The reader package and the `qe-corpus` command. |
| [`tests/`](tests) | Unit tests and checks against a downloaded corpus. |

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
