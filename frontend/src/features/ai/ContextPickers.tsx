/**
 * ContextPickers — the per-mode context picker strip shared by the chat
 * panel and the semantic-search panel.
 *
 * Each analysis mode shows the relevant entity list (memos for memo
 * analysis, codes for code analysis, files for text analysis, all three
 * for topic exploration and semantic search) with multi-select and
 * Select all / Deselect all. The search panel uses the selected files as
 * a search filter. Data loading and selection state live in
 * ``contextPickerData.ts``.
 */
import { useEffect, useMemo, useState } from "react";
import { Search } from "lucide-react";
import { type CodeTreeItem } from "@/lib/api";
import { mediaTypeLabel } from "@/features/manage/files";
import { useI18n } from "@/lib/i18n";
import { Input, SectionLabel } from "@/components/ui/orchestrator";
import { CONTEXT_PICKER_KINDS, type ContextPickerKind } from "@/features/ai/aiModes";
import {
  type ContextPickerState,
  type MemoEntry,
} from "@/features/ai/contextPickerData";

interface PickerItem {
  key: string;
  name: string;
  /** Right-hand meta next to the name (category, media type). */
  hint?: string;
  /** Count badge (code picker). */
  badge?: string;
  /** Tooltip (memo/explanation text). */
  title?: string;
}

interface PickerGroup {
  label?: string;
  items: PickerItem[];
}

const KIND_FIELD: Record<ContextPickerKind, keyof ContextPickerState["data"]> = {
  memos: "memos",
  codes: "codes",
  files: "sources",
};

/** One entity list with header, search box, Select all / Deselect all. */
function ContextPicker({
  label,
  placeholder,
  emptyText,
  query,
  onQuery,
  selected,
  onToggle,
  onSelectAll,
  onDeselectAll,
  selectedCount,
  groups,
}: {
  label: string;
  placeholder: string;
  emptyText: string;
  query: string;
  onQuery: (value: string) => void;
  selected: Set<string>;
  onToggle: (key: string) => void;
  onSelectAll: (keys: string[]) => void;
  onDeselectAll: () => void;
  selectedCount: number;
  groups: PickerGroup[];
}) {
  const { t } = useI18n();
  const visibleKeys = useMemo(() => groups.flatMap((g) => g.items.map((i) => i.key)), [groups]);
  const allVisibleSelected =
    visibleKeys.length > 0 && visibleKeys.every((key) => selected.has(key));
  const isEmpty = groups.every((g) => g.items.length === 0);

  return (
    <div className="flex min-w-0 flex-col gap-1.5">
      <div className="flex min-w-0 items-center justify-between gap-1.5">
        <span className="text-[10px] font-semibold uppercase tracking-wide text-text-secondary">
          {label}
        </span>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => onSelectAll(visibleKeys)}
            disabled={visibleKeys.length === 0 || allVisibleSelected}
            className="text-[11px] text-accent hover:underline disabled:cursor-not-allowed disabled:opacity-50"
          >
            {t("ai.selectAll")}
          </button>
          <button
            type="button"
            onClick={onDeselectAll}
            disabled={selectedCount === 0}
            className="text-[11px] text-accent hover:underline disabled:cursor-not-allowed disabled:opacity-50"
          >
            {t("ai.deselectAll")}
          </button>
        </div>
      </div>
      <div className="flex min-w-0 items-center gap-1.5">
        <Search size={12} className="shrink-0 text-text-secondary" aria-hidden />
        <Input
          value={query}
          onChange={(e) => onQuery(e.target.value)}
          placeholder={placeholder}
          aria-label={placeholder}
          className="h-7 min-w-0 flex-1 px-2 py-1 text-xs"
        />
        <span className="shrink-0 text-[10px] text-text-secondary">
          {t("ai.memosSelected", { count: selectedCount })}
        </span>
      </div>
      <div className="qc-scroll min-w-0 max-h-40 overflow-y-auto rounded-sm border border-border bg-bg p-1">
        {isEmpty ? (
          <p className="px-2 py-3 text-center text-xs text-text-secondary">{emptyText}</p>
        ) : (
          groups.map((group) => (
            <div key={group.label ?? "items"} className="min-w-0">
              {group.label && <SectionLabel>{group.label}</SectionLabel>}
              {group.items.map((item) => (
                <label
                  key={item.key}
                  className="flex min-w-0 cursor-pointer items-center gap-1.5 rounded-sm px-1.5 py-0.5 text-xs hover:bg-surface-higher"
                  title={item.title}
                >
                  <input
                    type="checkbox"
                    checked={selected.has(item.key)}
                    onChange={() => onToggle(item.key)}
                    className="accent-accent"
                  />
                  <span className="truncate">{item.name}</span>
                  {item.hint && <span className="truncate text-text-secondary">{item.hint}</span>}
                  {item.badge && (
                    <span className="ml-auto shrink-0 rounded-full bg-surface-higher px-1.5 text-[10px] text-text-secondary">
                      {item.badge}
                    </span>
                  )}
                </label>
              ))}
            </div>
          ))
        )}
      </div>
    </div>
  );
}

