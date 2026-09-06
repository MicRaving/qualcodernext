/**
 * PseudonymsMenu — project pseudonym editor as an app-themed dropdown in
 * the Files topbar (left of the broken-links button).
 *
 * Pseudonyms (original → replacement) anonymize names on file replacement
 * and survey import. They live in `pseudonyms.json` inside the project
 * folder, so they travel with the project — the menu edits them where the
 * data work happens instead of in Settings.
 *
 * Anchored-flyout pattern (relative wrapper, fixed Menu clamped to the
 * viewport, outside-click + Escape dismissal), mirroring CoderSwitcher.
 */
import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { Trash2, VenetianMask, X } from "lucide-react";
import { Button, IconButton, Input, Menu } from "@/components/ui/orchestrator";
import { useI18n } from "@/lib/i18n";
import { api, type Pseudonym } from "@/lib/api";
import { errorDetail } from "@/features/ai/format";

const FLYOUT_WIDTH = 320;
const FLYOUT_MARGIN = 8;
const FLYOUT_GAP = 4;
const FLYOUT_MIN_HEIGHT = 220;

export function PseudonymsMenu() {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const [pseudonyms, setPseudonyms] = useState<Pseudonym[]>([]);
  const [original, setOriginal] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const rootRef = useRef<HTMLDivElement>(null);
  const [viewportTick, setViewportTick] = useState(0);

  const reload = useCallback(async () => {
    try {
      const res = await api.pseudonyms();
      setPseudonyms(res.pseudonyms);
      setError(null);
    } catch (e) {
      setError(errorDetail(e, "Could not load pseudonyms"));
    }
  }, []);

  useEffect(() => {
    if (open) void reload();
  }, [open, reload]);

  // Outside-click + Escape dismissal while open.
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      const target = e.target instanceof Node ? e.target : null;
      if (target && !rootRef.current?.contains(target)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    window.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      window.removeEventListener("keydown", onKey);
    };
  }, [open ]);

  useEffect(() => {
    if (!open) return;
    const onResize = () => setViewportTick((n) => n + 1);
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, [open ]);

  // Anchored under the button, clamped inside the window (opens above
  // when there is no room below).
  const menuPos = useMemo(() => {
    const el = rootRef.current;
    if (!el) return undefined;
    const rect = el.getBoundingClientRect();
    const iw = window.innerWidth;
    const ih = window.innerHeight;
    const left = Math.max(
      FLYOUT_MARGIN,
      Math.min(rect.right - FLYOUT_WIDTH, iw - FLYOUT_WIDTH - FLYOUT_MARGIN),
    );
    const below = ih - rect.bottom - FLYOUT_GAP - FLYOUT_MARGIN;
    const above = rect.top - FLYOUT_GAP - FLYOUT_MARGIN;
    const openAbove = below < FLYOUT_MIN_HEIGHT && above > below;
    const maxHeight = Math.max(
      FLYOUT_MIN_HEIGHT,
      Math.min(ih - 2 * FLYOUT_MARGIN, openAbove ? above : below),
    );
    const top = openAbove
      ? Math.max(FLYOUT_MARGIN, rect.top - FLYOUT_GAP - maxHeight)
      : Math.min(rect.bottom + FLYOUT_GAP, ih - FLYOUT_MARGIN - maxHeight);
    return { left, top, maxHeight };
    // open + viewportTick are intentional recompute triggers.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, viewportTick]);

  async function addPseudonym(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await api.addPseudonym(original, name);
      setOriginal("");
      setName("");
      await reload();
    } catch (err) {
      setError(errorDetail(err, "Could not add pseudonym"));
    }
  }

  async function removePseudonym(target: string) {
    try {
      await api.deletePseudonym(target);
      await reload();
    } catch (err) {
      setError(errorDetail(err, "Could not delete pseudonym"));
    }
  }

  return (
    <div ref={rootRef} className="relative flex shrink-0 items-center">
      <IconButton
        label={t("ai.pseudonymsSection")}
        title={t("ai.pseudonymsSection")}
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-haspopup="menu"
      >
        <VenetianMask size={15} aria-hidden />
      </IconButton>

      {open && (
        <Menu
          position="fixed"
          role="menu"
          aria-label={t("ai.pseudonymsSection")}
          className="flex flex-col overflow-hidden"
          style={{ ...menuPos, width: FLYOUT_WIDTH }}
        >
          <div className="flex items-center gap-1 border-b border-border px-2 py-1">
            <span className="min-w-0 flex-1 text-xs font-medium text-text-secondary">
              {t("ai.pseudonymsSection")} ({pseudonyms.length})
            </span>
            <IconButton label={t("common.close")} size="sm" onClick={() => setOpen(false)}>
              <X size={13} aria-hidden />
            </IconButton>
          </div>
          <p className="px-2 pt-1.5 text-[11px] text-text-secondary">
            {t("ai.pseudonymsHint")}
          </p>
          <form onSubmit={(e) => void addPseudonym(e)} className="flex gap-1.5 px-2 py-1.5">
            <Input
              value={original}
              onChange={(e) => setOriginal(e.target.value)}
              placeholder={t("ai.pseudonymOriginalPlaceholder")}
              aria-label={t("ai.pseudonymOriginal")}
              className="min-w-0 flex-1"
            />
            <Input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={t("ai.pseudonymPseudonymPlaceholder")}
              aria-label={t("ai.pseudonymPseudonym")}
              className="min-w-0 flex-1"
            />
            <Button
              variant="primaryCompact"
              type="submit"
              disabled={original.trim().length < 2}
            >
              {t("ai.pseudonymAdd")}
            </Button>
          </form>
          {error && <p className="px-2 pb-1 text-xs text-danger">{error}</p>}
          {pseudonyms.length === 0 ? (
            <p className="px-2 pb-2 text-xs text-text-secondary">{t("ai.pseudonymNone")}</p>
          ) : (
            <div className="min-h-0 overflow-y-auto px-1 pb-1">
              {pseudonyms.map((p) => (
                <div
                  key={p.original}
                  className="flex items-center gap-1 rounded-sm px-1.5 py-1 hover:bg-surface-higher"
                >
                  <span className="min-w-0 flex-1 truncate text-xs">
                    {p.original}{" "}
                    <span className="text-text-secondary">→ {p.pseudonym}</span>
                  </span>
                  <IconButton
                    label={t("ai.pseudonymDelete")}
                    size="sm"
                    onClick={() => void removePseudonym(p.original)}
                    className="hover:bg-danger/10 hover:text-danger"
                  >
                    <Trash2 size={12} aria-hidden />
                  </IconButton>
                </div>
              ))}
            </div>
          )}
        </Menu>
      )}
    </div>
  );
}
