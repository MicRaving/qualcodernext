/**
 * Scheme-driven extraction editor (contract §3/§4/§11).
 *
 * Renders the active scheme's study fields and repeatable metric/contrast
 * fields as an editable form (every codebook-v2 editor), with per-metric
 * completeness pills derived from the metric roles. A "raw" toggle keeps the
 * old JSON viewer as a secondary view. Saving goes through
 * `api.metaSaveExtraction`; when the backend has no write endpoint yet the
 * failure is surfaced as a toast instead of crashing.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { Braces, Check, Plus, Trash2, TriangleAlert } from "lucide-react";
import { api } from "@/lib/api";
import type {
  MetaExtraction,
  MetaExtractionMetric,
  MetaExtractionRecord,
  MetaScheme,
} from "@/lib/api/types";
import { Button, IconButton, Input, Select, Textarea, Toggle } from "@/components/ui/orchestrator";
import { useI18n } from "@/lib/i18n";
import { useToast } from "@/lib/toast";
import { errorMessage } from "@/lib/utils";
import {
  codebookOf,
  coerceValue,
  effectFamiliesOf,
  isEmptyValue,
  metricFieldsOf,
  metricStatus,
  roleMapOf,
  studyFieldsOf,
} from "@/features/meta/metaScheme";

/** Editors whose value is a free-form JSON blob. */
const JSON_EDITORS = new Set(["json", "object"]);

function JsonField({
  value,
  onChange,
  ariaLabel,
  rows = 2,
}: {
  value: unknown;
  onChange: (next: unknown) => void;
  ariaLabel: string;
  rows?: number;
}) {
  const [text, setText] = useState(() => JSON.stringify(value ?? null, null, 2));
  const [error, setError] = useState(false);
  useEffect(() => {
    setText(JSON.stringify(value ?? null, null, 2));
    setError(false);
  }, [value]);
  return (
    <Textarea
      value={text}
      aria-label={ariaLabel}
      rows={rows}
      className={`w-full text-xs ${error ? "border-danger" : ""}`}
      onChange={(e) => {
        setText(e.target.value);
        try {
          onChange(e.target.value.trim() === "" ? null : JSON.parse(e.target.value));
          setError(false);
        } catch {
          setError(true);
        }
      }}
    />
  );
}

function KeyValueEditor({
  value,
  onChange,
  t,
  label,
}: {
  value: Record<string, unknown>;
  onChange: (next: Record<string, unknown>) => void;
  t: (key: string, params?: Record<string, string | number>) => string;
  label: string;
}) {
  const entries = Object.entries(value ?? {});
  const setKey = (index: number, nextKey: string) => {
    const out: Record<string, unknown> = {};
    entries.forEach(([k, v], i) => {
      out[i === index ? nextKey : k] = v;
    });
    onChange(out);
  };
  const addEntry = () => {
    let i = 1;
    let key = `key_${i}`;
    while (Object.prototype.hasOwnProperty.call(value ?? {}, key)) {
      i += 1;
      key = `key_${i}`;
    }
    onChange({ ...value, [key]: "" });
  };
  const setVal = (index: number, nextVal: unknown) => {
    const out: Record<string, unknown> = {};
    entries.forEach(([k, v], i) => {
      out[k] = i === index ? nextVal : v;
    });
    onChange(out);
  };
  return (
    <div className="space-y-1">
      {entries.map(([k, v], i) => (
        <div key={`${k}-${i}`} className="flex items-center gap-1">
          <Input
            value={k}
            onChange={(e) => setKey(i, e.target.value)}
            placeholder={t("meta.kvKey")}
            className="h-7 w-32 shrink-0 text-xs"
            aria-label={t("meta.kvKey")}
          />
          <Input
            value={String(v ?? "")}
            onChange={(e) => setVal(i, e.target.value)}
            placeholder={t("meta.kvValue")}
            className="h-7 min-w-0 flex-1 text-xs"
            aria-label={t("meta.kvValue")}
          />
          <IconButton
            label={t("meta.removeEntry", { name: label })}
            size="row"
            onClick={() => {
              const out: Record<string, unknown> = {};
              entries.forEach(([key, val], j) => {
                if (j !== i) out[key] = val;
              });
              onChange(out);
            }}
          >
            <Trash2 size={12} aria-hidden />
          </IconButton>
        </div>
      ))}
      <Button variant="secondary" icon={<Plus size={12} aria-hidden />} onClick={addEntry}>
        {t("meta.kvAdd")}
      </Button>
    </div>
  );
}

