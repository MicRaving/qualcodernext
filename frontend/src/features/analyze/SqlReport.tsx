/**
 * SqlReport — run ad-hoc read-only SQL against the project database and
 * manage saved queries.
 */
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { LoaderCircle, Play, Save, Trash2 } from "lucide-react";
import { api, ApiError, type SavedQuery, type SqlResult } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { useToast } from "@/lib/toast";
import {
  Button,
  ErrorBanner,
  Input,
  TableHead,
  Textarea,
} from "@/components/ui/orchestrator";

function errorDetail(e: unknown): string {
  if (e instanceof ApiError && typeof e.detail === "string") return e.detail;
  return e instanceof Error ? e.message : "Request failed";
}

export function SqlReport() {
  const { t } = useI18n();
  const toast = useToast();
  const [sql, setSql] = useState("");
  const [title, setTitle] = useState("");
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<SqlResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<SavedQuery[]>([]);
  const [savedError, setSavedError] = useState<string | null>(null);

  const loadSaved = useCallback(async () => {
    try {
      const res = await api.savedQueries();
      setSaved(res.rows);
      setSavedError(null);
    } catch (e) {
      setSavedError(e instanceof Error ? e.message : "Failed to load saved queries");
    }
  }, []);

  useEffect(() => {
    void loadSaved();
  }, [loadSaved]);

  async function run(query: string) {
    if (!query.trim() || running) return;
    setRunning(true);
    setError(null);
    try {
      setResult(await api.sqlRun(query));
    } catch (e) {
      const detail = errorDetail(e);
      setResult(null);
      setError(detail);
      toast.error(detail);
    } finally {
      setRunning(false);
    }
  }

  async function save() {
    const name = title.trim();
    if (!name || !sql.trim() || running) return;
    try {
      await api.saveQuery({ title: name, ssql: sql });
      setTitle("");
      setError(null);
      await loadSaved();
      toast.success(`Saved query "${name}"`);
    } catch (err) {
      const detail = errorDetail(err);
      setError(detail);
      toast.error(detail);
    }
  }

  async function handleSave(e: FormEvent) {
    e.preventDefault();
    await save();
  }

  async function handleDelete(q: SavedQuery) {
    if (!window.confirm(t("analyze.deleteQueryConfirm", { name: q.title }))) return;
    try {
      await api.deleteQuery(q.title);
      setError(null);
      await loadSaved();
      toast.info(`Deleted query "${q.title}"`);
    } catch (e) {
      const detail = errorDetail(e);
      setError(detail);
      toast.error(detail);
    }
  }

  return (
    <div className="flex h-full flex-col">
      {/* Toolbar */}
      <div className="space-y-2 border-b border-border bg-surface p-3">
        <Textarea
          value={sql}
          onChange={(e) => setSql(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
              e.preventDefault();
              void run(sql);
            }
          }}
          rows={6}
          spellCheck={false}
          placeholder={t("analyze.sqlPlaceholder")}
          aria-label={t("analyze.sqlQueryAria")}
          className="w-full resize-y p-2 font-mono text-xs! text-text-primary"
        />
        <div className="flex flex-wrap items-center gap-2">
          <Button
            variant="primary"
            onClick={() => void run(sql)}
            disabled={!sql.trim() || running}
            icon={<Play size={14} aria-hidden />}
          >
            {t("analyze.run")}
          </Button>
          {running && (
            <span className="flex items-center gap-1 text-xs text-text-secondary" role="status">
              <LoaderCircle size={12} className="animate-spin" aria-hidden />
              {t("analyze.running")}
            </span>
          )}
          <span className="flex-1" />
          <form onSubmit={(e) => void handleSave(e)} className="flex items-center gap-2">
            <Input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder={t("analyze.queryTitlePlaceholder")}
              aria-label={t("analyze.queryTitleAria")}
              className="w-44"
            />
            <Button
              variant="primary"
              type="submit"
              disabled={!title.trim() || !sql.trim() || running}
              icon={<Save size={14} aria-hidden />}
            >
              {t("analyze.saveQuery")}
            </Button>
          </form>
        </div>
      </div>

      {/* Notices */}
      {error && <ErrorBanner>{error}</ErrorBanner>}
      {result?.truncated && (
        <ErrorBanner tone="warning">Results truncated — refine the query to see all rows.</ErrorBanner>
      )}

      {/* Saved queries */}
      <div className="flex shrink-0 items-start gap-2 border-b border-border bg-surface px-3 py-2">
        <span className="mt-1 shrink-0 text-xs text-text-secondary">Saved:</span>
        <div className="flex min-w-0 flex-1 flex-wrap gap-1.5">
          {savedError ? (
            <span className="text-xs text-danger">{savedError}</span>
          ) : saved.length === 0 ? (
            <span className="text-xs text-text-secondary">{t("analyze.noSavedQueries")}</span>
          ) : (            saved.map((q) => (
              <span
                key={q.title}
                className="flex items-center gap-1 rounded-sm border border-border bg-bg px-2 py-1 text-xs"
              >
                <button
                  type="button"
                  onClick={() => {
                    setSql(q.ssql);
                    void run(q.ssql);
                  }}
                  title={q.ssql}
                  className="max-w-56 truncate text-text-primary hover:text-accent"
                >
                  {q.title}
                </button>
                <button
                  type="button"
                  onClick={() => void handleDelete(q)}
                  aria-label={t("analyze.deleteQueryFor", { name: q.title })}
                  title="Delete"
                  className="rounded-sm p-0.5 text-text-secondary hover:bg-surface-higher hover:text-danger"
                >
                  <Trash2 size={12} aria-hidden />
                </button>
              </span>
            ))
          )}
        </div>
        <Button
          variant="primary"
          className="shrink-0"
          onClick={() => void save()}
          disabled={!title.trim() || !sql.trim() || running}
          icon={<Save size={14} aria-hidden />}
        >
          {t("analyze.saveCurrent")}
        </Button>
      </div>

      {/* Results */}
      <div className="min-h-0 flex-1 overflow-auto">
        {result && (
          <table className="w-full border-separate border-spacing-0">
            <thead className="sticky top-0 z-10 bg-surface">
              <tr>
                {result.columns.map((col) => (
                  <TableHead key={col}>{col}</TableHead>
                ))}
              </tr>
            </thead>
            <tbody>
              {result.rows.map((row, i) => (
                <tr key={i} className="hover:bg-surface-higher">
                  {row.map((cell, j) => (
                    <td
                      key={j}
                      className="border-b border-border px-2 py-1.5 text-sm"
                    >
                      {cell === null ? (
                        <span className="text-text-secondary">NULL</span>
                      ) : (
                        String(cell)
                      )}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {!result && !error && !running && (
          <div className="flex h-48 items-center justify-center">
            <p className="text-sm text-text-secondary">
              Run a query to see results.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