const PICKER_LABELS: Record<ContextPickerKind, string> = {
  memos: "ai.contextMemos",
  codes: "ai.contextCodes",
  files: "ai.contextFiles",
};

const PICKER_TAB_LABELS: Record<ContextPickerKind, string> = {
  memos: "ai.pickerMemos",
  codes: "ai.pickerCodes",
  files: "ai.pickerFiles",
};

/**
 * The context strip above the chat input. Single-picker modes render the
 * picker directly (same look as before); multi-picker modes (topic
 * exploration, semantic search) get a Memos / Codes / Files tab row.
 */
export function ContextPickerArea({ pickers }: { pickers: ContextPickerState }) {
  const { t } = useI18n();
  const kinds = useMemo(
    () => CONTEXT_PICKER_KINDS.filter((k) => pickers.required[k]),
    [pickers.required],
  );
  const [active, setActive] = useState<ContextPickerKind>(kinds[0] ?? "memos");

  useEffect(() => {
    if (!kinds.includes(active)) setActive(kinds[0] ?? "memos");
  }, [kinds, active]);

  const loading = kinds.some((k) => pickers.data[KIND_FIELD[k]] === null);

  function countFor(kind: ContextPickerKind): number {
    let n = 0;
    for (const key of pickers.selectedKeys) {
      if (kind === "memos" && (key.startsWith("file:") || key.startsWith("code:"))) n++;
      else if (kind === "codes" && key.startsWith("c:")) n++;
      else if (kind === "files" && key.startsWith("f:")) n++;
    }
    return n;
  }

  const memoGroups: PickerGroup[] = useMemo(() => {
    const q = pickers.query.memos.trim().toLowerCase();
    const visible = (pickers.data.memos ?? []).filter(
      (m) => !q || m.name.toLowerCase().includes(q) || m.memo.toLowerCase().includes(q),
    );
    const toItem = (m: MemoEntry): PickerItem => ({
      key: `${m.kind}:${m.id}`,
      name: m.name,
      title: m.memo,
    });
    return [
      { label: t("ai.memosFile"), items: visible.filter((m) => m.kind === "file").map(toItem) },
      { label: t("ai.memosCode"), items: visible.filter((m) => m.kind === "code").map(toItem) },
    ].filter((g) => g.items.length > 0);
  }, [pickers.data.memos, pickers.query.memos, t]);

  const codeGroups: PickerGroup[] = useMemo(() => {
    const items = pickers.data.codes ?? [];
    if (items.length === 0) return [];
    const byId = new Map(items.map((i) => [i.id, i]));
    const categoryOf = (item: CodeTreeItem): string => {
      let current = item;
      for (let depth = 0; depth < 10 && current.parent_id != null; depth++) {
        const parent = byId.get(current.parent_id);
        if (!parent) break;
        if (parent.kind === "category") return parent.name;
        current = parent;
      }
      return "";
    };
    const q = pickers.query.codes.trim().toLowerCase();
    const visible = items.filter((item) => {
      if (item.kind !== "code") return false;
      if (!q) return true;
      const category = categoryOf(item).toLowerCase();
      return (
        item.name.toLowerCase().includes(q) ||
        (category !== "" && category.includes(q)) ||
        item.memo.toLowerCase().includes(q)
      );
    });
    return [
      {
        items: visible.map((item) => {
          const category = categoryOf(item);
          return {
            key: `c:${item.id}`,
            name: item.name,
            hint: category ? `(${category})` : undefined,
            badge: String(pickers.data.codeCounts.get(item.id) ?? 0),
            title: item.memo || undefined,
          };
        }),
      },
    ];
  }, [pickers.data.codes, pickers.data.codeCounts, pickers.query.codes]);

  const fileGroups: PickerGroup[] = useMemo(() => {
    const q = pickers.query.files.trim().toLowerCase();
    const visible = (pickers.data.sources ?? []).filter(
      (s) => !q || s.name.toLowerCase().includes(q) || s.memo.toLowerCase().includes(q),
    );
    return [
      {
        items: visible.map((s) => ({
          key: `f:${s.id}`,
          name: s.name,
          hint: mediaTypeLabel(s.media_type, s.name),
          title: s.memo || undefined,
        })),
      },
    ];
  }, [pickers.data.sources, pickers.query.files]);

  return (
    <div className="min-w-0 shrink-0 border-t border-border bg-surface px-3 py-2">
      <div className="mx-auto flex min-w-0 w-full max-w-2xl flex-col gap-2">
        {kinds.length > 1 && (
          <div className="flex items-center gap-0.5 rounded-sm border border-border bg-bg p-0.5">
            {kinds.map((kind) => (
              <button
                key={kind}
                type="button"
                onClick={() => setActive(kind)}
                aria-pressed={active === kind}
                className={`flex items-center rounded-sm px-2 py-1 text-xs font-medium ${
                  active === kind
                    ? "bg-surface-higher text-accent"
                    : "text-text-secondary hover:text-text-primary"
                }`}
              >
                {t(PICKER_TAB_LABELS[kind])}
              </button>
            ))}
          </div>
        )}
        {loading ? (
          <p className="py-1 text-center text-xs text-text-secondary">{t("ai.contextLoading")}</p>
        ) : active === "memos" ? (
          <ContextPicker
            label={t(PICKER_LABELS.memos)}
            placeholder={t("ai.memosSearch")}
            emptyText={t("ai.memosEmpty")}
            query={pickers.query.memos}
            onQuery={(v) => pickers.setQuery("memos", v)}
            selected={pickers.selectedKeys}
            onToggle={pickers.toggle}
            onSelectAll={pickers.selectAll}
            onDeselectAll={pickers.deselectAll}
            selectedCount={countFor("memos")}
            groups={memoGroups}
          />
        ) : active === "codes" ? (
          <ContextPicker
            label={t(PICKER_LABELS.codes)}
            placeholder={t("ai.codesSearch")}
            emptyText={t("ai.codesEmpty")}
            query={pickers.query.codes}
            onQuery={(v) => pickers.setQuery("codes", v)}
            selected={pickers.selectedKeys}
            onToggle={pickers.toggle}
            onSelectAll={pickers.selectAll}
            onDeselectAll={pickers.deselectAll}
            selectedCount={countFor("codes")}
            groups={codeGroups}
          />
        ) : (
          <ContextPicker
            label={t(PICKER_LABELS.files)}
            placeholder={t("ai.filesSearch")}
            emptyText={t("ai.filesEmpty")}
            query={pickers.query.files}
            onQuery={(v) => pickers.setQuery("files", v)}
            selected={pickers.selectedKeys}
            onToggle={pickers.toggle}
            onSelectAll={pickers.selectAll}
            onDeselectAll={pickers.deselectAll}
            selectedCount={countFor("files")}
            groups={fileGroups}
          />
        )}
      </div>
    </div>
  );
}