function ObjectListEditor({
  field,
  value,
  onChange,
  t,
}: {
  field: { label?: string; name?: string; columns?: { name: string; type: string }[] };
  value: Record<string, unknown>[];
  onChange: (next: Record<string, unknown>[]) => void;
  t: (key: string, params?: Record<string, string | number>) => string;
}) {
  const columns = field.columns?.length ? field.columns : [{ name: "value", type: "string" }];
  const rows = Array.isArray(value) ? value : [];
  const patch = (rowIndex: number, column: string, raw: string, type: string) => {
    const parsed = type === "number" || type === "integer" ? Number(raw) : raw;
    onChange(rows.map((r, i) => (i === rowIndex ? { ...r, [column]: parsed } : r)));
  };
  return (
    <div className="space-y-1">
      {rows.map((row, ri) => (
        <div key={ri} className="flex items-start gap-1 rounded-sm border border-border p-1.5">
          {columns.map((column) => (
            <Input
              key={column.name}
              value={String(row[column.name] ?? "")}
              onChange={(e) => patch(ri, column.name, e.target.value, column.type)}
              placeholder={column.name}
              className="h-7 min-w-0 flex-1 text-xs"
              aria-label={`${column.name} ${ri + 1}`}
            />
          ))}
          <IconButton
            label={t("meta.removeRow", { name: field.label || field.name || t("meta.addRow") })}
            size="row"
            onClick={() => onChange(rows.filter((_, i) => i !== ri))}
          >
            <Trash2 size={12} aria-hidden />
          </IconButton>
        </div>
      ))}
      <Button
        variant="secondary"
        icon={<Plus size={12} aria-hidden />}
        onClick={() => onChange([...rows, Object.fromEntries(columns.map((c) => [c.name, ""]))])}
      >
        {t("meta.addRow")}
      </Button>
    </div>
  );
}

