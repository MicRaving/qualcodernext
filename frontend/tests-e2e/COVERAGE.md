# E2E coverage matrix

Every user operation documented in the in-app help docs
(`backend/src/qualcoder_api/help_docs/*.md`), the UI spec
(`frontend/src/DESIGN.md`) and the view registry (`frontend/src/stores/project.ts`
/ `frontend/src/features/analyze/registry.ts`), mapped to the spec that
exercises it. **Covered** = the operation is actually driven through the UI and
asserted (not merely that its screen exists). **Gap** = documented but not
exercised by any e2e test.

Legend: A=advanced.spec.ts · App=app.spec.ts · CF=coding-flows.spec.ts ·
F=features.spec.ts · IA=inspector-annotation.spec.ts · M=media.spec.ts ·
R=roadmap.spec.ts · S=smoke-features.spec.ts · SY=sync.spec.ts ·
T=tasks-a11y.spec.ts · CG=coverage-gaps.spec.ts · W=coverage-wave.spec.ts

## Summary

| | Count |
|---|---|
| Covered operations | **106** |
| Gaps | **139** |
| Total documented operations | **245** |

Top gaps worth filling next (quick to script, high value):
1. **AI agentic chat** — none of the chat flows are e2e-driven yet (no model
   in CI): composer + context pickers, the Tools/Confirm-writes toggles, the
   approval UI, tool bubbles and the permission badge. Needs a stubbed
   OpenAI-compatible backend.
2. **History undo/redo** — W now drives per-row undo + redo (audit-log rows
   carry undo icons); detail modal + pagination remain untested.
3. **Notes workspace** — W covers journal create/edit/save and the code-memo
   tree (add/save); annotation tabs, memo delete and "open file" remain.
4. **AV transcript coding** — the transcript pane is a full text-coder surface
   but only manual-mode editing is covered.
5. **Sentiment / Stats / Summary-table** — W runs the lexicon scoring, the
   crosstab (chi-square) and the file×code grid; the other report modes
   (AI sentiment, group comparison, case scope) stay untested.

---

## Shell (workspace.md)

| Area | User operation | Covered? | Gap? |
|---|---|---|---|
| Ribbon | Nav buttons (Dashboard/Files/Cases/Notes/QTT/Reports) switch views | App, F, S | — |
| Ribbon | Task-queue chip opens flyout; pause/resume/clear-finished | T (batch autocode) | — |
| Task queue | Per-task remove (trashcan) | T | — |
| Task queue | Drag-to-reorder queued jobs | — | **Gap** |
| Task queue | Import progress row (done/total) | — | **Gap** |
| Task queue | App-update status row (available → download) | — | **Gap** |
| Coder switcher | Open flyout, add coder, per-row delete (+ reassignment prompt) | T | — |
| Coder switcher | Switch current coder | — | **Gap** |
| Coder switcher | Rename coder | — | **Gap** |
| Coder switcher | Per-coder stats | — | **Gap** |
| Coder switcher | Per-coder visibility toggle for sync | — | **Gap** |
| Coder switcher | Collaboration sync switch, status, "Sync now" | SY | — |
| Inspector | File details (type/date/owner/memo), "Open in coder" | IA (annotation), F | — |
| Inspector | Add annotation inline | IA | — |
| Inspector | Code details: highlight-in-open-file, memo edit, recent segments jump, links in/out | — | **Gap** |
| Inspector | Right-click memo label → Memos tab | — | **Gap** |
| Layout | Resize sidebars; drag-hide past minimum; edge-arrow recall | T | — |
| Status bar | Project name · file/code/case/journal counts · version | — | **Gap** |
| Theme | Dark/light persistence | A (localStorage) | — |
| A11y | Display-mode dropdown applies classes (dashboard + settings) | T | — |
| A11y | Screenreader aria-live region + skip link | — | **Gap** |
| Keyboard | Escape closes floating UI; Ctrl+S in edit mode | — | **Gap** |

## Dashboard (workspace.md)

| Area | User operation | Covered? | Gap? |
|---|---|---|---|
| Empty state | Dashboard without project: New/Open enabled, nav disabled | App | — |
| Project | New project dialog (path input) | A, App, F, M, R, T, CG | — |
| Project | Open project dialog → nonexistent path error banner | A | — |
| Project | Open locked project reports the locking user | — | **Gap** |
| Recent | Recent-projects list reopens on click | App, A | — |
| Recent | Recent list persists across reload | A | — |
| Stats | Stat cards (files/codes/categories/cases/attr types/journal) | — | **Gap** |
| A11y | Dashboard display-mode dropdown | T | — |

