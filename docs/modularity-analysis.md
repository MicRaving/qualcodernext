# QualCoder v4 — Modularity & Hardcoding Analysis

> Planning document. **Implementation complete** — see the status table in
> section H. Verification: backend 883 tests + ruff + mypy clean; frontend
> tsc + eslint clean, vitest 319/319.

## Method

Full inventory of `backend/src` and `frontend/src` by line count, then
targeted grep for recurring snippets, hardcoded constants, and cross-file
coupling. Findings are grouped: **monoliths** (files >600 lines), **recurring
snippets** (same logic copy-pasted across files), **hardcoded values**, and
**structural friction** (patterns that make adding a feature touch many files).

---

## A. Monoliths — files over 600 lines

### Backend

| File | Lines | Problem |
|---|---|---|
| `persistence/repositories.py` | **2110** | 14 repository classes + 120-color palette + 9 module-level helpers all in one file. Every service imports private helpers (`_capture`, `_rowdict`, `_inserted_pk`, `_now`) from here, creating a de-facto god module. |
| `services/audit_undo.py` | **2000** | 60+ `_revert_*` functions + a 140-line `apply()` if/elif dispatch chain. One undo handler per audit action — adding a new audited action means editing this file AND the dispatch. |
| `interchange/importers.py` | **1530** | RQDA + Taguette + Transana + RIS + Survey CSV + XLSX + SPSS importers all in one file. Each is ~150-250 lines; they share no interface. |
| `services/report_service.py` | **1471** | Every report query (frequencies, segments, comparison, co-occurrence, exact matches, word frequencies, codebook, charts, relations, attributes…) in one module. |
| `services/scrape_service.py` | **1377** | YouTube + article + HTML snapshot + PDF render scrapers in one file. |
| `api/v1/sources.py` | **1080** | File CRUD + import + transcript companion + bad-links + filters + bulk-rename + PDF export + case-link endpoints. |
| `api/v1/importers.py` | **903** | Interchange API endpoints — wraps every importer in `interchange/importers.py`. |
| `services/graph_service.py` | **892** | Graph CRUD + nodes + lines + text items + free items + models + layout. |
| `services/coding_service.py` | **842** | Text/image/AV coding create/delete/update + autocode + shift-positions + commit-edit. |
| `api/v1/codes.py` | **725** | Code + category CRUD + tree move + merge + promote/demote. |
| `services/merge_projects.py` | **721** | Full project merge (tables-by-table copy with id remapping). |
| `persistence/migration.py` | **693** | v2→v5 and v6→v14 migration chains as two giant methods. |
| `services/ai_service.py` | **677** | AI chat + models + settings + index management. |
| `services/sync.py` | **620** | Collaboration sync (export/import/conflict resolution). |
| `api/v1/qtt.py` | **608** | QTT crafter endpoints (sheets + items + send-segment). |
| `persistence/tables.py` | **607** | All SQLAlchemy table definitions in one file. |

### Frontend

