# Wave 3 Backend Split Plan — for a smaller model

Sequential, one task at a time. After each task: run the verification
commands listed at the end of that task. Do NOT start the next task
until the current one passes verification. Do NOT write code for a
later task while an earlier one is unfinished.

## Global rules (read before starting)

1. **Python interpreter**: always use
   `D:\Downloads\qualcoder-rework\backend\.venv\Scripts\python.exe`
   Run every command from `D:\Downloads\qualcoder-rework\backend`.
2. **No behavior changes.** Move functions between files; never edit
   a function body. Copy-paste the exact text including docstrings.
3. **After every file you create or edit**, run:
   `python -m py_compile <file>`
   If it fails, you made a syntax error — fix it immediately before
   doing anything else.
4. **Never use `write` to append to a file.** If a file already exists
   and you need to change part of it, use the `edit` tool (find-and-
   replace). Use `write` only to create a new file with its full
   content in one shot, or to fully overwrite a file you are replacing.
5. **The `edit` tool requires `oldString` to match exactly once.**
   If the text appears multiple times, include more surrounding lines
   to make it unique, or set `replaceAll: true`.
6. **Line numbers shift as you edit.** Before referencing a line
   number, re-read the file to get the current number.
7. **Do not commit anything.** This is all uncommitted working-tree
   work.

## Current state (verified after server restart)

| Task | Status | Detail |
|---|---|---|
| J5 autocode split | ✅ done | `coding_service.py` 424 lines + `autocode_service.py` 441 lines, barrel re-exports `autocode`/`ai_autocode` |
| J7 importers split | ✅ done | `importers.py` 486 lines + `importers_preview.py` 433 lines, but 2 ruff errors (unused `import asyncio` at top + redefined at line 76) |
| J4 pdf_locate | ⚠️ half-done | `pdf_locate.py` (432 lines) created with all pure functions, BUT `sources.py` (1080 lines) still has every function AND does not import from `pdf_locate.py`. The new file is dead duplicate code. |
| J1 entity.py split | ⏳ not started | `handlers/entity.py` is 938 lines |
| J2 report_service split | ⏳ not started | `report_service.py` is 1471 lines |
| J3 scrape_service split | ⏳ deferred | 1377 lines — tests use ~40 `patch.object(scrape_service, "_YT_*")` and `patch("...scrape_service.subprocess.run")` calls that BREAK if functions move to a submodule. Only safe to split if you also update every test patch target. See Task 6 below. |
| J6 graph_service split | ⏳ not started | `graph_service.py` is 888 lines |

Baseline: 883 pytest pass, mypy clean (115 files), 2 ruff errors.

---

## Task 1: Fix J7 ruff errors (5 minutes)

**Problem**: `src/qualcoder_api/api/v1/importers.py` has `import asyncio`
at line 5 (unused — the asyncio usage was moved to `importers_preview.py`)
and `import asyncio` again at line 76 (used inside `_merge_archive`).

**Steps**:

1. Read `src/qualcoder_api/api/v1/importers.py` lines 1-10.
2. Use `edit` to remove the top-level `import asyncio` line (line 5).
   The `oldString` should be:
   ```
   from __future__ import annotations

   import asyncio
   import os
   ```
   The `newString` should be:
   ```
   from __future__ import annotations

   import os
   ```
3. The `import asyncio` inside `_merge_archive` (around line 76) stays —
   it's a local import and is actually used there.

**Verify**:
```
cd D:\Downloads\qualcoder-rework\backend
.venv\Scripts\python.exe -m ruff check src/qualcoder_api/api/v1/importers.py
.venv\Scripts\python.exe -m py_compile src/qualcoder_api/api/v1/importers.py
```
Both must pass with zero errors.

---

## Task 2: Complete J4 — wire pdf_locate.py into sources.py (20 minutes)

**Problem**: `src/qualcoder_api/services/pdf_locate.py` exists (432 lines)
with all the pure locate functions and request/response models, but
`src/qualcoder_api/api/v1/sources.py` (1080 lines) still defines all of
them too. We need to: (a) remove the duplicates from `sources.py`,
(b) add an import from `pdf_locate.py`, (c) keep the `pdf_text_locate`
endpoint in `sources.py` but have it call the imported functions.

**Step 2a — Read both files**:

