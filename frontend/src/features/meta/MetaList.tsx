/**
 * Meta-analysis left bar — the study list for the active pipeline tab plus
 * that tab's primary actions:
 *   Screen   → Import; filter chips, progress, stage switch, blind toggle
 *   Download → Download, Import PDFs (batch)
 *   Extract  → row checkboxes (the scheme picker lives in the center menubar)
 *   Analyze  → section navigation + scheme shown in the center
 *   Conflicts→ screening/extraction scope, screening stage, per-study list
 * A global coder/owner scope sits in the header for the Agreement
 * tab; on Extract the scope follows the app's current coder. Analyze always
 * pools every coder (consensus rows), so it shows no coder picker.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowDownToLine,
  ClipboardCheck,
  FileText,
  FlaskConical,
  FolderOpen,
  Grid3x3,
  Layers,
  Sigma,
  Table2,
  Trash2,
  Upload,
  Workflow,
} from "lucide-react";
import { api } from "@/lib/api";
import type { MetaConflictsResult, MetaHit, MetaStatus } from "@/lib/api/types";
import {
  BarHeader,
  BarTitle,
  Button,
  EmptyState,
  IconButton,
  Input,
  LeftBar,
  Select,
} from "@/components/ui/orchestrator";
import { useI18n } from "@/lib/i18n";
import { useToast } from "@/lib/toast";
import { cn, errorMessage } from "@/lib/utils";
import { useWorkspaceStore, type MetaAgreementScope, type MetaAnalysisSection, type MetaScreeningFilter } from "@/stores/workspace";

const CHECKBOX =
  "h-3.5 w-3.5 shrink-0 cursor-pointer rounded-sm border border-border accent-[var(--qc-accent)]";

/** Page size for the study list; further pages load on demand. */
const PAGE_SIZE = 100;

const SCREENING_FILTERS: MetaScreeningFilter[] = ["all", "todo", "screened", "included", "excluded"];
const ANALYSIS_SECTIONS: MetaAnalysisSection[] = [
  "pooled",
  "subgroup",
  "multiverse",
  "prisma",
  "audit",
  "summary",
  "report",
];

/** Icon per Analyze section, mirroring the reports left bar rows. */
const SECTION_ICONS: Record<
  MetaAnalysisSection,
  React.ComponentType<{ size?: number; className?: string; "aria-hidden"?: boolean }>
> = {
  pooled: Sigma,
  subgroup: Layers,
  multiverse: Grid3x3,
  prisma: Workflow,
  audit: ClipboardCheck,
  summary: Table2,
  report: FileText,
};

function scopeForTab(tab: string): "all" | "included" | "acquired" | null {
  if (tab === "download") return "included";
  if (tab === "extract") return "acquired";
  if (tab === "conflicts") return null;
  return "all";
}

function matchesFilter(hit: MetaHit, filter: MetaScreeningFilter): boolean {
  switch (filter) {
    case "todo":
      return !hit.screened;
    case "screened":
      return Boolean(hit.screened);
    case "included":
      return Boolean(hit.eligible);
    case "excluded":
      return Boolean(hit.screened) && !hit.eligible;
    default:
      return true;
  }
}