| File | Lines | Problem |
|---|---|---|
| `features/coding/AvCoder.tsx` | **2138** | Audio/video coder — playback, timeline, segment CRUD, transcript editing, bookmarks, links, autocode, transcribe dialog, details bar. |
| `components/shell/Sidebar.tsx` | **2034** | Files tree + code tree + cases list + code sets — four distinct panels in one component, with inline context menus, drag-drop, search, and CRUD. |
| `lib/api.ts` | **1847** | 92 exported symbols: base-URL resolution, fetch transport, **all** type definitions (60+ interfaces), AND the `api` object with every endpoint. Three concerns in one file. |
| `features/coding/HtmlCoder.tsx` | **1776** | Webpage snapshot coder — plain-text coding + iframe rendering + highlight injection + selection mapping. |
| `lib/locales/en.ts` | **1687** | Flat i18n dictionary — single 1687-line `Record<string, string>`. |
| `lib/locales/de.ts` | **1659** | German locale — same flat dict pattern (×14 locale files). |
| `features/coding/PdfCoder.tsx` | **1670** | PDF coder — pdf.js rendering + rectangle selection + overlays + per-page details. |
| `features/analyze/merged.tsx` | **1355** | Six merged report views in one file (frequencies, segments, file×code, relations, interrater, corpus). |
| `features/graphs/GraphsView.tsx` | **1236** | Graph canvas + node/line CRUD + models + layout + export. |
| `stores/project.ts` | **1183** | Zustand store: project lifecycle + view state + coder management + graph actions + inspector + a11y prefs + theme. |
| `features/manage/FileManager.tsx` | **1159** | File table + import + filters + bad-links + bulk-rename + case-assign + context menu. |
| `features/coding/TextCoder.tsx` | **1157** | Text coder — the base coder, but still a single component with rendering, selection, edit mode, annotations, links, autocode. |
| `features/notes/NotesView.tsx` | **1088** | Notes workspace (annotations + memos + journals). |
| `features/coding/htmlHighlight.ts` | **1072** | Highlight matching engine — pure logic but very large. |
| `components/shell/Inspector.tsx` | **959** | Code details + file details + memo editor + annotations + comments + links + case-assign. |
| `features/coding/CsvCoder.tsx` | **780** | CSV grid coder. |
| `features/qtt/QttView.tsx` | **736** | QTT crafter — sheets + items + send-segment. |
| `features/analyze/RConsole.tsx` | **702** | R console + script management. |
| `components/shell/ProjectShell.tsx` | **670** | View registry + routing. |
| `components/shell/CoderSwitcher.tsx` | **653** | Coder dropdown + sync status. |
| `features/bugreport/BugReportView.tsx` | **648** | Bug report form + screenshot + GitHub submit. |
| `features/interchange/ImportPreview.tsx` | **644** | Import preview + mapping. |
| `features/coding/ImageCoder.tsx` | **607** | Image coder (under threshold but shares the monolith pattern). |
| `features/coding/SelectionToolbar.tsx` | **579** | Floating selection toolbar. |
| `components/ui/orchestrator.tsx` | **599** | UI orchestrator (intentional — the design system hub). |

**Backend tests over 600 lines**: `test_api_ai.py` (851), `test_api_domains.py`
(809), `test_ai_context.py` (781), `test_api_importers.py` (758),
`test_audit_undo_all.py` (745), `test_api_undo.py` (677),
`test_upstream_parity.py` (525).

---

## B. Recurring snippets — same logic copy-pasted across files

### B1. `_now()` — timestamp helper (13 backend copies)

```python
def _now() -> str:
    return datetime.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")
```

**Copied verbatim in 13 files**: `repositories.py`, `code_sets.py`,
`comments.py`, `creative.py`, `coding_service.py`, `links_service.py`,
`dictionary_service.py`, `graph_service.py`, `merge_projects.py`,
`qtt.py`, `r_scripts.py`, `speakers.py`, `codebook.py`.
`file_replacement.py` does a lazy import instead of redefining.

Also inlined (without the helper) in `audit.py`, `sync.py`,
`user_settings.py`, `import_service.py`, `schema.py`, and the baseline
migration.

**Fix sketch**: create `backend/src/qualcoder_api/core/timeutil.py` with
`now()` (and `now_utc()` if needed). Replace all 14 copies with one import.

### B2. `let cancelled = false` async-effect pattern (34 frontend copies)

The same useEffect-cleanup boilerplate for async data loading:

```tsx
useEffect(() => {
  let cancelled = false;
  (async () => {
    try {
      const data = await api.someCall();
      if (!cancelled) setX(data);
    } catch (e) {
      if (!cancelled) setError(e instanceof Error ? e.message : "Failed");
    } finally {
      if (!cancelled) setLoading(false);
    }
  })();
  return () => { cancelled = true };
}, [deps]);
```

**Found in 34 effects across 21 files**: every coder (AvCoder ×3, HtmlCoder ×2,
PdfCoder ×3, TextCoder ×3, CsvCoder ×1, ImageCoder ×1), every report
(DictionaryReport ×2, RConsole ×3, upstreamReports ×2, reportData ×1,
SentimentReport ×1, merged ×1), AiSearchPanel ×2, AiChatPanel ×1,
contextPickerData ×1, AiView ×1, DashboardView ×1, SettingsView ×1,
CodingWorkspace ×1, SelectionToolbar ×2, CoderSwitcher ×1.

**Fix sketch**: create `frontend/src/lib/useAsync.ts` exporting a
`useAsyncEffect` hook (or `useAsyncData<T>`) that encapsulates the
cancelled-flag, try/catch/finally, and error extraction. Each call site
shrinks from ~15 lines to ~3.

