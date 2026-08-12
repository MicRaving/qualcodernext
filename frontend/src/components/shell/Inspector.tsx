/**
 * Inspector — right-side details panel for the selected code or file.
 */
import { useCallback, useEffect, useState, type ReactNode } from "react";
import { ChevronDown, ChevronRight, FileText, Hash, LoaderCircle, Plus, Trash2, X } from "lucide-react";
import { api, type Annotation, type CodeDetails, type SourceDetails } from "@/lib/api";

import {
  BarHeader,
  Button,
  IconButton,
  LeftBar,
  SectionLabel,
  Select,
  Textarea,
} from "@/components/ui/orchestrator";
import { useI18n } from "@/lib/i18n";
import { useProjectStore } from "@/stores/project";
import {
  formatMediaLabel,
  formatStats,
  isCodeDetails,
  isSourceDetails,
} from "@/features/shell/inspector";

/** Fallback for code swatches with no API color (matches CodePicker). */
const SWATCH_FALLBACK = "var(--qc-accent)";

/**
 * Inline memo editor: shows the memo text with an Edit button, and swaps
 * to a textarea with Save/Cancel while editing.
 */
function MemoEditor({
  memo,
  onSave,
}: {
  memo: string;
  onSave: (value: string) => Promise<void>;
}) {
  const { t } = useI18n();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  // "Edit memo" actions (sidebar context menus) jump straight into edit mode.
  const memoEditRequest = useProjectStore((s) => s.inspectorMemoEdit);
  useEffect(() => {
    if (memoEditRequest) {
      setEditing(true);
      setDraft(memo);
      useProjectStore.getState().setInspectorMemoEdit(false);
    }
  }, [memoEditRequest, memo]);

  async function handleSave() {
    if (draft == null || saving) return;
    setSaving(true);
    setSaveError(null);
    try {
      await onSave(draft);
      setEditing(false);
      setDraft(null);
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : t("inspector.memoSaveError"));
    } finally {
      setSaving(false);
    }
  }

  if (!editing) {
    return (
      <div className="px-3 py-2">
        <div
          className="mb-1 flex items-center justify-between"
          onContextMenu={(e) => {
            e.preventDefault();
            useProjectStore.getState().setNotesUi({ tab: "memos" });
            useProjectStore.getState().setView({ kind: "notes" });
          }}
          title={t("inspector.openMemos")}
        >
          <SectionLabel>{t("inspector.memo")}</SectionLabel>
          <IconButton
            label={t("inspector.addMemo")}
            title={memo.trim() === "" ? t("inspector.addMemo") : t("inspector.editMemo")}
            size="sm"
            onClick={() => {
              setDraft(memo);
              setEditing(true);
            }}
          >
            <Plus size={12} aria-hidden />
          </IconButton>
        </div>
        <button
          type="button"
          onClick={() => {
            setDraft(memo);
            setEditing(true);
          }}
          className="block w-full rounded-sm bg-surface-higher px-2 py-1.5 text-left hover:bg-border"
          title={t("inspector.editMemo")}
        >
          <p className="text-sm text-text-primary">
            {memo.trim() === "" ? (
              <span className="italic text-text-secondary">{t("common.noMemo")}</span>
            ) : (
              <span className="whitespace-pre-wrap">{memo}</span>
            )}
          </p>
        </button>
      </div>
    );
  }

  return (
    <div className="px-3 py-2">
      <div className="mb-1">
        <SectionLabel>{t("inspector.memo")}</SectionLabel>
      </div>
      <Textarea
        autoFocus
        value={draft ?? ""}
        onChange={(e) => setDraft(e.target.value)}
        rows={4}
        aria-label={t("inspector.memoAria")}
        className="w-full resize-y px-2 py-1 text-text-primary"
      />
      <div className="mt-1.5 flex items-center gap-1.5">
        <Button
          variant="primary"
          onClick={() => void handleSave()}
          disabled={saving}
          icon={saving ? <LoaderCircle size={10} className="animate-spin" aria-hidden /> : undefined}
        >
          {t("common.save")}
        </Button>
        <Button
          variant="secondary"
          onClick={() => {
            setEditing(false);
            setDraft(null);
          }}
          disabled={saving}
        >
          {t("common.cancel")}
        </Button>
      </div>
      {saveError && <p className="mt-1.5 text-xs text-danger">{saveError}</p>}
    </div>
  );
}

