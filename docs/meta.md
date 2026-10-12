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
   mapped to a meta field. Hits are deduplicated on DOI, and on normalized
   title + authors when no DOI is present.
2. **Screening** — the center shows the focused study's abstract next to the
   verdict editor (the study list lives in the left bar). Configure inclusion
   criteria (per project, auto-saved), then either screen manually per hit
   (verdict + certainty per criterion, rationale, intervention type) or start
   an AI screening job from the center menubar. The job clusters several
   abstracts per request and writes editable proposals (`origin=llm`). Criteria
   are created in the criteria editor and may be a Yes/No/Unsure *verdict*, a
   *classify* criterion with named options, or a *number*; each carries the
   values that count as a pass, an exclusion-reason label (used by PRISMA), an
   optional *gating* flag (informational criteria never block inclusion) and
   help text. The left bar adds To-screen/Screened/Included/Excluded filters, a
   progress bar and a select-all control. Abstract and full-text verdicts are
   stored separately (Screening always records the abstract stage; full-text
   exclusion happens from the Extraction tab, see below), and the verdict pane
   supports quick keyboard screening: `Y`/`N`/`U`
   set the focused criterion and advance to the next one (the last one saves and
   loads the next abstract), `Tab`/`Shift+Tab` move between criteria, and
   `↑`/`↓` between studies. The **Blind** toggle sits in the center menubar and
   hides the AI proposals.
3. **Downloads** — the left bar's **Download** button runs the automatic
   retrieval chain for included hits. It collects every open-access candidate
   (OpenAlex locations, Unpaywall `oa_locations`, Europe PMC) and tries them
   **repository mirrors first**, then the publisher PDF, the Crossref landing
   page and the DOI resolver, so one blocked source no longer sinks the paper;
   a running local Zotero remains a best-effort reuse source. The Download left
   bar shows a **downloaded / total** indicator with a failed count, each row
   keeps its status pill, and a failure message names the reason (e.g.
   `all 3 sources blocked (last: HTTP 403)`) or `no open-access copy found`.
   The Unpaywall contact e-mail is set in the center menubar. **Import PDFs**
   batch-imports a folder of PDFs, matching each filename to a hit by DOI or
   title; files assigned per row remain possible too. Zotero has no public
   machine API to "find a PDF for a DOI" — QCnext reimplements the resolver
   semantics natively and treats Zotero as a best-effort reuse source.
   Clicking a row opens its paper in the app right bar, using the same themed
   PDF viewer as the coding center.
