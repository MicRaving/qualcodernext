/**
 * Meta coding-scheme editor / creator.
 *
 * A scheme is a named field list (groups + fields + optional qualitative
 * fields) plus its prescreen prompt; the coding prompt can be generated from
 * the fields and then edited. Fields use dropdown selectors for group, type
 * and editor, and a dedicated option-list editor for select/list fields.
 *
 * Stored on ``meta_scheme``: the structured schema lives in ``codebook``
 * (``groups`` + ``study_fields`` + ``code_fields``), the prompts as text.
 */
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { ChevronDown, ChevronUp, Plus, Sparkles, Trash2 } from "lucide-react";
import { api } from "@/lib/api";
import type { MetaScheme } from "@/lib/api/types";
import { Button, IconButton, Input, Modal, Select, Textarea, Toggle } from "@/components/ui/orchestrator";
import { useI18n } from "@/lib/i18n";
import { useToast } from "@/lib/toast";
import { errorMessage } from "@/lib/utils";

const FIELD_TYPES = ["string", "integer", "number", "boolean", "list", "object"] as const;
const EDITORS = ["text", "number", "select", "textarea"] as const;

interface SchemeField {
  id: string;
  name: string;
  label: string;
  group: string;
  type: string;
  editor: string;
  description: string;
  required: boolean;
  options: string[];
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
  fields: SchemeField[];
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

function fieldOf(raw: Record<string, unknown>, fallbackGroup: string): SchemeField {
  return {
    id: uid(),
    name: String(raw.name ?? ""),
    label: String(raw.label ?? ""),
    group: String(raw.group ?? fallbackGroup),
    type: String(raw.type ?? "string"),
    editor: String(raw.editor ?? "text"),
    description: String(raw.description ?? ""),
    required: Boolean(raw.required),
    options: Array.isArray(raw.options) ? (raw.options as unknown[]).map(String) : [],
  };
}

function draftFor(scheme: MetaScheme): SchemeDraft {
  let book: Record<string, unknown> = {};
  try {
    const parsed = JSON.parse(scheme.codebook || "{}");
    if (parsed && typeof parsed === "object") book = parsed as Record<string, unknown>;
  } catch {
    book = {};
  }
  const groups = Array.isArray(book.groups) ? (book.groups as unknown[]).map(String) : [];
  const rawFields = (book.study_fields ?? book.fields) as unknown;
  const fields = Array.isArray(rawFields)
    ? (rawFields as Record<string, unknown>[]).map((f) => fieldOf(f, groups[0] ?? "Study"))
    : [];
  const codeFields = Array.isArray(book.code_fields)
    ? (book.code_fields as unknown[]).map(String).join(", ")
    : "";
  return {
    id: scheme.id,
    name: scheme.name,
    label: scheme.label ?? "",
    description: scheme.description ?? "",
    category: String(book.category ?? "Meta"),
    prescreen: scheme.prescreen_prompt ?? "",
    prompt: scheme.coding_prompt ?? "",
    groups: groups.length ? groups : ["Study"],
    codeFields,
    fields,
  };
}

function splitList(value: string): string[] {
  return value
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
}

function generatePrompt(draft: SchemeDraft): string {
  const lines: string[] = [];
  const groups = [...draft.groups];
  for (const field of draft.fields) {
    if (field.group && !groups.includes(field.group)) groups.push(field.group);
  }
  for (const group of groups) {
    const members = draft.fields.filter((f) => (f.group || groups[0]) === group);
    if (members.length === 0) continue;
    lines.push(`### ${group}`);
    for (const field of members) {
      const opts = field.options.length ? ` Options: ${field.options.join(", ")}.` : "";
      const req = field.required ? " (required)" : "";
      const label = field.label && field.label !== field.name ? ` — ${field.label}` : "";
      lines.push(`* **${field.name}**${label}${req}: ${field.description}${opts}`);
    }
  }
  const codeFields = splitList(draft.codeFields);
  return [
    "You are an expert academic research assistant and data coder. Read the paper thoroughly and code each independent experiment.",
    "Output the extracted data strictly as a JSON array of objects (one object per experiment).",
    "",
    "Study fields:",
    ...(lines.length ? lines : ["* (add fields to generate this section)"]),
    "",
    "Effect sizes: for every inferential dependent variable (DV) and every reported group contrast add a DV_Metrics array entry with at least one complete set of:",
    "full descriptives (n1i, m1i, sd1i, n2i, m2i, sd2i), (t_val, n1i, n2i), (F_val, df_num, df_den, n1i, n2i), (r_val, n_total), (yi, vi) or (yi, sei).",
    "Never leave a DV comparison without full descriptives or one complete fallback set; set missing numeric fields to null and note why in missing_metrics_reason.",
    ...(codeFields.length
      ? ["", `Also provide these qualitative fields as short strings or arrays: ${codeFields.join(", ")}.`]
      : []),
  ].join("\n");
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
  const [selectedFieldId, setSelectedFieldId] = useState<string | null>(null);
  const [newGroup, setNewGroup] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open) return;
    const next = schemes[0] ? draftFor(schemes[0]) : EMPTY;
    setDraft(next);
    setSelectedFieldId(next.fields[0]?.id ?? null);
    setPane(next.fields.length ? "field" : "prompts");
    // Reset only when the dialog opens — reloading the scheme list while the
    // editor is open must not discard in-progress edits.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const grouped = useMemo(() => {
    const map = new Map<string, SchemeField[]>();
    for (const group of draft.groups) map.set(group, []);
    for (const field of draft.fields) {
      const group = field.group || draft.groups[0] || "Study";
      if (!map.has(group)) map.set(group, []);
      map.get(group)!.push(field);
    }
    return [...map.entries()];
  }, [draft.groups, draft.fields]);

  const selectedField = draft.fields.find((f) => f.id === selectedFieldId) ?? null;

  const patchField = (id: string, patch: Partial<SchemeField>) =>
    setDraft((prev) => ({
      ...prev,
      fields: prev.fields.map((f) => (f.id === id ? { ...f, ...patch } : f)),
    }));

  const addField = (group: string) => {
    const field = fieldOf({ group }, group);
    setDraft((prev) => ({ ...prev, fields: [...prev.fields, field] }));
    setSelectedFieldId(field.id);
    setPane("field");
  };

  const removeField = (id: string) => {
    setDraft((prev) => ({ ...prev, fields: prev.fields.filter((f) => f.id !== id) }));
    if (selectedFieldId === id) setSelectedFieldId(null);
  };

  const moveField = (id: string, delta: number) => {
    setDraft((prev) => {
      const index = prev.fields.findIndex((f) => f.id === id);
      const target = index + delta;
      if (index < 0 || target < 0 || target >= prev.fields.length) return prev;
      const fields = [...prev.fields];
      [fields[index], fields[target]] = [fields[target], fields[index]];
      return { ...prev, fields };
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

  const optionRows = (id: string, options: string[]) => (
    <div className="space-y-1">
      {options.map((option, i) => (
        <div key={i} className="flex items-center gap-1">
          <Input
            value={option}
            onChange={(e) =>
              patchField(id, { options: options.map((o, j) => (j === i ? e.target.value : o)) })
            }
            className="h-7 min-w-0 flex-1 text-xs"
            aria-label={t("meta.optionPlaceholder")}
          />
          <IconButton
            label={t("common.delete")}
            size="row"
            onClick={() => patchField(id, { options: options.filter((_, j) => j !== i) })}
          >
            <Trash2 size={12} aria-hidden />
          </IconButton>
        </div>
      ))}
      <Button
        variant="secondary"
        icon={<Plus size={12} aria-hidden />}
        onClick={() => patchField(id, { options: [...options, ""] })}
      >
        {t("meta.addOption")}
      </Button>
    </div>
  );

  const openScheme = (id: number | null) => {
    if (id === null) {
      setDraft({ ...EMPTY, groups: [...EMPTY.groups] });
      setSelectedFieldId(null);
      setPane("prompts");
      return;
    }
    const found = schemes.find((s) => s.id === id);
    if (!found) return;
    const next = draftFor(found);
    setDraft(next);
    setSelectedFieldId(next.fields[0]?.id ?? null);
    setPane(next.fields.length ? "field" : "prompts");
  };

  const save = async () => {
    if (!draft.name.trim()) {
      toast.error(t("meta.schemeNameRequired"));
      return;
    }
    const studyFields = draft.fields.map((f) => ({
      name: f.name || slugifyName(f.label) || "field",
      label: f.label || f.name,
      group: f.group || draft.groups[0] || "Study",
      type: f.type,
      editor: f.editor,
      description: f.description,
      required: f.required,
      options: f.options.filter((o) => o.trim() !== ""),
    }));
    const body = {
      name: draft.name.trim(),
      label: draft.label || undefined,
      description: draft.description || undefined,
      prescreen_prompt: draft.prescreen,
      coding_prompt: draft.prompt,
      codebook: {
        category: draft.category || `Meta / ${draft.label || draft.name}`,
        groups: draft.groups,
        study_fields: studyFields,
        fields: studyFields,
        code_fields: splitList(draft.codeFields),
      },
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

  const showOptions = selectedField?.editor === "select" || selectedField?.type === "list";

  const fieldInput = (label: string, control: ReactNode) => (
    <label className="block min-w-0">
      <span className="mb-1 block text-[11px] text-text-secondary">{label}</span>
      {control}
    </label>
  );

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={t("meta.schemeEditor")}
      panelClassName="flex h-[86vh] w-[94vw] max-w-6xl flex-col"
    >
      <div className="flex min-h-0 flex-1">
        {/* ── left pane: scheme picker, meta, groups, field list ── */}
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
            <IconButton label={t("common.delete")} size="row" onClick={() => void remove()}>
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
                      <IconButton label={t("meta.addField")} size="sm" onClick={() => addField(group)}>
                        <Plus size={11} aria-hidden />
                      </IconButton>
                    </div>
                    <ul className="space-y-0.5">
                      {members.map((field) => (
                        <li key={field.id}>
                          <button
                            type="button"
                            onClick={() => {
                              setSelectedFieldId(field.id);
                              setPane("field");
                            }}
                            className={`flex w-full items-center gap-1 rounded-sm px-1.5 py-1 text-left text-xs qc-motion ${
                              selectedFieldId === field.id
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
                onClick={() => addField(draft.groups[0] ?? "Study")}
              >
                {t("meta.addField")}
              </Button>
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
              selectedField === null ? (
                <p className="text-xs text-text-secondary">{t("meta.selectField")}</p>
              ) : (
                <div className="space-y-3">
                  <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                    {fieldInput(
                      t("meta.fieldLabel"),
                      <Input
                        value={selectedField.label}
                        onChange={(e) => {
                          const label = e.target.value;
                          const auto = !selectedField.name || selectedField.name === slugifyName(selectedField.label);
                          patchField(selectedField.id, {
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
                        value={selectedField.name}
                        onChange={(e) => patchField(selectedField.id, { name: slugifyName(e.target.value) })}
                        className="h-7 w-full text-xs"
                      />,
                    )}
                    {fieldInput(
                      t("meta.fieldGroup"),
                      <Select
                        value={selectedField.group}
                        onChange={(e) => patchField(selectedField.id, { group: e.target.value })}
                        className="h-7 w-full text-xs"
                      >
                        {[...new Set([...draft.groups, selectedField.group].filter(Boolean))].map((g) => (
                          <option key={g} value={g}>
                            {g}
                          </option>
                        ))}
                      </Select>,
                    )}
                    {fieldInput(
                      t("meta.fieldType"),
                      <Select
                        value={selectedField.type}
                        onChange={(e) => patchField(selectedField.id, { type: e.target.value })}
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
                        value={selectedField.editor}
                        onChange={(e) => patchField(selectedField.id, { editor: e.target.value })}
                        className="h-7 w-full text-xs"
                      >
                        {EDITORS.map((ed) => (
                          <option key={ed} value={ed}>
                            {t(`meta.editor_${ed}`)}
                          </option>
                        ))}
                      </Select>,
                    )}
                    <div className="flex items-end">
                      <Toggle
                        checked={selectedField.required}
                        onChange={() =>
                          patchField(selectedField.id, { required: !selectedField.required })
                        }
                        label={t("meta.required")}
                      />
                    </div>
                  </div>

                  {fieldInput(
                    t("meta.fieldDescription"),
                    <Textarea
                      value={selectedField.description}
                      onChange={(e) => patchField(selectedField.id, { description: e.target.value })}
                      className="w-full text-xs"
                      rows={2}
                    />,
                  )}

                  {showOptions && (
                    <div className="rounded-sm border border-border p-2">
                      <p className="mb-1 text-[11px] text-text-secondary">{t("meta.fieldOptions")}</p>
                      {optionRows(selectedField.id, selectedField.options)}
                    </div>
                  )}

                  <div className="flex items-center gap-1 border-t border-border pt-3">
                    <IconButton
                      label={t("meta.moveUp")}
                      size="row"
                      onClick={() => moveField(selectedField.id, -1)}
                    >
                      <ChevronUp size={13} aria-hidden />
                    </IconButton>
                    <IconButton
                      label={t("meta.moveDown")}
                      size="row"
                      onClick={() => moveField(selectedField.id, 1)}
                    >
                      <ChevronDown size={13} aria-hidden />
                    </IconButton>
                    <span className="flex-1" />
                    <Button
                      variant="danger"
                      icon={<Trash2 size={12} aria-hidden />}
                      onClick={() => removeField(selectedField.id)}
                    >
                      {t("common.delete")}
                    </Button>
                  </div>
                </div>
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
