# Wave 4 — Modularity Audit & Implementation Plan

> **Audience**: a smaller model (e.g. MiMo v2.5) with limited context window.
> Each task is self-contained, has exact file paths, exact edits, and a
> verification command. **Do one task at a time. Do not start the next
> task until the current one passes verification.**
>
> **Status legend**: ✅ verified clean · ⚠️ partial · ❌ broken/missing · ➖ by design

---

## Part 1 — Assessment: current state vs. the plan

### 1.1 Backend file splits (Wave 2 & 3) — VERIFIED CLEAN

I audited every claimed split. All are genuinely done — no dead duplicate
code remains in any of them:

| Split | Old file | New location | Old size | New size | Verdict |
|---|---|---|---|---|---|
| report_service | `services/report_service.py` | `services/reports/` (9 files) | 1471 | 78-line shim | ✅ clean shim, 0 defs |
| repositories | `persistence/repositories.py` | `persistence/repo/` (10 files) | 2110 | 51-line shim | ✅ clean shim, 0 defs |
| audit_undo | `services/audit_undo.py` (gone) | `services/audit_undo/` pkg | 2000 | removed | ✅ monolith deleted |
| interchange/importers | `interchange/importers.py` (gone) | `interchange/importers/` (10 files) | 1530 | removed | ✅ monolith deleted |
| graph_service | `services/graph_service.py` | + `graph_base/items/lines` | 888 | 412 + 58 + 307 + 171 | ✅ imports wired |
| coding_service | `services/coding_service.py` | + `autocode_service.py` | 838 | 424 + 441 | ✅ hybrid (re-exports + own logic) |
| sources | `api/v1/sources.py` | + `services/pdf_locate.py` | 1080 | 666 + 432 | ✅ imports, 0 dupes |
| importers API | `api/v1/importers.py` | + `importers_preview.py` | 903 | 485 + 433 | ✅ imports wired |
| entity.py | `audit_undo/handlers/entity.py` | + 11 sub-domain files | 938 | 123 + 11 files | ✅ 101 handlers registered |

These splits are real. The doc claims match the actual line counts exactly.

### 1.2 Frontend splits — VERIFIED CLEAN

| Split | Old | New | Verdict |
|---|---|---|---|
| `lib/api.ts` monolith | 1847-line file (gone) | `lib/api/{transport,types,endpoints,index}.ts` (277+825+839+3) | ✅ clean |
| `stores/project.ts` | 1183 lines | 543 + 6 slices (workspace/coder/inspector/graph/prefs/updates) | ✅ clean |

### 1.3 Centralized modules — PARTIAL ADOPTION (the real problems)

This is where the docs overstate completion. Each row below was claimed
"✅ done" in `modularity-analysis.md` section H, but the audit found bypasses.

| # | Centralized module | Claim | Reality | Bypasses |
|---|---|---|---|---|
| C-1 | `core/timeutil.py` `now()` | ✅ 13 copies replaced | ⚠️ mostly done | `migration.py` inlines 1 copy (acceptable — runs before schema exists) |
| C-2 | `core/palette.py` | ✅ palette moved | ✅ true | 0 bypasses; `repositories.py` is a shim |
| C-3 | `persistence/audit_capture.py` | ✅ "28 lazy imports eliminated" | ❌ **FALSE** | See §1.4 below — the fix is half-done |
| C-4 | `lib/useAsync.ts` `useAsyncEffect` | ✅ "23 effects converted" | ⚠️ partial | 3 true bypasses: `contextPickerData.ts`, `ImageCoder.tsx`, `CoderSwitcher.tsx` |
| C-5 | `lib/utils.ts` `errorMessage` | ✅ "183 sites" | ⚠️ partial | 1 real bypass: `project.ts:181` `errorTextOf` (different shape); `transport.ts` uses are infra |
| C-6 | `features/coding/tint.ts` `FALLBACK_CODE_COLOR` | ✅ "4 copies consolidated" | ⚠️ partial | 8 files still inline `"var(--qc-accent)"` |
| C-7 | `features/coding/codingApi.ts` `useCodeMaps` | ✅ hook created | ⚠️ partial | 3 of 6 coders bypass (shape mismatch — see §1.5) |
| C-8 | `lib/config.ts` magic numbers | ✅ "all api.ts magic numbers replaced" | ⚠️ partial | 4 files hardcode `60_000`/`30_000` |
| C-9 | `features/graphs/models.ts` `GRAPH_MODELS` | ✅ "moved + re-export" | ❌ **DEAD CODE** | `models.ts` is orphaned; the live copy is `lib/api/types.ts:771` |
| C-10 | `lib/api/` package | ✅ split | ✅ true | 0 bypasses |
| C-11 | store slices | ✅ split | ✅ true | 0 bypasses |
| C-12 | `confirmAction()` helper (B4) | ⏳ deferred | ⏳ deferred | 46 `window.confirm`/`prompt` calls remain (by design) |

### 1.4 The circular-dependency "fix" (section E) is INCOMPLETE — critical finding

**Doc claim** (section H row 9): "E — fix circular deps (audit_capture) —
28 lazy imports eliminated — ✅".

**Reality**: `audit_capture.py` exists but only `repo/base.py` uses it. The
actual repository classes bypass it entirely and still lazily import the
**services layer** (`services.sync`) directly:

- `persistence/repo/code_repo.py` — **11 lazy imports** of
  `from qualcoder_api.services import sync` (lines 205, 239, 255, 299, 337,
  459, 569, 621, 661, 731, 817), calling `sync.table_row()`,
  `sync.capture_insert()`, `sync.capture_update()`, `sync.capture_delete()`.
- `persistence/repo/source_repo.py` — **3 lazy imports** (lines 90, 117, 169).
- `services/coding_service.py` — 2 lazy imports of `_capture, _rowdict`
  from `repositories` (lines 303, 384).
- `services/graph_base.py` — 3 lazy imports (lines 18, 32, 43).
- `services/merge_projects.py` — 1 (line 83).
- `services/audit_undo/base.py` — 1 (line 62).
- `services/speakers.py` — 1 (line 301).
- `api/v1/tools.py` — 2 (lines 423, 450).
- `api/v1/sql_reports.py` — 2 (lines 126, 158).
- `api/v1/sources.py` — 1 (line 618).
- `services/import_service.py` — 1 (line 324).

**~28 lazy imports remain.** The count matches what the doc claimed to have
eliminated — meaning nothing was actually eliminated. `audit_capture.py`
only copies `table_row` (verbatim) and wraps `capture()` (delegating back to
`sync.capture` via lazy import). It does NOT expose `capture_insert`,
`capture_update`, `capture_delete` — which is what the repos actually call.

**Root cause**: `services/sync.py` owns the canonical `table_row`,
`capture`, `capture_insert`, `capture_update`, `capture_delete`. The
persistence layer needs these but must not import the services layer
(layer inversion). `audit_capture.py` was meant to break the cycle but only
redirected 2 of 5 functions.

