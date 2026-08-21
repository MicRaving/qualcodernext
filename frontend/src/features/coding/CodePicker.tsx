/**
 * CodePicker — modal for picking an existing code (or creating a new one)
 * before applying a text selection coding.
 *
 * Supports multi-select: single click codes + closes; Ctrl/Shift click
 * accumulates selection. On close (X, Escape, or single click) all
 * selected codes are applied.
 */
import { errorMessage, cn } from "@/lib/utils";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { LoaderCircle, Plus, Search, X } from "lucide-react";
import { api, type CodeTreeItem } from "@/lib/api";
import { FALLBACK_CODE_COLOR } from "@/features/coding/tint";
import { Button, IconButton, Input, MenuItem, Modal } from "@/components/ui/orchestrator";
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
  onPick: (codes: PickedCode[]) => void;
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
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const pendingPickRef = useRef<PickedCode[]>([]);

  useEffect(() => {
    if (open) {
      setQuery("");
      setNewName("");
      setError(null);
      setSelectedIds(new Set());
      pendingPickRef.current = [];
    }
  }, [open]);

  const codeItems = useMemo(() => {
    const q = query.trim().toLowerCase();
    return codes
      .filter((c) => c.kind === "code" && (q === "" || c.name.toLowerCase().includes(q)))
      .sort((a, b) => a.name.localeCompare(b.name));
  }, [codes, query]);

  const applySelection = useCallback(() => {
    const items: PickedCode[] = [];
    for (const id of selectedIds) {
      const c = codes.find((code) => code.id === id);
      if (c) items.push({ cid: c.id, name: c.name, color: c.color });
    }
    if (items.length > 0) {
      onPick(items);
    }
    setSelectedIds(new Set());
  }, [selectedIds, codes, onPick]);

  if (!open) return null;

  async function handleCreate() {
    const name = newName.trim();
    if (!name || busy) return;
    setBusy(true);
    setError(null);
    try {
      const res = await api.createCode(name);
      onPick([{ cid: res.cid, name, color: null }]);
    } catch (e) {
      setError(errorMessage(e, t("codePicker.createError")));
    } finally {
      setBusy(false);
    }
  }

  function handleCodeClick(c: CodeTreeItem, e: React.MouseEvent) {
    if (e.ctrlKey || e.metaKey || e.shiftKey) {
      // Multi-select: toggle in selection, keep flyout open
      e.preventDefault();
      setSelectedIds((prev) => {
        const next = new Set(prev);
        if (next.has(c.id)) next.delete(c.id);
        else next.add(c.id);
        return next;
      });
    } else {
      // Single click: code with that code and close flyout
      onPick([{ cid: c.id, name: c.name, color: c.color }]);
    }
  }

  return (
    <Modal open={open} onClose={() => { applySelection(); onClose(); }} size="sm" ariaLabel={t("codePicker.ariaTitle")}>
      <div className="flex items-center gap-2 border-b border-border px-3 py-2">
        <Search size={14} className="text-text-secondary" aria-hidden />
        <input
          autoFocus
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={t("codePicker.searchPlaceholder")}
          className="min-w-0 flex-1 bg-transparent text-sm text-text-primary outline-none placeholder:text-text-secondary"
        />
        {selectedIds.size > 0 && (
          <span className="text-[10px] text-accent">{selectedIds.size} selected</span>
        )}
        <IconButton label={t("common.close")} size="sm" onClick={() => { applySelection(); onClose(); }}>
          <X size={14} aria-hidden />
        </IconButton>
      </div>

      <ul className="max-h-64 overflow-y-auto p-1">
        {codeItems.length === 0 && (
          <li className="px-2 py-3 text-center text-sm text-text-secondary">
            {t("codePicker.noMatches")}
          </li>
        )}
        {codeItems.map((c) => {
          const path = categoryPath(codes, c);
          const isSelected = selectedIds.has(c.id);
          return (
            <li key={c.id}>
              <MenuItem
                className={cn("rounded-sm", isSelected && "bg-accent/10")}
                onClick={(e) => handleCodeClick(c, e)}
              >
                <span
                  className="h-3 w-3 shrink-0 rounded-sm border border-border"
                  style={{ backgroundColor: c.color ?? FALLBACK_CODE_COLOR }}
                  aria-hidden
                />
                <span className="truncate">{c.name}</span>
                {path && <span className="truncate text-xs text-text-secondary">{path}</span>}
              </MenuItem>
            </li>
          );
        })}
      </ul>

      <div className="border-t border-border p-2">
        <div className="flex items-center gap-1.5">
          <Input
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") void handleCreate();
            }}
            placeholder={t("codePicker.newNamePlaceholder")}
            className="min-w-0 flex-1"
          />
          <Button
            variant="primary"
            onClick={() => void handleCreate()}
            disabled={busy || newName.trim() === ""}
            icon={
              busy ? (
                <LoaderCircle size={12} className="animate-spin" aria-hidden />
              ) : (
                <Plus size={12} aria-hidden />
              )
            }
          >
            {t("codePicker.create")}
          </Button>
        </div>
        {error && <p className="mt-1.5 text-xs text-danger">{error}</p>}
      </div>
    </Modal>
  );
}
