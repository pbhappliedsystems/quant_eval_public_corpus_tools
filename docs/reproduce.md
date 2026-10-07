# Reproducing the quant_eval public corpus results

This guide takes a reader from the published datasets to every table and figure in
Whitepaper 2 (*The quant_eval Public Corpus: Behavioral Measurement of Quantization
Degradation*) that can be recomputed from public data, and states plainly what
cannot be.

Author: Patrick Hill · PBH Applied Systems, LLC

---

## What you can and cannot reproduce

| Tier (Whitepaper 2, §8.1) | What it establishes | Possible with public material? |
|---|---|---|
| 1. Integrity | The files you hold are the files that were published | **Yes.** `qe-corpus verify` |
| 2. Recomputation | D5 and D6 follow from the D1 per-case rows | **Yes.** `qe-corpus paired --check`, the test suite |
| Figures | Figures 1–4 follow from the published values | **Yes.** `qe-corpus figure-inputs` + `make_figures.py` |
| 3. Re-execution | The D1 rows follow from running the models | **No.** See the last section. |

## 1. Download the datasets

Each dataset is a separate Zenodo record under CC BY 4.0. Cite and download by
**concept DOI**, which always resolves to the latest version:

| | Dataset | Concept DOI |
|---|---|---|
| D0 | Public corpus record (includes `build_manifest.json`) | [10.5281/zenodo.22009419](https://doi.org/10.5281/zenodo.22009419) |
| D1 | Per-case behavioral results | [10.5281/zenodo.22009799](https://doi.org/10.5281/zenodo.22009799) |
| D2 | Throughput telemetry | [10.5281/zenodo.22009987](https://doi.org/10.5281/zenodo.22009987) |
| D3 | Golden oracle fixtures | [10.5281/zenodo.22010278](https://doi.org/10.5281/zenodo.22010278) |
| D4 | Run provenance | [10.5281/zenodo.22010462](https://doi.org/10.5281/zenodo.22010462) |
| D5 | Paired degradation statistics | [10.5281/zenodo.22010557](https://doi.org/10.5281/zenodo.22010557) |
| D6 | Family pass rates | [10.5281/zenodo.22010623](https://doi.org/10.5281/zenodo.22010623) |
| D7 | Efficiency and footprint | [10.5281/zenodo.22010723](https://doi.org/10.5281/zenodo.22010723) |

The same DOIs are listed in [`reserved_dois.json`](../reserved_dois.json). D1–D7 are
mirrored on Hugging Face and Kaggle under `pbhappliedsystems`; D0 is Zenodo-only.

Open each DOI, download the record's files, and place each dataset in its own folder
under one root, named as in the corpus build manifest:

```
quant_eval_corpus/
  D0_quant_eval_public_corpus/              build_manifest.json, README.md, ...
  D1_quant_eval_behavioral_per_case_results/ quant_eval_behavioral_per_case_results.csv, data_dictionary.json, ...
  D2_quant_eval_throughput_telemetry/
  D3_quant_eval_golden_oracle_fixtures/
  D4_quant_eval_run_provenance/
  D5_quant_eval_paired_degradation_statistics/
  D6_quant_eval_family_pass_rates/
  D7_quant_eval_efficiency_and_footprint/
```

`qe-corpus` finds data files by their published names anywhere under the root, so a
flat folder also works for every command except the per-file digest check, which
needs the folder names to locate files listed in `build_manifest.json`. You need
only the datasets a step uses: recomputation needs D1 (plus D4, D5, D6 to compare
against); figures need D5 and D7.

## 2. Install

From a clone of this repository:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install .                 # installs the qe_corpus package and the qe-corpus command
pip install matplotlib        # only for regenerating the figures
pip install '.[pandas]'       # optional: Corpus.dataframe() returns pandas DataFrames
```

The package needs Python 3.9 or later and nothing outside the standard library.
Set `QE_CORPUS_DATA` to the corpus root, or pass `--data` to every command:

```bash
export QE_CORPUS_DATA=~/quant_eval_corpus
qe-corpus summary
```

`summary` lists the runs, models and families, the D1 row count per run and family,
the D3 case count per family, and the row counts of D2, D5, D6 and D7. It warns if
D1 holds run identifiers that D4 does not, which indicates a partial or wrong download.

## 3. Tier one: integrity

```bash
qe-corpus verify
```

checks:

* every file listed in D0's `build_manifest.json` that you hold, by SHA-256 and byte
  count (files you did not download are reported as not present; `--strict` makes that
  an error);
* the D3 fixture file: its SHA-256 against the crosswalk's `is_published_file` row,
  against the `fixtures_sha256` recorded in D4, and against the source-bundle digests
  in `source_bundle_checksums.json`; and its canonical content hash against the
  crosswalk (recipe in [fixture_format.md](fixture_format.md#6-versioning-and-the-crosswalk)).

D7 has a version 1.0.1. If a dataset you downloaded is newer than the D0 record you
verify it against, its files will not match that manifest; verify each dataset
against the D0 version that includes it.

`--bundle DIR` additionally checks a publication bundle (for example the
`publication/` files published alongside a model on Hugging Face) against its own
`checksums.json`; the layout is described by
[`schemas/checksums.schema.json`](../schemas/checksums.schema.json).

## 4. Tier two: recompute D5 and D6 from D1

A family's pass rate is the fraction of its cases in which every gating signal is
true; the gates are published verbatim in D6 `gating_signals` (and in Whitepaper 2,
Table 1). `qe-corpus` reads them from D6 when D6 is present.

For one run:

```bash
qe-corpus paired --run Mistral_Nemo_Instruct_2407_20260814_030505 --check
```

prints, per family: paired n, the pass rate of each lane, the delta (quantized minus
full weight), the discordant counts b (full-weight-only passes) and c
(quantized-only passes), and the exact two-sided McNemar p-value,

    p = min(1, 2 · Σ_{i=0}^{min(b,c)} C(b+c, i) / 2^(b+c)),   p = 1 when b + c = 0,

computed in exact rational arithmetic. `--check` compares every cell with D5:
counts exactly, delta and disagreement rate to 1e-12, and the p-value to a relative
1e-9 (D5 stores the harness's floating-point value, which can differ from the exact
rational in the last bits). It exits 1 on any difference. `--json` emits the cells.

The six runs are:

```
Mistral_Nemo_Instruct_2407_20260814_030505   Mistral-Nemo   F16 vs Q4_K_M
Mistral_Nemo_Instruct_2407_20260815_113254   Mistral-Nemo   F16 vs Q5_K_M
Mistral_Nemo_Instruct_2407_20260816_084553   Mistral-Nemo   F16 vs Q8_0
Qwen2.5_7B_Instruct_20260814_234822          Qwen2.5-7B     F16 vs Q4_K_M
Qwen2.5_14B_Instruct_1M_20260815_220633      Qwen2.5-14B-1M F16 vs Q4_K_M
Qwen2.5_32B_Instruct_20260815_081051         Qwen2.5-32B    F16 vs Q4_K_M
```

Whitepaper 2 Tables 5 and 6 (families degraded / improved / not significant at
p < 0.05):

```bash
qe-corpus significance                 # from D1 per-case rows
qe-corpus significance --source d5     # from D5's published discordance counts
```

The full check is the test suite:

```bash
QE_CORPUS_DATA=~/quant_eval_corpus python -m unittest discover -s tests -v
```

| Test | Checks | Needs |
|---|---|---|
| `D5Internal.test_every_cell` | All 48 D5 rows: delta, disagreements and McNemar p follow from D5's own counts | D5 |
| `D5Internal.test_wp2_table_counts` | Tables 5/6 counts for the six runs | D5 |
| `D5D6Consistency` | All 96 D6 rows: pass counts equal D5's both-pass plus one-lane counts; pass rate and Wilson interval recomputed | D5, D6 |
| `D1ReproducesD5.test_all_cells` | All 48 run × family cells recomputed from D1 match D5 | D1, D5 (D4, D6) |
| `D1ReproducesD5.test_d6_from_d1` | All 96 pass counts recomputed from D1 match D6 | D1, D6 |
| `FixtureIdentity` | D3 file size, SHA-256, canonical hash, 1,600 cases | D3 |
| `test_stats`, `test_synthetic` | The statistics and the CLI on synthetic data | nothing |

Tests whose data is absent are skipped, not failed.

Other tables come straight from published columns rather than from a recomputation:
Table 2 and Table 8 from D4 and the D1 decode columns, Table 3 from file row counts
(`qe-corpus summary`), Table 7 from D7.

### What tier two does not recompute

* **`delta_ci_low` / `delta_ci_high`** (method `paired_multinomial_bonferroni_wilson`).
  D5 names the method but the corpus does not publish its full construction, so these
  tools do not reproduce it. The Wilson intervals in D6 are textbook and are reproduced.
* **The `cluster_adjusted_*` columns.** They depend on a semantic grouping of the
  `json_multistep` fixtures that is not published as data. The unadjusted columns are
  published alongside them so a reader can apply a grouping of their own.
* **`discriminating`.** An evidence-adjudication flag recorded by the harness, not a
  function of the published counts.

## 5. Figures 1–4

`make_figures.py` plots values from each run's `rollup.json`. It reads exactly five
groups of fields, and `build_datasets.py` copies each of them into D5 or D7 unchanged:

| rollup.json field | Published as |
|---|---|
| `paired_runner_comparison.<family>.pass_rate_delta_runner_b_minus_runner_a` | D5 `pass_rate_delta_runner_b_minus_runner_a` |
| `paired_runner_comparison.<family>.pass_rate_delta_ci.{low,high}` | D5 `delta_ci_low`, `delta_ci_high` |
| `paired_runner_comparison.<family>.mcnemar_exact.p_value` | D5 `mcnemar_p_value` |
| `efficiency.artifact_footprint[0].{baseline_bytes,quantized_bytes,compression_ratio,size_reduction_fraction}` | D7 columns of the same names |
| `efficiency.runtime_comparison.headline_runtime_metric.{value,direction}` | D7 `observed_wall_time_ratio`, `wall_time_direction` |

So the figures can be rebuilt from the datasets. `figure-inputs` writes a reduced
`rollup.json` per run containing only those fields, a `corpus_runs.txt`, and a
`hardware_map.txt` taken from D7's `baseline_accelerator` / `quantized_accelerator`
(the same declaration as this repository's `hardware_map.txt`):

```bash
qe-corpus figure-inputs --out build/figure_inputs
python3 make_figures.py --runs-root build/figure_inputs \
                        --bundles-file build/figure_inputs/corpus_runs.txt \
                        --hardware-map build/figure_inputs/hardware_map.txt \
                        --out build/figures
```

Always pass `--runs-root`; the script's default points at the author's own run
store. The output is SVG plus 200-dpi PNG. Built from D5 and D7 v1.0.1, the four PNGs
are pixel-identical to those in [`figures/`](../figures), and the SVGs differ only in
the random element identifiers matplotlib assigns.

## 6. What cannot be reproduced without the private harness

Stated plainly, so no one spends effort discovering it:

* **Re-running the models.** The quant_eval evaluation harness is proprietary and is
  not distributed. Nothing here regenerates a D1 row from a model: no prompt
  construction, decoding, scoring, normalization or gate evaluation code is published.
  The model artifacts are identified by SHA-256 in D4, but holding the weights does
  not let you produce the per-case rows.
* **Bit-reproducibility of the two Modal runs** (Qwen2.5-14B-1M and Qwen2.5-32B). They
  record `decode_seed_status = unsupported`; even the author does not expect re-runs to
  reproduce their token sequences.
* **D2, D4 and D7 values.** They are carried from run files (`throughput_telemetry.jsonl`,
  `run_manifest.json`, `rollup.json`) that are not republished for the corpus runs,
  because those files carry fields excluded for confidentiality. They are traceable
  through the bundle digests, not recomputable.
* **Re-executing `build_datasets.py`** on the corpus. It reads the six source
  publication bundles, which are not republished. The script is published so every
  column operation can be inspected; it cannot be re-run by a reader for these six runs.
* **The fixture oracle and the fuzz generator.** D3 publishes every case and its
  expected answer, but not the rules or code that produced them, so new cases under the
  same contract cannot be generated.
* **Calibration runs.** Their identifiers are disclosed in D4 `calibration_lineage.csv`;
  their data is not published.
* **The delta intervals, cluster adjustment and `discriminating` flag** (section 4).

## Licence

Code in this repository: Apache-2.0. Datasets and figures: CC BY 4.0. Cite the corpus
as Hill, Patrick. *quant_eval Public Corpus*. PBH Applied Systems, LLC, 2026.
[10.5281/zenodo.22009419](https://doi.org/10.5281/zenodo.22009419).