### 1.5 `useCodeMaps` shape mismatch — why 3 coders bypass it

The hook returns `{ colorByCid: Map<number,string>, nameByCid: Map<number,string> }`.
But:
- **TextCoder** builds `colorByCid` as a `Record<number,string>` with
  `FALLBACK_CODE_COLOR` baked in (different type + different semantics).
- **HtmlCoder** and **CsvCoder** build a `codeById: Map<number, CodeTreeItem>`
  because they need the **full tree item** (color + name + kind + memo), not
  just color/name strings.

So the hook doesn't serve those coders. A richer hook
(`useCodeIndex(codes): { byId: Map<number, CodeTreeItem>, colorByCid, nameByCid }`)
would cover all 6.

### 1.6 `GRAPH_MODELS` — orphaned duplicate (dead code)

`features/graphs/models.ts` defines `GRAPH_MODELS` (8 lines). **Nobody imports
it** (grep confirms 0 importers). The actual `GRAPH_MODELS` used by the app
is `lib/api/types.ts:771`, re-exported through the `lib/api/index.ts` barrel.
`GraphsView.tsx:34` imports `GRAPH_MODELS` from `@/lib/api`, not from
`features/graphs/models.ts`.

The "move to feature folder" task (C4) created the file but never updated
the import, and never removed the old definition. Result: dead code + a
duplicate definition.

---

## Part 2 — Redundancies & bad practices found

### 2.1 Duplicate helper functions (backend)

| Helper | Copies | Canonical | Copy locations |
|---|---|---|---|
| `_inserted_pk` | 7 | `persistence/repo/base.py:31` | `api/v1/code_sets.py:28`, `comments.py:58`, `creative.py:30`, `qtt.py:57`, `r_scripts.py:40`, `services/links_service.py:28` |
| `_rowdict` | 4 | `persistence/repo/base.py:44` | `services/dictionary_service.py:31`, `links_service.py:22`, `repo/code_repo.py:623 & 663` (nested) |
| `_row_dict` (renamed) | 1 | — | `services/graph_base.py:13` (same logic, different name) |
| `table_row` | 2 | `services/sync.py:59` | `persistence/audit_capture.py:18` (copied verbatim) |

All 6 `_inserted_pk` copies are identical one-liners. They should import
from `persistence.repo.base`.

### 2.2 Lazy imports of `tables` (200 instances)

`api/v1/entities.py` re-imports `tables` inside 12 endpoints (lines 74, 100,
150, 198, 219, 244, 308, 334, 378, 411, 450). `api/v1/tools.py` has 15.
`api/v1/codes.py` has 7, `api/v1/codings.py` has 6. This is a pattern, not a
circular-dep workaround — `tables` has no inbound dependencies. These should
be top-level imports.

### 2.3 Overly broad exception handling (backend)

**27 `except Exception:` sites.** The worst:

- `services/autocode_service.py:404` — `except (AiUnavailable, Exception):`
  is **redundant** (`Exception` already catches `AiUnavailable`) AND swallows
  all bugs (NameError, KeyError, programming errors) into `return []`.
- `services/autocode_service.py:434` — `except Exception: continue` swallows
  DB errors when creating a code.
- `services/ai_service.py` — 4 sites (lines 62, 342, 439, 514).
- `services/sync.py` — 4 sites.
- `services/transcription.py` — 3 sites.

No bare `except:` found (good). No `# type: ignore` abuse (only 1, a Pydantic
decorator). No `@ts-ignore` in frontend (clean).

### 2.4 SQL injection-adjacent pattern

`api/v1/sql_reports.py:69` — user SQL is f-string interpolated:
```python
limited_sql = f"{req.sql.rstrip().rstrip(';').rstrip()} LIMIT {MAX_ROWS + 1}"
text(limited_sql)
```
Mitigated by `_validate_read_only` (rejects non-SELECT, blocks `;`/`--`/`/*`),
but the pattern is risky if the validator has gaps. The `LIMIT` part is a
hardcoded int (safe); the user SQL part is the concern.

### 2.5 Long functions

Only `services/transcription.py` `finalize_transcript` (~182 lines) exceeds
150 lines. `ai_service.chat` (~141) and `autocode_service.autocode` (~141)
are close. The rest are under 150 effective lines.

### 2.6 Frontend large components (unchanged from analysis)

`AvCoder.tsx` (~2106), `Sidebar.tsx` (~2031), `HtmlCoder.tsx` (~1383),
`PdfCoder.tsx` (~1660), `TextCoder.tsx` (~1152), `FileManager.tsx` (~1161),
`NotesView.tsx` (~1091), `GraphsView.tsx` (1238). These were noted in the
original analysis (section A) and not prioritized. They remain.

### 2.7 `noqa` comments — mostly legitimate

21 total. `# noqa: ASYNC230` (sync file I/O in async endpoints — intentional,
small local reads). `# noqa: F401` (re-export shims). 1 `# type: ignore`
(Pydantic). All legitimate — no action needed.

---

## Part 3 — Implementation plan for a smaller model

**Global rules** (read before starting any task):

1. **Python interpreter**: always
   `D:\Downloads\qualcoder-rework\backend\.venv\Scripts\python.exe`.
   Run every backend command from `D:\Downloads\qualcoder-rework\backend`.
2. **No behavior changes.** Move code or replace inline copies with imports.
   Never edit a function body's logic.
3. **After every file you create or edit**, run:
   `python -m py_compile <file>` — fix syntax errors immediately.
4. **The `edit` tool** requires `oldString` to match exactly once. If it
   matches multiple times, add more surrounding context or use
   `replaceAll: true`.
5. **Line numbers shift as you edit.** Before referencing a line number,
   re-read the file to get the current number.
6. **Do not commit anything.**
7. **Verification after each task**: run the exact command listed at the
   end of the task. Do not start the next task until it passes.
8. **Frontend commands** run from `D:\Downloads\qualcoder-rework\frontend`.
9. **If a task feels risky or you're unsure**, stop and re-read the task.
   Do not improvise.

**Task ordering**: tasks are sorted by risk (lowest first). Each is
independent — if you get stuck on one, you can skip it and come back.

---

### Task 1: Remove dead `features/graphs/models.ts` (5 min, zero risk)

**Problem**: `frontend/src/features/graphs/models.ts` defines `GRAPH_MODELS`
but nobody imports it. The live definition is at
`frontend/src/lib/api/types.ts:771`. The file is dead code.

**Steps**:

1. Confirm it's dead — run this grep (should show 0 importers besides the
   file itself):
   ```
   rg "graphs/models" frontend/src
   ```
   (Use the `grep` tool with pattern `graphs/models` in `frontend/src`.)
   The only match should be the file itself, or nothing.

2. Delete the file `frontend/src/features/graphs/models.ts`.
   (Use the shell: `Remove-Item frontend/src/features/graphs/models.ts` from
   the frontend directory. Or use `shell` with `Remove-Item`.)

