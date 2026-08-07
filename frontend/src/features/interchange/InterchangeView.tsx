/**
 * Interchange — export the project in REFI-QDA and import REFI-QDA,
 * RQDA, Taguette, RIS, Survey, plain-text codebooks, other .qda projects
 * (merge) or Zotero references.
 */
import { useState, type ChangeEvent, type FormEvent } from "react";
import { CircleAlert, CircleCheck, Download, LoaderCircle, Upload } from "lucide-react";
import { api, ApiError, type InterchangeResult } from "@/lib/api";
import { useToast } from "@/lib/toast";
import { formatImportResult, importLabel } from "@/features/interchange/format";
import { useProjectStore } from "@/stores/project";

type ImportFormat = "refi" | "rqda" | "taguette" | "ris" | "survey" | "codebook" | "merge" | "zotero";

const IMPORT_FORMATS: ImportFormat[] = [
  "refi",
  "rqda",
  "taguette",
  "ris",
  "survey",
  "codebook",
  "merge",
  "zotero",
];

const IMPORT_IMPORTERS: Record<
  ImportFormat,
  ((file: File, extra?: string[] | undefined) => Promise<InterchangeResult>) | "zotero"
> = {
  refi: (file) => api.importRefi(file),
  rqda: (file) => api.importRqda(file),
  taguette: (file) => api.importTaguette(file),
  ris: (file) => api.importRis(file),
  survey: (file, extra) => api.importSurvey(file, undefined, extra),
  codebook: (file) => api.importCodebook(file),
  merge: (file) => api.importMerge(file),
  zotero: "zotero",
};

/** Formats that (re)create project content — refresh the store afterwards. */
const REFRESH_FORMATS: ImportFormat[] = ["rqda", "taguette", "survey", "codebook", "merge"];

const FORMAT_HELP: Record<ImportFormat, string> = {
  refi: "REFI-QDA (.qdp / .qdc) — codebook, sources, codings and cases from other REFI-compliant tools.",
  rqda: "RQDA (.rqda) — a QualCoder v3 project file with codes, sources, codings and cases.",
  taguette: "Taguette (.tag / .json) — codes and coded excerpts from a Taguette export.",
  ris: "RIS (.ris) — bibliographic references imported as journal references.",
  survey:
    "Survey (.csv) — spreadsheet columns imported as cases with attributes; qualitative columns become text files per row.",
  codebook: "Codebook (.txt/.csv) — plain-text codebook with category>>subcategory>>code lines.",
  merge: "Project (.zip) — merge another .qda project (zipped) into the open project.",
  zotero: "Zotero — import references from the local Zotero API (localhost:23119, Zotero 7+).",
};

function errorDetail(e: unknown): string {
  if (e instanceof ApiError && typeof e.detail === "string") return e.detail;
  return e instanceof Error ? e.message : "Import failed";
}

