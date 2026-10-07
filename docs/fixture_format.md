# Fixture format: `golden_oracle_fixtures.json` (D3)

This document specifies the layout of the golden oracle fixture set published as
**D3, quant_eval Golden Oracle Fixtures**
([10.5281/zenodo.22010278](https://doi.org/10.5281/zenodo.22010278), concept DOI,
CC BY 4.0). It is written only from the published D3 files, the D4 run provenance
table, and this repository's `build_datasets.py`. It describes what the file
contains. It does not describe how the evaluation harness builds prompts from a
case, scores a response, or normalizes output; that code is proprietary and is
not distributed (Whitepaper 2, §8.5).

Author: Patrick Hill · PBH Applied Systems, LLC

---

## 1. Files in D3

| File | Contents |
|---|---|
| `golden_oracle_fixtures.json` | The locked evaluation fixture set: 1,600 cases, 200 in each of eight task families, with their expected outputs. A byte-for-byte copy of the file one source run read; it is never re-serialized. |
| `fixture_version_crosswalk.csv` | One row per published run: the fixture file digest and version label that run recorded, and the canonical content hash shared by all of them. |
| `source_bundle_checksums.json` | The source bundles' `checksums.json` files, republished verbatim and keyed by `run_id`. |
| `README.md`, `LICENSE`, `CITATION.cff`, `dataset-metadata.json` | Dataset card, licence, citation and Kaggle metadata. |

Identity of the published fixture file (D3 card; Whitepaper 2, §4.2 and §8.2):

| Property | Value |
|---|---|
| Size | 2,733,585 bytes |
| File SHA-256 | `0673b5e5c0fb1b7ba4bdc8c9aa985104260db183453c5708aff14c87823edb97` |
| Canonical content SHA-256 | `b7dd9258ca64c434eb57d32199e610c558a9e24cd0402e419de7ae72624e0cb8` |
| `version` | `v7.22.22` |
| `fixture_schema_version` | `7.22.13` |

`qe-corpus verify` checks all of these (see [reproduce.md](reproduce.md)).

## 2. Top-level object

The file is one UTF-8 JSON object. Key order in the published file:

| Key | JSON type | Published value / meaning |
|---|---|---|
| `version` | string | Version label of the file, e.g. `v7.22.22`. Differs between runs that read content-identical fixtures; see §6. Excluded from the canonical content hash. |
| `fixture_schema_version` | string | Version of the fixture layout described here: `7.22.13`. |
| `comparability` | string | Free-text note recorded with the fixture set. |
| `difficulty_calibration` | string | Identifier of the difficulty-ladder policy recorded with the set. |
| `migration_from` | string | Version label of the fixture set this one was migrated from. |
| `dataset_split` | string | `evaluation`. Matches D4 `fixture_split`. |
| `dataset_role` | string | `locked_unseen_evaluation`. |
| `json_shelf_cases` | **object** | 200 cases of the `json` family, keyed by `case_id` (each key equals the case's own `case_id`). |
| `json_multistep_cases` | array | 200 cases of the `json_multistep` family. |
| `mcq_cases` | array | 200 cases of the `mcq` family. |
| `toolcall_cases` | array | 200 cases of the `toolcall` family. |
| `fuzz_cases` | array | 200 cases of the `fuzz` family. |
| `stateful_followup_cases` | array | 200 cases of the `stateful_followup` family. |
| `toolcall_only_cases` | array | 200 cases of the `toolcall_only` family. |
| `mixed_brief_json_cases` | array | 200 cases of the `mixed_brief_json` family. |

Every key ending in `_cases` holds one family. The count of all cases is the sum of
their lengths (1,600); `build_datasets.py` counts cases exactly this way.

Note that `json_shelf_cases` is an object while the other seven are arrays. A reader
iterating cases should take `.values()` for that one key.

## 3. Families, keys and case identifiers

| D1/D5/D6 `family` | Fixture key | `case_id` pattern | Cases | `difficulty` counts |
|---|---|---|---:|---|
| `json` | `json_shelf_cases` | `json_evaluation_NNN` | 200 | operational 49, boundary 110, stress 41 |
| `json_multistep` | `json_multistep_cases` | `ms_evaluation_<difficulty>_NNN` | 200 | foundation 50, operational 50, stress 50, boundary 50 |
| `mcq` | `mcq_cases` | `mcq_evaluation_<difficulty>_v7224_NNN` | 200 | foundation 52, operational 52, stress 48, boundary 48 |
| `mixed_brief_json` | `mixed_brief_json_cases` | `mixed_evaluation_<difficulty>_v72213_NNN` | 200 | foundation 52, operational 52, stress 48, boundary 48 |
| `stateful_followup` | `stateful_followup_cases` | `state_evaluation_<difficulty>_v7225_NNN` | 200 | foundation 52, operational 52, stress 48, boundary 48 |
| `toolcall` | `toolcall_cases` | `tool_evaluation_<difficulty>_v7227_NNN` | 200 | foundation 40, operational 40, stress 40, boundary 40, adversarial 40 |
| `toolcall_only` | `toolcall_only_cases` | `toolonly_evaluation_<difficulty>_v7229_NNN` | 200 | foundation 20, operational 20, stress 40, boundary 60, adversarial 60 |
| `fuzz` | `fuzz_cases` | `fuzz_evaluation_NNNN` | 200 | foundation 36, operational 39, stress 34, boundary 91 |

`case_id` is unique within its family and across the file. It is the join key to
the per-case results: a D1 row is identified by `run_id + runner + family + case_id`,
and its `case_id` equals the fixture case's `case_id`. Every case appears once per
lane per run in D1.

`difficulty` is one of `foundation`, `operational`, `stress`, `boundary`,
`adversarial`. It labels the case's band on the fixture set's difficulty ladder;
it plays no part in the pass/fail gate.

## 4. Per-family case structure

Types are JSON types. "All cases" means the field is present in every case of
that family in the published file; no family has optional fields.

### 4.1 Shelf-planning families: `json`, `json_multistep`, `fuzz`

These three families pose the same planning domain (Whitepaper 2, §3.2): an initial
state of three shelves and a sequence of arriving items, each to be placed on a
shelf or answered with `STOP`. The fixture records the initial state, the arrivals,
and the oracle's expected answer. **D3 contains no prompt text for these families**;
the prompt is built by the harness from the case fields and is not published.

| Field | Type | `json` | `json_multistep` | `fuzz` | Description |
|---|---|:-:|:-:|:-:|---|
| `case_id` | string | ✓ | ✓ | ✓ | Case identifier (§3). |
| `A0`, `B0`, `C0` | array of 3 integers | ✓ | ✓ | ✓ | Initial state of shelves A, B and C. |
| `arrivals` | array of strings | ✓ | ✓ | ✓ | Arriving items in order; each is one of `H`, `P`, `S`. Length 2–5 (`json`), 1–4 (`json_multistep`), 1–6 (`fuzz`). |
| `difficulty` | string | ✓ | ✓ | ✓ | Difficulty band (§3). |
| `expected_plan` | array of strings | ✓ | ✓ | ✓ | Oracle answer per arrival: `A`, `B`, `C` or `STOP`. Same length as `arrivals` in every published case. |
| `expected_final` | object | ✓ | ✓ | ✓ | Oracle final state: `A`, `B`, `C` (array of 3 integers each), `new_shelf` (integer), `shelf_a_hazard_blocked` (integer). |
| `trace_sha256` | string (64 hex) | ✓ | ✓ | ✓ | SHA-256 recorded for the oracle trace of the case. Whitepaper 2 §5.2 uses agreement of these values across bundles as part of the fixture-equality evidence. |
| `is_feasible` | boolean | | ✓ | | Whether the arrivals can all be placed. 93 true, 107 false. |
| `expected_stop` | boolean | | ✓ | | Whether the expected plan stops. Always the negation of `is_feasible` in the published file. |
| `expected_stop_reason` | string | | ✓ | | `new_shelf_needed` when `expected_stop` is true, otherwise `""`. |
| `expected_stop_step_index` | integer | | ✓ | | Zero-based index of the first `STOP` in `expected_plan`, or `-1` when the plan does not stop. |

What D3 does **not** define, and this document therefore does not state: the meaning
of each position in the three-integer shelf arrays, the capacity and placement
rules the first-fit oracle applies, or how `new_shelf` and `shelf_a_hazard_blocked`
are computed. Those are properties of the oracle, which is not distributed. The
expected values are published so that any response can be compared against them;
the rules that produced them are not. The fuzz generator is likewise not
distributed: its 200 generated cases ship here, but new cases under the same
contract cannot be produced from public material (Whitepaper 2, §8.5).

### 4.2 `mcq`

| Field | Type | Description |
|---|---|---|
| `case_id` | string | Case identifier. |
| `prompt` | string | The question text as recorded in the fixture, including the four lettered options `A)`–`D)`. |
| `correct` | string | Letter of the correct option, `A`–`D` (50 cases each). |
| `correct_answer` | string | Text of the correct option. |
| `answer_contract` | string | `answer_value` in every case: the expected answer is the option's value, not its letter. |
| `difficulty` | string | Difficulty band. |

### 4.3 `mixed_brief_json`

| Field | Type | Description |
|---|---|---|
| `case_id` | string | Case identifier. |
| `prompt` | string | Instruction text as recorded in the fixture. |
| `expected_answer_line` | string | Expected first output line, beginning `RESULT: `. |
| `expected_json` | object | Expected JSON block with exactly the keys `input`, `rule`, `output` (strings). `rule` is one of `lookup`, `promote`, `route`, `advance`. |
| `difficulty` | string | Difficulty band. |

### 4.4 `stateful_followup`

| Field | Type | Description |
|---|---|---|
| `case_id` | string | Case identifier. |
| `turn1_prompt` | string | First-turn instruction as recorded in the fixture. |
| `turn2_prompt` | string | Second-turn instruction as recorded in the fixture. |
| `expected_turn1` | object | Expected JSON state after turn 1. |
| `expected_turn2` | object | Expected JSON state after turn 2. |
| `difficulty` | string | Difficulty band. |

The expected state objects use the key sets `{request, status}` (52 cases),
`{items, status}` (52), `{context, items, status}` (48) and
`{context, flags, items, status}` (48); turn 1 and turn 2 of a case share a key set.

### 4.5 `toolcall` and `toolcall_only`

| Field | Type | `toolcall` | `toolcall_only` | Description |
|---|---|:-:|:-:|---|
| `case_id` | string | ✓ | ✓ | Case identifier. |
| `tool_prompt` | string | ✓ | ✓ | Dispatch-stage instruction as recorded in the fixture, including the tool definitions offered. |
| `tool_schema` | object (JSON Schema) | ✓ | ✓ | Schema of a valid call: an object with required `tool_name` (string enum) and `args` (object), no additional properties. |
| `offered_tools` | array of strings | ✓ | ✓ | Tools offered in the case, from `add`, `subtract`, `multiply`, `divide`, `average`, `maximum`, `minimum`, `echo`. |
| `tool_name` | string | ✓ | ✓ | Expected tool, or `decline` when no offered tool applies. |
| `expected_args` | object | ✓ | ✓ | Expected arguments: `{"a": number, "b": number}`, or `{}` for `decline`. |
| `decline_expected` | boolean | ✓ | ✓ | True for the 20 cases per family whose expected answer is `decline`. |
| `final_prompt_template` | string | ✓ | | Second-stage instruction template as recorded in the fixture. Contains the placeholder `{tool_result}`. |
| `expected_final` | string | ✓ | | Expected second-stage output: a JSON-encoded string of an object with keys `request_id`, `status` (`completed` or `declined`) and `value`. |
| `difficulty` | string | ✓ | ✓ | Difficulty band. |

`toolcall` scores the full lifecycle (dispatch, execution and the final receipt);
`toolcall_only` scores the dispatch alone (Whitepaper 2, §3.2).

### 4.6 Prompt text in D3

Five families carry instruction text in the fixture (`prompt`, `turn1_prompt`,
`turn2_prompt`, `tool_prompt`, `final_prompt_template`). That text is published as
fixture data. It is not necessarily the exact string sent to a model: chat
templates, system prompts and any harness wrapping are outside D3 and are not
documented here. The three shelf-planning families carry no prompt text at all.

## 5. How expected outputs are represented

Every case states its ground truth as data, computed before any model ran:

| Family | Expected output fields |
|---|---|
| `json`, `fuzz` | `expected_plan`, `expected_final` |
| `json_multistep` | `expected_plan`, `expected_final`, `expected_stop`, `expected_stop_reason`, `expected_stop_step_index`, `is_feasible` |
| `mcq` | `correct`, `correct_answer` |
| `mixed_brief_json` | `expected_answer_line`, `expected_json` |
| `stateful_followup` | `expected_turn1`, `expected_turn2` |
| `toolcall` | `tool_name`, `expected_args`, `decline_expected`, `expected_final` |
| `toolcall_only` | `tool_name`, `expected_args`, `decline_expected` |

D1 republishes the comparable expected/observed pairs per row (`expected_plan`,
`got_plan`, `expected_final`, `got_final`, `expected_json`, `got_json`, and so on)
together with the scored signals. Whether a row passes is defined by the family's
gate conjunction, published verbatim in D6 `gating_signals`; the scoring code that
sets each signal is not published.

## 6. Versioning and the crosswalk

Four identifiers are involved, and they are not interchangeable (Whitepaper 2, §3.1):

* `version` (top-level key): a label that changed across releases while case content
  did not.
* `fixture_schema_version`: the layout version, `7.22.13` for every published run.
* `fixtures_sha256`: the SHA-256 of the exact file a run read. Two files that differ
  only in `version` therefore have different digests.
* **Canonical content hash**: SHA-256 over the fixture object with `version` removed,
  serialized with sorted keys and compact separators, UTF-8, non-ASCII characters
  unescaped. It is identical for every published run.

```python
import hashlib, json

def canonical_fixture_hash(obj):
    stripped = {k: v for k, v in obj.items() if k != "version"}
    blob = json.dumps(stripped, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()
```

A different serialization gives a different value; use exactly this recipe.

The six corpus runs recorded three labels and three file digests (from D4):

| Run | `fixture_version_label` | `fixtures_sha256` |
|---|---|---|
| `Mistral_Nemo_Instruct_2407_20260814_030505` | `v7.22.13` | `ae7d7fa90a2ef8d4…` |
| `Qwen2.5_7B_Instruct_20260814_234822` | `v7.22.19` | `2a0f7cdd3d2432d7…` |
| `Mistral_Nemo_Instruct_2407_20260815_113254` | `v7.22.22` | `0673b5e5c0fb1b7b…` |
| `Mistral_Nemo_Instruct_2407_20260816_084553` | `v7.22.22` | `0673b5e5c0fb1b7b…` |
| `Qwen2.5_14B_Instruct_1M_20260815_220633` | `v7.22.22` | `0673b5e5c0fb1b7b…` |
| `Qwen2.5_32B_Instruct_20260815_081051` | `v7.22.22` | `0673b5e5c0fb1b7b…` |

All six share the canonical content hash `b7dd9258ca64c434…`, which is what licenses
pooling them. The file published in D3 is the `v7.22.22` copy.

`fixture_version_crosswalk.csv` columns (written by `build_datasets.py`, `build_d3`):

| Column | Description |
|---|---|
| `run_id` | Published run. |
| `fixtures_sha256` | SHA-256 of the fixture file that run read. |
| `fixture_version_label` | That file's `version` value. |
| `fixture_schema_version` | That file's `fixture_schema_version`. |
| `evaluation_contract_id` | The run's evaluation contract identifier (also in D4). |
| `fixture_split` | The run's fixture split (also in D4). |
| `canonical_content_sha256` | Canonical content hash of that run's file (§6 recipe). |
| `is_published_file` | `true` on the row(s) whose `fixtures_sha256` equals the published file's digest. |

## 7. Checksums

Three layers let a reader confirm the fixture file without trusting this document:

1. **File digest.** Hash the downloaded `golden_oracle_fixtures.json`; it must equal
   the `is_published_file` row of the crosswalk and the value in §1.
2. **Source digest.** The same digest appears for `golden_oracle_fixtures.json` in the
   source bundle records in `source_bundle_checksums.json` (layout:
   [`schemas/checksums.schema.json`](../schemas/checksums.schema.json), one object per
   run under `bundles`), and as `fixtures_sha256` on the D4 rows of the runs that read
   that exact file.
3. **Output digest.** `build_manifest.json` in D0 lists the SHA-256 and byte count of
   every published file, including the D3 files.

The canonical content hash (§6) then shows that the other two digests recorded in D4
differ only in `version`. Doing that comparison byte-for-byte requires those two
earlier files, which are not republished; the crosswalk records their canonical hash
so the claim can be checked by anyone holding them.
