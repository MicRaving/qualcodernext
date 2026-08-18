/**
 * AiTemplateEditor — modal for managing user-defined instruction templates
 * (project-scoped ``ai_prompt`` rows). A list view shows the saved templates;
 * the edit view creates or updates one template's name, description and
 * prompt body.
 */
import { useEffect, useState } from "react";
import { Plus, Pencil, Trash2 } from "lucide-react";
import { api, type AiTemplateInfo } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { Button, Field, IconButton, Input, Modal, Textarea } from "@/components/ui/orchestrator";

export function AiTemplateEditor({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t } = useI18n();
  const [templates, setTemplates] = useState<AiTemplateInfo[]>([]);
  const [editing, setEditing] = useState<AiTemplateInfo | null>(null);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [text, setText] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!open) return;
    setEditing(null);
    setError("");
    api
      .aiTemplates()
      .then((res) => setTemplates(res.templates))
      .catch(() => setTemplates([]));
  }, [open]);

  function startNew() {
    setEditing({ id: 0, name: "", description: "", text: "", created: "", updated: "" });
    setName("");
    setDescription("");
    setText("");
    setError("");
  }

  function startEdit(template: AiTemplateInfo) {
    setEditing(template);
    setName(template.name);
    setDescription(template.description);
    setText(template.text);
    setError("");
  }

  async function save() {
    if (!name.trim() || !text.trim()) {
      setError(t("ai.templateValidation"));
      return;
    }
    setSaving(true);
    setError("");
    try {
      const body = { name: name.trim(), description: description.trim(), text };
      if (editing && editing.id > 0) {
        await api.aiTemplateUpdate(editing.id, body);
      } else {
        await api.aiTemplateCreate(body);
      }
      const res = await api.aiTemplates();
      setTemplates(res.templates);
      setEditing(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }

  async function remove(template: AiTemplateInfo) {
    try {
      await api.aiTemplateDelete(template.id);
      setTemplates((prev) => prev.filter((t) => t.id !== template.id));
    } catch {
      /* keep the row; the list reloads next time */
    }
  }

  return (
    <Modal open={open} onClose={onClose} title={t("ai.templatesTitle")} size="md">
      <div className="qc-scroll flex max-h-[70vh] min-h-0 flex-col gap-3 overflow-y-auto p-4">
        {error && <p className="text-xs text-danger">{error}</p>}
        {editing ? (
          <div className="flex min-w-0 flex-col gap-3">
            <Field label={t("ai.templateName")}>
              <Input value={name} onChange={(e) => setName(e.target.value)} aria-label={t("ai.templateName")} />
            </Field>
            <Field label={t("ai.templateDescription")}>
              <Input
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                aria-label={t("ai.templateDescription")}
              />
            </Field>
            <Field label={t("ai.templateText")}>
              <Textarea
                value={text}
                onChange={(e) => setText(e.target.value)}
                rows={10}
                className="min-h-0 w-full resize-y text-xs"
                aria-label={t("ai.templateText")}
              />
            </Field>
            <div className="flex items-center justify-end gap-2">
              <Button variant="secondary" onClick={() => setEditing(null)} disabled={saving}>
                {t("ai.templateCancel")}
              </Button>
              <Button variant="primary" onClick={() => void save()} disabled={saving}>
                {t("ai.templateSave")}
              </Button>
            </div>
          </div>
        ) : (
          <>
            <div className="flex items-center justify-between">
              <span className="text-xs text-text-secondary">{t("ai.templatesHint")}</span>
              <Button variant="primaryCompact" onClick={startNew} icon={<Plus size={14} aria-hidden />}>
                {t("ai.templateNew")}
              </Button>
            </div>
            {templates.length === 0 ? (
              <p className="py-4 text-center text-xs text-text-secondary">{t("ai.templatesEmpty")}</p>
            ) : (
              templates.map((template) => (
                <div
                  key={template.id}
                  className="flex min-w-0 items-center gap-2 rounded-sm border border-border bg-bg px-2 py-1.5"
                >
                  <button
                    type="button"
                    onClick={() => startEdit(template)}
                    className="flex min-w-0 flex-1 flex-col items-start gap-0.5 text-left hover:text-accent"
                  >
                    <span className="truncate text-xs font-medium text-text-primary">{template.name}</span>
                    {template.description && (
                      <span className="truncate text-[11px] text-text-secondary">{template.description}</span>
                    )}
                  </button>
                  <IconButton label={t("ai.templateEdit")} title={t("ai.templateEdit")} size="sm" onClick={() => startEdit(template)}>
                    <Pencil size={12} aria-hidden />
                  </IconButton>
                  <IconButton
                    label={t("ai.templateDelete")}
                    title={t("ai.templateDelete")}
                    size="sm"
                    className="text-danger"
                    onClick={() => void remove(template)}
                  >
                    <Trash2 size={12} aria-hidden />
                  </IconButton>
                </div>
              ))
            )}
          </>
        )}
      </div>
    </Modal>
  );
}