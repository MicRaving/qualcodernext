/**
 * Interchange — export the project in REFI-QDA and import interchange files
 * with automatic format detection (REFI-QDA, RQDA, Taguette, RIS, Survey,
 * plain-text codebooks, zipped .qda projects or Zotero references).
 */
import { useEffect, useRef, useState, type ChangeEvent, type FormEvent } from "react";
import { BookMarked, CircleAlert, CircleCheck, Download, HelpCircle, LoaderCircle, Upload } from "lucide-react";
import { api, ApiError, type InterchangeResult } from "@/lib/api";
import { useToast } from "@/lib/toast";
import { formatImportResult, importLabel } from "@/features/interchange/format";
import { useProjectStore } from "@/stores/project";

const FORMAT_HELP: [string, string][] = [
  ["refi", "REFI-QDA (.qdp / .qdc) — codebook, sources, codings and cases from other REFI-compliant tools."],
  ["rqda", "RQDA (.rqda) — a QualCoder v3 project file with codes, sources, codings and cases."],
  ["taguette", "Taguette (.tag / .json) — codes and coded excerpts from a Taguette export."],
  ["ris", "RIS (.ris) — bibliographic references imported as journal references."],
  ["survey", "Survey (.csv) — spreadsheet columns imported as cases with attributes; qualitative columns become text files per row."],
  ["codebook", "Codebook (.txt/.csv) — plain-text codebook with category>>subcategory>>code lines."],
  ["merge", "Project (.zip) — merge another .qda project (zipped) into the open project."],
  ["zotero", "Zotero — import references from the local Zotero API (localhost:23119, Zotero 7+)."],
];

function errorDetail(e: unknown): string {
  if (e instanceof ApiError && typeof e.detail === "string") return e.detail;
  return e instanceof Error ? e.message : "Import failed";
}

function FormatHelpPopover({ onClose }: { onClose: () => void }) {
  const rootRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const onDown = (e: MouseEvent) => {
      const target = e.target instanceof Node ? e.target : null;
      if (target && !rootRef.current?.contains(target)) onClose();
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("mousedown", onDown);
    window.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      window.removeEventListener("keydown", onKey);
    };
  }, [onClose]);

  return (
    <div
      ref={rootRef}
      className="absolute right-0 top-full z-50 mt-1 w-80 rounded-md border border-border bg-surface p-3 shadow-lg"
      role="dialog"
      aria-label="Import formats"
    >
      <ul className="space-y-1.5">
        {FORMAT_HELP.map(([kind, help]) => (
          <li key={kind} className="text-xs leading-relaxed text-text-secondary">
            <span className="font-medium text-text-primary">{importLabel(kind)}</span>
            {" — "}
            {help}
          </li>
        ))}
      </ul>
    </div>
  );
}

export function InterchangeView({ embedded = false }: { embedded?: boolean }) {
  const toast = useToast();
  const [file, setFile] = useState<File | null>(null);
  const [qualHeaders, setQualHeaders] = useState("");
  const [helpOpen, setHelpOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<InterchangeResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const isCsv = file?.name.toLowerCase().endsWith(".csv") ?? false;

  function handleFileChange(e: ChangeEvent<HTMLInputElement>) {
    setFile(e.target.files?.[0] ?? null);
    setResult(null);
    setError(null);
  }

  async function handleImport(e: FormEvent) {
    e.preventDefault();
    if (busy || !file) return;
    setBusy(true);
    setResult(null);
    setError(null);
    try {
      const res = await api.importAuto(
        file,
        undefined,
        isCsv
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
        if (res.codes !== undefined || res.sources !== undefined || res.cases !== undefined) {
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

  async function handleZotero() {
    if (busy) return;
    setBusy(true);
    setResult(null);
    setError(null);
    try {
      const res = await api.importZotero();
      setResult(res);
      if (!res.ok) {
        const detail = res.message ?? "Import failed";
        setError(detail);
        toast.error(detail);
      } else {
        toast.success(res.message ?? formatImportResult(res));
        void useProjectStore.getState().refreshProject();
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
            <div className="relative flex items-center gap-1">
              <h2 className="text-sm font-semibold text-text-primary">Import</h2>
              <button
                type="button"
                onClick={() => setHelpOpen((o) => !o)}
                aria-expanded={helpOpen}
                aria-label="What each format provides"
                title="What each format provides"
                className="ml-1 rounded-sm p-0.5 text-text-secondary hover:bg-surface-higher hover:text-text-primary"
              >
                <HelpCircle size={14} aria-hidden />
              </button>
              {helpOpen && <FormatHelpPopover onClose={() => setHelpOpen(false)} />}
            </div>
            <form onSubmit={(e) => void handleImport(e)} className="mt-3 space-y-3">
              <label className="block">
                <span className="mb-1 block text-xs text-text-secondary">
                  File (format is detected automatically)
                </span>
                <input
                  type="file"
                  onChange={handleFileChange}
                  className="block w-full text-xs text-text-secondary file:mr-2 file:rounded-sm file:border-0 file:bg-surface-higher file:px-2 file:py-1 file:text-xs file:font-medium file:text-text-primary hover:file:bg-accent-hover hover:file:text-bg"
                  aria-label="Import file"
                />
              </label>
              {isCsv && (
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
              <div className="flex items-center gap-2">
                <button
                  type="submit"
                  disabled={busy || !file}
                  className="flex items-center gap-1.5 rounded-sm bg-accent px-2.5 py-1 text-xs font-medium text-bg hover:bg-accent-hover disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {busy ? (
                    <LoaderCircle size={14} className="animate-spin" aria-hidden />
                  ) : (
                    <Upload size={14} aria-hidden />
                  )}
                  {busy ? "Importing…" : "Import"}
                </button>
                <button
                  type="button"
                  onClick={() => void handleZotero()}
                  disabled={busy}
                  className="flex items-center gap-1.5 rounded-sm border border-border bg-bg px-2.5 py-1 text-xs text-text-secondary hover:bg-surface-higher disabled:cursor-not-allowed disabled:opacity-50"
                >
                  <BookMarked size={14} aria-hidden />
                  Import from Zotero
                </button>
              </div>
            </form>
          </section>
        </div>
      </div>
    </div>
  );
}