## Files (files.md)

| Area | User operation | Covered? | Gap? |
|---|---|---|---|
| Import | Import text/PDF/image/audio (multi-file) | A, App, CF, F, M, T, CG | — |
| Import | Duplicate import → "Skipped (duplicate)" banner | A | — |
| Import | Import progress in the ribbon queue flyout | — | **Gap** |
| Table | Sortable columns (name/type/date/owner) | — | **Gap** |
| Table | Sidebar search filters groups + table | — | **Gap** |
| Table | Row click opens the matching coder | A, CF, F, M, T, CG | — |
| Selection | Multi-row checkboxes; batch buttons with eligible/total counts | T | — |
| Selection | Select-all checkbox | — | **Gap** |
| Selection | Batch transcribe (enabled path on AV media) | T (disabled state only) | **Gap** |
| Selection | Batch autocode → queued background jobs | T | — |
| Selection | Delete selected (danger, confirm) | — | **Gap** |
| Context menu | Right-click row → Rename / Edit memo / Delete | W | — |
| Context menu | Assign to case (prompt) | W (presence) | — |
| Context menu | Replace file (text sources) | W (presence) | — |
| Filters | Saved filters: save/apply/delete | — | **Gap** |
| URL import | UrlImportDialog (reddit/youtube/article/html) | — | **Gap** |
| URL import | Leftbar "URL" button (files sidebar, next to Import) opens the dialog | — | **Gap** |
| Repair | Broken-links list + per-row "Fix" | — | **Gap** |
| Repair | Bulk rename path (prefix replace) | — | **Gap** |
| Empty state | No-files / no-search-match hints | — | **Gap** |

## Text coder (files.md)

| Area | User operation | Covered? | Gap? |
|---|---|---|---|
| Selection | Toolbar appears on text selection | CF, F, CG | — |
| Selection | Code via toolbar → CodePicker (search + create) | CG | — |
| Selection | Code via sidebar code click (active code) | F | — |
| Selection | Annotate inline popover | — | **Gap** |
| Selection | Copy segment link → "Link copied" feedback | CG | — |
| Selection | Paste link here → link created | CG | — |
| Selection | Send to QTT → pick worksheet → segment item stored | CG | — |
| Segments | Coded-segment rendering, click → details panel (swatch/memo/date/delete) | F, A (delete) | — |
| Segments | Clicking a coded segment also shows the code in the right-bar Inspector | — | **Gap** |
| Segments | Unmark last (undo stack) | — | **Gap** |
| Segments | Link marker jump → switches file + flashes span | CG | — |
| Annotations | Annotation details panel edit memo / delete | — | **Gap** |
| Edit mode | Enter edit mode; live shifted highlights; Ctrl+S / Save commit | — | **Gap** |
| Edit mode | Escape / Cancel discards (confirm when dirty) | — | **Gap** |
| Autocode | Dialog: prompt, multi-code select, run | App, F, CF (multi-code) | — |
| Autocode | Suggest-new-codes option | CF (presence) | — |
| Dictionary | Autocode with dictionary (dialog tab) | — | **Gap** |
| Bookmarks | Set bookmark; go-to; persistence | CG | — |
| Hidden codes | Sidebar toggle hides segments in the document | — | **Gap** |
| Jump | Inspector recent-segment → jump+flash | — | **Gap** |
| Code colors | Segments tinted per code color | implicit (rendered) | — |

## PDF coder (files.md)

| Area | User operation | Covered? | Gap? |
|---|---|---|---|
| Render | pdf.js page renders (role=img "Page 1 of 1") | A, CF, T | — |
| Coding | Region coding (drag → CodePicker → overlay → details → delete) | A | — |
| Coding | Text coding (drag on text items → plain-text-layer coding) | CF | — |
| Plain text | Plain-text pane on/off; split with draggable divider | T | — |
| Plain text | "Rendered mode" back toggle | — | **Gap** |
| Zoom | Fit width + 50/75/100/150 % | — | **Gap** |
| Pages | Single-page mode, prev/next, page-number input | — | **Gap** |
| Overlays | Edit region (prompt x1,y1,width,height) | — | **Gap** |
| Hidden codes | Overlays of hidden codes dimmed | — | **Gap** |
| Autocode | Autocode dialog inside PdfCoder | — | **Gap** |
| CodePicker | Search + create-new-code | A, F, M | — |