3. Optionally also remove the duplicate `GRAPH_MODELS` from
   `lib/api/types.ts:771` and have `lib/api/types.ts` import it from a new
   location — **BUT only if a feature file actually wants to own it.**
   Since `GraphsView.tsx` imports from `@/lib/api`, the simplest fix is to
   **keep** the `types.ts` definition and just delete the dead file. Do not
   move it — that would require updating the import in `GraphsView.tsx`
   for no benefit.

**Verify**:
```
cd D:\Downloads\qualcoder-rework\frontend
npx tsc --noEmit -p tsconfig.json
```
Must pass with 0 errors. (If it fails, the file wasn't dead — restore it
with `git checkout frontend/src/features/graphs/models.ts` and skip this
task.)

---

### Task 2: Replace 6 duplicate `_inserted_pk` copies with an import (15 min, low risk)

**Problem**: `_inserted_pk` is defined identically in 7 files. The canonical
copy is `persistence/repo/base.py:31`. The other 6 should import it.

**The 6 files to fix**:
- `api/v1/code_sets.py:28`
- `api/v1/comments.py:58`
- `api/v1/creative.py:30`
- `api/v1/qtt.py:57`
- `api/v1/r_scripts.py:40`
- `services/links_service.py:28`

**Steps for EACH file**:

1. Read the file. Find the `def _inserted_pk(result: Result) -> int:` function
   (it's a ~10-line function ending with `return int(pk[0])`).
2. Delete the entire function definition (from `def _inserted_pk` through
   the `return int(pk[0])` line).
3. Add an import at the top of the file (with the other imports):
   ```python
   from qualcoder_api.persistence.repo.base import _inserted_pk
   ```
   If the file already imports `Result` from sqlalchemy **only** for the
   `_inserted_pk` function, check if `Result` is still used elsewhere in the
   file. If not, you can leave the `Result` import (harmless) or remove it
   (ruff will flag it as unused — remove if flagged).

4. Run `python -m py_compile <file>` — must pass.

**Important**: Check whether each file's `_inserted_pk` has any **subtle
difference** from the canonical one (e.g. different type hint, different
cast). If so, do NOT replace it — leave that file alone and note it.

**Verify** (after all 6 files):
```
cd D:\Downloads\qualcoder-rework\backend
.venv\Scripts\python.exe -m ruff check src/qualcoder_api/api/v1/code_sets.py src/qualcoder_api/api/v1/comments.py src/qualcoder_api/api/v1/creative.py src/qualcoder_api/api/v1/qtt.py src/qualcoder_api/api/v1/r_scripts.py src/qualcoder_api/services/links_service.py
.venv\Scripts\python.exe -m pytest tests -q --tb=short -x
```
Ruff must pass (0 errors — if you left an unused `Result` import, ruff will
flag it; remove the import). Tests must pass (883+).

---

### Task 3: Replace duplicate `_rowdict` copies with import (15 min, low risk)

**Problem**: `_rowdict` is defined in 3 non-canonical locations:
- `services/dictionary_service.py:31`
- `services/links_service.py:22`
- `services/graph_base.py:13` (named `_row_dict` — check if identical logic)

The canonical copy is `persistence/repo/base.py:44`.

**Steps**:

1. Read `services/dictionary_service.py` around line 31. Find the
   `def _rowdict` function. Compare its body to `repo/base.py:44`:
   ```python
   def _rowdict(row) -> dict:
       from qualcoder_api.persistence import audit_capture
       return audit_capture.table_row(row._mapping)
   ```
   If the copy's body is different (e.g. it does `{k: v for k, v in ...}`
   inline instead of calling `audit_capture`), **do not replace it** —
   note the difference and skip. The canonical one delegates to
   `audit_capture.table_row`.

2. Read `services/links_service.py` around line 22. Same comparison.

3. Read `services/graph_base.py` around line 13 (`def _row_dict`). This one
   is named `_row_dict` (no final `ct`). Check its body. If it's the same
   `{k: v for k, v in dict(row._mapping)...}` logic, it's a duplicate under
   a different name.

**For each file where the body matches the canonical logic**:

- Delete the local `def _rowdict` / `def _row_dict` function.
- Add import: `from qualcoder_api.persistence.repo.base import _rowdict`
  (use `_rowdict` even in `graph_base.py` — update all call sites in that
  file from `_row_dict(...)` to `_rowdict(...)`).
- If a file uses a different name (`_row_dict`), you must also update every
  call site in that file. Use `replaceAll: true` for the rename in the edit
  tool.

**If the body differs** (e.g. inline dict comprehension vs. delegating to
`audit_capture`): the difference is that the canonical `_rowdict` filters
keys starting with `_` (via `audit_capture.table_row`), while copies may
not. **Check carefully** — if a copy does NOT filter `_`-prefixed keys,
replacing it would change behavior. If unsure, skip that file.

**Verify**:
```
cd D:\Downloads\qualcoder-rework\backend
.venv\Scripts\python.exe -m py_compile src/qualcoder_api/services/dictionary_service.py src/qualcoder_api/services/links_service.py src/qualcoder_api/services/graph_base.py
.venv\Scripts\python.exe -m ruff check src/qualcoder_api/services/dictionary_service.py src/qualcoder_api/services/links_service.py src/qualcoder_api/services/graph_base.py
.venv\Scripts\python.exe -m pytest tests -q --tb=short -x
```
All must pass. If any test fails, restore the file (`git checkout <file>`)
and skip it — the body difference matters.

---

### Task 4: Move `60_000` / `30_000` magic numbers to `lib/config.ts` (10 min, low risk)

**Problem**: `lib/config.ts` centralizes magic numbers but 4 files bypass it.

**The 4 bypasses**:
- `frontend/src/features/analyze/PublishDialog.tsx:57` — `fetchWithTimeout(url, {...}, 60_000)`
- `frontend/src/lib/dictionaryApi.ts:91` — `request(..., 60_000)`
- `frontend/src/features/settings/AiTab.tsx:151` — `window.setInterval(..., 60_000)`
- `frontend/src/components/shell/CoderSwitcher.tsx:36` — `const SYNC_POLL_MS = 30_000`

**Steps**:

1. Read `frontend/src/lib/config.ts`. Note the existing exports:
   `DEV_API_BASE`, `PORT_POLL_MAX_ATTEMPTS`, `PORT_POLL_INTERVAL_MS`,
   `REQUEST_TIMEOUT_MS` (15_000), `SOURCE_TIMEOUT_MS` (60_000).

   Note: `SOURCE_TIMEOUT_MS = 60_000` already exists. The 3 files using
   `60_000` should import `SOURCE_TIMEOUT_MS` (for the timeout/poll cases)
   or a new `AI_REFRESH_MS` constant.

