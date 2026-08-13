/**
 * Interchange — export the project in REFI-QDA and import interchange files
 * with automatic format detection (REFI-QDA, RQDA, Taguette, RIS, Survey,
 * plain-text codebooks, zipped .qda projects or Zotero references).
 *
 * Picking a file shows an import menu (name + detected format + Import);
 * the embedded Settings variant is chrome-free (no cards, explanations live
 * behind ? icons).
 */
import { useRef, useState, type ChangeEvent, type ReactNode } from "react";
import { CircleAlert, CircleCheck, Download, HelpCircle, LoaderCircle } from "lucide-react";
import { api, ApiError, type InterchangeResult } from "@/lib/api";
import { Button, HelpFlyout, IconButton, ViewHeader } from "@/components/ui/orchestrator";
import { cls } from "@/components/ui/tokens";
import { importLabel } from "@/features/interchange/format";
import { useI18n } from "@/lib/i18n";
import { useProjectStore } from "@/stores/project";

const FORMAT_HELP: [string, string][] = [
  ["refi", "REFI-QDA (.qdp / .qdc) — codebook, sources, codings and cases from other REFI-compliant tools."],
  ["rqda", "RQDA (.rqda) — a QualCoder v3 project file with codes, sources, codings and cases."],
  ["taguette", "Taguette (.tag / .json) — codes and coded excerpts from a Taguette export."],
  ["ris", "RIS (.ris) — bibliographic references imported as journal references."],
  ["survey", "Survey (.csv) — spreadsheet columns imported as cases with attributes; qualitative columns become text files per row."],
  ["xlsx", "Excel (.xlsx) — multi-column sheets imported like a survey CSV; other sheets become one text file per sheet."],
  ["sav", "SPSS (.sav) — variable columns imported as case attributes; qualitative string variables become text files per row."],
  ["codebook", "Codebook (.txt/.csv) — plain-text codebook with category>>subcategory>>code lines."],
  ["merge", "Project (.zip) — merge another .qda project (zipped) into the open project."],
  ["zotero", "Zotero — import references from the local Zotero API (localhost:23119, Zotero 7+)."],
];

function errorDetail(e: unknown): string {
  if (e instanceof ApiError && typeof e.detail === "string") return e.detail;
  return e instanceof Error ? e.message : "Import failed";
}

/** Best-guess format key for a chosen file name (for the import menu). */
function detectFormat(name: string): string {
  const ext = name.split(".").pop()?.toLowerCase() ?? "";
  if (ext === "qdp" || ext === "qdc") return "refi";
  if (ext === "rqda") return "rqda";
  if (ext === "tag" || ext === "json") return "taguette";
  if (ext === "ris") return "ris";
  if (ext === "csv") return "survey";
  if (ext === "xlsx" || ext === "xls") return "xlsx";
  if (ext === "sav") return "sav";
  if (ext === "zip") return "merge";
  if (ext === "txt") return "codebook";
  return "refi";
}

function FormatHelpList() {
  return (
    <ul className="space-y-1.5">
      {FORMAT_HELP.map(([key, help]) => (
        <li key={key} className="text-xs leading-relaxed text-text-secondary">
          {importLabel(key)}
          {" — "}
          {help}
        </li>
      ))}
    </ul>
  );
}

/** The counts the backend reports after an import, as [label, value] pairs. */
function resultCounts(res: InterchangeResult): [string, number][] {
  const out: [string, number][] = [];
  if (res.codes !== undefined) out.push(["Codes", res.codes]);
  if (res.categories !== undefined) out.push(["Categories", res.categories]);
  if (res.sources !== undefined) out.push(["Files", res.sources]);
  if (res.codings !== undefined) out.push(["Codings", res.codings]);
  if (res.cases !== undefined) out.push(["Cases", res.cases]);
  if (res.references !== undefined) out.push(["References", res.references]);
  if (res.attributes !== undefined) out.push(["Attributes", res.attributes]);
  return out;
}

