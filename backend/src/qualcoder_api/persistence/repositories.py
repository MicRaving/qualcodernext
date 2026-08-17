"""Async repositories over the v14 project schema.

Each repository wraps an ``AsyncSession`` and returns Pydantic domain models
(``qualcoder_api.core.models``). SQL follows the legacy behavior exactly;
business-rule quirks (unique-constraint conflicts during merge, orphan
supercatid cleanup) are preserved deliberately.

Backwards-compatible barrel: the implementation now lives in
``qualcoder_api.persistence.repo`` and is re-exported here so that all
existing ``qualcoder_api.persistence.repositories`` imports keep working.
"""

from __future__ import annotations

import logging

from qualcoder_api.persistence.repo import (
    AnnotationRepository,
    AttributeRepository,
    CaseRepository,
    CodeRepository,
    CodingRepository,
    JournalRepository,
    ProjectRepository,
    SourceRepository,
    _capture,
    _coding_row,
    _inserted_pk,
    _now,
    _rowdict,
    random_code_color,
)

__all__ = [
    "AnnotationRepository",
    "AttributeRepository",
    "CaseRepository",
    "CodeRepository",
    "CodingRepository",
    "JournalRepository",
    "ProjectRepository",
    "SourceRepository",
    "_capture",
    "_coding_row",
    "_inserted_pk",
    "_now",
    "_rowdict",
    "random_code_color",
]

logger = logging.getLogger(__name__)
