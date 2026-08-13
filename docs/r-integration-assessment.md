# R Integration — Feasibility Assessment (2026-08)

**Status: HIGHLY feasible.** R can already read QCnext projects today (SQLite), and a
script-bridge adds execution + results. Recommended route: **Rscript subprocess bridge +
CSV/SQLite/HTTP data exchange**. rpy2 in the packaged app: not recommended.

## 1. Current QCnext state (grounding facts)

- Backend: FastAPI + SQLAlchemy (async, SQLite) on `127.0.0.1`; dev default port **8765**,
  packaged app picks an ephemeral port and writes it to
  `%TEMP%\qualcoder-port-<pid>.json` (`{"port", "pid"}`) — the Tauri shell discovers it
  via the `backend_port` command.
- Project = a folder with `data.qda` (SQLite) — tables: `source`, `code_name`, `code_cat`,
  `code_text`, `code_image`, `code_av`, `annotation`, `cases`, `case_text`, `attribute`,
  `attribute_type`, `journal`, `audit_log`, `sync_log`, … plus `*_visible` SQL views
  (coder-visibility aware).
- **Read-only SQL console**: `POST /sql/run` (SELECT/WITH/EXPLAIN/PRAGMA/VALUES only,
  single statement, 5000-row cap) — exists today, ideal for R-over-HTTP.
- Report endpoints return tabular data; CSV export everywhere (`downloadCsv`,
  `ReportCsvButton`); charts as PNG (`chartPng.ts`).
- Packaging constraint: PyInstaller onedir (`compile.ps1`) — new deps must be pure-Python
  or wheel-verified; the build already carries heavy libs (whisper, pandas, …).
- Background-jobs pattern exists (transcription/autocode queue) — reusable for R runs.

## 2. Integration routes — feasibility

| Route | Feasibility | Notes |
|---|---|---|
| **A. Rscript subprocess bridge** (QCnext spawns `Rscript`, exchanges files) | ✅ **Recommended** | R installed externally; version-tolerant; zero new Python deps; async job fits the existing queue |
| **B. Direct SQLite read from R** (`RSQLite`) | ✅ Works TODAY | R opens `data.qda` read-only; can query any table/view incl. `*_visible`; no QCnext code needed |
| **C. HTTP exchange from R** (`httr`/`jsonlite` → `/sql/run`, `/reports/*`) | ✅ Feasible | Uses the existing read-only SQL console + report endpoints; needs port discovery (env var) |
| **D. rpy2 in-process** | ⚠️ Dev-only | Embedding R into Python breaks PyInstaller packaging (needs R_HOME at runtime, +500 MB, version-fragile). Optional dev extra, not for the shipped build |
| **E. Rserve daemon** | ❌ Overkill | Adds a service to install/manage; only useful for always-on R sessions |

## 3. Exact methods of exchanging data

### Method 1 — CSV files (out: QCnext → R)
- QCnext exports report data (code frequencies, crosstab, code-by-variable, codings-by-segments,
  summary table, word frequencies) as CSV — mostly existing endpoints; the bridge writes them
  into an exchange dir `<project>/r_exchange/in/*.csv` before launching Rscript.
- R reads with `read.csv(..., fileEncoding="UTF-8")`.

### Method 2 — SQLite read-only (R → project; works without any bridge)
- `RSQLite::dbConnect(RSQLite::SQLite(), "data.qda")` — read-only connection is safe
  alongside the running backend (SQLite allows concurrent readers; QCnext never locks
  exclusively except during schema migration).
- The `*_visible` views honor coder visibility, matching what the UI shows.
- Example (code × document matrix in 4 lines):
  ```r
  library(RSQLite); library(dplyr)
  con <- dbConnect(SQLite(), "data.qda", flags = SQLITE_RO)
  m <- tbl(con, "code_text_visible") %>% count(cid, fid) %>% collect() %>% tidyr::pivot_wider(names_from=fid, values_from=n, values_fill=0)
  ```
- Caveat: R must be **read-only** — writes would corrupt the project; the bridge only
  grants the file path, never write advice.

