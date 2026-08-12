# Feature Comparison: MAXQDA 26 vs. QualCoder Next (QCnext v4)

**Compared versions**
- **MAXQDA Release 26 (26.3, June 2026)** — latest release of the commercial QDA suite by VERBI (Win/macOS). Free upgrade for MAXQDA 24 subscribers. Add-ons: AI Assist, MAXQDA Transcription, TeamCloud, Analytics Pro.
- **QCnext v4** — QualCoder rework in this repository (Tauri 2 desktop + React 19 frontend + FastAPI backend). Open-source, local-first.

**Legend:** ✓ = full feature · ~ = partial / equivalent-but-different · ✗ = not available

---

## 1. Platform & licensing

| Feature | MAXQDA 26 | QCnext v4 | Notes |
|---|---|---|---|
| Windows | ✓ | ✓ | |
| macOS | ✓ | ✓ | |
| Linux | ✗ | ✓ (Tauri stack) | MAXQDA is Win/mac only |
| Web/browser version | ✓ (separate product MAXQDA Tailwind) | ✗ | QCnext is a desktop app (frontend is web tech but not distributed as a hosted web app) |
| License model | Commercial subscription; free 14-day trial; free course licenses | Free, open source | |
| In-app update mechanism | ✓ ("Search for updates"; upgrade 26 requires reinstall) | ✓ (Tauri auto-updater, configurable check interval, auto-install) | QCnext: daily/weekly/never |
| Second instance / multi-open of a project | ✗ (single instance) | ✓ (ephemeral backend port, presence registry, project lock with timeout) | QCnext reports other live instances |
| Start screen / recent projects | ✓ | ✓ (Dashboard with recent projects, auto-open last) | |
| Dark theme | ✗ | ✓ (dark/light, persisted) | |
| UI languages | ✓ (~13, incl. Traditional Chinese since 26.0) | ✓ (14 locales) | Both multilingual |
| Unicode analysis in any language | ✓ | ✓ | |

## 2. Data sources & import

| Feature | MAXQDA 26 | QCnext v4 | Notes |
|---|---|---|---|
| Text: .txt | ✓ | ✓ | |
| Rich text .rtf | ✓ | ✓ | |
| Word .docx | ✓ | ✓ | |
| OpenDocument .odt | ✓ | ✓ | |
| HTML / web page files | ✓ (incl. Web Collector capture) | ✓ (import only; no live capture) | |
| Markdown .md | ✓ (since 26.3) | ✓ | |
| EPUB | ~ (as text) | ✓ | |
| LaTeX .tex | ✗ | ✓ | |
| PDF | ✓ | ✓ | See coding section for region coding |
| Excel tables as documents | ✓ (.xlsx as table docs) | ✗ | QCnext only does survey CSV |
| SPSS .sav | ✓ | ✗ | |
| Survey import (CSV/Excel) | ✓ (dedicated Survey Analysis workspace, 26.0) | ✓ (CSV: row = case, attributes, coded text files) | |
| Images | ✓ (jpg/png/gif/bmp/tif…) | ~ (jpg/jpeg/png only) | |
| Audio | ✓ (mp3/wav/m4a/aac…) | ~ (wav/mp3/m4a) | |
| Video | ✓ (mp4/mkv/mov/wmv/avi/m4v…) | ~ (mp4/mkv/mov/wmv/webm/ogg) | |
| Emails (EML/Outlook/MBOX) | ✓ | ✗ | |
| Web page capture (browser extension) | ✓ (MAXQDA Web Collector) | ✗ | |
| YouTube comments | ✓ (Web Collector) | ✗ | |
| Twitter/X data | ✓ (Web Collector) | ✗ | |
| Bibliographic data (Zotero/EndNote/Citavi/BibTeX/RIS) | ✓ | ~ (Zotero 7 local API + RIS import) | |
| Focus group transcripts | ✓ | ~ (speaker detection on AV) | |
| External files linked by path (no copy) | ✓ (re-link support since 26.3) | ✓ (broken-link detection, bulk path repair, mediapath fix) | |
| Project merge (two projects into one) | ✓ | ✓ (zipped .qda merge) | |

## 3. Document organization

