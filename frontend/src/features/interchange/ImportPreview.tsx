/**
 * ImportPreview — the interchange import manager (embedded in the Settings
 * pane).
 *
 * Critcomp-inspired layout: a dashed drop zone with an accent drag-over
 * flip, a per-file list with detected/forced format, size and a tinted
 * status chip, a preview pane (first rows of CSV/XLSX/SAV, codebook lines,
 * or the per-format help text), per-file customization (qualitative
 * columns for survey-style imports) and a confirm bar that imports the
 * batch sequentially through the existing auto-detect endpoint.
 *
 * Overall progress rides the store's background-import task (the ribbon
 * queue chip); per-file status lives in the list. After a successful
 * import the classic result card stays visible (counts per entity).
 */
import { useRef, useState, type ChangeEvent, type DragEvent } from "react";
import {
  CircleCheck,
  FileText,
  LoaderCircle,
  Trash2,
  Upload,
} from "lucide-react";
import { ApiError, type InterchangeResult } from "@/lib/api";
import { Button, Field, IconButton, Input, Select } from "@/components/ui/orchestrator";
import { importLabel } from "@/features/interchange/format";
import {
  FORCEABLE_FORMATS,
  importInterchange,
  previewInterchange,
  type InterchangePreview,
} from "@/features/interchange/importApi";
import { useI18n } from "@/lib/i18n";
import { useProjectStore } from "@/stores/project";

type ItemStatus = "pending" | "importing" | "done" | "error";

interface PreviewItem {
  id: number;
  file: File;
  /** Detected or user-forced format ("" = auto-detect). */
  format: string;
  preview: InterchangePreview | null;
  detecting: boolean;
  status: ItemStatus;
  error: string | null;
  result: InterchangeResult | null;
  qualitativeHeaders: string;
}

/** Survey-style formats take the qualitative-columns customization. */
const QUALITATIVE_FORMATS = new Set(["survey", "xlsx", "sav"]);

/** Tinted status chips (critcomp status-pill look). */
const STATUS_CHIP: Record<ItemStatus, string> = {
  pending: "border-border bg-surface-higher text-text-secondary",
  importing: "border-accent/50 bg-accent/10 text-accent",
  done: "border-success/50 bg-success/10 text-success",
  error: "border-danger/50 bg-danger/10 text-danger",
};

const STATUS_LABEL: Record<ItemStatus, string> = {
  pending: "interchange.statusPending",
  importing: "interchange.statusImporting",
  done: "interchange.statusDone",
  error: "interchange.statusError",
};

/** Display label for a format kind (localized where a key exists). */
function formatLabel(t: (key: string) => string, kind: string): string {
  const key = `interchange.format${kind.charAt(0).toUpperCase()}${kind.slice(1)}`;
  const localized = t(key);
  return localized !== key ? localized : importLabel(kind);
}

/** Per-format help text (localized; empty when no key exists). */
function formatHelp(t: (key: string) => string, kind: string): string {
  const key = `interchange.help${kind.charAt(0).toUpperCase()}${kind.slice(1)}`;
  const localized = t(key);
  return localized !== key ? localized : "";
}