Read `src/qualcoder_api/services/pdf_locate.py` fully. Note every
function/class name it defines:
`_normalize_with_spans`, `_normalize_text`, `_word_seq_span`,
`_normalized_match`, `_fuzzy_span`, `_page_anchor`, `_best_run`,
`_similarity_with_context`, `_span_for_selection`, `_run_locate`,
`_fuzzy_locate`, `_locate`, `PdfTextLocateRequest`,
`PdfTextLocateResponse`.

Read `src/qualcoder_api/api/v1/sources.py` fully. Find the exact line
range for each of those names. They are roughly lines 364-841 (the
block between `source_thumbnail` endpoint and `import_source` endpoint,
plus the `pdf_text_locate` endpoint around line 784).

**Step 2b — Check what the endpoint calls**:

Read the `pdf_text_locate` async function (around line 784-841) in
`sources.py`. Note which of the pure functions it calls (likely
`_locate` or `_fuzzy_locate` or `_run_locate`, and
`PdfTextLocateRequest`/`PdfTextLocateResponse`).

**Step 2c — Add the import to sources.py**:

At the top of `sources.py`, after the existing imports, add:
```python
from qualcoder_api.services.pdf_locate import (
    PdfTextLocateRequest,
    PdfTextLocateResponse,
    _locate,
    _fuzzy_locate,
    _normalize_text,
    _normalize_with_spans,
    _word_seq_span,
    _normalized_match,
    _fuzzy_span,
    _page_anchor,
    _best_run,
    _similarity_with_context,
    _span_for_selection,
    _run_locate,
)
```
(Include every name the endpoint uses. If the endpoint only calls
`_locate` and uses the two models, you only need those three — but
including all of them is harmless and avoids NameError if any are
referenced. Check which are actually referenced in the endpoint body
and import exactly those. Ruff will flag unused imports — remove any
you don't use.)

**Step 2d — Remove the duplicate definitions from sources.py**:

Delete these from `sources.py` (use `edit` for each, or read the exact
text block and replace with empty):
- The `class PdfTextLocateRequest` definition
- The `class PdfTextLocateResponse` definition
- All the `def _normalize_with_spans` ... `def _locate` functions
- The `async def pdf_text_locate` endpoint STAYS — do not remove it.

After removal, `sources.py` should be ~600-650 lines.

**Step 2e — Check the endpoint still works**:

The `pdf_text_locate` endpoint must still reference `PdfTextLocateRequest`,
`PdfTextLocateResponse`, and whatever `_locate`/`_fuzzy_locate` it calls.
Those now come from the import. If the endpoint calls a helper that you
didn't import, add it to the import list.

**Verify**:
```
cd D:\Downloads\qualcoder-rework\backend
.venv\Scripts\python.exe -m py_compile src/qualcoder_api/api/v1/sources.py
.venv\Scripts\python.exe -m py_compile src/qualcoder_api/services/pdf_locate.py
.venv\Scripts\python.exe -c "import qualcoder_api.api.v1.sources; from qualcoder_api.services.pdf_locate import _locate, PdfTextLocateRequest; print('OK')"
.venv\Scripts\python.exe -m ruff check src/qualcoder_api/api/v1/sources.py src/qualcoder_api/services/pdf_locate.py
.venv\Scripts\python.exe -m mypy src/qualcoder_api/api/v1/sources.py src/qualcoder_api/services/pdf_locate.py
```
Then find and run the relevant tests:
```
.venv\Scripts\python.exe -m pytest tests/test_api_sources.py -x -q --tb=short
```
(If that test file doesn't exist, search: `grep -rln "pdf_text_locate\|source_pdf\|/sources/" tests` and run whatever you find.)
All must pass. If a test fails with `NameError: name '_locate' is not
defined`, you forgot to import something the endpoint uses.

---

## Task 3: J1 — Split entity.py into sub-domain files (30 minutes)

**Problem**: `src/qualcoder_api/services/audit_undo/handlers/entity.py`
is 938 lines with 30 `_revert_*` handlers covering ~10 feature domains.

**Step 3a — Read entity.py fully** and record:
- The exact import block at the top (lines 1-22):
  ```python
  from __future__ import annotations
  from sqlalchemy import text
  from sqlalchemy.ext.asyncio import AsyncSession
  from ..base import (
      UnsupportedAction, _delete_by_id, _detail, _ensure, _in_params,
      _insert_row, _missing_data, _revert_row_pair, _revert_row_update,
      _sync_capture, _update_row,
  )
  from ..registry import register
  ```
  (Verify the exact names — some may differ.)
- Every `@register("action1", "action2", ...)` decorator and which
  function it's on. Record the action strings exactly — if any change,
  undo breaks.

**Step 3b — Record the handler count BEFORE splitting**:
```
cd D:\Downloads\qualcoder-rework\backend
.venv\Scripts\python.exe -c "from qualcoder_api.services.audit_undo.registry import HANDLERS; print('BEFORE:', len(HANDLERS))"
```
Write down this number. After the split, the count must be identical.

**Step 3c — Create the new files**:

Create these files under `src/qualcoder_api/services/audit_undo/handlers/`.
Each file starts with the SAME import block as entity.py (copy it
verbatim, adjusting nothing). Then paste the exact function text
(including the `@register(...)` decorator) for each handler listed.

- `case_attribute.py` — `_revert_case_link`, `_revert_attribute_type`,
  `_revert_attribute_set`
- `annotation_extras.py` — `_revert_link`, `_revert_comment`,
  `_revert_bookmark`, `_revert_speakers_mark`, `_revert_pseudonym`
- `creative.py` — `_revert_creative`, `_revert_creative_promote`
- `reference.py` — `_revert_reference_delete`,
  `_revert_reference_attach`, `_revert_reference_detach`
- `coder_sync.py` — `_revert_coder`, `_revert_sync_toggle`
- `dictionary_codeset.py` — `_revert_dictionary`,
  `_revert_dictionary_delete`, `_revert_dictionary_import`,
  `_revert_code_set`, `_revert_code_set_members`, `_revert_r_script`,
  `_revert_r_run`
- `qtt_filter_sql.py` — `_revert_qtt_sheet_create`,
  `_revert_qtt_sheet_delete`, `_revert_qtt_item`,
  `_revert_qtt_update`, `_revert_filter`, `_revert_sql`

**Keep in `entity.py`** (the generic CRUD inverters):
- `_revert_entity_create`, `_revert_entity_delete`, `_revert_update`
- Remove every function you moved to the new files. After removal,
  entity.py should be ~150 lines.

**IMPORTANT**: When you paste a function into a new file, include its
`@register(...)` decorator line(s) directly above the `async def`. The
decorator must be the EXACT same action strings as in the original.

**IMPORTANT**: Some functions may use helpers from `base` that aren't in
the standard import block (e.g. `_GRAPH_PKS`, `_coding_table_for`). If a
function you're moving references a name not in the import block, add it
to the import block of the new file. Check by reading the function body.

**Step 3d — Update handlers/__init__.py**:

Read `src/qualcoder_api/services/audit_undo/handlers/__init__.py`.
It currently imports the handler modules so their `@register` decorators
run. It looks something like:
```python
from . import coding, code, source, entity, graph  # noqa: F401
```
Add the new module names:
```python
from . import (  # noqa: F401
    case_attribute, code, coding, coder_sync, creative,
    dictionary_codeset, entity, annotation_extras, graph,
    qtt_filter_sql, reference, source,
)
```
Preserve any existing module names that were already there. The key
rule: EVERY module containing a `@register` decorator must be imported
in `__init__.py`, or those handlers won't be registered.

**Verify**:
```
cd D:\Downloads\qualcoder-rework\backend
.venv\Scripts\python.exe -m py_compile src/qualcoder_api/services/audit_undo/handlers/*.py
.venv\Scripts\python.exe -c "from qualcoder_api.services.audit_undo.registry import HANDLERS; print('AFTER:', len(HANDLERS))"
```
The AFTER number MUST equal the BEFORE number from Step 3b. If it's
less, a `@register` decorator is missing from a new file, or a module
isn't imported in `__init__.py`.

```
.venv\Scripts\python.exe -m pytest tests/test_api_undo.py tests/test_audit_undo_all.py tests/test_audit_undo_robustness.py -x -q --tb=short
.venv\Scripts\python.exe -m ruff check src/qualcoder_api/services/audit_undo/
.venv\Scripts\python.exe -m mypy src/qualcoder_api/services/audit_undo/ 2>&1 | Select-Object -Last 5
```
All must pass. If a test fails with "no undo for X", the handler for
action "X" is missing from the registry — find which file it was
supposed to go in and check its `@register` decorator.

---

## Task 4: J2 — Split report_service.py into reports/ package (45 minutes)

**Problem**: `src/qualcoder_api/services/report_service.py` is 1471
lines with ~32 functions covering many report types.

**Step 4a — Read report_service.py fully** and record:
- The import block at the top (lines 1-22):
  ```python
  from __future__ import annotations
  import re
  from collections import defaultdict
  from typing import cast
  from sqlalchemy import text
  from sqlalchemy.ext.asyncio import AsyncSession
  from qualcoder_api.core.enums import MediaType
  CODING_TABLES = ("code_text_visible", "code_image_visible", "code_av_visible")
  ```
  (Verify exact names.)
- The constant `CODING_TABLES` (line 22) — this is used by many
  functions. It goes in `_shared.py`.
- Any other module-level constants (e.g. `_STOPWORDS` — check if it
  exists; `dictionary_service.py` imports `_STOPWORDS` from here).
- Which functions call which (e.g. `interrater` calls
  `_pair_report`/`_pairwise_summary`; `crosstab` calls `_attr_*`/
  `_crosstab_stats`; `attributes_report` may share helpers with
  `crosstab`). Shared helpers go in `_shared.py`.

**Step 4b — Record consumer imports**:

Consumers (from the grep):
- `api/v1/reports.py`: `from qualcoder_api.services import report_service`
  then calls `report_service.code_frequencies(db)`, `.codes_by_segments`,
  `.comparison_table`, `.cooccurrence`, `.exact_matches`, `.file_summary`,
  `.coder_comparison`, `.attributes_report`, `.interrater`,
  `.code_segments`, `.code_summary`, `.coder_file_comparison`,
  `.code_relations`, `.word_frequencies`, `.charts_data`,
  `.codebook_plain`, `.crosstab`, `.group_compare`, `.code_by_variable`,
  `.summary_table`
- `api/v1/publish.py`: `from qualcoder_api.services import report_service`
  then calls `.code_frequencies`, `.codes_by_segments`,
  `.coder_comparison`, `.codebook_plain`, `.summary_table`
- `api/v1/r_scripts.py`: `from qualcoder_api.services import report_service`
  then calls `.code_frequencies`, `.codes_by_segments`,
  `.coder_comparison`, `.summary_table`
- `services/dictionary_service.py`:
  `from qualcoder_api.services.report_service import _STOPWORDS`
  (line 419 — lazy import inside a function)

The barrel `__init__.py` must re-export EVERY function those consumers
call, PLUS `_STOPWORDS` (if it exists).

**Step 4c — Create the package**:

Create `src/qualcoder_api/services/reports/` with these files. Each
file starts with the same imports as report_service.py (plus any
additional imports that file's functions need). Copy function bodies
byte-for-byte.

- `reports/_shared.py` — `CODING_TABLES` constant, `_STOPWORDS` (if
  exists), and any helper used by 2+ report families:
  `_attr_definition`, `_attr_scope`, `_units_with_values`,
  `_unit_coding_sets`, `_unit_coding_counts`, `_sorted_values`,
  `_crosstab_stats` (check which functions use these — if only
  `crosstab` and `attributes_report` use them, they go here).
- `reports/frequencies.py` — `code_frequencies`, `codes_by_segments`,
  `code_summary`, `word_frequencies`
- `reports/comparison.py` — `comparison_table`, `coder_comparison`,
  `coder_file_comparison`, `group_compare`, `code_by_variable`
- `reports/relations.py` — `cooccurrence`, `code_relations`,
  `exact_matches`
- `reports/interrater.py` — `interrater`, `_krippendorff_alpha`,
  `_pair_report`, `_pairwise_summary`
- `reports/attributes.py` — `attributes_report`, `crosstab` (plus any
  _attr_/_crosstab helpers NOT in _shared)
- `reports/charts.py` — `charts_data`, `codebook_plain`
- `reports/summary.py` — `file_summary`, `code_segments`,
  `summary_table`

Each file that uses `CODING_TABLES` or shared helpers imports them:
```python
from qualcoder_api.services.reports._shared import CODING_TABLES
```
(Use the full path, not relative, to avoid circular import issues.)

**Step 4d — Create the barrel**:

`reports/__init__.py` re-exports every public name:
```python
"""Backwards-compatible barrel for the reports package."""
from qualcoder_api.services.reports.frequencies import (
    code_frequencies, codes_by_segments, code_summary, word_frequencies,
)
from qualcoder_api.services.reports.comparison import (
    comparison_table, coder_comparison, coder_file_comparison,
    group_compare, code_by_variable,
)
from qualcoder_api.services.reports.relations import (
    cooccurrence, code_relations, exact_matches,
)
from qualcoder_api.services.reports.interrater import interrater
from qualcoder_api.services.reports.attributes import (
    attributes_report, crosstab,
)
from qualcoder_api.services.reports.charts import charts_data, codebook_plain
from qualcoder_api.services.reports.summary import (
    file_summary, code_segments, summary_table,
)
from qualcoder_api.services.reports._shared import _STOPWORDS  # if it exists

__all__ = [
    "code_frequencies", "codes_by_segments", "code_summary",
    "word_frequencies", "comparison_table", "coder_comparison",
    "coder_file_comparison", "group_compare", "code_by_variable",
    "cooccurrence", "code_relations", "exact_matches", "interrater",
    "attributes_report", "crosstab", "charts_data", "codebook_plain",
    "file_summary", "code_segments", "summary_table", "_STOPWORDS",
]
```

**Step 4e — Replace the old file**:

Replace `src/qualcoder_api/services/report_service.py` with a thin shim:
```python
"""Backwards-compatible barrel for the reports package."""
from qualcoder_api.services.reports import *  # noqa: F401,F403
from qualcoder_api.services.reports import (  # noqa: F401
    code_frequencies, codes_by_segments, code_summary, word_frequencies,
    comparison_table, coder_comparison, coder_file_comparison,
    group_compare, code_by_variable, cooccurrence, code_relations,
    exact_matches, interrater, attributes_report, crosstab, charts_data,
    codebook_plain, file_summary, code_segments, summary_table,
)
```
(Add `_STOPWORDS` to the explicit list if it exists.)

**Verify**:
```
cd D:\Downloads\qualcoder-rework\backend
.venv\Scripts\python.exe -m py_compile src/qualcoder_api/services/reports/*.py
.venv\Scripts\python.exe -c "import qualcoder_api.services.report_service; from qualcoder_api.services.report_service import code_frequencies, interrater, crosstab, charts_data, summary_table, codebook_plain, attributes_report; print('barrel OK')"
.venv\Scripts\python.exe -m pytest tests/test_api_reports.py tests/test_api_publish.py tests/test_api_r_scripts.py tests/test_api_interrater.py tests/test_api_stats.py -x -q --tb=short
.venv\Scripts\python.exe -m ruff check src/qualcoder_api/services/reports/ src/qualcoder_api/services/report_service.py
.venv\Scripts\python.exe -m mypy src/qualcoder_api/services/reports/ 2>&1 | Select-Object -Last 5
```
All must pass.

---

## Task 5: J6 — Split graph_service.py into core + items + lines (30 minutes)

**Problem**: `src/qualcoder_api/services/graph_service.py` is 888 lines
mixing graph CRUD, item CRUD (5 kinds), line CRUD (3 kinds), and layout.

**Step 5a — Read graph_service.py fully** and record:
- The import block (lines 12-24):
  ```python
  from __future__ import annotations
  import json, math
  from collections import defaultdict, deque
  from typing import Any
  from sqlalchemy import delete, insert, select, text, update
  from sqlalchemy.ext.asyncio import AsyncSession
  from qualcoder_api.core.timeutil import now as _now
  from qualcoder_api.persistence import tables
  ```
  (Verify exact names.)
- The shared helpers: `_row_dict` (26), `_insert` (30), `_capture_row`
  (43), `_capture_delete` (53), `_record_audit` (63). These are used by
  the item/line CRUD functions.
- Which functions belong to which group:
  - **Graph CRUD** (keep in graph_service.py): `list_graphs`,
    `get_graph`, `create_graph`, `update_graph`, `delete_graph`
  - **Item CRUD** (move to graph_items.py): `add_cdct_item`,
    `update_cdct_item`, `delete_cdct_item`, `add_case_item`,
    `update_case_item`, `delete_case_item`, `add_file_item`,
    `update_file_item`, `delete_file_item`, `add_free_item`,
    `update_free_item`, `delete_free_item`, `add_memo_item`,
    `update_memo_item`, `delete_memo_item`
  - **Line CRUD** (move to graph_lines.py): `add_cdct_line`,
    `update_cdct_line`, `delete_cdct_line`, `update_free_line`,
    `delete_free_line`, `add_entity_line`
  - **Layout** (keep in graph_service.py): `_circle_layout`,
    `generate_model`

**Step 5b — Record consumer imports**:

From the grep: NO src/ files import from `graph_service` directly. The
API layer `api/v1/graphs.py` likely imports it. Check:
```
grep -rn "graph_service" src/qualcoder_api/api/
```
The barrel must re-export every name the API layer uses.

**Step 5c — Create graph_items.py**:

`src/qualcoder_api/services/graph_items.py`:
- Same import block as graph_service.py.
- Import the shared helpers:
  ```python
  from qualcoder_api.services.graph_service import (
      _row_dict, _insert, _capture_row, _capture_delete, _record_audit,
  )
  ```
  Wait — this creates a circular import if graph_service.py later
  imports from graph_items.py. So instead: put the shared helpers in a
  new `graph_base.py`, or keep them in graph_service.py and import them
  with a lazy import inside each function.

  **Recommended approach**: Create `graph_base.py` with the 5 helpers.
  Then graph_service.py, graph_items.py, and graph_lines.py all import
  from graph_base.py. No circular deps.

  `src/qualcoder_api/services/graph_base.py`:
  - Same import block as graph_service.py.
  - Paste `_row_dict`, `_insert`, `_capture_row`, `_capture_delete`,
    `_record_audit`.

  Then in `graph_items.py` and `graph_lines.py`:
  ```python
  from qualcoder_api.services.graph_base import (
      _row_dict, _insert, _capture_row, _capture_delete, _record_audit,
  )
  ```
  And in `graph_service.py`, replace the helper definitions with:
  ```python
  from qualcoder_api.services.graph_base import (
      _row_dict, _insert, _capture_row, _capture_delete, _record_audit,
  )
  ```

- Paste all the `add_*_item`/`update_*_item`/`delete_*_item` functions
  with their exact bodies.

**Step 5d — Create graph_lines.py**:

Same structure. Paste all the line CRUD functions.

**Step 5e — Update graph_service.py**:

- Remove the helper definitions (moved to graph_base.py) → import them.
- Remove all item CRUD functions (moved to graph_items.py).
- Remove all line CRUD functions (moved to graph_lines.py).
- Keep: graph CRUD + layout + `generate_model`.
- Add re-export imports for backwards compat:
  ```python
  from qualcoder_api.services.graph_items import (  # noqa: F401
      add_cdct_item, update_cdct_item, delete_cdct_item,
      add_case_item, update_case_item, delete_case_item,
      add_file_item, update_file_item, delete_file_item,
      add_free_item, update_free_item, delete_free_item,
      add_memo_item, update_memo_item, delete_memo_item,
  )
  from qualcoder_api.services.graph_lines import (  # noqa: F401
      add_cdct_line, update_cdct_line, delete_cdct_line,
      update_free_line, delete_free_line, add_entity_line,
  )
  ```
  (Adjust the exact names to match what you actually moved.)

After this, graph_service.py should be ~280-350 lines.

**Verify**:
```
cd D:\Downloads\qualcoder-rework\backend
.venv\Scripts\python.exe -m py_compile src/qualcoder_api/services/graph_service.py src/qualcoder_api/services/graph_items.py src/qualcoder_api/services/graph_lines.py src/qualcoder_api/services/graph_base.py
.venv\Scripts\python.exe -c "import qualcoder_api.services.graph_service; from qualcoder_api.services.graph_service import list_graphs, add_cdct_item, add_entity_line, generate_model; print('barrel OK')"
```
Find graph tests:
```
grep -rln "graph_service\|/graphs/" tests
```
Run whatever you find:
```
.venv\Scripts\python.exe -m pytest tests/test_api_graphs.py -x -q --tb=short
```
(adjust file name to what exists)
```
.venv\Scripts\python.exe -m ruff check src/qualcoder_api/services/graph_service.py src/qualcoder_api/services/graph_items.py src/qualcoder_api/services/graph_lines.py src/qualcoder_api/services/graph_base.py
.venv\Scripts\python.exe -m mypy src/qualcoder_api/services/graph_service.py src/qualcoder_api/services/graph_items.py src/qualcoder_api/services/graph_lines.py src/qualcoder_api/services/graph_base.py 2>&1 | Select-Object -Last 5
```
All must pass.

---

## Task 6: J3 — Split scrape_service.py (DEFERRED — read before deciding)

**Problem**: `src/qualcoder_api/services/scrape_service.py` is 1377
lines. BUT the test file `tests/test_scrape.py` uses ~40 calls like:
```python
patch.object(scrape_service, "_YT_SUBPROCESS_ENABLED", False)
patch("qualcoder_api.services.scrape_service.subprocess.run", ...)
patch("qualcoder_api.services.scrape_service.fetch_url", ...)
patch("qualcoder_api.services.scrape_service.yt_dlp.YoutubeDL", ...)
patch.object(scrape_service, "_YT_TIMEOUT_SECONDS", 0.2)
scrape_service._comment_row(...)
scrape_service._yt_subprocess_enabled()
scrape_service._yt_dlp_extract(...)
```

These patches target the `scrape_service` MODULE's namespace. If you
move `scrape_youtube` to `scrape/youtube.py`, then:
- `patch("qualcoder_api.services.scrape_service.subprocess.run")` patches
  `subprocess.run` in the `scrape_service` module — but `scrape_youtube`
  in `youtube.py` reads `subprocess.run` from `youtube.py`'s globals, so
  the patch has NO EFFECT. Tests will hang or fail.
- `patch.object(scrape_service, "_YT_SUBPROCESS_ENABLED")` patches the
  attribute on the `scrape_service` module object — but
  `_yt_subprocess_enabled()` in `youtube.py` reads
  `_YT_SUBPROCESS_ENABLED` from `youtube.py`'s module globals. Patch
  has no effect.

**If you decide to do this split**, you MUST also update every test
patch in `tests/test_scrape.py` to target the new module path:
- `patch("qualcoder_api.services.scrape.youtube.subprocess.run", ...)`
- `patch.object(scrape_service.youtube, "_YT_SUBPROCESS_ENABLED", ...)`
  (where `scrape_service` is imported as
  `from qualcoder_api.services import scrape_service` and then
  `scrape_service.youtube` is the submodule)

This is ~40 patch calls to update. It's mechanical but error-prone.

**Recommendation**: SKIP this task unless you have time to update all
the test patches. The file is 1377 lines but it's a single domain
(scraping) with clear internal sections. The risk/reward is worse than
the other tasks.

**If you do it**: the split is:
- `scrape/__init__.py` — barrel re-exporting `ScrapeError`,
  `ScrapedContent`, `validate_url`, `detect_mode`, `scrape_url`,
  `scrape_youtube`, `scrape_article`, `scrape_html`, `scrape_pdf`
- `scrape/common.py` — `ScrapeError`, `ScrapedContent`, `validate_url`,
  `detect_mode`, `fetch_url`, `sanitize_name`, tiny helpers
- `scrape/youtube.py` — all youtube functions + `_YT_*` globals
- `scrape/article.py` — `scrape_article`
- `scrape/snapshot.py` — `_fetch_resource`, `_SnapshotRewriter`,
  `scrape_html`
- `scrape/pdf.py` — `scrape_pdf`
- `scrape/dispatch.py` — `scrape_url`
- `scrape_service.py` — thin shim re-exporting everything

Then update EVERY `patch("qualcoder_api.services.scrape_service.X")` in
`tests/test_scrape.py` to `patch("qualcoder_api.services.scrape.youtube.X")`
(for youtube functions) or the appropriate submodule.

**Verify** (if you do it):
```
cd D:\Downloads\qualcoder-rework\backend
.venv\Scripts\python.exe -m pytest tests/test_scrape.py -x -q --tb=short
```
This file has ~70 tests. If patches are mis-targeted, you'll see
hangs (subprocess actually runs) or assertion failures.

---

## Final verification (after all tasks you choose to do)

Run the full backend suite:
```
cd D:\Downloads\qualcoder-rework\backend
.venv\Scripts\python.exe -m pytest tests -q --tb=short
.venv\Scripts\python.exe -m ruff check src
.venv\Scripts\python.exe -m mypy src
```
All must pass: 883+ tests, 0 ruff errors, 0 mypy errors.

Then update `docs/modularity-analysis.md` section J status table:
change ⏳ to ✅ for each completed task, with the final line counts.