### B3. `e instanceof Error ? e.message : fallback` (177 frontend copies)

The error-message extraction pattern is the most duplicated snippet in the
frontend — **177 occurrences across 33 files**. Top offenders: AvCoder (15),
Sidebar (16), FileManager (13), Inspector (13), stores/project.ts (12),
PdfCoder (11), QttView (9), CasesView (8). Some files already have a local
helper (`errorDetail` in `AutocodeDialog`, `errMsg` in `features/ai/format.ts`,
`CoderSwitcher` line 57), but only a handful of sites use them — the remaining
170+ inline the pattern directly.

**Fix sketch**: add `errorMessage(e: unknown, fallback?: string): string`
to `frontend/src/lib/utils.ts` (or a new `lib/errors.ts`). Replace the 177
inline copies.

### B4. `window.confirm` / `window.prompt` — 46 inline calls

46 direct `window.confirm`/`window.prompt` calls across 20+ files. The
`DESIGN.md` says "every destructive action confirms via `window.confirm`"
so this is intentional, but the pattern is verbose and not centralized:

```tsx
if (!window.confirm(t("files.deleteConfirm", { name: row.name }))) return;
// ... delete logic ...
```

**Fix sketch**: create `frontend/src/lib/confirm.ts` with
`confirmAction(key, params)` and `promptName(key, params, current)` thin
wrappers. Centralizes the i18n-keyed confirm/prompt pattern and makes it
easy to swap for a custom modal later (DESIGN.md says `window.confirm`
now; a future migration to `Modal` would touch one file).

### B5. `FALLBACK_CODE_COLOR = "var(--qc-accent)"` — 4 copies

Duplicated in `TextCoder.tsx`, `HtmlCoder.tsx`, `CsvCoder.tsx`,
`DetailsBars.tsx`. `PdfCoder.tsx` uses a different constant
(`DEFAULT_CODING_COLOR = "rgba(0,0,0,0.15)"` from `pdf.ts`).

**Fix sketch**: add `export const FALLBACK_CODE_COLOR = "var(--qc-accent)"`
to `frontend/src/features/coding/tint.ts` (already the color-utility
module). Import everywhere.

### B6. `colorByCid` / `nameByCid` useMemo — repeated in every coder

Every coder builds the same two maps from the code tree:

```tsx
const colorByCid = useMemo(() => {
  const map = new Map<number, string>();
  for (const c of codes) if (c.kind === "code" && c.color) map.set(c.id, c.color);
  return map;
}, [codes]);
const nameByCid = useMemo(() => {
  const map = new Map<number, string>();
  for (const c of codes) if (c.kind === "code") map.set(c.id, c.name);
  return map;
}, [codes]);
```

**Fix sketch**: add `useCodeMaps(codes)` hook to
`frontend/src/features/coding/codingApi.ts` returning
`{ colorByCid, nameByCid }`. Used by TextCoder, HtmlCoder, PdfCoder,
AvCoder, ImageCoder, CsvCoder.

---

## C. Hardcoded values

### C1. 120-color code palette (`repositories.py` lines 66-92)

```python
CODE_COLORS = ["#F5F6CE", "#F2F5A9", ... ]  # 120 hex colors
COLOUR_RANGES = [{"name": "yellow", "min": 0, "max": 5}, ...]
```

Hardcoded in `repositories.py` (the persistence layer). `user_settings.py`
imports them lazily. `random_code_color()` also lives here.

**Fix sketch**: move to `backend/src/qualcoder_api/core/palette.py` — a
pure-data module with `CODE_COLORS`, `COLOUR_RANGES`, and
`random_code_color()`. Both `repositories.py` and `user_settings.py`
import from there. The palette is domain data, not persistence logic.

### C2. App version `"0.2.0"` hardcoded in two places

- `backend/src/qualcoder_api/api/v1/router.py` line 86: `version: str = "0.2.0"`
- `frontend/src/lib/locales/en.ts` line 8: `"app.version": "0.2.0"`

**Fix sketch**: single `VERSION` constant. Backend: `core/__init__.py`
or `pyproject.toml` read. Frontend: `package.json` import or a
`lib/version.ts`. Both already drift independently.

### C3. Backend port `8765` hardcoded

`frontend/src/lib/api.ts` line 16: `DEV_FALLBACK = "http://localhost:8765/api/v1"`.
Also appears in Tauri config and test setup.