function CodeDetailsPanel({ details }: { details: CodeDetails }) {
  const { t } = useI18n();
  const selectCode = useProjectStore((s) => s.selectCode);
  const clearInspector = useProjectStore((s) => s.clearInspector);
  const [actionError, setActionError] = useState<string | null>(null);

  async function saveMemo(value: string) {
    await api.patchCode(details.code.cid, { memo: value });
    await selectCode(details.code.cid);
  }

  async function handleDelete() {
    if (!window.confirm(t("inspector.deleteCodeConfirm", { name: details.code.name }))) return;
    setActionError(null);
    try {
      await api.deleteCode(details.code.cid);
      clearInspector();
      await useProjectStore.getState().refreshProject();
    } catch (e) {
      setActionError(e instanceof Error ? e.message : t("inspector.deleteCodeError"));
    }
  }

  return (
    <div className="flex flex-col">
      {/* Category path */}
      <div className="flex items-center gap-1 border-b border-border px-3 py-1.5 text-xs text-text-secondary">
        {details.category_path.length === 0 ? (
          <span>—</span>
        ) : (
          details.category_path.map((name, i) => (
            <span key={`${name}-${i}`} className="flex min-w-0 items-center gap-1">
              {i > 0 && <ChevronRight size={10} className="shrink-0" aria-hidden />}
              <span className="truncate">{name}</span>
            </span>
          ))
        )}
      </div>

      {/* Stats — same meta-row style as the file details panel */}
      <dl className="flex flex-col gap-1 border-b border-border px-3 py-2 text-xs">
        <div className="flex justify-between gap-2">
          <dt className="text-text-secondary">{t("inspector.codings")}</dt>
          <dd className="truncate text-text-primary">{details.coding_count}</dd>
        </div>
        <div className="flex justify-between gap-2">
          <dt className="text-text-secondary">{t("inspector.files")}</dt>
          <dd className="truncate text-text-primary">{details.file_count}</dd>
        </div>
      </dl>

      <MemoEditor key={details.code.cid} memo={details.code.memo} onSave={saveMemo} />
      {actionError && <p className="px-3 pb-2 text-xs text-danger">{actionError}</p>}

      {/* Recent coded segments — click opens the file and highlights the
          segment in the coder for ~2s. */}
      <div className="px-3 py-2">
        <SectionLabel>{t("inspector.recentSegments")}</SectionLabel>
        {details.recent_examples.length === 0 ? (
          <p className="text-sm text-text-secondary">{t("inspector.noSegments")}</p>
        ) : (
          <ul className="flex flex-col gap-1.5">
            {details.recent_examples.slice(0, 5).map((ex) => (
              <li key={ex.ctid}>
                <button
                  type="button"
                  onClick={() => {
                    useProjectStore.getState().setView({ kind: "coding", sourceId: ex.fid });
                    useProjectStore.getState().setGotoSegment({
                      ctid: ex.ctid,
                      pos0: ex.pos0,
                      pos1: ex.pos1,
                    });
                  }}
                  title={t("inspector.gotoSegment", { file: ex.file_name })}
                  className="block w-full rounded-sm bg-surface-higher px-2 py-1.5 text-left hover:bg-border"
                >
                  <p className="truncate text-xs text-text-secondary">{ex.file_name}</p>
                  <p className="line-clamp-2 text-sm text-text-primary">{ex.seltext}</p>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="border-t border-border p-2">
        <button
          type="button"
          onClick={() => void handleDelete()}
          className="flex w-full items-center justify-center gap-1.5 rounded-sm border border-danger px-2 py-1.5 text-xs font-medium text-danger hover:bg-danger/10"
        >
          <Trash2 size={12} aria-hidden />
          {t("inspector.deleteCode")}
        </button>
      </div>
    </div>
  );
}

function FileDetailsPanel({ details }: { details: SourceDetails }) {
  const { t } = useI18n();
  const selectFile = useProjectStore((s) => s.selectFile);
  const hiddenCodes = useProjectStore((s) => s.hiddenCodes);
  const toggleHiddenCode = useProjectStore((s) => s.toggleHiddenCode);
  const stats = formatStats(details);
  const src = details.source;

  // Case assignment
  const allCases = useProjectStore((s) => s.cases);
  const assignedIds = new Set(details.cases.map((c) => c.caseid));
  const unassignedCases = allCases.filter((c) => !assignedIds.has(c.caseid));
  const [assignCaseId, setAssignCaseId] = useState("");
  const [caseError, setCaseError] = useState<string | null>(null);
  /** "Codes used" is collapsed by default. */
  const [codesCollapsed, setCodesCollapsed] = useState(true);

  // Annotations on this file
  const [annotations, setAnnotations] = useState<Annotation[]>([]);
  const [annError, setAnnError] = useState<string | null>(null);
  const [newAnnMemo, setNewAnnMemo] = useState("");
  const inspectorNewAnnotation = useProjectStore((s) => s.inspectorNewAnnotation);
  const setInspectorNewAnnotation = useProjectStore((s) => s.setInspectorNewAnnotation);

  const loadAnnotations = useCallback(async () => {
    try {
      setAnnotations(await api.fileAnnotations(src.id));
      setAnnError(null);
    } catch (e) {
      setAnnError(e instanceof Error ? e.message : t("inspector.annotationsLoadError"));
    }
  }, [src.id, t]);

  useEffect(() => {
    void loadAnnotations();
  }, [loadAnnotations]);

  async function saveNewAnnotation() {
    const memo = newAnnMemo.trim();
    if (!memo) return;
    try {
      await api.createAnnotation({ fid: src.id, pos0: 0, pos1: 1, memo });
      setNewAnnMemo("");
      setInspectorNewAnnotation(false);
      await loadAnnotations();
    } catch (e) {
      setAnnError(e instanceof Error ? e.message : t("inspector.annotationsLoadError"));
    }
  }

  async function unassignCase(caseid: number) {
    setCaseError(null);
    try {
      await api.unlinkFileFromCase(caseid, src.id);
      await selectFile(src.id);
    } catch (e) {
      setCaseError(e instanceof Error ? e.message : t("inspector.assignCaseError"));
    }
  }

  async function doAssignCase() {
    if (!assignCaseId) return;
    setCaseError(null);
    try {
      await api.linkFileToCase(Number(assignCaseId), src.id);
      setAssignCaseId("");
      await selectFile(src.id);
    } catch (e) {
      setCaseError(e instanceof Error ? e.message : t("inspector.assignCaseError"));
    }
  }

  /** Inline annotation editing: clicking a card enters edit mode (no
   *  system prompt). */
  const [editingAnnId, setEditingAnnId] = useState<number | null>(null);
  const [editingAnnMemo, setEditingAnnMemo] = useState("");

  async function saveAnnotationEdit(anid: number) {
    try {
      await api.updateAnnotation(anid, editingAnnMemo);
      setEditingAnnId(null);
      await loadAnnotations();
    } catch (e) {
      setAnnError(e instanceof Error ? e.message : t("inspector.annotationsLoadError"));
    }
  }

  async function deleteAnnotation(anid: number) {
    if (!window.confirm(t("coder.deleteAnnotation"))) return;
    try {
      await api.deleteAnnotation(anid);
      if (editingAnnId === anid) setEditingAnnId(null);
      await loadAnnotations();
    } catch (e) {
      setAnnError(e instanceof Error ? e.message : t("inspector.annotationsLoadError"));
    }
  }

  async function saveMemo(value: string) {
    await api.patchSource(src.id, { memo: value });
    await selectFile(src.id);
  }

  return (
    <div className="flex flex-col">
      {/* Meta rows */}
      <dl className="flex flex-col gap-1 border-b border-border px-3 py-2 text-xs">
        <div className="flex justify-between gap-2">
          <dt className="text-text-secondary">{t("inspector.type")}</dt>
          <dd className="truncate text-text-primary">{formatMediaLabel(src)}</dd>
        </div>
        <div className="flex justify-between gap-2">
          <dt className="text-text-secondary">{t("inspector.date")}</dt>
          <dd className="truncate text-text-primary">{src.date}</dd>
        </div>
        <div className="flex justify-between gap-2">
          <dt className="text-text-secondary">{t("inspector.owner")}</dt>
          <dd className="truncate text-text-primary">{src.owner}</dd>
        </div>
        <div className="flex justify-between gap-2">
          <dt className="text-text-secondary">{t("inspector.codings")}</dt>
          <dd className="truncate text-text-primary">{stats.primary}</dd>
        </div>
      </dl>

      {/* Codes used — collapsed by default; click a code to highlight/hide
          its segments in the open coder. Right-click the header to jump to
          the memos view (codes have memos too). */}
      <div className="px-3 py-2">
        <div
          className="flex items-center justify-between"
          onContextMenu={(e) => {
            e.preventDefault();
            useProjectStore.getState().setNotesUi({ tab: "memos" });
            useProjectStore.getState().setView({ kind: "notes" });
          }}
          title={t("inspector.openMemos")}
        >
          <SectionLabel>{t("inspector.codesUsed")}</SectionLabel>
          <IconButton
            label={codesCollapsed ? t("inspector.expand") : t("inspector.collapse")}
            title={codesCollapsed ? t("inspector.expand") : t("inspector.collapse")}
            size="sm"
            onClick={() => setCodesCollapsed((v) => !v)}
          >
            {codesCollapsed ? (
              <ChevronRight size={12} aria-hidden />
            ) : (
              <ChevronDown size={12} aria-hidden />
            )}
          </IconButton>
        </div>
        {!codesCollapsed &&
          (details.codes_used.length === 0 ? (
            <p className="text-sm text-text-secondary">{t("inspector.noCodings")}</p>
          ) : (
            <div className="flex flex-wrap gap-1">
              {details.codes_used.map((c) => {
                const hidden = hiddenCodes.includes(c.cid);
                return (
                  <button
                    key={c.cid}
                    type="button"
                    onClick={() => toggleHiddenCode(c.cid)}
                    aria-pressed={hidden}
                    title={t("inspector.hideInCoder")}
                    className={`flex items-center gap-1 rounded-sm bg-surface-higher px-1.5 py-0.5 text-xs ${
                      hidden ? "opacity-40" : "hover:bg-surface-higher"
                    }`}
                  >
                    <span
                      className="h-2 w-2 shrink-0 rounded-sm border border-border"
                      style={{ backgroundColor: c.color ?? SWATCH_FALLBACK }}
                      aria-hidden
                    />
                    <span className="max-w-28 truncate">{c.name}</span>
                    <span className="text-text-secondary">{c.count}</span>
                  </button>
                );
              })}
            </div>
          ))}
      </div>

      {/* Cases — with inline assignment from the right bar. Right-click the
          header to jump to the Cases workspace. */}
      <div className="px-3 py-2">
        <div
          onContextMenu={(e) => {
            e.preventDefault();
            useProjectStore.getState().setView({ kind: "cases" });
          }}
          title={t("inspector.openCases")}
        >
          <SectionLabel>{t("inspector.cases")}</SectionLabel>
        </div>
        {caseError && <p className="mb-1 text-xs text-danger">{caseError}</p>}
        {details.cases.length === 0 ? (
          <p className="text-sm text-text-secondary">{t("inspector.noCases")}</p>
        ) : (
          <div className="flex flex-col gap-1">
            {details.cases.map((c) => (
              <span
                key={c.caseid}
                className="flex w-full items-center gap-1.5 rounded-sm bg-surface-higher px-2 py-1 text-sm text-text-primary"
              >
                <span className="min-w-0 flex-1 truncate">{c.name}</span>
                <IconButton
                  label={t("inspector.unassignCase", { name: c.name })}
                  title={t("inspector.unassignCase", { name: c.name })}
                  size="sm"
                  className="shrink-0 hover:text-danger"
                  onClick={() => void unassignCase(c.caseid)}
                >
                  <Trash2 size={12} aria-hidden />
                </IconButton>
              </span>
            ))}
          </div>
        )}
        <div className="mt-2 flex items-center gap-1.5">
          <Select
            value={assignCaseId}
            onChange={(e) => setAssignCaseId(e.target.value)}
            aria-label={t("inspector.assignCase")}
            className="min-w-0 flex-1"
          >
            <option value="">{t("inspector.assignCase")}</option>
            {unassignedCases.map((c) => (
              <option key={c.caseid} value={c.caseid}>
                {c.name}
              </option>
            ))}
          </Select>
          <Button
            variant="secondary"
            disabled={!assignCaseId}
            onClick={() => void doAssignCase()}
          >
            {t("inspector.assign")}
          </Button>
        </div>
      </div>

      {/* Annotations on this file — right-click the header to open the
          full annotations view (Notes workspace, annotations tab). */}
      <div className="px-3 py-2">
        <div
          className="mb-1 flex items-center justify-between"
          onContextMenu={(e) => {
            e.preventDefault();
            useProjectStore.getState().setNotesUi({ tab: "annotations" });
            useProjectStore.getState().setView({ kind: "notes" });
          }}
          title={t("inspector.openAnnotations")}
        >
          <SectionLabel>{t("inspector.annotations")}</SectionLabel>
          <IconButton
            label={t("inspector.addAnnotation")}
            title={t("inspector.addAnnotation")}
            size="sm"
            onClick={() => {
              setNewAnnMemo("");
              setInspectorNewAnnotation(true);
            }}
          >
            <Plus size={12} aria-hidden />
          </IconButton>
        </div>
        {annError && <p className="mb-1 text-xs text-danger">{annError}</p>}
        {/* Inline new-annotation editor (opened by "Add annotation") */}
        {inspectorNewAnnotation && (
          <div className="mb-2 rounded-sm border border-border bg-bg p-2">
            <Textarea
              autoFocus
              value={newAnnMemo}
              onChange={(e) => setNewAnnMemo(e.target.value)}
              placeholder={t("inspector.annotationPrompt")}
              aria-label={t("inspector.annotationPrompt")}
              className="min-h-14 w-full resize-none p-1.5"
            />
            <div className="mt-1.5 flex items-center justify-end gap-1.5">
              <Button
                variant="secondary"
                onClick={() => setInspectorNewAnnotation(false)}
              >
                {t("common.cancel")}
              </Button>
              <Button
                variant="primary"
                disabled={!newAnnMemo.trim()}
                onClick={() => void saveNewAnnotation()}
              >
                {t("inspector.addAnnotation")}
              </Button>
            </div>
          </div>
        )}
        {annotations.length === 0 ? (
          <p className="text-sm text-text-secondary">{t("inspector.noAnnotations")}</p>
        ) : (
          <ul className="flex flex-col gap-0.5">
            {annotations.map((a) => {
              if (editingAnnId === a.anid) {
                return (
                  <li
                    key={a.anid}
                    className="rounded-sm border border-border bg-bg p-1.5"
                  >
                    <Textarea
                      autoFocus
                      value={editingAnnMemo}
                      onChange={(e) => setEditingAnnMemo(e.target.value)}
                      placeholder={t("inspector.annotationPrompt")}
                      aria-label={t("inspector.annotationPrompt")}
                      className="min-h-14 w-full resize-none p-1.5"
                    />
                    <div className="mt-1.5 flex items-center justify-end gap-1.5">
                      <Button variant="secondary" onClick={() => setEditingAnnId(null)}>
                        {t("common.cancel")}
                      </Button>
                      <Button
                        variant="primary"
                        onClick={() => void saveAnnotationEdit(a.anid)}
                      >
                        {t("common.save")}
                      </Button>
                    </div>
                  </li>
                );
              }
              return (
                <li key={a.anid}>
                  <button
                    type="button"
                    onClick={() => {
                      setEditingAnnId(a.anid);
                      setEditingAnnMemo(a.memo);
                    }}
                    title={t("inspector.editAnnotation")}
                    className="flex w-full items-center gap-1.5 rounded-sm bg-surface-higher px-2 py-1 text-left hover:bg-border"
                  >
                    <span className="min-w-0 flex-1 truncate text-sm text-text-primary">
                      {a.memo || t("common.noMemo")}
                    </span>
                    <IconButton
                      label={t("coder.deleteAnnotation")}
                      title={t("coder.deleteAnnotation")}
                      size="sm"
                      className="shrink-0 hover:text-danger"
                      onClick={(e) => {
                        e.stopPropagation();
                        void deleteAnnotation(a.anid);
                      }}
                    >
                      <Trash2 size={11} aria-hidden />
                    </IconButton>
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </div>

      <MemoEditor key={src.id} memo={src.memo} onSave={saveMemo} />
    </div>
  );
}

export function Inspector() {
  const { t } = useI18n();
  const selection = useProjectStore((s) => s.inspectorSelection);
  const details = useProjectStore((s) => s.inspectorDetails);
  const loading = useProjectStore((s) => s.inspectorLoading);
  const error = useProjectStore((s) => s.inspectorError);
  const selectCode = useProjectStore((s) => s.selectCode);
  const selectFile = useProjectStore((s) => s.selectFile);
  const clearInspector = useProjectStore((s) => s.clearInspector);

  function retry() {
    if (!selection) return;
    void (selection.kind === "code" ? selectCode(selection.id) : selectFile(selection.id));
  }

  let body: ReactNode;
  if (loading) {
    body = (
      <div className="flex flex-1 items-center justify-center gap-2 text-sm text-text-secondary">
        <LoaderCircle size={14} className="animate-spin" aria-hidden />
        {t("common.loading")}
      </div>
    );
  } else if (!selection) {
    body = (
      <div className="flex flex-1 items-center justify-center px-4 text-center text-sm text-text-secondary">
        {t("inspector.selectHint")}
      </div>
    );
  } else if (error) {
    body = (
      <div className="flex flex-1 flex-col items-center justify-center gap-3 px-4 text-center">
        <p className="text-sm text-danger">{error}</p>
        <button
          type="button"
          onClick={retry}
          className="rounded-sm border border-border bg-bg px-3 py-1 text-xs hover:bg-surface-higher"
        >
          {t("common.retry")}
        </button>
      </div>
    );
  } else if (details && isCodeDetails(details)) {
    body = <CodeDetailsPanel details={details} />;
  } else if (details && isSourceDetails(details)) {
    body = <FileDetailsPanel details={details} />;
  } else {
    body = (
      <div className="flex flex-1 items-center justify-center px-4 text-center text-sm text-text-secondary">
        {t("inspector.selectHint")}
      </div>
    );
  }

  const itemName =
    details && isCodeDetails(details)
      ? details.code.name
      : details && isSourceDetails(details)
        ? details.source.name
        : null;

  return (
    <LeftBar
      borderSide="l"
      className="h-full min-h-0"
      header={
        <BarHeader
          title={
            selection ? (
              <span className="flex min-w-0 items-center gap-1.5">
                {selection.kind === "code" ? (
                  <Hash size={13} className="shrink-0 text-text-secondary" aria-hidden />
                ) : (
                  <FileText size={13} className="shrink-0 text-text-secondary" aria-hidden />
                )}
                <span className="truncate">{itemName ?? t("inspector.details")}</span>
              </span>
            ) : (
              t("inspector.details")
            )
          }
          actions={
            selection && (
              <IconButton label={t("common.closeDetails")} size="sm" onClick={clearInspector}>
                <X size={14} aria-hidden />
              </IconButton>
            )
          }
        />
      }
    >
      {body}
    </LeftBar>
  );
}