## Image coder (files.md)

| Area | User operation | Covered? | Gap? |
|---|---|---|---|
| Coding | Drag a rectangle → CodePicker → colored overlay | F | — |
| Coding | Second rectangle while one is selected | F | — |
| Overlay | Click region → details panel (swatch, memo, size) | F | — |
| Overlay | Delete region (actual delete) | F (button presence) | **Gap** |
| Overlay | Edit region (prompt) | — | **Gap** |
| Zoom | Zoom in/out/fit with percentage readout | — | **Gap** |
| Hidden codes | Dimmed overlays | — | **Gap** |
| Errors | Load error + Retry | — | **Gap** |

## Memo gutter (DESIGN.md §10a)

| Area | User operation | Covered? | Gap? |
|---|---|---|---|
| Toggle | "Memos" button shows/hides gutter | — | **Gap** |
| Cards | Collapsed card (dot + name + memo preview + weight chip) | — | **Gap** |
| Cards | Expanded card (header + weight steppers + memo textarea + delete) | — | **Gap** |
| Stacking | "+N more" chip when > 3 cards at same anchor | — | **Gap** |
| Selection | Click card to expand; click again or Escape to collapse | — | **Gap** |
| Bubble | When gutter hidden, selecting segment opens floating bubble | — | **Gap** |
| Memo | Edit memo in card/bubble, save on blur | — | **Gap** |
| Weight | Stepper increment/decrement in card/bubble | — | **Gap** |
| Delete | Delete coding from card/bubble | — | **Gap** |
| Important | Toggle important flag from card/bubble | — | **Gap** |

## Audio/video coder (files.md)

| Area | User operation | Covered? | Gap? |
|---|---|---|---|
| Playback | Import WAV; duration metadata; play/pause toggle | M | — |
| Transport | Click-to-seek timeline; Set start; Set end & code | M | — |
| Transport | Playback-speed selector (0.5×–2×) | — | **Gap** |
| Segments | Timeline block click → seek + details + delete | M | — |
| Transcript | Auto transcript `[mm:ss]` lines; active line highlight | M (whisper run) | — |
| Transcript | Click a line to seek | — | **Gap** |
| Transcript | Full text-coder surface: select → Code/Annotate/links/autocode | — | **Gap** |
| Transcription | TranscribeDialog options (model/lang/VAD/beam/timestamps/segment coding) | M (model select) | — |
| Transcription | Live partial transcript preview while job runs | — | **Gap** |
| Manual | Transcribe-mode toggle → editable draft → save/commit | M | — |
| Manual | Enter/clock inserts `[mm:ss]` at caret | — | **Gap** |
| Speakers | Speaker detect/review/mark | — | **Gap** |
| Bookmarks | AV bookmark set / go-to (seek) | — | **Gap** |
| Media keys | F9 / Ctrl+Space / OS media keys | — | **Gap** |
| Video | Video pane hide/show + resize divider | — | **Gap** |

## Cases + attributes (cases.md)

| Area | User operation | Covered? | Gap? |
|---|---|---|---|
| List | Add case (untitled, inline name editor) | F, R | — |
| List | Search cases | — | **Gap** |
| List | Rename / delete case (context menu) | — | **Gap** |
| Details | Case memo textarea + Save | — | **Gap** |
| Properties | Attribute type create; set value; persistence | F | — |
| Properties | Attribute type with value labels → select; persist value | R | — |
| Properties | Add/edit/remove attribute values | F (add/set) | — |
| Members | Member files list + unlink | — | **Gap** |
| Link | Link-file dropdown + Link button | — | **Gap** |
| Files | Assign to case from the Files context menu | — | **Gap** |

## Notes (notes.md)

| Area | User operation | Covered? | Gap? |
|---|---|---|---|
| Ribbon | Journal ribbon nav | S | — |
| Journal | Add entry; edit text; Save; rename; delete | W (add/edit/save) | — |
| Annotations | Tab lists all annotations; inline memo edit; delete; move file | — | **Gap** |
| Annotations | Add from the Notes list header | — | **Gap** |
| Memos | Code-memo tree; files-with-memos; add/save/delete memo | W (code tree, add/save) | — |
| Memos | "Open file" from a file memo | — | **Gap** |

