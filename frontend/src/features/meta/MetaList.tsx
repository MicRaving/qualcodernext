/**
 * Meta-analysis left bar — the study list for the active pipeline tab
 * (Screening: all hits / Downloads: abstract-included / Extraction:
 * acquired) plus that tab's primary actions in the header:
 *   Screen   → Import
 *   Download → Download, Import PDFs (batch)
 *   Extract  → coding-scheme picker + Create scheme, and row checkboxes for
 *              multi-select autocoding.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { ArrowDownToLine, Upload } from "lucide-react";
import { api } from "@/lib/api";
import type { MetaHit, MetaScheme } from "@/lib/api/types";
import { BarHeader, Button, EmptyState, Input, LeftBar, Select } from "@/components/ui/orchestrator";
import { useI18n } from "@/lib/i18n";
import { useToast } from "@/lib/toast";
import { errorMessage } from "@/lib/utils";
import { useWorkspaceStore } from "@/stores/workspace";

const CHECKBOX =
  "h-3.5 w-3.5 shrink-0 cursor-pointer rounded-sm border border-border accent-[var(--qc-accent)]";

function scopeForTab(tab: string): "all" | "included" | "acquired" {
  if (tab === "download") return "included";
  if (tab === "extract") return "acquired";
  return "all";
}

export function MetaList() {
  const { t } = useI18n();
  const toast = useToast();
  const tab = useWorkspaceStore((s) => s.metaUi.tab);
  const selectedHit = useWorkspaceStore((s) => s.metaUi.selectedHit);
  const selectedIds = useWorkspaceStore((s) => s.metaUi.selectedIds);
  const scheme = useWorkspaceStore((s) => s.metaUi.scheme);
  const email = useWorkspaceStore((s) => s.metaUi.email);
  const tick = useWorkspaceStore((s) => s.metaUi.tick);
  const setMetaUi = useWorkspaceStore((s) => s.setMetaUi);

  const [hits, setHits] = useState<MetaHit[]>([]);
  const [total, setTotal] = useState(0);
  const [schemes, setSchemes] = useState<MetaScheme[]>([]);
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const pdfRef = useRef<HTMLInputElement>(null);

  const scope = scopeForTab(tab);
  const bumped = tick + 1;

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const [res, schemeList] = await Promise.all([
          api.metaHits({ scope, limit: 500 }),
          tab === "extract" ? api.metaSchemes() : Promise.resolve<MetaScheme[]>([]),
        ]);
        if (cancelled) return;
        setHits(res.hits);
        setTotal(res.total);
        if (tab === "extract") setSchemes(schemeList);
      } catch {
        /* no project open */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [scope, tab, tick]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return hits;
    return hits.filter((h) =>
      [h.title, h.authors, h.doi].some((v) => (v ?? "").toString().toLowerCase().includes(q)),
    );
  }, [hits, query]);

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
      setMetaUi({ tick: bumped });
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
      setMetaUi({ tick: bumped });
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setBusy(false);
      if (pdfRef.current) pdfRef.current.value = "";
    }
  };

  const selectAllControl = (
    <label className="flex items-center gap-1.5 text-[11px] text-text-secondary">
      {tab === "extract" && (
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
        <BarHeader title={t("meta.listTitle")} count={total}>
          {tab === "screen" && (
            <Button
              variant="secondary"
              icon={<Upload size={12} aria-hidden />}
              onClick={() => setMetaUi({ importOpen: true })}
            >
              {t("meta.importSearch")}
            </Button>
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
          {tab === "extract" && (
            <>
              <Select
                value={scheme}
                onChange={(e) => setMetaUi({ scheme: e.target.value })}
                className="h-7 w-32 text-xs"
                aria-label={t("meta.scheme")}
                title={t("meta.scheme")}
              >
                {schemes.length === 0 && <option value="">—</option>}
                {schemes.map((s) => (
                  <option key={s.id} value={s.name}>
                    {s.label ?? s.name}
                  </option>
                ))}
              </Select>
              <Button variant="secondary" onClick={() => setMetaUi({ schemeOpen: true })}>
                {t("meta.create")}
              </Button>
            </>
          )}
        </BarHeader>
      }
    >
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
      <div className="min-h-0 flex-1 overflow-y-auto">
        {filtered.length === 0 ? (
          <EmptyState>{total === 0 ? t("meta.noEligible") : t("meta.noMatches")}</EmptyState>
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
                  {tab === "extract" && (
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
                    <span className="truncate text-xs text-text-secondary">
                      {hit.authors ?? ""} {hit.year ? `· ${hit.year}` : ""}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        )}
        {total > hits.length && (
          <p className="px-3 py-2 text-[11px] text-text-secondary">
            {t("meta.listTruncated", { shown: String(hits.length), total: String(total) })}
          </p>
        )}
      </div>
    </LeftBar>
  );
}
