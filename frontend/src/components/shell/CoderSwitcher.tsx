/**
 * CoderSwitcher — shows the current coder; the dropdown switches coders or
 * adds a new one with an inline name input (fully self-contained, no
 * window.prompt). Managing/deleting lives in Settings → Coders.
 */
import { useEffect, useRef, useState } from "react";
import { Check, ChevronDown, Eye, EyeOff, User, UserPlus, X } from "lucide-react";
import { api } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { useProjectStore } from "@/stores/project";

export function CoderSwitcher() {
  const { t } = useI18n();
  const coderName = useProjectStore((s) => s.coderName);
  const coders = useProjectStore((s) => s.coders);
  const switchCoder = useProjectStore((s) => s.switchCoder);
  const createCoder = useProjectStore((s) => s.createCoder);
  const [open, setOpen] = useState(false);
  const [adding, setAdding] = useState(false);
  const [newName, setNewName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [visibility, setVisibility] = useState<Record<string, number>>({});
  const rootRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    if (!open) return;
    void api
      .coderVisibility()
      .then((res) => setVisibility(res.visibility))
      .catch(() => setVisibility({}));
    const onDown = (e: MouseEvent) => {
      const target = e.target instanceof Node ? e.target : null;
      if (target && !rootRef.current?.contains(target)) {
        setOpen(false);
        setAdding(false);
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setOpen(false);
        setAdding(false);
      }
    };
    document.addEventListener("mousedown", onDown);
    window.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      window.removeEventListener("keydown", onKey);
    };
  }, [open]);

  useEffect(() => {
    if (adding) inputRef.current?.focus();
  }, [adding]);

  async function toggleVisibility(name: string) {
    const next = (visibility[name] ?? 1) === 1 ? 0 : 1;
    try {
      await api.setCoderVisibility(name, next === 1);
      setVisibility((v) => ({ ...v, [name]: next }));
    } catch {
      setError(t("coder.visibilityHint"));
    }
  }

  async function confirmAdd() {
    const name = newName.trim();
    if (!name) return;
    setError(null);
    const ok = await createCoder(name);
    if (!ok) {
      setError(t("coder.addFailed"));
      return;
    }
    await switchCoder(name);
    setAdding(false);
    setNewName("");
  }

  function closeAll() {
    setOpen(false);
    setAdding(false);
  }

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={t("coder.switchAria", { name: coderName })}
        title={t("coder.switchTitle")}
        className="flex max-w-40 items-center gap-1.5 rounded-sm border border-border bg-bg px-2 py-1 text-xs hover:bg-surface-higher"
      >
        <User size={12} className="shrink-0 text-text-secondary" aria-hidden />
        <span className="truncate">{coderName}</span>
        <ChevronDown size={12} className="shrink-0 text-text-secondary" aria-hidden />
      </button>

      {open && (
        <div
          role="listbox"
          aria-label={t("coder.listAria")}
          className="absolute right-0 top-full z-50 mt-1 min-w-56 rounded-md border border-border bg-surface py-1 shadow-lg"
        >
          {coders.map((c) => (
            <div
              key={c.name}
              role="option"
              aria-selected={c.name === coderName}
              className={`flex w-full items-center gap-2 px-2 py-1.5 text-left text-sm hover:bg-surface-higher ${
                c.name === coderName ? "text-accent" : ""
              }`}
            >
              <button
                type="button"
                onClick={() => {
                  if (c.name !== coderName) void switchCoder(c.name);
                  closeAll();
                }}
                className="flex min-w-0 flex-1 items-center gap-2"
              >
                <User size={13} aria-hidden />
                <span className="truncate">{c.name}</span>
                {c.coding_count > 0 && (
                  <span className="ml-auto text-xs text-text-secondary">{c.coding_count}</span>
                )}
              </button>
              <button
                type="button"
                title={t((visibility[c.name] ?? 1) === 1 ? "coder.hide" : "coder.show")}
                aria-label={t((visibility[c.name] ?? 1) === 1 ? "coder.hide" : "coder.show")}
                onClick={(e) => {
                  e.stopPropagation();
                  void toggleVisibility(c.name);
                }}
                className={`shrink-0 rounded-sm p-1 hover:bg-surface-higher ${
                  (visibility[c.name] ?? 1) === 1
                    ? "text-text-secondary"
                    : "text-danger"
                }`}
              >
                {(visibility[c.name] ?? 1) === 1 ? (
                  <Eye size={13} aria-hidden />
                ) : (
                  <EyeOff size={13} aria-hidden />
                )}
              </button>
            </div>
          ))}
          <div className="my-1 h-px bg-border" aria-hidden />
          {adding ? (
            <div className="px-2 py-1.5">
              <div className="flex items-center gap-1">
                <input
                  ref={inputRef}
                  type="text"
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") void confirmAdd();
                  }}
                  placeholder={t("coder.newNamePlaceholder")}
                  aria-label={t("coder.newNamePlaceholder")}
                  className="w-full min-w-0 flex-1 rounded-sm border border-border bg-bg px-2 py-1 text-sm outline-none focus:border-accent"
                />
                <button
                  type="button"
                  onClick={() => void confirmAdd()}
                  disabled={!newName.trim()}
                  aria-label={t("coder.confirmAdd")}
                  className="shrink-0 rounded-sm bg-accent p-1 text-[var(--qc-bg)] hover:bg-accent-hover disabled:opacity-40"
                >
                  <Check size={13} aria-hidden />
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setAdding(false);
                    setNewName("");
                    setError(null);
                  }}
                  aria-label={t("common.cancel")}
                  className="shrink-0 rounded-sm border border-border bg-bg p-1 text-text-secondary hover:bg-surface-higher"
                >
                  <X size={13} aria-hidden />
                </button>
              </div>
              {error && <p className="mt-1 text-xs text-danger">{error}</p>}
            </div>
          ) : (
            <button
              type="button"
              onClick={() => {
                setAdding(true);
                setError(null);
              }}
              className="flex w-full items-center gap-2 px-2 py-1.5 text-left text-sm hover:bg-surface-higher"
            >
              <UserPlus size={13} aria-hidden />
              {t("coder.addNew")}
            </button>
          )}
        </div>
      )}
    </div>
  );
}
