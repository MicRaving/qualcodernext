/**
 * HistoryView — edit review: the chronological audit log of the project,
 * filterable by action and coder, with a detail drawer (before/after diff
 * for text edits).
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { CircleAlert, CircleCheck, History, LoaderCircle, RotateCw, Undo2, X } from "lucide-react";
import { api, type AuditRow, type AuditStatsRow } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { ViewHeader } from "@/components/ui/orchestrator";

const PAGE_SIZE = 100;

/** Actions the backend can invert (undo/redo) from their audit detail. */
const UNDOABLE = new Set([
  "coding.create",
  "coding.delete",
  "annotation.create",
  "annotation.delete",
  "source.edit",
  "code.rename",
  "code.create",
  "case.create",
  "journal.create",
]);

function actionLabel(action: string, t: (key: string) => string): string {
  const key = `history.action.${action}`;
  return t(key);
}

/** Simple line diff for the before/after texts (edit review). */
function lineDiff(before: string, after: string): { removed: string[]; added: string[] } {
  const a = before.split(/\r?\n/);
  const b = after.split(/\r?\n/);
  const removed = a.filter((l) => !b.includes(l));
  const added = b.filter((l) => !a.includes(l));
  return { removed, added };
}

export function HistoryView() {
  const { t } = useI18n();
  const [rows, setRows] = useState<AuditRow[]>([]);
  const [total, setTotal] = useState(0);
  const [stats, setStats] = useState<AuditStatsRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [offset, setOffset] = useState(0);
  const [filterAction, setFilterAction] = useState("");
  const [filterUser, setFilterUser] = useState("");
  const [selected, setSelected] = useState<AuditRow | null>(null);
  const [redoStack, setRedoStack] = useState<number[]>([]);
  const [actionMsg, setActionMsg] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [res, st] = await Promise.all([
        api.audit({ limit: PAGE_SIZE, offset, action: filterAction || undefined, user: filterUser || undefined }),
        api.auditStats(),
      ]);
      setRows(res.rows);
      setTotal(res.total);
      setStats(st);
    } catch (e) {
      setError(e instanceof Error ? e.message : t("history.loadError"));
    } finally {
      setLoading(false);
    }
  }, [offset, filterAction, filterUser, t]);

  useEffect(() => {
    void load();
  }, [load]);

  const users = useMemo(() => [...new Set(rows.map((r) => r.user).filter(Boolean))], [rows]);

  function resetAndFilter() {
    setOffset(0);
  }

  const diff = useMemo(() => {
    if (!selected || selected.action !== "source.edit") return null;
    const before = String(selected.detail.before ?? "");
    const after = String(selected.detail.after ?? "");
    return lineDiff(before, after);
  }, [selected]);

  async function handleUndo(row: AuditRow) {
    setError(null);
    setActionMsg(null);
    try {
      const res = await api.auditUndo(row.id);
      setRedoStack((s) => [...s.slice(-9), row.id]);
      setActionMsg(res.message);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : t("history.undoError"));
    }
  }

  async function handleRedo() {
    const id = redoStack[redoStack.length - 1];
    if (id == null) return;
    setError(null);
    setActionMsg(null);
    try {
      const res = await api.auditRedo(id);
      setRedoStack((s) => s.slice(0, -1));
      setActionMsg(res.message);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : t("history.redoError"));
    }
  }

  const filterCls =
    "h-8 rounded-sm border border-border bg-bg px-2 text-sm outline-none focus:border-accent";

  return (
    <div className="flex h-full flex-col bg-bg">
      <ViewHeader back={false}
        title={
          <span className="flex items-center gap-1.5">
            <History size={15} aria-hidden />
            {t("history.title")}
          </span>
        }
        actions={
          <>
            <select
              value={filterAction}
              onChange={(e) => {
                setFilterAction(e.target.value);
                resetAndFilter();
              }}
              aria-label={t("history.filterAction")}
              className={filterCls}
            >
              <option value="">{t("history.allActions")}</option>
              {stats.map((s) => (
                <option key={s.action} value={s.action}>
                  {actionLabel(s.action, t)} ({s.count})
                </option>
              ))}
            </select>
            <select
              value={filterUser}
              onChange={(e) => {
                setFilterUser(e.target.value);
                resetAndFilter();
              }}
              aria-label={t("history.filterUser")}
              className={filterCls}
            >
              <option value="">{t("history.allUsers")}</option>
              {users.map((u) => (
                <option key={u} value={u}>
                  {u}
                </option>
              ))}
            </select>
            <button
              type="button"
              onClick={() => void load()}
              disabled={loading}
              aria-label={t("common.retry")}
              className="rounded-sm border border-border bg-bg p-1.5 text-text-secondary hover:bg-surface-higher disabled:opacity-50"
            >
              <RotateCw size={14} aria-hidden />
            </button>
            <button
              type="button"
              onClick={() => void handleRedo()}
              disabled={redoStack.length === 0}
              title={t("history.redoTitle")}
              className="flex items-center gap-1 rounded-sm border border-border bg-bg px-2 py-1 text-xs text-text-secondary hover:bg-surface-higher disabled:opacity-40"
            >
              <Undo2 size={13} className="scale-x-[-1]" aria-hidden />
              {t("history.redo")}
            </button>
          </>
        }
      />

      {actionMsg && (
        <div className="flex shrink-0 items-center gap-2 border-b border-border bg-surface px-3 py-1.5 text-xs text-success">
          <CircleCheck size={13} aria-hidden />
          <span className="min-w-0 flex-1 truncate">{actionMsg}</span>
        </div>
      )}

      {error && (
        <div className="flex shrink-0 items-center gap-2 border-b border-danger bg-danger/10 px-3 py-1.5 text-sm text-danger">
          <CircleAlert size={14} aria-hidden />
          <span className="min-w-0 flex-1 truncate">{error}</span>
          <button
            type="button"
            onClick={() => setError(null)}
            aria-label={t("common.dismiss")}
            className="rounded-sm p-0.5 hover:bg-surface-higher"
          >
            <X size={14} aria-hidden />
          </button>
        </div>
      )}

      <div className="min-h-0 flex-1 overflow-y-auto">
        {loading && rows.length === 0 ? (
          <div className="flex h-full items-center justify-center gap-2 text-text-secondary">
            <LoaderCircle size={16} className="animate-spin" aria-hidden />
            {t("history.loading")}
          </div>
        ) : rows.length === 0 ? (
          <div className="flex h-full items-center justify-center text-sm text-text-secondary">
            {t("history.empty")}
          </div>
        ) : (
          <table className="w-full text-left text-sm">
            <thead className="sticky top-0 bg-surface text-xs text-text-secondary">
              <tr>
                <th className="px-3 py-2 font-medium">{t("history.colWhen")}</th>
                <th className="px-3 py-2 font-medium">{t("history.colUser")}</th>
                <th className="px-3 py-2 font-medium">{t("history.colAction")}</th>
                <th className="px-3 py-2 font-medium">{t("history.colEntity")}</th>
                <th className="px-3 py-2 font-medium">{t("history.colDetail")}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr
                  key={r.id}
                  onClick={() => setSelected(r)}
                  className="cursor-pointer border-t border-border hover:bg-surface-higher"
                >
                  <td className="whitespace-nowrap px-3 py-1.5 text-xs text-text-secondary">{r.ts}</td>
                  <td className="px-3 py-1.5">{r.user}</td>
                  <td className="px-3 py-1.5">{actionLabel(r.action, t)}</td>
                  <td className="px-3 py-1.5 text-xs text-text-secondary">
                    {r.entity}
                    {r.entity_id != null ? ` #${r.entity_id}` : ""}
                  </td>
                  <td className="max-w-64 truncate px-3 py-1.5 text-xs text-text-secondary">
                    {r.action === "coding.create" && r.detail.cid != null
                      ? `cid ${String(r.detail.cid)} · ${String(r.detail.pos0 ?? "")}–${String(r.detail.pos1 ?? "")}`
                      : r.action === "source.edit"
                        ? `${String(r.detail.before_length ?? "?")} → ${String(r.detail.new_length ?? "?")} chars`
                        : r.action === "coding.autocode" && r.detail.count != null
                          ? `${String(r.detail.count)} segments`
                          : r.action === "interchange.import"
                            ? t("history.importSummary")
                            : JSON.stringify(r.detail)}
                  </td>
                  <td className="px-3 py-1.5 text-right">
                    {UNDOABLE.has(r.action) && (
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          void handleUndo(r);
                        }}
                        title={t("history.undoTitle")}
                        className="rounded-sm border border-border bg-bg px-1.5 py-0.5 text-xs text-text-secondary hover:bg-surface-higher hover:text-text-primary"
                      >
                        {t("history.undo")}
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {total > PAGE_SIZE && (
        <footer className="flex shrink-0 items-center justify-center gap-3 border-t border-border bg-surface px-3 py-1.5 text-xs text-text-secondary">
          <button
            type="button"
            disabled={offset === 0}
            onClick={() => setOffset((o) => Math.max(0, o - PAGE_SIZE))}
            className="rounded-sm border border-border bg-bg px-2 py-0.5 hover:bg-surface-higher disabled:opacity-40"
          >
            {t("history.prev")}
          </button>
          <span>
            {offset + 1}–{Math.min(offset + PAGE_SIZE, total)} / {total}
          </span>
          <button
            type="button"
            disabled={offset + PAGE_SIZE >= total}
            onClick={() => setOffset((o) => o + PAGE_SIZE)}
            className="rounded-sm border border-border bg-bg px-2 py-0.5 hover:bg-surface-higher disabled:opacity-40"
          >
            {t("history.next")}
          </button>
        </footer>
      )}

      {selected && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-bg/70"
          onMouseDown={(e) => {
            if (e.target === e.currentTarget) setSelected(null);
          }}
          role="dialog"
          aria-modal="true"
          aria-label={t("history.detailTitle")}
        >
          <div className="w-[32rem] max-w-[90vw] rounded-lg border border-border bg-surface shadow-xl">
            <div className="flex items-center gap-2 border-b border-border px-3 py-2">
              <span className="text-sm font-semibold text-text-primary">
                {actionLabel(selected.action, t)}
              </span>
              <span className="text-xs text-text-secondary">
                {selected.ts} · {selected.user}
              </span>
              <div className="flex-1" />
              <button
                type="button"
                onClick={() => setSelected(null)}
                aria-label={t("common.close")}
                className="rounded-sm p-1 text-text-secondary hover:bg-surface-higher hover:text-text-primary"
              >
                <X size={14} aria-hidden />
              </button>
            </div>
            <div className="max-h-[60vh] overflow-y-auto p-3 text-sm">
              {diff ? (
                <div className="space-y-3">
                  {diff.removed.length > 0 && (
                    <div>
                      <p className="text-xs font-medium text-danger">{t("history.before")}</p>
                      <pre className="mt-1 whitespace-pre-wrap rounded-sm border border-border bg-bg p-2 text-xs text-text-primary">
                        {diff.removed.join("\n")}
                      </pre>
                    </div>
                  )}
                  {diff.added.length > 0 && (
                    <div>
                      <p className="text-xs font-medium text-success">{t("history.after")}</p>
                      <pre className="mt-1 whitespace-pre-wrap rounded-sm border border-border bg-bg p-2 text-xs text-text-primary">
                        {diff.added.join("\n")}
                      </pre>
                    </div>
                  )}
                  <p className="text-xs text-text-secondary">
                    {t("history.lengthChange", {
                      before: String(selected.detail.before_length ?? "?"),
                      after: String(selected.detail.new_length ?? "?"),
                    })}
                  </p>
                </div>
              ) : (
                <pre className="whitespace-pre-wrap rounded-sm border border-border bg-bg p-2 text-xs text-text-primary">
                  {JSON.stringify(selected.detail, null, 2)}
                </pre>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
