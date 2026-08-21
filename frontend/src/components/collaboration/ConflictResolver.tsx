/**
 * ConflictResolver — modal dialog for resolving sync conflicts.
 *
 * Shows a list of unresolved conflicts with local vs remote row snapshots.
 * For each conflict, the user can choose "Keep mine", "Take theirs", or
 * "Merge" (which opens a simple field-by-field editor).
 *
 * Follows DESIGN.md §12 (Modal primitive, size="lg").
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Check } from "lucide-react";
import { useI18n } from "@/lib/i18n";
import { usePrefsStore } from "@/stores/prefs";
import { useToast } from "@/lib/toast";
import { Button, Modal } from "@/components/ui/orchestrator";
import type { SyncConflictV2 } from "@/lib/api";

interface ConflictResolverProps {
  open: boolean;
  onClose: () => void;
}

/** Fields to hide from the diff view (internal metadata). */
const HIDDEN_FIELDS = new Set(["id", "date", "owner", "memo_type"]);

function ConflictRow({
  conflict,
  onResolve,
}: {
  conflict: SyncConflictV2;
  onResolve: (id: number, resolution: "local" | "remote" | "merged", merged?: Record<string, unknown>) => void;
}) {
  const { t } = useI18n();
  const [mode, setMode] = useState<"choose" | "merge">("choose");
  const [merged, setMerged] = useState<Record<string, unknown>>(
    conflict.remote_row ?? {},
  );

  const fields = useMemo(() => {
    const allKeys = new Set([
      ...Object.keys(conflict.local_row ?? {}),
      ...Object.keys(conflict.remote_row ?? {}),
    ]);
    return [...allKeys].filter((k) => !HIDDEN_FIELDS.has(k));
  }, [conflict.local_row, conflict.remote_row]);

  if (mode === "merge") {
    return (
      <div className="rounded-sm border border-border bg-bg p-2">
        <p className="mb-2 text-xs font-medium text-text-primary">
          {t("sync.conflictItem", { entity: conflict.entity_label, pk: conflict.pk, reason: "" })}
        </p>
        <div className="space-y-1.5">
          {fields.map((field) => {
            const localVal = String((conflict.local_row ?? {})[field] ?? "");
            const remoteVal = String((conflict.remote_row ?? {})[field] ?? "");
            const isDifferent = localVal !== remoteVal;
            return (
              <div key={field}>
                <label className="text-[10px] font-medium text-text-secondary">{field}</label>
                {isDifferent ? (
                  <textarea
                    value={String(merged[field] ?? "")}
                    onChange={(e) => setMerged((prev) => ({ ...prev, [field]: e.target.value }))}
                    className="mt-0.5 w-full rounded-sm border border-border bg-bg px-1.5 py-1 text-xs text-text-primary focus:border-accent"
                    rows={2}
                  />
                ) : (
                  <p className="text-xs text-text-secondary">{localVal || "—"}</p>
                )}
              </div>
            );
          })}
        </div>
        <div className="mt-2 flex gap-1.5">
          <Button
            variant="primary"
            onClick={() => onResolve(conflict.id, "merged", merged)}
          >
            {t("sync.applyResolution")}
          </Button>
          <Button variant="secondary" onClick={() => setMode("choose")}>
            {t("common.cancel")}
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="rounded-sm border border-border bg-bg p-2">
      <p className="mb-1.5 text-xs font-medium text-text-primary">
        {t("sync.conflictItem", { entity: conflict.entity_label, pk: conflict.pk, reason: "" })}
      </p>
      <div className="grid grid-cols-2 gap-2 text-[11px]">
        <div>
          <span className="font-medium text-text-secondary">{t("sync.localVersion")}</span>
          <div className="mt-0.5 space-y-0.5 rounded-sm border border-border p-1.5">
            {fields.map((field) => (
              <p key={field} className="truncate">
                <span className="text-text-secondary">{field}:</span>{" "}
                {String((conflict.local_row ?? {})[field] ?? "—")}
              </p>
            ))}
            {conflict.local_row === null && (
              <p className="italic text-text-secondary">{t("sync.localDeleted")}</p>
            )}
          </div>
        </div>
        <div>
          <span className="font-medium text-text-secondary">
            {t("sync.remoteVersion", { coder: conflict.remote_coder || conflict.remote_instance })}
          </span>
          <div className="mt-0.5 space-y-0.5 rounded-sm border border-border p-1.5">
            {fields.map((field) => (
              <p key={field} className="truncate">
                <span className="text-text-secondary">{field}:</span>{" "}
                {String((conflict.remote_row ?? {})[field] ?? "—")}
              </p>
            ))}
            {conflict.remote_row === null && (
              <p className="italic text-text-secondary">{t("sync.remoteDeleted")}</p>
            )}
          </div>
        </div>
      </div>
      <div className="mt-2 flex gap-1.5">
        <Button variant="primary" onClick={() => onResolve(conflict.id, "local")}>
          {t("sync.keepMine")}
        </Button>
        <Button variant="secondary" onClick={() => onResolve(conflict.id, "remote")}>
          {t("sync.takeTheirs")}
        </Button>
        <Button variant="secondary" onClick={() => setMode("merge")}>
          {t("sync.merge")}
        </Button>
      </div>
    </div>
  );
}

export function ConflictResolver({ open, onClose }: ConflictResolverProps) {
  const { t } = useI18n();
  const toast = useToast();
  const conflicts = usePrefsStore((s) => s.conflicts);
  const resolveConflict = usePrefsStore((s) => s.resolveConflict);
  const resolveAllConflicts = usePrefsStore((s) => s.resolveAllConflicts);
  const [bulkBusy, setBulkBusy] = useState(false);
  // Tracks whether any conflict was resolved this session so the popup only
  // auto-closes when it finishes an actual resolution (never on initial open
  // with zero conflicts).
  const justResolved = useRef(false);

  // Auto-close once the last conflict is resolved.
  useEffect(() => {
    if (open && conflicts.length === 0 && justResolved.current) {
      justResolved.current = false;
      onClose();
    }
  }, [open, conflicts.length, onClose]);

  const handleResolve = useCallback(
    async (id: number, resolution: "local" | "remote" | "merged", merged?: Record<string, unknown>) => {
      justResolved.current = true;
      await resolveConflict(id, resolution, merged);
    },
    [resolveConflict],
  );

  const handleResolveAll = useCallback(
    async (resolution: "local" | "remote") => {
      setBulkBusy(true);
      try {
        const n = await resolveAllConflicts(resolution);
        if (n > 0) {
          justResolved.current = true;
          toast.success(t("sync.resolvedAll", { n: String(n) }));
        }
      } finally {
        setBulkBusy(false);
      }
    },
    [resolveAllConflicts, toast, t],
  );

  const headerActions = (
    <div className="flex shrink-0 items-center gap-1.5">
      <button
        type="button"
        disabled={bulkBusy || conflicts.length === 0}
        onClick={() => void handleResolveAll("local")}
        className="rounded-sm border border-border bg-surface px-2 py-1 text-xs font-medium leading-none text-text-primary hover:bg-surface-higher disabled:opacity-40"
      >
        {t("sync.resolveAllMine")}
      </button>
      <button
        type="button"
        disabled={bulkBusy || conflicts.length === 0}
        onClick={() => void handleResolveAll("remote")}
        className="rounded-sm border border-border bg-surface px-2 py-1 text-xs font-medium leading-none text-text-primary hover:bg-surface-higher disabled:opacity-40"
      >
        {t("sync.resolveAllTheirs")}
      </button>
    </div>
  );

  return (
    <Modal
      open={open}
      onClose={onClose}
      size="lg"
      title={t("sync.conflictResolver")}
      headerActions={headerActions}
    >
      <div className="max-h-[60vh] overflow-y-auto p-4">
        {conflicts.length === 0 ? (
          <div className="flex flex-col items-center gap-2 py-8 text-text-secondary">
            <Check size={24} aria-hidden />
            <p className="text-sm">{t("sync.conflictResolverEmpty")}</p>
          </div>
        ) : (
          <div className="space-y-3">
            <p className="text-xs text-text-secondary">
              {t("sync.conflicts", { n: String(conflicts.length) })}
            </p>
            {conflicts.map((conflict) => (
              <ConflictRow
                key={conflict.id}
                conflict={conflict}
                onResolve={handleResolve}
              />
            ))}
          </div>
        )}
      </div>
      <div className="flex justify-end border-t border-border px-3 py-2">
        <Button variant="secondary" onClick={onClose}>
          {t("common.close")}
        </Button>
      </div>
    </Modal>
  );
}
