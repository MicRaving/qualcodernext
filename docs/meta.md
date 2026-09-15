# Meta-analysis workspace

The Meta-analysis workspace runs a systematic-review style pipeline over a
table of search hits, one row per hit. It mirrors the workflow of a classic
meta-analysis screening pipeline (abstract screening → paper download → data
extraction) while keeping every step optional to automate with the configured
AI backend.

## Pipeline

1. **Import** — from the study left bar's **Import** button. Import a
   search-results file (EBSCOhost XML, Excel `.xlsx`, RIS or CSV); a labeler
   shows the detected sheet, header row and columns so each column can be
   mapped to a meta field. Hits are deduplicated on DOI.
2. **Screening** — the center shows the focused study's abstract next to the
   verdict editor (the study list lives in the left bar). Configure inclusion
   criteria (per project, auto-saved), then either screen manually per hit
   (verdict + certainty per criterion, rationale, intervention type) or start
   an AI screening job from the center menubar. The job clusters several
   abstracts per request and writes editable proposals (`origin=llm`).
3. **Downloads** — the left bar's **Download** button runs the automatic
   retrieval chain for included hits: OpenAlex → Unpaywall → Crossref landing
   page, then a running local Zotero for PDFs the user already have. The
   Unpaywall contact e-mail is set in the center menubar. **Import PDFs**
   batch-imports a folder of PDFs, matching each filename to a hit by DOI or
   title; files assigned per row remain possible too. Zotero has no public
   machine API to "find a PDF for a DOI" — QCnext reimplements the resolver
   semantics natively and treats Zotero as a best-effort reuse source.
4. **Extraction** — pick a coding scheme in the left bar (the **Create**
   button opens the scheme editor), tick the papers to process in the left
   list, then **Autocode selected**. Each paper runs a cheap AI prescreen and
   the full scheme-driven coding prompt. DV metrics are normalized (inferred
   group sizes, `d → yi/vi/sei` conversions) and validated against the metafor
   completeness rules; missing-statistics comparisons are flagged. **Export**
   (CSV/Excel, one row per DV metric) sits in the center menubar; results can
   also be published into QCnext primitives (a case per study with attributes,
   plus codes under `Meta/<scheme>` carrying the extraction rationale). A
   per-request **max chars** box caps the paper text sent to the model
   (head+tail truncated) so an oversized paper cannot hard-fail a
   smaller-context model; whole-queue runs skip eligible papers that have no
   downloaded source instead of erroring. **View PDF** opens the linked paper
   beside the scheme reference.

Each tab drives its queue: the left bar shows all hits (Screening), the
abstract-included hits (Downloads) or the acquired papers (Extraction), and
the Extraction rows expose a **View** dialog with the raw study fields and
effect sizes for verification.

## Local-only in v1

The `meta_*` tables deliberately live **outside** the collaboration sync
(`sync_log`), the undo registry and the coder-visibility views. Meta rows are
project-local; if you work on the same project from multiple devices the meta
tables are not replayed between them. Rows still carry an `owner`, so a later
milestone can add sync/replay additively without a schema change.

## LLM automation

Screening, prescreen and extraction use the same AI configuration as the rest
of QCnext (Settings → AI). Screening and extraction jobs appear as background
tasks and can be paused between units of work, cancelled, and resumed from
where they stopped (screening resumes per hit; extraction re-screens papers
that were not yet processed). AI verdicts are stored with `origin=llm` and
remain editable — saving a verdict promotes it to `origin=manual`.