# QualCoder v4 — Implementation Plan (Phase 14)

## Status: ALL PHASES IMPLEMENTED (2026-08-05)

| Phase | Status | Gates |
|---|---|---|
| A Dashboard start + browse auto-open | ✅ | 21/21 E2E |
| B Transparent code regions | ✅ | tint.test.ts |
| C Coders | ✅ | 4 API tests |
| D LM Studio | ✅ | AI tests updated |
| E History view | ✅ | 3 audit API tests + E2E |
| F Whisper + noScribe | ✅ | 5 transcription tests + real E2E (tiny model) |
| G Simultaneous work | ✅ | presence-registry tests, dynamic port |
| H Packaging | ✅ | 187 backend / 21 E2E / lint / build / Rust clippy-clean; 140 MB exe |

Notes: noScribe engine level 2 stays gated (docx transcript import already
works through the standard .docx import). Whisper models cache in
`~/.qualcoder/models/whisper` (first run downloads).

---

Eight features, ordered by dependency. Each phase is independently
shippable and must keep the gates green: backend `pytest` (175), frontend
`npm run build` / `npm run lint` / `npm test`, E2E `npm run test:e2e` (19).

Artifact pipeline: `compile.ps1` (PyInstaller backend → embedded in Tauri exe).
New backend deps must be added to `backend/requirements.txt` + the PyInstaller
spec (`backend/qualcoder_backend.spec` hidden imports) — never to `requirements.txt`
of the root v3 repo.

---

## Phase A — Dashboard is the start page; New/Open live there (small)

