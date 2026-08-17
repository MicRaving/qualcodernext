# Import / Export (interchange)

QCnext exchanges projects with other QDA tools. You can **export** the whole
project in the open **REFI-QDA** standard, and **import** many formats with
automatic detection. The interchange UI appears standalone or embedded in the
Settings pane.

## How to reach it

- Settings → **Import / Export** (the embedded variant). There is no ribbon
  entry; the pane is part of the Settings right bar.

## Export

One click: **REFI-QDA export** — a download of the project's codebook,
sources, codings and cases as a `.qdp` document that other REFI-compliant
tools (NVivo, ATLAS.ti, MAXQDA, …) can open.

## Import

Pick a file; a card shows the **detected format** (by extension) with
Import / Cancel; the backend re-detects the real format. After a successful
import, a **result card** shows counts of whatever the importer produced
(codes, categories, files, codings, cases, references, attributes) plus any
message, and the project refreshes when content changed.

## Supported formats

| Format | Extension | What is imported |
|---|---|---|
| **REFI-QDA** | `.qdp` / `.qdc` | Codebook, sources, codings, cases from any REFI-compliant tool |
| **RQDA** | `.rqda` | A classic QualCoder v3 project file |
| **Taguette** | `.tag` / `.json` | Codes and coded excerpts |
| **Transana** | `.tprd` | Media transcripts, keyword codes and time-based codings |
| **NVivo** | `.nvpx` | Best-effort: documents, codes, codings where positions are available |
| **ATLAS.ti** | — | No direct `.atlproj`/`.atlasti` support — export ATLAS.ti to REFI-QDA (`.qdp`) and import that instead |
| **RIS** | `.ris` | Bibliographic references (as journal references) |
| **Survey** | `.csv` | Columns imported as cases with attributes; qualitative columns become one text file per row |
| **Excel** | `.xlsx` | Multi-column sheets like a survey CSV; other sheets become one text file per sheet |
| **SPSS** | `.sav` | Variables imported as case attributes; qualitative string variables become one text file per row |
| **Codebook** | `.txt` / `.csv` | Plain-text codebook with `category>>subcategory>>code` lines (round-trips with the Codebook report) |
| **Project merge** | `.zip` | Merge another `.qda` project into the open one |
| **Zotero** | — | References from the local Zotero API (localhost:23119, Zotero 7+) |

## High-level logic

The importer **sniffs** the real format regardless of the filename (e.g. an
NVivo zip is detected by its XML marker). Imports that build new content
(survey/Excel/SPSS/codebook/RIS/REFI/NVivo/RQDA/Taguette/Transana) can be
**previewed** first: a read-only parse reports the "will create" destination
summary before you commit. Project merges are uncountable and skipped in the
preview.
