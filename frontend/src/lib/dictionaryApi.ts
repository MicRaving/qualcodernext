/**
 * Typed client for the word-dictionary endpoints (dictionaries.py +
 * the dictionary-autocode endpoint in codings.py).
 *
 * api.ts is shared infrastructure; this small client lives beside it so the
 * dictionary feature can be added without touching the shared client.
 */
import { localRequest } from "@/lib/api";
import { SOURCE_TIMEOUT_MS } from "@/lib/config";

export interface DictionaryEntry {
  id: number;
  dict_id: number;
  code_name: string;
  term: string;
}

export interface DictionarySummary {
  id: number;
  name: string;
  owner: string | null;
  created: string | null;
  entries: DictionaryEntry[];
}

export interface DictionaryAutocodeResult {
  dictionary_id: number;
  per_code: { code_name: string; count: number }[];
  total: number;
  unmatched_codes: string[];
  skipped_terms: string[];
}

export interface DictionaryFrequencies {
  dictionary_id: number;
  dictionary_name: string;
  terms: string[];
  files: { fid: number; name: string }[];
  rows: { fid: number; file: string; counts: number[]; total: number }[];
  column_totals: number[];
  total: number;
  normalize: boolean;
}

async function request<T>(path: string, init?: RequestInit, timeoutMs = 30_000): Promise<T> {
  return localRequest<T>(path, init ?? {}, timeoutMs);
}

export const dictionaryApi = {
  list: () => request<DictionarySummary[]>("/dictionaries"),

  create: (name: string) =>
    request<DictionarySummary>("/dictionaries", { method: "POST", body: JSON.stringify({ name }) }),

  rename: (dictId: number, name: string) =>
    request<DictionarySummary>(`/dictionaries/${dictId}`, {
      method: "PATCH",
      body: JSON.stringify({ name }),
    }),

  remove: (dictId: number) =>
    request<void>(`/dictionaries/${dictId}`, { method: "DELETE" }, 15_000),

  addEntry: (dictId: number, codeName: string, term: string) =>
    request<DictionaryEntry>(`/dictionaries/${dictId}/entries`, {
      method: "POST",
      body: JSON.stringify({ code_name: codeName, term }),
    }),

  removeEntry: (entryId: number) =>
    request<void>(`/dictionaries/entries/${entryId}`, { method: "DELETE" }, 15_000),

  importFile: (file: File, name?: string) => {
    const form = new FormData();
    form.append("file", file);
    if (name) form.append("name", name);
    return request<{
      dictionary: DictionarySummary;
      created: boolean;
      added: number;
      skipped: number;
    }>("/dictionaries/import", { method: "POST", body: form }, 30_000);
  },

  autocode: (dictionaryId: number, sources?: number[] | null) =>
    request<DictionaryAutocodeResult>("/codings/dictionary-autocode", {
      method: "POST",
      body: JSON.stringify({
        dictionary_id: dictionaryId,
        sources: sources && sources.length > 0 ? sources : null,
      }),
    }, SOURCE_TIMEOUT_MS),

  frequencies: (dictionaryId: number, normalize = false, stopwords = true) =>
    request<DictionaryFrequencies>(
      `/dictionaries/${dictionaryId}/frequencies?normalize=${normalize}&stopwords=${stopwords}`,
    ),
};

