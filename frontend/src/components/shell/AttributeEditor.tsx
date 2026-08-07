/**
 * AttributeEditor — editable property grid for an entity (case or file).
 * Rows come from the entity's existing values plus the scope's attribute
 * types that have no value yet; saving writes the value.
 */
import { useCallback, useEffect, useState } from "react";
import { LoaderCircle, Plus } from "lucide-react";
import { api } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div className="mb-1 text-xs font-medium uppercase tracking-wide text-text-secondary">
      {children}
    </div>
  );
}

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

  return (
    <div>
      <div className="mb-1 flex items-center justify-between">
        <SectionLabel>{t("inspector.attributes")}</SectionLabel>
        <button
          type="button"
          onClick={() => {
            const name = window.prompt(t("inspector.attributesAddType"));
            if (!name?.trim()) return;
            void (async () => {
              try {
                await api.createAttributeType(name.trim(), scope, "text");
                await reload();
                await onChange();
              } catch (e) {
                setError(e instanceof Error ? e.message : t("inspector.attributesSaveError"));
              }
            })();
          }}
          aria-label={t("inspector.attributesAddType")}
          title={t("inspector.attributesAddType")}
          className="rounded-sm p-1 text-text-secondary hover:bg-surface-higher hover:text-text-primary"
        >
          <Plus size={12} aria-hidden />
        </button>
      </div>
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
