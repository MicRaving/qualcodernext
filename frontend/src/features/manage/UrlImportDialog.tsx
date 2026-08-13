/**
 * UrlImportDialog — import a web resource as a new source: Reddit thread,
 * YouTube video (metadata, captions, comments), article text, raw HTML,
 * or a PDF rendering of a page. The backend fetches and parses the URL;
 * this dialog only submits it.
 */
import { useState, type FormEvent } from "react";
import { Globe, LoaderCircle } from "lucide-react";
import { ApiError, fetchWithTimeout, initApiBase } from "@/lib/api";
import { Button, ErrorBanner, Field, Input, Modal, Select } from "@/components/ui/orchestrator";
import { useI18n } from "@/lib/i18n";
import { useToast } from "@/lib/toast";
import { useProjectStore } from "@/stores/project";

export type ScrapeMode = "auto" | "reddit" | "youtube" | "article" | "html" | "pdf";

interface ScrapeResult {
  source_id: number;
  name: string;
  mode: string;
  text_length: number;
}

const MODE_OPTIONS: { value: ScrapeMode; labelKey: string }[] = [
  { value: "auto", labelKey: "files.urlImportModeAuto" },
  { value: "reddit", labelKey: "files.urlImportModeReddit" },
  { value: "youtube", labelKey: "files.urlImportModeYoutube" },
  { value: "article", labelKey: "files.urlImportModeArticle" },
  { value: "html", labelKey: "files.urlImportModeHtml" },
  { value: "pdf", labelKey: "files.urlImportModePdf" },
];

/**
 * Local-fetch POST (the /scrape endpoints are not in lib/api.ts yet) —
 * same pattern as features/analyze/statsApi.ts.
 */
async function scrapeImport(url: string, mode: ScrapeMode): Promise<ScrapeResult> {
  const base = await initApiBase();
  const res = await fetchWithTimeout(`${base}/scrape/import`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url, mode }),
  });
  if (!res.ok) {
    let detail: unknown;
    try {
      detail = (await res.json()).detail;
    } catch {
      // non-JSON error body
    }
    const suffix = typeof detail === "string" && detail ? `: ${detail}` : "";
    throw new ApiError(res.status, `API error ${res.status} on /scrape/import${suffix}`, detail);
  }
  return (await res.json()) as ScrapeResult;
}

interface Props {
  onClose: () => void;
}

export function UrlImportDialog({ onClose }: Props) {
  const { t } = useI18n();
  const toast = useToast();
  const [url, setUrl] = useState("");
  const [mode, setMode] = useState<ScrapeMode>("auto");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (busy) return;
    setError(null);
    setBusy(true);
    try {
      const result = await scrapeImport(url.trim(), mode);
      toast.success(t("files.urlImported", { name: result.name }));
      onClose();
      await useProjectStore.getState().refreshProject();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("files.urlImportError"));
      setBusy(false);
    }
  }

  return (
    <Modal
      open
      onClose={onClose}
      closeDisabled={busy}
      title={t("files.urlImport")}
      icon={<Globe size={15} aria-hidden />}
    >
      <form onSubmit={(ev) => void handleSubmit(ev)} className="space-y-3 p-3">
        <Field label={t("files.urlImportUrl")}>
          <Input
            type="url"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder={t("files.urlImportUrlPlaceholder")}
            className="w-full"
            autoFocus
          />
        </Field>
        <Field label={t("files.urlImportMode")}>
          <Select
            value={mode}
            onChange={(e) => setMode(e.target.value as ScrapeMode)}
            className="w-full"
          >
            {MODE_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {t(opt.labelKey)}
              </option>
            ))}
          </Select>
        </Field>
        <p className="text-xs text-text-secondary">{t("files.urlImportHint")}</p>
        {error && <ErrorBanner onClose={() => setError(null)}>{error}</ErrorBanner>}
        <div className="flex justify-end gap-2 pt-1">
          <Button variant="secondary" onClick={onClose} disabled={busy}>
            {t("common.cancel")}
          </Button>
          <Button
            variant="primary"
            type="submit"
            disabled={busy || !url.trim()}
            icon={
              busy ? (
                <LoaderCircle size={12} className="animate-spin" aria-hidden />
              ) : (
                <Globe size={12} aria-hidden />
              )
            }
          >
            {busy ? t("files.urlImporting") : t("files.urlImportButton")}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
