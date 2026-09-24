/**
 * Meta coding-scheme editor / creator.
 *
 * A scheme is a field list (groups + study fields + optional per-contrast
 * metric fields) plus its prescreen/coding prompts. The editor follows the
 * codebook-v2 contract (`docs/meta-port.md` §3): every field carries a type, an
 * editor, and an optional controlled **role** from the shared vocabulary; the
 * metrics section is a repeatable per-contrast field list gated by a toggle,
 * and enabled effect-size families can be expanded into editable metric fields.
 *
 * Stored on ``meta_scheme``: the structured schema lives in ``codebook`` (v2)
 * with ``study_fields`` kept as a v1 alias so the publish path keeps working.
 */
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { ChevronDown, ChevronUp, Copy, Download, Plus, Sparkles, Trash2, Upload } from "lucide-react";
import { api } from "@/lib/api";
import type {
  FieldRole,
  MetaEffectFamily,
  MetaScheme,
  MetaSchemeCodebookV2,
  MetaSchemeExport,
  SchemeField,
} from "@/lib/api/types";
import { EFFECT_FAMILIES, METRIC_ROLES, STUDY_ROLES } from "@/lib/api/types";
import { Button, IconButton, Input, Modal, Select, Textarea, Toggle } from "@/components/ui/orchestrator";
import { useI18n } from "@/lib/i18n";
import { useToast } from "@/lib/toast";
import { errorMessage } from "@/lib/utils";

const FIELD_TYPES = ["string", "integer", "number", "boolean", "list", "object"] as const;
const EDITORS = [
  "text",
  "textarea",
  "number",
  "boolean",
  "select",
  "multiselect",
  "date",
  "json",
  "objectlist",
  "kv",
] as const;

type Scope = "field" | "metric";

interface ColumnDraft {
  name: string;
  type: string;
}

interface FieldDraft {
  id: string;
  name: string;
  label: string;
  group: string;
  type: string;
  editor: string;
  description: string;
  instruction: string;
  required: boolean;
  options: string[];
  columns: ColumnDraft[];
  role: FieldRole | "";
  /** Offer this field as a subgroup/moderator variable. */
  moderator: boolean;
}

interface SchemeDraft {
  id: number | null;
  name: string;
  label: string;
  description: string;
  category: string;
  prescreen: string;
  prompt: string;
  groups: string[];
  codeFields: string;
  fields: FieldDraft[];
  metricsEnabled: boolean;
  metricsGroup: string;
  metricsLabel: string;
  metricsFields: FieldDraft[];
  effectFamilies: string[];
}

const EMPTY: SchemeDraft = {
  id: null,
  name: "",
  label: "",
  description: "",
  category: "Meta",
  prescreen: "",
  prompt: "",
  groups: ["Study"],
  codeFields: "",
  fields: [],
  metricsEnabled: false,
  metricsGroup: "Metrics",
  metricsLabel: "Effect sizes",
  metricsFields: [],
  effectFamilies: [],
};

const ALL_ROLES: readonly FieldRole[] = [...STUDY_ROLES, ...METRIC_ROLES];

/** Standard metric field presets for each enabled effect-size family. */
const FAMILY_FIELDS: Record<
  MetaEffectFamily,
  { name: string; label: string; type: string; editor: string; role: FieldRole }[]
> = {
  descriptives: [
    { name: "n1i", label: "N (group 1)", type: "integer", editor: "number", role: "n1" },
    { name: "m1i", label: "Mean (group 1)", type: "number", editor: "number", role: "m1" },
    { name: "sd1i", label: "SD (group 1)", type: "number", editor: "number", role: "sd1" },
    { name: "n2i", label: "N (group 2)", type: "integer", editor: "number", role: "n2" },
    { name: "m2i", label: "Mean (group 2)", type: "number", editor: "number", role: "m2" },
    { name: "sd2i", label: "SD (group 2)", type: "number", editor: "number", role: "sd2" },
  ],
  t: [
    { name: "t_val", label: "t statistic", type: "number", editor: "number", role: "t" },
    { name: "df_den", label: "df (denominator)", type: "number", editor: "number", role: "df_den" },
  ],
  F: [
    { name: "F_val", label: "F statistic", type: "number", editor: "number", role: "F" },
    { name: "df_num", label: "df (numerator)", type: "number", editor: "number", role: "df_num" },
    { name: "df_den", label: "df (denominator)", type: "number", editor: "number", role: "df_den" },
  ],
  r: [
    { name: "r_val", label: "Correlation r", type: "number", editor: "number", role: "r" },
    { name: "n_total", label: "Total N", type: "integer", editor: "number", role: "n_total" },
  ],
  yi: [
    { name: "yi", label: "Effect size yi", type: "number", editor: "number", role: "yi" },
    { name: "vi", label: "Variance vi", type: "number", editor: "number", role: "vi" },
    { name: "sei", label: "Standard error sei", type: "number", editor: "number", role: "sei" },
  ],
  d_g: [
    { name: "d_val", label: "Cohen's d", type: "number", editor: "number", role: "d" },
    { name: "g_val", label: "Hedges' g", type: "number", editor: "number", role: "g" },
    { name: "d_ci_low", label: "d CI low", type: "number", editor: "number", role: "d_ci_low" },
    { name: "d_ci_high", label: "d CI high", type: "number", editor: "number", role: "d_ci_high" },
    { name: "g_ci_low", label: "g CI low", type: "number", editor: "number", role: "g_ci_low" },
    { name: "g_ci_high", label: "g CI high", type: "number", editor: "number", role: "g_ci_high" },
    { name: "d_se", label: "d standard error", type: "number", editor: "number", role: "d_se" },
    { name: "g_se", label: "g standard error", type: "number", editor: "number", role: "g_se" },
  ],
  odds_ratio: [
    { name: "or_val", label: "Odds ratio", type: "number", editor: "number", role: "or" },
    { name: "or_ci_low", label: "OR CI low", type: "number", editor: "number", role: "or_ci_low" },
    { name: "or_ci_high", label: "OR CI high", type: "number", editor: "number", role: "or_ci_high" },
    { name: "log_odds", label: "Log odds", type: "number", editor: "number", role: "log_odds" },
    { name: "rr", label: "Risk ratio", type: "number", editor: "number", role: "rr" },
  ],
  beta: [
    { name: "beta_val", label: "Regression beta", type: "number", editor: "number", role: "beta" },
    { name: "beta_se", label: "Beta standard error", type: "number", editor: "number", role: "beta_se" },
  ],
  eta2p: [
    { name: "eta2p", label: "Partial eta squared", type: "number", editor: "number", role: "eta2p" },
    { name: "eta2p_ci_low", label: "Partial eta² CI low", type: "number", editor: "number", role: "eta2p_ci_low" },
    { name: "eta2p_ci_high", label: "Partial eta² CI high", type: "number", editor: "number", role: "eta2p_ci_high" },
  ],
  chi2: [
    { name: "chi2_val", label: "Chi-square", type: "number", editor: "number", role: "chi2" },
    { name: "p_val", label: "p-value", type: "number", editor: "number", role: "p" },
    { name: "p_censored", label: "p censored (e.g. < .001)", type: "boolean", editor: "boolean", role: "p_censored" },
  ],
};