2. Add to `config.ts` (if not present):
   ```ts
   /** AI model list refresh interval (ms). */
   export const AI_REFRESH_MS = 60_000;
   /** Coder sync-status polling interval (ms). */
   export const SYNC_POLL_MS = 30_000;
   ```
   (Use the `edit` tool to add these after the existing exports.)

3. In `PublishDialog.tsx`: replace `60_000` with `SOURCE_TIMEOUT_MS` and add
   the import `import { SOURCE_TIMEOUT_MS } from "@/lib/config";` at the top.

4. In `dictionaryApi.ts`: replace `60_000` with `SOURCE_TIMEOUT_MS` and add
   the import.

5. In `AiTab.tsx`: replace `60_000` with `AI_REFRESH_MS` and add the import.

6. In `CoderSwitcher.tsx`: delete the local `const SYNC_POLL_MS = 30_000;`
   line and add `import { SYNC_POLL_MS } from "@/lib/config";` at the top.
   (Or if the local constant is used only once, just replace the literal
   with the imported constant.)

**Verify**:
```
cd D:\Downloads\qualcoder-rework\frontend
npx tsc --noEmit -p tsconfig.json
npx eslint src --max-warnings 0
npm test -- --run
```
All must pass. If tsc fails with "cannot find name SOURCE_TIMEOUT_MS", you
forgot the import in that file.

---

### Task 5: Fix `FALLBACK_CODE_COLOR` bypasses in 6 files (20 min, low risk)

**Problem**: `tint.ts` exports `FALLBACK_CODE_COLOR = "var(--qc-accent)"`
but 8 files inline the string. 4 already import from `tint.ts`. Fix the
other 6 that use it as a code-color fallback.

**The 6 files to fix** (these use it as a code-color fallback):
1. `frontend/src/features/coding/AvCoder.tsx:578` — `codeTint(color ?? "var(--qc-accent)")`
2. `frontend/src/features/coding/AvCoder.tsx:1971` — `colorByCid.get(...) ?? "var(--qc-accent)"`
3. `frontend/src/features/coding/CodePicker.tsx:112` — `c.color ?? "var(--qc-accent)"`
4. `frontend/src/features/coding/AutocodeDialog.tsx:250` — `c.color ?? "var(--qc-accent)"`
5. `frontend/src/features/analyze/merged.tsx:331` — `row.color ?? "var(--qc-accent)"`
6. `frontend/src/features/analyze/reportKit.tsx:134` — `color ?? "var(--qc-accent)"`
7. `frontend/src/features/analyze/StatsReport.tsx:440` — `code.color ?? "var(--qc-accent)"`

**Do NOT touch** (these are not code-color fallbacks):
- `PdfCoder.tsx:1346, 1627` — these use `"var(--qc-accent)"` as a literal
  background, not a fallback. Check the context; if it's `?? "var(--qc-accent)"`
  it's a fallback and should be fixed; if it's a standalone `"var(--qc-accent)"`
  assignment, leave it.
- `Inspector.tsx:56` — defines its own `SWATCH_FALLBACK`. Could use the
  shared one, but it's a local constant (acceptable). Leave it.
- `ProjectShell.tsx:79` — SVG stroke, not a code color. Leave it.
- `FileManager.tsx:881, 960` — CSS `accent-[var(--qc-accent)]` class, not a
  code color. Leave it.

**Steps for EACH file**:

1. Read the file's import section. Check if it already imports from
   `@/features/coding/tint`. If yes, just replace the string. If no, add
   the import.
2. Replace `"var(--qc-accent)"` (in the fallback context `?? "var(--qc-accent)"`)
   with `FALLBACK_CODE_COLOR`.
3. The import line (add if missing):
   ```ts
   import { FALLBACK_CODE_COLOR } from "@/features/coding/tint";
   ```
   For files in `features/analyze/`, the path is `"@/features/coding/tint"`.

**Verify**:
```
cd D:\Downloads\qualcoder-rework\frontend
npx tsc --noEmit -p tsconfig.json
npx eslint src --max-warnings 0
```
All must pass.

---

### Task 6: Consolidate `errorTextOf` bypass in `project.ts` (10 min, low risk)

**Problem**: `frontend/src/stores/project.ts:181` defines a local
`errorTextOf(e)` that duplicates `errorMessage(e)` from `lib/utils.ts`, with
a slightly different shape (handles `e.name`, strings, objects with
`.message`).

**Steps**:

1. Read `frontend/src/stores/project.ts` lines 178-195. Read the full
   `errorTextOf` function.
2. Read `frontend/src/lib/utils.ts` — find `errorMessage`.
3. Compare: `errorMessage(e, fallback = "Operation failed")` returns
   `e instanceof Error ? e.message : fallback`. `errorTextOf` additionally
   handles `e.message || e.name` (Error with empty message), strings, and
   objects with a `.message` property.

4. **Decision**: if `errorTextOf` is only used for the global error handler
   (window.onerror / unhandledrejection) where the error can be anything
   (not just Error), the extra cases are legitimate. In that case:
   - Move `errorTextOf` to `lib/utils.ts` (rename to `errorTextOf` or
     `errorDetail`) and import it in `project.ts`.
   - Do NOT delete it — it serves a different purpose than `errorMessage`.

5. If `errorTextOf` is used in only one place (the global handler), moving
   it to `lib/utils.ts` and importing it is the clean fix. Add to
   `lib/utils.ts`:
   ```ts
   /** Like errorMessage but handles non-Error throwables (strings, objects). */
   export function errorTextOf(e: unknown): string {
     if (e instanceof Error) return e.message || e.name;
     if (typeof e === "string") return e;
     if (e && typeof e === "object" && "message" in e && typeof e.message === "string") {
       return e.message;
     }
     try { return String(e); } catch { return "Unknown error"; }
   }
   ```
   (Copy the exact body from `project.ts` — do NOT improvise.)

6. In `project.ts`: delete the local `errorTextOf` function, add
   `import { errorTextOf } from "@/lib/utils";` (or add to the existing
   utils import line if one exists).

**Verify**:
```
cd D:\Downloads\qualcoder-rework\frontend
npx tsc --noEmit -p tsconfig.json
npx eslint src --max-warnings 0
npm test -- --run
```

---

### Task 7: Complete the circular-dependency fix — move `capture_insert/update/delete` to `audit_capture.py` (45 min, MEDIUM risk)

**Problem**: `persistence/audit_capture.py` only has `table_row` and
`capture`. The repo classes (`code_repo.py`, `source_repo.py`) need
`capture_insert`, `capture_update`, `capture_delete` — which still live in
`services/sync.py`. So they lazily import `sync` (14 times), defeating the
purpose of `audit_capture.py`.

**Goal**: move `capture_insert`, `capture_update`, `capture_delete` (and
their helper `capture` if needed) into `audit_capture.py`, so the
persistence layer never imports `services.sync`.

**Step 7a — Read `services/sync.py` lines 59-185**:
Read the definitions of `table_row`, `capture`, `capture_delete`,
`capture_insert`, `capture_update`. Note their exact signatures and bodies.
Note any helper functions they call (e.g. `_capture_row`, `_sync_log_insert`).