4. **Extraction** — a Coding-style split view: the scheme-driven coding form on
   the left (a collapsible full-text screening panel above it) and the study's
   linked paper on the right, with the same draggable divider as the Coding
   panels (reusing `useSplitResize` and the canvas PDF viewer). The scheme
   `<Select>` and the **Schema editor** button sit in the center menubar; the
   Extract left bar is just the study list. The full-text panel starts
   collapsed and never pre-fills verdicts — a criterion is only recorded once
   you answer it. Tick the
   papers to process and **Autocode selected**, or code by hand — typing a level
   number (`1..9`) picks that option for a categorical field and advances,
   `Enter` advances from a number field, and `Tab`/`Shift+Tab` move between
   fields. Each paper runs a cheap AI prescreen and the full scheme-driven
   coding prompt. DV metrics are normalized (inferred group sizes,
   `d → yi/vi/sei` conversions) and validated against the metafor completeness
   rules; missing-statistics comparisons are flagged. **Export** (Excel, one
   row per DV metric) sits in the center menubar; results can also be published
   into QCnext primitives (a case per study with attributes, plus codes under
   `Meta/<scheme>` carrying the extraction rationale). A per-request **max
   chars** box caps the paper text sent to the model (head+tail truncated) so an
   oversized paper cannot hard-fail a smaller-context model; whole-queue runs
   skip eligible papers that have no downloaded source instead of erroring.
   Extractions can be paused/resumed.
   Schemes are created in the scheme editor: typed fields with
   text/number/boolean/select/multiselect/date/JSON/object-list/key-value
   editors, an optional repeatable contrast/**metrics** section, and a
   controlled **role** per field (`study_id`, `dv_domain`, `n1`/`m1`/`sd1`…,
   `yi`, `vi`, odds ratio, …) that drives validation, analysis and agreement.
   **Add standard effect-size fields** inserts an editable preset, and schemes
   can be cloned and imported/exported as JSON. Extracted rows open in a
   scheme-driven edit form (repeatable experiments and metrics, per-metric
   completeness pills, missing-only filter, raw-JSON toggle). Each
   `(coder, scheme)` pair keeps its own extraction, so a second scheme does not
   overwrite the first; extraction runs expose **max chars** and full-text-only
   controls and can be paused/resumed.

Each tab drives its queue: the left bar shows all hits (Screening), the
abstract-included hits (Downloads) or the acquired papers (Extraction). The
Screening/Download/Extract left bars share the same screening **progress bar**,
and Screening and Extraction both offer a **select-all** control. The Extraction
center is the selected study's scheme-driven **edit** form (with a raw-JSON
toggle) for verification and correction. All meta reads and writes use the
app's current coder (the ribbon coder switcher); the Analyze scope defaults to
that coder and can be widened to all coders.

## Reliability

The **Agreement** tab (between Extract and Analyze) computes Gwet's AC1 (and AC2 for ordered
numeric fields) across coders, for both the screening criteria and the
extracted categorical variables. Conflicts are listed per study and field with
one chip per rater's value; settling a conflict writes the chosen value into an
adjudicated `master` row without touching the other coders' data. Extraction
units are keyed by the metric's stable name (falling back to its index), so
reordered contrasts do not create false conflicts.

## Analyze

A fourth **Analyze** tab reports from the extracted effect sizes:

- random-effects (DerSimonian–Laird) pooling with Q, I², τ² and 95% CI
  (selectable fixed-effect or two-stage two-level models with a variance
  decomposition), leave-one-out influence and Egger's regression;
- a **Bayesian** random-effects model with Bayes factors and prior sensitivity;
- subgroup and moderator fits by **any coded variable** (study or metric field,
  e.g. `intervention_type` or `dv_domain`) — with an **interaction builder**
  (`A * B`) — except variables hidden with **Use as moderator** in the scheme
  editor; moderators are picked from collapsible per-group checklists drawn
  from the extraction schema;
- a forest table with an inline plot, plus PRISMA, forest, funnel, spec-curve and
  Bayes-posterior PNG figures;
- publication-bias diagnostics (Egger, PET-PEESE, trim-and-fill, p-curve);
- a specification **multiverse** (estimator × primary-only × domain × outlier
  choices) with a spec table and a spec-curve figure;
- a **variable audit** of the coded extractions (field coverage and
  role-integrity issues such as half-entered effects);
- PRISMA identification/screening/full-text/inclusion counts (including
  duplicate records) with exclusion reasons;
- categorical level summaries with contributing study counts;
- export of an APA-style methods/results report as Markdown, DOCX or
  PowerPoint (the preview renders markdown).

The Analyze left bar explains each section in one line, like the Reports list.

The Analyze tab does **not** select a coding scheme — it pools every scheme's
extractions — and has no coder picker either: analyses combine all codings
into one consensus (unanimous values kept, master-resolved conflicts applied,
units with unresolved conflicts excluded and counted). The
**frequentist/Bayes switch, the estimator** (DerSimonian–Laird,
two-level, fixed) and **Subgroup by** live in the center menubar, and the active
coder scope applies to every analysis. The moderator panel builds a model from
any coded variables and supports **interaction terms** (`A * B`).

Effect sizes are derived from each metric's roles (`yi`/`vi`, `d`/`g`,
descriptives, `t`, `F`, `r`, odds ratio, partial eta², β or χ²); `polarity`
flips `higher_is_worse` outcomes and `eligible_primary` restricts the primary
pool. Everything is computed locally in pure Python/numpy, with the heavy work
run off the request loop so a long analysis leaves the app responsive instead of
timing out.

## Importing a CodingStudio project

The Screen left bar's **Import CodingStudio** action imports a reference
CodingStudio project folder (the layout used by the inoculation-meta coder):
`master_dataset.xlsx` (bibliographic rows + full-text verdicts), `Extraction/*.json`
(multi-experiment records with `DV_Metrics`), `Screening/*.json` (per-coder
abstract verdicts), `Scripts/coding_web/schema.json` (used to build the coding
scheme), and `Papers/*.pdf` (linked to the matching hits). The dialog previews
the folder first, then imports hits, abstract + full-text screening, the scheme,
extractions and PDFs. It is idempotent — re-running skips existing hits and
overwrites the same `(hit, coder, scheme)` rows instead of duplicating. CodingStudio
`DV_Metrics` field names map to QCnext roles through the legacy aliases, so the
imported effects flow straight into the Analyze tab. The importer covers the
current v3.1 specification: it derives field editors and option lists from the
schema's controlled vocabularies, keeps each module field's identity (and its
per-module option levels where a field name repeats across modules), imports the
workbook's C1–C4 base verdicts as an `LLM/base` rater alongside the per-coder
full-text decisions, skips harmonizer/variant `Codings/` files, and makes every
coded field available as a moderator (free-text/identifier fields are excluded).

## Sample project

`samples/meta/meta-sample.qda` is a ready-to-open test project: 10 hits (6
included, 4 excluded for the four criteria), a role-based scheme with one
variable hidden from the moderators, two coders' screening with deliberate
disagreements for the Agreement tab, six coded extractions across three
outcome domains, and a PDF per included study. The same search results in EBSCO
XML, RIS and CSV live in `samples/meta/imports/`. Regenerate everything with:

```
backend/.venv/Scripts/python.exe scripts/make-meta-sample.py
```

## Local-only in v1

The `meta_*` tables deliberately live **outside** the collaboration sync
(`sync_log`) and the undo registry. Meta rows are project-local; if you work on
the same project from multiple devices the meta tables are not replayed between
them. Rows carry an `owner`, and coder rename/delete/reassign keeps the meta
owners in step, so a later milestone can add sync/replay additively.

## LLM automation

Screening, prescreen and extraction use the same AI configuration as the rest
of QCnext (Settings → AI). Screening and extraction jobs appear as background
tasks and can be paused between units of work, cancelled, and resumed from
where they stopped (screening resumes per hit; extraction re-screens papers
that were not yet processed). AI verdicts are stored with `origin=llm` and
remain editable — saving a verdict promotes it to `origin=manual`.