**Goal:** App always opens on the dashboard. When no project is open the
dashboard shows "New project" / "Open project" cards (the WelcomeScreen
logic moves into the dashboard's empty state). Opening a project lands on
the same dashboard with stats.

**Scope:**
- `frontend/src/components/shell/ProjectShell.tsx`: render `DashboardView`
  for ALL views including the no-project state; remove the welcome-screen
  switch from `App.tsx` / wherever `WelcomeScreen` is mounted.
- `frontend/src/features/dashboard/DashboardView.tsx`: add empty-state
  branch (`projectOpen === false`): two cards reusing the existing
  create/open forms (move the form components from `WelcomeScreen.tsx`
  into the dashboard feature, delete WelcomeScreen or keep as thin shell).
- Store (`stores/project.ts`): no structural change; `projectOpen` already
  drives state.

**Browse auto-open (the "second click" fix):**
- In the Open card, after `pickDirectory()` returns a path:
  `openPath` is set **and** `openProject(dir)` is invoked immediately
  (button is `disabled` only while `busy`). Remove the "Open project"
  submit button for the browse flow — picking a folder IS the action.
- Create card: Browse fills `…\NewProject.qda` and keeps the Create
  button (a name still has to be entered).
- E2E: extend `app.spec.ts`/`features.spec.ts` — assert the dashboard
  shows after app start with no project, create from the dashboard,
  and that the welcome screen is gone.

**Risk:** E2E helpers (`ensureProjectOpen` in 3 spec files) target the
welcome screen — update all locators to the dashboard empty state.

---

## Phase B — Coded regions follow the code color, transparently (small)

**Goal:** highlights use the code's color only as a translucent tint.

**Current:** `color-mix(in srgb, {color} 30%, transparent)` inline in
TextCoder (`softBackground`), PdfCoder/ImageCoder/AvCoder use similar or
`DEFAULT_CODING_COLOR`.

**Changes:**
- `frontend/src/lib/tokens.ts` (or the theme tokens): add a design token
  `--qc-coding-alpha` (e.g. `0.15`) — **not** a Tailwind spacing/container
  key (known collision trap).
- Shared helper `codeTint(color)` in `features/coding/segments.ts` or a
  new `features/coding/tint.ts`: `color-mix(in srgb, ${color} var(--qc-coding-alpha), transparent)`.
  Replace all hardcoded mixes in TextCoder, PdfCoder, ImageCoder, AvCoder
  (+ `PreviewRect`), keep region codings with their 1px colored border.
- Segment hover: keep `outline`/brightening at slightly higher alpha so
  regions remain clickable/visible (a11y check — contrast vs `bg-bg`).

**Tests:** unit test for `codeTint` output; visual smoke via existing E2E
(regions still visible); no behavioral change expected.

---

## Phase C — Multiple coders (create / switch / delete) (medium)

**Goal:** real user ("coder") identities instead of the hardcoded
`owner: "default"`.

**Backend:**
- `services/user_settings.py`: settings gain `codername` (already exists)
  + `coders: string[]` list (create/switch/delete coders).
- New endpoints in `api/v1` (new `coders.py` router):
  - `GET /coders` → `{ current: str, coders: [{ name, coding_count }] }`
  - `POST /coders` `{ name }` → create (409 on duplicate)
  - `PUT /coders/current` `{ name }` → switch (persist `codername`)
  - `DELETE /coders/{name}` → refuse when it has codings (409 + count) or
    when it is the last coder; optional `reassign_to` param.
  - `GET /coders/{name}/codings-count` (or fold into GET /coders).
- `router.py`: every create endpoint already accepts `owner`/`codername` —
  defaults must follow the *current* coder from settings instead of
  `"default"` (project_service + coding/annotation services).

**Frontend:**
- `lib/api.ts`: drop the `owner: "default"` literals; add
  `coders` API group.
- New `CoderSwitcher` in the ProjectShell toolbar (name + caret dropdown:
  switch, manage, add). `features/settings/SettingsView.tsx`: "Coders"
  section with create/rename/delete + per-coder coding counts.
- Store: `coderName` (from `GET /coders`), refreshed on open; coding
  requests no longer send `owner` (backend derives it).

**Tests:** backend: coder CRUD + default-owner-follows-current-coder
(+ regression: existing tests keep working via `default`); E2E: switch
coder → create coding → owner column reflects the new name.

---

## Phase D — LM Studio as a local AI backend (small)

**Goal:** one-click LM Studio preset.

**Current:** `AiService` already talks to any OpenAI-compatible endpoint
(`api_base` from settings, default `http://localhost:11434/v1` = Ollama).

**Changes:**
- `user_settings.py` AI defaults: add `provider: "ollama" | "lmstudio" |
  "custom"`; provider presets: LM Studio → `http://localhost:1234/v1`,
  Ollama → `http://localhost:11434/v1`.
- `SettingsView` (AI section): provider select; switching fills the
  default `api_base`; keep manual override ("custom").
- AI status endpoint: report the resolved base URL so the UI can show
  "LM Studio not running" with the correct hint.
- Docs (`frontend/README-tauri.md` or a new `docs/ai.md`): enable LM
  Studio (Settings → Server → Start, model loaded, OpenAI-compatible
  server on 1234).

**Tests:** unit test for preset resolution; E2E: switch provider → status
shows the LM Studio URL (backend unreachable is fine, message asserted).

---

## Phase E — Edit review / project history view (medium-large)

**Goal:** browse a chronological, per-user audit of all changes; review
edits (with before/after for text edits).

**Backend:**
- Schema v15 migration (`persistence/migration.py`): table
  `audit_log (id INTEGER PK, ts TEXT, user TEXT, action TEXT, entity TEXT,
  entity_id INTEGER, detail TEXT JSON, source_id INTEGER NULL)`.
- `services/audit.py`: `record(conn_or_session, user, action, entity, id,
  detail={...})`; action vocabulary: `coding.create`, `coding.delete`,
  `coding.autocode`, `annotation.*`, `case.*`, `attribute.*`,
  `journal.*`, `source.import`, `source.delete`, `source.edit`,
  `code.create/rename/merge/delete`, `project.open/close`.
- Wire into: coding_service (create/delete/undo/autocode/shift),
  commit-edit (before/after text snapshot), import_service, manage
  (file/case/attribute/journal services), code_tree_crud.
- Endpoints: `GET /audit?limit&offset&action&user&source_id&from&to`;
  `GET /audit/stats` (counts by action for the review view).

**Frontend:**
- New nav item "History" (lucide `History` icon) → `HistoryView`:
  filter bar (action, coder, date range), paginated table
  (time · coder · action · entity · detail), detail drawer showing
  JSON pretty + for `source.edit` a before/after diff (simple
  line-diff client-side).
- Store slice: `history` pagination state.

**Scope decision (note):** history is read-only in this phase. Undo-from-
history (revert a specific change) is listed as a follow-up — requires
per-entity inverse operations.

**Tests:** backend: audit rows recorded for each action type; endpoint
filters. E2E: create a coding + edit text → History shows both, filter by
action.

---

## Phase F — Transcription: Whisper + noScribe (large)

**Goal:** transcribe audio/video sources inside the app; Whisper
(high-quality, configurable) as the primary engine; noScribe as an
alternative integration.

**Decisions (locked in this plan):**
- Engine: **`faster-whisper`** (CTranslate2) — the best CPU-friendly
  Whisper implementation; supports `large-v3-turbo`, VAD, beam search,
  CPU/GPU. Models auto-download to `~/.qualcoder/models/whisper`.
- noScribe: two integration levels —
  1. **Import its output**: noScribe `.docx` transcripts imported as text
     sources (with speaker/timestamp parsing when detectable).
  2. **Optional engine**: if the `noscribe` package is importable in the
     backend venv, offer it as a transcription provider (its Whisper +
     diarization pipeline runs locally). Not bundled by default (heavy
     deps, often a GUI install) — documented and gated.

**Backend:**
- New `services/transcription.py` + `api/v1/transcribe.py`:
  - `GET /transcribe/status` → engines available (faster-whisper present?
    noScribe present? device, model cache size)
  - `POST /transcribe` `{ source_id, engine: "whisper"|"noscribe",
    model, language|null, translate, beam_size, temperature, vad,
    device, compute_type, segments_timestamps }` → runs as a background
    job (asyncio task / threadpool; report progress)
  - `GET /transcribe/jobs/{id}` → progress %, state, result
  - On completion: create a new text source `<av-name>.txt` with the
    transcript (timestamps `[mm:ss]` lines when requested), optionally
    auto-link segments: AV codings for each segment (if
    `segments_timestamps` + auto-segment-coding enabled).
- Whisper-specific settings persisted in `user_settings` under
  `transcription: { engine, model: "large-v3-turbo", language: null,
  translate: false, beam_size: 5, temperature: 0.0, vad: true,
  device: "auto", compute_type: "auto", segment_coding: false }`.
- PyInstaller: faster-whisper + ctranslate2 + onnxruntime hidden imports
  in `qualcoder_backend.spec`; **exclude** from the default bundle only if
  size is a problem — decision point: bundle vs optional-install
  (recommend bundling; +~150 MB exe).

**Frontend:**
- AvCoder header: "Transcribe…" button → `TranscribeDialog` (engine
  select, model size, language, options, progress bar, poll job).
- On success: toast + refresh source list; if segment coding on, the
  new AV codings appear in the timeline.
- Settings: transcription defaults.

**Tests:** unit: transcript import parse (docx) + timestamp-line parse.
E2E: generate a tiny WAV with a spoken line via a fixture script
(pyttsx3 not available — use espeak? decision: synthesize offline with a
small pre-generated WAV committed to tests-e2e/fixtures) → transcribe
(faster-whisper tiny model, CPU) → assert `.txt` source exists.
Mark heavy test `@pytest.mark.slow` / `test.skip` when no model cache.

**Risks:** model download size/time (first run); CUDA optional;
noScribe import friction (documented as optional engine).

---

## Phase G — Simultaneous work on the same project (large)

**Goal:** two+ app instances may open the same project and see each
other's changes.

**Blockers today:** (1) every instance binds port 8765 → second instance
has no backend; (2) `project_in_use.lock` is exclusive → second open
reports "in use"; (3) sqlite locking on Windows (busy/`database is
locked`).

**Backend changes:**
1. **Dynamic port** (`main.py` + Rust):
   - `uvicorn` binds `8765`, on `EADDRINUSE` fall back to a free port
     (bind `127.0.0.1:0` probe) — implemented in `run_packaged.py` /
     `__main__.py` path used by the embedded backend.
   - Rust `start_backend`: after spawn, probe candidate ports, store the
     winner in a per-instance file `%TEMP%\qualcoder-port-<pid>.json`
     (backend writes it itself — single source of truth).
   - Frontend: `api.ts` resolves `API_BASE` at startup: if running under
     Tauri, `invoke("backend_port")` (new Rust command reading the same
     file) → else `VITE_API_BASE` (dev/E2E unchanged).
2. **Lock semantics** (`project_service.py`):
   - Replace exclusive lock with a **presence registry**: lock file holds
     one line per open instance (`user | pid | port | timestamp`).
     `_acquire_lock` appends its line; `close_project`/startup removes it;
     stale lines (dead pid) pruned. Opening is allowed when any OTHER
     live instance holds the project — that's the feature now.
   - Keep a `lock_token` (instance pid+port) returned on open for close.
   - Migration for old-format lock files (treated as stale).
3. **SQLite concurrency**: ensure `journal_mode=WAL` +
   `busy_timeout=5000` on every engine (`persistence/database.py`),
   `check_same_thread=False` already in place via aiosqlite. Verify
   `save_backup` uses the SQLite backup API or a WAL-safe copy
   (`VACUUM INTO`).
4. Recent-projects/settings: keep shared (last writer wins) — acceptable.

**Frontend:** refresh-on-focus (when the window regains focus, re-run
`refreshProject` + current source reload) so cross-instance changes
appear; "other users online" indicator: `GET /projects/current/openers`
→ list of live openers (from the registry) shown in the dashboard.

**Dev/E2E implications:** E2E spawns its own uvicorn on 8765 — unchanged
(dev path never auto-ports). Add an integration test: two `ProjectService`
instances (two backends on different ports in-process) → concurrent
open + concurrent coding writes.

**Risks:** sqlite write contention under heavy parallel autocoding
(mitigated by busy_timeout + WAL); port file race (mitigated by retry);
this phase must not regress the single-user lock recovery (Phase 9 tests).

---

## Phase H — Packaging & final gates

- `compile.ps1`: unchanged flow; new optional model/engine bundling
  flagged in the report (faster-whisper bundled by default).
- Full verification: backend 175+ new tests, frontend build/lint/unit,
  E2E (19 + new specs), packaged exe smoke from `C:\Windows\System32`
  (create → open → transcribe → history → second instance).
- Docs: `IMPLEMENTATION_PLAN_V4.md` status table + README updates
  (LM Studio, Whisper/noScribe, multi-instance, history).

---

## Suggested order & effort

| Phase | Effort | Depends on |
|---|---|---|
| A Dashboard start + browse auto-open | S | — |
| B Transparent code regions | S | — |
| C Coders | M | B (cosmetic) |
| D LM Studio | S | — |
| E History view | M–L | C (user attribution) |
| F Whisper + noScribe | L | C (owner), D (unrelated) |
| G Simultaneous work | L | E (port plumbing) |
| H Packaging + gates | M | all |

Ship A–D as one release (quick wins), E alone, F alone, G last
(riskiest). Every phase ends with green gates + a packaged exe smoke.