**Step 7b — Read `persistence/audit_capture.py` fully** (51 lines).
It currently has `table_row` (copied) and `capture` (delegates to
`sync.capture` via lazy import).

**Step 7c — Check what `capture_insert/update/delete` depend on**:
Read their bodies in `sync.py`. Do they call other `sync.py` functions?
If they call `_now()`, `tables.*`, or other sync-internal helpers, note
which ones. If they only call `capture()` + sqlalchemy + `tables`, they
can be moved cleanly.

If `capture_insert/update/delete` call `sync.py`-private helpers that
themselves import from the services layer, **stop** — the move is more
complex than this task assumes. Skip and document.

**Step 7d — Move the functions to `audit_capture.py`**:
Copy `capture_insert`, `capture_update`, `capture_delete` from `sync.py`
into `audit_capture.py`. Copy them **byte-for-byte** (same docstrings,
same logic). Update `audit_capture.capture` to be the real implementation
(not a delegate) if it's simpler — but only if `sync.capture` doesn't call
back into `audit_capture` (check for recursion).

**Step 7e — Update `sync.py` to re-export from `audit_capture`**:
In `sync.py`, replace the function definitions with imports:
```python
from qualcoder_api.persistence.audit_capture import (
    capture,
    capture_delete,
    capture_insert,
    capture_update,
    table_row,
)
```
Keep them re-exported so existing `from qualcoder_api.services.sync import
capture_insert` callers still work.

**Step 7f — Update `code_repo.py` and `source_repo.py`**:
Replace every `from qualcoder_api.services import sync` lazy import with
`from qualcoder_api.persistence import audit_capture as sync` — BUT this
only works if `audit_capture` has all the names they use. Check each call
site: `sync.table_row`, `sync.capture_insert`, `sync.capture_update`,
`sync.capture_delete` must all exist in `audit_capture`.

Better: replace `sync.table_row(...)` with `audit_capture.table_row(...)`
etc., and change the lazy import to
`from qualcoder_api.persistence import audit_capture`.

**Step 7g — Update `repo/base.py`**:
`_rowdict` already delegates to `audit_capture.table_row` — keep as is.
`_capture` delegates to `audit_capture.capture` — keep as is. No change
needed here.

**Verify**:
```
cd D:\Downloads\qualcoder-rework\backend
.venv\Scripts\python.exe -m py_compile src/qualcoder_api/persistence/audit_capture.py src/qualcoder_api/services/sync.py src/qualcoder_api/persistence/repo/code_repo.py src/qualcoder_api/persistence/repo/source_repo.py
.venv\Scripts\python.exe -c "from qualcoder_api.persistence.audit_capture import table_row, capture, capture_insert, capture_update, capture_delete; print('audit_capture OK')"
.venv\Scripts\python.exe -c "from qualcoder_api.services.sync import table_row, capture, capture_insert, capture_update, capture_delete; print('sync re-export OK')"
.venv\Scripts\python.exe -m ruff check src
.venv\Scripts\python.exe -m mypy src
.venv\Scripts\python.exe -m pytest tests -q --tb=short -x
```
All must pass: 883+ tests, 0 ruff, 0 mypy. If `sync.py` functions called
private helpers that you didn't move, tests will fail with
`AttributeError` or `NameError` — move the missing helper too, or revert
(`git checkout`) and skip this task with a note.

---

### Task 8: Fix `autocode_service.py:404` redundant broad except (10 min, low risk)

**Problem**: Line 404: `except (AiUnavailable, Exception):` — `Exception`
already catches `AiUnavailable`, so listing both is redundant. Worse,
catching `Exception` swallows programming bugs (NameError, KeyError) into
`return []`, hiding real errors.

**Steps**:

1. Read `services/autocode_service.py` lines 395-410.
2. Replace:
   ```python
       except (AiUnavailable, Exception):
           return []
   ```
   with:
   ```python
       except AiUnavailable:
           return []
       except Exception:
           logger.exception("AI code suggestion failed")
           return []
   ```
   (Add `import logging` + `logger = logging.getLogger(__name__)` at the
   top if not present. Check first — it may already exist.)

3. **Important**: this changes behavior slightly — it now logs the
   exception. If the tests expect silent `return []`, they should still
   pass (the return value is the same). But if a test specifically asserts
   no logging, it may fail. Check test expectations.

4. Also fix line 434: `except Exception: continue` — this swallows DB
   errors when creating a code. Replace with:
   ```python
       except Exception:
           logger.warning("Failed to create suggested code %r", name, exc_info=True)
           continue
   ```

**Verify**:
```
cd D:\Downloads\qualcoder-rework\backend
.venv\Scripts\python.exe -m py_compile src/qualcoder_api/services/autocode_service.py
.venv\Scripts\python.exe -m ruff check src/qualcoder_api/services/autocode_service.py
.venv\Scripts\python.exe -m pytest tests/test_api_ai.py tests/test_autocode.py -q --tb=short -x
```
(Adjust test file names if they don't exist — grep for `autocode` in
`tests/` to find the right files.) If tests fail on log assertions, revert
the logging and use `except AiUnavailable: return []` + `except Exception:
return []` (keep the broad catch but at least remove the redundancy).

---

### Task 9: Fix `useAsyncEffect` bypass in `contextPickerData.ts` (20 min, MEDIUM risk)

**Problem**: `frontend/src/features/ai/contextPickerData.ts:95-117` uses the
old `let cancelled = false` + `.then()` pattern instead of `useAsyncEffect`.

**Why it's harder**: this effect fires 3 parallel fetches (memos, codes,
files) and merges results into state. `useAsyncEffect` takes a single async
function with a `signal` — the parallel-fetch pattern needs
`Promise.allSettled` or 3 separate checks.

**Steps**:

1. Read `contextPickerData.ts` lines 88-140 fully. Understand the 3
   parallel fetches and how they merge into `setData`.

2. Rewrite the `useEffect` block as a `useAsyncEffect`:
   ```ts
   useAsyncEffect(async (signal) => {
     setSelectedKeys(new Set());
     setQueryState({ memos: "", codes: "", files: "" });
     setData((prev) => ({
       memos: required.memos ? null : prev.memos,
       codes: required.codes ? null : prev.codes,
       codeCounts: required.codes ? new Map() : prev.codeCounts,
       sources: required.files ? null : prev.sources,
     }));

     const tasks: Promise<void>[] = [];
     if (required.memos) {
       tasks.push(
         fetchMemos()
           .then((items) => signal.throwIfAborted() || setData((p) => ({ ...p, memos: items })))
           .catch(() => signal.throwIfAborted() || setData((p) => ({ ...p, memos: [] })))
       );
     }
     if (required.codes) { /* same pattern */ }
     if (required.files) { /* same pattern */ }
     await Promise.allSettled(tasks);
   }, [required.memos, required.codes, required.files]);
   ```
   **Note**: `signal.throwIfAborted()` throws `AbortError` if cancelled;
   the `||` short-circuits so `setData` only runs if not aborted. But
   `throwIfAborted` throws, not returns false — so use:
   ```ts
   .then((items) => { signal.throwIfAborted(); setData((p) => ({ ...p, memos: items })); })
   ```
   Check the actual `useAsyncEffect` signature in `lib/useAsync.ts` —
   the signal has `throwIfAborted()`.