function uid(): string {
  return Math.random().toString(36).slice(2, 10);
}

/** Field identifier derived from a human label (``Sample size`` → ``sample_size``). */
function slugifyName(label: string): string {
  const slug = label
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
  return /^[0-9]/.test(slug) ? `f_${slug}` : slug;
}

function normalizeRole(raw: unknown): FieldRole | "" {
  const value = String(raw ?? "");
  return (ALL_ROLES as readonly string[]).includes(value) ? (value as FieldRole) : "";
}

function readColumns(raw: unknown): ColumnDraft[] {
  if (!Array.isArray(raw)) return [];
  return raw
    .filter((c): c is Record<string, unknown> => Boolean(c) && typeof c === "object")
    .map((c) => ({ name: String(c.name ?? ""), type: String(c.type ?? "string") }));
}

function fieldOf(raw: Record<string, unknown>, fallbackGroup: string): FieldDraft {
  return {
    id: uid(),
    name: String(raw.name ?? ""),
    label: String(raw.label ?? ""),
    group: String(raw.group ?? fallbackGroup),
    type: String(raw.type ?? "string"),
    editor: String(raw.editor ?? "text"),
    description: String(raw.description ?? ""),
    instruction: String(raw.instruction ?? ""),
    required: Boolean(raw.required),
    options: Array.isArray(raw.options) ? (raw.options as unknown[]).map(String) : [],
    columns: readColumns(raw.columns),
    role: normalizeRole(raw.role),
    // Fields opt in by default; only an explicit false hides them.
    moderator: raw.moderator === undefined ? true : Boolean(raw.moderator),
  };
}

function blankField(group: string): FieldDraft {
  return fieldOf({ group }, group);
}

/** Read `groups` from either v1 string list or v2 `{name,label}` list. */
function readGroups(raw: unknown): string[] {
  if (!Array.isArray(raw)) return [];
  return raw
    .map((g) => (g && typeof g === "object" ? String((g as { name?: unknown }).name ?? "") : String(g)))
    .map((g) => g.trim())
    .filter(Boolean);
}

/** Read `code_fields` from either v1 string list or v2 `{name,label}` list. */
function readCodeFields(raw: unknown): string {
  if (!Array.isArray(raw)) return "";
  return raw
    .map((c) => (c && typeof c === "object" ? String((c as { name?: unknown }).name ?? "") : String(c)))
    .filter(Boolean)
    .join(", ");
}

function draftFor(scheme: MetaScheme): SchemeDraft {
  let book: Record<string, unknown> = {};
  try {
    const parsed = JSON.parse(scheme.codebook || "{}");
    if (parsed && typeof parsed === "object") book = parsed as Record<string, unknown>;
  } catch {
    book = {};
  }
  const groups = readGroups(book.groups);
  const rawFields = (book.study_fields ?? book.fields) as unknown;
  const fields = Array.isArray(rawFields)
    ? (rawFields as Record<string, unknown>[]).map((f) => fieldOf(f, groups[0] ?? "Study"))
    : [];
  const metricsRaw =
    book.metrics && typeof book.metrics === "object" ? (book.metrics as Record<string, unknown>) : {};
  const metricsFields = Array.isArray(metricsRaw.fields)
    ? (metricsRaw.fields as Record<string, unknown>[]).map((f) =>
        fieldOf(f, String(metricsRaw.group ?? "Metrics")),
      )
    : [];
  const families = Array.isArray(book.effect_families)
    ? (book.effect_families as unknown[]).map(String).filter((f): f is MetaEffectFamily => f in FAMILY_FIELDS)
    : [];
  return {
    id: scheme.id,
    name: scheme.name,
    label: scheme.label ?? "",
    description: scheme.description ?? "",
    category: String(book.category ?? "Meta"),
    prescreen: scheme.prescreen_prompt ?? "",
    prompt: scheme.coding_prompt ?? "",
    groups: groups.length ? groups : ["Study"],
    codeFields: readCodeFields(book.code_fields),
    fields,
    metricsEnabled: Boolean(metricsRaw.enabled) || metricsFields.length > 0,
    metricsGroup: String(metricsRaw.group ?? "Metrics"),
    metricsLabel: String(metricsRaw.label ?? "Effect sizes"),
    metricsFields,
    effectFamilies: families,
  };
}

function splitList(value: string): string[] {
  return value
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
}