### Method 3 — HTTP from R (the elegant route)
- QCnext launches Rscript with `QC_PORT=<port>` (and `QC_PROJECT=<path>`) in the
  environment; R discovers the port and calls the API:
  ```r
  base <- sprintf("http://127.0.0.1:%s/api/v1", Sys.getenv("QC_PORT", "8765"))
  res <- httr::POST(paste0(base, "/sql/run"), body = list(query = "SELECT cid, name FROM code_name"),
                    encode = "json")
  df <- jsonlite::fromJSON(httr::content(res, "text"))
  ```
- `POST /sql/run` gives R the **whole project schema** (any SELECT) with the same
  read-only guardrails as the UI; report endpoints give pre-shaped tables.
- Port fallback: the port file (`%TEMP%\qualcoder-port-*.json`) for scripts run outside
  the bridge.

### Method 4 — Results back into QCnext (R → QCnext)
- **Plots:** R writes `*.png` into `<project>/r_exchange/out/`; the bridge returns the
  file list and the "R console" view renders them (existing PNG handling).
- **Tables:** R writes `*.csv`; QCnext displays them in the results pane (and the user can
  persist via the existing importers — e.g. results reshaped as survey/codebook CSV).
- **Write-back into the project** (R creating codings/cases): v1 keeps R **read-only**.
  If needed later, the safe path is R → CSV → QCnext's existing importers, or an explicit
  REST write contract (out of scope v1).

## 4. Tooling

**R side (user-installed; the bridge only detects it):**
- Base **R ≥ 4.2** (`Rscript` on PATH, `R_HOME`, or well-known install dirs:
  `C:\Program Files\R\R-*\bin\Rscript.exe` on Windows, `/usr/bin/Rscript` on Linux,
  `/Library/Frameworks/R.framework/Resources/bin/Rscript` on macOS).
- Packages (installable via `install.packages`): `RSQLite`, `jsonlite`, `httr`, `dplyr`,
  `tidyr`, `ggplot2`, `janitor`, `irr` (inter-rater — a strong complement to the built-in
  Kappa/Alpha), `quanteda` (text analysis), `renv` (per-project reproducibility).
- **QCnext side:** zero new Python dependencies; PyInstaller spec untouched; the bridge
  uses `subprocess`/`asyncio.create_subprocess_exec` (already used for whisper jobs).

## 5. Scope proposal

**Phase 1 — R bridge (3–5 person-days)**
- R detection + status (version, PATH/R_HOME/install-dir probing) in a new Settings section.
- "R console" view in Analyze (left-bar entry): script editor (plain textarea v1), Run
  button → background job (reuses the task queue), stdout/stderr/warnings captured into a
  log pane, exit code surfaced; PNG outputs from `r_exchange/out/` rendered below.
- Script templates: "code × document matrix", "coded segments to data.frame",
  "interrater (irr package)", "word frequencies (quanteda)" — each with the
  port/project env-var boilerplate.
- Env contract: `QC_PORT`, `QC_PROJECT`, `QC_EXCHANGE` (exchange dir path).

**Phase 2 — parameterized workflows (4–6 person-days)**
- "Send report to R": the current report's data written to `r_exchange/in/` + a template
  script stub (reproducible per report).
- Saved R scripts per project (new `r_script` table, like `stored_sql`), syntax
  highlighting optional (simple editor first).
- Output artifact browser (csv/png) + "open folder" action.

**Out of scope:** bundling R, rpy2 in the packaged build, RStudio integration, remote
R servers, R writing into the project DB.

## 6. Risks & constraints

- **R must be installed** — the bridge detects and clearly explains; Settings shows status.
- **Arbitrary code execution**: R scripts are local code, same trust model as the SQL
  console — keep it local-only, add a "runs code on your machine" hint on Run.
- **Encoding**: Windows R defaults to the system codepage — launch with
  `--encoding=UTF-8` and document `fileEncoding="UTF-8"` in templates.
- **SQL console 5000-row cap** applies to the HTTP route; the direct-SQLite route has no
  cap (R reads the DB itself) — note it in the docs.
- **Concurrency**: R jobs serialize through the existing background-job queue (no parallel
  runs), same as transcription.
- **SQLite locking**: read-only R connections are safe; the bridge never grants write
  intent.

## 7. Verdict

Build **Phase 1** (bridge + console + templates): low risk, high researcher value
(quanteda, ggplot2, irr, mixed-models analyses QCnext's pure-Python stats suite can't
cover). The direct-SQLite and HTTP routes mean even a "no bridge" workflow works today
for CLI-savvy users — the bridge just makes it first-class.
