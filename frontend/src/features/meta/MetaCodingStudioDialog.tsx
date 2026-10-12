/**
 * CodingStudio folder importer for meta analysis.
 *
 * Point at a CodingStudio project folder, preview what it holds (papers,
 * texts, extraction workbooks, screenings per coder), then import the hits,
 * screening rows, extractions and PDF links into the active meta project. Big
 * folders can take minutes, so the dialog locks while the import runs.
 */
import { useState } from "react";
import { FolderOpen, LoaderCircle, Upload } from "lucide-react";
import { api } from "@/lib/api";
import type { MetaCodingStudioImportResult, MetaCodingStudioPreview } from "@/lib/api/types";
import { Button, Input, Modal, TableHead } from "@/components/ui/orchestrator";
import { useI18n } from "@/lib/i18n";
import { useToast } from "@/lib/toast";
import { errorMessage } from "@/lib/utils";

const TD = "border-b border-border px-3 py-1.5 text-sm align-top";
const CHECKBOX =
  "h-3.5 w-3.5 shrink-0 cursor-pointer rounded-sm border border-border accent-[var(--qc-accent)]";

/** One optional import step; all default to on. */
function Flag({
  label,
  checked,
  onChange,
  disabled,
}: {
  label: string;
  checked: boolean;
  onChange: (value: boolean) => void;
  disabled: boolean;
}) {
  return (
    <label className="flex items-center gap-1.5 text-xs text-text-primary">
      <input
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
        className={CHECKBOX}
        aria-label={label}
      />
      {label}
    </label>
  );
}

