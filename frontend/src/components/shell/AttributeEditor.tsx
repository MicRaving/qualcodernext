/**
 * AttributeEditor — editable property grid for an entity (case or file).
 * Rows come from the entity's existing values plus the scope's attribute
 * types that have no value yet; saving writes the value.
 *
 * Attribute types may carry a MAXQDA-style value list (raw value → label).
 * For those, the value editor renders a dropdown of the defined labels
 * (display label, stored raw value) with a free-text fallback for values
 * not in the list.
 */
import { errorMessage } from "@/lib/utils";
import { useCallback, useEffect, useState } from "react";
import { Check, ChevronDown, LoaderCircle, Plus, X } from "lucide-react";
import {
  ApiError,
  api,
  fetchWithTimeout,
  initApiBase,
} from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { Button, Input, SectionLabel } from "@/components/ui/orchestrator";

/** Attribute type shape with the value-labels map (api.ts type is fixed). */
type AttrTypeLite = {
  name: string;
  case_or_file?: string;
  value_labels?: Record<string, string>;
};

type LabelRow = { raw: string; label: string };

const CUSTOM = "__qc_custom__";

export function AttributeEditor({
  entityId,
  scope,
  values,
  onChange,
}: {
  entityId: number;
  scope: "case" | "file";
  values: { name: string; value: string }[];
  onChange: () => Promise<void>;
}) {
  const { t } = useI18n();
  const [types, setTypes] = useState<AttrTypeLite[]>([]);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [newName, setNewName] = useState("");
  const [labelsOpen, setLabelsOpen] = useState(false);
  const [newLabels, setNewLabels] = useState<LabelRow[]>([{ raw: "", label: "" }]);

  const reload = useCallback(async () => {
    try {
      const list = (await api.attributeTypes()) as AttrTypeLite[];
      const scopeTypes = list.filter((ty) => ty.case_or_file === scope);
      setTypes(scopeTypes);
      setDrafts((prev) => {
        const next: Record<string, string> = {};
        for (const ty of scopeTypes) {
          // The API value wins; the previous draft is only a fallback so a
          // freshly mounted editor never shows stale/empty data.
          next[ty.name] =
            values.find((v) => v.name === ty.name)?.value ?? prev[ty.name] ?? "";
        }
        return next;
      });
      setError(null);
    } catch {
      setError(t("inspector.attributesLoadError"));
    }
  }, [scope, values, t]);

  useEffect(() => {
    void reload();
  }, [entityId, reload]);

  async function save(name: string, value: string) {
    if (saving) return;
    setSaving(name);
    setError(null);
    try {
      await api.setAttributeValue(name, scope, entityId, value);
      await onChange();
    } catch (e) {
      setError(errorMessage(e, t("inspector.attributesSaveError")));
    } finally {
      setSaving(null);
    }
  }

  /** POST an attribute type with its value labels (api.ts wrapper is fixed). */
  async function postType(name: string, value_labels: Record<string, string>) {
    const base = await initApiBase();
    const res = await fetchWithTimeout(`${base}/attributes/types`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name,
        case_or_file: scope,
        value_type: "text",
        value_labels,
      }),
    });
    if (!res.ok) {
      let detail: unknown;
      try {
        detail = (await res.json()).detail;
      } catch {
        /* non-JSON error body */
      }
      const suffix = typeof detail === "string" && detail ? `: ${detail}` : "";
      throw new ApiError(res.status, `API error ${res.status} on /attributes/types${suffix}`, detail);
    }
  }

  async function createType() {
    const name = newName.trim();
    if (!name) return;
    setError(null);
    try {
      const labels: Record<string, string> = {};
      for (const row of newLabels) {
        const raw = row.raw.trim();
        if (raw) labels[raw] = row.label.trim();
      }
      await postType(name, labels);
      setAdding(false);
      setNewName("");
      setLabelsOpen(false);
      setNewLabels([{ raw: "", label: "" }]);
      await reload();
      await onChange();
    } catch (e) {
      setError(errorMessage(e, t("inspector.attributesSaveError")));
    }
  }

  function updateLabelRow(i: number, patch: Partial<LabelRow>) {
    setNewLabels((rows) => rows.map((r, idx) => (idx === i ? { ...r, ...patch } : r)));
  }

  return (
    <div>
      <div className="mb-1 flex items-center justify-between">
        <SectionLabel>{t("inspector.attributes")}</SectionLabel>
        <Button
          variant="primaryCompact"
          icon={<Plus size={12} aria-hidden />}
          title={t("inspector.attributesAddType")}
          onClick={() => {
            setAdding((a) => !a);
            setNewName("");
          }}
        >
          {t("inspector.attributesAddType")}
        </Button>
      </div>
      {adding && (
        <div className="mb-2 flex flex-col gap-1.5">
          <div className="flex items-center gap-1.5">
            <Input
              autoFocus
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && newName.trim()) void createType();
              }}
              placeholder={t("inspector.attributesAddType")}
              className="min-w-0 flex-1"
            />
            <Button
              variant="primary"
              icon={<Check size={14} aria-hidden />}
              title={t("inspector.attributesAddType")}
              disabled={!newName.trim()}
              onClick={() => void createType()}
            >
              {t("common.add")}
            </Button>
            <Button
              variant="secondary"
              icon={<X size={14} aria-hidden />}
              title={t("common.cancel")}
              onClick={() => setAdding(false)}
            >
              {t("common.cancel")}
            </Button>
          </div>
          <Button
            variant="secondary"
            icon={
              <ChevronDown
                size={12}
                aria-hidden
                className={`transition-transform ${labelsOpen ? "rotate-180" : ""}`}
              />
            }
            className="self-start"
            onClick={() => setLabelsOpen((o) => !o)}
          >
            {t("inspector.attributesValueLabels")}
          </Button>
          {labelsOpen && (
            <div className="flex flex-col gap-1.5 border-l border-border pl-2">
              {newLabels.map((row, i) => (
                <div key={i} className="flex items-center gap-1.5">
                  <Input
                    value={row.raw}
                    onChange={(e) => updateLabelRow(i, { raw: e.target.value })}
                    placeholder={t("inspector.attributesRawValue")}
                    className="min-w-0 flex-1"
                  />
                  <Input
                    value={row.label}
                    onChange={(e) => updateLabelRow(i, { label: e.target.value })}
                    placeholder={t("inspector.attributesLabel")}
                    className="min-w-0 flex-1"
                  />
                  <Button
                    variant="danger"
                    icon={<X size={12} aria-hidden />}
                    aria-label={t("inspector.attributesRemoveLabel")}
                    title={t("inspector.attributesRemoveLabel")}
                    className="shrink-0"
                    onClick={() => setNewLabels((rows) => rows.filter((_, idx) => idx !== i))}
                  />
                </div>
              ))}
              <Button
                variant="secondary"
                icon={<Plus size={12} aria-hidden />}
                className="self-start"
                onClick={() => setNewLabels((rows) => [...rows, { raw: "", label: "" }])}
              >
                {t("inspector.attributesAddLabel")}
              </Button>
            </div>
          )}
        </div>
      )}
      {types.length === 0 ? (
        <p className="text-sm text-text-secondary">{t("inspector.noAttributes")}</p>
      ) : (
        <div className="flex flex-col gap-1.5">
          {types.map((ty) => {
            const labels = ty.value_labels ?? {};
            const hasLabels = Object.keys(labels).length > 0;
            const raw = drafts[ty.name] ?? "";
            const inList = raw in labels;
            return (
              <div key={ty.name} className="flex items-center gap-2 text-xs">
                <span className="w-28 shrink-0 truncate text-text-secondary" title={ty.name}>
                  {ty.name}
                </span>
                {hasLabels ? (
                  <div className="flex min-w-0 flex-1 items-center gap-1.5">
                    <select
                      aria-label={ty.name}
                      value={inList ? raw : CUSTOM}
                      onChange={(e) => {
                        const v = e.target.value;
                        if (v !== CUSTOM) {
                          setDrafts((d) => ({ ...d, [ty.name]: v }));
                          void save(ty.name, v);
                        }
                      }}
                      className="min-w-0 flex-1 rounded-sm border border-border bg-bg px-1.5 py-1 text-sm outline-none focus:border-accent"
                    >
                      {Object.entries(labels).map(([value, label]) => (
                        <option key={value} value={value}>
                          {label === value ? label : `${label} (${value})`}
                        </option>
                      ))}
                      <option value={CUSTOM}>{t("inspector.attributesCustomValue")}</option>
                    </select>
                    {!inList && (
                      <input
                        type="text"
                        value={raw}
                        placeholder={t("inspector.attributesCustomValue")}
                        onChange={(e) => setDrafts((d) => ({ ...d, [ty.name]: e.target.value }))}
                        onBlur={(e) => void save(ty.name, e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") void save(ty.name, e.currentTarget.value);
                        }}
                        aria-label={`${ty.name} custom`}
                        className="min-w-0 flex-1 rounded-sm border border-border bg-bg px-1.5 py-1 text-sm outline-none focus:border-accent"
                      />
                    )}
                  </div>
                ) : (
                  <input
                    type="text"
                    value={raw}
                    onChange={(e) => setDrafts((d) => ({ ...d, [ty.name]: e.target.value }))}
                    onBlur={(e) => void save(ty.name, e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") void save(ty.name, e.currentTarget.value);
                    }}
                    aria-label={ty.name}
                    className="min-w-0 flex-1 rounded-sm border border-border bg-bg px-1.5 py-1 text-sm outline-none focus:border-accent"
                  />
                )}
                {saving === ty.name && (
                  <LoaderCircle size={12} className="animate-spin text-text-secondary" aria-hidden />
                )}
              </div>
            );
          })}
        </div>
      )}
      {error && <p className="mt-1 text-xs text-danger">{error}</p>}
    </div>
  );
}