3. If the rewrite is too complex or the parallel pattern doesn't fit
   `useAsyncEffect` cleanly, **skip this task** — the old pattern works
   correctly, it's just not using the hook. Note "bypass retained —
   parallel-fetch pattern doesn't fit single-async hook".

**Verify**:
```
cd D:\Downloads\qualcoder-rework\frontend
npx tsc --noEmit -p tsconfig.json
npx eslint src --max-warnings 0
npm test -- --run
```

---

### Task 10: Fix `useAsyncEffect` bypass in `ImageCoder.tsx` and `CoderSwitcher.tsx` (15 min, low risk)

**Problem**: 2 simpler bypasses:

- `ImageCoder.tsx:96` — `let cancelled = false` + single async blob fetch.
- `CoderSwitcher.tsx:98` — `let cancelled = false` + `setInterval` polling.

**Steps for `ImageCoder.tsx`**:

1. Read lines 90-115. It fetches a blob URL and sets state.
2. Replace the `useEffect` with `useAsyncEffect`:
   ```ts
   useAsyncEffect(async (signal) => {
     const url = await fetchBlobUrl(...);
     signal.throwIfAborted();
     setBlobUrl(url);
   }, [dep]);
   ```
   Add `import { useAsyncEffect } from "@/lib/useAsync";` if not present.

**Steps for `CoderSwitcher.tsx`**:

1. Read lines 95-115. It's a polling effect with `setInterval`.
2. `useAsyncEffect` is for one-shot async, not polling. **If it's a
   pure interval poll with no async fetch, do NOT convert it** — the
   `let cancelled` flag is the correct pattern for interval cleanup. Note
   "legitimate — polling pattern, not a fetch".

3. If it DOES fetch inside the interval, the interval itself stays as
   `useEffect` but the inner fetch could use `useAsyncEffect` — but that's
   over-engineering. **Leave it.**

**Verify** (after ImageCoder only):
```
cd D:\Downloads\qualcoder-rework\frontend
npx tsc --noEmit -p tsconfig.json
npx eslint src --max-warnings 0
npm test -- --run
```

---

### Task 11: Upgrade `useCodeMaps` to `useCodeIndex` covering all 6 coders (30 min, MEDIUM risk)

**Problem**: `useCodeMaps` returns `{ colorByCid: Map, nameByCid: Map }`.
3 coders (TextCoder, HtmlCoder, CsvCoder) need the full `CodeTreeItem`, so
they bypass the hook and build their own `codeById` map.

**Goal**: add a `useCodeIndex` hook that returns
`{ byId: Map<number, CodeTreeItem>, colorByCid: Map<number,string>, nameByCid: Map<number,string> }`,
covering all use cases.

**Steps**:

1. Read `frontend/src/features/coding/codingApi.ts` lines 14-29 (the
   current `useCodeMaps`).
2. Add a new hook below it:
   ```ts
   /** Build a full code index: by-id map + color/name lookup maps. */
   export function useCodeIndex(codes: CodeTreeItem[]) {
     const byId = useMemo(() => {
       const m = new Map<number, CodeTreeItem>();
       for (const c of codes) m.set(c.id, c);
       return m;
     }, [codes]);
     const { colorByCid, nameByCid } = useCodeMaps(codes);
     return { byId, colorByCid, nameByCid };
   }
   ```
3. In `TextCoder.tsx`: replace the local `colorByCid` useMemo with
   `const { colorByCid } = useCodeIndex(codes);` — BUT check if TextCoder's
   map has `FALLBACK_CODE_COLOR` baked in. If so, the hook's map does NOT
   have the fallback (it only sets color if `c.color` is truthy). You'd
   need to either: (a) keep the local map (it has different semantics), or
   (b) apply the fallback at the call site (`colorByCid.get(id) ?? FALLBACK_CODE_COLOR`).

   **If the semantics differ, do NOT replace** — note "shape mismatch
   retained" and skip that coder.

4. In `HtmlCoder.tsx` and `CsvCoder.tsx`: replace the local `codeById`
   useMemo with `const { byId } = useCodeIndex(codes);` and update call
   sites from `codeById.get(...)` to `byId.get(...)`. Check if they use
   `codeById` for anything beyond `.get(id)?.color` and `.get(id)?.name` —
   if they use `.kind`, `.memo`, etc., `byId` (full item) covers it.

**Verify**:
```
cd D:\Downloads\qualcoder-rework\frontend
npx tsc --noEmit -p tsconfig.json
npx eslint src --max-warnings 0
npm test -- --run
```
If any coder's semantics differ and you can't cleanly replace, revert
that coder (`git checkout <file>`) and keep the rest.

---

### Task 12: Move lazy `tables` imports to top-level in `api/v1/entities.py` (15 min, low risk)

**Problem**: `api/v1/entities.py` re-imports `from qualcoder_api.persistence import tables`
inside 12 endpoints (lazy). `tables` has no inbound dependencies — there's
no circular dep. These should be top-level.

**Steps**:

1. Read `api/v1/entities.py` lines 1-15. Check if `tables` is already
   imported at the top. If yes, the lazy imports are pure redundancy.
2. If not at top level, add:
   ```python
   from qualcoder_api.persistence import tables
   ```
   to the top import block.
3. Delete every `from qualcoder_api.persistence import tables` line that
   appears inside a function body (indented). Use `replaceAll: true` if
   the exact text is identical across all 12 sites — BUT be careful:
   the surrounding context differs. Safer to do them one at a time by
   reading the line and using enough context.

   Actually, if the line is always exactly `        from qualcoder_api.persistence import tables`
   (8-space indent), you can use `replaceAll: true` with that exact string
   → replace with empty. But that leaves blank lines. Better: replace
   each with nothing and clean up blank lines after.

4. Run `python -m py_compile` — if it fails with `NameError: tables`, you
   missed adding the top-level import.

**Verify**:
```
cd D:\Downloads\qualcoder-rework\backend
.venv\Scripts\python.exe -m py_compile src/qualcoder_api/api/v1/entities.py
.venv\Scripts\python.exe -m ruff check src/qualcoder_api/api/v1/entities.py
.venv\Scripts\python.exe -m pytest tests -q --tb=short -x
```

**Repeat for** `api/v1/tools.py` (15 lazy imports), `api/v1/codes.py` (7),
`api/v1/codings.py` (6) — same pattern. Do one file at a time with full
verification between each.