| Feature | MAXQDA 26 | QCnext v4 | Notes |
|---|---|---|---|
| Document groups (hierarchical) | ✓ | ~ (static groups: Text/PDF/Images/Audio/Video) | |
| Document sets | ✓ | ~ (saved file filters) | QCnext has no set concept; filters are reusable subsets |
| Code sets | ✓ | ✗ | |
| Variable sets | ✓ | ✗ | |
| Expand/collapse all in trees | ✓ (since 26.0) | ✗ | |
| Sortable/searchable file table | ✓ | ✓ (virtualized, sortable, multi-select, bulk delete) | |
| Saved filters for documents | ~ | ✓ (GET/POST/DELETE saved filters) | |
| Document replacement keeping codings | ✗ | ✓ (replace source with re-anchoring by first-match text) | |
| In-app text editing of sources | ✗ (read-only) | ✓ (edit mode, live diff-based re-anchoring of codings/annotations/case links) | |
| Backup / archive | ✓ (project export/archive) | ✓ (backup-on-open, backups folder) | |
| Zoom controls in document browser | ✓ (since 26.0) | ✓ (in PDF/image coders) | |

## 4. Codes & coding

| Feature | MAXQDA 26 | QCnext v4 | Notes |
|---|---|---|---|
| Hierarchical code system | ✓ (unlimited levels) | ✓ (categories + sub-codes; depth cap 64; namespace-safe legacy tree) | |
| Text coding | ✓ | ✓ (colored spans, overlap tinting, tooltips) | |
| PDF coding | ✓ | ✓ (rectangle regions + text selection reverse-mapped + plain-text mode) | |
| Image coding | ✓ (rectangles) | ✓ (rectangles, move/resize, thumbnails) | |
| Audio/video coding | ✓ (time segments) | ✓ (ms precision, timeline, resizable video pane) | |
| Coding memos on every segment | ✓ | ✓ | |
| Segment weights | ✓ (weight 1–100) | ~ (importance star flag) | |
| Important / star segments | ~ | ✓ | |
| Code colors | ✓ (21 colors + custom) | ✓ (user-configurable global palette) | |
| Code symbols / emojis | ✓ | ✗ | |
| In-vivo coding (code from selected text) | ✓ | ✗ | QCnext: create code manually, or AI-suggested codes |
| Quick coding (single click) | ✓ | ✓ (active code + floating selection toolbar) | |
| Drag & drop coding | ✓ | ✗ | |
| Overlapping codes on same segment | ✓ | ✓ (nested tinted spans) | |
| Sub-codes (code under code) | ✓ | ✓ | |
| Merge codes | ✓ | ✓ | |
| Merge categories | ✓ | ✓ | |
| Creative coding (scratchpad for idea codes) | ✓ | ✗ | |
| Autocode by search terms | ✓ | ✓ (literal, all/first/last, multi-term, per file or project) | |
| Autocode by regex | ✓ | ✓ | |
| Autocode via dictionary | ✓ (MAXDictio) | ✗ | |
| AI autocoding | ✓ (AI Assist suggestions) | ✓ (prompt-based + suggested new codes) | |
| Code visibility / hide codes in documents | ~ | ✓ (per-coder visibility registry, dim/hide segments, highlight single code) | |
| Code search (flat results) | ✓ | ✓ | |
| Segment retrieval with filters | ✓ | ✓ (codes-by-segments, per-code "code in all files") | |

## 5. Memos, notes, annotations, journals

| Feature | MAXQDA 26 | QCnext v4 | Notes |
|---|---|---|---|
| Memos attached to any element (doc, code, group, case, segment, media clip) | ✓ | ~ (codes, categories, files, codings, cases; not groups/clips) | |
| Memo types / icons (11 types) | ✓ | ✗ | QCnext memos are free-form text only |
| Memo Manager (central overview) | ✓ | ✓ (Notes workspace with memo tree) | |
| Memo search | ✓ | ✓ (notes search) | |
| Memo export | ✓ | ~ (codebook export includes memos) | |
| Paraphrases (dedicated function + summary tables) | ✓ | ✗ | QCnext: memo-based paraphrasing only |
| Text annotations (positional) | ✓ | ✓ (span annotations with memo, move between files, inline edit) | |
| Free annotations anywhere | ✓ | ✗ | |
| Journal / logbook | ✓ (logbook) | ✓ (journal entries) | |
| Bookmarks | ✗ | ✓ (one text + one AV bookmark per project) | |
| Audit trail / change history | ~ (logbook + memos) | ✓ (full audit log, paged, filtered, with undo/redo of logged changes) | |

## 6. Search