export function MetaCodingStudioDialog({
  open,
  onClose,
  onImported,
}: {
  open: boolean;
  onClose: () => void;
  onImported: () => void;
}) {
  const { t } = useI18n();
  const toast = useToast();
  const [folder, setFolder] = useState("");
  const [preview, setPreview] = useState<MetaCodingStudioPreview | null>(null);
  const [result, setResult] = useState<MetaCodingStudioImportResult | null>(null);
  const [owner, setOwner] = useState("");
  const [runId, setRunId] = useState("");
  const [importHits, setImportHits] = useState(true);
  const [importScreening, setImportScreening] = useState(true);
  const [importExtractions, setImportExtractions] = useState(true);
  const [linkPdfs, setLinkPdfs] = useState(true);
  const [phase, setPhase] = useState<null | "preview" | "import">(null);
  const busy = phase !== null;

  const runPreview = async () => {
    const path = folder.trim();
    if (!path || busy) return;
    setPhase("preview");
    setResult(null);
    try {
      setPreview(await api.metaCodingStudioPreview(path));
    } catch (err) {
      setPreview(null);
      toast.error(errorMessage(err));
    } finally {
      setPhase(null);
    }
  };

  const runImport = async () => {
    const path = folder.trim();
    if (!path || !preview?.exists || busy) return;
    setPhase("import");
    try {
      const res = await api.metaCodingStudioImport({
        folder: path,
        owner: owner.trim() || undefined,
        run_id: runId.trim() || undefined,
        import_hits: importHits,
        import_screening: importScreening,
        import_extractions: importExtractions,
        link_pdfs: linkPdfs,
      });
      setResult(res);
      toast.success(
        t("meta.codingStudioDone", {
          hits: String(res.hits_imported),
          skipped: String(res.hits_skipped),
          screening: String(res.screening_rows),
          extractions: String(res.extractions_imported),
          pdfs: String(res.pdfs_linked),
        }),
      );
      onImported();
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setPhase(null);
    }
  };

  return (
    <Modal open={open} onClose={onClose} size="xl" title={t("meta.codingStudioTitle")}>
      <div className="qc-scroll max-h-[75vh] space-y-3 overflow-auto p-3 text-xs">
        <div className="flex flex-wrap items-center gap-2">
          <Input
            value={folder}
            onChange={(e) => setFolder(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") void runPreview();
            }}
            placeholder={t("meta.codingStudioFolderPlaceholder")}
            className="h-7 min-w-0 flex-1 text-xs"
            aria-label={t("meta.codingStudioFolder")}
          />
          <Button
            variant="secondary"
            icon={
              phase === "preview" ? (
                <LoaderCircle size={13} className="animate-spin" aria-hidden />
              ) : (
                <FolderOpen size={13} aria-hidden />
              )
            }
            disabled={busy || folder.trim() === ""}
            onClick={() => void runPreview()}
          >
            {t("meta.codingStudioPreview")}
          </Button>
        </div>

        {!preview && <p className="text-text-secondary">{t("meta.codingStudioPreviewHint")}</p>}

        {preview && !preview.exists && (
          <p className="rounded-sm border border-danger/40 bg-danger/10 px-2 py-1.5 text-danger" role="alert">
            {t("meta.codingStudioNotFound", { folder: preview.folder })}
          </p>
        )}

        {preview?.exists && (
          <>
            <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-3 lg:grid-cols-4">
              <Summary label={t("meta.codingStudioPapers")} value={preview.papers} />
              <Summary label={t("meta.codingStudioTexts")} value={preview.texts} />
              <Summary label={t("meta.codingStudioExtractionFiles")} value={preview.extraction_files} />
              <Summary label={t("meta.codingStudioStudies")} value={preview.study_count} />
              <Summary
                label={t("meta.codingStudioWorkbook")}
                value={
                  preview.workbook
                    ? t("meta.codingStudioWorkbookRows", { rows: preview.workbook.rows })
                    : t("meta.codingStudioNoWorkbook")
                }
              />
              <Summary
                label={t("meta.codingStudioSchema")}
                value={preview.schema_version ?? "—"}
              />
            </div>

            <div className="flex flex-wrap items-center gap-1.5">
              <span className="text-text-secondary">{t("meta.codingStudioScreenings")}:</span>
              {preview.screenings.length === 0 ? (
                <span className="text-text-secondary">—</span>
              ) : (
                preview.screenings.map((s) => (
                  <span
                    key={s.coder}
                    className="rounded-sm bg-surface-higher px-1.5 py-px text-[10px] text-text-primary"
                  >
                    {s.coder}: {s.rows}
                  </span>
                ))
              )}
            </div>

            {preview.sample_studies.length > 0 && (
              <div className="overflow-auto rounded-sm border border-border">
                <div className="border-b border-border px-3 py-1.5 text-[11px] font-medium text-text-secondary">
                  {t("meta.codingStudioSample")}
                </div>
                <table className="w-full text-left">
                  <thead className="sticky top-0 bg-surface">
                    <tr>
                      <TableHead>{t("meta.codingStudioColKey")}</TableHead>
                      <TableHead>{t("meta.colTitle")}</TableHead>
                      <TableHead>{t("meta.codingStudioColDoi")}</TableHead>
                      <TableHead>{t("meta.codingStudioColRecords")}</TableHead>
                    </tr>
                  </thead>
                  <tbody>
                    {preview.sample_studies.map((study) => (
                      <tr key={study.key}>
                        <td className={`${TD} max-w-0 truncate text-text-secondary`}>{study.key}</td>
                        <td className={`${TD} max-w-0 truncate text-text-primary`}>{study.title}</td>
                        <td className={`${TD} max-w-0 truncate text-text-secondary`}>{study.doi || "—"}</td>
                        <td className={`${TD} text-text-secondary`}>{study.records}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}

        {preview && preview.errors.length > 0 && (
          <div className="rounded-sm border border-warning/40 bg-warning/10 px-2 py-1.5 text-warning">
            <span className="font-medium">{t("meta.codingStudioErrors")}</span>
            <ul className="mt-0.5 list-disc pl-4">
              {preview.errors.map((err, i) => (
                <li key={i}>{err}</li>
              ))}
            </ul>
          </div>
        )}

        {preview?.exists && (
          <div className="space-y-2 border-t border-border pt-3">
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5">
              <Flag
                label={t("meta.codingStudioImportHits")}
                checked={importHits}
                onChange={setImportHits}
                disabled={busy}
              />
              <Flag
                label={t("meta.codingStudioImportScreening")}
                checked={importScreening}
                onChange={setImportScreening}
                disabled={busy}
              />
              <Flag
                label={t("meta.codingStudioImportExtractions")}
                checked={importExtractions}
                onChange={setImportExtractions}
                disabled={busy}
              />
              <Flag
                label={t("meta.codingStudioLinkPdfs")}
                checked={linkPdfs}
                onChange={setLinkPdfs}
                disabled={busy}
              />
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Input
                value={owner}
                onChange={(e) => setOwner(e.target.value)}
                placeholder={t("meta.codingStudioOwner")}
                className="h-7 w-40 text-xs"
                aria-label={t("meta.codingStudioOwner")}
                disabled={busy}
              />
              <Input
                value={runId}
                onChange={(e) => setRunId(e.target.value)}
                placeholder={t("meta.codingStudioRunId")}
                className="h-7 w-40 text-xs"
                aria-label={t("meta.codingStudioRunId")}
                disabled={busy}
              />
            </div>
            {phase === "import" && (
              <p className="flex items-center gap-1.5 text-text-secondary">
                <LoaderCircle size={12} className="animate-spin text-accent" aria-hidden />
                {t("meta.codingStudioImporting")}
              </p>
            )}
          </div>
        )}

        {result && (
          <div className="rounded-sm border border-success/40 bg-success/10 px-2 py-1.5 text-text-primary">
            {t("meta.codingStudioDone", {
              hits: String(result.hits_imported),
              skipped: String(result.hits_skipped),
              screening: String(result.screening_rows),
              extractions: String(result.extractions_imported),
              pdfs: String(result.pdfs_linked),
            })}
            {result.errors.length > 0 && (
              <ul className="mt-1 list-disc pl-4 text-danger">
                {result.errors.map((err, i) => (
                  <li key={i}>{err}</li>
                ))}
              </ul>
            )}
          </div>
        )}

        <div className="flex justify-end gap-2 border-t border-border pt-3">
          <Button variant="secondary" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button
            variant="primary"
            icon={
              phase === "import" ? (
                <LoaderCircle size={13} className="animate-spin" aria-hidden />
              ) : (
                <Upload size={13} aria-hidden />
              )
            }
            disabled={busy || !preview?.exists}
            aria-label={t("meta.codingStudioRun")}
            onClick={() => void runImport()}
          >
            {t("meta.codingStudioRun")}
          </Button>
        </div>
      </div>
    </Modal>
  );
}

function Summary({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-sm border border-border bg-surface px-2 py-1.5">
      <div className="text-[10px] uppercase text-text-secondary">{label}</div>
      <div className="text-sm font-medium text-text-primary">{value}</div>
    </div>
  );
}
