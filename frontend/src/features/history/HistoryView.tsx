/**
 * HistoryView — the audit log as a right-bar pane: filterable by action and
 * coder, every change a small card with an undo icon (details are hidden).
 *
 * The list uses the ``summary`` projection (no huge ``detail`` JSON), the
 * undo/redo buttons are gated by the backend ``/undoable`` predicate, and
 * redo is driven by the server-side ``audit.undo``/``audit.redo`` markers so
 * it survives a pane reload.
 */
import { errorMessage } from "@/lib/utils";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Download, History, RotateCw, Search, Undo2 } from "lucide-react";
import { api, type AuditRow, type AuditStatsRow } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { useProjectStore } from "@/stores/project";
import {
  BarHeader,
  Button,
  EmptyState,
  ErrorBanner,
  IconButton,
  Input,
  LeftBar,
  LoadingState,
  Modal,
  Select,
} from "@/components/ui/orchestrator";

const PAGE_SIZE = 100;

/** Actions that can silently wipe large amounts of work if mis-clicked. */
const DESTRUCTIVE_ACTIONS = new Set([
  "code.merge",
  "code.delete",
  "category.merge",
  "category.delete",
  "source.delete",
  "source.replace",
  "speakers.mark",
  "coding.autocode",
]);

/** Entity tables that back the coder views — only these need a coding refetch. */
const CODING_ENTITIES = new Set(["code_text", "code_image", "code_av", "annotation"]);

function actionLabel(action: string, t: (key: string) => string): string {
  const key = `history.action.${action}`;
  const label = t(key);
  if (label === key) {
    // Safety net: prettify an action that has no i18n key yet.
    return action
      .split(".")
      .map((part) => part.charAt(0).toUpperCase() + part.slice(1).replace(/_/g, " "))
      .join(" · ");
  }
  return label;
}