function FieldControl({
  field,
  value,
  onChange,
  onNavigate,
  t,
}: {
  field: {
    name: string;
    label?: string;
    editor: string;
    type?: string;
    options?: string[];
    columns?: { name: string; type: string }[];
  };
  value: unknown;
  onChange: (next: unknown) => void;
  onNavigate: (el: HTMLElement, delta: number) => void;
  t: (key: string, params?: Record<string, string | number>) => string;
}) {
  const aria = field.label || field.name;
  const options = field.options ?? [];

  // Quick-entry keys: Tab walks the flat field order; a digit picks the Nth
  // option for categorical/option fields; Enter advances a number editor.
  const handleKeyDown = (e: React.KeyboardEvent<HTMLElement>) => {
    const el = e.currentTarget;
    if (e.key === "Tab") {
      e.preventDefault();
      onNavigate(el, e.shiftKey ? -1 : 1);
      return;
    }
    if (field.editor !== "number" && options.length > 0 && /^[1-9]$/.test(e.key)) {
      e.preventDefault();
      const option = options[Math.min(Number(e.key), options.length) - 1];
      if (field.editor === "multiselect") {
        const chosen = Array.isArray(value) ? value.map(String) : [];
        onChange(
          chosen.includes(option) ? chosen.filter((v) => v !== option) : [...chosen, option],
        );
      } else {
        onChange(option);
      }
      onNavigate(el, 1);
      return;
    }
    if (field.editor === "number" && e.key === "Enter") {
      e.preventDefault();
      onNavigate(el, 1);
    }
  };

  switch (field.editor) {
    case "textarea":
      return (
        <Textarea
          data-qc-field="true"
          onKeyDown={handleKeyDown}
          value={String(value ?? "")}
          onChange={(e) => onChange(e.target.value)}
          className="w-full text-xs"
          rows={3}
          aria-label={aria}
        />
      );
    case "number":
      return (
        <Input
          data-qc-field="true"
          onKeyDown={handleKeyDown}
          type="number"
          value={value === null || value === undefined ? "" : String(value)}
          onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))}
          className="h-7 w-full text-xs"
          aria-label={aria}
        />
      );
    case "boolean":
      return (
        <label className="flex items-center gap-1.5 text-xs text-text-primary">
          <input
            data-qc-field="true"
            onKeyDown={handleKeyDown}
            type="checkbox"
            checked={Boolean(value)}
            onChange={(e) => onChange(e.target.checked)}
            className="accent-accent"
            aria-label={aria}
          />
          <span>{t("meta.booleanTrue")}</span>
        </label>
      );
    case "select":
      return (
        <Select
          data-qc-field="true"
          onKeyDown={handleKeyDown}
          value={String(value ?? "")}
          onChange={(e) => onChange(e.target.value)}
          className="h-7 w-full text-xs"
          aria-label={aria}
        >
          <option value="">—</option>
          {options.map((o) => (
            <option key={o} value={o}>
              {o}
            </option>
          ))}
        </Select>
      );
    case "multiselect": {
      const chosen = Array.isArray(value) ? value.map(String) : [];
      return (
        <div
          data-qc-field="true"
          tabIndex={0}
          onKeyDown={handleKeyDown}
          className="flex flex-wrap gap-x-3 gap-y-1 outline-none focus-visible:ring-1 focus-visible:ring-accent"
          role="group"
          aria-label={aria}
        >
          {options.length === 0 ? (
            <span className="text-[11px] text-text-secondary">—</span>
          ) : (
            options.map((o) => (
              <label key={o} className="flex items-center gap-1 text-xs text-text-primary">
                <input
                  type="checkbox"
                  checked={chosen.includes(o)}
                  onChange={(e) =>
                    onChange(e.target.checked ? [...chosen, o] : chosen.filter((v) => v !== o))
                  }
                  className="accent-accent"
                />
                <span>{o}</span>
              </label>
            ))
          )}
        </div>
      );
    }
    case "date":
      return (
        <Input
          data-qc-field="true"
          onKeyDown={handleKeyDown}
          type="date"
          value={String(value ?? "")}
          onChange={(e) => onChange(e.target.value)}
          className="h-7 w-full text-xs"
          aria-label={aria}
        />
      );
    case "objectlist":
      return (
        <div data-qc-field="true" tabIndex={-1} onKeyDown={handleKeyDown}>
          <ObjectListEditor
            field={field}
            value={(value as Record<string, unknown>[]) ?? []}
            onChange={onChange}
            t={t}
          />
        </div>
      );
    case "kv":
      return (
        <div data-qc-field="true" tabIndex={-1} onKeyDown={handleKeyDown}>
          <KeyValueEditor
            value={(value as Record<string, unknown>) ?? {}}
            onChange={onChange}
            t={t}
            label={aria}
          />
        </div>
      );
    default:
      if (JSON_EDITORS.has(field.editor)) {
        return (
          <div data-qc-field="true" tabIndex={-1} onKeyDown={handleKeyDown}>
            <JsonField value={value} onChange={onChange} ariaLabel={aria} />
          </div>
        );
      }
      return (
        <Input
          data-qc-field="true"
          onKeyDown={handleKeyDown}
          value={String(value ?? "")}
          onChange={(e) => onChange(e.target.value)}
          className="h-7 w-full text-xs"
          aria-label={aria}
        />
      );
  }
}

function statusPillClass(status: string): string {
  if (status === "complete") return "bg-success/10 text-success";
  if (status === "fallback") return "bg-warning/10 text-warning";
  return "bg-danger/10 text-danger";
}