## Analysis — reports (reports.md)

| Report | Operation | Covered? | Gap? |
|---|---|---|---|
| Registry | Left-bar lists all 15 reports + tools + graphs; nav + aria-current | R, S | — |
| Code frequencies | Ranked list + details table with counts | App | — |
| Code frequencies | Row → code summary card; Cumulative mode chart; CSV | — | **Gap** |
| Code segments | Flat table; code/coder picker; rich single-code view; compare-coders | — | **Gap** |
| File × code | Dimension picker; table/stacked/heatmap toggle; CSV | — | **Gap** |
| Code relations | Co-occurrence matrix; crossovers mode; CSV | — | **Gap** |
| Interrater | Coder chips; alpha; pairwise table; agreement card | — | **Gap** |
| Text & corpus | Word cloud / exact matches / file summary / attributes tabs; CSV | — | **Gap** |
| Dictionary | Create dictionary; add term→code entry; autocode all sources | CG | — |
| Dictionary | Import (.txt/.csv); frequency matrix + normalize; CSV | — | **Gap** |
| Stats | Crosstab (chi-square); group comparison; code-by-variable; CSV | W (crosstab chi-square) | — |
| Summary table | Document/case × code grid; inline memo edit | W | — |
| Sentiment | Lexicon mode run; AI mode; distribution chips; CSV | W (lexicon + chips) | — |
| Document compare | Two-file chart; stats; block click → jump; CSV | — | **Gap** |
| Codebook | Download codebook; copy to clipboard; memos toggle | S (button presence) | — |
| References | RIS table; open source; detach/attach; delete; CSV | — | **Gap** |
| SQL | Run ad-hoc query; results table | F | — |
| SQL | Save/load/delete saved queries; non-SELECT rejection | — | **Gap** |
| Publish | Publish dialog: formats, filename, real .docx export | CG | — |
| CSV | Report CSV exports (codebook copy only) | — | **Gap** |

## Graphs (reports.md)

| Area | User operation | Covered? | Gap? |
|---|---|---|---|
| Toolbar | Graph list; Add (name dialog); Delete (confirm) | CF | — |
| Toolbar | Models dialog (six generators) | — | **Gap** |
| Toolbar | Zoom in/out; Connect (link mode) | — | **Gap** |
| Canvas | Pan; dbl-click context menu → add nodes (all kinds) | — | **Gap** |
| Nodes | Drag to move; details (label edit, Bold, Font+, Delete) | — | **Gap** |
| Lines | Create via Connect; label edit; arrow mode; Delete | — | **Gap** |
| Reports nav | Graphs entry under Reports | S, CF | — |

## QTT (reports.md)

| Area | User operation | Covered? | Gap? |
|---|---|---|---|
| Worksheets | Create worksheet (Qual template); appears in list; select | R | — |
| Worksheets | Mixed template (two-column) | — | **Gap** |
| Worksheets | Rename / delete worksheet | — | **Gap** |
| Info | Research question/purpose/framework editors; Save | R (RQ value) | — |
| Sections | New-note input per card; note item added | R | — |
| Items | Segment item from the coder's Send-to-QTT | CG | — |
| Items | Chart item (report reference) | — | **Gap** |
| Items | Link item (external URL) | — | **Gap** |
| Items | Move item to another section; delete item | — | **Gap** |
| Items | Click segment → jump into coder + flash | — | **Gap** |

## Creative (reports.md)

| Area | User operation | Covered? | Gap? |
|---|---|---|---|
| Panel | Open from ribbon; add note; item appears | R | — |
| Items | Inline edit (pencil) with Save/Cancel | — | **Gap** |
| Items | Delete item | — | **Gap** |
| Items | Search filter | — | **Gap** |
| Items | Promote to code (with source-span coding) | — | **Gap** |
| Items | Source chip → jump to file in coder | — | **Gap** |

## AI (ai.md)