function errorDetail(e: unknown): string {
  if (e instanceof ApiError && typeof e.detail === "string") return e.detail;
  return e instanceof Error ? e.message : "Import failed";
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

/** The counts the backend reports after an import, as [label, value] pairs
 *  (localized labels — rendered as "1 Codes", matching the result card). */
function resultCounts(t: (key: string) => string, res: InterchangeResult): [string, number][] {
  const counts: [string, number | undefined][] = [
    [t("interchange.countCodes"), res.codes],
    [t("interchange.countCategories"), res.categories],
    [t("interchange.countCodings"), res.codings],
    [t("interchange.countSources"), res.sources],
    [t("interchange.countCases"), res.cases],
    [t("interchange.countReferences"), res.references],
    [t("interchange.countAttributes"), res.attributes],
  ];
  return counts.filter(([, value]) => value !== undefined && value > 0) as [string, number][];
}

/** One-line per-file summary ("Codes: 2 · Cases: 1"). */
function resultSummary(t: (key: string) => string, res: InterchangeResult): string {
  const parts = resultCounts(t, res).map(([label, value]) => `${label}: ${value}`);
  return parts.length > 0 ? parts.join(" · ") : t("interchange.importComplete");
}

export function ImportPreview() {
  const { t } = useI18n();
  const [items, setItems] = useState<PreviewItem[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState({ done: 0, total: 0 });
  const [lastResult, setLastResult] = useState<InterchangeResult | null>(null);

  const itemsRef = useRef<PreviewItem[]>([]);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const nextId = useRef(0);
  /** Sequence guard per item: a stale preview response (format changed or
   *  file removed) must never overwrite the current state. */
  const detectSeq = useRef<Record<number, number>>({});

  function patchItem(id: number, patch: Partial<PreviewItem>) {
    itemsRef.current = itemsRef.current.map((it) =>
      it.id === id ? { ...it, ...patch } : it,
    );
    setItems(itemsRef.current);
  }

  /** Sniff an upload (optionally as a forced format) and fill its preview. */
  function startDetect(id: number, forceKind: string | undefined) {
    const item = itemsRef.current.find((it) => it.id === id);
    if (!item) return;
    const seq = (detectSeq.current[id] = (detectSeq.current[id] ?? 0) + 1);
    patchItem(id, { detecting: true, error: null });
    void previewInterchange(item.file, forceKind)
      .then((preview) => {
        if (detectSeq.current[id] !== seq) return; // superseded
        patchItem(id, {
          detecting: false,
          preview,
          format: preview.format,
          // Prefill the qualitative columns from the detected string
          // columns (once — a typed value survives a re-detect).
          ...(item.qualitativeHeaders.trim() === "" && preview.qual_columns?.length
            ? { qualitativeHeaders: preview.qual_columns.join(", ") }
            : {}),
        });
      })
      .catch((e) => {
        if (detectSeq.current[id] !== seq) return;
        patchItem(id, { detecting: false, error: errorDetail(e) });
      });
  }

  function addFiles(list: File[]) {
    const existing = new Set(itemsRef.current.map((it) => it.file.name));
    const added = list
      .filter((file) => !existing.has(file.name))
      .map((file): PreviewItem => ({
        id: nextId.current++,
        file,
        format: "",
        preview: null,
        detecting: false,
        status: "pending",
        error: null,
        result: null,
        qualitativeHeaders: "",
      }));
    if (added.length === 0) return;
    const hadSelection = selectedId != null;
    itemsRef.current = [...itemsRef.current, ...added];
    setItems(itemsRef.current);
    if (!hadSelection) setSelectedId(added[0].id);
    for (const item of added) startDetect(item.id, undefined);
  }

  function removeItem(id: number) {
    delete detectSeq.current[id];
    itemsRef.current = itemsRef.current.filter((it) => it.id !== id);
    setItems(itemsRef.current);
    if (selectedId === id) setSelectedId(itemsRef.current[0]?.id ?? null);
  }

  function handleFileChange(e: ChangeEvent<HTMLInputElement>) {
    const files = Array.from(e.target.files ?? []);
    e.target.value = "";
    if (files.length > 0) addFiles(files);
  }

  function handleDragOver(e: DragEvent<HTMLDivElement>) {
    if (e.dataTransfer.types.includes("Files")) {
      e.preventDefault();
      setDragOver(true);
    }
  }

  function handleDrop(e: DragEvent<HTMLDivElement>) {
    e.preventDefault();
    setDragOver(false);
    const files = Array.from(e.dataTransfer.files);
    if (files.length > 0) addFiles(files);
  }

  /** Format override: re-interpret the file as another format ("" resets
   *  to auto-detection). */
  function changeFormat(id: number, kind: string) {
    patchItem(id, { format: kind });
    startDetect(id, kind === "" ? undefined : kind);
  }

  /** Import the pending files sequentially through the auto-detect
   *  endpoint (forced to each file's format). Progress rides the store's
   *  background-import task — the ribbon queue chip shows it. */
  async function runImport() {
    if (busy) return;
    const pending = itemsRef.current.filter((it) => it.status !== "done");
    if (pending.length === 0) return;
    setBusy(true);
    setProgress({ done: 0, total: pending.length });
    const store = useProjectStore.getState();
    store.setImportState({ done: 0, total: pending.length });
    let ok = 0;
    for (let i = 0; i < pending.length; i++) {
      const item = pending[i];
      patchItem(item.id, { status: "importing", error: null });
      try {
        const qualitativeHeaders = QUALITATIVE_FORMATS.has(item.format)
          ? item.qualitativeHeaders
              .split(",")
              .map((h) => h.trim())
              .filter(Boolean)
          : undefined;
        const res = await importInterchange(item.file, {
          forceKind: item.format || undefined,
          qualitativeHeaders,
        });
        if (res.ok) {
          patchItem(item.id, { status: "done", result: res });
          setLastResult(res);
          ok += 1;
        } else {
          patchItem(item.id, {
            status: "error",
            error: res.message ?? t("interchange.importFailed"),
            result: res,
          });
        }
      } catch (e) {
        patchItem(item.id, { status: "error", error: errorDetail(e) });
      }
      const done = i + 1;
      setProgress({ done, total: pending.length });
      store.setImportState({ done, total: pending.length });
    }
    store.setImportState(null);
    setBusy(false);
    if (ok > 0) void useProjectStore.getState().refreshProject();
  }

  const selectedItem = items.find((it) => it.id === selectedId) ?? null;
  const pendingCount = items.filter((it) => it.status !== "done").length;
  const pct = progress.total > 0 ? Math.round((progress.done / progress.total) * 100) : 0;

  return (
    <div>
      {/* Drop zone — dashed with an accent flip while a file drag hovers
          (critcomp's drag-over pattern). */}
      <div
        onDragOver={handleDragOver}
        onDragLeave={() => setDragOver(false)}
        onDrop={handleDrop}
        className={`rounded-md border-2 border-dashed p-3 text-center transition-colors ${
          dragOver ? "border-accent bg-accent/10" : "border-border bg-bg"
        }`}
      >
        <Upload size={18} className="mx-auto text-text-secondary" aria-hidden />
        <p className="mt-1 text-xs text-text-secondary">{t("interchange.dropZone")}</p>
        <p className="mx-auto mt-0.5 max-w-xs text-[10px] leading-relaxed text-text-secondary/80">
          {t("interchange.dropZoneHint")}
        </p>
        <Button
          variant="secondary"
          icon={<Upload size={12} aria-hidden />}
          className="mt-2"
          onClick={() => fileInputRef.current?.click()}
          disabled={busy}
        >
          {t("interchange.browse")}
        </Button>
        <input
          ref={fileInputRef}
          type="file"
          multiple
          hidden
          aria-label={t("interchange.importFileAria")}
          onChange={handleFileChange}
          disabled={busy}
        />
      </div>

      {/* File list */}
      {items.length > 0 && (
        <div className="mt-2 rounded-sm border border-border bg-bg">
          {items.map((item) => (
            <div
              key={item.id}
              onClick={() => setSelectedId(item.id)}
              className={`cursor-pointer border-b border-border px-2 py-1.5 last:border-0 ${
                selectedId === item.id ? "bg-accent/10" : "hover:bg-surface-higher"
              }`}
            >
              <div className="flex items-center gap-1.5">
                <FileText size={13} className="shrink-0 text-text-secondary" aria-hidden />
                <span className="min-w-0 flex-1 truncate text-xs font-medium">
                  {item.file.name}
                </span>
                <span
                  className={`shrink-0 rounded-full border px-1.5 py-px text-[9px] font-medium ${STATUS_CHIP[item.status]}`}
                >
                  {t(STATUS_LABEL[item.status])}
                </span>
                <IconButton
                  label={t("interchange.removeFile")}
                  title={t("interchange.removeFile")}
                  size="sm"
                  disabled={busy}
                  onClick={(e) => {
                    e.stopPropagation();
                    removeItem(item.id);
                  }}
                  className="hover:bg-danger/10 hover:text-danger"
                >
                  <Trash2 size={11} aria-hidden />
                </IconButton>
              </div>
              <div className="mt-1 flex items-center gap-1.5 pl-5">
                <span className="shrink-0 text-[10px] text-text-secondary">
                  {formatBytes(item.file.size)}
                </span>
                <Select
                  value={item.format}
                  onChange={(e) => changeFormat(item.id, e.target.value)}
                  disabled={busy}
                  aria-label={t("interchange.formatLabel")}
                  title={t("interchange.forcedFormat")}
                  className="h-5 min-w-0 flex-1 text-[10px]"
                >
                  <option value="">{t("interchange.auto")}</option>
                  {FORCEABLE_FORMATS.map((kind) => (
                    <option key={kind} value={kind}>
                      {formatLabel(t, kind)}
                    </option>
                  ))}
                </Select>
              </div>
              {item.detecting && (
                <p className="mt-0.5 flex items-center gap-1 pl-5 text-[10px] text-text-secondary">
                  <LoaderCircle size={10} className="animate-spin" aria-hidden />
                  {t("interchange.detecting")}
                </p>
              )}
              {item.status === "error" && item.error && (
                <p className="mt-0.5 pl-5 text-[10px] text-danger">{item.error}</p>
              )}
              {item.status === "done" && item.result && (
                <p className="mt-0.5 pl-5 text-[10px] text-text-secondary">
                  {resultSummary(t, item.result)}
                </p>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Preview pane */}
      <div className="mt-2 rounded-sm border border-border bg-bg p-2">
        <p className="text-[10px] uppercase tracking-wide text-text-secondary">
          {t("interchange.preview")}
        </p>
        {selectedItem ? (
          selectedItem.detecting ? (
            <p className="mt-1 flex items-center gap-1.5 text-xs text-text-secondary" role="status">
              <LoaderCircle size={12} className="animate-spin" aria-hidden />
              {t("interchange.detecting")}
            </p>
          ) : selectedItem.preview?.lines?.length ? (
            <>
              <p className="mt-1 text-[10px] text-text-secondary">
                {t("interchange.sampleRows", { n: String(selectedItem.preview.lines.length) })}
              </p>
              <ol className="qc-scroll mt-1 max-h-56 overflow-auto rounded-sm border border-border bg-bg p-2 font-mono text-[10px] leading-relaxed text-text-primary">
                {selectedItem.preview.lines.map((line, i) => (
                  <li key={i} className="truncate">
                    {line}
                  </li>
                ))}
              </ol>
            </>
          ) : selectedItem.preview?.columns?.length ? (
            <TabularPreview preview={selectedItem.preview} />
          ) : (
            <p className="mt-1 text-xs leading-relaxed text-text-secondary">
              {formatHelp(t, selectedItem.format) || t("interchange.previewNone")}
            </p>
          )
        ) : (
          <p className="mt-1 text-xs text-text-secondary">
            {t(items.length === 0 ? "interchange.noFiles" : "interchange.selectFile")}
          </p>
        )}
      </div>

      {/* Customization */}
      {selectedItem && (
        <div className="mt-2 rounded-sm border border-border bg-bg p-2">
          {QUALITATIVE_FORMATS.has(selectedItem.format) ? (
            <>
              <Field label={t("interchange.surveyQualitative")}>
                <Input
                  type="text"
                  value={selectedItem.qualitativeHeaders}
                  onChange={(e) => patchItem(selectedItem.id, { qualitativeHeaders: e.target.value })}
                  placeholder="col_a, col_b"
                  aria-label={t("interchange.surveyQualitative")}
                  className="mt-1 w-full"
                  disabled={busy}
                />
              </Field>
              <p className="mt-1.5 text-[10px] leading-relaxed text-text-secondary">
                {t("interchange.surveyQualitativeHint")}
              </p>
            </>
          ) : selectedItem.format !== "codebook" ? (
            <p className="text-xs text-text-secondary">{t("interchange.customizationNone")}</p>
          ) : null}
        </div>
      )}

      {/* Confirm bar */}
      <div className="mt-2 flex items-center gap-2">
        <Button
          variant="primary"
          icon={busy ? <LoaderCircle size={12} className="animate-spin" aria-hidden /> : <Upload size={12} aria-hidden />}
          onClick={() => void runImport()}
          disabled={busy || pendingCount === 0}
        >
          {pendingCount === 1
            ? t("interchange.import")
            : t("interchange.importAll", { n: String(pendingCount) })}
        </Button>
        {busy && (
          <div className="flex min-w-0 flex-1 items-center gap-2" role="status">
            <p className="shrink-0 text-[10px] text-text-secondary">
              {t("interchange.importProgress", {
                done: String(progress.done),
                total: String(progress.total),
              })}
            </p>
            <div className="h-1 min-w-0 flex-1 overflow-hidden rounded-full bg-border">
              <div className="h-full rounded-full bg-accent transition-all" style={{ width: `${pct}%` }} />
            </div>
          </div>
        )}
      </div>

      {/* Result card — the counts of the last successful import stay visible. */}
      {lastResult?.ok && (
        <div className="mt-2 rounded-sm border border-border bg-bg p-2">
          <p className="flex items-center gap-1.5 text-xs font-medium text-success">
            <CircleCheck size={12} aria-hidden />
            {t("interchange.importComplete")}
          </p>
          <ul className="mt-1 grid grid-cols-2 gap-x-3 gap-y-0.5 text-xs text-text-secondary">
            {resultCounts(t, lastResult).map(([label, value]) => (
              <li key={label}>
                {value} {label}
              </li>
            ))}
          </ul>
          {lastResult.message && (
            <p className="mt-1 text-xs text-text-secondary">{lastResult.message}</p>
          )}
        </div>
      )}
    </div>
  );
}

/** First rows of a parsed survey/XLSX/SAV file as a compact table. */
function TabularPreview({ preview }: { preview: InterchangePreview }) {
  const { t } = useI18n();
  const columns = preview.columns ?? [];
  const rows = preview.rows_sample ?? [];
  return (
    <div>
      <p className="mt-1 text-[10px] text-text-secondary">
        {t("interchange.sampleRows", { n: String(rows.length) })}
      </p>
      <div className="qc-scroll mt-1 max-h-56 overflow-auto rounded-sm border border-border bg-bg">
        <table className="w-full border-collapse">
          <thead className="sticky top-0 z-10 bg-surface">
            <tr>
              {columns.map((col, i) => (
                <th
                  key={`${col}-${i}`}
                  className="whitespace-nowrap border-b border-r border-border px-2 py-1 text-left text-[10px] font-medium uppercase tracking-wide text-text-secondary last:border-r-0"
                >
                  {col}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => (
              <tr key={i} className="border-b border-border last:border-0">
                {columns.map((col, j) => (
                  <td
                    key={`${col}-${j}`}
                    className="max-w-40 truncate whitespace-nowrap border-r border-border px-2 py-1 text-xs text-text-primary last:border-r-0"
                    title={row[j] ?? ""}
                  >
                    {row[j] ?? ""}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