export function MetaList() {
  const { t } = useI18n();
  const toast = useToast();
  const tab = useWorkspaceStore((s) => s.metaUi.tab);
  const selectedHit = useWorkspaceStore((s) => s.metaUi.selectedHit);
  const selectedIds = useWorkspaceStore((s) => s.metaUi.selectedIds);
  const scheme = useWorkspaceStore((s) => s.metaUi.scheme);
  const email = useWorkspaceStore((s) => s.metaUi.email);
  const coderScope = useWorkspaceStore((s) => s.metaUi.coderScope);
  const screeningFilter = useWorkspaceStore((s) => s.metaUi.screeningFilter);
  const screeningStage = useWorkspaceStore((s) => s.metaUi.screeningStage);
  const blind = useWorkspaceStore((s) => s.metaUi.blind);
  const analysisSection = useWorkspaceStore((s) => s.metaUi.analysisSection);
  const agreementScope = useWorkspaceStore((s) => s.metaUi.agreementScope);
  const agreementStudy = useWorkspaceStore((s) => s.metaUi.agreementStudy);
  const tick = useWorkspaceStore((s) => s.metaUi.tick);
  const setMetaUi = useWorkspaceStore((s) => s.setMetaUi);

  const [hits, setHits] = useState<MetaHit[]>([]);
  const [total, setTotal] = useState(0);
  const [status, setStatus] = useState<MetaStatus | null>(null);
  const [conflicts, setConflicts] = useState<MetaConflictsResult | null>(null);
  const [coders, setCoders] = useState<string[]>([]);
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const pdfRef = useRef<HTMLInputElement | null>(null);

  const scope = scopeForTab(tab);
  // Screening and extraction both work through the per-row selection (screen
  // selection is inert for now; there is no batch endpoint for verdicts yet).
  const selectionEnabled = tab === "screen" || tab === "extract";

  // Mirror the loaded hits into the shared store so the verdict pane can
  // navigate next/previous without re-fetching the list.
  useEffect(() => {
    if (tab === "analyze" || tab === "conflicts") return;
    setMetaUi({ hits });
  }, [hits, tab, setMetaUi]);

  const reload = useCallback(() => {
    setMetaUi({ tick: useWorkspaceStore.getState().metaUi.tick + 1 });
  }, [setMetaUi]);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const needsHits = tab !== "analyze" && tab !== "conflicts";
        const [res, stat, coderRes] = await Promise.all([
          needsHits
            ? api.metaHits({ scope: scope ?? "all", limit: PAGE_SIZE, offset: 0 })
            : Promise.resolve(null),
          api.metaStatus().catch(() => null),
          tab === "analyze" || tab === "conflicts"
            ? api.coders().catch(() => null)
            : Promise.resolve(null),
        ]);
        if (cancelled) return;
        if (res) {
          setHits(res.hits);
          setTotal(res.total);
        } else {
          setHits([]);
          setTotal(0);
        }
        setStatus(stat);
        if (coderRes) setCoders(coderRes.coders?.map((c) => c.name) ?? []);
        setError(null);
      } catch (err) {
        if (!cancelled) setError(errorMessage(err));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [scope, tab, tick]);

  // The conflicts tab lists studies with their open/settled counts (the
  // reliability + conflict rows themselves render in the center panel).
  useEffect(() => {
    if (tab !== "conflicts") return;
    let cancelled = false;
    void (async () => {
      try {
        const res =
          agreementScope === "screening"
            ? await api.metaScreeningConflicts({ stage: screeningStage })
            : await api.metaExtractionConflicts({ scheme: scheme || undefined });
        if (!cancelled) setConflicts(res as MetaConflictsResult);
      } catch {
        if (!cancelled) setConflicts(null);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [tab, agreementScope, screeningStage, scheme, tick]);

  const loadMore = async () => {
    setLoadingMore(true);
    try {
      const res = await api.metaHits({ scope: scope ?? "all", limit: PAGE_SIZE, offset: hits.length });
      setHits((prev) => [...prev, ...res.hits]);
      setTotal(res.total);
      setError(null);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoadingMore(false);
    }
  };

  const deleteHit = async (hit: MetaHit) => {
    if (!window.confirm(t("meta.confirmDelete", { title: hit.title }))) return;
    setBusy(true);
    try {
      await api.metaDeleteHit(hit.hit_id);
      if (selectedHit?.hit_id === hit.hit_id) setMetaUi({ selectedHit: null });
      setMetaUi({ tick: useWorkspaceStore.getState().metaUi.tick + 1 });
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return hits.filter((h) => {
      if (tab === "screen" && !matchesFilter(h, screeningFilter)) return false;
      if (!q) return true;
      return [h.title, h.authors, h.doi].some((v) => (v ?? "").toString().toLowerCase().includes(q));
    });
  }, [hits, query, tab, screeningFilter]);

  const screenedCount = useMemo(() => {
    // `screened_hits` counts distinct hits with an abstract screening row, so
    // it matches the To-screen/Screened filters (the old `by_status` hit-status
    // tally disagreed with the list, e.g. "0 to screen" but "4/10 screened").
    if (typeof status?.screened_hits === "number") return status.screened_hits;
    return hits.filter((h) => h.screened).length;
  }, [status, hits]);
  const progressTotal = status?.hits ?? total;
  const progressPct = progressTotal ? Math.min(100, Math.round((screenedCount / progressTotal) * 1000) / 10) : 0;

  // Screening progress — shared by the Screen and Extract left bars.
  const progress = (
    <div className="flex items-center gap-2">
      <div className="flex-1">
        <div className="mb-0.5 flex items-center justify-between text-[10px] text-text-secondary">
          <span>{t("meta.screenedProgress", { done: screenedCount, total: progressTotal })}</span>
          <span>{progressPct}%</span>
        </div>
        <div className="h-1 w-full overflow-hidden rounded-full bg-surface-higher">
          <div className="h-full rounded-full bg-accent" style={{ width: `${progressPct}%` }} />
        </div>
      </div>
    </div>
  );

  // Documents progress — the Download left bar's own indicator, distinct from
  // screening. `total` is the backend's document tally when present, else the
  // eligible-hits count (so the bar still reads before the first download).
  const docCounts = status?.documents;
  const docsDone = docCounts?.done ?? status?.documents_done ?? 0;
  const docsFailed = docCounts?.failed ?? 0;
  const eligibleTotal = status?.eligible || status?.tabs?.downloads || 0;
  const docsTotal =
    typeof docCounts?.total === "number" && docCounts.total > 0 ? docCounts.total : eligibleTotal;
  const docsPct = docsTotal ? Math.min(100, Math.round((docsDone / docsTotal) * 1000) / 10) : 0;

  const documentsProgress = (
    <div className="flex items-center gap-2">
      <div className="flex-1">
        <div className="mb-0.5 flex items-center justify-between text-[10px] text-text-secondary">
          <span>{t("meta.documentsProgress", { done: docsDone, total: docsTotal })}</span>
          <span className="flex items-center gap-1.5">
            {docsFailed > 0 ? (
              <span className="text-danger" title={t("meta.documentsFailed", { count: docsFailed })}>
                {t("meta.documentsFailed", { count: docsFailed })}
              </span>
            ) : null}
            <span>{docsPct}%</span>
          </span>
        </div>
        <div className="h-1 w-full overflow-hidden rounded-full bg-surface-higher">
          <div className="h-full rounded-full bg-accent" style={{ width: `${docsPct}%` }} />
        </div>
      </div>
    </div>
  );

  const toggleId = (id: number) =>
    setMetaUi({
      selectedIds: selectedIds.includes(id)
        ? selectedIds.filter((x) => x !== id)
        : [...selectedIds, id],
    });

  const visibleIds = filtered.map((h) => h.hit_id);
  const allSelected = visibleIds.length > 0 && visibleIds.every((id) => selectedIds.includes(id));
  const toggleAll = () =>
    setMetaUi({
      selectedIds: allSelected
        ? selectedIds.filter((id) => !visibleIds.includes(id))
        : Array.from(new Set([...selectedIds, ...visibleIds])),
    });

  const runDownloads = async () => {
    try {
      await api.metaDownloadRun({ email: email.trim() || undefined });
      toast.success(t("meta.downloadStarted"));
      reload();
    } catch (err) {
      toast.error(errorMessage(err));
    }
  };

  const importPdfs = async (files: FileList | null) => {
    if (!files || files.length === 0) return;
    setBusy(true);
    try {
      const res = await api.metaAssignPdfs(Array.from(files));
      toast.success(
        t("meta.batchImportResult", {
          assigned: String(res.assigned.length),
          unmatched: String(res.unmatched.length),
          failed: String(res.failed.length),
        }),
      );
      reload();
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setBusy(false);
      if (pdfRef.current) pdfRef.current.value = "";
    }
  };

  const coderSelect = (
    <Select
      value={coderScope}
      onChange={(e) => setMetaUi({ coderScope: e.target.value, coderScopeCustom: true })}
      className="h-7 w-28 text-xs"
      aria-label={t("meta.coderScope")}
      title={t("meta.coderScope")}
    >
      {coders.map((name) => (
        <option key={name} value={name}>
          {name}
        </option>
      ))}
      <option value="">{t("meta.allCoders")}</option>
    </Select>
  );

  const selectAllControl = (
    <label className="flex items-center gap-1.5 text-[11px] text-text-secondary">
      {selectionEnabled && (
        <>
          <input
            type="checkbox"
            checked={allSelected}
            onChange={toggleAll}
            className={CHECKBOX}
            aria-label={t("meta.selectAll")}
            title={t("meta.selectAll")}
          />
          <span>{t("meta.selectedCount", { count: String(selectedIds.length) })}</span>
        </>
      )}
    </label>
  );

  return (
    <LeftBar
      borderSide="r"
      className="h-full min-h-0"
      scroll={false}
      header={
        <BarHeader
          title={<BarTitle icon={FlaskConical} label={t("meta.listTitle")} />}
          count={tab === "analyze" ? undefined : tab === "conflicts" ? conflicts?.total : total}
        >
          {tab === "screen" && (
            <>
              <Button
                variant="secondary"
                icon={<Upload size={12} aria-hidden />}
                onClick={() => setMetaUi({ importOpen: true })}
              >
                {t("meta.importSearch")}
              </Button>
              <Button
                variant="secondary"
                icon={<FolderOpen size={12} aria-hidden />}
                title={t("meta.codingStudioTitle")}
                onClick={() => setMetaUi({ codingStudioOpen: true })}
              >
                {t("meta.codingStudioImport")}
              </Button>
            </>
          )}
          {tab === "download" && (
            <>
              <Button
                variant="primary"
                icon={<ArrowDownToLine size={12} aria-hidden />}
                onClick={() => void runDownloads()}
              >
                {t("meta.runDownloads")}
              </Button>
              <Button
                variant="secondary"
                icon={<Upload size={12} aria-hidden />}
                disabled={busy}
                onClick={() => pdfRef.current?.click()}
              >
                {t("meta.importPdfs")}
              </Button>
              <input
                ref={pdfRef}
                type="file"
                accept=".pdf"
                multiple
                hidden
                aria-hidden
                onChange={(e) => void importPdfs(e.target.files)}
              />
            </>
          )}
          {tab === "conflicts" && coderSelect}
        </BarHeader>
      }
    >
      {error && (
        <div
          className="flex shrink-0 items-center gap-2 border-b border-danger bg-danger/10 px-3 py-1.5 text-sm text-danger"
          role="alert"
        >
          <span className="min-w-0 flex-1 truncate">{error}</span>
          <button
            type="button"
            onClick={reload}
            className="shrink-0 rounded-sm border border-border px-1.5 py-0.5 text-[11px] qc-motion hover:bg-surface-higher"
          >
            {t("common.retry")}
          </button>
        </div>
      )}
      {tab === "screen" && (
        <div className="shrink-0 space-y-1.5 border-b border-border px-2 py-1.5">
          <div className="flex flex-wrap items-center gap-1">
            {SCREENING_FILTERS.map((filter) => (
              <button
                key={filter}
                type="button"
                onClick={() => setMetaUi({ screeningFilter: filter })}
                aria-pressed={screeningFilter === filter}
                className={`rounded-sm px-1.5 py-0.5 text-[11px] font-medium qc-motion ${
                  screeningFilter === filter
                    ? "bg-surface-higher text-accent"
                    : "text-text-secondary hover:bg-surface-higher"
                }`}
              >
                {t(`meta.filter_${filter}`)}
              </button>
            ))}
          </div>
          {progress}
        </div>
      )}

      {tab === "download" && (
        <div className="shrink-0 border-b border-border px-2 py-1.5">{documentsProgress}</div>
      )}

      {tab === "extract" && (
        <div className="shrink-0 border-b border-border px-2 py-1.5">{progress}</div>
      )}

      {tab === "conflicts" && (
        <>
          {/* Scope (Screening/Extraction) and stage (Abstract/Full-text) share
              one row as two compact segmented switches. */}
          <div className="flex shrink-0 items-center gap-3 border-b border-border px-2 py-1.5">
            <div
              className="flex items-center gap-1"
              role="group"
              aria-label={t("meta.agreementTitle")}
            >
              {(["screening", "extraction"] as MetaAgreementScope[]).map((s) => (
                <button
                  key={s}
                  type="button"
                  onClick={() => setMetaUi({ agreementScope: s, agreementStudy: "" })}
                  aria-pressed={agreementScope === s}
                  className={`rounded-sm px-1.5 py-0.5 text-[11px] font-medium qc-motion ${
                    agreementScope === s
                      ? "bg-surface-higher text-accent"
                      : "text-text-secondary hover:bg-surface-higher"
                  }`}
                >
                  {s === "screening" ? t("meta.agreementScreening") : t("meta.agreementExtraction")}
                </button>
              ))}
            </div>
            {agreementScope === "screening" && (
              <div
                className="flex items-center gap-1"
                role="group"
                aria-label={t("meta.stageFulltext")}
              >
                {(["abstract", "fulltext"] as const).map((stage) => (
                  <button
                    key={stage}
                    type="button"
                    onClick={() => setMetaUi({ screeningStage: stage })}
                    aria-pressed={screeningStage === stage}
                    className={`rounded-sm px-1.5 py-0.5 text-[11px] font-medium qc-motion ${
                      screeningStage === stage
                        ? "bg-surface-higher text-accent"
                        : "text-text-secondary hover:bg-surface-higher"
                    }`}
                  >
                    {stage === "abstract" ? t("meta.stageAbstract") : t("meta.stageFulltext")}
                  </button>
                ))}
              </div>
            )}
          </div>
          <div className="qc-scroll min-h-0 flex-1 overflow-y-auto">
            <button
              type="button"
              onClick={() => setMetaUi({ agreementStudy: "" })}
              aria-pressed={agreementStudy === ""}
              className={cn(
                "flex w-full items-center gap-2 border-b border-border px-3 py-2 text-left qc-motion hover:bg-surface-higher",
                agreementStudy === "" && "bg-accent/10 text-accent",
              )}
            >
              <span className="min-w-0 flex-1 truncate text-sm font-medium">
                {t("meta.conflictStudyAll")}
              </span>
              <span className="shrink-0 rounded-sm bg-warning/10 px-1.5 py-px text-[10px] text-warning">
                {conflicts?.total ?? 0}
              </span>
            </button>
            {(conflicts?.studies ?? []).map((study) => {
              const key = String(study.key);
              const active = agreementStudy === key;
              return (
                <button
                  key={key}
                  type="button"
                  onClick={() => setMetaUi({ agreementStudy: active ? "" : key })}
                  aria-pressed={active}
                  className={cn(
                    "flex w-full items-center gap-2 border-b border-border px-3 py-2 text-left qc-motion hover:bg-surface-higher",
                    active && "bg-accent/10 text-accent",
                  )}
                >
                  <span className="min-w-0 flex-1 truncate text-sm">{study.label}</span>
                  {study.n_open > 0 ? (
                    <span
                      className="shrink-0 rounded-sm bg-warning/10 px-1.5 py-px text-[10px] text-warning"
                      title={t("meta.conflictOpen")}
                    >
                      {study.n_open}
                    </span>
                  ) : null}
                  {study.n_settled > 0 ? (
                    <span
                      className="shrink-0 rounded-sm bg-success/10 px-1.5 py-px text-[10px] text-success"
                      title={t("meta.conflictSettled")}
                    >
                      {study.n_settled}
                    </span>
                  ) : null}
                </button>
              );
            })}
            {(conflicts?.studies ?? []).length === 0 ? (
              <EmptyState>{t("meta.conflictsEmpty")}</EmptyState>
            ) : null}
          </div>
        </>
      )}

      {tab === "analyze" ? (
        <div className="qc-scroll min-h-0 flex-1 overflow-y-auto">
          {ANALYSIS_SECTIONS.map((section) => {
            const Icon = SECTION_ICONS[section];
            const active = analysisSection === section;
            return (
              <div
                key={section}
                role="button"
                tabIndex={0}
                onClick={() => setMetaUi({ analysisSection: section })}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") setMetaUi({ analysisSection: section });
                }}
                aria-label={t(`meta.section_${section}`)}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "flex cursor-pointer items-center gap-2 border-b border-border px-3 py-2 hover:bg-surface-higher",
                  active && "bg-accent/10 text-accent",
                )}
              >
                <Icon size={14} className="shrink-0 text-text-secondary" aria-hidden />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-medium">
                    {t(`meta.section_${section}`)}
                  </span>
                  <span className="block truncate text-xs text-text-secondary">
                    {t(`meta.section_${section}_hint`)}
                  </span>
                </span>
              </div>
            );
          })}
        </div>
      ) : tab === "conflicts" ? null : (
        <>
          <div className="flex items-center gap-2 border-b border-border px-2 py-1.5">
            <Input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={t("meta.filterHits")}
              className="h-7 min-w-0 flex-1 text-xs"
              aria-label={t("meta.filterHits")}
            />
            {selectAllControl}
          </div>
          <div className="qc-scroll min-h-0 flex-1 overflow-y-auto">
            {filtered.length === 0 ? (
              <EmptyState>
                {error ? t("meta.loadFailed") : total === 0 ? t("meta.noEligible") : t("meta.noMatches")}
              </EmptyState>
            ) : (
              <ul>
                {filtered.map((hit) => {
                  const checked = selectedIds.includes(hit.hit_id);
                  const active = selectedHit?.hit_id === hit.hit_id;
                  return (
                    <li
                      key={hit.hit_id}
                      className={`flex items-start gap-2 border-b border-border px-3 py-1.5 qc-motion ${
                        active ? "bg-accent/10" : "hover:bg-surface-higher"
                      }`}
                    >
                      {selectionEnabled && (
                        <input
                          type="checkbox"
                          checked={checked}
                          onChange={() => toggleId(hit.hit_id)}
                          className={`${CHECKBOX} mt-0.5`}
                          aria-label={hit.title}
                        />
                      )}
                      <button
                        type="button"
                        onClick={() => setMetaUi({ selectedHit: hit })}
                        title={hit.title}
                        className="flex min-w-0 flex-1 flex-col gap-0.5 text-left"
                      >
                        <span className="truncate text-sm text-text-primary">{hit.title}</span>
                        <span className="flex items-center gap-1.5 truncate text-xs text-text-secondary">
                          <span className="truncate">
                            {hit.authors ?? ""} {hit.year ? `· ${hit.year}` : ""}
                          </span>
                          {tab === "screen" && hit.screened && !blind ? (
                            <span
                              className={`shrink-0 rounded-sm px-1 text-[10px] font-medium ${
                                hit.eligible ? "bg-success/10 text-success" : "bg-danger/10 text-danger"
                              }`}
                            >
                              {hit.eligible ? t("meta.hitEligible") : t("meta.excluded")}
                            </span>
                          ) : null}
                        </span>
                      </button>
                      <IconButton
                        label={t("meta.deleteHit")}
                        title={t("meta.deleteHit")}
                        size="sm"
                        disabled={busy}
                        className="mt-0.5 shrink-0 disabled:opacity-30"
                        onClick={() => void deleteHit(hit)}
                      >
                        <Trash2 size={11} aria-hidden />
                      </IconButton>
                    </li>
                  );
                })}
              </ul>
            )}
            {total > hits.length && (
              <div className="flex items-center justify-between gap-2 px-3 py-2">
                <span className="text-[11px] text-text-secondary">
                  {t("meta.pageOf", { from: 1, to: hits.length, total })}
                </span>
                <Button
                  variant="secondary"
                  disabled={loadingMore}
                  onClick={() => void loadMore()}
                >
                  {t("meta.next")}
                </Button>
              </div>
            )}
          </div>
        </>
      )}
    </LeftBar>
  );
}
