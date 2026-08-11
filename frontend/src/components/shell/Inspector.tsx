/**
 * Inspector — right-side details panel for the selected code or file.
 */
import { useState, type ReactNode } from "react";
import { ChevronRight, FileText, Hash, LoaderCircle, Pencil, Trash2, X } from "lucide-react";
import { api, type CodeDetails, type SourceDetails } from "@/lib/api";
import { AttributeEditor } from "@/components/shell/AttributeEditor";
import { BarHeader, IconButton, LeftBar, SectionLabel } from "@/components/ui/orchestrator";
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
        <div className="mb-1 flex items-center justify-between">
          <SectionLabel>{t("inspector.memo")}</SectionLabel>
          <button
            type="button"
            onClick={() => {
              setDraft(memo);
              setEditing(true);
            }}
            className="flex items-center gap-1 rounded-sm border border-border bg-bg px-1.5 py-0.5 text-xs text-text-secondary hover:bg-surface-higher hover:text-text-primary"
          >
            <Pencil size={11} aria-hidden />
            {memo.trim() === "" ? t("inspector.addMemo") : t("inspector.editMemo")}
          </button>
        </div>
        <p className="text-sm text-text-primary">
          {memo.trim() === "" ? (
            <span className="italic text-text-secondary">{t("common.noMemo")}</span>
          ) : (
            <span className="whitespace-pre-wrap">{memo}</span>
          )}
        </p>
      </div>
    );
  }

  return (
    <div className="px-3 py-2">
      <div className="mb-1">
        <SectionLabel>{t("inspector.memo")}</SectionLabel>
      </div>
      <textarea
        autoFocus
        value={draft ?? ""}
        onChange={(e) => setDraft(e.target.value)}
        rows={4}
        aria-label={t("inspector.memoAria")}
        className="w-full resize-y rounded-sm border border-border bg-bg px-2 py-1 text-sm text-text-primary outline-none focus:border-accent"
      />
      <div className="mt-1.5 flex items-center gap-1.5">
        <button
          type="button"
          onClick={() => void handleSave()}
          disabled={saving}
          className="flex items-center gap-1 rounded-sm bg-accent px-2 py-1 text-xs font-medium text-bg hover:bg-accent-hover disabled:opacity-50"
        >
          {saving && <LoaderCircle size={10} className="animate-spin" aria-hidden />}
          {t("common.save")}
        </button>
        <button
          type="button"
          onClick={() => {
            setEditing(false);
            setDraft(null);
          }}
          disabled={saving}
          className="rounded-sm border border-border px-2 py-1 text-xs hover:bg-surface-higher disabled:opacity-50"
        >
          {t("common.cancel")}
        </button>
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
  const stats = formatStats(details);

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

      {/* Stats */}
      <div className="flex gap-2 border-b border-border px-3 py-2">
        <div className="flex-1 rounded-sm bg-surface-higher px-2 py-1.5 text-center">
          <div className="text-sm font-semibold text-text-primary">{stats.primary}</div>
          <div className="text-xs text-text-secondary">{stats.secondary}</div>
        </div>
      </div>

      <MemoEditor key={details.code.cid} memo={details.code.memo} onSave={saveMemo} />
      {actionError && <p className="px-3 pb-2 text-xs text-danger">{actionError}</p>}

      {/* Recent coded segments */}
      <div className="px-3 py-2">
        <SectionLabel>{t("inspector.recentSegments")}</SectionLabel>
        {details.recent_examples.length === 0 ? (
          <p className="text-sm text-text-secondary">{t("inspector.noSegments")}</p>
        ) : (
          <ul className="flex flex-col gap-1.5">
            {details.recent_examples.slice(0, 5).map((ex) => (
              <li key={ex.ctid} className="rounded-sm bg-surface-higher px-2 py-1.5">
                <p className="truncate text-xs text-text-secondary">{ex.file_name}</p>
                <p className="line-clamp-2 text-sm text-text-primary">{ex.seltext}</p>
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
  const stats = formatStats(details);
  const src = details.source;

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
      </dl>

      {/* Stats */}
      <div className="flex gap-2 border-b border-border px-3 py-2">
        <div className="flex-1 rounded-sm bg-surface-higher px-2 py-1.5 text-center">
          <div className="text-sm font-semibold text-text-primary">{stats.primary}</div>
        </div>
        <div className="flex-1 rounded-sm bg-surface-higher px-2 py-1.5 text-center">
          <div className="text-sm font-semibold text-text-primary">{stats.secondary}</div>
        </div>
      </div>

      {/* Codes used */}
      <div className="px-3 py-2">
        <SectionLabel>{t("inspector.codesUsed")}</SectionLabel>
        {details.codes_used.length === 0 ? (
          <p className="text-sm text-text-secondary">{t("inspector.noCodings")}</p>
        ) : (
          <div className="flex flex-wrap gap-1">
            {details.codes_used.map((c) => (
              <span
                key={c.cid}
                className="flex items-center gap-1 rounded-sm bg-surface-higher px-1.5 py-0.5 text-xs"
              >
                <span
                  className="h-2 w-2 shrink-0 rounded-sm border border-border"
                  style={{ backgroundColor: c.color ?? SWATCH_FALLBACK }}
                  aria-hidden
                />
                <span className="max-w-28 truncate">{c.name}</span>
                <span className="text-text-secondary">{c.count}</span>
              </span>
            ))}
          </div>
        )}
      </div>

      {/* Cases */}
      <div className="px-3 py-2">
        <SectionLabel>{t("inspector.cases")}</SectionLabel>
        {details.cases.length === 0 ? (
          <p className="text-sm text-text-secondary">{t("inspector.noCases")}</p>
        ) : (
          <ul className="flex flex-col gap-0.5">
            {details.cases.map((c) => (
              <li key={c.caseid} className="truncate text-sm text-text-primary">
                {c.name}
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* Attributes — editable (file-scope property grid) */}
      <AttributeEditor
        entityId={src.id}
        scope="file"
        values={details.attributes.map((a) => ({ name: a.name, value: a.value }))}
        onChange={async () => {
          await selectFile(src.id);
        }}
      />

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