| Feature | MAXQDA 26 | QCnext v4 | Notes |
|---|---|---|---|
| Project-wide lexical search | ✓ | ~ (file/code/case/note/history searches + autocode find-text) | No dedicated operator-driven search UI in QCnext |
| Boolean operators (AND/OR/NOT, phrases, wildcards) | ✓ | ~ (regex support in autocode) | |
| Search within search results | ✓ | ✗ | |
| Search in memos | ✓ | ✓ | |
| Semantic (AI) search | ✗ | ✓ (embedding cosine similarity, persistent vector index) | QCnext unique |
| Autocode from search hits | ✓ | ✓ (autocode dialog) | |

## 7. Audio/video & transcription

| Feature | MAXQDA 26 | QCnext v4 | Notes |
|---|---|---|---|
| Code media directly without transcript | ✓ | ✓ | |
| Manual transcription mode | ✓ (mode switcher, 26.3; foot pedal support, speed/volume control) | ✗ | QCnext has no manual transcription UI — significant gap |
| Automatic transcription | ✓ (cloud service, 50+ languages; audio track extracted for video, 26.3) | ✓ (local faster-whisper, 13 models, VAD, beam, temperature, translate) | MAXQDA is cloud-based; QCnext runs fully offline |
| Transcript ↔ media time links | ✓ | ✓ ([mm:ss] transcript parse, AV codings linked to transcript) | |
| Live transcript preview during transcription | ✗ | ✓ (streaming partial transcript in UI) | |
| Per-segment auto-coding of transcript | ~ (AI) | ✓ (optional code applied to transcript segments) | |
| Speaker detection / marking | ✓ (focus group feature) | ✓ (name/hash/@/brackets/braces/custom regex; optional speaker codes) | |
| Media playback speed control | ✓ | ✓ (playback rate) | |
| Foot pedal support | ✓ | ✗ | |
| Media clips as first-class segments (retrieve, memo, weight) | ✓ | ~ (retrieve + memo; no weight) | |
| External media re-linking after move/delete | ✓ (26.3) | ✓ (bad-link detection + bulk path rename) | |

## 8. Cases, variables, mixed methods

| Feature | MAXQDA 26 | QCnext v4 | Notes |
|---|---|---|---|
| Case system | ✓ | ✓ (case memos, link whole file or text span) | |
| Document variables | ✓ | ✓ (attribute types: text/number/date/boolean, case or file scope) | |
| Case variables | ✓ | ✓ | |
| Value labels / defined value lists | ✓ | ✗ | |
| Variable import/export | ✓ | ✗ | |
| Mixed methods: quantify codes by variable, group comparisons | ✓ | ~ (attribute report, case heatmaps, coder comparisons) | |
| Statistical analysis (crosstabs, frequencies, R integration) | ✓ (Analytics Pro) | ✗ | |
| Survey Analysis workspace (Questions Browser, freq tables, charts) | ✓ (since 26.0) | ~ (CSV survey import only) | |
| Sentiment analysis | ✓ (AI Assist + survey workspace) | ✗ | |
| Segment hyperlinks / linked quotes | ✓ | ✗ | QCnext links only via graphs |

## 9. Visualization

| Feature | MAXQDA 26 | QCnext v4 | Notes |
|---|---|---|---|
| Word cloud | ✓ (MAXDictio) | ✓ (canvas) | |
| Word frequencies + stop lists | ✓ | ✓ | |
| Dictionary-based content analysis | ✓ (MAXDictio) | ✗ | |
| Keyword-in-context (KWIC) | ✓ | ~ (codes-by-segments / word freq views) | |
| Code Matrix Browser | ✓ | ~ (file×code matrix, stacked bars, heatmaps) | |
| Code Relations Browser (overlaps/crossovers) | ✓ | ✓ (code relations report + co-occurrence) | |
| Code Map (automated) | ✓ | ✓ (graph models: category-hierarchy, file-hierarchy, file-comparison, case-hierarchy, case-comparison, co-occurrence-network) | |
| MAXMaps concept maps (manual editing) | ✓ | ✓ (SVG graph editor: code/category/case/file/free-text/memo nodes, styled labeled lines, arrows, pan/zoom) | |
| Document Portrait | ✓ | ✗ | |
| Document Comparison Chart | ✓ | ✗ | |
| Code Theory Model | ✓ | ~ (case-comparison model) | |
| Charts: bar / stacked / cumulative / heatmap | ✓ | ✓ (7 chart kinds) | |
| Export visuals as images | ✓ | ✓ (PNG) | |
| Colorblind-accessible color dialogs | ✓ (26.3 tooltips) | ✗ | |