| Area | User operation | Covered? | Gap? |
|---|---|---|---|
| Pane | Ribbon AI toggle opens the chat pane (and closes it) | App (pane presence) | — |
| Chat | Composer send; thinking indicator; clear | — | **Gap** |
| Chat | Context pickers (memos/codes/files) feed the prompt | — | **Gap** |
| Chat | "All" toggle selects/clears every memos+code+file; on by default | — | **Gap** |
| Chat | Data selector collapses/expands via the arrow in its header | — | **Gap** |
| Chat | Assistant replies render as markdown (headings/lists/code) | — | **Gap** |
| Chat | Prompt-library dropdown (Analysis / Specialized / My templates) | — | **Gap** |
| Chat | Wrapping prompt: edit + reset-to-default (template editor) | — | **Gap** |
| Chat | Personas: edit each chat mode's system prompt + reset-to-default | — | **Gap** |
| Chat | Built-in templates: edit via app-wide override; Reset to default | — | **Gap** |
| Chat | "Save globally": copy a project template to the app store | — | **Gap** |
| Chat | History: new chat, open session, inline rename/delete | — | **Gap** |
| Agentic | "Tools" toggle hands the assistant the MCP tools | — | **Gap** |
| Agentic | "Confirm writes" pauses before a write; Approve/Reject | — | **Gap** |
| Agentic | Executed tools shown as "Tools used" lines under the answer | — | **Gap** |
| Agentic | Read-only tool calls show no "Rejected" tag | — | **Gap** |
| Agentic | Sidebar MCP access toggle (Read only / Read + write / Full access) | — | **Gap** |
| Search | Semantic search via the ribbon flyout; result → open in coder | — | **Gap** |
| Search | Flyout has no header bar; the query lives in the ribbon input | — | **Gap** |
| Search | "X" in the ribbon input clears the query (search.clear) | — | **Gap** |
| Settings | AI enable, provider, model list, base URL, key, MCP perms | App (pane presence) | — |
| Settings | "Check" service status probe | — | **Gap** |
| Settings | Semantic index status / build / rebuild / delete | — | **Gap** |

## Settings (ai.md)

| Area | User operation | Covered? | Gap? |
|---|---|---|---|
| Pane | Open; Appearance + AI assistant sections | App | — |
| Appearance | Dark/light theme switch via the Settings UI | A (localStorage) | **Gap** |
| Language | UI locale dropdown | — | **Gap** |
| A11y | Mode dropdown (off/screenreader/high-contrast/large-text/reduced-motion/colorblind) | T (3 modes) | — |
| Import/Export | REFI export link; auto-detect import; result card counts | F | — |
| AI | Provider/model/base/key/MCP configuration | — | **Gap** |
| Pseudonyms | Add pair; list; delete | — | **Gap** |
| Updates | Auto-update toggle; interval; Check now; Install | — | **Gap** |
| About | App text | — | **Gap** |

## Interchange

| Area | User operation | Covered? | Gap? |
|---|---|---|---|
| Export | REFI-QDA download | F | — |
| Import | REFI-QDA (.qdp) with codes/sources/codings/cases | F | — |
| Import | RQDA / Taguette / Transana / RIS / Survey CSV / XLSX / SAV / codebook / merge / Zotero | — | **Gap** |

## History

| Area | User operation | Covered? | Gap? |
|---|---|---|---|
| Log | Open pane; change cards with action labels | F | — |
| Filters | Filter by action (narrows list) | F | — |
| Filters | Filter by coder; refresh button | — | **Gap** |
| Search | Client-side text search | — | **Gap** |
| Undo | Per-row undo; redo stack | W | — |
| Details | Card click → detail modal (diff for source edits) | — | **Gap** |
| Pagination | 100 rows/page, prev/next, range readout | — | **Gap** |

## Status & tasks (workspace.md)

| Area | User operation | Covered? | Gap? |
|---|---|---|---|
| Queue | Flyout rows, pause/resume, per-task remove, clear finished | T | — |
| Queue | Drag-to-reorder jobs | — | **Gap** |
| Completion | Toast + project refresh when a job finishes | T (implicit) | — |
| Import | Ribbon chip fill while importing | — | **Gap** |
| Sync | Enable/disable cycle; last-sync/pending/error; Sync now | SY | — |
| Sync | Shared-folder auto-detect notice | SY | — |
| Sync | Live coder presence: active-coder indicator + current file | SY | — |
| Sync | Sync dot state on the coder switcher | — | **Gap** |
| Visibility | Hide a coder's codings from other users | — | **Gap** |
| Lock | Open an in-use project reports the locking user | — | **Gap** |

---

*Generated against the current docs (v0.1.0); update when screens change.
Counts: covered rows are the "Covered?" cells with a spec reference; "—" in both
columns marks implicit-only coverage.*
