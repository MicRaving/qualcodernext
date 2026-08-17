"""Reports sub-package — re-exports every public name for consumers."""

from qualcoder_api.services.reports._shared import (
    _STOPWORDS,
    CODING_TABLES,
    _attr_definition,
    _attr_scope,
    _crosstab_stats,
    _sorted_values,
    _unit_coding_counts,
    _unit_coding_sets,
    _units_with_values,
)
from qualcoder_api.services.reports.attributes import attributes_report, crosstab
from qualcoder_api.services.reports.charts import charts_data, codebook_plain
from qualcoder_api.services.reports.comparison import (
    code_by_variable,
    coder_comparison,
    coder_file_comparison,
    comparison_table,
    group_compare,
)
from qualcoder_api.services.reports.frequencies import (
    code_frequencies,
    code_summary,
    codes_by_segments,
    word_frequencies,
)
from qualcoder_api.services.reports.interrater import (
    _krippendorff_alpha,
    _pair_report,
    _pairwise_summary,
    interrater,
)
from qualcoder_api.services.reports.relations import (
    code_relations,
    cooccurrence,
    exact_matches,
)
from qualcoder_api.services.reports.summary import (
    code_segments,
    file_summary,
    summary_table,
)

__all__ = [
    # Constants / stopwords
    "CODING_TABLES",
    "_STOPWORDS",
    # Shared helpers (for callers that import them directly)
    "_attr_definition",
    "_attr_scope",
    "_crosstab_stats",
    "_krippendorff_alpha",
    "_pair_report",
    "_pairwise_summary",
    "_sorted_values",
    "_unit_coding_counts",
    "_unit_coding_sets",
    "_units_with_values",
    # Attributes
    "attributes_report",
    # Charts / codebook
    "charts_data",
    "code_by_variable",
    # Frequencies
    "code_frequencies",
    "code_relations",
    "code_segments",
    "code_summary",
    "codebook_plain",
    "coder_comparison",
    "coder_file_comparison",
    "codes_by_segments",
    # Comparison
    "comparison_table",
    # Relations
    "cooccurrence",
    "crosstab",
    "exact_matches",
    # Summary
    "file_summary",
    "group_compare",
    # Interrater
    "interrater",
    "summary_table",
    "word_frequencies",
]
