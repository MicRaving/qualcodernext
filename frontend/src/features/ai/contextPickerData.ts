/**
 * ContextPickers data layer — loading + multi-select state for the
 * per-mode context pickers (shared by the chat and search panels).
 *
 * Every analysis mode loads all three kinds (additive pickers); the
 * selection may mix them freely. Memo keys keep the legacy
 * ``file:<id>``/``code:<id>`` shape; codes use ``c:<cid>`` and files
 * ``f:<sid>`` so the three pickers never collide.
 */
import { useEffect, useMemo, useState } from "react";
import { ApiError, api, fetchWithTimeout, initApiBase, type CodeTreeItem, type Source } from "@/lib/api";
import { CONTEXT_PICKERS, type AiMode, type ContextPickerKind } from "@/features/ai/aiModes";

export interface MemoEntry {
  kind: "file" | "code";
  id: number;
  name: string;
  memo: string;
  date: string;
  owner: string;
}

export async function fetchMemos(): Promise<MemoEntry[]> {
  const base = await initApiBase();
  const res = await fetchWithTimeout(`${base}/memos`);
  if (!res.ok) throw new ApiError(res.status, `API error ${res.status} on /memos`);
  const body = (await res.json()) as { memos: MemoEntry[] };
  return body.memos;
}

/** The code tree plus per-code coding counts (counts degrade to none). */
export async function fetchCodes(): Promise<{
  tree: CodeTreeItem[];
  counts: Map<number, number>;
}> {
  let tree: CodeTreeItem[] = [];
  try {
    tree = await api.codeTree();
  } catch {
    /* picker degrades to names only */
  }
  const counts = new Map<number, number>();
  try {
    const freq = await api.reports.codeFrequencies();
    for (const row of freq.rows) counts.set(row.cid, row.count);
  } catch {
    /* no count badges */
  }
  return { tree, counts };
}

/** Text sources (plain text, PDF, HTML) for the files picker. */
export async function fetchSources(): Promise<Source[]> {
  const sources = await api.sources();
  return sources
    .filter((s) => s.media_type === "text")
    .sort((a, b) => a.name.localeCompare(b.name));
}

export interface ContextPickerState {
  required: Record<ContextPickerKind, boolean>;
  data: {
    memos: MemoEntry[] | null;
    codes: CodeTreeItem[] | null;
    codeCounts: Map<number, number>;
    sources: Source[] | null;
  };
  query: Record<ContextPickerKind, string>;
  setQuery: (kind: ContextPickerKind, value: string) => void;
  selectedKeys: Set<string>;
  toggle: (key: string) => void;
  selectAll: (keys: string[]) => void;
  deselectAll: () => void;
  selectedMemoIds: number[];
  selectedCodeIds: number[];
  selectedSourceIds: number[];
}

/** Loads the context picker data for a mode and tracks the multi-select. */
export function useContextPickers(mode: AiMode): ContextPickerState {
  const required = CONTEXT_PICKERS[mode];
  const [data, setData] = useState<ContextPickerState["data"]>({
    memos: null,
    codes: null,
    codeCounts: new Map(),
    sources: null,
  });
  const [query, setQueryState] = useState<Record<ContextPickerKind, string>>({
    memos: "",
    codes: "",
    files: "",
  });
  const [selectedKeys, setSelectedKeys] = useState<Set<string>>(new Set());

  useEffect(() => {
    let cancelled = false;
    setSelectedKeys(new Set());
    setQueryState({ memos: "", codes: "", files: "" });
    setData((prev) => ({
      memos: required.memos ? null : prev.memos,
      codes: required.codes ? null : prev.codes,
      codeCounts: required.codes ? new Map() : prev.codeCounts,
      sources: required.files ? null : prev.sources,
    }));
    if (required.memos) {
      fetchMemos()
        .then((items) => {
          if (!cancelled) setData((p) => ({ ...p, memos: items }));
        })
        .catch(() => {
          if (!cancelled) setData((p) => ({ ...p, memos: [] }));
        });
    }
    if (required.codes) {
      fetchCodes()
        .then(({ tree, counts }) => {
          if (!cancelled) setData((p) => ({ ...p, codes: tree, codeCounts: counts }));
        })
        .catch(() => {
          if (!cancelled) setData((p) => ({ ...p, codes: [], codeCounts: new Map() }));
        });
    }
    if (required.files) {
      fetchSources()
        .then((items) => {
          if (!cancelled) setData((p) => ({ ...p, sources: items }));
        })
        .catch(() => {
          if (!cancelled) setData((p) => ({ ...p, sources: [] }));
        });
    }
    return () => {
      cancelled = true;
    };
  }, [mode, required.memos, required.codes, required.files]);

  const memoById = useMemo(
    () => new Map<string, MemoEntry>((data.memos ?? []).map((m) => [`${m.kind}:${m.id}`, m])),
    [data.memos],
  );
  const selectedMemoIds = useMemo(
    () =>
      Array.from(
        new Set(
          [...selectedKeys]
            .map((key) => memoById.get(key)?.id)
            .filter((id): id is number => id != null),
        ),
      ),
    [selectedKeys, memoById],
  );
  const selectedCodeIds = useMemo(
    () =>
      Array.from(
        new Set(
          [...selectedKeys]
            .filter((key) => key.startsWith("c:"))
            .map((key) => Number(key.slice(2)))
            .filter((id) => Number.isInteger(id)),
        ),
      ),
    [selectedKeys],
  );
  const selectedSourceIds = useMemo(
    () =>
      Array.from(
        new Set(
          [...selectedKeys]
            .filter((key) => key.startsWith("f:"))
            .map((key) => Number(key.slice(2)))
            .filter((id) => Number.isInteger(id)),
        ),
      ),
    [selectedKeys],
  );

  function toggle(key: string) {
    setSelectedKeys((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  function selectAll(keys: string[]) {
    if (keys.length === 0) return;
    setSelectedKeys((prev) => {
      const next = new Set(prev);
      for (const key of keys) next.add(key);
      return next;
    });
  }

  function deselectAll() {
    setSelectedKeys(new Set());
  }

  return {
    required,
    data,
    query,
    setQuery: (kind, value) => setQueryState((prev) => ({ ...prev, [kind]: value })),
    selectedKeys,
    toggle,
    selectAll,
    deselectAll,
    selectedMemoIds,
    selectedCodeIds,
    selectedSourceIds,
  };
}
