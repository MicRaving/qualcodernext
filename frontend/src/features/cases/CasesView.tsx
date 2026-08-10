/**
 * Cases workspace — split into the shell's left bar (CasesList) and center
 * (CaseDetails). Both share the selection via the project store, so the
 * orchestrator can deliver them in the standard slots.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  CircleAlert,
  FileText,
  Link2,
  LoaderCircle,
  Pencil,
  Plus,
  RefreshCw,
  Search,
  Trash2,
  Unlink,
  UserRound,
  X,
} from "lucide-react";
import { api, type Case, type CaseFileLink } from "@/lib/api";
import { AttributeEditor } from "@/components/shell/AttributeEditor";
import { cn } from "@/lib/utils";
import { useI18n } from "@/lib/i18n";
import { useProjectStore } from "@/stores/project";

const primaryBtnCls =
  "flex items-center gap-1 rounded-sm bg-accent px-2.5 py-1 text-xs font-medium text-bg hover:bg-accent-hover disabled:opacity-50";
const iconBtnCls =
  "rounded-sm p-1 text-text-secondary hover:bg-surface-higher hover:text-text-primary";

/** Left bar: the case list with search + add actions. */
export function CasesList() {
  const { t } = useI18n();
  const cases = useProjectStore((s) => s.cases);
  const casesUi = useProjectStore((s) => s.casesUi);
  const setCasesUi = useProjectStore((s) => s.setCasesUi);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const list = await api.cases();
      useProjectStore.setState({ cases: list });
    } catch (e) {
      setLoadError(e instanceof Error ? e.message : t("cases.loadError"));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    void load();
  }, [load]);

  const filtered = useMemo(() => {
    const q = casesUi.query.trim().toLowerCase();
    if (!q) return cases;
    return cases.filter(
      (c) => c.name.toLowerCase().includes(q) || c.memo.toLowerCase().includes(q),
    );
  }, [cases, casesUi.query]);

  async function addCase() {
    const name = window.prompt(t("cases.newNamePrompt"));
    if (name === null) return;
    const trimmed = name.trim();
    if (!trimmed) return;
    setActionError(null);
    try {
      const created = await api.createCase(trimmed);
      setCasesUi({ selectedId: created.caseid });
      await useProjectStore.getState().refreshProject();
    } catch (e) {
      setActionError(e instanceof Error ? e.message : t("cases.createError"));
    }
  }

  async function renameCase(c: Case) {
    const next = window.prompt(t("cases.renamePrompt", { name: c.name }), c.name);
    if (next === null) return;
    const name = next.trim();
    if (!name || name === c.name) return;
    setActionError(null);
    try {
      await api.updateCase(c.caseid, { name });
      await useProjectStore.getState().refreshProject();
    } catch (e) {
      setActionError(e instanceof Error ? e.message : t("cases.renameError"));
    }
  }

  async function deleteCase(c: Case) {
    if (!window.confirm(t("cases.deleteConfirm", { name: c.name }))) return;
    setActionError(null);
    try {
      await api.deleteCase(c.caseid);
      if (casesUi.selectedId === c.caseid) setCasesUi({ selectedId: null });
      await useProjectStore.getState().refreshProject();
    } catch (e) {
      setActionError(e instanceof Error ? e.message : t("cases.deleteError"));
    }
  }

  return (
    <aside className="flex w-72 shrink-0 flex-col border-r border-border bg-surface">
      <header className="flex h-10 shrink-0 items-center gap-2 border-b border-border px-3">
        <h1 className="text-sm font-semibold text-text-primary">{t("nav.cases")}</h1>
        <span className="rounded-sm bg-surface-higher px-1.5 py-px text-xs font-medium text-text-secondary">
          {cases.length}
        </span>
        <button
          type="button"
          onClick={() => void load()}
          aria-label={t("cases.refreshAria")}
          title={t("common.refresh")}
          className={iconBtnCls}
        >
          <RefreshCw size={14} aria-hidden />
        </button>
        <div className="flex-1" />
        <button type="button" onClick={() => void addCase()} className={primaryBtnCls}>
          <Plus size={14} aria-hidden />
          {t("cases.addCase")}
        </button>
      </header>
      {actionError && (
        <div
          role="alert"
          className="flex shrink-0 items-center gap-2 border-b border-border bg-danger/10 px-3 py-1.5 text-xs text-danger"
        >
          <span className="min-w-0 flex-1 truncate">{actionError}</span>
          <button
            type="button"
            onClick={() => setActionError(null)}
            aria-label={t("common.dismiss")}
            className="rounded-sm p-0.5 hover:bg-surface-higher"
          >
            <X size={12} aria-hidden />
          </button>
        </div>
      )}
      <div className="relative shrink-0 px-3 py-2">
        <Search
          size={14}
          className="pointer-events-none absolute left-5 top-1/2 -translate-y-1/2 text-text-secondary"
          aria-hidden
        />
        <input
          value={casesUi.query}
          onChange={(e) => setCasesUi({ query: e.target.value })}
          placeholder={t("cases.searchPlaceholder")}
          aria-label={t("cases.searchAria")}
          className="h-7 w-full rounded-sm border border-border bg-bg pl-7 pr-2 text-sm outline-none focus:border-accent"
        />
      </div>
      <div className="min-h-0 flex-1 overflow-auto">
        {loading && cases.length === 0 ? (
          <div className="flex items-center justify-center gap-2 py-6 text-xs text-text-secondary">
            <LoaderCircle size={12} className="animate-spin" aria-hidden />
            {t("cases.loading")}
          </div>
        ) : loadError ? (
          <p className="px-3 py-6 text-center text-sm text-danger">{loadError}</p>
        ) : (
          filtered.map((c) => (
            <div
              key={c.caseid}
              role="button"
              tabIndex={0}
              onClick={() => setCasesUi({ selectedId: c.caseid })}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") setCasesUi({ selectedId: c.caseid });
              }}
              className={cn(
                "flex cursor-pointer items-center gap-2 border-b border-border px-3 py-2 hover:bg-surface-higher",
                casesUi.selectedId === c.caseid && "bg-accent/10",
              )}
            >
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm font-medium">{c.name}</span>
                <span className="block truncate text-xs text-text-secondary">{c.date}</span>
              </span>
              <span className="flex shrink-0 gap-0.5">
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    void renameCase(c);
                  }}
                  aria-label={t("cases.renameFor", { name: c.name })}
                  title={t("cases.renameTitle")}
                  className={iconBtnCls}
                >
                  <Pencil size={13} aria-hidden />
                </button>
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    void deleteCase(c);
                  }}
                  aria-label={t("cases.deleteFor", { name: c.name })}
                  title={t("common.delete")}
                  className={cn(iconBtnCls, "hover:text-danger")}
                >
                  <Trash2 size={13} aria-hidden />
                </button>
              </span>
            </div>
          ))
        )}
        {!loading && filtered.length === 0 && (
          <p className="px-3 py-6 text-center text-sm text-text-secondary">
            {cases.length === 0 ? t("cases.empty") : t("cases.noMatch", { query: casesUi.query })}
          </p>
        )}
      </div>
    </aside>
  );
}