export function MetaExtractionForm({
  extraction,
  scheme,
  owner,
  onSaved,
}: {
  extraction: MetaExtraction;
  scheme: MetaScheme | null;
  /** Effective writer: the scoped/current coder. Defaults to the row's owner. */
  owner?: string;
  onSaved: (updated: MetaExtraction) => void;
}) {
  const { t } = useI18n();
  const toast = useToast();
  const [records, setRecords] = useState<MetaExtractionRecord[]>([]);
  const [raw, setRaw] = useState(false);
  const [missingOnly, setMissingOnly] = useState(false);
  const [busy, setBusy] = useState(false);
  const formRef = useRef<HTMLDivElement | null>(null);

  // Flat field order = DOM order of every `[data-qc-field]` control: study
  // fields first, then each contrast's metric fields.
  const navigateField = (current: HTMLElement, delta: number) => {
    const container = formRef.current;
    if (!container) return;
    const fields = Array.from(container.querySelectorAll<HTMLElement>("[data-qc-field]"));
    const index = fields.indexOf(current);
    if (index < 0) return;
    fields[index + delta]?.focus();
  };

  const book = useMemo(() => codebookOf(scheme), [scheme]);
  const studyFields = useMemo(() => studyFieldsOf(book), [book]);
  const metricFields = useMemo(() => metricFieldsOf(book), [book]);
  const families = useMemo(() => effectFamiliesOf(book), [book]);
  const roleMap = useMemo(
    () => roleMapOf([...studyFields, ...metricFields]),
    [studyFields, metricFields],
  );

  // Reset the working draft whenever a different extraction is opened.
  useEffect(() => {
    const vars = extraction.study_vars;
    const initial =
      vars && typeof vars === "object" && Array.isArray((vars as { records?: unknown }).records)
        ? ((vars as { records: MetaExtractionRecord[] }).records as MetaExtractionRecord[])
        : [];
    setRecords(
      initial.length
        ? initial.map((r) => ({
            study: { ...(r.study ?? {}) },
            metrics: Array.isArray(r.metrics) ? r.metrics.map((m) => ({ ...m })) : [],
          }))
        : [{ study: {}, metrics: [{}] }],
    );
  }, [extraction]);

  const patchStudy = (index: number, name: string, value: unknown) =>
    setRecords((prev) =>
      prev.map((r, i) => (i === index ? { ...r, study: { ...r.study, [name]: value } } : r)),
    );
  const patchMetric = (recordIndex: number, metricIndex: number, name: string, value: unknown) =>
    setRecords((prev) =>
      prev.map((r, i) =>
        i === recordIndex
          ? {
              ...r,
              metrics: r.metrics.map((m, j) => (j === metricIndex ? { ...m, [name]: value } : m)),
            }
          : r,
      ),
    );
  const addMetric = (recordIndex: number) =>
    setRecords((prev) =>
      prev.map((r, i) => (i === recordIndex ? { ...r, metrics: [...r.metrics, {}] } : r)),
    );
  const removeMetric = (recordIndex: number, metricIndex: number) =>
    setRecords((prev) =>
      prev.map((r, i) =>
        i === recordIndex
          ? { ...r, metrics: r.metrics.filter((_, j) => j !== metricIndex) }
          : r,
      ),
    );
  const addRecord = () => setRecords((prev) => [...prev, { study: {}, metrics: [{}] }]);
  const removeRecord = (index: number) =>
    setRecords((prev) => prev.filter((_, i) => i !== index));

  const studyFieldMissing = (record: MetaExtractionRecord) =>
    studyFields.some((f) => f.required && isEmptyValue(f, record.study[f.name]));

  const metricIsMissing = (metric: MetaExtractionMetric) =>
    metricStatus(metric, roleMap, families).status !== "complete";

  const save = async () => {
    setBusy(true);
    try {
      const result = await api.metaSaveExtraction({
        hit_id: extraction.hit_id,
        owner: owner || extraction.owner,
        scheme: extraction.scheme,
        study_vars: { records },
        status: extraction.status || "extracted",
        missing_reason: extraction.missing_reason ?? null,
      });
      // The endpoint wraps the saved row in an envelope; unwrap `.extraction`.
      const updated =
        result?.extraction ?? ({ ...extraction, study_vars: { records } } as MetaExtraction);
      toast.success(t("meta.extractionSaved"));
      onSaved(updated);
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const fieldLabel = (name: string, label?: string) => label || name;

  const renderStudyField = (record: MetaExtractionRecord, recordIndex: number, fieldIndex: number) => {
    const field = studyFields[fieldIndex];
    return (
      <label key={field.name} className="block min-w-0">
        <span className="mb-1 block text-[11px] text-text-secondary">
          {fieldLabel(field.name, field.label)}
          {field.required ? <span className="text-danger"> *</span> : null}
        </span>
        <FieldControl
          field={field}
          value={record.study[field.name]}
          onChange={(next) =>
            patchStudy(recordIndex, field.name, coerceValue(field, next))
          }
          onNavigate={navigateField}
          t={t}
        />
        {field.role ? (
          <span className="mt-0.5 block text-[10px] text-text-secondary">{field.role}</span>
        ) : null}
      </label>
    );
  };

  const renderMetricField = (
    record: MetaExtractionRecord,
    recordIndex: number,
    metricIndex: number,
    fieldIndex: number,
  ) => {
    const field = metricFields[fieldIndex];
    const metric = record.metrics[metricIndex] ?? {};
    return (
      <label key={field.name} className="block min-w-0">
        <span className="mb-1 block text-[11px] text-text-secondary">
          {fieldLabel(field.name, field.label)}
          {field.required ? <span className="text-danger"> *</span> : null}
        </span>
        <FieldControl
          field={field}
          value={metric[field.name]}
          onChange={(next) => patchMetric(recordIndex, metricIndex, field.name, coerceValue(field, next))}
          onNavigate={navigateField}
          t={t}
        />
      </label>
    );
  };

  const visibleRecords = missingOnly
    ? records.filter(
        (r) => studyFieldMissing(r) || r.metrics.some((m) => metricIsMissing(m)),
      )
    : records;

  return (
    <div className="space-y-3" ref={formRef}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs text-text-secondary">
          {scheme?.label ?? extraction.scheme_label ?? extraction.scheme}
        </span>
        <span className={`rounded-sm px-1.5 py-px text-[10px] font-medium ${statusPillClass(extraction.status)}`}>
          {extraction.status}
        </span>
        <span className="text-[10px] text-text-secondary">{t("meta.quickEntryHint")}</span>
        <span className="flex-1" />
        <Toggle
          checked={missingOnly}
          onChange={() => setMissingOnly((v) => !v)}
          label={t("meta.missingOnly")}
        />
        <Button
          variant="secondary"
          icon={raw ? <Check size={12} aria-hidden /> : <Braces size={12} aria-hidden />}
          onClick={() => setRaw((v) => !v)}
        >
          {raw ? t("meta.editorView") : t("meta.rawView")}
        </Button>
      </div>

      {raw ? (
        <div className="space-y-3">
          {extraction.prescreen ? (
            <div>
              <h4 className="mb-1 font-medium text-text-primary">{t("meta.prescreen")}</h4>
              <pre className="whitespace-pre-wrap rounded-sm bg-surface-higher p-2 text-[11px] text-text-secondary">
                {JSON.stringify(extraction.prescreen, null, 2)}
              </pre>
            </div>
          ) : null}
          <div>
            <h4 className="mb-1 font-medium text-text-primary">{t("meta.studyVars")}</h4>
            <pre className="whitespace-pre-wrap rounded-sm bg-surface-higher p-2 text-[11px] text-text-secondary">
              {JSON.stringify({ records }, null, 2)}
            </pre>
          </div>
          <div>
            <h4 className="mb-1 font-medium text-text-primary">
              {t("meta.dvMetrics")} ({extraction.dv_metrics?.length ?? 0})
            </h4>
            <pre className="whitespace-pre-wrap rounded-sm bg-surface-higher p-2 text-[11px] text-text-secondary">
              {JSON.stringify(extraction.dv_metrics, null, 2)}
            </pre>
          </div>
        </div>
      ) : (
        <div className="space-y-4">
          {visibleRecords.length === 0 ? (
            <p className="text-xs text-text-secondary">{t("meta.noMissingMetrics")}</p>
          ) : null}
          {visibleRecords.map((record) => {
            const recordIndex = records.indexOf(record);
            const metrics = missingOnly
              ? record.metrics.filter((m) => metricIsMissing(m))
              : record.metrics;
            return (
              <div key={recordIndex} className="rounded-sm border border-border p-2">
                <div className="mb-2 flex items-center gap-2">
                  <span className="text-[11px] font-medium uppercase tracking-wide text-text-secondary">
                    {t("meta.experiment")} {recordIndex + 1}
                  </span>
                  <span className="flex-1" />
                  <IconButton
                    label={t("meta.removeExperiment")}
                    size="sm"
                    className="disabled:opacity-30"
                    disabled={records.length <= 1}
                    onClick={() => removeRecord(recordIndex)}
                  >
                    <Trash2 size={12} aria-hidden />
                  </IconButton>
                </div>

                {studyFields.length > 0 && (
                  <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                    {studyFields.map((_, fi) => renderStudyField(record, recordIndex, fi))}
                  </div>
                )}

                {metricFields.length > 0 && (
                  <div className="mt-3 space-y-2">
                    {metrics.map((metric) => {
                      const metricIndex = record.metrics.indexOf(metric);
                      const status = metricStatus(metric, roleMap, families);
                      return (
                        <div key={metricIndex} className="rounded-sm bg-surface-higher p-2">
                          <div className="mb-1.5 flex items-center gap-2">
                            <span className="text-[11px] font-medium text-text-secondary">
                              {t("meta.contrast")} {metricIndex + 1}
                            </span>
                            <span
                              className={`rounded-sm px-1.5 py-px text-[10px] font-medium ${statusPillClass(status.status)}`}
                              title={
                                status.reason.startsWith("meta.")
                                  ? t(status.reason)
                                  : status.reason
                              }
                            >
                              {t(`meta.metric_${status.status}`)}
                            </span>
                            {status.status === "incomplete" ? (
                              <TriangleAlert size={11} className="text-warning" aria-hidden />
                            ) : null}
                            <span className="flex-1" />
                            <IconButton
                              label={t("meta.removeMetric")}
                              size="sm"
                              onClick={() => removeMetric(recordIndex, metricIndex)}
                            >
                              <Trash2 size={12} aria-hidden />
                            </IconButton>
                          </div>
                          <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
                            {metricFields.map((_, fi) =>
                              renderMetricField(record, recordIndex, metricIndex, fi),
                            )}
                          </div>
                        </div>
                      );
                    })}
                    <Button
                      variant="secondary"
                      icon={<Plus size={12} aria-hidden />}
                      onClick={() => addMetric(recordIndex)}
                    >
                      {t("meta.addContrast")}
                    </Button>
                  </div>
                )}
              </div>
            );
          })}

          {studyFields.length === 0 && metricFields.length === 0 ? (
            <p className="text-xs text-text-secondary">{t("meta.schemeHasNoFields")}</p>
          ) : null}
        </div>
      )}

      <div className="flex items-center justify-end gap-2 border-t border-border pt-3">
        <Button variant="secondary" icon={<Plus size={12} aria-hidden />} onClick={addRecord}>
          {t("meta.addExperiment")}
        </Button>
        <Button variant="primary" disabled={busy || raw} onClick={() => void save()}>
          {t("common.save")}
        </Button>
      </div>
    </div>
  );
}