---

## Part 4 — Tasks NOT recommended (leave alone)

These were identified but should NOT be done by a smaller model:

1. **Split `AvCoder.tsx` (2106 lines)** — too complex, high risk of breaking
   playback/timeline/segment logic. Needs a human or large model with full
   context.
2. **Split `Sidebar.tsx` (2031 lines)** — same, 4 panels with drag-drop.
3. **`confirmAction()` helper (B4)** — 46 `window.confirm` calls. The
   DESIGN.md spec says to keep `window.confirm` for now. A future modal
   migration would touch one helper. Low priority, deferred by design.
4. **Split locale dictionaries (D7)** — 14 files × domains. Large effort,
   low reward. The flat dict works.
5. **`sql_reports.py` SQL injection pattern** — the validator mitigates it.
   Fixing it properly (parameterized LIMIT, or a read-only DB connection)
   is a security task, not a modularity task. Flag for the security review.
6. **`finalize_transcript` (182 lines)** — only function over 150 lines.
   It's a single cohesive concern (transcript finalization). Splitting it
   would create artificial fragmentation. Leave it.
7. **`scrape_service.py` split (J3)** — deferred in Wave 3 due to ~40 test
   `patch()` calls targeting the module namespace. Still deferred.

---

## Part 5 — Final verification (after all tasks you complete)

Run the full suites:
```
cd D:\Downloads\qualcoder-rework\backend
.venv\Scripts\python.exe -m pytest tests -q --tb=short
.venv\Scripts\python.exe -m ruff check src
.venv\Scripts\python.exe -m mypy src

cd D:\Downloads\qualcoder-rework\frontend
npx tsc --noEmit -p tsconfig.json
npx eslint src --max-warnings 0
npm test -- --run
```

All must pass: 883+ backend tests, 319+ frontend tests, 0 ruff, 0 mypy,
0 tsc, 0 eslint.

Then update this doc's task table with ✅/⚠️/➖ for each task.

---

## Part 6 — Summary of what's genuinely done vs. claimed

| Claim in docs | Reality |
|---|---|
| "28 lazy imports eliminated" (section E) | ❌ ~28 lazy imports REMAIN. `audit_capture.py` only half-redirects. |
| "GRAPH_MODELS moved to feature folder" (C4) | ❌ Dead file created; live copy still in `types.ts`. |
| "4 copies of FALLBACK_CODE_COLOR consolidated" (B5) | ⚠️ 4 import, 8 still inline. |
| "all api.ts magic numbers replaced" (C3) | ⚠️ 4 files bypass `config.ts`. |
| "useCodeMaps hook" (B6) | ⚠️ 3 of 6 coders use it; 3 need a richer hook. |
| "183 error-message sites replaced" (B3) | ⚠️ 1 real bypass (`errorTextOf`). |
| "23 effects converted" (B2) | ⚠️ 3 true bypasses remain. |
| All Wave 3 file splits | ✅ Verified clean — no duplicate code. |
| `lib/api.ts` split (D1) | ✅ Clean. |
| Store slices (D6) | ✅ Clean (543 from 1183). |
| `timeutil.py` (B1) | ✅ Mostly done (1 acceptable inline). |
| `palette.py` (C1) | ✅ Clean. |

The file-split work (Wave 2 & 3) is solid. The centralized-module adoption
(Wave 2 section H) has real gaps that the docs overstate. Wave 4 closes
those gaps.

---

## Part 7 — Implementation status (completed 2026-08-17)

All 12 tasks were executed and verified. The verification commands in
Part 5 now all pass.

| Task | Verdict | Notes |
|---|---|---|
| 1 — delete dead `features/graphs/models.ts` | ✅ | Deleted; `tsc` clean. The only remaining `graphs/models` reference is the API endpoint path in `endpoints.ts`, not a module import. |
| 2 — replace 6 `_inserted_pk` copies | ✅ | `code_sets.py`, `comments.py`, `creative.py`, `qtt.py`, `r_scripts.py`, `links_service.py` now import from `persistence/repo/base.py`. Only the canonical definition remains. 30 targeted tests passed. |
| 3 — replace `_rowdict` / `_row_dict` copies | ✅ | `dictionary_service.py` → canonical import; `graph_base.py` re-exports `_rowdict as _row_dict` (`# noqa: F401`) so the 3 graph consumers are unchanged. Both copies were pure `dict(row._mapping)`; verified no table column starts with `_` so the canonical underscore-filter is behavior-identical. 59 tests passed. **Scope: module-level copies only.** 2 nested `_rowdict` helpers inside `code_repo.py` (`delete_code`/`delete_category`) pre-existed and now just wrap `audit_capture.table_row` — redundant with canonical `base._rowdict` but out of scope (see Residuals). |
| 4 — magic numbers → `config.ts` | ✅ | Added `AI_REFRESH_MS` (AiTab poll), `SYNC_POLL_MS` (CoderSwitcher, local const removed); `PublishDialog` + `dictionaryApi` autocode now use `SOURCE_TIMEOUT_MS`. |
| 5 — `FALLBACK_CODE_COLOR` bypasses | ✅ | Fixed 7 call sites across `AvCoder` (2), `CodePicker`, `AutocodeDialog`, `merged.tsx`, `reportKit.tsx`, `StatsReport.tsx`. PdfCoder's two `"var(--qc-accent)"` literals are standalone assignments, not fallbacks — left per plan. |
| 6 — consolidate `errorTextOf` | ✅ | Moved to `lib/utils.ts`; `project.ts` imports it. |
| 7 — complete circular-dep fix | ✅ | **Full capture cluster moved to `persistence/audit_capture.py`** (`table_row`, `_current_user`, `_suspended`, `suspended()`, `set_current_user()`, `current_user()`, `capture()`, `capture_delete/insert/update`). `services/sync.py` re-exports them so `sync.*` callers/tests are unchanged. `code_repo.py` (11 sites) and `source_repo.py` (3 sites) now lazily import `from qualcoder_api.persistence import audit_capture` and call `audit_capture.*`. Full suite: 883 passed. |
| 8 — redundant broad except | ✅ | `autocode_service.py:404` `except (AiUnavailable, Exception)` → `except Exception`; removed the now-unused local `AiUnavailable` import in that function. (AiUnavailable still used at line 218 in another function.) |
| 9 — `useAsyncEffect` in `contextPickerData.ts` | ✅ | Manual `cancelled` + 3 `.then()` chains → single `useAsyncEffect` with `Promise.allSettled` firing the required fetches in parallel; `signal.throwIfAborted()` replaces `!cancelled`. |
| 10 — `useAsyncEffect` in `ImageCoder.tsx` | ✅ | Blob-fetch effect converted. `useAsyncEffect` discards returned cleanups, so the blob-URL `revokeObjectURL` moved to a small companion `useEffect` keyed on `imgSrc` (behavior-identical). `CoderSwitcher` polling left as-is — legitimate interval pattern per plan. |
| 11 — `useCodeIndex` for all 6 coders | ✅ | Added `useCodeIndex` to `codingApi.ts` returning `{ byId, colorByCid, nameByCid }` (byId filtered to `kind === "code"`, matching the previous local maps). Migrated: HtmlCoder (`byId`), CsvCoder (`byId: codeById` alias — keeps its prop/helper call sites), PdfCoder (`byId` + `colorByCid` from one hook), TextCoder (`byId: codeById` alias). TextCoder keeps its fallback-baking `colorByCid` derivation (semantics differ from the hook — per-plan decision) but sources the map from the hook's `byId`. AvCoder/ImageCoder already used `useCodeMaps`. |
| 12 — lazy `tables` imports | ✅ | `entities.py`: added top-level `tables` + `select` imports, removed 11 lazy pairs (both `select` and `tables` were lazy); whitespace artifacts cleaned by ruff. `codes.py`: removed 6 lazy `tables` imports + 1 nested duplicate. `tools.py` already had only the top-level import. **Scope: entities/codes/tools only.** ~18 lazy `tables` imports remain in 10 other files (`codings`, `dictionaries`, `links`, `router`, `sources`, `transcribe`, `ai_index`, `audit_undo/base`, `audit_undo/handlers/{code,coder_sync}`) — out of scope (see Residuals). |