export function HistoryView() {
  const { t } = useI18n();
  const [rows, setRows] = useState<AuditRow[]>([]);
  const [total, setTotal] = useState(0);
  const [stats, setStats] = useState<AuditStatsRow[]>([]);
  const [users, setUsers] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [offset, setOffset] = useState(0);
  const [filterAction, setFilterAction] = useState("");
  const [filterUser, setFilterUser] = useState("");
  const [search, setSearch] = useState("");
  const [q, setQ] = useState("");
  const [selected, setSelected] = useState<AuditRow | null>(null);
  const [confirm, setConfirm] = useState<AuditRow | null>(null);
  const [redoPending, setRedoPending] = useState<{ count: number; next_id: number | null }>({
    count: 0,
    next_id: null,
  });
  const [actionMsg, setActionMsg] = useState<string | null>(null);
  const loadSeqRef = useRef(0);
  const searchTimer = useRef<number | undefined>(undefined);

  // Debounce the search input into the server query param (300ms).
  useEffect(() => {
    window.clearTimeout(searchTimer.current);
    searchTimer.current = window.setTimeout(() => {
      setQ(search.trim());
      setOffset(0);
    }, 300);
    return () => window.clearTimeout(searchTimer.current);
  }, [search]);

  const refreshRedoPending = useCallback(async () => {
    try {
      const res = await api.auditRedoPending();
      setRedoPending(res);
    } catch {
      // Redo availability is best-effort; ignore.
    }
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    const seq = ++loadSeqRef.current;
    try {
      const [res, st, us] = await Promise.all([
        api.audit({
          limit: PAGE_SIZE,
          offset,
          action: filterAction || undefined,
          user: filterUser || undefined,
          q: q || undefined,
          summary: true,
        }),
        api.auditStats(),
        api.auditUsers(),
      ]);
      if (seq !== loadSeqRef.current) return;
      setRows(res.rows);
      setTotal(res.total);
      setStats(st);
      setUsers(us);
    } catch (e) {
      if (seq !== loadSeqRef.current) return;
      setError(errorMessage(e, t("history.loadError")));
    } finally {
      if (seq === loadSeqRef.current) setLoading(false);
    }
  }, [offset, filterAction, filterUser, q, t]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    void refreshRedoPending();
  }, [refreshRedoPending]);

  function resetAndFilter() {
    setOffset(0);
  }

  function notifyViewsChanged(entity: string, sourceId: number | null) {
    // Only coding-backed entities need the coder views to refetch; everything
    // else is handled by the project refresh below.
    if (!CODING_ENTITIES.has(entity)) return;
    window.dispatchEvent(
      new CustomEvent("qc:codings-changed", {
        detail: { entities: [entity], sourceIds: sourceId != null ? [sourceId] : [] },
      }),
    );
  }

  async function runUndo(row: AuditRow) {
    setError(null);
    setActionMsg(null);
    try {
      const res = await api.auditUndo(row.id);
      setActionMsg(res.message);
      await useProjectStore.getState().refreshProject();
      notifyViewsChanged(row.entity, row.source_id);
      await Promise.all([load(), refreshRedoPending()]);
    } catch (e) {
      setError(errorMessage(e, t("history.undoError")));
    }
  }

  function handleUndo(row: AuditRow) {
    if (DESTRUCTIVE_ACTIONS.has(row.action)) {
      setConfirm(row);
      return;
    }
    void runUndo(row);
  }

  function handleRedo() {
    const id = redoPending.next_id;
    if (id == null) return;
    setError(null);
    setActionMsg(null);
    void (async () => {
      try {
        const res = await api.auditRedo(id);
        setActionMsg(res.message);
        await useProjectStore.getState().refreshProject();
        window.dispatchEvent(
          new CustomEvent("qc:codings-changed", { detail: { entities: ["*"], sourceIds: [] } }),
        );
        await Promise.all([load(), refreshRedoPending()]);
      } catch (e) {
        setError(errorMessage(e, t("history.redoError")));
      }
    })();
  }

  async function openDetail(row: AuditRow) {
    try {
      const full = await api.auditGet(row.id);
      setSelected(full);
    } catch (e) {
      setSelected(row);
      setError(errorMessage(e, t("history.loadError")));
    }
  }

  return (
    <LeftBar
      borderSide="l"
      className="h-full min-h-0"
      header={
        <>
          <BarHeader
            title={
              <span className="flex items-center gap-1.5">
                <History size={15} aria-hidden />
                {t("history.title")}
              </span>
            }
            actions={
              <IconButton
                label={t("history.redoTitle")}
                title={
                  redoPending.count > 0
                    ? `${t("history.redoTitle")} (${redoPending.count})`
                    : t("history.redoTitle")
                }
                onClick={handleRedo}
                disabled={redoPending.count === 0}
              >
                <Undo2 size={14} className="scale-x-[-1]" aria-hidden />
              </IconButton>
            }
          />
          {/* Filter top bar */}
          <div className="flex shrink-0 items-center gap-1.5 border-b border-border px-3 py-1.5">
            <Select
              value={filterAction}
              onChange={(e) => {
                setFilterAction(e.target.value);
                resetAndFilter();
              }}
              aria-label={t("history.filterAction")}
              className="min-w-0 flex-1"
            >
              <option value="">{t("history.allActions")}</option>
              {stats.map((s) => (
                <option key={s.action} value={s.action}>
                  {actionLabel(s.action, t)} ({s.count})
                </option>
              ))}
            </Select>
            <Select
              value={filterUser}
              onChange={(e) => {
                setFilterUser(e.target.value);
                resetAndFilter();
              }}
              aria-label={t("history.filterUser")}
              className="min-w-0 flex-1"
            >
              <option value="">{t("history.allUsers")}</option>
              {users.map((u) => (
                <option key={u} value={u}>
                  {u}
                </option>
              ))}
            </Select>
            <IconButton
              label={t("common.retry")}
              onClick={() => void load()}
              disabled={loading}
              className="border border-border bg-bg"
            >
              <RotateCw size={14} aria-hidden />
            </IconButton>
          </div>
          {/* Search bar */}
          <div className="relative shrink-0 border-b border-border px-3 py-1.5">
            <Search
              size={14}
              className="pointer-events-none absolute left-5 top-1/2 -translate-y-1/2 text-text-secondary"
              aria-hidden
            />
            <Input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder={t("history.searchPlaceholder")}
              aria-label={t("history.searchPlaceholder")}
              className="w-full pl-7!"
            />
          </div>
        </>
      }
    >
      {actionMsg && <ErrorBanner tone="success">{actionMsg}</ErrorBanner>}
      {error && <ErrorBanner onClose={() => setError(null)}>{error}</ErrorBanner>}

      {loading && rows.length === 0 ? (
        <LoadingState>{t("history.loading")}</LoadingState>
      ) : rows.length === 0 ? (
        <EmptyState>{t("history.empty")}</EmptyState>
      ) : (
        <>
          <ul className="divide-y divide-border">
            {rows.map((r) => {
              const canUndo = r.undoable ?? true;
              return (
                <li key={r.id} className="flex items-start gap-2 px-3 py-2">
                  <button
                    type="button"
                    onClick={() => void openDetail(r)}
                    className="min-w-0 flex-1 text-left"
                    title={t("history.detailTitle")}
                  >
                    <div className="flex items-baseline justify-between gap-2">
                      <span className="truncate text-sm font-medium text-text-primary hover:text-accent">
                        {actionLabel(r.action, t)}
                      </span>
                      <span className="shrink-0 text-[10px] text-text-secondary">{r.ts}</span>
                    </div>
                    <div className="mt-0.5 flex items-center gap-2 text-xs text-text-secondary">
                      <span className="truncate">
                        {r.user}
                        {r.entity
                          ? ` · ${r.entity}${r.entity_id != null ? ` #${r.entity_id}` : ""}`
                          : ""}
                      </span>
                      {r.summary && <span className="truncate text-text-secondary/80">{r.summary}</span>}
                    </div>
                  </button>
                  <IconButton
                    label={t("history.undoRowTitle")}
                    title={canUndo ? t("history.undoRowTitle") : (r.undo_reason ?? t("history.undoRowTitle"))}
                    size="row"
                    className="mt-0.5"
                    disabled={!canUndo}
                    onClick={() => handleUndo(r)}
                  >
                    <Undo2 size={14} aria-hidden />
                  </IconButton>
                </li>
              );
            })}
          </ul>
          {total > PAGE_SIZE && (
            <div className="flex shrink-0 items-center justify-center gap-3 border-t border-border px-3 py-1.5 text-xs text-text-secondary">
              <Button
                variant="secondary"
                disabled={offset === 0}
                onClick={() => setOffset((o) => Math.max(0, o - PAGE_SIZE))}
              >
                {t("history.prev")}
              </Button>
              <span>
                {offset + 1}–{Math.min(offset + PAGE_SIZE, total)} / {total}
              </span>
              <Button
                variant="secondary"
                disabled={offset + PAGE_SIZE >= total}
                onClick={() => setOffset((o) => o + PAGE_SIZE)}
              >
                {t("history.next")}
              </Button>
            </div>
          )}
        </>
      )}

      {/* Detail view (before/after diff for text edits, raw detail otherwise) */}
      <Modal
        open={selected !== null}
        onClose={() => setSelected(null)}
        size="lg"
        ariaLabel={t("history.detailTitle")}
        title={
          selected ? (
            <>
              {actionLabel(selected.action, t)}
              <span className="ml-2 text-xs font-normal text-text-secondary">
                {selected.ts} · {selected.user}
              </span>
            </>
          ) : undefined
        }
      >
        {selected && <DetailContent row={selected} t={t} />}
      </Modal>

      {/* Confirm dialog for destructive undos */}
      <Modal
        open={confirm !== null}
        onClose={() => setConfirm(null)}
        size="sm"
        ariaLabel={t("history.confirmTitle")}
        title={confirm ? actionLabel(confirm.action, t) : ""}
      >
        {confirm && (
          <div className="space-y-4 p-3 text-sm">
            <p className="text-text-primary">{t("history.confirmBody")}</p>
            <div className="flex justify-end gap-2">
              <Button variant="secondary" onClick={() => setConfirm(null)}>
                {t("common.cancel")}
              </Button>
              <Button
                variant="danger"
                onClick={() => {
                  const row = confirm;
                  setConfirm(null);
                  void runUndo(row);
                }}
              >
                {t("history.undo")}
              </Button>
            </div>
          </div>
        )}
      </Modal>
    </LeftBar>
  );
}