function fieldLine(field: FieldDraft): string {
  const opts = field.options.filter((o) => o.trim() !== "");
  const req = field.required ? " (required)" : "";
  const role = field.role ? ` [role: ${field.role}]` : "";
  const label = field.label && field.label !== field.name ? ` — ${field.label}` : "";
  const instruction = field.instruction ? ` ${field.instruction}` : "";
  const options = opts.length ? ` Options: ${opts.join(", ")}.` : "";
  return `* **${field.name}**${label}${role}${req}: ${field.description}${instruction}${options}`;
}

/** Role-aware coding prompt generation (contract §3/§11). */
function generatePrompt(draft: SchemeDraft): string {
  const lines: string[] = [];
  const groups = [...draft.groups];
  for (const field of draft.fields) {
    if (field.group && !groups.includes(field.group)) groups.push(field.group);
  }
  lines.push(
    "You are an expert academic research assistant and data coder. Read the paper thoroughly and code each independent experiment.",
  );
  lines.push(
    'Output the extracted data strictly as a JSON array of objects, one per experiment: [{"study": {...}, "metrics": [...]}].',
  );
  lines.push("");
  lines.push("Study fields:");
  const studyLines: string[] = [];
  for (const group of groups) {
    const members = draft.fields.filter((f) => (f.group || groups[0]) === group);
    if (members.length === 0) continue;
    studyLines.push(`### ${group}`);
    for (const field of members) studyLines.push(fieldLine(field));
  }
  lines.push(...(studyLines.length ? studyLines : ["* (add fields to generate this section)"]));

  const requiredStudy = draft.fields.filter((f) => f.required).map((f) => f.name);
  if (requiredStudy.length) lines.push(`Required study fields: ${requiredStudy.join(", ")}.`);

  if (draft.metricsEnabled) {
    lines.push("");
    lines.push(`${draft.metricsLabel || "Effect sizes"} — one entry per inferential DV/contrast:`);
    for (const field of draft.metricsFields) lines.push(fieldLine(field));
    const roles = draft.metricsFields.map((f) => f.role).filter(Boolean);
    if (roles.length) lines.push(`Metric roles in use: ${[...new Set(roles)].join(", ")}.`);
    const families = draft.effectFamilies.filter((f) => f in FAMILY_FIELDS);
    if (families.length) lines.push(`Preferred effect-size families: ${families.join(", ")}.`);
    lines.push(
      "For every inferential DV and every reported group contrast add a metrics entry with at least one complete set of: full descriptives (roles n1, m1, sd1, n2, m2, sd2), (role t with n1, n2), (role F with df_num, df_den, n1, n2), (role r with n_total), (role yi with vi or sei), (role d or g with n1, n2).",
    );
    lines.push(
      "Never leave a contrast without a complete metric set; leave unavailable numeric fields null and record why in the **missing_metrics_reason** field.",
    );
  } else {
    lines.push("");
    lines.push(
      "Effect sizes: for every inferential dependent variable (DV) and every reported group contrast add a metrics array entry with at least one complete set of full descriptives or a documented fallback.",
    );
  }

  const codeFields = splitList(draft.codeFields);
  if (codeFields.length) {
    lines.push("");
    lines.push(`Also provide these qualitative fields as short strings or arrays: ${codeFields.join(", ")}.`);
  }
  return lines.join("\n");
}

/** Export bundle built from the current draft (used when the scheme is new). */
function bundleFromDraft(draft: SchemeDraft): MetaSchemeExport {
  const studyFields = buildStudyFields(draft);
  const metricFields = buildMetricFields(draft);
  const codebook: MetaSchemeCodebookV2 = {
    version: 2,
    category: draft.category || `Meta / ${draft.label || draft.name}`,
    groups: draft.groups.map((g) => ({ name: g, label: g })),
    fields: studyFields,
    study_fields: studyFields,
    metrics: {
      enabled: draft.metricsEnabled,
      group: draft.metricsGroup || "Metrics",
      label: draft.metricsLabel || "Effect sizes",
      fields: metricFields,
    },
    effect_families: draft.effectFamilies.filter(
      (f): f is MetaEffectFamily => f in FAMILY_FIELDS,
    ),
    code_fields: splitList(draft.codeFields).map((name) => ({ name, label: name, instruction: "" })),
  };
  return {
    name: draft.name.trim() || "scheme",
    label: draft.label || undefined,
    description: draft.description || undefined,
    prescreen_prompt: draft.prescreen,
    coding_prompt: draft.prompt,
    codebook,
  };
}

function toApiField(field: FieldDraft, fallbackGroup: string): SchemeField {
  return {
    name: field.name || slugifyName(field.label) || "field",
    label: field.label || field.name,
    group: field.group || fallbackGroup,
    type: field.type,
    editor: field.editor,
    required: field.required,
    description: field.description,
    instruction: field.instruction,
    options: field.options.filter((o) => o.trim() !== ""),
    columns: field.columns.filter((c) => c.name.trim() !== ""),
    role: field.role || null,
    moderator: field.moderator,
  };
}

function buildStudyFields(draft: SchemeDraft): SchemeField[] {
  return draft.fields.map((f) => toApiField(f, draft.groups[0] || "Study"));
}

function buildMetricFields(draft: SchemeDraft): SchemeField[] {
  return draft.metricsFields.map((f) => toApiField(f, draft.metricsGroup || "Metrics"));
}

function draftFromBundle(bundle: MetaSchemeExport): SchemeDraft {
  const codebook = bundle.codebook ?? ({} as MetaSchemeCodebookV2);
  const asScheme: MetaScheme = {
    id: 0,
    name: bundle.name ?? "scheme",
    label: bundle.label ?? null,
    description: bundle.description ?? null,
    prescreen_prompt: bundle.prescreen_prompt ?? "",
    coding_prompt: bundle.coding_prompt ?? "",
    codebook: JSON.stringify(codebook),
    created: "",
    updated: "",
  };
  return { ...draftFor(asScheme), id: null };
}