## 10. Reports & analysis tools

| Feature | MAXQDA 26 | QCnext v4 | Notes |
|---|---|---|---|
| Code frequency report | ✓ | ✓ (ranked bar + table, cumulative) | |
| Per-code summary (counts by media, files, memo) | ✓ | ✓ | |
| Coded-segment retrieval (flat + per code) | ✓ | ✓ (incl. image rects and AV ms) | |
| Summary Grids (doc/code comparison) | ✓ | ~ (comparison matrix + heatmap) | |
| Summary Tables (paraphrase tables) | ✓ | ✗ | |
| Smart Publisher (Word/PDF/PowerPoint reports) | ✓ | ✗ | QCnext exports CSV/plain text |
| QTT workspace (Questions, Themes, Theories) | ✓ | ✗ | |
| Mixed Methods QTT Worksheet (Creswell 14-step) | ✓ (since 26.0) | ✗ | |
| Send-to-QTT collection | ✓ | ✗ | |
| Exact identical segments detection | ~ | ✓ (exact-matches report) | |
| File summary statistics (words/codes/segments/cases) | ✓ | ✓ | |
| Coder comparison (volume, per-file side-by-side) | ✓ | ✓ (coder-comparison + coder-file-comparison) | |
| Ad-hoc SQL console (read-only, saved queries) | ✗ | ✓ | QCnext unique |
| References manager (RIS + attach PDF/EPUB as sources) | ~ (bibliographic docs) | ✓ | |

## 11. Intercoder reliability & statistics

| Feature | MAXQDA 26 | QCnext v4 | Notes |
|---|---|---|---|
| Cohen's Kappa | ✓ | ✓ | |
| Krippendorff's Alpha | ✓ | ✓ | |
| Gwet's AC1 | ✗ | ✓ | |
| Contingency details (units/categories/pairs, both/only-A/only-B/neither) | ~ | ✓ | |
| Intercoder agreement on media segments | ✓ | ✓ (text/image/AV counts included) | |

## 12. Interchange (import/export)

| Feature | MAXQDA 26 | QCnext v4 | Notes |
|---|---|---|---|
| REFI-QDA export (.qdp) | ✓ | ✓ | |
| REFI-QDA import | ✓ | ✓ (plus automatic format detection) | |
| NVivo import | ✓ | ✗ | |
| ATLAS.ti import | ✓ | ✗ | |
| Transana import | ✓ | ✗ | |
| RQDA import | ✗ | ✓ | |
| Taguette import | ✗ | ✓ | |
| Plain-text codebook export/import | ✓ | ✓ (round-trippable) | |
| Project export as folder structure / archive | ✓ | ~ (project IS a folder; zipped .qda for merging) | |
| Excel export of tables/results | ✓ | ~ (CSV) | |
| Word/PDF/PowerPoint/HTML report export | ✓ | ✗ | |
| CSV export | ✓ | ✓ | |

## 13. Teamwork & collaboration