export function InterchangeView({ embedded = false }: { embedded?: boolean }) {
  const { t } = useI18n();
  const [helpOpen, setHelpOpen] = useState<null | "export" | "import">(null);
  const [helpAnchor, setHelpAnchor] = useState<HTMLElement | null>(null);
  const [busy, setBusy] = useState(false);
  const [pending, setPending] = useState<File | null>(null);
  const [result, setResult] = useState<InterchangeResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  function toggleHelp(kind: "export" | "import", anchor: HTMLElement) {
    setHelpAnchor(anchor);
    setHelpOpen((cur) => (cur === kind ? null : kind));
  }

  /** Picking a file shows the import menu (name + format + Import/Cancel). */
  function handleFileChange(e: ChangeEvent<HTMLInputElement>) {
    const picked = e.target.files?.[0] ?? null;
    e.target.value = "";
    if (!picked || busy) return;
    setPending(picked);
    setResult(null);
    setError(null);
  }

  async function runImport() {
    if (!pending || busy) return;
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const res = await api.importAuto(pending);
      setResult(res);
      setPending(null);
      if (!res.ok) {
        setError(res.message ?? "Import failed");
      } else if (res.codes !== undefined || res.sources !== undefined || res.cases !== undefined) {
        void useProjectStore.getState().refreshProject();
      }
    } catch (err) {
      setError(errorDetail(err));
      setPending(null);
    } finally {
      setBusy(false);
    }
  }

  const pendingCard: ReactNode =
    pending && !busy ? (
      <div className="mt-2 rounded-sm border border-border bg-bg p-2">
        <p className="flex items-center gap-1.5 text-xs font-medium text-text-primary">
          <Download size={11} className="rotate-180 text-text-secondary" aria-hidden />
          <span className="min-w-0 flex-1 truncate">{pending.name}</span>
        </p>
        <p className="mt-0.5 text-[10px] text-text-secondary">
          {importLabel(detectFormat(pending.name))}
        </p>
        <div className="mt-2 flex items-center justify-end gap-2">
          <Button variant="secondary" onClick={() => setPending(null)}>
            {t("common.cancel")}
          </Button>
          <Button
            variant="primary"
            icon={<Download size={12} className="rotate-180" aria-hidden />}
            onClick={() => void runImport()}
          >
            {t("interchange.import")}
          </Button>
        </div>
      </div>
    ) : null;

  const statusCard: ReactNode =
    busy || (result && result.ok) || error ? (
      <div className="mt-2">
        {busy ? (
          <p className="flex items-center gap-1.5 text-xs text-text-secondary" role="status">
            <LoaderCircle size={12} className="animate-spin" aria-hidden />
            {t("interchange.importing")}
          </p>
        ) : result && result.ok ? (
          <div className="rounded-sm border border-border bg-bg p-2">
            <p className="flex items-center gap-1.5 text-xs font-medium text-success">
              <CircleCheck size={12} aria-hidden />
              {t("interchange.importComplete")}
            </p>
            <ul className="mt-1 grid grid-cols-2 gap-x-3 gap-y-0.5 text-xs text-text-secondary">
              {resultCounts(result).map(([label, value]) => (
                <li key={label}>
                  {value} {label}
                </li>
              ))}
            </ul>
            {result.message && <p className="mt-1 text-xs text-text-secondary">{result.message}</p>}
          </div>
        ) : error ? (
          <p className="flex items-start gap-1.5 text-xs text-danger">
            <CircleAlert size={12} className="mt-0.5 shrink-0" aria-hidden />
            <span>{error}</span>
          </p>
        ) : null}
      </div>
    ) : null;

  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const filePicker: ReactNode = (
    <>
      <input
        ref={fileInputRef}
        type="file"
        onChange={handleFileChange}
        disabled={busy}
        className="hidden"
        aria-label={t("interchange.importFileAria")}
        data-testid="import-file-input"
      />
      <Button
        variant="primary"
        className="mt-2"
        icon={<Download size={14} className="rotate-180" aria-hidden />}
        onClick={() => fileInputRef.current?.click()}
        disabled={busy}
      >
        {t("interchange.import")}
      </Button>
    </>
  );

  return (
    <div className={embedded ? "flex flex-col" : "flex h-full flex-col bg-bg"}>
      {!embedded && <ViewHeader back={false} title={t("interchange.title")} />}

      <div className={embedded ? "p-0" : "min-h-0 flex-1 overflow-y-auto p-4"}>
        <div className="grid max-w-3xl grid-cols-1 gap-4 lg:grid-cols-2">
          {/* Export */}
          <div className={embedded ? undefined : undefined}>
            <div className="flex items-center gap-1.5">
              <h2 className="text-sm font-semibold text-text-primary">{t("interchange.exportSection")}</h2>
              <IconButton
                label={t("interchange.exportHelp")}
                title={t("interchange.exportHelp")}
                size="sm"
                aria-expanded={helpOpen === "export"}
                onClick={(e) => toggleHelp("export", e.currentTarget)}
              >
                <HelpCircle size={12} aria-hidden />
              </IconButton>
            </div>
            {helpOpen === "export" && helpAnchor && (
              <HelpFlyout anchor={helpAnchor} onClose={() => setHelpOpen(null)}>
                <p className="text-xs leading-relaxed text-text-secondary">{t("interchange.exportHelp")}</p>
              </HelpFlyout>
            )}
            <a
              href={api.interchange.exportRefiUrl()}
              download
              className={`mt-2 inline-flex items-center gap-1.5 ${cls.primary}`}
            >
              <Download size={14} aria-hidden />
              {t("interchange.exportButton")}
            </a>
          </div>

          {/* Import */}
          <div>
            <div className="relative flex items-center gap-1">
              <h2 className="text-sm font-semibold text-text-primary">{t("interchange.importSection")}</h2>
              <IconButton
                label={t("interchange.helpTitle")}
                title={t("interchange.helpTitle")}
                size="sm"
                className="ml-1"
                onClick={(e) => toggleHelp("import", e.currentTarget)}
                aria-expanded={helpOpen === "import"}
              >
                <HelpCircle size={14} aria-hidden />
              </IconButton>
              {helpOpen === "import" && helpAnchor && (
                <HelpFlyout anchor={helpAnchor} onClose={() => setHelpOpen(null)}>
                  <FormatHelpList />
                </HelpFlyout>
              )}
            </div>
            {filePicker}
            {pendingCard}
            {statusCard}
          </div>
        </div>
      </div>
    </div>
  );
}
