"""Async repositories over the v14 project schema.

Each repository wraps an ``AsyncSession`` and returns Pydantic domain models
(``qualcoder_api.core.models``). SQL follows the legacy behavior exactly;
business-rule quirks (unique-constraint conflicts during merge, orphan
supercatid cleanup) are preserved deliberately.

The implementation was split from a single ``repositories.py`` module into
this package; this barrel re-exports every public name so
``qualcoder_api.persistence.repositories`` keeps working as the canonical
import path.
"""

from qualcoder_api.core.palette import random_code_color
from qualcoder_api.persistence.repo.annotation_repo import AnnotationRepository
from qualcoder_api.persistence.repo.attribute_repo import AttributeRepository
from qualcoder_api.persistence.repo.base import (
    _capture,
    _coding_row,
    _inserted_pk,
    _now,
    _rowdict,
)
from qualcoder_api.persistence.repo.case_repo import CaseRepository
from qualcoder_api.persistence.repo.code_repo import CodeRepository
from qualcoder_api.persistence.repo.coding_repo import CodingRepository
from qualcoder_api.persistence.repo.journal_repo import JournalRepository
from qualcoder_api.persistence.repo.project_repo import ProjectRepository
from qualcoder_api.persistence.repo.source_repo import SourceRepository

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
