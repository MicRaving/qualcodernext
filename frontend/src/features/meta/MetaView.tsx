/**
 * Meta-analysis workspace — hits move through abstract screening, paper
 * download, data extraction and conflict settling. Tab-specific controls live
 * in the center menubar and the study left bar; the center shows the work for
 * the focused (or selected) study: its abstract + verdicts, the download
 * table, the scheme-driven coding form, or the reliability/conflict panel.
 * The Extract tab's right bar shows the study's linked paper.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowDownToLine,
  Check,
  ChevronDown,
  ChevronUp,
  FilePlus2,
  FileSpreadsheet,
  Handshake,
  LoaderCircle,
  Pause,
  Play,
  Search,
  Settings2,
  Sparkles,
  Trash2,
  X,
} from "lucide-react";
import { api, localRequestBlob } from "@/lib/api";
import type {
  MetaCriterion,
  MetaDocument,
  MetaExtraction,
  MetaHit,
  MetaJob,
  MetaModerator,
  MetaPoolModel,
  MetaScheme,
  MetaScreening,
} from "@/lib/api/types";
import {
  Button,
  EmptyState,
  ErrorBanner,
  IconButton,
  Input,
  LoadingState,
  Select,
  TableHead,
  Textarea,
  Toggle,
  ViewHeader,
} from "@/components/ui/orchestrator";
import { useI18n } from "@/lib/i18n";
import { useToast } from "@/lib/toast";
import { errorMessage } from "@/lib/utils";
import { useWorkspaceStore, type MetaTab } from "@/stores/workspace";
import { useCoderStore } from "@/stores/coder";
import { MetaImportDialog } from "@/features/meta/MetaImportDialog";
import { MetaSchemeEditor } from "@/features/meta/MetaSchemeEditor";
import { MetaCriteriaEditor, type MetaCriterionDraft } from "@/features/meta/MetaCriteriaEditor";
import { MetaExtractionForm } from "@/features/meta/MetaExtractionForm";
import { MetaFulltextPanel } from "@/features/meta/MetaFulltextPanel";
import { MetaAgreementPanel } from "@/features/meta/MetaAgreementDialog";
import { MetaAnalyze } from "@/features/meta/MetaAnalyze";
import { useMetaCoderScope } from "@/features/meta/useMetaCoderScope";

const VERDICT_CHOICES = ["Yes", "No", "Unsure"] as const;
const CERTAINTY_CHOICES = ["High", "Medium", "Low"] as const;

/** Frequentist estimator options shown in the Analyze menubar. */
const POOL_MODELS: { value: MetaPoolModel; labelKey: string }[] = [
  { value: "dl", labelKey: "meta.poolModelDl" },
  { value: "two_level", labelKey: "meta.poolModelTwoLevel" },
  { value: "fixed", labelKey: "meta.poolModelFixed" },
];

/** Table body cell (mirrors the report tables' `tdCls`). */
const TD = "border-b border-border px-3 py-1.5 text-sm align-top";

function statusBadgeClass(status: string): string {
  switch (status) {
    case "included":
    case "downloaded":
    case "extracted":
    case "done":
      return "bg-success/10 text-success";
    case "excluded":
    case "failed":
      return "bg-danger/10 text-danger";
    case "working":
      return "bg-warning/10 text-warning";
    default:
      return "bg-surface-higher text-text-secondary";
  }
}

/** i18n key for a status value; unknown statuses fall back to the raw text. */
function statusKey(status: string): string {
  return `meta.status_${status}`;
}

/** i18n key for a job kind (reuses the pipeline tab labels). */
function jobKindKey(kind: string): string {
  return kind === "screen"
    ? "meta.jobScreen"
    : kind === "download"
      ? "meta.jobDownload"
      : "meta.jobExtract";
}

function isRunning(job: MetaJob): boolean {
  return job.state === "running" || job.state === "queued";
}

/** i18n key for a job's state chip (cancelled/paused included). */
function jobStateKey(state: string): string {
  return state === "done"
    ? "meta.jobDone"
    : state === "error"
      ? "meta.jobFailed"
      : state === "cancelled"
        ? "meta.jobCancelled"
        : state === "paused"
          ? "meta.jobPaused"
          : state === "queued"
            ? "meta.jobQueued"
            : "meta.jobRunning";
}

/** MetaCriterion (v1/v2) → editor draft. */
function criterionToDraft(c: MetaCriterion): MetaCriterionDraft {
  return {
    id: c.id,
    key: c.key,
    label: c.label,
    prompt_text: c.prompt_text,
    kind: c.kind ?? "verdict",
    options: c.options ?? [],
    pass_values: c.pass_values ?? ["yes"],
    exclude_reason: c.exclude_reason ?? "",
    gating: c.gating === undefined ? true : Boolean(c.gating),
    help: c.help ?? "",
  };
}

/** Editor draft → MetaCriterion (position + key defaulted). */
function draftToCriterion(d: MetaCriterionDraft, index: number): MetaCriterion {
  return {
    id: d.id ?? -(index + 1),
    position: index,
    key: d.key || `criterion${index + 1}`,
    label: d.label,
    prompt_text: d.prompt_text,
    created: "",
    kind: d.kind,
    options: d.options,
    pass_values: d.pass_values,
    exclude_reason: d.exclude_reason,
    gating: d.gating,
    help: d.help,
  };
}

function criterionPasses(c: MetaCriterion, applies: string | undefined): boolean {
  const pass = (c.pass_values && c.pass_values.length > 0 ? c.pass_values : ["yes"]).map((v) =>
    String(v).toLowerCase(),
  );
  return pass.includes(String(applies ?? "").toLowerCase());
}

function isGating(c: MetaCriterion): boolean {
  return !(c.gating === false || c.gating === 0);
}

/** First failing gating criterion → its PRISMA exclusion reason. */
function derivedExclusionReason(
  criteria: MetaCriterion[],
  verdicts: Record<string, { applies: string; certainty: string }>,
): { label: string; reason: string } | null {
  for (const c of criteria) {
    if (!isGating(c)) continue;
    if (!criterionPasses(c, verdicts[c.key]?.applies)) {
      return { label: c.label, reason: c.exclude_reason || c.label || c.key };
    }
  }
  return null;
}

/** A not-yet-saved extraction for a study that has no row yet. */
function blankExtractionFor(hit: MetaHit, scheme: string, owner: string): MetaExtraction {
  return {
    id: -hit.hit_id,
    hit_id: hit.hit_id,
    owner,
    scheme,
    study_vars: { records: [] },
    dv_metrics: [],
    status: "pending",
    title: hit.title,
    created: "",
    updated: "",
  };
}

