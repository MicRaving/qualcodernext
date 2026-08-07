/**
 * CodePicker — modal for picking an existing code (or creating a new one)
 * before applying a text selection coding.
 */
import { useEffect, useMemo, useState } from "react";
import { LoaderCircle, Plus, Search, X } from "lucide-react";
import { api, type CodeTreeItem } from "@/lib/api";
import { cn } from "@/lib/utils";
import { useI18n } from "@/lib/i18n";

export interface PickedCode {
  cid: number;
  name: string;
  color: string | null;
}

interface CodePickerProps {
  open: boolean;
  codes: CodeTreeItem[];
  onClose: () => void;
  onPick: (code: PickedCode) => void;
}

/** Breadcrumb path of categories leading to a code, e.g. "Interviews / Core". */
function categoryPath(codes: CodeTreeItem[], item: CodeTreeItem): string {
  const byId = new Map(codes.map((c) => [c.id, c]));
  const parts: string[] = [];
  let parent = item.parent_id;
  let guard = 0;
  while (parent != null && guard < 20) {
    const p = byId.get(parent);
    if (!p || p.kind !== "category") break;
    parts.unshift(p.name);
    parent = p.parent_id;
    guard += 1;
  }
  return parts.join(" / ");
}

export function CodePicker({ open, codes, onClose, onPick }: CodePickerProps) {
  const { t } = useI18n();
  const [query, setQuery] = useState("");
  const [newName, setNewName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  useEffect(() => {
    if (open) {
      setQuery("");
      setNewName("");
      setError(null);
    }
  }, [open]);

  const codeItems = useMemo(() => {
    const q = query.trim().toLowerCase();
    return codes
      .filter((c) => c.kind === "code" && (q === "" || c.name.toLowerCase().includes(q)))
      .sort((a, b) => a.name.localeCompare(b.name));
  }, [codes, query]);

  if (!open) return null;

  async function handleCreate() {
    const name = newName.trim();
    if (!name || busy) return;
    setBusy(true);
    setError(null);
    try {
      const res = await api.createCode(name);
      onPick({ cid: res.cid, name, color: null });
    } catch (e) {
      setError(e instanceof Error ? e.message : t("codePicker.createError"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-bg/70"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
      role="dialog"
      aria-modal="true"
      aria-label={t("codePicker.ariaTitle")}
    >
      <div className="w-80 max-w-[90vw] rounded-lg border border-border bg-surface shadow-xl">
        <div className="flex items-center gap-2 border-b border-border px-3 py-2">
          <Search size={14} className="text-text-secondary" aria-hidden />
          <input
            autoFocus
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t("codePicker.searchPlaceholder")}
            className="min-w-0 flex-1 bg-transparent text-sm text-text-primary outline-none placeholder:text-text-secondary"
          />
          <button
            type="button"
            onClick={onClose}
            aria-label={t("common.close")}
            className="rounded-sm p-1 text-text-secondary hover:bg-surface-higher hover:text-text-primary"
          >
            <X size={14} aria-hidden />
          </button>
        </div>

        <ul className="max-h-64 overflow-y-auto p-1">
          {codeItems.length === 0 && (
            <li className="px-2 py-3 text-center text-sm text-text-secondary">
              {t("codePicker.noMatches")}
            </li>
          )}
          {codeItems.map((c) => {
            const path = categoryPath(codes, c);
            return (
              <li key={c.id}>
                <button
                  type="button"
                  onClick={() => onPick({ cid: c.id, name: c.name, color: c.color })}
                  className="flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-left text-sm hover:bg-surface-higher"
                >
                  <span
                    className="h-3 w-3 shrink-0 rounded-sm border border-border"
                    style={{ backgroundColor: c.color ?? "var(--qc-accent)" }}
                    aria-hidden
                  />
                  <span className="truncate">{c.name}</span>
                  {path && <span className="truncate text-xs text-text-secondary">{path}</span>}
                </button>
              </li>
            );
          })}
        </ul>

        <div className="border-t border-border p-2">
          <div className="flex items-center gap-1.5">
            <input
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") void handleCreate();
              }}
              placeholder={t("codePicker.newNamePlaceholder")}
              className="min-w-0 flex-1 rounded-sm border border-border bg-bg px-2 py-1 text-sm outline-none focus:border-accent"
            />
            <button
              type="button"
              onClick={() => void handleCreate()}
              disabled={busy || newName.trim() === ""}
              className="flex shrink-0 items-center gap-1 rounded-sm bg-accent px-2 py-1 text-xs font-medium text-[var(--qc-bg)] hover:bg-accent-hover disabled:opacity-50"
            >
              {busy ? (
                <LoaderCircle size={12} className="animate-spin" aria-hidden />
              ) : (
                <Plus size={12} aria-hidden />
              )}
              {t("codePicker.create")}
            </button>
          </div>
          {error && <p className={cn("mt-1.5 text-xs text-danger")}>{error}</p>}
        </div>
      </div>
    </div>
  );
}
