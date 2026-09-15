/**
 * Manual import labeler for meta search results.
 *
 * Pick a file (EBSCO XML / Excel / RIS / CSV), see the detected sheet, header
 * row, columns and a sample, then map each column to a meta field before
 * importing. Structured formats (XML/RIS) import as-is.
 */
import { useRef, useState } from "react";
import { Upload } from "lucide-react";
import { api } from "@/lib/api";
import type { MetaImportPreview } from "@/lib/api/types";
import { Button, Input, Modal, Select, TableHead } from "@/components/ui/orchestrator";
import { useI18n } from "@/lib/i18n";
import { useToast } from "@/lib/toast";
import { errorMessage } from "@/lib/utils";

const TD = "border-b border-border px-3 py-1.5 text-sm align-top";

export function MetaImportDialog({
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
  const fileRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [searchRun, setSearchRun] = useState("");
  const [preview, setPreview] = useState<MetaImportPreview | null>(null);
  const [sheet, setSheet] = useState("");
  const [headerRow, setHeaderRow] = useState(0);
  const [columnField, setColumnField] = useState<Record<number, string>>({});
  const [busy, setBusy] = useState(false);

  const applyPreview = (p: MetaImportPreview) => {
    setPreview(p);
    setSheet(p.sheet);
    setHeaderRow(p.header_row >= 0 ? p.header_row : 0);
    const inverted: Record<number, string> = {};
    for (const [field, idx] of Object.entries(p.mapping)) {
      if (idx !== null && idx !== undefined) inverted[idx as number] = field;
    }
    setColumnField(inverted);
  };

  const loadPreview = async (f: File, sheetName?: string) => {
    setBusy(true);
    try {
      applyPreview(await api.metaPreviewHits(f, sheetName));
    } catch (err) {
      setPreview(null);
      toast.error(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const onFile = (f: File | undefined) => {
    if (!f) return;
    setFile(f);
    void loadPreview(f);
  };

  // Header row + sheet changes need a fresh preview server-side (the sample
  // and detected mapping depend on them).
  const changeSheet = (name: string) => {
    setSheet(name);
    if (file) void loadPreview(file, name);
  };

  const setColumn = (col: number, field: string) => {
    setColumnField((prev) => {
      const next = { ...prev };
      if (field) {
        for (const key of Object.keys(next)) {
          if (next[Number(key)] === field) delete next[Number(key)];
        }
        next[col] = field;
      } else {
        delete next[col];
      }
      return next;
    });
  };

  const buildMapping = (): Record<string, number | null> => {
    const mapping: Record<string, number | null> = {};
    for (const field of preview?.fields ?? []) mapping[field] = null;
    for (const [col, field] of Object.entries(columnField)) {
      if (field) mapping[field] = Number(col);
    }
    return mapping;
  };

  const doImport = async () => {
    if (!file || !preview) return;
    setBusy(true);
    try {
      const res = await api.metaImportHits(
        file,
        searchRun.trim() || undefined,
        preview.structured
          ? undefined
          : { sheet: sheet || undefined, headerRow, mapping: buildMapping() },
      );
      toast.success(
        t("meta.imported", {
          imported: String(res.imported),
          duplicates: String(res.duplicates_skipped),
        }),
      );
      onImported();
      onClose();
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const columns = preview
    ? preview.structured
      ? preview.columns
      : (preview.head_rows[headerRow] ?? [])
    : [];

  return (
    <Modal open={open} onClose={onClose} size="xl" title={t("meta.importTitle")}>
      <div className="max-h-[75vh] space-y-3 overflow-auto p-3 text-xs">
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="secondary" icon={<Upload size={13} aria-hidden />} onClick={() => fileRef.current?.click()}>
            {t("meta.chooseFile")}
          </Button>
          <span className="min-w-0 flex-1 truncate text-text-secondary">
            {file?.name ?? t("meta.importHint")}
          </span>
          <Input
            value={searchRun}
            onChange={(e) => setSearchRun(e.target.value)}
            placeholder={t("meta.searchRun")}
            className="h-7 w-36 text-xs"
            aria-label={t("meta.searchRun")}
          />
          <input
            ref={fileRef}
            type="file"
            accept=".xml,.xlsx,.xlsm,.xls,.ris,.csv"
            hidden
            aria-hidden
            onChange={(e) => {
              onFile(e.target.files?.[0]);
              e.target.value = "";
            }}
          />
        </div>

        {preview?.structured && <p className="text-text-secondary">{t("meta.structuredHint")}</p>}

        {preview && !preview.structured && (
          <>
            <div className="flex flex-wrap items-center gap-3">
              {preview.sheets.length > 0 && (
                <label className="flex items-center gap-2">
                  <span className="text-text-secondary">{t("meta.sheet")}</span>
                  <Select value={sheet} onChange={(e) => changeSheet(e.target.value)} className="h-7 text-xs">
                    {preview.sheets.map((s) => (
                      <option key={s} value={s}>
                        {s}
                      </option>
                    ))}
                  </Select>
                </label>
              )}
              <label className="flex items-center gap-2">
                <span className="text-text-secondary">{t("meta.headerRow")}</span>
                <Select
                  value={headerRow}
                  onChange={(e) => setHeaderRow(Number(e.target.value))}
                  className="h-7 text-xs"
                >
                  {preview.head_rows.map((_, i) => (
                    <option key={i} value={i}>
                      {i + 1}
                    </option>
                  ))}
                </Select>
              </label>
            </div>

            <table className="w-full text-left">
              <thead className="sticky top-0 bg-surface">
                <tr>
                  <TableHead>{t("meta.colColumn")}</TableHead>
                  <TableHead>{t("meta.colField")}</TableHead>
                  <TableHead>{t("meta.colSample")}</TableHead>
                </tr>
              </thead>
              <tbody>
                {columns.map((header, idx) => (
                  <tr key={idx}>
                    <td className={`${TD} max-w-0 truncate text-text-primary`}>{header || `#${idx + 1}`}</td>
                    <td className={TD}>
                      <Select
                        value={columnField[idx] ?? ""}
                        onChange={(e) => setColumn(idx, e.target.value)}
                        className="h-7 w-40 text-xs"
                        aria-label={header}
                      >
                        <option value="">{t("meta.ignore")}</option>
                        {preview.fields.map((field) => (
                          <option key={field} value={field}>
                            {field}
                          </option>
                        ))}
                      </Select>
                    </td>
                    <td className={`${TD} max-w-0 truncate text-text-secondary`}>
                      {preview.rows_sample[0]?.[idx] ?? ""}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}

        <div className="flex justify-end gap-2 border-t border-border pt-3">
          <Button variant="secondary" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button variant="primary" disabled={!file || busy || !preview} onClick={() => void doImport()}>
            {t("meta.importSearch")}
          </Button>
        </div>
      </div>
    </Modal>
  );
}
