/**
 * DictionaryReport — MAXDictio-style word dictionaries.
 *
 * Dictionary CRUD (create/rename/import/delete), entry management (term +
 * code name), dictionary autocoding and the per-document x per-term
 * frequency matrix with CSV export.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { BookOpenText, Download, Plus, Trash2, Upload } from "lucide-react";
import { cn } from "@/lib/utils";
import { useI18n } from "@/lib/i18n";
import { downloadCsv } from "@/lib/csv";
import { useProjectStore } from "@/stores/project";
import {
  dictionaryApi,
  type DictionaryAutocodeResult,
  type DictionaryFrequencies,
  type DictionarySummary,
} from "@/lib/dictionaryApi";
import {
  Button,
  EmptyState,
  Field,
  Input,
  Select,
} from "@/components/ui/orchestrator";
import { errorDetail } from "@/features/ai/format";
import {
  cardCls,
  tdCls,
  thCls,
} from "@/features/analyze/reportData";
import {
  ReportMenuBar,
  ReportStatus,
} from "@/features/analyze/reportKit";

const formatCount = (n: number): string => (Number.isInteger(n) ? String(n) : n.toFixed(1));

export function DictionaryReport() {
  const { t } = useI18n();
  const codeNames = useProjectStore((s) => s.codeTree)
    .filter((c) => c.kind === "code")
    .map((c) => c.name);

  const [dictionaries, setDictionaries] = useState<DictionarySummary[] | null>(null);
  const [selectedId, setSelectedId] = useState<number | "">("");
  const [loadError, setLoadError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  const [newName, setNewName] = useState("");
  const [creating, setCreating] = useState(false);

  const [term, setTerm] = useState("");
  const [codeName, setCodeName] = useState("");
  const [entryError, setEntryError] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);

  const [autoResult, setAutoResult] = useState<DictionaryAutocodeResult | null>(null);
  const [autocoding, setAutocoding] = useState(false);

  const [freq, setFreq] = useState<DictionaryFrequencies | null>(null);
  const [freqLoading, setFreqLoading] = useState(false);
  const [freqError, setFreqError] = useState<string | null>(null);
  const [normalize, setNormalize] = useState(false);

  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const selected = useMemo(
    () => dictionaries?.find((d) => d.id === selectedId) ?? null,
    [dictionaries, selectedId],
  );

  useEffect(() => {
    let cancelled = false;
    setLoadError(null);
    dictionaryApi
      .list()
      .then((items) => {
        if (cancelled) return;
        setDictionaries(items);
        setSelectedId((prev) =>
          items.some((d) => d.id === prev) ? prev : (items[0]?.id ?? ""),
        );
      })
      .catch((e) => {
        if (!cancelled) setLoadError(e instanceof Error ? e.message : "Failed to load");
      });
    return () => {
      cancelled = true;
    };
  }, [attempt]);

  // Frequency matrix for the selected dictionary.
  useEffect(() => {
    if (selectedId === "") {
      setFreq(null);
      setFreqError(null);
      return;
    }
    let cancelled = false;
    setFreqLoading(true);
    setFreqError(null);
    dictionaryApi
      .frequencies(selectedId, normalize)
      .then((data) => {
        if (!cancelled) setFreq(data);
      })
      .catch((e) => {
        if (!cancelled) setFreqError(e instanceof Error ? e.message : "Failed to load");
      })
      .finally(() => {
        if (!cancelled) setFreqLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedId, normalize, attempt]);

  async function refresh() {
    setAttempt((a) => a + 1);
  }

  async function createDictionary() {
    const name = newName.trim();
    if (!name) return;
    setCreating(true);
    try {
      const created = await dictionaryApi.create(name);
      await refresh();
      setSelectedId(created.id);
      setNewName("");
    } catch (e) {
      setLoadError(errorDetail(e, t("dictionary.createError")));
    } finally {
      setCreating(false);
    }
  }

  async function importFile(file: File) {
    setLoadError(null);
    try {
      const result = await dictionaryApi.importFile(file);
      await refresh();
      setSelectedId(result.dictionary.id);
    } catch (e) {
      setLoadError(errorDetail(e, t("dictionary.importError")));
    }
  }

  async function deleteDictionary() {
    if (!selected || !window.confirm(t("dictionary.deleteConfirm", { name: selected.name }))) {
      return;
    }
    try {
      await dictionaryApi.remove(selected.id);
      setSelectedId("");
      await refresh();
    } catch (e) {
      setLoadError(errorDetail(e, t("dictionary.deleteError")));
    }
  }

  async function addEntry() {
    if (!selected) return;
    const trimmedTerm = term.trim();
    const trimmedCode = codeName.trim();
    if (!trimmedTerm || !trimmedCode) return;
    setAdding(true);
    setEntryError(null);
    try {
      await dictionaryApi.addEntry(selected.id, trimmedCode, trimmedTerm);
      setTerm("");
      setCodeName("");
      await refresh();
    } catch (e) {
      setEntryError(errorDetail(e, t("dictionary.entryAddError")));
    } finally {
      setAdding(false);
    }
  }

  async function removeEntry(entryId: number) {
    try {
      await dictionaryApi.removeEntry(entryId);
      await refresh();
    } catch (e) {
      setLoadError(errorDetail(e, t("dictionary.entryDeleteError")));
    }
  }

  async function runAutocode() {
    if (!selected) return;
    setAutocoding(true);
    setLoadError(null);
    try {
      setAutoResult(await dictionaryApi.autocode(selected.id, null));
    } catch (e) {
      setLoadError(errorDetail(e, t("dictionary.autocodeError")));
    } finally {
      setAutocoding(false);
    }
  }

  const csvHeaders = useMemo(() => {
    if (!freq) return [];
    return [t("dictionary.colFile"), ...freq.terms, t("dictionary.colTotal")];
  }, [freq, t]);

  const csvRows = useMemo(() => {
    if (!freq) return [];
    return [
      ...freq.rows.map((r) => [r.file, ...r.counts, r.total]),
      [t("dictionary.colTotal"), ...freq.column_totals, freq.total],
    ];
  }, [freq, t]);

  if (loadError && !dictionaries) {
    return <ReportStatus loading={false} error={loadError} onRetry={refresh} />;
  }

  return (
    <div className="space-y-2">
      <ReportMenuBar>
        {freq && (
          <Button
            variant="secondary"
            className="text-text-secondary hover:text-text-primary"
            onClick={() =>
              downloadCsv(`dictionary-${freq.dictionary_name}.csv`, csvHeaders, csvRows)
            }
            icon={<Download size={12} aria-hidden />}
          >
            CSV
          </Button>
        )}
      </ReportMenuBar>

      {/* Toolbar: picker, create, import, delete */}
      <div className="flex flex-wrap items-end gap-2">
        <Field label={t("dictionary.pickDictionary")} className="min-w-44 flex-1">
          <Select
            value={selectedId}
            onChange={(e) => setSelectedId(e.target.value === "" ? "" : Number(e.target.value))}
            aria-label={t("dictionary.pickDictionary")}
            className="w-full"
          >
            {(dictionaries ?? []).map((d) => (
              <option key={d.id} value={d.id}>
                {d.name} ({d.entries.length})
              </option>
            ))}
          </Select>
        </Field>
        <Field label={t("dictionary.create")} className="min-w-40 flex-1">
          <div className="flex gap-1">
            <Input
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              placeholder={t("dictionary.namePlaceholder")}
              aria-label={t("dictionary.create")}
              className="w-full"
              onKeyDown={(e) => {
                if (e.key === "Enter") void createDictionary();
              }}
            />
            <Button
              variant="primary"
              icon={<Plus size={12} aria-hidden />}
              onClick={() => void createDictionary()}
              disabled={creating || !newName.trim()}
              aria-label={t("dictionary.create")}
            />
          </div>
        </Field>
        <div className="flex items-center gap-1 pb-0.5">
          <Button
            variant="secondary"
            icon={<Upload size={12} aria-hidden />}
            onClick={() => fileInputRef.current?.click()}
          >
            {t("dictionary.import")}
          </Button>
          {selected && (
            <Button
              variant="secondary"
              className="text-danger hover:bg-danger/10"
              icon={<Trash2 size={12} aria-hidden />}
              onClick={() => void deleteDictionary()}
            >
              {t("dictionary.delete")}
            </Button>
          )}
          <input
            ref={fileInputRef}
            type="file"
            accept=".txt,.csv,text/plain,text/csv"
            className="hidden"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) void importFile(file);
              e.target.value = "";
            }}
          />
        </div>
      </div>

      {loadError && <p className="text-xs text-danger">{loadError}</p>}

      {dictionaries && dictionaries.length === 0 ? (
        <div className="h-48">
          <EmptyState icon={<BookOpenText size={20} aria-hidden />}>
            {t("dictionary.noDictionaries")}
          </EmptyState>
        </div>
      ) : selected ? (
        <>
          {/* Dictionary autocode */}
          <div className="flex items-center gap-2 rounded-sm border border-border bg-surface px-2 py-1.5">
            <Button
              variant="primary"
              icon={<BookOpenText size={12} aria-hidden />}
              onClick={() => void runAutocode()}
              disabled={autocoding || selected.entries.length === 0}
            >
              {autocoding ? t("dictionary.autocoding") : t("dictionary.autocode")}
            </Button>
            {autoResult && (
              <span className="text-xs text-success">
                {t("dictionary.autocoded", { total: autoResult.total })}
                {autoResult.per_code.length > 0 &&
                  ` · ${autoResult.per_code
                    .map((c) => t("dictionary.autocodedPerCode", { code: c.code_name, count: c.count }))
                    .join(", ")}`}
                {autoResult.unmatched_codes.length > 0 && (
                  <span className="text-text-secondary">
                    {" · "}
                    {t("dictionary.unmatchedCodes", {
                      names: autoResult.unmatched_codes.join(", "),
                    })}
                  </span>
                )}
              </span>
            )}
          </div>

          {/* Entries */}
          <div className={cardCls}>
            <table className="w-full border-collapse">
              <thead className="sticky top-0 z-10">
                <tr>
                  <th className={thCls}>{t("dictionary.entryTerm")}</th>
                  <th className={thCls}>{t("dictionary.entryCode")}</th>
                  <th className={cn(thCls, "w-10")} />
                </tr>
              </thead>
              <tbody>
                {selected.entries.length === 0 ? (
                  <tr>
                    <td colSpan={3} className={cn(tdCls, "py-4 text-center text-text-secondary")}>
                      {t("dictionary.noEntries")}
                    </td>
                  </tr>
                ) : (
                  selected.entries.map((entry) => (
                    <tr key={entry.id} className="hover:bg-surface-higher">
                      <td className={cn(tdCls, "font-medium")}>{entry.term}</td>
                      <td className={tdCls}>
                        <span className="rounded-sm bg-surface-higher px-1.5 py-px text-xs text-text-secondary">
                          {entry.code_name}
                        </span>
                      </td>
                      <td className={cn(tdCls, "text-right")}>
                        <button
                          type="button"
                          title={t("dictionary.entryDelete")}
                          aria-label={`${t("dictionary.entryDelete")}: ${entry.term}`}
                          onClick={() => void removeEntry(entry.id)}
                          className="rounded-sm p-1 text-text-secondary hover:bg-danger/10 hover:text-danger"
                        >
                          <Trash2 size={12} aria-hidden />
                        </button>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>

          {/* Add entry form */}
          <div className="flex items-end gap-2">
            <Field label={t("dictionary.entryTerm")} className="flex-1">
              <Input
                value={term}
                onChange={(e) => setTerm(e.target.value)}
                placeholder={t("dictionary.entryTermPlaceholder")}
                aria-label={t("dictionary.entryTerm")}
                className="w-full"
              />
            </Field>
            <Field label={t("dictionary.entryCode")} className="flex-1">
              <Input
                value={codeName}
                onChange={(e) => setCodeName(e.target.value)}
                placeholder={t("dictionary.entryCodePlaceholder")}
                aria-label={t("dictionary.entryCode")}
                list="qc-dictionary-code-options"
                className="w-full"
              />
              <datalist id="qc-dictionary-code-options">
                {codeNames.map((name) => (
                  <option key={name} value={name} />
                ))}
              </datalist>
            </Field>
            <Button
              variant="primary"
              icon={<Plus size={12} aria-hidden />}
              onClick={() => void addEntry()}
              disabled={adding || !term.trim() || !codeName.trim()}
            >
              {t("dictionary.entryAdd")}
            </Button>
          </div>
          {entryError && <p className="text-xs text-danger">{entryError}</p>}

          {/* Frequency matrix */}
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-medium text-text-primary">{t("dictionary.frequencies")}</h2>
            <label className="flex items-center gap-1.5 text-xs text-text-secondary">
              <input
                type="checkbox"
                checked={normalize}
                onChange={(e) => setNormalize(e.target.checked)}
                className="accent-accent"
              />
              {t("dictionary.normalize")}
            </label>
          </div>
          {freqLoading ? (
            <ReportStatus loading error={null} onRetry={() => {}} />
          ) : freqError ? (
            <ReportStatus loading={false} error={freqError} onRetry={refresh} />
          ) : freq && freq.rows.length > 0 ? (
            <div className={cardCls}>
              <table className="w-full border-collapse">
                <thead className="sticky top-0 z-10">
                  <tr>
                    <th className={thCls}>{t("dictionary.colFile")}</th>
                    {freq.terms.map((termName) => (
                      <th key={termName} className={cn(thCls, "text-right")}>
                        {termName}
                      </th>
                    ))}
                    <th className={cn(thCls, "text-right")}>{t("dictionary.colTotal")}</th>
                  </tr>
                </thead>
                <tbody>
                  {freq.rows.map((row) => (
                    <tr key={row.fid} className="hover:bg-surface-higher">
                      <td className={cn(tdCls, "max-w-56")}>
                        <span className="block truncate font-medium" title={row.file}>
                          {row.file}
                        </span>
                      </td>
                      {row.counts.map((count, i) => (
                        <td
                          key={freq.terms[i]}
                          className={cn(tdCls, "text-right tabular-nums")}
                        >
                          {formatCount(count)}
                        </td>
                      ))}
                      <td className={cn(tdCls, "text-right font-medium tabular-nums")}>
                        {formatCount(row.total)}
                      </td>
                    </tr>
                  ))}
                  <tr className="border-t-2 border-border bg-surface-higher">
                    <td className={cn(tdCls, "font-semibold")}>{t("dictionary.colTotal")}</td>
                    {freq.column_totals.map((total, i) => (
                      <td key={freq.terms[i]} className={cn(tdCls, "text-right font-semibold tabular-nums")}>
                        {formatCount(total)}
                      </td>
                    ))}
                    <td className={cn(tdCls, "text-right font-semibold tabular-nums")}>
                      {formatCount(freq.total)}
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          ) : freq ? (
            <div className="h-32">
              <EmptyState>{t("dictionary.noFrequencies")}</EmptyState>
            </div>
          ) : null}
        </>
      ) : null}
    </div>
  );
}