| Feature | MAXQDA 26 | QCnext v4 | Notes |
|---|---|---|---|
| Cloud collaboration (TeamCloud add-on) | ✓ (shared projects, web access, comments) | ✗ | |
| Real-time team session (simultaneous editing) | ✓ (Team Session) | ~ (multiple live instances + presence; not realtime conflict-merged) | |
| Folder-sync collaboration (Nextcloud/Syncthing-style) | ✗ | ✓ (change-log JSONL sidecars, 60 s cycle, last-write-wins replay, conflict reporting) | QCnext unique |
| Per-user coding visibility control | ~ | ✓ (hide/show a coder's codings project-wide incl. reports) | |
| Coder management (create/switch/rename/delete/reassign) | ✓ (TeamCloud users) | ✓ (local coders with stats, reassign on delete) | |
| User accounts & roles | ✓ (TeamCloud) | ✗ (local coder names only) | |

## 14. AI features

| Feature | MAXQDA 26 | QCnext v4 | Notes |
|---|---|---|---|
| AI chat with documents/segments | ✓ (AI Chat 2.0, 26.3; welcome page, auto-titles) | ✓ (chat modes: general/help/topic exploration/code analysis/text analysis) | |
| Chat with memos | ✓ (26.3, memo selection + analysis) | ✗ | |
| Saved chat context/preferences | ✓ (Chat Preferences: project context, response prefs) | ✗ | |
| AI summarization of segments | ✓ (AI Assist) | ~ (possible via chat, no dedicated tool) | |
| AI paraphrase | ✓ | ✗ | |
| AI suggestion of coded segments | ✓ | ✓ | |
| AI subcode suggestions | ✓ | ✓ | |
| AI sentiment analysis | ✓ | ✗ | |
| AI transcription | ✓ (cloud, 50+ languages) | ✓ (local, offline) | |
| Bring-your-own model/API key | ✓ (AI Assist custom model settings) | ✓ (Ollama, LM Studio, opencode-go, Gemini, GPT, Claude, custom OpenAI-compatible) | |
| Local/offline AI | ✗ (cloud only) | ✓ (Ollama/LM Studio) | |
| Prompt library | ✗ | ✓ (30+ method prompts) | |
| Semantic search over sources | ✗ | ✓ | |
| MCP server (Model Context Protocol) for project data | ✗ | ✓ (JSON-RPC, permission-gated read/write tools, resources, prompts) | QCnext unique |
| AI model listing & connectivity probe | ✗ | ✓ (/ai/models, /ai/status) | |

## 15. App-level / small features

| Feature | MAXQDA 26 | QCnext v4 | Notes |
|---|---|---|---|
| Keyboard shortcuts | ✓ | ✓ (Ctrl+S, Ctrl+Enter, inline rename Tab-cycling…) | |
| Pseudonym management | ✗ | ✓ (pseudonyms.json, used with AI) | |
| Undo of coding actions | ~ | ✓ (unmark-last stack 20 + audit undo/redo) | |
| Document/file filters by type in browser | ✓ (refreshed filter UI, 26.0) | ✓ | |
| Internal links preserved on project share | ✓ (26.0) | ~ (via sync sidecars) | |
| Media file handling performance | ✓ (26.0 optimized) | ✓ | |
| Button/label visual overhaul | ✓ (26.3) | ✓ (design-system per DESIGN.md) | Cosmetic both |
| Background task queue (imports/transcription) | ✓ | ✓ (top-bar indicator + status) | |
| Multilingual project content (Unicode) | ✓ | ✓ | |
| Status bar with project stats | ~ | ✓ (files/codes/cases/journals/annotations/memos/version) | |

---

## Summary

| Dimension | MAXQDA 26 | QCnext v4 |
|---|---|---|
| Where MAXQDA 26 leads | Manual transcription mode, foot pedal, MAXDictio dictionary analysis, Smart Publisher reports, QTT + mixed-methods worksheet, Survey Analysis workspace, TeamCloud real-time collaboration, NVivo/ATLAS.ti/Transana imports, SPSS/Excel table docs, emails, web/YouTube capture, creative coding, in-vivo coding, weights, memo types, dark-side: no dark theme | — |
| Where QCnext v4 leads | Local/offline AI (Ollama/LM Studio), MCP server, semantic search, audit log with undo/redo, editable sources with re-anchoring, SQL console, exact-matches report, Gwet's AC1, folder-sync collaboration (no vendor cloud), pseudonyms, bookmarking, document replacement, local whisper transcription incl. streaming preview, regex/boolean autocode, per-coder visibility | — |
| Roughly on par | Text/PDF/image/AV coding, code tree + colors + merge, memos/annotations/journals, code frequencies & matrices, co-occurrence, graphs/concept maps, word cloud/frequencies, inter-rater (Kappa/Alpha), REFI-QDA, autocode, cases & attributes, transcription (auto), speaker detection, 14+ languages | |
| Clear gaps in QCnext | Manual transcription, rich report publishing, MAXDictio, SPSS/survey-questionnaire analysis, email/web/YouTube import, team cloud, in-vivo/drag-drop/creative coding, memo types, weights | |
| Clear gaps in MAXQDA | Offline AI, MCP, semantic search, audit/undo, text editing of sources, SQL, Linux, dark theme, Gwet's AC1, RQDA/Taguette import, folder-sync team work | |

**Bottom line:** MAXQDA 26 is the fuller end-to-end research suite (mixed methods, publishing, team cloud, manual transcription, broad data ingest). QCnext is a strong local-first analyst: it matches the core coding/analysis/visualization workflow, and uniquely offers offline AI, MCP, semantic search, undo/audit, SQL, and sync-based collaboration — but lacks MAXQDA's publishing, quantitative-text-analysis, survey/SPSS, and real-time team features.

*Sources: MAXQDA product pages, release notes for MAXQDA 26.0 (Nov 2025), 26.3 (June 2026); QCnext: backend routers + frontend views in this repository.*
