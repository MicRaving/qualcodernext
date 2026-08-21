/**
 * ContextPickers data layer — loading + multi-select state for the
 * context pickers shared with every AI chat request.
 *
 * All three kinds (memos / codes / files) are always loaded and shown
 * (additive pickers); the selection may mix them freely. Memo keys keep the
 * legacy ``file:<id>``/``code:<id>`` shape; codes use ``c:<cid>`` and files
 * ``f:<sid>`` so the three pickers never collide.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { useAsyncEffect } from "@/lib/useAsync";
import { ApiError, api, fetchWithTimeout, initApiBase, type CodeTreeItem, type Source } from "@/lib/api";
import { type ContextPickerKind } from "@/features/ai/aiModes";

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
  /** True when every loaded memos/codes/files key is selected ("All"). */
  all: boolean;
  /** Select or clear the whole dataset at once. */
  setAll: (on: boolean) => void;
  toggle: (key: string) => void;
  selectAll: (keys: string[]) => void;
  deselectAll: () => void;
  selectedMemoIds: number[];
  selectedCodeIds: number[];
  selectedSourceIds: number[];
}

/** Loads the context picker data (all three kinds) and tracks the multi-select. */
export function useContextPickers(): ContextPickerState {
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

  // All keys across the three pickers (memo keys keep their ``file:``/``code:``
  // prefixes, code rows use ``c:`` and files ``f:`` so nothing collides).
  const allKeys = useMemo(() => {
    const keys = new Set<string>();
    for (const memo of data.memos ?? []) keys.add(`${memo.kind}:${memo.id}`);
    for (const code of data.codes ?? []) if (code.kind === "code") keys.add(`c:${code.id}`);
    for (const source of data.sources ?? []) keys.add(`f:${source.id}`);
    return keys;
  }, [data.memos, data.codes, data.sources]);

  // All is the default: on the first full data load, select everything.
  const seeded = useRef(false);
  useEffect(() => {
    if (seeded.current) return;
    if (data.memos === null || data.codes === null || data.sources === null) return;
    seeded.current = true;
    setSelectedKeys(new Set(allKeys));
  }, [data.memos, data.codes, data.sources, allKeys]);

  const all = allKeys.size > 0 && [...allKeys].every((key) => selectedKeys.has(key));

  function setAll(on: boolean) {
    setSelectedKeys(on ? new Set(allKeys) : new Set());
  }

  useAsyncEffect(async (signal) => {
    setSelectedKeys(new Set());
    setQueryState({ memos: "", codes: "", files: "" });
    setData((prev) => ({ ...prev, memos: null, codes: null, codeCounts: new Map(), sources: null }));

    await Promise.allSettled([
      fetchMemos()
        .then((items) => {
          signal.throwIfAborted();
          setData((p) => ({ ...p, memos: items }));
        })
        .catch(() => {
          signal.throwIfAborted();
          setData((p) => ({ ...p, memos: [] }));
        }),
      fetchCodes()
        .then(({ tree, counts }) => {
          signal.throwIfAborted();
          setData((p) => ({ ...p, codes: tree, codeCounts: counts }));
        })
        .catch(() => {
          signal.throwIfAborted();
          setData((p) => ({ ...p, codes: [], codeCounts: new Map() }));
        }),
      fetchSources()
        .then((items) => {
          signal.throwIfAborted();
          setData((p) => ({ ...p, sources: items }));
        })
        .catch(() => {
          signal.throwIfAborted();
          setData((p) => ({ ...p, sources: [] }));
        }),
    ]);
  }, []);

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
    required: { memos: true, codes: true, files: true },
    data,
    query,
    setQuery: (kind, value) => setQueryState((prev) => ({ ...prev, [kind]: value })),
    selectedKeys,
    all,
    setAll,
    toggle,
    selectAll,
    deselectAll,
    selectedMemoIds,
    selectedCodeIds,
    selectedSourceIds,
  };
}
