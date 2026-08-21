/**
 * AiTemplateEditor — modal for managing AI personas, editable instruction
 * templates and the chat wrapping prompt.
 *
 * Two tabs:
 * - Personas: the system prompt of every chat mode, editable and saved for
 *   all projects (Reset to default restores the shipped text). The wrapping
 *   prompt lives below — the machine-wide "be short and concise" directive.
 * - Templates: the full editable catalog. Built-in templates are edited via
 *   an app-wide override ("Save" writes it, "Reset to default" clears it);
 *   app-wide templates are stored in the settings and work in every project;
 *   project templates are the project's ``ai_prompt`` rows and can be copied
 *   to the app store with "Save globally".
 */
import { useEffect, useRef, useState } from "react";
import { Globe, Plus, Pencil, RotateCw, Trash2 } from "lucide-react";
import {
  api,
  type AiEditorTemplate,
  type AiPersonaInfo,
} from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import {
  Button,
  Field,
  IconButton,
  Input,
  Modal,
  Textarea,
} from "@/components/ui/orchestrator";

const PERSONA_MODE_LABELS: Record<string, string> = {
  general: "ai.modeGeneral",
  help: "ai.modeHelp",
  topic_exploration: "ai.modeTopic",
  code_analysis: "ai.modeCode",
  text_analysis: "ai.modeText",
  memo_analysis: "ai.modeMemos",
  sentiment: "ai.modeSentiment",
};

const SCOPE_LABELS: Record<AiEditorTemplate["scope"], string> = {
  builtin: "ai.templatesScopeBuiltin",
  app: "ai.templatesScopeApp",
  project: "ai.templatesScopeProject",
};

const GROUP_LABELS: Record<string, string> = {
  analysis: "ai.templatesGroupAnalysis",
  specialized: "ai.templatesGroupSpecialized",
  custom: "ai.templatesGroupCustom",
};

function groupLabel(group: string, t: (key: string) => string): string {
  return GROUP_LABELS[group] ? t(GROUP_LABELS[group]) : group;
}

