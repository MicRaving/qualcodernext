/**
 * AttributeEditor — editable property grid for an entity (case or file).
 * Rows come from the entity's existing values plus the scope's attribute
 * types that have no value yet; saving writes the value.
 */
import { useCallback, useEffect, useState } from "react";
import { Check, LoaderCircle, Plus, X } from "lucide-react";
import { api } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { IconButton, Input, SectionLabel } from "@/components/ui/orchestrator";

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
  const [types, setTypes] = useState<{ name: string }[]>([]);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [newName, setNewName] = useState("");

  const reload = useCallback(async () => {
    try {
      const list = await api.attributeTypes();
      const scopeTypes = list.filter((ty) => ty.case_or_file === scope);
      setTypes(scopeTypes.map((ty) => ({ name: ty.name })));
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
      setError(e instanceof Error ? e.message : t("inspector.attributesSaveError"));
    } finally {
      setSaving(null);
    }
  }

  async function createType() {
    const name = newName.trim();
    if (!name) return;
    setError(null);
    try {
      await api.createAttributeType(name, scope, "text");
      setAdding(false);
      setNewName("");
      await reload();
      await onChange();
    } catch (e) {
      setError(e instanceof Error ? e.message : t("inspector.attributesSaveError"));
    }
  }

  return (
    <div>
      <div className="mb-1 flex items-center justify-between">
        <SectionLabel>{t("inspector.attributes")}</SectionLabel>
        <IconButton
          label={t("inspector.attributesAddType")}
          title={t("inspector.attributesAddType")}
          size="sm"
          onClick={() => {
            setAdding((a) => !a);
            setNewName("");
          }}
        >
          <Plus size={12} aria-hidden />
        </IconButton>
      </div>
      {adding && (
        <div className="mb-2 flex items-center gap-1.5">
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
          <IconButton
            label={t("common.rename")}
            title={t("inspector.attributesAddType")}
            size="md"
            disabled={!newName.trim()}
            onClick={() => void createType()}
          >
            <Check size={14} aria-hidden />
          </IconButton>
          <IconButton
            label={t("common.cancel")}
            title={t("common.cancel")}
            size="md"
            onClick={() => setAdding(false)}
          >
            <X size={14} aria-hidden />
          </IconButton>
        </div>
      )}
      {types.length === 0 ? (
        <p className="text-sm text-text-secondary">{t("inspector.noAttributes")}</p>
      ) : (
        <div className="flex flex-col gap-1.5">
          {types.map((ty) => (
            <label key={ty.name} className="flex items-center gap-2 text-xs">
              <span className="w-28 shrink-0 truncate text-text-secondary" title={ty.name}>
                {ty.name}
              </span>
              <input
                type="text"
                value={drafts[ty.name] ?? ""}
                onChange={(e) => setDrafts((d) => ({ ...d, [ty.name]: e.target.value }))}
                onBlur={(e) => void save(ty.name, e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") void save(ty.name, e.currentTarget.value);
                }}
                aria-label={ty.name}
                className="min-w-0 flex-1 rounded-sm border border-border bg-bg px-1.5 py-1 text-sm outline-none focus:border-accent"
              />
              {saving === ty.name && (
                <LoaderCircle size={12} className="animate-spin text-text-secondary" aria-hidden />
              )}
            </label>
          ))}
        </div>
      )}
      {error && <p className="mt-1 text-xs text-danger">{error}</p>}
    </div>
  );
}