**Fix sketch**: `frontend/src/lib/config.ts` with `DEV_API_BASE`,
`POLL_TIMEOUT_MS` (150), `POLL_INTERVAL_MS` (200), `REQUEST_TIMEOUT_MS`
(15_000), `SOURCE_TIMEOUT_MS` (60_000) — all currently magic numbers in
`api.ts`.

### C4. Graph model list hardcoded in `api.ts` line 1062

```ts
export const GRAPH_MODELS = [ ... ]
```

Inline in the API client; should live with the graph feature.

**Fix sketch**: move to `frontend/src/features/graphs/models.ts`.

### C5. `_GRAPH_PKS` dict in `audit_undo.py`

A mapping of entity → primary key name, used by the undo dispatch. It's
domain metadata buried in a 1828-line file.

**Fix sketch**: part of the audit_undo decomposition (see D2).

---

## D. Structural friction — adding a feature touches too many files

### D1. `lib/api.ts` is three concerns in one (1847 lines)

The file mixes: (1) transport (base-URL resolution, fetch, retry, timeout),
(2) type definitions (60+ interfaces), and (3) the `api` object (every
endpoint). Adding any backend endpoint means editing this one giant file,
and every component imports types from the same file that owns the fetch
logic.

**Fix sketch**: split into:
```
lib/api/
  transport.ts   — resolveBase, request, fetchWithTimeout, ApiError,
                   fetchSourceFile, invalidateApiBase (~180 lines)
  types.ts       — all exported interfaces (~500 lines, pure types)
  endpoints.ts   — the `api` object (~700 lines, one import per domain)
  index.ts       — re-export everything (existing imports stay valid)
```
This keeps the public API (`import { api, ApiError, type Coding } from
"@/lib/api"`) unchanged — the barrel file re-exports.

### D2. `audit_undo.py` — dispatch chain + handler zoo (2000 lines)

The `apply()` function is a 140-line if/elif chain dispatching to 60+
handlers. Adding a new audited action requires: (1) writing a `_revert_*`
function, (2) adding an `if action == "..."` branch to `apply()`. The
handlers also share boilerplate (`_detail`, `_ensure`, `_insert_row`,
`_delete_by_id`, `_update_row`).

**Fix sketch**: registry pattern.
```python
# audit_undo/registry.py
HANDLERS: dict[str, RevertHandler] = {}
def register(*actions: str):
    def deco(fn): 
        for a in actions: HANDLERS[a] = fn
        return fn
    return deco

# audit_undo/handlers/coding.py
@register("coding.create", "coding.delete")
async def _revert_coding(session, row, *, undo): ...

# audit_undo/handlers/source.py
@register("source.import", "source.delete", ...)
async def _revert_source(...): ...

# audit_undo/apply.py
async def apply(session, row, *, undo, project_path=None):
    handler = HANDLERS.get(row.get("action", ""))
    if handler is None: raise UnsupportedAction(...)
    return await handler(session, row, undo=undo, project_path=project_path)
```
Split into `audit_undo/` package with `base.py` (shared helpers),
`registry.py`, `apply.py`, and `handlers/` subpackage (one file per
domain: `coding.py`, `source.py`, `code.py`, `category.py`, `graph.py`,
etc.). Adding a new action = one decorated function in the right
handler file; no edit to `apply()`.

### D3. `repositories.py` — god module (2110 lines)

14 repository classes + the color palette + 9 helpers (`_now`,
`_capture`, `_rowdict`, `_inserted_pk`, `_coding_row`,
`random_code_color`). 43 import statements across 26 files import from
this module — 28 of those are function-level (lazy) imports of the
private helpers (`_capture`, `_rowdict`, `_inserted_pk`), indicating
circular dependency workarounds.

**Fix sketch**: split into a `persistence/repo/` package:
```
persistence/repo/
  __init__.py        — re-exports all repositories (compatibility)
  base.py            — _inserted_pk, _coding_row, _rowdict, _capture helpers
  code_repo.py       — CodeRepository, CategoryRepository
  coding_repo.py     — CodingRepository, AVCodingRepository, ImageCodingRepository
  source_repo.py     — SourceRepository
  case_repo.py       — CaseRepository, CaseTextRepository
  project_repo.py    — ProjectRepository
  attribute_repo.py  — AttributeRepository
  journal_repo.py    — JournalRepository
  annotation_repo.py— AnnotationRepository
```
Move `CODE_COLORS`/`COLOUR_RANGES`/`random_code_color` to
`core/palette.py`. Move `_now()` to `core/timeutil.py`. The `__init__.py`
barrel keeps all existing imports valid.