export function AiTemplateEditor({
  open,
  onClose,
  onChanged,
}: {
  open: boolean;
  onClose: () => void;
  onChanged: () => void;
}) {
  const { t } = useI18n();
  const [tab, setTab] = useState<"personas" | "templates">("personas");

  // --- Personas ----------------------------------------------------------
  const [personas, setPersonas] = useState<AiPersonaInfo[]>([]);
  const [personaDrafts, setPersonaDrafts] = useState<Record<string, string>>({});
  const [savingPersona, setSavingPersona] = useState<string | null>(null);
  const [personaFlash, setPersonaFlash] = useState<Record<string, string>>({});
  const personaTimers = useRef<Record<string, number | undefined>>({});

  // --- Templates ---------------------------------------------------------
  const [templates, setTemplates] = useState<AiEditorTemplate[]>([]);
  const [editing, setEditing] = useState<AiEditorTemplate | "new" | "newGlobal" | null>(null);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [text, setText] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [flash, setFlash] = useState("");

  // --- Wrapping prompt ---------------------------------------------------
  const [wrappingPrompt, setWrappingPrompt] = useState("");
  const [wrappingDefault, setWrappingDefault] = useState("");
  const [savingWrapping, setSavingWrapping] = useState(false);
  const [wrappingError, setWrappingError] = useState("");
  const [wrappingSaved, setWrappingSaved] = useState(false);
  const wrappingTimer = useRef<number | undefined>(undefined);

  useEffect(() => {
    if (!open) return;
    setEditing(null);
    setError("");
    setFlash("");
    setTab("personas");
    void loadPersonas();
    void loadTemplates();
    api
      .aiWrappingPrompt()
      .then((res) => {
        setWrappingPrompt(res.text);
        setWrappingDefault(res.default);
      })
      .catch(() => {});
  }, [open]);

  useEffect(
    () => () => {
      window.clearTimeout(wrappingTimer.current);
      for (const timer of Object.values(personaTimers.current)) {
        window.clearTimeout(timer);
      }
    },
    [],
  );

  async function loadPersonas() {
    try {
      const res = await api.aiPersonas();
      setPersonas(res.personas);
      const drafts: Record<string, string> = {};
      for (const p of res.personas) drafts[p.mode] = p.text;
      setPersonaDrafts(drafts);
    } catch {
      setPersonas([]);
    }
  }

  async function loadTemplates() {
    try {
      const res = await api.aiTemplatesAll();
      setTemplates(res.templates);
    } catch {
      setTemplates([]);
    }
  }

  function flashPersona(mode: string, key: string) {
    setPersonaFlash((prev) => ({ ...prev, [mode]: key }));
    window.clearTimeout(personaTimers.current[mode]);
    personaTimers.current[mode] = window.setTimeout(() => {
      setPersonaFlash((prev) => {
        const next = { ...prev };
        delete next[mode];
        return next;
      });
    }, 2000);
  }

  async function savePersona(mode: string) {
    if (savingPersona) return;
    setSavingPersona(mode);
    try {
      const draft = (personaDrafts[mode] ?? "").trim();
      await api.aiSavePersonas({ [mode]: draft });
      flashPersona(mode, "ai.personasSaved");
      setPersonas((prev) =>
        prev.map((p) =>
          p.mode === mode ? { ...p, text: draft || p.default } : p,
        ),
      );
    } catch {
      /* keep the draft; the reload next open shows the stored value */
    } finally {
      setSavingPersona(null);
    }
  }

  async function resetPersona(mode: string) {
    if (savingPersona) return;
    const persona = personas.find((p) => p.mode === mode);
    if (!persona) return;
    setPersonaDrafts((prev) => ({ ...prev, [mode]: persona.default }));
    setSavingPersona(mode);
    try {
      await api.aiSavePersonas({ [mode]: "" });
      flashPersona(mode, "ai.personasSaved");
      setPersonas((prev) =>
        prev.map((p) => (p.mode === mode ? { ...p, text: p.default } : p)),
      );
    } catch {
      /* keep the draft */
    } finally {
      setSavingPersona(null);
    }
  }

  function startNew(global: boolean) {
    setEditing(global ? "newGlobal" : "new");
    setName("");
    setDescription("");
    setText("");
    setError("");
  }

  function startEdit(template: AiEditorTemplate) {
    setEditing(template);
    setName(template.name);
    setDescription(template.description);
    setText(template.text);
    setError("");
  }

  async function save() {
    if (!name.trim() || !text.trim()) {
      setError(t("ai.templatesValidation"));
      return;
    }
    setSaving(true);
    setError("");
    try {
      if (editing === "new") {
        await api.aiTemplateCreate({ name: name.trim(), description: description.trim(), text });
      } else if (editing === "newGlobal") {
        await api.aiTemplateGlobalCreate({ name: name.trim(), description: description.trim(), text });
      } else if (editing) {
        await api.aiTemplateSaveAll({
          id: editing.id,
          name: name.trim(),
          description: description.trim(),
          text,
        });
      }
      await loadTemplates();
      setEditing(null);
      setFlash(editing === "newGlobal" ? "ai.templatesSavedGlobal" : "ai.wrappingSaved");
      window.setTimeout(() => setFlash(""), 2000);
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }

  async function resetBuiltin(template: AiEditorTemplate) {
    if (saving) return;
    setSaving(true);
    setError("");
    try {
      await api.aiTemplateReset(template.id);
      await loadTemplates();
      setEditing(null);
      setFlash("ai.templatesResetDone");
      window.setTimeout(() => setFlash(""), 2000);
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }

  async function remove(template: AiEditorTemplate) {
    try {
      if (template.scope === "project") {
        const rowId = Number(template.id.replace("custom:", ""));
        await api.aiTemplateDelete(rowId);
      } else if (template.scope === "app") {
        await api.aiTemplateGlobalDelete(template.id.replace("global:", ""));
      }
      await loadTemplates();
      onChanged();
    } catch {
      /* keep the row; the list reloads next time */
    }
  }

  async function saveGlobally(template: AiEditorTemplate) {
    try {
      await api.aiTemplateGlobalCreate({
        name: template.name,
        description: template.description,
        text: template.text,
      });
      await loadTemplates();
      setFlash("ai.templatesSavedGlobal");
      window.setTimeout(() => setFlash(""), 2000);
      onChanged();
    } catch {
      /* keep the row */
    }
  }

  async function saveWrappingTo(target: string) {
    if (savingWrapping) return;
    setSavingWrapping(true);
    setWrappingError("");
    try {
      const res = await api.aiSaveWrappingPrompt(target);
      setWrappingPrompt(res.text);
      setWrappingDefault(res.default);
      setWrappingSaved(true);
      window.clearTimeout(wrappingTimer.current);
      wrappingTimer.current = window.setTimeout(() => setWrappingSaved(false), 2000);
    } catch (e) {
      setWrappingError(e instanceof Error ? e.message : String(e));
    } finally {
      setSavingWrapping(false);
    }
  }

  function saveWrapping() {
    void saveWrappingTo(wrappingPrompt);
  }

  function resetWrapping() {
    if (savingWrapping) return;
    setWrappingError("");
    setWrappingPrompt(wrappingDefault);
    void saveWrappingTo(wrappingDefault);
  }

  const grouped = (scope: AiEditorTemplate["scope"]) => templates.filter((t) => t.scope === scope);
  const builtins = grouped("builtin");
  const appTemplates = grouped("app");
  const projectTemplates = grouped("project");

  return (
    <Modal open={open} onClose={onClose} title={t("ai.templatesTitle")} size="md">
      <div className="qc-scroll flex max-h-[70vh] min-h-0 flex-col gap-3 overflow-y-auto p-4">
        <div className="flex items-center gap-1 border-b border-border pb-2">
          <button
            type="button"
            onClick={() => setTab("personas")}
            className={`rounded-sm px-2.5 py-1 text-xs font-medium ${
              tab === "personas" ? "bg-surface-higher text-text-primary" : "text-text-secondary hover:text-text-primary"
            }`}
          >
            {t("ai.editorPersonasTab")}
          </button>
          <button
            type="button"
            onClick={() => setTab("templates")}
            className={`rounded-sm px-2.5 py-1 text-xs font-medium ${
              tab === "templates" ? "bg-surface-higher text-text-primary" : "text-text-secondary hover:text-text-primary"
            }`}
          >
            {t("ai.editorTemplatesTab")}
          </button>
        </div>

        {tab === "personas" ? (
          <>
            <p className="text-xs text-text-secondary">{t("ai.personasHint")}</p>
            {personas.map((persona) => (
              <div
                key={persona.mode}
                className="flex min-w-0 flex-col gap-1.5 rounded-sm border border-border bg-bg p-2"
              >
                <div className="flex items-center gap-2">
                  <span className="min-w-0 flex-1 truncate text-xs font-semibold text-text-primary">
                    {t(PERSONA_MODE_LABELS[persona.mode] ?? "ai.modeGeneral")}
                  </span>
                  <Button
                    variant="secondary"
                    onClick={() => void resetPersona(persona.mode)}
                    disabled={savingPersona === persona.mode}
                    icon={<RotateCw size={11} aria-hidden />}
                    title={t("ai.personasReset")}
                  >
                    {t("ai.personasReset")}
                  </Button>
                  <Button
                    variant="primary"
                    onClick={() => void savePersona(persona.mode)}
                    disabled={savingPersona === persona.mode}
                  >
                    {t("ai.templatesSave")}
                  </Button>
                  {personaFlash[persona.mode] && (
                    <span className="text-xs text-success">{t(personaFlash[persona.mode])}</span>
                  )}
                </div>
                <Textarea
                  value={personaDrafts[persona.mode] ?? persona.text}
                  onChange={(e) =>
                    setPersonaDrafts((prev) => ({ ...prev, [persona.mode]: e.target.value }))
                  }
                  rows={3}
                  className="w-full resize-y text-xs"
                  aria-label={t(PERSONA_MODE_LABELS[persona.mode] ?? "ai.modeGeneral")}
                />
              </div>
            ))}

            {/* Wrapping prompt — the system-level directive appended to every
                chat turn ("be short and concise" by default). */}
            <div className="border-t border-border pt-3">
              <h3 className="text-sm font-semibold text-text-primary">{t("ai.wrappingTitle")}</h3>
              <p className="mt-1 text-xs leading-relaxed text-text-secondary">{t("ai.wrappingHint")}</p>
              <Textarea
                value={wrappingPrompt}
                onChange={(e) => setWrappingPrompt(e.target.value)}
                rows={3}
                className="mt-2 w-full resize-y text-xs"
                aria-label={t("ai.wrappingTitle")}
              />
              <div className="mt-2 flex items-center gap-2">
                <Button
                  variant="secondary"
                  onClick={resetWrapping}
                  disabled={savingWrapping}
                  icon={<RotateCw size={12} aria-hidden />}
                >
                  {t("ai.wrappingReset")}
                </Button>
                <Button variant="primary" onClick={() => void saveWrapping()} disabled={savingWrapping}>
                  {t("ai.wrappingSave")}
                </Button>
                {wrappingSaved && <span className="text-xs text-success">{t("ai.wrappingSaved")}</span>}
                {wrappingError && <span className="text-xs text-danger">{wrappingError}</span>}
              </div>
            </div>
          </>
        ) : editing ? (
          <div className="flex min-w-0 flex-col gap-3">
            {editing !== "new" && editing !== "newGlobal" && (
              <div className="flex items-center gap-2 text-[11px] text-text-secondary">
                <span className="rounded-sm border border-border px-1.5 py-0.5">
                  {t(SCOPE_LABELS[editing.scope])}
                </span>
                <span className="rounded-sm border border-border px-1.5 py-0.5">
                  {groupLabel(editing.group, t)}
                </span>
              </div>
            )}
            <Field label={t("ai.templatesName")}>
              <Input value={name} onChange={(e) => setName(e.target.value)} aria-label={t("ai.templatesName")} />
            </Field>
            <Field label={t("ai.templatesDescription")}>
              <Input
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                aria-label={t("ai.templatesDescription")}
              />
            </Field>
            <Field label={t("ai.templatesText")}>
              <Textarea
                value={text}
                onChange={(e) => setText(e.target.value)}
                rows={10}
                className="min-h-0 w-full resize-y text-xs"
                aria-label={t("ai.templatesText")}
              />
            </Field>
            <div className="flex items-center justify-end gap-2">
              {editing !== "new" && editing !== "newGlobal" && editing.scope === "builtin" && (
                <Button
                  variant="secondary"
                  onClick={() => void resetBuiltin(editing)}
                  disabled={saving}
                  icon={<RotateCw size={12} aria-hidden />}
                  title={t("ai.templatesResetDefaultHint")}
                >
                  {t("ai.templatesResetDefault")}
                </Button>
              )}
              <Button variant="secondary" onClick={() => setEditing(null)} disabled={saving}>
                {t("ai.templatesCancel")}
              </Button>
              <Button variant="primary" onClick={() => void save()} disabled={saving}>
                {t("ai.templatesSave")}
              </Button>
            </div>
          </div>
        ) : (
          <>
            {error && <p className="text-xs text-danger">{error}</p>}
            <div className="flex items-center justify-between gap-2">
              <span className="min-w-0 text-xs text-text-secondary">{t("ai.templatesAllHint")}</span>
              <div className="flex shrink-0 items-center gap-1.5">
                <Button
                  variant="primaryCompact"
                  onClick={() => startNew(true)}
                  icon={<Globe size={14} aria-hidden />}
                  title={t("ai.templatesSaveGlobalHint")}
                >
                  {t("ai.templatesNewGlobal")}
                </Button>
                <Button variant="primaryCompact" onClick={() => startNew(false)} icon={<Plus size={14} aria-hidden />}>
                  {t("ai.templatesNew")}
                </Button>
              </div>
            </div>
            {flash && <p className="text-xs text-success">{t(flash)}</p>}
            {templates.length === 0 ? (
              <p className="py-4 text-center text-xs text-text-secondary">{t("ai.templatesEmpty")}</p>
            ) : (
              <div className="flex min-w-0 flex-col gap-2">
                {builtins.length > 0 && (
                  <TemplateSection
                    label={t("ai.templatesGroupAnalysis")}
                    templates={builtins}
                    onEdit={startEdit}
                    onRemove={remove}
                    onSaveGlobally={saveGlobally}
                    t={t}
                  />
                )}
                {appTemplates.length > 0 && (
                  <TemplateSection
                    label={t("ai.templatesGroupCustom")}
                    templates={appTemplates}
                    onEdit={startEdit}
                    onRemove={remove}
                    onSaveGlobally={saveGlobally}
                    t={t}
                  />
                )}
                {projectTemplates.length > 0 && (
                  <TemplateSection
                    label={`${t("ai.templatesGroupCustom")} · ${t("ai.templatesScopeProject")}`}
                    templates={projectTemplates}
                    onEdit={startEdit}
                    onRemove={remove}
                    onSaveGlobally={saveGlobally}
                    t={t}
                  />
                )}
              </div>
            )}
          </>
        )}
      </div>
    </Modal>
  );
}

function TemplateSection({
  label,
  templates,
  onEdit,
  onRemove,
  onSaveGlobally,
  t,
}: {
  label: string;
  templates: AiEditorTemplate[];
  onEdit: (template: AiEditorTemplate) => void;
  onRemove: (template: AiEditorTemplate) => void;
  onSaveGlobally: (template: AiEditorTemplate) => void;
  t: (key: string) => string;
}) {
  return (
    <div className="flex min-w-0 flex-col gap-1">
      <span className="px-1 text-[11px] font-semibold uppercase tracking-wide text-text-secondary">{label}</span>
      {templates.map((template) => (
        <div
          key={template.id}
          className="flex min-w-0 items-center gap-2 rounded-sm border border-border bg-bg px-2 py-1.5"
        >
          <span
            className="shrink-0 rounded-sm border border-border px-1.5 py-0.5 text-[10px]"
            title={t(SCOPE_LABELS[template.scope])}
          >
            {t(SCOPE_LABELS[template.scope])}
          </span>
          <button
            type="button"
            onClick={() => onEdit(template)}
            className="flex min-w-0 flex-1 flex-col items-start gap-0.5 text-left hover:text-accent"
          >
            <span className="truncate text-xs font-medium text-text-primary">{template.name}</span>
            {template.description && (
              <span className="truncate text-[11px] text-text-secondary">{template.description}</span>
            )}
          </button>
          {template.scope === "project" && (
            <IconButton
              label={t("ai.templatesSaveGlobal")}
              title={t("ai.templatesSaveGlobalHint")}
              size="sm"
              onClick={() => onSaveGlobally(template)}
            >
              <Globe size={12} aria-hidden />
            </IconButton>
          )}
          <IconButton label={t("ai.templatesEdit")} title={t("ai.templatesEdit")} size="sm" onClick={() => onEdit(template)}>
            <Pencil size={12} aria-hidden />
          </IconButton>
          {template.scope !== "builtin" && (
            <IconButton
              label={t("ai.templatesDelete")}
              title={t("ai.templatesDelete")}
              size="sm"
              className="text-danger"
              onClick={() => onRemove(template)}
            >
              <Trash2 size={12} aria-hidden />
            </IconButton>
          )}
        </div>
      ))}
    </div>
  );
}