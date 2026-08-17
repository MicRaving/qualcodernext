"""Interchange importers: RQDA, Taguette, Transana, RIS, Survey CSV, XLSX, SPSS.

Pure async module: no FastAPI imports. ``session_factory`` is an
``async_sessionmaker`` bound to the open project's engine. The source files
(RQDA/Taguette SQLite databases, RIS text, Survey CSV, XLSX workbooks, SPSS
``.sav`` files) are read directly with aiosqlite / the stdlib csv module /
openpyxl / pyreadstat; every write goes through the repositories in
``qualcoder_api.persistence.repositories``.

Importers deduplicate by name against the target project (existing rows are
skipped) and return a result dict. Unreadable or malformed files raise
``ValueError``, which the API layer maps to HTTP 422.
"""

from qualcoder_api.interchange.importers.detect import detect_import_kind
from qualcoder_api.interchange.importers.ris import import_ris
from qualcoder_api.interchange.importers.rqda import import_rqda
from qualcoder_api.interchange.importers.sav import _sav_cell, import_sav
from qualcoder_api.interchange.importers.survey import import_survey
from qualcoder_api.interchange.importers.taguette import import_taguette
from qualcoder_api.interchange.importers.transana import import_transana
from qualcoder_api.interchange.importers.xlsx import (
    _read_xlsx_sheets,
    _sheet_looks_like_survey,
    import_xlsx,
)

__all__ = [
    # Private helpers re-exported for the API preview layer.
    "_read_xlsx_sheets",
    "_sav_cell",
    "_sheet_looks_like_survey",
    "detect_import_kind",
    "import_ris",
    "import_rqda",
    "import_sav",
    "import_survey",
    "import_taguette",
    "import_transana",
    "import_xlsx",
]
