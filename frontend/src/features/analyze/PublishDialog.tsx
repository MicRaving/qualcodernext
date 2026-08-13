/**
 * Smart Publisher — export the current report as a Word / Excel / PowerPoint
 * document through POST /publish/from-report (backend renders the bytes).
 *
 * Downloads match the codebase Blob + a[download] mechanism (lib/csv.ts
 * downloadCsv, chartPng.downloadChartPng): the backend bytes arrive as a
 * blob and a temporary <a download> click saves them under the chosen name.
 */
import { useState, type FormEvent } from "react";
import { Share2 } from "lucide-react";
import { Button, Field, Input, Modal, Select } from "@/components/ui/orchestrator";
import { ApiError, fetchWithTimeout, initApiBase } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import type { ReportId } from "@/stores/project";
import { useProjectStore } from "@/stores/project";

export type PublishFormat = "docx" | "pptx" | "xlsx";

/** Frontend report id → backend /publish report name. Reports absent from
 *  this map have no publisher yet and the dialog disables every format. */
const PUBLISHABLE: Partial<Record<ReportId, string>> = {
  "code-frequencies": "code-frequencies",
  "code-segments": "code-segments",
  "summary-table": "summary-table",
  codebook: "codebook",
};

/** Backend report names that render as a slide deck (per-code slides). */
const PPTX_REPORTS = new Set(["code-segments", "code-frequencies"]);

const EXTENSIONS: Record<PublishFormat, string> = { docx: "docx", pptx: "pptx", xlsx: "xlsx" };

/** `<report>-<date>` default file name, e.g. code-frequencies-2026-08-13. */
function defaultFileName(reportName: string | undefined): string {
  const date = new Date().toISOString().slice(0, 10);
  return `${reportName ?? "report"}-${date}`;
}

/** Replace any existing document extension, else append the new one. */
function withExtension(name: string, format: PublishFormat): string {
  return name.trim().replace(/\.(docx|pptx|xlsx)$/i, `.${EXTENSIONS[format]}`) || `${name}.${EXTENSIONS[format]}`;
}

/** Same local-fetch pattern as statsApi.ts: initApiBase + fetchWithTimeout,
 *  single retry on network-level failure (packaged backend restart). */
async function publishBlob(report: string, format: PublishFormat): Promise<Blob> {
  const doFetch = async (): Promise<Blob> => {
    const base = await initApiBase();
    const res = await fetchWithTimeout(
      `${base}/publish/from-report`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ report, format }),
      },
      60_000,
    );
    if (!res.ok) {
      let detail: unknown;
      try {
        detail = (await res.json()).detail;
      } catch {
        /* non-JSON error body */
      }
      const suffix = typeof detail === "string" && detail ? `: ${detail}` : "";
      throw new ApiError(res.status, `API error ${res.status} on /publish/from-report${suffix}`, detail);
    }
    return res.blob();
  };
  try {
    return await doFetch();
  } catch (err) {
    if (err instanceof ApiError) throw err;
    return doFetch();
  }
}

function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export function PublishDialog({ onClose }: { onClose: () => void }) {
  const { t } = useI18n();
  const selectedId = useProjectStore((s) => s.analyzeUi.selectedId);
  const reportName = selectedId ? PUBLISHABLE[selectedId] : undefined;
  const supported = reportName != null;
  const pptxSupported = reportName != null && PPTX_REPORTS.has(reportName);

  const [format, setFormat] = useState<PublishFormat>(pptxSupported ? "pptx" : "docx");
  const [fileName, setFileName] = useState(defaultFileName(reportName));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!reportName || busy) return;
    setError(null);
    setBusy(true);
    try {
      const blob = await publishBlob(reportName, format);
      downloadBlob(blob, withExtension(fileName, format));
      onClose();
    } catch (err) {
      setError(t("analyze.publishError", { message: err instanceof Error ? err.message : String(err) }));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      open
      onClose={busy ? undefined : onClose}
      closeDisabled={busy}
      size="sm"
      ariaLabel={t("analyze.publishTitle")}
    >
      <form onSubmit={(e) => void submit(e)}>
        <div className="border-b border-border px-4 py-2.5">
          <h2 className="text-sm font-semibold text-text-primary">{t("analyze.publishTitle")}</h2>
        </div>
        <div className="space-y-3 p-4">
          {!supported && (
            <p className="text-xs text-text-secondary">{t("analyze.publishNotSupported")}</p>
          )}
          <Field label={t("analyze.publishFormat")}>
            <Select
              value={format}
              onChange={(e) => setFormat(e.target.value as PublishFormat)}
              disabled={!supported}
            >
              <option value="docx">{t("analyze.publishFormatWord")}</option>
              <option value="xlsx">{t("analyze.publishFormatExcel")}</option>
              <option value="pptx" disabled={!pptxSupported}>
                {t("analyze.publishFormatPowerPoint")}
              </option>
            </Select>
          </Field>
          {!pptxSupported && (
            <p className="text-xs text-text-secondary">{t("analyze.publishHintPptx")}</p>
          )}
          <Field label={t("analyze.publishFileName")}>
            <Input
              value={fileName}
              onChange={(e) => setFileName(e.target.value)}
              disabled={!supported || busy}
              spellCheck={false}
            />
          </Field>
          {error && (
            <p className="text-xs text-danger" role="alert">
              {error}
            </p>
          )}
          <div className="flex justify-end gap-2 pt-1">
            <Button variant="secondary" onClick={onClose} disabled={busy}>
              {t("common.cancel")}
            </Button>
            <Button variant="primary" type="submit" disabled={busy || !supported || !fileName.trim()}>
              {busy ? t("analyze.publishing") : t("analyze.publishButton")}
            </Button>
          </div>
        </div>
      </form>
    </Modal>
  );
}

/** Toolbar button that owns the dialog's open state (AnalyzeView actions). */
export function PublishButton() {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button
        variant="secondary"
        className="h-6 px-2 py-0 text-text-secondary hover:text-text-primary"
        onClick={() => setOpen(true)}
        icon={<Share2 size={12} aria-hidden />}
        title={t("analyze.publish")}
      >
        {t("analyze.publish")}
      </Button>
      {open && <PublishDialog onClose={() => setOpen(false)} />}
    </>
  );
}
