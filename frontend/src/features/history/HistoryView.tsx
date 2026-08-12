/**
 * HistoryView — the audit log as a right-bar pane: filterable by action and
 * coder, every change a small card with an undo icon (details are hidden).
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { History, RotateCw, Search, Undo2 } from "lucide-react";
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

/** Actions the backend can invert (undo/redo) from their audit detail. */
const UNDOABLE = new Set([
  "coding.create",
  "coding.delete",
  "annotation.create",
  "annotation.delete",
  "source.edit",
  "code.rename",
  "code.create",
  "code.delete",
  "case.create",
  "journal.create",
]);

function actionLabel(action: string, t: (key: string) => string): string {
  const key = `history.action.${action}`;
  return t(key);
}

function detailSummary(r: AuditRow, t: (key: string) => string): string {
  if (r.action === "coding.create" && r.detail.cid != null) {
    return `cid ${String(r.detail.cid)} · ${String(r.detail.pos0 ?? "")}–${String(r.detail.pos1 ?? "")}`;
  }
  if (r.action === "source.edit") {
    return `${String(r.detail.before_length ?? "?")} → ${String(r.detail.new_length ?? "?")} chars`;
  }
  if (r.action === "coding.autocode" && r.detail.count != null) {
    return `${String(r.detail.count)} segments`;
  }
  if (r.action === "interchange.import") return t("history.importSummary");
  return "";
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
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<AuditRow | null>(null);
  const [redoStack, setRedoStack] = useState<number[]>([]);
  const [actionMsg, setActionMsg] = useState<string | null>(null);
  const loadSeqRef = useRef(0);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    // A stale response must not overwrite a newer page's rows (rapid
    // pagination/filter switches race otherwise).
    const seq = ++loadSeqRef.current;
    try {
      const [res, st] = await Promise.all([
        api.audit({ limit: PAGE_SIZE, offset, action: filterAction || undefined, user: filterUser || undefined }),
        api.auditStats(),
      ]);
      if (seq !== loadSeqRef.current) return;
      setRows(res.rows);
      setTotal(res.total);
      setStats(st);
    } catch (e) {
      if (seq !== loadSeqRef.current) return;
      setError(e instanceof Error ? e.message : t("history.loadError"));
    } finally {
      if (seq === loadSeqRef.current) setLoading(false);
    }
  }, [offset, filterAction, filterUser, t]);

  useEffect(() => {
    void load();
  }, [load]);

  const users = useMemo(() => [...new Set(rows.map((r) => r.user).filter(Boolean))], [rows]);

  /** Client-side text search over the loaded page. */
  const visibleRows = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return rows;
    return rows.filter(
      (r) =>
        r.user.toLowerCase().includes(q) ||
        r.entity.toLowerCase().includes(q) ||
        actionLabel(r.action, t).toLowerCase().includes(q) ||
        JSON.stringify(r.detail).toLowerCase().includes(q),
    );
  }, [rows, search, t]);

  function resetAndFilter() {
    setOffset(0);
  }

  async function handleUndo(row: AuditRow) {
    setError(null);
    setActionMsg(null);
    try {
      const res = await api.auditUndo(row.id);
      setRedoStack((s) => [...s.slice(-9), row.id]);
      setActionMsg(res.message);
      await useProjectStore.getState().refreshProject();
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
      await useProjectStore.getState().refreshProject();
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : t("history.redoError"));
    }
  }

  return (
    <LeftBar
      borderSide="l"
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
                title={t("history.redoTitle")}
                onClick={() => void handleRedo()}
                disabled={redoStack.length === 0}
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
            {visibleRows.map((r) => {
              const detail = detailSummary(r, t);
              return (
                <li key={r.id} className="flex items-start gap-2 px-3 py-2">
                  <button
                    type="button"
                    onClick={() => setSelected(r)}
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
                      {detail && <span className="truncate text-text-secondary/80">{detail}</span>}
                    </div>
                  </button>
                  {UNDOABLE.has(r.action) && (
                    <IconButton
                      label={t("history.undoTitle")}
                      title={t("history.undoTitle")}
                      size="row"
                      className="mt-0.5"
                      onClick={() => void handleUndo(r)}
                    >
                      <Undo2 size={14} aria-hidden />
                    </IconButton>
                  )}
                </li>
              );
            })}
          </ul>
          {visibleRows.length === 0 && (
            <p className="px-3 py-6 text-center text-sm text-text-secondary">
              {t("history.noMatch")}
            </p>
          )}
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
        {selected && (
          <div className="max-h-[60vh] overflow-y-auto p-3 text-sm">
            {selected.action === "source.edit" ? (
              <div className="space-y-3">
                <div>
                  <p className="text-xs font-medium text-danger">{t("history.before")}</p>
                  <pre className="mt-1 whitespace-pre-wrap rounded-sm border border-border bg-bg p-2 text-xs text-text-primary">
                    {String(selected.detail.before ?? "")}
                  </pre>
                </div>
                <div>
                  <p className="text-xs font-medium text-success">{t("history.after")}</p>
                  <pre className="mt-1 whitespace-pre-wrap rounded-sm border border-border bg-bg p-2 text-xs text-text-primary">
                    {String(selected.detail.after ?? "")}
                  </pre>
                </div>
              </div>
            ) : (
              <pre className="whitespace-pre-wrap rounded-sm border border-border bg-bg p-2 text-xs text-text-primary">
                {JSON.stringify(selected.detail, null, 2)}
              </pre>
            )}
          </div>
        )}
      </Modal>
    </LeftBar>
  );
}