export function MetaView() {
  const { t } = useI18n();
  const toast = useToast();
  const tab = useWorkspaceStore((s) => s.metaUi.tab);
  const selectedHit = useWorkspaceStore((s) => s.metaUi.selectedHit);
  const hits = useWorkspaceStore((s) => s.metaUi.hits);
  const selectedIds = useWorkspaceStore((s) => s.metaUi.selectedIds);
  const scheme = useWorkspaceStore((s) => s.metaUi.scheme);
  const email = useWorkspaceStore((s) => s.metaUi.email);
  const importOpen = useWorkspaceStore((s) => s.metaUi.importOpen);
  const schemeOpen = useWorkspaceStore((s) => s.metaUi.schemeOpen);
  const screeningStage = useWorkspaceStore((s) => s.metaUi.screeningStage);
  const blind = useWorkspaceStore((s) => s.metaUi.blind);
  /** Screening on the Screen tab is always abstract-stage; the full-text stage
   *  lives in the Extraction tab (exclusion dropdown) and the Conflicts tab. */
  const effectiveScreeningStage = tab === "screen" ? "abstract" : screeningStage;
  const coderScope = useWorkspaceStore((s) => s.metaUi.coderScope);
  const coderName = useCoderStore((s) => s.coderName);
  // Keep the scope pinned to the app's current coder until the user picks one.
  useMetaCoderScope();
  /** Effective writer for every meta mutation: the scoped coder, or the app's
   *  current coder when the scope is "All coders". */
  const writeOwner = coderScope || coderName;
  const analysisModel = useWorkspaceStore((s) => s.metaUi.analysisModel);
  const poolModel = useWorkspaceStore((s) => s.metaUi.poolModel);
  const analysisSection = useWorkspaceStore((s) => s.metaUi.analysisSection);
  const subgroupBy = useWorkspaceStore((s) => s.metaUi.subgroupBy);
  const tick = useWorkspaceStore((s) => s.metaUi.tick);
  const setMetaUi = useWorkspaceStore((s) => s.setMetaUi);

  const [criteria, setCriteria] = useState<MetaCriterion[]>([]);
  const [criteriaDrafts, setCriteriaDrafts] = useState<MetaCriterionDraft[]>([]);
  const draftIdRef = useRef(-1);
  const persistTimerRef = useRef<number | null>(null);
  const [schemes, setSchemes] = useState<MetaScheme[]>([]);
  const [moderators, setModerators] = useState<MetaModerator[]>([]);
  const [documents, setDocuments] = useState<MetaDocument[]>([]);
  const [extractions, setExtractions] = useState<MetaExtraction[]>([]);
  const [status, setStatus] = useState<{
    hits: number;
    criteria: number;
    schemes: number;
    eligible: number;
    documents_done: number;
    extracted: number;
  } | null>(null);
  const [jobs, setJobs] = useState<MetaJob[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Screening controls (center menubar).
  const [runId, setRunId] = useState("");
  const [clusterSize, setClusterSize] = useState(8);

  // Extraction controls (extract tab menubar).
  const [maxInputChars, setMaxInputChars] = useState(120000);
  const [fulltextOnly, setFulltextOnly] = useState(true);

  // Full-text screening (extraction tab): the focused study's full-text
  // screening row, edited through the criteria panel above the coding form.
  const [fulltextScreening, setFulltextScreening] = useState<MetaScreening | null>(null);

  const [showCriteria, setShowCriteria] = useState(false);
  const [selectedScreening, setSelectedScreening] = useState<MetaScreening | null>(null);
  const [formExtraction, setFormExtraction] = useState<MetaExtraction | null>(null);
  const formExtractionSigRef = useRef("");

  /** Bump the shared data version so both this view and the left bar reload. */
  const refresh = useCallback(() => {
    setMetaUi({ tick: useWorkspaceStore.getState().metaUi.tick + 1 });
  }, [setMetaUi]);

  const load = useCallback(
    async (isCancelled?: () => boolean) => {
      try {
        const [c, s, d, e, st, mods] = await Promise.all([
          api.metaCriteria(),
          api.metaSchemes(),
          api.metaDocuments(),
          api.metaExtractions(undefined, writeOwner || undefined),
          api.metaStatus(),
          tab === "analyze"
            ? api.metaModerators().catch(() => [] as MetaModerator[])
            : Promise.resolve([] as MetaModerator[]),
        ]);
        if (isCancelled?.()) return;
        setCriteria(c);
        setCriteriaDrafts(c.map(criterionToDraft));
        setSchemes(s);
        setModerators(mods);
        setDocuments(d);
        setExtractions(e);
        setStatus(st);
        const current = useWorkspaceStore.getState().metaUi.scheme;
        if (s.length > 0 && (!current || !s.some((x) => x.name === current))) {
          setMetaUi({ scheme: s[0].name });
        }
        // Default the Analyze subgroup picker to the first available variable.
        const currentSub = useWorkspaceStore.getState().metaUi.subgroupBy;
        if (mods.length > 0 && (!currentSub || !mods.some((m) => m.name === currentSub))) {
          setMetaUi({ subgroupBy: mods[0].name });
        }
        setError(null);
      } catch (err) {
        if (isCancelled?.()) return;
        // Surface a real load failure instead of spinning forever; a transient
        // miss keeps whatever is already loaded.
        setError(errorMessage(err));
        setStatus((prev) =>
          prev ?? { hits: 0, criteria: 0, schemes: 0, eligible: 0, documents_done: 0, extracted: 0 },
        );
      }
    },
    [setMetaUi, writeOwner, tab],
  );

  const loadJobs = useCallback(async () => {
    try {
      setJobs(await api.metaJobs());
    } catch {
      /* no project open */
    }
  }, []);

  // Keep the latest `load` reachable from the polling interval without
  // restarting it every time `scheme` changes.
  const loadRef = useRef(load);
  useEffect(() => {
    loadRef.current = load;
  }, [load]);

  // Reload data + jobs on tab change and whenever a mutation bumps the tick
  // (including mutations performed by the study left bar). The cancelled flag
  // drops an out-of-order response when the scope/tab changes mid-flight.
  useEffect(() => {
    let cancelled = false;
    void load(() => cancelled);
    void loadJobs();
    return () => {
      cancelled = true;
    };
  }, [tab, tick, writeOwner, load, loadJobs]);

  // Poll only while a job is running; reload the data once when it settles.
  const runningKey = useMemo(
    () => jobs.filter(isRunning).map((j) => j.id).sort().join(","),
    [jobs],
  );
  useEffect(() => {
    if (!runningKey) return;
    let cancelled = false;
    const timer = window.setInterval(() => {
      void (async () => {
        try {
          const next = await api.metaJobs();
          if (cancelled) return;
          setJobs(next);
          if (!next.some(isRunning)) {
            window.clearInterval(timer);
            void loadRef.current(() => cancelled);
          }
        } catch {
          /* transient */
        }
      })();
    }, 2000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [runningKey]);

  const finishedJobs = jobs.filter((j) => !isRunning(j));

  // Group the moderator catalogue by its codebook group (study/metric fallback).
  const moderatorGroups = useMemo(() => {
    const groups: [string, MetaModerator[]][] = [];
    for (const entry of moderators) {
      const group =
        entry.group || (entry.kind === "metric" ? t("meta.unitMetric") : t("meta.unitStudy"));
      const bucket = groups.find(([name]) => name === group);
      if (bucket) bucket[1].push(entry);
      else groups.push([group, [entry]]);
    }
    return groups;
  }, [moderators, t]);

  // ── criteria ────────────────────────────────────────────────────────

  // Criteria are persisted automatically (debounced) instead of an explicit
  // save step: they are project data like everything else. New drafts get a
  // stable negative id so the editor's controlled inputs keep their focus.
  const persistCriteria = async (list: MetaCriterion[]) => {
    try {
      await api.metaReplaceCriteria(list.map((c, i) => ({ ...c, position: i })));
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("meta.criteriaSaveFailed"));
    }
  };

  const pendingCriteriaRef = useRef<MetaCriterion[] | null>(null);

  const updateCriteriaDrafts = (next: MetaCriterionDraft[]) => {
    const withIds = next.map((d) => (d.id !== undefined ? d : { ...d, id: draftIdRef.current-- }));
    setCriteriaDrafts(withIds);
    const mapped = withIds.map(draftToCriterion);
    setCriteria(mapped);
    pendingCriteriaRef.current = mapped;
    if (persistTimerRef.current) window.clearTimeout(persistTimerRef.current);
    persistTimerRef.current = window.setTimeout(() => {
      persistTimerRef.current = null;
      pendingCriteriaRef.current = null;
      void persistCriteria(mapped);
    }, 600);
  };

  // Flush a pending debounced save when the view unmounts so the last edit is
  // not silently dropped (e.g. switching tabs right after typing).
  useEffect(
    () => () => {
      if (persistTimerRef.current) {
        window.clearTimeout(persistTimerRef.current);
        persistTimerRef.current = null;
        if (pendingCriteriaRef.current) void persistCriteria(pendingCriteriaRef.current);
        pendingCriteriaRef.current = null;
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );

  // ── screening ───────────────────────────────────────────────────────

  const startLlmScreen = async () => {
    if (busy) return;
    setBusy(true);
    try {
      await api.metaLlmScreen({ run_id: runId, cluster_size: clusterSize });
      toast.success(t("meta.screenStarted"));
      void loadJobs();
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const refreshSelectedScreening = useCallback(
    async (hitId: number, stage: string, isCancelled?: () => boolean) => {
      try {
        // Scope the fetch to the active coder so the verdicts shown are the
        // ones the next save would overwrite.
        const rows = await api.metaScreening({
          hit_id: hitId,
          stage,
          owner: writeOwner || undefined,
        });
        if (isCancelled?.()) return;
        const latest = rows.reduce<MetaScreening | null>(
          (best, row) => (!best || row.id > best.id ? row : best),
          null,
        );
        setSelectedScreening(latest);
      } catch {
        if (!isCancelled?.()) setSelectedScreening(null);
      }
    },
    [writeOwner],
  );

  // Focus the study chosen in the left bar and load its verdicts for the
  // active screening stage. `writeOwner` is a dependency because the owner
  // scope decides whose verdicts are shown (and written back).
  useEffect(() => {
    let cancelled = false;
    if (!selectedHit) {
      setSelectedScreening(null);
      return;
    }
    setSelectedScreening(null);
    void refreshSelectedScreening(selectedHit.hit_id, effectiveScreeningStage, () => cancelled);
    return () => {
      cancelled = true;
    };
  }, [selectedHit, effectiveScreeningStage, writeOwner, refreshSelectedScreening]);

  /** Index of the focused hit within the left bar's loaded (filtered) list. */
  const hitIndex = useMemo(
    () => hits.findIndex((h) => h.hit_id === selectedHit?.hit_id),
    [hits, selectedHit],
  );

  const goToHit = useCallback(
    (delta: number) => {
      if (hits.length === 0) return;
      const base = hitIndex < 0 ? 0 : hitIndex;
      const next = (base + delta + hits.length) % hits.length;
      setMetaUi({ selectedHit: hits[next] });
    },
    [hits, hitIndex, setMetaUi],
  );

  // Gating criteria in display order — the order the quick-coding focus walks.
  const gatingCriteria = useMemo(() => criteria.filter(isGating), [criteria]);
  const [focusedGatingIndex, setFocusedGatingIndex] = useState(0);

  // Each study starts on its first criterion.
  useEffect(() => {
    setFocusedGatingIndex(0);
  }, [selectedHit?.hit_id]);

  const saveVerdict = async (
    hit: MetaHit,
    verdicts: Record<string, { applies: string; certainty: string }> = selectedScreening?.verdicts ??
      {},
    advance = false,
  ) => {
    if (!selectedScreening || busy) return;
    const failing = derivedExclusionReason(criteria, verdicts);
    setBusy(true);
    try {
      await api.metaSaveScreening({
        hit_id: hit.hit_id,
        run_id: selectedScreening.run_id,
        verdicts,
        intervention_type: selectedScreening.intervention_type,
        rationale: selectedScreening.rationale,
        owner: selectedScreening.owner || writeOwner || undefined,
        stage: effectiveScreeningStage,
        reason: failing?.reason ?? "",
      });
      toast.success(t("meta.verdictSaved"));
      refresh();
      if (advance) goToHit(1);
      else await refreshSelectedScreening(hit.hit_id, effectiveScreeningStage);
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const updateVerdict = (key: string, field: "applies" | "certainty", value: string) => {
    setSelectedScreening((prev) => {
      if (!prev) return prev;
      const verdicts = { ...prev.verdicts };
      const current = verdicts[key] ?? { applies: "No", certainty: "Medium" };
      verdicts[key] = { ...current, [field]: value };
      return { ...prev, verdicts };
    });
  };

  const updateScreeningField = (field: "intervention_type" | "rationale", value: string) => {
    setSelectedScreening((prev) => (prev ? { ...prev, [field]: value } : prev));
  };

  const ensureScreeningRow = (hit: MetaHit) => {
    if (selectedScreening) return;
    if (criteria.length === 0) {
      toast.error(t("meta.noCriteriaHint"));
      return;
    }
    const empty: Record<string, { applies: string; certainty: string }> = {};
    for (const c of criteria) {
      empty[c.key] = { applies: "No", certainty: "Medium" };
    }
    setSelectedScreening({
      id: -hit.hit_id,
      hit_id: hit.hit_id,
      owner: writeOwner,
      run_id: runId,
      verdicts: empty,
      origin: "manual",
      stage: effectiveScreeningStage,
      created: "",
      updated: "",
    });
  };

  // Track the focused study's full-text screening row for the criteria
  // panel above the coding form.
  useEffect(() => {
    let cancelled = false;
    if (tab !== "extract" || !selectedHit) {
      setFulltextScreening(null);
      return;
    }
    const hitId = selectedHit.hit_id;
    void (async () => {
      try {
        const rows = await api.metaScreening({
          hit_id: hitId,
          stage: "fulltext",
          owner: writeOwner || undefined,
        });
        if (cancelled) return;
        setFulltextScreening(
          rows.reduce<MetaScreening | null>(
            (best, row) => (!best || row.id > best.id ? row : best),
            null,
          ),
        );
      } catch {
        if (!cancelled) setFulltextScreening(null);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [tab, selectedHit, writeOwner, tick]);

  // ── keyboard-driven screening (high-volume task) ────────────────────

  /** Apply a verdict to the focused gating criterion, then walk forward. */
  const quickVerdict = (value: "Yes" | "No" | "Unsure") => {
    if (!selectedHit || gatingCriteria.length === 0 || !selectedScreening) return;
    const index = Math.min(focusedGatingIndex, gatingCriteria.length - 1);
    const criterion = gatingCriteria[index];
    const current = selectedScreening.verdicts[criterion.key] ?? {
      applies: "No",
      certainty: "Medium",
    };
    const verdicts = {
      ...selectedScreening.verdicts,
      [criterion.key]: { ...current, applies: value },
    };
    setSelectedScreening((prev) => (prev ? { ...prev, verdicts } : prev));
    if (index < gatingCriteria.length - 1) {
      setFocusedGatingIndex(index + 1);
      return;
    }
    // Last gating criterion: persist the verdict and load the next hit.
    setFocusedGatingIndex(0);
    void saveVerdict(selectedHit, verdicts, true);
  };

  /** Free-text controls keep their own Tab/typing; selects, numbers & buttons
   *  let the quick keys through. */
  const isTextEntry = (target: HTMLElement | null): boolean => {
    if (!target) return false;
    if (target.isContentEditable || target.tagName === "TEXTAREA") return true;
    if (target.tagName === "INPUT") {
      const type = (target as HTMLInputElement).type;
      return ["text", "search", "email", "url", "tel", "password"].includes(type);
    }
    return false;
  };

  // Handled in the capture phase so Y/N/U + Tab reach the focused criterion
  // even when an inner select/button owns DOM focus; free-text fields keep
  // their own typing (and their own Tab handling).
  const onVerdictKeyDown = (e: React.KeyboardEvent) => {
    const textEntry = isTextEntry(e.target as HTMLElement | null);
    if (e.key === "Tab") {
      if (textEntry || gatingCriteria.length === 0) return;
      const delta = e.shiftKey ? -1 : 1;
      setFocusedGatingIndex((i) =>
        Math.min(Math.max(i + delta, 0), gatingCriteria.length - 1),
      );
      e.preventDefault();
      return;
    }
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      if (textEntry) return;
      goToHit(e.key === "ArrowDown" ? 1 : -1);
      e.preventDefault();
      return;
    }
    const key = e.key.toLowerCase();
    if (key === "y" || key === "n" || key === "u") {
      if (textEntry) return;
      quickVerdict(key === "y" ? "Yes" : key === "n" ? "No" : "Unsure");
      e.preventDefault();
    }
  };

  // ── downloads ───────────────────────────────────────────────────────

  const assignPdf = async (hitId: number, file: File | undefined) => {
    if (!file) return;
    try {
      await api.metaAssignPdf(hitId, file);
      refresh();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("meta.assignPdfFailed"));
    }
  };

  const assignRefs = useRef<Record<number, HTMLInputElement | null>>({});

  const currentDocument = useMemo(
    () => documents.find((d) => d.hit_id === selectedHit?.hit_id) ?? null,
    [documents, selectedHit],
  );

  // The Extraction tab's center shows the focused study's form; the right bar
  // shows its full text. Mirror that document into the store and open the bar
  // when the tab becomes active with a paper linked. The Download tab lets a
  // row click choose the document, so a focused-study change never overwrites
  // that choice (and the selection is not nulled while on Download).
  const currentSourceId = currentDocument?.source_id ?? null;
  useEffect(() => {
    if (tab === "extract") {
      setMetaUi({ selectedDocument: currentDocument });
    } else if (tab === "download") {
      if (!useWorkspaceStore.getState().metaUi.selectedDocument) {
        setMetaUi({ selectedDocument: currentDocument });
      }
    } else {
      setMetaUi({ selectedDocument: null });
    }
  }, [tab, currentDocument, setMetaUi]);

  useEffect(() => {
    if ((tab !== "extract" && tab !== "download") || !currentSourceId) return;
    window.dispatchEvent(new Event("qc:rightbar-open"));
  }, [tab, currentSourceId]);

  /** Show a download row's linked paper in the shared right-bar viewer. */
  const openDocument = (doc: MetaDocument) => {
    setMetaUi({ selectedDocument: doc });
    window.dispatchEvent(new Event("qc:rightbar-open"));
  };

  // ── extraction ──────────────────────────────────────────────────────

  // Resolve the focused study's extraction (or a blank draft so a fresh study
  // can be coded) for the inline scheme-driven form. The signature keeps the
  // object identity stable across unrelated reloads so unsaved edits survive;
  // it changes when the row is saved (new `updated`) or the selection moves.
  useEffect(() => {
    if (tab !== "extract" || !selectedHit) {
      formExtractionSigRef.current = "";
      setFormExtraction(null);
      return;
    }
    const found = extractions.find((e) => e.hit_id === selectedHit.hit_id) ?? null;
    const resolvedScheme = found?.scheme || scheme || "";
    const candidate = found
      ? found.scheme
        ? found
        : { ...found, scheme: resolvedScheme }
      : blankExtractionFor(selectedHit, resolvedScheme, writeOwner);
    const sig = `${candidate.id}|${candidate.updated}|${candidate.scheme}|${candidate.owner}`;
    if (sig !== formExtractionSigRef.current) {
      formExtractionSigRef.current = sig;
      setFormExtraction(candidate);
    }
  }, [tab, selectedHit, extractions, scheme, writeOwner]);

  const startExtraction = async () => {
    if (busy) return;
    if (!scheme) {
      toast.error(t("meta.needScheme"));
      return;
    }
    if (selectedIds.length === 0) {
      toast.error(t("meta.selectPapersHint"));
      return;
    }
    setBusy(true);
    try {
      await api.metaExtractRun({
        scheme,
        hit_ids: selectedIds,
        max_input_chars: maxInputChars,
        fulltext_only: fulltextOnly,
      });
      toast.success(t("meta.extractionStarted"));
      void loadJobs();
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  /** Save a blob under `filename` without racing the object-URL revoke. */
  const downloadBlob = (blob: Blob, filename: string) => {
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 0);
  };

  const exportData = async (fmt: "csv" | "xlsx") => {
    try {
      const blob = await localRequestBlob(`/meta/extract/export?fmt=${fmt}`);
      downloadBlob(blob, fmt === "csv" ? "meta_extraction.csv" : "meta_extraction.xlsx");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("meta.exportFailed"));
    }
  };

  const controlJob = async (jobId: string, action: "pause" | "resume" | "cancel") => {
    try {
      await api.metaJobControl(jobId, action);
      void loadJobs();
    } catch (err) {
      toast.error(errorMessage(err));
    }
  };

  const clearFinishedJobs = async () => {
    for (const job of finishedJobs) {
      try {
        await api.metaJobDelete(job.id);
      } catch {
        /* already gone */
      }
    }
    void loadJobs();
  };

  if (status === null) {
    return (
      <div className="flex h-full flex-col bg-bg">
        <ViewHeader back={false} title={t("nav.meta")} />
        <LoadingState />
      </div>
    );
  }

  const pipelineTabs = (
    <div className="flex items-center gap-1">
      {(
        [
          ["screen", t("meta.tabScreen")],
          ["download", t("meta.tabDownload")],
          ["extract", t("meta.tabExtract")],
          ["conflicts", t("meta.tabConflicts")],
          ["analyze", t("meta.tabAnalyze")],
        ] as [MetaTab, string][]
      ).map(([key, label]) => (
        <button
          key={key}
          type="button"
          onClick={() => setMetaUi({ tab: key })}
          aria-pressed={tab === key}
          className={`rounded-sm px-2 py-1 text-xs font-medium qc-motion ${
            tab === key ? "bg-surface-higher text-accent" : "text-text-secondary hover:bg-surface-higher"
          }`}
        >
          {label}
        </button>
      ))}
    </div>
  );

  return (
    <div className="flex h-full flex-col bg-bg">
      <ViewHeader
        back={false}
        collapseTitle
        title={t("nav.meta")}
        leading={pipelineTabs}
        actions={
          <div className="flex items-center gap-2">
            {tab === "screen" && (
              <div className="flex items-center gap-2">
                <Input
                  value={runId}
                  onChange={(e) => setRunId(e.target.value)}
                  placeholder={t("meta.llmRunId")}
                  className="h-7 w-28 text-xs"
                  aria-label={t("meta.llmRunId")}
                />
                <Select
                  value={clusterSize}
                  onChange={(e) => setClusterSize(Number(e.target.value))}
                  className="h-7 w-12 text-xs"
                  aria-label={t("meta.clusterSize")}
                  title={t("meta.clusterHint")}
                >
                  {[4, 8, 12, 16].map((n) => (
                    <option key={n} value={n}>
                      {n}
                    </option>
                  ))}
                </Select>
                <Button
                  variant="primary"
                  icon={<Sparkles size={13} aria-hidden />}
                  onClick={() => void startLlmScreen()}
                  disabled={criteria.length === 0 || busy}
                  title={criteria.length === 0 ? t("meta.noCriteriaHint") : undefined}
                >
                  {t("meta.llmScreen")}
                </Button>
                <Button variant="secondary" onClick={() => setShowCriteria((v) => !v)}>
                  {t("meta.criteriaTitle")}
                </Button>
                <span title={t("meta.blindHint")}>
                  <Toggle
                    checked={blind}
                    onChange={() => setMetaUi({ blind: !blind })}
                    label={t("meta.blind")}
                  />
                </span>
              </div>
            )}

            {tab === "download" && (
              <Input
                value={email}
                onChange={(e) => setMetaUi({ email: e.target.value })}
                placeholder={t("meta.unpaywallEmail")}
                className="h-7 w-64 text-xs"
                aria-label={t("meta.unpaywallEmail")}
              />
            )}

            {tab === "extract" && (
              <div className="flex items-center gap-2">
                <Button
                  variant="secondary"
                  icon={<Settings2 size={13} aria-hidden />}
                  onClick={() => setMetaUi({ schemeOpen: true })}
                  title={t("meta.schemeEditor")}
                >
                  {t("meta.editSchemes")}
                </Button>
                <Select
                  value={scheme}
                  onChange={(e) => setMetaUi({ scheme: e.target.value })}
                  className="h-7 w-36 text-xs"
                  aria-label={t("meta.scheme")}
                  title={t("meta.scheme")}
                >
                  {schemes.length === 0 ? <option value="">—</option> : null}
                  {schemes.map((s) => (
                    <option key={s.id} value={s.name}>
                      {s.label ?? s.name}
                    </option>
                  ))}
                </Select>
                <label className="flex items-center gap-1.5 text-[11px] text-text-secondary">
                  {t("meta.maxInput")}
                  <Input
                    type="number"
                    min={2000}
                    step={1000}
                    value={maxInputChars}
                    onChange={(e) => setMaxInputChars(Number(e.target.value) || 120000)}
                    className="h-7 w-24 text-xs"
                    aria-label={t("meta.maxInput")}
                    title={t("meta.maxInputHint")}
                  />
                </label>
                <label className="flex items-center gap-1.5 text-[11px] text-text-secondary">
                  <input
                    type="checkbox"
                    checked={fulltextOnly}
                    onChange={(e) => setFulltextOnly(e.target.checked)}
                    className="h-3.5 w-3.5 accent-[var(--qc-accent)]"
                    aria-label={t("meta.fulltextOnly")}
                  />
                  {t("meta.fulltextOnly")}
                </label>
                <Button
                  variant="primary"
                  icon={<Sparkles size={13} aria-hidden />}
                  onClick={() => void startExtraction()}
                  disabled={schemes.length === 0 || selectedIds.length === 0 || busy}
                  title={selectedIds.length === 0 ? t("meta.selectPapersHint") : undefined}
                >
                  {t("meta.autocodeSelected")}
                </Button>
                <Button
                  variant="secondary"
                  icon={<FileSpreadsheet size={13} aria-hidden />}
                  onClick={() => void exportData("xlsx")}
                  title={t("meta.exportXlsx")}
                >
                  {t("meta.exportXlsxShort")}
                </Button>
              </div>
            )}

            {tab === "analyze" && (
              <div className="flex items-center gap-2">
                {analysisSection === "subgroup" ? (
                  <Select
                    value={subgroupBy}
                    onChange={(e) => setMetaUi({ subgroupBy: e.target.value })}
                    className="h-7 w-44 text-xs"
                    aria-label={t("meta.subgroupBy")}
                    title={t("meta.subgroupBy")}
                  >
                    {moderators.length === 0 ? <option value="">—</option> : null}
                    {moderatorGroups.map(([group, entries]) => (
                      <optgroup key={group} label={group}>
                        {entries.map((entry) => (
                          <option key={entry.name} value={entry.name}>
                            {entry.label || entry.name}
                          </option>
                        ))}
                      </optgroup>
                    ))}
                  </Select>
                ) : null}
                <div
                  className="inline-flex rounded-sm border border-border p-0.5"
                  role="group"
                  aria-label={t("meta.modelLabel")}
                >
                  <button
                    type="button"
                    aria-pressed={analysisModel === "frequentist"}
                    onClick={() => setMetaUi({ analysisModel: "frequentist" })}
                    className={`rounded-sm px-2 py-1 text-xs font-medium qc-motion ${
                      analysisModel === "frequentist"
                        ? "bg-surface-higher text-accent"
                        : "text-text-secondary hover:bg-surface-higher"
                    }`}
                  >
                    {t("meta.modelFrequentist")}
                  </button>
                  <button
                    type="button"
                    aria-pressed={analysisModel === "bayes"}
                    onClick={() => setMetaUi({ analysisModel: "bayes" })}
                    className={`rounded-sm px-2 py-1 text-xs font-medium qc-motion ${
                      analysisModel === "bayes"
                        ? "bg-surface-higher text-accent"
                        : "text-text-secondary hover:bg-surface-higher"
                    }`}
                  >
                    {t("meta.modelBayes")}
                  </button>
                </div>
                {analysisModel === "frequentist" ? (
                  <Select
                    value={poolModel}
                    onChange={(e) => setMetaUi({ poolModel: e.target.value as MetaPoolModel })}
                    className="h-7 w-44 text-xs"
                    aria-label={t("meta.poolModelLabel")}
                    title={t("meta.poolModelLabel")}
                  >
                    {POOL_MODELS.map((m) => (
                      <option key={m.value} value={m.value}>
                        {t(m.labelKey)}
                      </option>
                    ))}
                  </Select>
                ) : null}
              </div>
            )}

            {tab !== "screen" && tab !== "conflicts" && (
              <Button
                variant="secondary"
                icon={<Handshake size={13} aria-hidden />}
                onClick={() => setMetaUi({ tab: "conflicts" })}
                title={t("meta.agreementTitle")}
              >
                {t("meta.agreement")}
              </Button>
            )}
          </div>
        }
      />
      {error && <ErrorBanner onClose={() => setError(null)}>{error}</ErrorBanner>}

      {/* Jobs strip */}
      {jobs.length > 0 && (
        <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-border bg-surface px-3 py-1 text-xs">
          {jobs.map((job) => (
            <span
              key={job.id}
              className="flex items-center gap-1.5 rounded-sm border border-border px-2 py-0.5"
              title={`${job.label} · ${job.state === "error" ? job.error ?? job.message : job.message ?? ""}`}
            >
              {isRunning(job) ? (
                <LoaderCircle size={11} className="animate-spin text-accent" aria-hidden />
              ) : job.state === "done" ? (
                <Check size={11} className="text-success" aria-hidden />
              ) : job.state === "error" ? (
                <span className="text-danger" aria-hidden>
                  ✗
                </span>
              ) : null}
              <span>
                {t(jobKindKey(job.kind))} · {Math.round(job.progress)}%
              </span>
              <span className="rounded-sm bg-surface-higher px-1 py-px text-[10px] text-text-secondary">
                {job.paused ? t("meta.jobPaused") : t(jobStateKey(job.state))}
              </span>
              {job.state === "error" && job.error ? (
                <span className="max-w-64 truncate text-danger" title={job.error}>
                  {job.error}
                </span>
              ) : null}
              {job.state === "running" && !job.paused ? (
                <IconButton
                  label={t("meta.pauseJob")}
                  title={t("meta.pauseJob")}
                  size="sm"
                  onClick={() => void controlJob(job.id, "pause")}
                >
                  <Pause size={10} aria-hidden />
                </IconButton>
              ) : null}
              {job.paused ? (
                <IconButton
                  label={t("meta.resumeJob")}
                  title={t("meta.resumeJob")}
                  size="sm"
                  onClick={() => void controlJob(job.id, "resume")}
                >
                  <Play size={10} aria-hidden />
                </IconButton>
              ) : null}
              {isRunning(job) ? (
                <IconButton
                  label={t("meta.cancelJob")}
                  title={t("meta.cancelJob")}
                  size="sm"
                  onClick={() => void controlJob(job.id, "cancel")}
                >
                  <X size={10} aria-hidden />
                </IconButton>
              ) : null}
            </span>
          ))}
          {finishedJobs.length > 0 && (
            <IconButton
              label={t("meta.clearFinished")}
              size="sm"
              className="ml-auto"
              onClick={() => void clearFinishedJobs()}
            >
              <Trash2 size={11} aria-hidden />
            </IconButton>
          )}
        </div>
      )}

      {/* ── SCREENING (abstract + verdicts in the center) ── */}
      {tab === "screen" && (
        <div className="flex min-h-0 flex-1 flex-col">
          {showCriteria && (
            <div className="qc-scroll shrink-0 overflow-auto border-b border-border bg-surface px-3 py-2" style={{ maxHeight: "50%" }}>
              <div className="mb-2 flex items-center gap-2">
                <span className="text-xs font-medium text-text-secondary">{t("meta.criteriaTitle")}</span>
                <span className="text-[11px] text-text-secondary">{t("meta.autoSaveHint")}</span>
              </div>
              <MetaCriteriaEditor value={criteriaDrafts} onChange={updateCriteriaDrafts} />
            </div>
          )}

          <div className="grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-[1fr_380px]">
            {/* Abstract */}
            <div className="qc-scroll min-h-0 overflow-auto border-b border-border p-4 lg:border-b-0 lg:border-r">
              {selectedHit === null ? (
                <EmptyState icon={<Search size={24} aria-hidden />}>{t("meta.selectHit")}</EmptyState>
              ) : (
                <>
                  <h2 className="text-sm font-semibold text-text-primary">{selectedHit.title}</h2>
                  <p className="mt-0.5 text-xs text-text-secondary">
                    {selectedHit.authors ?? ""} · {selectedHit.year ?? ""} · {selectedHit.doi ?? ""}
                  </p>
                  <p className="mt-3 whitespace-pre-wrap text-sm leading-relaxed text-text-secondary">
                    {selectedHit.abstract || t("meta.noAbstract")}
                  </p>
                </>
              )}
            </div>

            {/* Verdict editor — Y/N/U + ↑/↓ shortcuts for high-volume screening */}
            <div
              className="qc-scroll min-h-0 overflow-auto p-3 outline-none"
              tabIndex={-1}
              onKeyDownCapture={onVerdictKeyDown}
            >
              {selectedHit === null ? null : (
                (() => {
                  const hit = selectedHit;
                  const scr = selectedScreening;
                  const failing = scr ? derivedExclusionReason(criteria, scr.verdicts) : null;
                  return (
                    <div className="space-y-3">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="rounded-sm bg-surface-higher px-1.5 py-px text-[10px] uppercase text-text-secondary">
                          {effectiveScreeningStage === "fulltext" ? t("meta.stageFulltext") : t("meta.stageAbstract")}
                        </span>
                        {blind ? (
                          <span className="rounded-sm bg-warning/10 px-1.5 py-px text-[10px] text-warning">
                            {t("meta.blind")}
                          </span>
                        ) : null}
                        <span className="flex-1" />
                        <IconButton
                          label={t("meta.prev")}
                          title={t("meta.prev")}
                          size="sm"
                          disabled={hits.length === 0}
                          className="disabled:opacity-30"
                          onClick={() => goToHit(-1)}
                        >
                          <ChevronUp size={12} aria-hidden />
                        </IconButton>
                        <IconButton
                          label={t("meta.next")}
                          title={t("meta.next")}
                          size="sm"
                          disabled={hits.length === 0}
                          className="disabled:opacity-30"
                          onClick={() => goToHit(1)}
                        >
                          <ChevronDown size={12} aria-hidden />
                        </IconButton>
                      </div>
                      {!scr ? (
                        criteria.length === 0 ? (
                          <p className="text-xs text-text-secondary">{t("meta.noCriteriaHint")}</p>
                        ) : (
                          <Button
                            variant="primary"
                            icon={<Play size={13} aria-hidden />}
                            onClick={() => ensureScreeningRow(hit)}
                          >
                            {t("meta.verdicts")}
                          </Button>
                        )
                      ) : (
                        <div className="space-y-2">
                          {criteria.map((c) => {
                            const verdict = scr?.verdicts?.[c.key] ?? {
                              applies: c.kind === "classify" ? "" : "No",
                              certainty: "Medium",
                            };
                            const passes = criterionPasses(c, verdict.applies);
                            const gating = isGating(c);
                            const gatingIndex = gatingCriteria.findIndex((g) => g.key === c.key);
                            const isFocused =
                              gating &&
                              gatingCriteria.length > 0 &&
                              gatingIndex ===
                                Math.min(focusedGatingIndex, gatingCriteria.length - 1);
                            return (
                              <div
                                key={c.key}
                                data-focused={isFocused ? "true" : undefined}
                                className={`rounded-sm border p-2 qc-motion ${
                                  gating && !passes ? "border-danger/40" : "border-border"
                                } ${isFocused ? "ring-1 ring-accent" : ""}`}
                              >
                                <div className="mb-1 flex flex-wrap items-center gap-1.5">
                                  <span className="text-xs font-medium text-text-primary">{c.label}</span>
                                  <span className="rounded-sm bg-surface-higher px-1 text-[10px] text-text-secondary">
                                    {t(`meta.kind_${c.kind ?? "verdict"}`)}
                                  </span>
                                  {!gating ? (
                                    <span className="text-[10px] text-text-secondary">
                                      {t("meta.informational")}
                                    </span>
                                  ) : null}
                                </div>
                                {c.help ? (
                                  <p className="mb-1 text-[11px] text-text-secondary">{c.help}</p>
                                ) : null}

                                {c.kind === "classify" ? (
                                  <div className="flex flex-wrap gap-1">
                                    {(c.options ?? []).map((option) => (
                                      <button
                                        key={option}
                                        type="button"
                                        onClick={() => updateVerdict(c.key, "applies", option)}
                                        aria-pressed={verdict.applies === option}
                                        className={`rounded-sm border px-2 py-0.5 text-xs qc-motion ${
                                          verdict.applies === option
                                            ? "border-accent bg-accent/10 text-accent"
                                            : "border-border text-text-primary hover:bg-surface-higher"
                                        }`}
                                      >
                                        {option}
                                      </button>
                                    ))}
                                    {(c.options ?? []).length === 0 ? (
                                      <span className="text-[11px] text-text-secondary">—</span>
                                    ) : null}
                                  </div>
                                ) : c.kind === "number" ? (
                                  <Input
                                    value={verdict.applies}
                                    onChange={(e) => updateVerdict(c.key, "applies", e.target.value)}
                                    className="h-7 w-32 text-xs"
                                    aria-label={c.label}
                                  />
                                ) : (
                                  <div className="flex flex-wrap items-center gap-2">
                                    <label className="text-[10px] uppercase text-text-secondary">
                                      {t("meta.applies")}
                                    </label>
                                    <Select
                                      value={verdict.applies}
                                      onChange={(e) => updateVerdict(c.key, "applies", e.target.value)}
                                      className="h-7 w-24 text-xs"
                                    >
                                      {VERDICT_CHOICES.map((v) => (
                                        <option key={v} value={v}>
                                          {t(`meta.${v.toLowerCase()}`)}
                                        </option>
                                      ))}
                                    </Select>
                                  </div>
                                )}

                                <div className="mt-1.5 flex flex-wrap items-center gap-2">
                                  <label className="text-[10px] uppercase text-text-secondary">
                                    {t("meta.certainty")}
                                  </label>
                                  <Select
                                    value={verdict.certainty}
                                    onChange={(e) => updateVerdict(c.key, "certainty", e.target.value)}
                                    className="h-7 w-24 text-xs"
                                  >
                                    {CERTAINTY_CHOICES.map((v) => (
                                      <option key={v} value={v}>
                                        {t(`meta.${v.toLowerCase()}`)}
                                      </option>
                                    ))}
                                  </Select>
                                  {!passes && c.exclude_reason ? (
                                    <span className="text-[10px] text-danger">
                                      {t("meta.exclusionReasonShort", { reason: c.exclude_reason })}
                                    </span>
                                  ) : null}
                                </div>
                              </div>
                            );
                          })}
                          <label className="block text-xs font-medium text-text-secondary">
                            {t("meta.interventionType")}
                            <Input
                              value={scr?.intervention_type ?? ""}
                              onChange={(e) => updateScreeningField("intervention_type", e.target.value)}
                              className="mt-1 h-7 text-xs"
                            />
                          </label>
                          <label className="block text-xs font-medium text-text-secondary">
                            {t("meta.rationale")}
                            <Textarea
                              value={scr?.rationale ?? ""}
                              onChange={(e) => updateScreeningField("rationale", e.target.value)}
                              className="mt-1 text-xs"
                              rows={3}
                            />
                          </label>
                          {failing ? (
                            <p className="text-xs text-danger">
                              {t("meta.derivedReason", { reason: failing.reason })}
                            </p>
                          ) : scr.reason ? (
                            <p className="text-xs text-text-secondary">
                              {t("meta.structuredReason", { reason: scr.reason })}
                            </p>
                          ) : null}
                          <div className="flex flex-wrap items-center gap-1.5">
                            {VERDICT_CHOICES.map((v) => (
                              <Button
                                key={v}
                                variant="secondary"
                                onClick={() => quickVerdict(v)}
                                title={t("meta.keyboardHint", { key: v[0] })}
                              >
                                {t(`meta.${v.toLowerCase()}`)}
                              </Button>
                            ))}
                            <Button
                              variant="primary"
                              icon={<Check size={13} aria-hidden />}
                              disabled={busy}
                              onClick={() => void saveVerdict(hit)}
                            >
                              {t("meta.saveVerdict")}
                            </Button>
                            {scr?.origin === "llm" && !blind ? (
                              <span className="rounded-sm bg-warning/10 px-1.5 py-px text-[10px] text-warning">
                                {t("meta.llmProposal")}
                              </span>
                            ) : null}
                            {scr?.origin === "llm" && blind ? (
                              <span className="text-[10px] text-text-secondary">{t("meta.blindHidden")}</span>
                            ) : null}
                          </div>
                        </div>
                      )}
                    </div>
                  );
                })()
              )}
            </div>
          </div>
        </div>
      )}

      {/* ── DOWNLOADS ── */}
      {tab === "download" && (
        <div className="flex min-h-0 flex-1 flex-col">
          <div className="qc-scroll min-h-0 flex-1 overflow-auto p-4">
            {documents.length === 0 ? (
              <EmptyState icon={<ArrowDownToLine size={24} aria-hidden />}>{t("meta.noEligible")}</EmptyState>
            ) : (
              <div className="overflow-auto rounded-sm border border-border">
              <table className="w-full text-left">
                <thead className="sticky top-0 bg-surface">
                  <tr>
                    <TableHead>{t("meta.colTitle")}</TableHead>
                    <TableHead>{t("meta.pdfStatus")}</TableHead>
                    <TableHead>{t("meta.colMethod")}</TableHead>
                    <TableHead className="w-32" />
                  </tr>
                </thead>
                <tbody>
                  {documents.map((doc) => (
                    <tr
                      key={doc.id}
                      role="button"
                      tabIndex={0}
                      aria-label={t("meta.openLinkedPaper", { title: doc.title ?? "" })}
                      title={t("meta.openLinkedPaper", { title: doc.title ?? "" })}
                      onClick={() => openDocument(doc)}
                      onKeyDown={(e) => {
                        if (e.target !== e.currentTarget) return;
                        if (e.key === "Enter" || e.key === " ") {
                          e.preventDefault();
                          openDocument(doc);
                        }
                      }}
                      className="cursor-pointer qc-motion hover:bg-surface-higher focus-visible:bg-surface-higher focus-visible:outline-none"
                    >
                      <td className={`${TD} max-w-0`}>
                        <div className="truncate text-text-primary">{doc.title ?? ""}</div>
                        <div className="truncate text-xs text-text-secondary">{doc.doi ?? ""}</div>
                      </td>
                      <td className={TD}>
                        <span className={`rounded-sm px-1.5 py-px text-[10px] font-medium ${statusBadgeClass(doc.status)}`}>
                          {t(statusKey(doc.status))}
                        </span>
                        {doc.message ? (
                          <span className="ml-1.5 text-xs text-text-secondary">{doc.message}</span>
                        ) : null}
                      </td>
                      <td className={`${TD} text-text-secondary`}>
                        {doc.retrieval_method ? t(`meta.method_${doc.retrieval_method}`) : "—"}
                      </td>
                      <td className={`${TD} text-right`}>
                        <Button
                          variant="secondary"
                          icon={<FilePlus2 size={12} aria-hidden />}
                          onClick={(e) => {
                            e.stopPropagation();
                            assignRefs.current[doc.hit_id]?.click();
                          }}
                        >
                          {t("meta.assignPdf")}
                        </Button>
                        <input
                          ref={(el) => {
                            assignRefs.current[doc.hit_id] = el;
                          }}
                          type="file"
                          accept=".pdf"
                          className="hidden"
                          onChange={(e) => {
                            void assignPdf(doc.hit_id, e.target.files?.[0]);
                            e.target.value = "";
                          }}
                        />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              </div>
            )}
          </div>
        </div>
      )}

      {/* ── EXTRACTION (full-text screening + scheme-driven form) ── */}
      {tab === "extract" && (
        <div className="qc-scroll min-h-0 flex-1 overflow-auto p-4">
          {!selectedHit ? (
            <EmptyState icon={<Search size={24} aria-hidden />}>{t("meta.selectStudy")}</EmptyState>
          ) : (
            <>
              <MetaFulltextPanel
                key={`${selectedHit.hit_id}|${writeOwner}`}
                hit={selectedHit}
                criteria={criteria}
                screening={fulltextScreening}
                owner={writeOwner}
                onSaved={() => refresh()}
              />
              {formExtraction ? (
                <MetaExtractionForm
                  extraction={formExtraction}
                  scheme={schemes.find((s) => s.name === formExtraction.scheme) ?? null}
                  owner={writeOwner}
                  onSaved={() => refresh()}
                />
              ) : null}
            </>
          )}
        </div>
      )}

      {/* ── CONFLICTS (reliability + settle) ── */}
      {tab === "conflicts" && <MetaAgreementPanel />}

      {/* ── ANALYZE (pooled / subgroup / PRISMA / summary / report) ── */}
      {tab === "analyze" && <MetaAnalyze />}

      <MetaImportDialog
        open={importOpen}
        onClose={() => setMetaUi({ importOpen: false })}
        onImported={() => refresh()}
      />
      <MetaSchemeEditor
        open={schemeOpen}
        schemes={schemes}
        onClose={() => setMetaUi({ schemeOpen: false })}
        onChanged={() => refresh()}
      />
    </div>
  );
}
