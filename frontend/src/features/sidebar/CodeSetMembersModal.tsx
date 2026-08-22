/**
 * CodeSetMembersModal — membership editor: every code of the project with a
 * checkbox for the active set. Saving syncs the diff (add + remove) through
 * the API. Extracted from components/shell/Sidebar.tsx — behavior-neutral.
 */
import { useEffect, useState } from "react";
import { Check, CircleAlert, LoaderCircle, SlidersHorizontal } from "lucide-react";
import { Button, Modal } from "@/components/ui/orchestrator";
import { errorMessage } from "@/lib/utils";
import type { CodeSetSummary } from "@/lib/codeSetsApi";

export interface CodeSetOption {
  cid: number;
  label: string;
  color: string | null;
}

export function CodeSetMembersModal({
  open,
  set,
  members,
  codes,
  onClose,
  onSave,
  t,
}: {
  open: boolean;
  set: CodeSetSummary | null;
  members: Set<number> | null;
  codes: CodeSetOption[];
  onClose: () => void;
  onSave: (cids: number[]) => Promise<void>;
  t: (key: string, params?: Record<string, string | number>) => string;
}) {
  const [draft, setDraft] = useState<Set<number>>(new Set());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (open && members) setDraft(new Set(members));
  }, [open, members]);

  const toggle = (cid: number) => {
    setDraft((prev) => {
      const next = new Set(prev);
      if (next.has(cid)) next.delete(cid);
      else next.add(cid);
      return next;
    });
  };

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      await onSave([...draft]);
    } catch (e) {
      setError(errorMessage(e, t("codeSets.membersSaveError")));
      setBusy(false);
    }
  };

  return (
    <Modal
      open={open}
      onClose={busy ? undefined : onClose}
      title={set ? t("codeSets.membersTitle", { name: set.name }) : undefined}
      icon={<SlidersHorizontal size={14} aria-hidden />}
      size="lg"
      panelClassName="w-[32rem] max-w-[92vw]"
    >
      <div className="flex max-h-[65vh] flex-col">
        <div className="qc-scroll min-h-0 flex-1 overflow-y-auto px-2 py-1">
          {codes.length === 0 ? (
            <p className="px-2 py-3 text-center text-sm text-text-secondary">
              {t("codeSets.noCodes")}
            </p>
          ) : (
            codes.map((code) => (
              <label
                key={code.cid}
                className="flex cursor-pointer items-center gap-2 rounded-sm px-2 py-1 text-sm hover:bg-surface-higher"
              >
                <input
                  type="checkbox"
                  checked={draft.has(code.cid)}
                  onChange={() => toggle(code.cid)}
                  className="shrink-0 accent-accent"
                />
                <span
                  className="inline-block h-3 w-3 shrink-0 rounded-sm border border-border"
                  style={{ backgroundColor: code.color ?? "#ccc" }}
                  aria-hidden
                />
                <span className="min-w-0 truncate" title={code.label}>
                  {code.label}
                </span>
              </label>
            ))
          )}
        </div>
        {error && (
          <p
            role="alert"
            className="flex shrink-0 items-center gap-1.5 px-3 pt-2 text-xs text-danger"
          >
            <CircleAlert size={12} className="shrink-0" aria-hidden />
            <span className="min-w-0 truncate">{error}</span>
          </p>
        )}
        <div className="flex items-center justify-end gap-2 px-3 py-2">
          <Button variant="secondary" onClick={onClose} disabled={busy}>
            {t("common.cancel")}
          </Button>
          <Button
            variant="primary"
            icon={
              busy ? (
                <LoaderCircle size={12} className="animate-spin" aria-hidden />
              ) : (
                <Check size={12} aria-hidden />
              )
            }
            disabled={busy}
            onClick={() => void save()}
          >
            {t("codeSets.membersSave")}
          </Button>
        </div>
      </div>
    </Modal>
  );
}
