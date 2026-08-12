/**
 * TranscribeDialog — one panel for both AV tasks: configure and START a
 * background transcription, or detect and mark speakers in the transcript.
 * The job runs in the queue; progress is shown in the top bar (the dialog
 * closes immediately after starting).
 */
import { useEffect, useState, type FormEvent } from "react";
import { Captions, CircleAlert, LoaderCircle, Mic, Users } from "lucide-react";
import { api, type SpeakerInfo, type TranscribeStatus } from "@/lib/api";
import { Button, ErrorBanner, Field, Input, Modal, Select } from "@/components/ui/orchestrator";
import { useI18n } from "@/lib/i18n";
import { useProjectStore } from "@/stores/project";

const IDENTIFIER_OPTIONS = [
  { key: "name", labelKey: "avCoder.speakersName" },
  { key: "hash", labelKey: "avCoder.speakersHash" },
  { key: "at", labelKey: "avCoder.speakersAt" },
  { key: "bracket", labelKey: "avCoder.speakersBracket" },
  { key: "brace", labelKey: "avCoder.speakersBrace" },
  { key: "custom", labelKey: "avCoder.speakersCustom" },
] as const;

interface Props {
  sourceId: number;
  onClose: () => void;
}

export function TranscribeDialog({ sourceId, onClose }: Props) {
  const { t } = useI18n();
  const codeTree = useProjectStore((s) => s.codeTree);
  const codeOptions = codeTree.filter((c) => c.kind === "code");
  const source = useProjectStore((s) => s.sources.find((src) => src.id === sourceId));
  const transcriptId = source?.av_text_id ?? null;

  const [tab, setTab] = useState<"transcribe" | "speakers">("transcribe");

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

  // Speakers tab state.
  const [identifiers, setIdentifiers] = useState<string[]>(["name"]);
  const [customRegex, setCustomRegex] = useState("");
  const [speakers, setSpeakers] = useState<SpeakerInfo[]>([]);
  const [speakerTurns, setSpeakerTurns] = useState<{ name: string; pos0: number; pos1: number }[]>([]);
  const [speakerSelected, setSpeakerSelected] = useState<Record<string, boolean>>({});
  const [speakerBusy, setSpeakerBusy] = useState(false);
  const [speakerError, setSpeakerError] = useState<string | null>(null);
  const [speakerDone, setSpeakerDone] = useState<string | null>(null);

  const sourceName = source?.name ?? `source ${sourceId}`;

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

  async function detectSpeakers() {
    setSpeakerBusy(true);
    setSpeakerError(null);
    setSpeakerDone(null);
    try {
      const fid = transcriptId ?? sourceId;
      const res = await api.speakersDetect({ fid, identifiers, custom_regex: customRegex });
      setSpeakers(res.speakers);
      setSpeakerTurns(res.turns);
      setSpeakerSelected(Object.fromEntries(res.speakers.map((s) => [s.name, true])));
    } catch (e) {
      setSpeakerError(e instanceof Error ? e.message : "Failed to detect speakers");
    } finally {
      setSpeakerBusy(false);
    }
  }

  async function markSpeakers() {
    setSpeakerBusy(true);
    setSpeakerError(null);
    setSpeakerDone(null);
    try {
      const fid = transcriptId ?? sourceId;
      const selected = Object.entries(speakerSelected)
        .filter(([, v]) => v)
        .map(([name]) => name);
      const res = await api.speakersMark({ fid, identifiers, custom_regex: customRegex, selected });
      setSpeakers([]);
      setSpeakerTurns([]);
      await useProjectStore.getState().refreshProject();
      setSpeakerDone(
        t("avCoder.speakersDone", {
          turns: String(res.turns_marked),
          codes: String(res.codes_created),
        }),
      );
      setTab("transcribe");
    } catch (e) {
      setSpeakerError(e instanceof Error ? e.message : "Failed to mark speakers");
    } finally {
      setSpeakerBusy(false);
    }
  }

  const whisperAvailable = status?.engines.whisper ?? false;
  const noscribeAvailable = status?.engines.noscribe ?? false;

  return (
    <Modal
      open
      onClose={onClose}
      closeDisabled={busy || speakerBusy}
      title={t("transcribe.title")}
      icon={<Mic size={15} aria-hidden />}
      size="lg"
    >
      <div className="border-b border-border px-3 py-2">
        <div className="flex w-fit items-center gap-0.5 rounded-sm border border-border bg-bg p-0.5">
          <button
            type="button"
            onClick={() => setTab("transcribe")}
            aria-pressed={tab === "transcribe"}
            className={`flex items-center gap-1 rounded-sm px-2 py-1 text-xs font-medium ${
              tab === "transcribe"
                ? "bg-surface-higher text-accent"
                : "text-text-secondary hover:text-text-primary"
            }`}
          >
            <Mic size={12} aria-hidden />
            {t("transcribe.button")}
          </button>
          <button
            type="button"
            onClick={() => setTab("speakers")}
            aria-pressed={tab === "speakers"}
            className={`flex items-center gap-1 rounded-sm px-2 py-1 text-xs font-medium ${
              tab === "speakers"
                ? "bg-surface-higher text-accent"
                : "text-text-secondary hover:text-text-primary"
            }`}
          >
            <Users size={12} aria-hidden />
            {t("avCoder.markSpeakers")}
          </button>
        </div>
      </div>

      {tab === "transcribe" ? (
        <form onSubmit={(ev) => void handleStart(ev)} className="space-y-3 p-3">
          {!whisperAvailable && !noscribeAvailable && (
            <p className="flex items-center gap-1.5 text-xs text-danger">
              <CircleAlert size={13} aria-hidden />
              {t("transcribe.noEngine")}
            </p>
          )}

          <Field label={t("transcribe.engine")}>
            <Select value={engine} onChange={(e) => setEngine(e.target.value)} className="w-full">
              <option value="whisper" disabled={!whisperAvailable}>
                Whisper (faster-whisper)
              </option>
              <option value="noscribe" disabled={!noscribeAvailable}>
                noScribe
              </option>
            </Select>
          </Field>

          {engine === "whisper" && (
            <>
              <Field label={t("transcribe.model")}>
                <Select
                  value={model}
                  onChange={(e) => setModel(e.target.value)}
                  className="w-full"
                >
                  {(status?.models ?? []).map((m) => (
                    <option key={m} value={m}>
                      {m}
                      {status?.models_cached.includes(m) ? " ✓" : ""}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label={t("transcribe.language")}>
                <Input
                  type="text"
                  value={language}
                  onChange={(e) => setLanguage(e.target.value)}
                  placeholder={t("transcribe.languagePlaceholder")}
                  className="w-full"
                />
              </Field>
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
              <Field label={t("transcribe.beamSize")}>
                <Input
                  type="number"
                  min={1}
                  max={10}
                  value={beamSize}
                  onChange={(e) => setBeamSize(Number(e.target.value))}
                  className="w-full"
                />
              </Field>
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
                <Select
                  value={segmentCid}
                  onChange={(e) => setSegmentCid(e.target.value)}
                  aria-label={t("transcribe.segmentCode")}
                  className="w-full"
                >
                  <option value="">{t("coder.pickCode")}</option>
                  {codeOptions.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                    </option>
                  ))}
                </Select>
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
            <Button variant="secondary" onClick={onClose} disabled={busy}>
              {t("common.cancel")}
            </Button>
            <Button
              variant="primary"
              type="submit"
              disabled={busy || !whisperAvailable}
              icon={
                busy ? (
                  <LoaderCircle size={12} className="animate-spin" aria-hidden />
                ) : (
                  <Mic size={12} aria-hidden />
                )
              }
            >
              {t("transcribe.start")}
            </Button>
          </div>
        </form>
      ) : (
        <div className="space-y-3 p-3">
          {!transcriptId && (
            <p className="flex items-center gap-1.5 text-xs text-warning">
              <CircleAlert size={13} aria-hidden />
              {t("avCoder.speakersNoTranscript")}
            </p>
          )}

          <fieldset className="space-y-1">
            <legend className="text-xs font-medium text-text-secondary">
              {t("avCoder.speakersIdentifiers")}
            </legend>
            {IDENTIFIER_OPTIONS.map((opt) => (
              <label key={opt.key} className="flex items-center gap-2 text-sm text-text-primary">
                <input
                  type="checkbox"
                  checked={identifiers.includes(opt.key)}
                  onChange={(e) =>
                    setIdentifiers((prev) =>
                      e.target.checked
                        ? [...prev, opt.key]
                        : prev.filter((k) => k !== opt.key),
                    )
                  }
                  className="accent-accent"
                />
                {t(opt.labelKey)}
              </label>
            ))}
          </fieldset>
          {identifiers.includes("custom") && (
            <Input
              value={customRegex}
              onChange={(e) => setCustomRegex(e.target.value)}
              placeholder={t("avCoder.speakersCustomPlaceholder")}
              className="w-full"
            />
          )}

          <Button
            variant="secondary"
            onClick={() => void detectSpeakers()}
            disabled={speakerBusy || identifiers.length === 0}
            icon={
              speakerBusy ? (
                <LoaderCircle size={12} className="animate-spin" aria-hidden />
              ) : (
                <Users size={12} aria-hidden />
              )
            }
          >
            {t("avCoder.speakersDetect")}
          </Button>

          {speakerError && <p className="text-xs text-danger">{speakerError}</p>}
          {speakerDone && <ErrorBanner tone="success">{speakerDone}</ErrorBanner>}

          {speakers.length > 0 && (
            <div className="max-h-56 overflow-auto rounded-sm border border-border bg-bg">
              <table className="w-full border-collapse">
                <tbody>
                  {speakers.map((s) => (
                    <tr key={s.name} className="border-b border-border last:border-0">
                      <td className="px-2 py-1.5">
                        <input
                          type="checkbox"
                          checked={speakerSelected[s.name] ?? false}
                          onChange={(e) =>
                            setSpeakerSelected((prev) => ({
                              ...prev,
                              [s.name]: e.target.checked,
                            }))
                          }
                          className="accent-accent"
                          aria-label={s.name}
                        />
                      </td>
                      <td className="px-2 py-1.5 text-sm font-medium">{s.name}</td>
                      <td className="px-2 py-1.5 text-xs text-text-secondary">{s.count} turns</td>
                      <td className="max-w-40 truncate px-2 py-1.5 text-xs text-text-secondary" title={s.example}>
                        {s.example}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <div className="flex items-center justify-between pt-1">
            <span className="text-xs text-text-secondary">
              {speakerTurns.length > 0 ? `${speakerTurns.length} turn(s) detected` : ""}
            </span>
            <div className="flex items-center gap-2">
              <Button variant="secondary" onClick={onClose} disabled={speakerBusy}>
                {t("common.cancel")}
              </Button>
              <Button
                variant="primary"
                icon={<Captions size={12} aria-hidden />}
                onClick={() => void markSpeakers()}
                disabled={speakerBusy || speakers.length === 0}
              >
                {t("avCoder.speakersMark")}
              </Button>
            </div>
          </div>
        </div>
      )}
    </Modal>
  );
}