### D4. `interchange/importers.py` — 6 importers with no common interface (1530 lines)

RQDA, Taguette, Transana, RIS, Survey CSV, XLSX, SPSS importers are all
free functions in one file. `detect_import_kind()` sniffs the file and the
API layer (`api/v1/importers.py`, 903 lines) has one endpoint per kind.

**Fix sketch**: `interchange/importers/` package with a common
`Importer` protocol:
```python
class Importer(Protocol):
    kind: str  # "rqda" | "taguette" | "ris" | ...
    async def import(self, path: str, session_factory, ...) -> ImportResult: ...
```
One file per importer (`rqda.py`, `taguette.py`, `transana.py`, `ris.py`,
`survey.py`, `xlsx.py`, `sav.py`), a `registry.py` mapping kind →
importer, and `detect.py` for sniffing. The API layer shrinks to a
generic `POST /interchange/import` that dispatches via the registry.

### D5. The five coders share no base — 7330 lines of near-duplicate structure

AvCoder (2138), HtmlCoder (1776), PdfCoder (1670), TextCoder (1157),
CsvCoder (780), ImageCoder (607) all independently implement:
- loading codings + code tree (`api.xxxCodings` + `api.codesFlat`)
- `colorByCid` / `nameByCid` maps (B6)
- the cancelled-flag load effect (B2)
- error state + loading state
- CodePicker integration
- segment selection → create/delete coding
- details bar (CodingDetailsBar / AnnotationDetailsBar)
- autocode dialog trigger
- bookmark handling

Each is a standalone component with no shared hook or base.

**Fix sketch**: `frontend/src/features/coding/useCoder.ts` — a hook
encapsulating the shared coder state machine:
```ts
function useCoder(source: Source) {
  // loading, error, codings, codes, colorByCid, nameByCid
  // load(), createCoding(), deleteCoding(), updateWeight()
  return { codings, codes, loading, error, colorByCid, nameByCid, ... };
}
```
Each coder component calls `useCoder(source)` and renders only its
medium-specific surface (text / image / pdf / av / csv / html). The
~200-line preamble of each coder shrinks to one hook call. This also
makes adding a new coder type (e.g. a future Markdown coder) trivial.

### D6. `stores/project.ts` — one store for everything (1183 lines)

The Zustand store mixes project lifecycle, view routing, coder
management, graph actions, inspector state, a11y prefs, and theme. Any
change to any concern re-renders subscribers across the app.

