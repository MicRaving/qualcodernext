/**
 * TranscribeDialog — configure and START a background transcription.
 * The job runs in the queue; progress is shown in the top bar (the dialog
 * closes immediately after starting).
 */
import { useEffect, useState, type FormEvent } from "react";
import { CircleAlert, LoaderCircle, Mic, X } from "lucide-react";
import { api, type TranscribeStatus } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { useProjectStore } from "@/stores/project";

const inputCls =
  "h-8 w-full rounded-sm border border-border bg-bg px-2 text-sm outline-none focus:border-accent";

interface Props {
  sourceId: number;
  onClose: () => void;
}

export function TranscribeDialog({ sourceId, onClose }: Props) {
  const { t } = useI18n();
  const codeTree = useProjectStore((s) => s.codeTree);
  const codeOptions = codeTree.filter((c) => c.kind === "code");

  const [status, setStatus] = useState<TranscribeStatus | null>(null);
  const [engine, setEngine] = useState("whisper");
  const [model, setModel] = useState("large-v3-turbo");
  const [language, setLanguage] = useState("");
  const [translate, setTranslate] = useState(false);
  const [beamSize, setBeamSize] = useState(5);
  const [vad, setVad] = useState(true);
  const [timestamps, setTimestamps] = useState(true);
  const [segmentCoding, setSegmentCoding] = useState(false);
  const [segmentCid, setSegmentCid] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const sourceName = useProjectStore((s) =>
    s.sources.find((src) => src.id === sourceId)?.name ?? `source ${sourceId}`,
  );

  useEffect(() => {
    api
      .transcribeStatus()
      .then((s) => {
        setStatus(s);
        setEngine(s.settings.engine);
        setModel(s.settings.model);
        setLanguage(s.settings.language ?? "");
        setTranslate(s.settings.translate);
        setBeamSize(s.settings.beam_size);
        setVad(s.settings.vad);
        setSegmentCoding(s.settings.segment_coding);
      })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : t("transcribe.loadError")));
  }, [t]);

  async function handleStart(e: FormEvent) {
    e.preventDefault();
    if (busy) return;
    setError(null);
    setBusy(true);
    try {
      const res = await api.transcribeStart({
        source_id: sourceId,
        engine,
        model,
        language: language.trim() || null,
        translate,
        beam_size: beamSize,
        vad,
        timestamps,
        segment_coding: segmentCoding,
        segment_cid: segmentCoding && segmentCid ? Number(segmentCid) : null,
      });
      // Background job: queue it, close the dialog, progress lives in the
      // top bar (the shell polls and refreshes on completion).
      useProjectStore.getState().enqueueTranscribe({
        id: res.job_id,
        sourceId,
        sourceName,
      });
      onClose();
    } catch (err) {
      setBusy(false);
      setError(err instanceof Error ? err.message : t("transcribe.startError"));
    }
  }

  const whisperAvailable = status?.engines.whisper ?? false;
  const noscribeAvailable = status?.engines.noscribe ?? false;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-bg/70"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget && !busy) onClose();
      }}
      role="dialog"
      aria-modal="true"
      aria-label={t("transcribe.title")}
    >
      <div className="w-[26rem] max-w-[92vw] rounded-lg border border-border bg-surface shadow-xl">
        <div className="flex items-center gap-2 border-b border-border px-3 py-2">
          <Mic size={15} aria-hidden />
          <span className="text-sm font-semibold text-text-primary">{t("transcribe.title")}</span>
          <div className="flex-1" />
          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            aria-label={t("common.close")}
            className="rounded-sm p-1 text-text-secondary hover:bg-surface-higher hover:text-text-primary disabled:opacity-40"
          >
            <X size={14} aria-hidden />
          </button>
        </div>

        <form onSubmit={(ev) => void handleStart(ev)} className="space-y-3 p-3">
          {!whisperAvailable && !noscribeAvailable && (
            <p className="flex items-center gap-1.5 text-xs text-danger">
              <CircleAlert size={13} aria-hidden />
              {t("transcribe.noEngine")}
            </p>
          )}

          <label className="block">
            <span className="mb-1 block text-xs text-text-secondary">{t("transcribe.engine")}</span>
            <select
              value={engine}
              onChange={(e) => setEngine(e.target.value)}
              className={inputCls}
            >
              <option value="whisper" disabled={!whisperAvailable}>
                Whisper (faster-whisper)
              </option>
              <option value="noscribe" disabled={!noscribeAvailable}>
                noScribe
              </option>
            </select>
          </label>

          {engine === "whisper" && (
            <>
              <label className="block">
                <span className="mb-1 block text-xs text-text-secondary">{t("transcribe.model")}</span>
                <select
                  value={model}
                  onChange={(e) => setModel(e.target.value)}
                  className={inputCls}
                >
                  {(status?.models ?? []).map((m) => (
                    <option key={m} value={m}>
                      {m}
                      {status?.models_cached.includes(m) ? " ✓" : ""}
                    </option>
                  ))}
                </select>
              </label>
              <label className="block">
                <span className="mb-1 block text-xs text-text-secondary">
                  {t("transcribe.language")}
                </span>
                <input
                  type="text"
                  value={language}
                  onChange={(e) => setLanguage(e.target.value)}
                  placeholder={t("transcribe.languagePlaceholder")}
                  className={inputCls}
                />
              </label>
              <label className="flex items-center gap-2 text-sm text-text-primary">
                <input
                  type="checkbox"
                  checked={translate}
                  onChange={(e) => setTranslate(e.target.checked)}
                  className="accent-accent"
                />
                {t("transcribe.translate")}
              </label>
              <label className="flex items-center gap-2 text-sm text-text-primary">
                <input
                  type="checkbox"
                  checked={vad}
                  onChange={(e) => setVad(e.target.checked)}
                  className="accent-accent"
                />
                {t("transcribe.vad")}
              </label>
              <label className="block">
                <span className="mb-1 block text-xs text-text-secondary">{t("transcribe.beamSize")}</span>
                <input
                  type="number"
                  min={1}
                  max={10}
                  value={beamSize}
                  onChange={(e) => setBeamSize(Number(e.target.value))}
                  className={inputCls}
                />
              </label>
              <label className="flex items-center gap-2 text-sm text-text-primary">
                <input
                  type="checkbox"
                  checked={timestamps}
                  onChange={(e) => setTimestamps(e.target.checked)}
                  className="accent-accent"
                />
                {t("transcribe.timestamps")}
              </label>
              <label className="flex items-center gap-2 text-sm text-text-primary">
                <input
                  type="checkbox"
                  checked={segmentCoding}
                  onChange={(e) => setSegmentCoding(e.target.checked)}
                  className="accent-accent"
                />
                {t("transcribe.segmentCoding")}
              </label>
              {segmentCoding && (
                <select
                  value={segmentCid}
                  onChange={(e) => setSegmentCid(e.target.value)}
                  aria-label={t("transcribe.segmentCode")}
                  className={inputCls}
                >
                  <option value="">{t("coder.pickCode")}</option>
                  {codeOptions.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                    </option>
                  ))}
                </select>
              )}
            </>
          )}

          {error && (
            <p className="flex items-start gap-1.5 text-xs text-danger">
              <CircleAlert size={13} className="mt-0.5 shrink-0" aria-hidden />
              <span>{error}</span>
            </p>
          )}

          <p className="flex items-center gap-1.5 text-xs text-text-secondary" role="status">
            <LoaderCircle size={13} className="animate-pulse" aria-hidden />
            {t("transcribe.backgroundHint")}
          </p>

          <div className="flex justify-end gap-2 pt-1">
            <button
              type="button"
              onClick={onClose}
              disabled={busy}
              className="rounded-sm border border-border bg-bg px-2.5 py-1 text-xs hover:bg-surface-higher disabled:opacity-40"
            >
              {t("common.cancel")}
            </button>
            <button
              type="submit"
              disabled={busy || !whisperAvailable}
              className="flex items-center gap-1 rounded-sm bg-accent px-2.5 py-1 text-xs font-medium text-[var(--qc-bg)] hover:bg-accent-hover disabled:opacity-40"
            >
              {busy ? (
                <LoaderCircle size={12} className="animate-spin" aria-hidden />
              ) : (
                <Mic size={12} aria-hidden />
              )}
              {t("transcribe.start")}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
