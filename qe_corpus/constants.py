# Copyright 2026 PBH Applied Systems, LLC
# SPDX-License-Identifier: Apache-2.0
"""Names and identifiers taken from the published corpus and its cards."""

# Task families, in the order the corpus datasets list them.
FAMILIES = ["json", "json_multistep", "mcq", "mixed_brief_json",
            "stateful_followup", "toolcall", "toolcall_only", "fuzz"]

# Gate conjunction per family, as published verbatim in D6 `gating_signals`
# (and in Whitepaper 2, Table 1). A case passes when every listed D1 column is
# true. When D6 is present the CLI reads the gates from D6 and checks them
# against this table.
DEFAULT_GATES = {
    "json": ["schema_ok", "final_equiv_ok", "constraints_ok"],
    "json_multistep": ["parse_ok", "oracle_equiv_ok"],
    "mcq": ["semantic_choice_ok"],
    "mixed_brief_json": ["answer_line_ok", "json_parse_ok", "schema_ok",
                         "semantic_payload_ok"],
    "stateful_followup": ["turn1_parse_ok", "turn2_parse_ok",
                          "turn1_exact_match", "turn2_exact_match"],
    "toolcall": ["stage1_tool_parse_ok", "selection_ok", "stage1_args_ok",
                 "tool_exec_ok", "stage2_evaluable", "final_equiv_ok"],
    "toolcall_only": ["tool_name_ok", "args_ok"],
    "fuzz": ["plan_exact_match", "final_equiv_ok", "constraints_ok"],
}

# D1 family name -> top-level key in golden_oracle_fixtures.json (D3).
FIXTURE_KEYS = {
    "json": "json_shelf_cases",
    "json_multistep": "json_multistep_cases",
    "mcq": "mcq_cases",
    "mixed_brief_json": "mixed_brief_json_cases",
    "stateful_followup": "stateful_followup_cases",
    "toolcall": "toolcall_cases",
    "toolcall_only": "toolcall_only_cases",
    "fuzz": "fuzz_cases",
}

# Published data file names per dataset (Zenodo / Hugging Face / Kaggle layout).
DATASET_FILES = {
    "D0": ["build_manifest.json"],
    "D1": ["quant_eval_behavioral_per_case_results.csv", "data_dictionary.json"],
    "D2": ["quant_eval_throughput_telemetry.jsonl", "data_dictionary.json"],
    "D3": ["golden_oracle_fixtures.json", "fixture_version_crosswalk.csv"],
    "D4": ["quant_eval_run_provenance.csv", "calibration_lineage.csv"],
    "D5": ["quant_eval_paired_degradation_statistics.csv"],
    "D6": ["quant_eval_family_pass_rates.csv"],
    "D7": ["quant_eval_efficiency_and_footprint.csv"],
}

DATASET_FOLDERS = {
    "D0": "D0_quant_eval_public_corpus",
    "D1": "D1_quant_eval_behavioral_per_case_results",
    "D2": "D2_quant_eval_throughput_telemetry",
    "D3": "D3_quant_eval_golden_oracle_fixtures",
    "D4": "D4_quant_eval_run_provenance",
    "D5": "D5_quant_eval_paired_degradation_statistics",
    "D6": "D6_quant_eval_family_pass_rates",
    "D7": "D7_quant_eval_efficiency_and_footprint",
}

# Concept DOIs (always resolve to the latest version), from reserved_dois.json.
CONCEPT_DOIS = {
    "D0": "10.5281/zenodo.22009419",
    "D1": "10.5281/zenodo.22009799",
    "D2": "10.5281/zenodo.22009987",
    "D3": "10.5281/zenodo.22010278",
    "D4": "10.5281/zenodo.22010462",
    "D5": "10.5281/zenodo.22010557",
    "D6": "10.5281/zenodo.22010623",
    "D7": "10.5281/zenodo.22010723",
}

# Two-sided 95% normal quantile used for the Wilson intervals in D6.
Z95 = 1.959963984540054