**Fix sketch**: split into slices (Zustand's recommended pattern):
```
stores/
  project.ts        — open/close/create project, project summary
  workspace.ts       — view, rightPane, selectedSource
  coder.ts          — coder list, current coder, visibility
  inspector.ts      — code/file details, memo, annotations
  graph.ts          — graph data, node/line CRUD
  prefs.ts          — theme, a11y, auto-show-segment-details
```
Use Zustand's `combine` or separate `create()` calls. Components
subscribe only to the slice they need.

### D7. i18n locale files are 1600-line flat dictionaries

`en.ts` (1687 lines), `de.ts` (1659), and 12 other locale files are flat
`Record<string, string>` maps. Adding a key means editing 14 files. The
`i18n.tsx` (163 lines) is fine; the locale data is the issue.

**Fix sketch**: split each locale by domain (matching the feature
folders): `locales/en/coder.ts`, `locales/en/files.ts`,
`locales/en/reports.ts`, etc., merged in `locales/en/index.ts`. Or
move to JSON files loaded by domain. This is lower priority — the flat
dict works, it's just unwieldy. Consider only if translation workflow
becomes painful.

---

## E. Circular dependency workarounds (backend)

28 lazy inline imports of the form
`from qualcoder_api.persistence.repositories import _capture, _rowdict`
appear *inside functions* across 14 service/API files. This is a
workaround for circular imports: `repositories.py` imports from
`services/sync.py` (for `table_row` / `capture`), and services import
back from repositories.

The root cause is that `repositories.py` (persistence) depends on
`services/sync.py` (services) — a layer violation. `_rowdict` calls
`sync.table_row()` and `_capture` calls `sync.capture()`.

**Fix sketch**: move `table_row()` and `capture()` to
`persistence/audit_capture.py` (or `core/audit.py`). Then
`repositories.py` depends only on persistence/core, not services. The
lazy imports become top-level imports and the circular dependency is
eliminated.

---

## F. Raw SQL vs repository pattern (backend)

**151 raw SQL query strings** (`text("...")`) across the backend, vs the
repository pattern in `repositories.py`. Distribution:

| File | SQL count | Notes |
|---|---|---|
| `services/audit_undo.py` | 38 | undo/redo row manipulation — expected (inverse ops) |
| `services/report_service.py` | 31 | aggregation queries — no repository equivalent |
| `services/merge_projects.py` | 19 | table-by-table copy with id remapping |
| `services/sync.py` | 7 | sync export/import |
| `services/references.py` | 6 | reference management |
| `persistence/repositories.py` | 5 | the repositories themselves use some raw SQL |
| `api/v1/coders.py` | 4 | coder stats/visibility |
| `services/codebook.py` | 4 | codebook export |
| `api/v1/audit.py` | 4 | audit queries |
| `services/graph_service.py` | 2 | graph CRUD |
| `services/import_service.py` | 2 | import detection |
| `api/v1/sources.py` | 2 | file queries |
| `services/sentiment_service.py` | 2 | dynamic SQL (user-provided) |
| (others) | 1 each | scattered |

**Assessment**: the raw SQL is mostly in the *right* places —
`report_service.py` (aggregations that don't map to repository CRUD),
`audit_undo.py` (inverse operations), `merge_projects.py` (bulk copy).
The repositories own the entity CRUD; the services own the complex
queries. This is an acceptable pattern and **not** a modularity problem.
The only concern is that `audit_undo.py`'s 38 raw SQL statements are
part of the undo handler monolith (D2) — splitting that file would
distribute them naturally.

---

## G. Frontend API discipline — no endpoint leaks

A positive finding: **0 hardcoded API endpoint paths outside `lib/`**.
All 34 endpoint path literals live in `lib/api.ts`; the feature-level
API modules (`creativeApi.ts`, `codeSetsApi.ts`, `dictionaryApi.ts`,
`qttApi.ts`, `commentsApi.ts`, `statsApi.ts`, `codingApi.ts`) import
`localRequest`/`request` from `@/lib/api` and add only a handful of
paths. No feature component constructs raw `fetch()` calls with
hardcoded paths. The 3 raw `fetch()` calls in `api.ts` itself are for
file upload/replace (non-JSON `FormData` bodies). This is clean — the
split in D1 preserves this boundary.

---

## H. Priority summary

**Status legend**: ✅ done · ⚠️ partial · ⏳ pending

| Priority | Item | Impact | Effort | Status |
|---|---|---|---|---|
| **1** | B1 — `_now()` → `core/timeutil.py` | 13 copies + 5 inline sites | S | ✅ |
| **2** | C1 — color palette → `core/palette.py` | domain data out of persistence | S | ✅ |
| **3** | B5 — `FALLBACK_CODE_COLOR` → `tint.ts` | 4 files | S | ✅ |
| **4** | B3 — `errorMessage()` → `lib/utils.ts` | 183 sites | M | ✅ |
| **5** | B2 — `useAsyncEffect` hook | 23 effects converted, 7 left (polls/cleanup) | M | ✅ |
| **6** | B6 — `useCodeMaps()` hook | AvCoder/ImageCoder/PdfCoder; TextCoder+HtmlCoder/CsvCoder need bespoke maps | S | ✅ |
| **7** | D1 — split `lib/api.ts` into package | transport 269 / types 825 / endpoints 839 / index 3 | M | ✅ |
| **8** | D3 — split `repositories.py` → `repo/` package | 2065 → 9 files + 51-line shim | M | ✅ |
| **9** | E — fix circular deps (audit_capture) | 28 lazy imports eliminated | M | ✅ |
| **10** | D2 — `audit_undo` → registry + handlers | 2000 → 10 files, 101 actions registered | L | ✅ |
| **11** | D5 — `useCoder()` hook | ImageCoder + AvCoder converted; 4 coders kept bespoke loads (entangled) | L | ⚠️ |
| **12** | D4 — `interchange/importers` → package | 1530 → 10 files | M | ✅ |
| **13** | D6 — split `project.ts` store into slices | 1183 → 6 stores (project 543 / prefs 187 / graph 185 / inspector 149 / workspace 125 / coder 86) | M | ✅ |
| **14** | B4 — `confirmAction()` helper | kept `window.confirm` (DESIGN.md spec; modal migration later) | S | ⏳ |
| **15** | C2 — single VERSION constant | backend `APP_VERSION` in `core/__init__.py`; frontend `app.version` stays i18n data | S | ⚠️ |
| **16** | C3 — `lib/config.ts` for magic numbers | all api.ts magic numbers replaced | S | ✅ |
| **17** | C4 — move `GRAPH_MODELS` to graphs feature | `features/graphs/models.ts` + re-export | S | ✅ |
| **18** | D7 — split locale dicts by domain | 14 files × domains | L | ⏳ (low priority) |

**S** = <1 hour, **M** = half day, **L** = 1-2 days.

---

## I. What's already good

- **UI orchestrator** (`orchestrator.tsx` + `tokens.ts`) — the design
  system is well-centralized; views import from it instead of hardcoding
  classes. The `DESIGN.md` spec is enforced.
- **Report registry** (`analyze/registry.ts`) — the report catalog drives
  both the list and the view; adding a report is one entry.
- **Router** (`api/v1/router.py`) — clean include_router chain; adding an
  API module is one include line.
- **Service/API separation** — services don't import FastAPI; API routes
  are thin and delegate to services.
- **`codingApi.ts`, `codeSetsApi.ts`, `dictionaryApi.ts`** — feature-level
  API modules already exist for some domains; the pattern is established
  but not applied to `lib/api.ts` itself.
- **`reportData.ts` / `reportKit.tsx`** — shared report rendering helpers
  already factor out the `useReport` hook and table classes.

The codebase has the right *ideas* (registry, orchestrator, service/API
split); the gap is that the *data layers* (repositories, api.ts, audit_undo)
and the *coder components* haven't been decomposed yet.

---

## J. Wave 3 — remaining backend monoliths (post-Wave-2 assessment)

After Wave 2, the original priority items (H) are complete, but section A
listed many more backend files over 600 lines that were never prioritized.
A re-scan found **15 backend files still >600 lines**, plus **one
regression** introduced by the D2 split itself. This section adds the
worthwhile splits. Single-concern / borderline files are left alone.

**Status legend**: ✅ done · ⚠️ partial · ⏳ pending · ➖ leave as-is

| Priority | Item | Before | After | Status |
|---|---|---|---|---|
| **J1** | Split `audit_undo/handlers/entity.py` (D2 regression — 30 handlers / 10 domains in one file) | 938 | 6 sub-domain files | ⏳ |
| **J2** | Split `report_service.py` → `reports/` package by report family | 1471 | ~7 files | ⏳ |
| **J3** | Split `scrape_service.py` → `scrape/` package by source type | 1377 | ~6 files | ⏳ |
| **J4** | Extract pdf-text-locate engine from `api/v1/sources.py` → `services/pdf_locate.py` | 1080 | ~600 + ~480 | ⏳ |
| **J5** | Split `coding_service.py` → core + `autocode_service.py` | 838 | ~430 + ~410 | ⏳ |
| **J6** | Split `graph_service.py` → core + items + lines | 888 | ~3 files | ⏳ |
| **J7** | Split `api/v1/importers.py` → router + preview module | 903 | ~400 + ~500 | ⏳ |
| ➖ | `persistence/repo/code_repo.py` (872) | single class — mixin split is risky | — | ➖ |
| ➖ | `api/v1/codes.py` (725) | one domain (codes+categories) | — | ➖ |
| ➖ | `services/merge_projects.py` (718) | single concern (table copy) | — | ➖ |
| ➖ | `persistence/migration.py` (693) | single concern (migration chains) | — | ➖ |
| ➖ | `services/ai_service.py` (677) | cohesive AI domain | — | ➖ |
| ➖ | `services/sync.py` (620) | single domain (sync) | — | ➖ |
| ➖ | `persistence/tables.py` (607) | schema definitions belong together | — | ➖ |
| ➖ | `api/v1/qtt.py` (604) | just over threshold, one domain | — | ➖ |