function DetailContent({ row, t }: { row: AuditRow; t: (key: string) => string }) {
  const [showAll, setShowAll] = useState(false);
  const raw = useMemo(() => JSON.stringify(row.detail, null, 2), [row.detail]);
  const isHuge = raw.length > 20000;
  const display = showAll || !isHuge ? raw : `${raw.slice(0, 20000)}\n… (truncated)`;

  function download() {
    const blob = new Blob([raw], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `audit-${row.id}.json`;
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="max-h-[60vh] overflow-y-auto p-3 text-sm">
      {row.action === "source.edit" ? (
        <div className="space-y-3">
          <div>
            <p className="text-xs font-medium text-danger">{t("history.before")}</p>
            <pre className="mt-1 whitespace-pre-wrap rounded-sm border border-border bg-bg p-2 text-xs text-text-primary">
              {String(row.detail.before ?? "")}
            </pre>
          </div>
          <div>
            <p className="text-xs font-medium text-success">{t("history.after")}</p>
            <pre className="mt-1 whitespace-pre-wrap rounded-sm border border-border bg-bg p-2 text-xs text-text-primary">
              {String(row.detail.after ?? "")}
            </pre>
          </div>
        </div>
      ) : (
        <>
          <pre className="whitespace-pre-wrap rounded-sm border border-border bg-bg p-2 text-xs text-text-primary">
            {display}
          </pre>
          {isHuge && (
            <div className="mt-2 flex items-center justify-end gap-2">
              {!showAll && (
                <Button variant="secondary" onClick={() => setShowAll(true)}>
                  {t("history.showAll")}
                </Button>
              )}
              <Button variant="secondary" onClick={download}>
                <Download size={14} aria-hidden /> {t("history.downloadDetail")}
              </Button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