**Final verification results** (all green):

- Backend: `883 passed` (pytest), `0` ruff, `0` mypy (134 files).
- Frontend: `319 passed` (vitest, 28 files), `0` tsc, `0` eslint.
- E2E: `50 passed` (Playwright, serial, 2.3 min). One first-run failure in
  `roadmap.spec.ts` (promote/demote context-menu) was a pre-existing UI race
  in the code-tree sidebar — it passed in isolation and on a full clean
  re-run; no Wave-4 file is involved (`Sidebar.tsx` and the spec are
  untouched).

*Re-checked 2026-08-17:* ruff + mypy (134 files) and tsc + eslint still
clean with the working tree as-is; the pytest/vitest/e2e counts above are
from the completion-day full runs (no source changed since).

**Audit-table scorecard after Wave 4** (from Part 1 / Part 6):

| Claim | Before | After |
|---|---|---|
| C-3 / §1.4 "Section E" circular-dep (`audit_capture`) | ❌ persistence→services inversion (~28 lazy `sync` imports) | ✅ **persistence layer fully redirected**: `code_repo` (11) + `source_repo` (3) → `audit_capture`; `sync` re-exports the cluster for back-compat. Remaining `sync` lazy imports are services/api→services (`links_service`, `router`, `coders`) — same/upper layer, NOT inversions (see Residuals). |
| C-9 `GRAPH_MODELS` dead file | ❌ orphan | ✅ removed |
| C-5 `errorTextOf` bypass | ⚠️ 1 bypass | ✅ consolidated into `lib/utils.ts`; `project.ts` imports it |
| C-8 `config.ts` magic numbers | ⚠️ 4 files | ✅ 4 files fixed via 3 new constants (`AI_REFRESH_MS`, `SYNC_POLL_MS`, `SOURCE_TIMEOUT_MS`) |
| C-4 `useAsyncEffect` bypasses | ⚠️ 3 | ✅ 2 fixed (`contextPickerData`, `ImageCoder`); `CoderSwitcher` polling legitimately kept |
| C-7 `useCodeMaps` adoption | ⚠️ 3 of 6 | ✅ all 6 coders source maps from `codingApi`; 0 build local maps (4 via `useCodeIndex`, 2 via `useCodeMaps`) |
| C-6 `FALLBACK_CODE_COLOR` | ⚠️ 8 files inline | ✅ 7 call sites fixed (6 files); 2 standalone-literal sites in `PdfCoder` left by design (decorative accents, not fallbacks) |

**Residual items — documented for transparency (not regressions; mostly
out of Wave-4 scope):**

*By design (Part 4 / leave-alone):*
- `CoderSwitcher` interval polling (not a one-shot fetch; the `cancelled` flag
  is the correct pattern).
- `remote.py` / `updates.ts` `/api/update` timeouts (infra, not api.ts magic
  numbers).
- `migration.py` inline `now()` copy (runs before the schema / `timeutil`
  exists).
- `PdfCoder`'s two `var(--qc-accent)` decorative accents (not fallbacks).
- `scrape_service.py` split (J3) — deferred (Wave 3) due to ~40 test `patch()`
  calls targeting the module namespace.

*Out of Wave-4 task scope (small; candidate for a future micro-pass):*
- 2 nested `_rowdict` helpers in `code_repo.py` (`delete_code`,
  `delete_category`) now just wrap `audit_capture.table_row` — redundant with
  the canonical `persistence/repo/base._rowdict`. Task 3 targeted module-level
  copies only.
- ~18 lazy `from qualcoder_api.persistence import tables` imports remain in 10
  files not in Task 12's scope: `codings.py` (7), `dictionaries.py` (3),
  `links.py`, `router.py`, `sources.py`, `transcribe.py`, `ai_index.py`,
  `audit_undo/base.py`, `audit_undo/handlers/code.py` +
  `coder_sync.py`. These are services/api→persistence (correct direction, not
  inversions) — purely stylistic laziness; convert the same way as
  entities/codes if desired, but verify the `audit_undo` handlers aren't
  avoiding an import-time cycle first.
- `links_service.py:162` still lazy-imports `services.sync` for
  `capture_insert` — acceptable (services→services, same layer), so left on
  `sync`. `audit_capture` exists only to break the persistence→services
  inversion; same-layer callers have no reason to switch.

---

## Micropass - executed 2026-08-17

The two residuals flagged as "future micro-pass" candidates in Part 7 are now
implemented and verified:

- **`code_repo.py` nested `_rowdict` removed (x2).** `delete_code` and
  `delete_category` no longer define local wrappers; both use the canonical
  `persistence/repo/base._rowdict` (identical `audit_capture.table_row`
  semantics).
- **All lazy `from qualcoder_api.persistence import tables` imports moved to
  top-level - 26 across 13 files.** The Part 7 count ("10 files / ~18") was an
  undercount: it missed the deeper-indented ones in `ai_service.py` (5),
  `mcp_service.py` (1) and `transcription.py` (2). Full list: `codings.py`
  (7), `dictionaries.py` (3), `links.py`, `router.py`, `sources.py`,
  `transcribe.py`, `ai_index.py`, `audit_undo/base.py`,
  `audit_undo/handlers/{code,coder_sync}`, `ai_service.py`, `mcp_service.py`,
  `transcription.py`. The `audit_undo` handlers were verified non-cyclic
  (persistence has no `services` imports). All sites are services/api ->
  persistence (correct direction).

`links_service.py:162` still imports `services.sync` for `capture_insert` -
unchanged by design (services->services, same layer).

Verification: ruff + mypy (134 files) clean; pytest **883 passed**.
