"""Imports every handler module so the @register decorators run on import."""
from . import (  # noqa: F401
    annotation_extras,
    case_attribute,
    code,
    coder_sync,
    coding,
    creative,
    dictionary_codeset,
    entity,
    graph,
    qtt_filter_sql,
    reference,
    source,
)