export function InterchangeView({ embedded = false }: { embedded?: boolean }) {
  const toast = useToast();
  const [format, setFormat] = useState<ImportFormat>("refi");
  const [file, setFile] = useState<File | null>(null);
  const [qualHeaders, setQualHeaders] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<InterchangeResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  function handleFileChange(e: ChangeEvent<HTMLInputElement>) {
    setFile(e.target.files?.[0] ?? null);
    setResult(null);
    setError(null);
  }

  async function handleImport(e: FormEvent) {
    e.preventDefault();
    if (busy) return;
    if (format !== "zotero" && !file) return;
    setBusy(true);
    setResult(null);
    setError(null);
    try {
      const importer = IMPORT_IMPORTERS[format];
      const res =
        importer === "zotero"
          ? await api.importZotero()
          : await importer(
              file as File,
              format === "survey"
                ? qualHeaders
                    .split(",")
                    .map((h) => h.trim())
                    .filter(Boolean)
                : undefined,
            );
      setResult(res);
      if (!res.ok) {
        const detail = res.message ?? "Import failed";
        setError(detail);
        toast.error(detail);
      } else {
        const summary = res.message
          ? `${res.message} — ${formatImportResult(res)}`
          : formatImportResult(res);
        toast.success(summary);
        if (REFRESH_FORMATS.includes(format)) {
          void useProjectStore.getState().refreshProject();
        }
      }
    } catch (err) {
      const detail = errorDetail(err);
      setError(detail);
      toast.error(detail);
    } finally {
      setBusy(false);
    }
  }

  const cardCls = "rounded-lg border border-border bg-surface p-4";
  const inputCls =
    "h-8 rounded-sm border border-border bg-bg px-2 text-sm outline-none focus:border-accent";

  return (
    <div className={embedded ? "flex flex-col" : "flex h-full flex-col bg-bg"}>
      {!embedded && (
        <header className="flex h-10 shrink-0 items-center gap-2 border-b border-border bg-surface px-3">
          <h1 className="text-sm font-semibold text-text-primary">Import / Export</h1>
        </header>
      )}

      {/* Inline notices */}
      {result && result.ok && (
        <div
          role="status"
          className="flex shrink-0 items-center gap-2 border-b border-border bg-surface px-3 py-1.5 text-sm text-success"
        >
          <CircleCheck size={14} aria-hidden />
          <span className="min-w-0 flex-1">
            {result.message ? `${result.message} — ` : ""}
            {formatImportResult(result)}
          </span>
        </div>
      )}
      {error && (
        <div className="flex shrink-0 items-center gap-2 border-b border-border bg-surface px-3 py-1.5 text-sm text-danger">
          <CircleAlert size={14} aria-hidden />
          <span className="min-w-0 flex-1 truncate">{error}</span>
        </div>
      )}

      <div className={embedded ? "p-0" : "min-h-0 flex-1 overflow-y-auto p-4"}>
        <div className="grid max-w-3xl grid-cols-1 gap-4 lg:grid-cols-2">
          {/* Export */}
          <section className={cardCls}>
            <h2 className="text-sm font-semibold text-text-primary">Export</h2>
            <p className="mt-1 text-xs leading-relaxed text-text-secondary">
              Exports the codebook, text sources, coded segments and cases in the REFI-QDA
              interchange format.
            </p>
            <a
              href={api.interchange.exportRefiUrl()}
              download
              className="mt-3 inline-flex items-center gap-1.5 rounded-sm bg-accent px-2.5 py-1 text-xs font-medium text-bg hover:bg-accent-hover"
            >
              <Download size={14} aria-hidden />
              Export project (.qdp)
            </a>
          </section>

          {/* Import */}
          <section className={cardCls}>
            <h2 className="text-sm font-semibold text-text-primary">Import</h2>
            <form onSubmit={(e) => void handleImport(e)} className="mt-3 space-y-3">
              <label className="block">
                <span className="mb-1 block text-xs text-text-secondary">Format</span>
                <select
                  value={format}
                  onChange={(e) => setFormat(e.target.value as ImportFormat)}
                  className={inputCls}
                >
                  {IMPORT_FORMATS.map((f) => (
                    <option key={f} value={f}>
                      {importLabel(f)}
                    </option>
                  ))}
                </select>
              </label>
              {format === "survey" && (
                <label className="block">
                  <span className="mb-1 block text-xs text-text-secondary">
                    Qualitative columns (comma-separated)
                  </span>
                  <input
                    value={qualHeaders}
                    onChange={(e) => setQualHeaders(e.target.value)}
                    placeholder="e.g. answer, comment"
                    className={inputCls}
                  />
                </label>
              )}
              {format !== "zotero" && (
                <label className="block">
                  <span className="mb-1 block text-xs text-text-secondary">File</span>
                  <input
                    type="file"
                    onChange={handleFileChange}
                    className="block w-full text-xs text-text-secondary file:mr-2 file:rounded-sm file:border-0 file:bg-surface-higher file:px-2 file:py-1 file:text-xs file:font-medium file:text-text-primary hover:file:bg-accent-hover hover:file:text-bg"
                    aria-label="Import file"
                  />
                </label>
              )}
              <button
                type="submit"
                disabled={busy || (format !== "zotero" && !file)}
                className="flex items-center gap-1.5 rounded-sm bg-accent px-2.5 py-1 text-xs font-medium text-bg hover:bg-accent-hover disabled:cursor-not-allowed disabled:opacity-50"
              >
                {busy ? (
                  <LoaderCircle size={14} className="animate-spin" aria-hidden />
                ) : (
                  <Upload size={14} aria-hidden />
                )}
                {busy ? "Importing…" : format === "zotero" ? "Import from Zotero" : "Import"}
              </button>
            </form>
          </section>
        </div>

        {/* Help */}
        <section className="mt-4 max-w-3xl rounded-lg border border-border bg-surface p-4">
          <h2 className="text-sm font-semibold text-text-primary">What each format provides</h2>
          <ul className="mt-2 space-y-1.5">
            {IMPORT_FORMATS.map((f) => (
              <li key={f} className="text-xs leading-relaxed text-text-secondary">
                <span className="font-medium text-text-primary">{importLabel(f)}</span>
                {" — "}
                {FORMAT_HELP[f]}
              </li>
            ))}
          </ul>
        </section>
      </div>
    </div>
  );
}
