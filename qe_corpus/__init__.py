# Copyright 2026 PBH Applied Systems, LLC
# SPDX-License-Identifier: Apache-2.0
"""qe_corpus: read and recompute the quant_eval public corpus (D0-D7).

Works only on the published datasets. It does not run models and contains no
part of the quant_eval evaluation harness.

    from qe_corpus import Corpus, paired_table
    c = Corpus("path/to/downloaded/corpus")
    rows = paired_table(c, "Mistral_Nemo_Instruct_2407_20260814_030505")
"""
from .constants import FAMILIES, DEFAULT_GATES, DATASET_FILES, CONCEPT_DOIS
from .corpus import Corpus, CorpusError
from .stats import mcnemar_exact_p, wilson_interval, PairedCell
from .paired import paired_table, family_gates, lane_runners

__version__ = "0.1.0"
__author__ = "Patrick Hill"

__all__ = [
    "Corpus", "CorpusError", "FAMILIES", "DEFAULT_GATES", "DATASET_FILES",
    "CONCEPT_DOIS", "mcnemar_exact_p", "wilson_interval", "PairedCell",
    "paired_table", "family_gates", "lane_runners", "__version__",
]