/** Center: details of the selected case. */
export function CaseDetails() {
  const { t } = useI18n();
  const cases = useProjectStore((s) => s.cases);
  const sources = useProjectStore((s) => s.sources);
  const casesUi = useProjectStore((s) => s.casesUi);
  const selectedId = casesUi.selectedId;

  const [actionError, setActionError] = useState<string | null>(null);
  const [files, setFiles] = useState<CaseFileLink[]>([]);
  const [filesLoading, setFilesLoading] = useState(false);
  const [memo, setMemo] = useState("");
  const [memoSaving, setMemoSaving] = useState(false);
  const [linkFid, setLinkFid] = useState("");
  const [caseAttrs, setCaseAttrs] = useState<{ name: string; value: string }[]>([]);

  const selected = useMemo(
    () => cases.find((c) => c.caseid === selectedId) ?? null,
    [cases, selectedId],
  );

  const loadFiles = useCallback(async (caseid: number) => {
    setFilesLoading(true);
    try {
      setFiles(await api.caseFiles(caseid));
    } catch (e) {
      setActionError(e instanceof Error ? e.message : t("cases.loadFilesError"));
    } finally {
      setFilesLoading(false);
    }
  }, [t]);

  const refreshAll = useCallback(async () => {
    await useProjectStore.getState().refreshProject();
    if (selectedId != null) await loadFiles(selectedId);
  }, [selectedId, loadFiles]);

  useEffect(() => {
    if (selectedId == null) {
      setFiles([]);
      setMemo("");
      setCaseAttrs([]);
      return;
    }
    setMemo(selected?.memo ?? "");
    void loadFiles(selectedId);
    void (async () => {
      try {
        const values = await api.attributeValues();
        setCaseAttrs(
          values
            .filter((v) => v.attr_type === "case" && v.id === selectedId)
            .map((v) => ({ name: v.name, value: v.value })),
        );
      } catch {
        setCaseAttrs([]);
      }
    })();
  }, [selectedId, loadFiles, selected?.memo]);

  const linkedFids = useMemo(() => new Set(files.map((f) => f.id)), [files]);
  const linkable = useMemo(
    () => sources.filter((s) => !linkedFids.has(s.id)),
    [sources, linkedFids],
  );

  async function saveMemo() {
    if (!selected || memoSaving) return;
    setMemoSaving(true);
    setActionError(null);
    try {
      await api.updateCase(selected.caseid, { memo });
      await refreshAll();
    } catch (e) {
      setActionError(e instanceof Error ? e.message : t("cases.memoSaveError"));
    } finally {
      setMemoSaving(false);
    }
  }

  async function unlinkFile(fid: number) {
    if (!selected) return;
    setActionError(null);
    try {
      await api.unlinkFileFromCase(selected.caseid, fid);
      await refreshAll();
    } catch (e) {
      setActionError(e instanceof Error ? e.message : t("cases.unlinkError"));
    }
  }

  async function linkFile() {
    if (!selected || !linkFid) return;
    setActionError(null);
    try {
      await api.linkFileToCase(selected.caseid, Number(linkFid));
      setLinkFid("");
      await refreshAll();
    } catch (e) {
      setActionError(e instanceof Error ? e.message : t("cases.linkError"));
    }
  }

  return (
    <section className="flex h-full min-w-0 flex-1 flex-col bg-bg">
      {actionError && (
        <div className="flex shrink-0 items-center gap-2 border-b border-border bg-surface px-3 py-1.5 text-sm text-danger">
          <CircleAlert size={14} aria-hidden />
          <span className="min-w-0 flex-1 truncate">{actionError}</span>
          <button
            type="button"
            onClick={() => setActionError(null)}
            aria-label={t("common.dismiss")}
            className="rounded-sm p-0.5 hover:bg-surface-higher"
          >
            <X size={14} aria-hidden />
          </button>
        </div>
      )}

      {!selected ? (
        <div className="flex flex-1 flex-col items-center justify-center gap-2 text-text-secondary">
          <UserRound size={24} aria-hidden />
          <p className="text-sm">{t("cases.selectHint")}</p>
        </div>
      ) : (
        <div className="min-h-0 flex-1 overflow-y-auto p-4">
          <h2 className="text-base font-semibold text-text-primary">{selected.name}</h2>
          <p className="mt-0.5 text-xs text-text-secondary">
            {t("cases.createdBy", { date: selected.date, owner: selected.owner })}
          </p>

          <section className="mt-4">
            <h3 className="text-xs font-medium uppercase tracking-wide text-text-secondary">
              {t("cases.memo")}
            </h3>
            <textarea
              value={memo}
              onChange={(e) => setMemo(e.target.value)}
              rows={3}
              placeholder={t("cases.memoPlaceholder")}
              aria-label={t("cases.memoAria")}
              className="mt-1.5 w-full resize-y rounded-sm border border-border bg-surface px-2 py-1.5 text-sm outline-none focus:border-accent"
            />
            <div className="mt-1.5 flex justify-end">
              <button
                type="button"
                onClick={() => void saveMemo()}
                disabled={memoSaving || memo === selected.memo}
                className={primaryBtnCls}
              >
                {memoSaving && <LoaderCircle size={12} className="animate-spin" aria-hidden />}
                {t("cases.saveMemo")}
              </button>
            </div>
          </section>

          <section className="mt-5">
            <h3 className="text-xs font-medium uppercase tracking-wide text-text-secondary">
              {t("cases.properties")}
            </h3>
            <div className="mt-1.5 rounded-sm border border-border p-2">
              <AttributeEditor
                key={selected.caseid}
                entityId={selected.caseid}
                scope="case"
                values={caseAttrs}
                onChange={async () => {
                  const values = await api.attributeValues();
                  setCaseAttrs(
                    values
                      .filter((v) => v.attr_type === "case" && v.id === selected.caseid)
                      .map((v) => ({ name: v.name, value: v.value })),
                  );
                }}
              />
            </div>
          </section>

          <section className="mt-5">
            <h3 className="text-xs font-medium uppercase tracking-wide text-text-secondary">
              {t("cases.memberFiles", { count: files.length })}
            </h3>
            <div className="mt-1.5 rounded-sm border border-border">
              {filesLoading && files.length === 0 ? (
                <div className="flex items-center justify-center gap-2 py-4 text-xs text-text-secondary">
                  <LoaderCircle size={12} className="animate-spin" aria-hidden />
                  {t("common.loading")}
                </div>
              ) : files.length === 0 ? (
                <p className="px-3 py-4 text-xs text-text-secondary">{t("cases.noFiles")}</p>
              ) : (
                <ul className="divide-y divide-border">
                  {files.map((f) => (
                    <li key={f.id} className="flex items-center gap-2 px-3 py-1.5">
                      <FileText size={14} className="shrink-0 text-text-secondary" aria-hidden />
                      <span className="min-w-0 flex-1 truncate text-sm">{f.name}</span>
                      <button
                        type="button"
                        onClick={() => void unlinkFile(f.id)}
                        aria-label={t("cases.unlinkFor", { name: f.name })}
                        title={t("cases.unlink")}
                        className={iconBtnCls}
                      >
                        <Unlink size={13} aria-hidden />
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </section>

          <section className="mt-5">
            <h3 className="text-xs font-medium uppercase tracking-wide text-text-secondary">
              {t("cases.linkFiles")}
            </h3>
            <div className="mt-1.5 flex items-center gap-2">
              <select
                value={linkFid}
                onChange={(e) => setLinkFid(e.target.value)}
                aria-label={t("cases.linkAria")}
                className="h-7 min-w-0 flex-1 rounded-sm border border-border bg-surface px-2 text-sm outline-none focus:border-accent"
              >
                <option value="">{t("cases.selectFilePlaceholder")}</option>
                {linkable.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
              </select>
              <button
                type="button"
                onClick={() => void linkFile()}
                disabled={!linkFid}
                className={primaryBtnCls}
              >
                <Link2 size={14} aria-hidden />
                {t("cases.link")}
              </button>
            </div>
            {linkable.length === 0 && (
              <p className="mt-1.5 text-xs text-text-secondary">{t("cases.allLinked")}</p>
            )}
          </section>
        </div>
      )}
    </section>
  );
}
