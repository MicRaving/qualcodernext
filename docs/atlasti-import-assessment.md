# ATLAS.ti Import — Assessment (2026-08)

**Status: REFI-QDA path already works today. Native bundle import: NOT recommended (no public format, no open-source parsers).**

## 1. The ATLAS.ti format landscape (verified from official ATLAS.ti docs)

| Format | Used by | Nature | Spec publicly available? |
|---|---|---|---|
| `.qdp` / `.qdpx` (REFI-QDA) | All modern versions (Win/Mac/Web) | Open standard (REFI-QDA, qdasoftware.org) | ✅ Yes — full XSD + spec |
| XML export (Mac, "Project → Export XML") | ATLAS.ti for Mac (older) | Single XML file; blueprint of the UK Data Service qualitative archive (QualiBank) standard | ✅ Yes (archival standard docs) |
| `.atlproj` / `.atlproj23` / `.atlproj24` | ATLAS.ti 9/10/22/24 (Win + Mac) | Project bundle "box" (project + documents) | ❌ No — proprietary container, version-specific; ATLAS.ti itself is not backward compatible |
| `.atlasti` | Current versions + ATLAS.ti Web | Project bundle (successor of .atlproj) | ❌ No |
| `.proj` | Legacy ATLAS.ti 5–7 (Windows) | Proprietary binary | ❌ No |

Key vendor facts (from ATLAS.ti help articles):
- Current versions export projects as `.atlasti`; older ones as `.atlproj`/`.atlprojx`; "ATLAS.ti is not backward compatible."
- ATLAS.ti supports **REFI-QDA export/import**, and NVivo officially imports ATLAS.ti projects via **XML export or `.qdpx`** — the same two interchange routes QCnext already supports.

## 2. Feasibility per route for QCnext

### 2.1 REFI-QDA (`.qdp`/`.qdpx`) — ✅ DONE, primary path
QCnext already implements REFI-QDA import AND export (`POST /interchange/import/refi`, `GET /interchange/export/refi`, auto-detected in `/auto`). An ATLAS.ti user can migrate with zero new code:
`ATLAS.ti → Export → REFI-QDA (.qdp) → QCnext Interchange → Import`.
Coverage: documents, codes/code groups, codings/quotations, memos, cases/attributes (whatever the export carries).

**Action (zero-code):** document this path clearly in the Interchange view help and docs.

### 2.2 ATLAS.ti Mac XML export — ✅ FEASIBLE (best-effort, medium effort)
- Single XML, non-proprietary, structurally documented via the UK Data Service / QualiBank archival standard (the format was explicitly designed for external use/archiving).
- Element families: documents (primary docs), codes (code families), quotations (with positions), memos, relations.
- Effort: mirrors the NVivo `.nvpx` importer built in wave 4 (ZIP→XML became XML→tables; same defensive patterns: namespace-tolerant matching, skip-and-count, never fatal).
- Estimate: 2–4 person-days including a synthetic-fixture test suite.
- Validation problem: need one real ATLAS.ti XML export as a fixture to pin the exact element names (the archive docs describe the model, not necessarily the exact export serialization).

### 2.3 `.atlproj` / `.atlproj24` / `.atlasti` bundles — ❌ NOT RECOMMENDED
- No public specification. Container + internal model vary by version; ATLAS.ti itself only reads its own generation of files.
- **No verified open-source parser exists** (GitHub search: zero hits for `atlproj24`; community parsers that exist target the REFI/XML exports, not the bundle).
- Reverse-engineering the bundle would be a multi-week effort with high breakage risk per ATLAS.ti release — poor cost/benefit while the REFI path covers the same migration.
- Verdict: keep as **"Maybe"** on the roadmap; revisit only if a documented/OSS mapping appears.

### 2.4 Legacy `.proj` — skip (proprietary binary, 20 years old).

## 3. Open-source projects to draw inspiration from (verified)

| Project | URL | License | What it offers |
|---|---|---|---|
| `borisbachmann/atlas-qdpx` | github.com/borisbachmann/atlas-qdpx | MIT | Python tool that extracts annotations from **ATLAS.ti REFI-QDA exports** — closest existing reference for the mapping we'd build on |
| `openqda/refi-tools` | github.com/openqda/refi-tools | AGPL-3.0 | REFI-QDA utilities + XSD schemas + spec PDFs (the interchange standard ATLAS.ti implements) |
| `cbrincoveanu/pyrefiqda` | github.com/cbrincoveanu/pyrefiqda | MIT | Python/Pydantic mapping of `.qdpx` |
| `vmnacar/refio` | github.com/vmnacar/refio | MIT | Python read/write/convert of `.qdpx/.qde/.qdc` |
| `sky-loom/refi-qda` | github.com/sky-loom/refi-qda | MIT | TypeScript interfaces for REFI-QDA |
| QualiBank / UK Data Service XML | qualibank.ukdataservice.ac.uk | — | Archival documentation of the ATLAS.ti-XML-derived standard (for the 2.2 route) |

Not verified / excluded: the "atlastic" Python package (repo is an unrelated project; PyPI 404), an `atlast` R package on CRAN (page 404 — archived or renamed; do not rely on it without re-verification).

## 4. Recommendation

1. **Ship the docs-only change now**: Interchange help entry "ATLAS.ti — export as REFI-QDA (.qdp) and import here" + a paragraph in `docs/interchange.md`. Zero code, covers 100% of current ATLAS.ti users.
2. **If native-format import is still wanted**, implement route 2.2 (ATLAS.ti XML export) as a best-effort importer, modeled on `nvivo_import.py`, with a real fixture obtained from an ATLAS.ti Mac user. Add it to the roadmap as a concrete item.
3. **Do not invest in `.atlproj`/`.atlasti` bundles** unless a documented mapping or OSS parser appears — tracked as "Maybe" in the roadmap and README.
