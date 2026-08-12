/**
 * AutocodeDialog — the shared autocode dialog used by the text, PDF and
 * AV/transcript coders (identical everywhere).
 *
 * Code one or MULTIPLE selected codes from the project via a natural-language
 * CODING PROMPT (prefilled from the selection) that the AI applies to the
 * document; optionally let the AI suggest NEW codes for content that fits no
 * existing code. Without an AI assistant the selected code names are matched
 * literally as a fallback.
 */
import { useEffect, useRef, useState } from "react";
import { CheckCircle2, LoaderCircle, Sparkles } from "lucide-react";
import { api, type AutocodeResponse, type CodeTreeItem } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import {
  Button,
  Field,
  Modal,
  Textarea,
} from "@/components/ui/orchestrator";
import { errorDetail } from "@/features/ai/format";
import { useProjectStore } from "@/stores/project";

export interface AutocodeResult {
  count: number;
  suggested: { cid: number; name: string; reason: string }[];
}

export function AutocodeDialog({
  open,
  onClose,
  fid,
  codes,
  onDone,
  sourceIds,
}: {
  open: boolean;
  onClose: () => void;
  /** Source id to code (transcript sources for AV coders). */
  fid: number | null;
  codes: CodeTreeItem[];
  onDone: (result: AutocodeResult) => void;
  /** Batch mode: queue a background autocode job per source (overrides fid). */
  sourceIds?: number[];
}) {
  const { t } = useI18n();
  const batchMode = sourceIds != null && sourceIds.length > 0;
  const [prompt, setPrompt] = useState("");
  const promptTouched = useRef(false);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [suggest, setSuggest] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<AutocodeResult | null>(null);
  const [queued, setQueued] = useState(false);

  useEffect(() => {
    if (open) {
      setPrompt("");
      promptTouched.current = false;
      setSelected(new Set());
      setSuggest(false);
      setError(null);
      setResult(null);
      setQueued(false);
    }
  }, [open]);

  const codeOptions = codes.filter((c) => c.kind === "code");
  const selectedNames = codeOptions
    .filter((c) => selected.has(c.id))
    .map((c) => c.name);
  const selectedNamesKey = selectedNames.join("|");

  // Prefill the coding prompt from the selection (until the user edits it).
  useEffect(() => {
    if (promptTouched.current) return;
    setPrompt(
      t("coder.autoPrompt", {
        names: selectedNamesKey || t("coder.autoNoCodes"),
      }),
    );
  }, [selectedNamesKey, t]);

  function toggleCode(cid: number) {
    setSelected((s) => {
      const next = new Set(s);
      if (next.has(cid)) next.delete(cid);
      else next.add(cid);
      return next;
    });
  }

  function toggleAll() {
    setSelected(
      selected.size === codeOptions.length
        ? new Set()
        : new Set(codeOptions.map((c) => c.id)),
    );
  }

  async function run() {
    const text = prompt.trim();
    if (!text) {
      setError(t("coder.autoNoText"));
      return;
    }
    if (selected.size === 0) {
      setError(t("coder.autoNoCode"));
      return;
    }
    setBusy(true);
    setError(null);
    try {
      if (batchMode) {
        const res = await api.autocodeBatch({
          source_ids: sourceIds,
          cids: [...selected],
          prompt: text,
          suggest,
        });
        const names = new Map(
          useProjectStore.getState().sources.map((s) => [s.id, s.name] as const),
        );
        res.job_ids.forEach((jobId, i) => {
          const sid = sourceIds[i];
          useProjectStore.getState().enqueueAutocode({
            id: jobId,
            sourceId: sid,
            sourceName: names.get(sid) ?? `source ${sid}`,
          });
        });
        setQueued(true);
        window.setTimeout(() => onClose(), 1200);
        return;
      }
      const res: AutocodeResponse = await api.autocode({
        fid,
        cids: [...selected],
        find_texts: [],
        mode: "all",
        use_regex: false,
        prompt: text,
        suggest,
      });
      setResult({ count: res.count, suggested: res.suggested ?? [] });
      onDone({ count: res.count, suggested: res.suggested ?? [] });
      // Close right away: the overlay would otherwise block the app, and the
      // coded result is visible in the document.
      window.setTimeout(() => onClose(), 1200);
    } catch (e) {
      setError(errorDetail(e, t("coder.autoError")));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      size="md"
      title={t("coder.autocode")}
      ariaLabel={t("coder.autocode")}
    >
      <div className="p-3">
        <Field label={t("coder.autoPromptLabel")}>
          <Textarea
            value={prompt}
            onChange={(e) => {
              promptTouched.current = true;
              setPrompt(e.target.value);
            }}
            placeholder={t("coder.autoPromptPlaceholder")}
            aria-label={t("coder.autoPromptLabel")}
            className="h-16 w-full resize-none px-2 py-1"
          />
        </Field>

        <div className="mt-2">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-text-secondary">
              {t("coder.autoCodes", { n: selected.size })}
            </span>
            <button
              type="button"
              onClick={toggleAll}
              className="text-xs text-accent hover:underline"
            >
              {selected.size === codeOptions.length && codeOptions.length > 0
                ? t("coder.autoClear")
                : t("coder.autoSelectAll")}
            </button>
          </div>
          <div className="qc-scroll mt-1 max-h-40 overflow-y-auto rounded-sm border border-border bg-bg p-1">
            {codeOptions.length === 0 ? (
              <p className="px-2 py-3 text-center text-xs text-text-secondary">
                {t("coder.autoNoCodes")}
              </p>
            ) : (
              codeOptions.map((c) => (
                <label
                  key={c.id}
                  className="flex cursor-pointer items-center gap-2 rounded-sm px-1.5 py-1 text-sm hover:bg-surface-higher"
                >
                  <input
                    type="checkbox"
                    checked={selected.has(c.id)}
                    onChange={() => toggleCode(c.id)}
                    className="accent-accent"
                  />
                  <span
                    className="h-2.5 w-2.5 shrink-0 rounded-sm border border-border"
                    style={{ backgroundColor: c.color ?? "var(--qc-accent)" }}
                    aria-hidden
                  />
                  <span className="truncate">{c.name}</span>
                </label>
              ))
            )}
          </div>
        </div>

        <label
          className="mt-2 flex h-7 items-center gap-1.5 text-xs text-text-secondary"
          title={t("coder.autoSuggestHint")}
        >
          <input
            type="checkbox"
            checked={suggest}
            onChange={(e) => setSuggest(e.target.checked)}
            className="accent-accent"
          />
          <Sparkles size={12} aria-hidden />
          {t("coder.autoSuggest")}
        </label>

        {error && <p className="mt-2 text-xs text-danger">{error}</p>}

        {result && (
          <p className="mt-2 flex items-start gap-1.5 text-xs text-success">
            <CheckCircle2 size={13} className="mt-0.5 shrink-0" aria-hidden />
            <span>
              {t("coder.autocoded", { count: result.count })}
              {result.suggested.length > 0 &&
                ` · ${t("coder.autoSuggested", {
                  names: result.suggested.map((s) => s.name).join(", "),
                })}`}
            </span>
          </p>
        )}

        {queued && (
          <p className="mt-2 flex items-center gap-1.5 text-xs text-text-secondary">
            <LoaderCircle size={13} className="animate-pulse" aria-hidden />
            {t("tasks.autocodeQueueHint")}
          </p>
        )}

        <div className="mt-3 flex items-center justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>
            {t("common.close")}
          </Button>
          <Button
            variant="primary"
            icon={
              busy ? (
                <LoaderCircle size={12} className="animate-spin" aria-hidden />
              ) : (
                <Sparkles size={12} aria-hidden />
              )
            }
            onClick={() => void run()}
            disabled={busy || !prompt.trim()}
          >
            {t("coder.autocode")}
          </Button>
        </div>
      </div>
    </Modal>
  );
}