function downloadJson(filename: string, data: unknown) {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  // Revoke on a later tick: some browsers abort an in-flight download if the
  // object URL is revoked in the same task as the synthetic click.
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}

function roleSelect(
  value: FieldRole | "",
  onChange: (value: FieldRole | "") => void,
  t: (key: string) => string,
) {
  return (
    <Select
      value={value}
      onChange={(e) => onChange(normalizeRole(e.target.value))}
      className="h-7 w-full text-xs"
    >
      <option value="">{t("meta.roleNone")}</option>
      <optgroup label={t("meta.roleStudy")}>
        {STUDY_ROLES.map((role) => (
          <option key={role} value={role}>
            {role}
          </option>
        ))}
      </optgroup>
      <optgroup label={t("meta.roleMetric")}>
        {METRIC_ROLES.map((role) => (
          <option key={role} value={role}>
            {role}
          </option>
        ))}
      </optgroup>
    </Select>
  );
}

export function MetaSchemeEditor({
  open,
  schemes,
  onClose,
  onChanged,
}: {
  open: boolean;
  schemes: MetaScheme[];
  onClose: () => void;
  onChanged: () => void;
}) {
  const { t } = useI18n();
  const toast = useToast();
  const [draft, setDraft] = useState<SchemeDraft>(EMPTY);
  const [pane, setPane] = useState<"field" | "prompts">("field");
  const [selected, setSelected] = useState<{ scope: Scope; id: string } | null>(null);
  const [newGroup, setNewGroup] = useState("");
  const [busy, setBusy] = useState(false);
  const fileRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    if (!open) return;
    const next = schemes[0] ? draftFor(schemes[0]) : EMPTY;
    setDraft(next);
    setSelected(next.fields[0] ? { scope: "field", id: next.fields[0].id } : null);
    setPane(next.fields.length || next.metricsFields.length ? "field" : "prompts");
    // Reset only when the dialog opens — reloading the scheme list while the
    // editor is open must not discard in-progress edits.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const grouped = useMemo(() => {
    const map = new Map<string, FieldDraft[]>();
    for (const group of draft.groups) map.set(group, []);
    for (const field of draft.fields) {
      const group = field.group || draft.groups[0] || "Study";
      if (!map.has(group)) map.set(group, []);
      map.get(group)!.push(field);
    }
    return [...map.entries()];
  }, [draft.groups, draft.fields]);

  const selectedField = selected
    ? (selected.scope === "field" ? draft.fields : draft.metricsFields).find(
        (f) => f.id === selected.id,
      ) ?? null
    : null;

  const fieldScopeKey = (scope: Scope): "fields" | "metricsFields" =>
    scope === "field" ? "fields" : "metricsFields";

  const patchField = (scope: Scope, id: string, patch: Partial<FieldDraft>) =>
    setDraft((prev) => {
      const key = fieldScopeKey(scope);
      return { ...prev, [key]: prev[key].map((f) => (f.id === id ? { ...f, ...patch } : f)) };
    });

  const addField = (group: string, scope: Scope) => {
    const field = blankField(scope === "metric" ? draft.metricsGroup || "Metrics" : group);
    setDraft((prev) => ({
      ...prev,
      [fieldScopeKey(scope)]: [...prev[fieldScopeKey(scope)], field],
    }));
    setSelected({ scope, id: field.id });
    setPane("field");
  };

  const removeField = (scope: Scope, id: string) => {
    setDraft((prev) => {
      const key = fieldScopeKey(scope);
      return { ...prev, [key]: prev[key].filter((f) => f.id !== id) };
    });
    if (selected?.scope === scope && selected.id === id) setSelected(null);
  };

  const moveField = (scope: Scope, id: string, delta: number) => {
    setDraft((prev) => {
      const key = fieldScopeKey(scope);
      const list = prev[key];
      const index = list.findIndex((f) => f.id === id);
      const target = index + delta;
      if (index < 0 || target < 0 || target >= list.length) return prev;
      const next = [...list];
      [next[index], next[target]] = [next[target], next[index]];
      return { ...prev, [key]: next };
    });
  };

  const addGroup = () => {
    const name = newGroup.trim();
    if (!name || draft.groups.includes(name)) return;
    setDraft((prev) => ({ ...prev, groups: [...prev.groups, name] }));
    setNewGroup("");
  };

  const renameGroup = (old: string, next: string) => {
    setDraft((prev) => ({
      ...prev,
      groups: prev.groups.map((g) => (g === old ? next : g)),
      fields: prev.fields.map((f) => (f.group === old ? { ...f, group: next } : f)),
    }));
  };

  const removeGroup = (name: string) => {
    if (draft.fields.some((f) => f.group === name)) return;
    setDraft((prev) => ({ ...prev, groups: prev.groups.filter((g) => g !== name) }));
  };

  const toggleFamily = (family: MetaEffectFamily, checked: boolean) => {
    setDraft((prev) => ({
      ...prev,
      effectFamilies: checked
        ? [...new Set([...prev.effectFamilies, family])]
        : prev.effectFamilies.filter((f) => f !== family),
    }));
  };

  const addStandardFields = () => {
    const families = draft.effectFamilies.filter(
      (f): f is MetaEffectFamily => f in FAMILY_FIELDS,
    );
    if (families.length === 0) {
      toast.error(t("meta.selectFamily"));
      return;
    }
    setDraft((prev) => {
      const existing = new Set(prev.metricsFields.map((f) => f.name));
      const added: FieldDraft[] = [];
      for (const family of families) {
        for (const preset of FAMILY_FIELDS[family]) {
          if (existing.has(preset.name)) continue;
          existing.add(preset.name);
          added.push({
            id: uid(),
            name: preset.name,
            label: preset.label,
            group: prev.metricsGroup || "Metrics",
            type: preset.type,
            editor: preset.editor,
            description: "",
            instruction: "",
            required: false,
            options: [],
            columns: [],
            role: preset.role,
            moderator: true,
          });
        }
      }
      return { ...prev, metricsEnabled: true, metricsFields: [...prev.metricsFields, ...added] };
    });
    toast.success(t("meta.standardFieldsAdded"));
  };

  const optionRows = (scope: Scope, field: FieldDraft) => (
    <div className="space-y-1">
      {field.options.map((option, i) => (
        <div key={i} className="flex items-center gap-1">
          <Input
            value={option}
            onChange={(e) =>
              patchField(scope, field.id, {
                options: field.options.map((o, j) => (j === i ? e.target.value : o)),
              })
            }
            className="h-7 min-w-0 flex-1 text-xs"
            aria-label={t("meta.optionPlaceholder")}
          />
          <IconButton
            label={t("meta.removeOption")}
            size="row"
            onClick={() =>
              patchField(scope, field.id, { options: field.options.filter((_, j) => j !== i) })
            }
          >
            <Trash2 size={12} aria-hidden />
          </IconButton>
        </div>
      ))}
      <Button
        variant="secondary"
        icon={<Plus size={12} aria-hidden />}
        onClick={() => patchField(scope, field.id, { options: [...field.options, ""] })}
      >
        {t("meta.addOption")}
      </Button>
    </div>
  );

  const columnRows = (scope: Scope, field: FieldDraft) => (
    <div className="space-y-1">
      {field.columns.map((column, i) => (
        <div key={i} className="flex items-center gap-1">
          <Input
            value={column.name}
            onChange={(e) =>
              patchField(scope, field.id, {
                columns: field.columns.map((c, j) =>
                  j === i ? { ...c, name: e.target.value } : c,
                ),
              })
            }
            placeholder={t("meta.columnName")}
            className="h-7 min-w-0 flex-1 text-xs"
            aria-label={t("meta.columnName")}
          />
          <Select
            value={column.type}
            onChange={(e) =>
              patchField(scope, field.id, {
                columns: field.columns.map((c, j) =>
                  j === i ? { ...c, type: e.target.value } : c,
                ),
              })
            }
            className="h-7 w-24 shrink-0 text-xs"
            aria-label={t("meta.columnType")}
          >
            {FIELD_TYPES.map((ty) => (
              <option key={ty} value={ty}>
                {ty}
              </option>
            ))}
          </Select>
          <IconButton
            label={t("meta.removeColumn")}
            size="row"
            onClick={() =>
              patchField(scope, field.id, { columns: field.columns.filter((_, j) => j !== i) })
            }
          >
            <Trash2 size={12} aria-hidden />
          </IconButton>
        </div>
      ))}
      <Button
        variant="secondary"
        icon={<Plus size={12} aria-hidden />}
        onClick={() => patchField(scope, field.id, { columns: [...field.columns, { name: "", type: "string" }] })}
      >
        {t("meta.addColumn")}
      </Button>
    </div>
  );

  const openScheme = (id: number | null) => {
    if (id === null) {
      setDraft({ ...EMPTY, groups: [...EMPTY.groups] });
      setSelected(null);
      setPane("prompts");
      return;
    }
    const found = schemes.find((s) => s.id === id);
    if (!found) return;
    const next = draftFor(found);
    setDraft(next);
    setSelected(next.fields[0] ? { scope: "field", id: next.fields[0].id } : null);
    setPane(next.fields.length || next.metricsFields.length ? "field" : "prompts");
  };

  const save = async () => {
    if (!draft.name.trim()) {
      toast.error(t("meta.schemeNameRequired"));
      return;
    }
    const body = {
      name: draft.name.trim(),
      label: draft.label || undefined,
      description: draft.description || undefined,
      prescreen_prompt: draft.prescreen,
      coding_prompt: draft.prompt,
      codebook: bundleFromDraft(draft).codebook as unknown as Record<string, unknown>,
    };
    setBusy(true);
    try {
      if (draft.id === null) {
        await api.metaCreateScheme(body);
      } else {
        await api.metaUpdateScheme(draft.id, body);
      }
      toast.success(t("meta.schemeSaved"));
      onChanged();
      onClose();
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    if (draft.id === null) {
      openScheme(null);
      return;
    }
    if (!window.confirm(t("meta.schemeDeleteConfirm", { name: draft.name }))) return;
    try {
      await api.metaDeleteScheme(draft.id);
      onChanged();
      onClose();
    } catch (err) {
      toast.error(errorMessage(err));
    }
  };

  const clone = async () => {
    if (draft.id === null) return;
    try {
      const name = t("meta.cloneSchemeName", { name: draft.name });
      await api.metaCloneScheme(draft.id, { name });
      toast.success(t("meta.schemeCloned"));
      onChanged();
    } catch (err) {
      toast.error(errorMessage(err));
    }
  };

  const exportScheme = async () => {
    try {
      const bundle = draft.id === null ? bundleFromDraft(draft) : await api.metaExportScheme(draft.id);
      downloadJson(`${bundle.name || "scheme"}.json`, bundle);
      toast.success(t("meta.schemeExported"));
    } catch (err) {
      toast.error(errorMessage(err));
    }
  };

  const importScheme = async (file: File) => {
    try {
      const parsed = JSON.parse(await file.text()) as unknown;
      const bundle: MetaSchemeExport =
        parsed && typeof parsed === "object" && "codebook" in parsed
          ? (parsed as MetaSchemeExport)
          : { name: file.name.replace(/\.json$/i, ""), codebook: parsed as MetaSchemeCodebookV2 };
      setDraft(draftFromBundle(bundle));
      setSelected(null);
      setPane("prompts");
      toast.success(t("meta.schemeImported"));
    } catch {
      toast.error(t("meta.importInvalid"));
    }
  };

  const showOptions =
    selectedField?.editor === "select" ||
    selectedField?.editor === "multiselect" ||
    selectedField?.type === "list";
  const showColumns = selectedField?.editor === "objectlist";

  const fieldInput = (label: string, control: ReactNode) => (
    <label className="block min-w-0">
      <span className="mb-1 block text-[11px] text-text-secondary">{label}</span>
      {control}
    </label>
  );

  const renderFieldEditor = (scope: Scope, field: FieldDraft) => (
    <div className="space-y-3">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        {fieldInput(
          t("meta.fieldLabel"),
          <Input
            value={field.label}
            onChange={(e) => {
              const label = e.target.value;
              const auto = !field.name || field.name === slugifyName(field.label);
              patchField(scope, field.id, {
                label,
                ...(auto ? { name: slugifyName(label) } : {}),
              });
            }}
            className="h-7 w-full text-xs"
          />,
        )}
        {fieldInput(
          t("meta.fieldName"),
          <Input
            value={field.name}
            onChange={(e) => patchField(scope, field.id, { name: slugifyName(e.target.value) })}
            className="h-7 w-full text-xs"
          />,
        )}
        {fieldInput(
          t("meta.fieldGroup"),
          <Select
            value={field.group}
            onChange={(e) => patchField(scope, field.id, { group: e.target.value })}
            className="h-7 w-full text-xs"
          >
            {[...new Set([...draft.groups, field.group].filter(Boolean))].map((g) => (
              <option key={g} value={g}>
                {g}
              </option>
            ))}
          </Select>,
        )}
        {fieldInput(
          t("meta.fieldType"),
          <Select
            value={field.type}
            onChange={(e) => patchField(scope, field.id, { type: e.target.value })}
            className="h-7 w-full text-xs"
          >
            {FIELD_TYPES.map((ty) => (
              <option key={ty} value={ty}>
                {ty}
              </option>
            ))}
          </Select>,
        )}
        {fieldInput(
          t("meta.fieldEditor"),
          <Select
            value={field.editor}
            onChange={(e) => patchField(scope, field.id, { editor: e.target.value })}
            className="h-7 w-full text-xs"
          >
            {EDITORS.map((ed) => (
              <option key={ed} value={ed}>
                {t(`meta.editor_${ed}`)}
              </option>
            ))}
          </Select>,
        )}
        {fieldInput(t("meta.fieldRole"), roleSelect(field.role, (role) => patchField(scope, field.id, { role }), t))}
        <div className="flex items-end">
          <Toggle
            checked={field.required}
            onChange={() => patchField(scope, field.id, { required: !field.required })}
            label={t("meta.required")}
          />
        </div>
        <div className="flex items-end">
          <label className="flex items-center gap-1.5 text-xs text-text-primary">
            <input
              type="checkbox"
              checked={field.moderator}
              onChange={(e) => patchField(scope, field.id, { moderator: e.target.checked })}
              className="accent-accent"
              aria-label={t("meta.useAsModerator")}
            />
            <span>{t("meta.useAsModerator")}</span>
          </label>
        </div>
      </div>

      {fieldInput(
        t("meta.fieldDescription"),
        <Textarea
          value={field.description}
          onChange={(e) => patchField(scope, field.id, { description: e.target.value })}
          className="w-full text-xs"
          rows={2}
        />,
      )}
      {fieldInput(
        t("meta.fieldInstruction"),
        <Textarea
          value={field.instruction}
          onChange={(e) => patchField(scope, field.id, { instruction: e.target.value })}
          className="w-full text-xs"
          rows={2}
        />,
      )}

      {showOptions && (
        <div className="rounded-sm border border-border p-2">
          <p className="mb-1 text-[11px] text-text-secondary">{t("meta.fieldOptions")}</p>
          {optionRows(scope, field)}
        </div>
      )}

      {showColumns && (
        <div className="rounded-sm border border-border p-2">
          <p className="mb-1 text-[11px] text-text-secondary">{t("meta.fieldColumns")}</p>
          {columnRows(scope, field)}
        </div>
      )}

      <div className="flex items-center gap-1 border-t border-border pt-3">
        <IconButton label={t("meta.moveUp")} size="row" onClick={() => moveField(scope, field.id, -1)}>
          <ChevronUp size={13} aria-hidden />
        </IconButton>
        <IconButton label={t("meta.moveDown")} size="row" onClick={() => moveField(scope, field.id, 1)}>
          <ChevronDown size={13} aria-hidden />
        </IconButton>
        <span className="flex-1" />
        <Button
          variant="danger"
          icon={<Trash2 size={12} aria-hidden />}
          onClick={() => removeField(scope, field.id)}
        >
          {t("meta.removeField")}
        </Button>
      </div>
    </div>
  );

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={t("meta.schemeEditor")}
      panelClassName="flex h-[86vh] w-[94vw] max-w-6xl flex-col"
    >
      <div className="flex min-h-0 flex-1">
        {/* ── left pane: scheme picker, meta, groups, field + metric lists ── */}
        <aside className="flex w-72 min-w-0 shrink-0 flex-col border-r border-border">
          <div className="flex shrink-0 items-center gap-1.5 border-b border-border p-2">
            <Select
              value={draft.id ?? ""}
              onChange={(e) => openScheme(e.target.value === "" ? null : Number(e.target.value))}
              className="h-7 min-w-0 flex-1 text-xs"
              aria-label={t("meta.scheme")}
            >
              <option value="">{t("meta.schemeNew")}</option>
              {schemes.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.label || s.name}
                </option>
              ))}
            </Select>
            <IconButton label={t("meta.deleteScheme")} size="row" onClick={() => void remove()}>
              <Trash2 size={12} aria-hidden />
            </IconButton>
          </div>

          <div className="qc-scroll min-h-0 flex-1 space-y-3 overflow-y-auto p-2">
            <div className="space-y-2">
              {fieldInput(
                t("meta.schemeName"),
                <Input
                  value={draft.name}
                  onChange={(e) => setDraft({ ...draft, name: e.target.value })}
                  className="h-7 w-full text-xs"
                />,
              )}
              {fieldInput(
                t("meta.schemeLabel"),
                <Input
                  value={draft.label}
                  onChange={(e) => setDraft({ ...draft, label: e.target.value })}
                  className="h-7 w-full text-xs"
                />,
              )}
              {fieldInput(
                t("meta.schemeDescription"),
                <Textarea
                  value={draft.description}
                  onChange={(e) => setDraft({ ...draft, description: e.target.value })}
                  className="w-full text-xs"
                  rows={2}
                />,
              )}
            </div>

            <div>
              <p className="mb-1 text-[11px] font-medium uppercase tracking-wide text-text-secondary">
                {t("meta.schemeGroups")}
              </p>
              <div className="space-y-1">
                {draft.groups.map((group) => {
                  const inUse = draft.fields.some((f) => f.group === group);
                  return (
                    <div key={group} className="flex items-center gap-1">
                      <Input
                        value={group}
                        onChange={(e) => renameGroup(group, e.target.value)}
                        className="h-7 min-w-0 flex-1 text-xs"
                        aria-label={t("meta.fieldGroup")}
                      />
                      <IconButton
                        label={t("meta.removeGroup")}
                        size="row"
                        disabled={inUse}
                        title={inUse ? t("meta.groupInUse") : t("meta.removeGroup")}
                        className="disabled:opacity-30"
                        onClick={() => removeGroup(group)}
                      >
                        <Trash2 size={12} aria-hidden />
                      </IconButton>
                    </div>
                  );
                })}
                <div className="flex items-center gap-1">
                  <Input
                    value={newGroup}
                    onChange={(e) => setNewGroup(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") addGroup();
                    }}
                    placeholder={t("meta.addGroup")}
                    className="h-7 min-w-0 flex-1 text-xs"
                    aria-label={t("meta.addGroup")}
                  />
                  <IconButton label={t("meta.addGroup")} size="row" onClick={addGroup}>
                    <Plus size={12} aria-hidden />
                  </IconButton>
                </div>
              </div>
            </div>

            <div>
              <p className="mb-1 text-[11px] font-medium uppercase tracking-wide text-text-secondary">
                {t("meta.schemeFields")}
              </p>
              <div className="space-y-2">
                {grouped.map(([group, members]) => (
                  <div key={group}>
                    <div className="flex items-center justify-between">
                      <span className="text-[11px] text-text-secondary">{group}</span>
                      <IconButton label={t("meta.addField")} size="sm" onClick={() => addField(group, "field")}>
                        <Plus size={11} aria-hidden />
                      </IconButton>
                    </div>
                    <ul className="space-y-0.5">
                      {members.map((field) => (
                        <li key={field.id}>
                          <button
                            type="button"
                            onClick={() => {
                              setSelected({ scope: "field", id: field.id });
                              setPane("field");
                            }}
                            className={`flex w-full items-center gap-1 rounded-sm px-1.5 py-1 text-left text-xs qc-motion ${
                              selected?.scope === "field" && selected.id === field.id
                                ? "bg-accent/10 text-accent"
                                : "text-text-primary hover:bg-surface-higher"
                            }`}
                          >
                            <span className="min-w-0 flex-1 truncate">
                              {field.label || field.name || t("meta.fieldName")}
                            </span>
                            <span className="shrink-0 text-[10px] text-text-secondary">{field.type}</span>
                          </button>
                        </li>
                      ))}
                      {members.length === 0 && (
                        <li className="px-1.5 text-[11px] text-text-secondary">{t("meta.noFields")}</li>
                      )}
                    </ul>
                  </div>
                ))}
              </div>
              <Button
                variant="secondary"
                className="mt-2 w-full justify-center"
                icon={<Plus size={12} aria-hidden />}
                onClick={() => addField(draft.groups[0] ?? "Study", "field")}
              >
                {t("meta.addField")}
              </Button>
            </div>

            {/* ── repeatable metrics / contrast section ── */}
            <div className="rounded-sm border border-border p-2">
              <Toggle
                checked={draft.metricsEnabled}
                onChange={() => setDraft({ ...draft, metricsEnabled: !draft.metricsEnabled })}
                label={t("meta.metricsSection")}
                hint={draft.metricsEnabled ? t("meta.metricsHint") : undefined}
              />
              {draft.metricsEnabled && (
                <div className="mt-2 space-y-2">
                  <div className="grid grid-cols-2 gap-1">
                    {fieldInput(
                      t("meta.metricsGroup"),
                      <Input
                        value={draft.metricsGroup}
                        onChange={(e) => setDraft({ ...draft, metricsGroup: e.target.value })}
                        className="h-7 w-full text-xs"
                      />,
                    )}
                    {fieldInput(
                      t("meta.metricsLabel"),
                      <Input
                        value={draft.metricsLabel}
                        onChange={(e) => setDraft({ ...draft, metricsLabel: e.target.value })}
                        className="h-7 w-full text-xs"
                      />,
                    )}
                  </div>
                  <ul className="space-y-0.5">
                    {draft.metricsFields.map((field) => (
                      <li key={field.id}>
                        <button
                          type="button"
                          onClick={() => {
                            setSelected({ scope: "metric", id: field.id });
                            setPane("field");
                          }}
                          className={`flex w-full items-center gap-1 rounded-sm px-1.5 py-1 text-left text-xs qc-motion ${
                            selected?.scope === "metric" && selected.id === field.id
                              ? "bg-accent/10 text-accent"
                              : "text-text-primary hover:bg-surface-higher"
                          }`}
                        >
                          <span className="min-w-0 flex-1 truncate">
                            {field.label || field.name || t("meta.fieldName")}
                          </span>
                          {field.role && (
                            <span className="shrink-0 text-[10px] text-accent">{field.role}</span>
                          )}
                        </button>
                      </li>
                    ))}
                    {draft.metricsFields.length === 0 && (
                      <li className="px-1.5 text-[11px] text-text-secondary">{t("meta.noFields")}</li>
                    )}
                  </ul>
                  <Button
                    variant="secondary"
                    className="w-full justify-center"
                    icon={<Plus size={12} aria-hidden />}
                    onClick={() => addField(draft.metricsGroup || "Metrics", "metric")}
                  >
                    {t("meta.addMetricField")}
                  </Button>
                </div>
              )}

              <div className="mt-2 space-y-1">
                <p className="text-[11px] font-medium uppercase tracking-wide text-text-secondary">
                  {t("meta.effectFamilies")}
                </p>
                {EFFECT_FAMILIES.map((family) => (
                  <label key={family} className="flex items-center gap-1.5 text-xs text-text-primary">
                    <input
                      type="checkbox"
                      checked={draft.effectFamilies.includes(family)}
                      onChange={(e) => toggleFamily(family, e.target.checked)}
                      className="accent-accent"
                    />
                    <span>{t(`meta.family_${family}`)}</span>
                  </label>
                ))}
                <Button
                  variant="secondary"
                  className="w-full justify-center"
                  icon={<Sparkles size={12} aria-hidden />}
                  onClick={addStandardFields}
                >
                  {t("meta.addStandardFields")}
                </Button>
              </div>
            </div>

            {/* ── scheme clone / import / export ── */}
            <div className="flex flex-wrap items-center gap-1 border-t border-border pt-2">
              <Button
                variant="secondary"
                icon={<Copy size={12} aria-hidden />}
                disabled={draft.id === null}
                onClick={() => void clone()}
              >
                {t("meta.cloneScheme")}
              </Button>
              <Button
                variant="secondary"
                icon={<Upload size={12} aria-hidden />}
                onClick={() => fileRef.current?.click()}
              >
                {t("meta.importScheme")}
              </Button>
              <Button
                variant="secondary"
                icon={<Download size={12} aria-hidden />}
                onClick={() => void exportScheme()}
              >
                {t("meta.exportScheme")}
              </Button>
              <input
                ref={fileRef}
                type="file"
                accept=".json,application/json"
                className="hidden"
                aria-label={t("meta.importScheme")}
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  e.target.value = "";
                  if (file) void importScheme(file);
                }}
              />
            </div>
          </div>
        </aside>

        {/* ── right pane: field details / prompts ── */}
        <section className="flex min-h-0 min-w-0 flex-1 flex-col">
          <div className="flex shrink-0 items-center gap-1 border-b border-border px-2 py-1.5">
            {(["field", "prompts"] as const).map((key) => (
              <button
                key={key}
                type="button"
                onClick={() => setPane(key)}
                aria-pressed={pane === key}
                className={`rounded-sm px-2 py-1 text-xs font-medium qc-motion ${
                  pane === key ? "bg-surface-higher text-accent" : "text-text-secondary hover:bg-surface-higher"
                }`}
              >
                {key === "field" ? t("meta.fieldTab") : t("meta.promptTab")}
              </button>
            ))}
            <span className="flex-1" />
            {pane === "prompts" && (
              <Button
                variant="secondary"
                icon={<Sparkles size={12} aria-hidden />}
                onClick={() => setDraft((prev) => ({ ...prev, prompt: generatePrompt(prev) }))}
              >
                {t("meta.generatePrompt")}
              </Button>
            )}
          </div>

          <div className="qc-scroll min-h-0 flex-1 overflow-y-auto p-3">
            {pane === "field" ? (
              selectedField === null || selected === null ? (
                <p className="text-xs text-text-secondary">{t("meta.selectField")}</p>
              ) : (
                renderFieldEditor(selected.scope, selectedField)
              )
            ) : (
              <div className="space-y-3">
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                  {fieldInput(
                    t("meta.schemeCategory"),
                    <Input
                      value={draft.category}
                      onChange={(e) => setDraft({ ...draft, category: e.target.value })}
                      className="h-7 w-full text-xs"
                    />,
                  )}
                  {fieldInput(
                    t("meta.schemeCodeFields"),
                    <Input
                      value={draft.codeFields}
                      onChange={(e) => setDraft({ ...draft, codeFields: e.target.value })}
                      className="h-7 w-full text-xs"
                    />,
                  )}
                </div>
                {fieldInput(
                  t("meta.prescreenPrompt"),
                  <Textarea
                    value={draft.prescreen}
                    onChange={(e) => setDraft({ ...draft, prescreen: e.target.value })}
                    className="w-full text-xs"
                    rows={4}
                  />,
                )}
                {fieldInput(
                  t("meta.codingPrompt"),
                  <Textarea
                    value={draft.prompt}
                    onChange={(e) => setDraft({ ...draft, prompt: e.target.value })}
                    className="w-full text-xs"
                    rows={14}
                  />,
                )}
              </div>
            )}
          </div>
        </section>
      </div>

      <div className="flex shrink-0 items-center justify-end gap-2 border-t border-border px-3 py-2">
        <Button variant="secondary" onClick={onClose}>
          {t("common.cancel")}
        </Button>
        <Button variant="primary" disabled={busy} onClick={() => void save()}>
          {t("common.save")}
        </Button>
      </div>
    </Modal>
  );
}
