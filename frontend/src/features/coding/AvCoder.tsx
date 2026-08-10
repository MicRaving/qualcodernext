/**
 * AvCoder — audio/video playback with time-range coding on a timeline.
 *
 * Segment positions (pos0/pos1) are stored in milliseconds.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowLeft,
  Bookmark,
  Captions,
  ChevronDown,
  LoaderCircle,
  Mic,
  Music,
  Pause,
  Play,
  Trash2,
  Users,
  Video,
  X,
} from "lucide-react";
import { api, sourceFileUrl, type AVCoding, type CodeTreeItem, type Source, type SpeakerInfo } from "@/lib/api";
import { CodePicker, type PickedCode } from "@/features/coding/CodePicker";
import { TranscribeDialog } from "@/features/coding/TranscribeDialog";
import { formatTime, parseTranscript, segmentLeft, secondsToMs, segmentWidth } from "@/features/coding/media";
import { codeTint } from "@/features/coding/tint";
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

export function AvCoder({ source }: { source: Source }) {
  const { t } = useI18n();
  const setView = useProjectStore((s) => s.setView);
  const [transcribeOpen, setTranscribeOpen] = useState(false);
  const [transcribeMenuOpen, setTranscribeMenuOpen] = useState(false);
  const activeCodeId = useProjectStore((s) => s.activeCodeId);
  const mediaRef = useRef<HTMLVideoElement & HTMLAudioElement>(null);
  const timelineRef = useRef<HTMLDivElement>(null);

  const [codings, setCodings] = useState<AVCoding[]>([]);
  const [codes, setCodes] = useState<CodeTreeItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [durationMs, setDurationMs] = useState(0);
  const [currentMs, setCurrentMs] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [mediaError, setMediaError] = useState<string | null>(null);

  const [startMark, setStartMark] = useState<number | null>(null);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [pendingStart, setPendingStart] = useState<number | null>(null);
  const [selected, setSelected] = useState<AVCoding | null>(null);
  const [transcript, setTranscript] = useState<Source | null>(null);
  const [playbackRate, setPlaybackRate] = useState(1);
  const [videoVisible, setVideoVisible] = useState(true);

  useEffect(() => {
    if (!transcribeMenuOpen) return;
    const onDown = (e: MouseEvent) => {
      const target = e.target instanceof Node ? e.target : null;
      if (target && !(target as HTMLElement).closest("[data-transcribe-menu]")) {
        setTranscribeMenuOpen(false);
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setTranscribeMenuOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    window.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      window.removeEventListener("keydown", onKey);
    };
  }, [transcribeMenuOpen]);
  const [panelVisible, setPanelVisible] = useState(true);
  const [panelTab, setPanelTab] = useState<"transcript" | "speakers">("transcript");
  const subtitleRef = useRef<HTMLDivElement | null>(null);

  // Bookmark + speakers
  const [avBookmarkMs, setAvBookmarkMs] = useState<number | null>(null);
  const [avBookmarkFile, setAvBookmarkFile] = useState<number | null>(null);
  const [identifiers, setIdentifiers] = useState<string[]>(["name"]);
  const [customRegex, setCustomRegex] = useState("");
  const [speakers, setSpeakers] = useState<SpeakerInfo[]>([]);
  const [speakerTurns, setSpeakerTurns] = useState<{ name: string; pos0: number; pos1: number }[]>([]);
  const [speakerSelected, setSpeakerSelected] = useState<Record<string, boolean>>({});
  const [speakerBusy, setSpeakerBusy] = useState(false);
  const [speakerError, setSpeakerError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    void api
      .bookmarks()
      .then((b) => {
        if (!cancelled) {
          setAvBookmarkFile(b.av_bookmark_file_id);
          setAvBookmarkMs(b.av_bookmark_msec);
        }
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [source.id]);

  async function setAvBookmark() {
    try {
      const b = await api.setAvBookmark(source.id, Math.round(currentMs), null);
      setAvBookmarkFile(b.av_bookmark_file_id);
      setAvBookmarkMs(b.av_bookmark_msec);
    } catch {
      setError(t("coder.bookmarkSet"));
    }
  }

  async function goAvBookmark() {
    if (avBookmarkFile == null) return;
    if (avBookmarkFile === source.id && avBookmarkMs != null) {
      seekToMs(avBookmarkMs);
    } else {
      useProjectStore.getState().setView({ kind: "coding", sourceId: avBookmarkFile });
    }
  }

  async function detectSpeakers() {
    setSpeakerBusy(true);
    setSpeakerError(null);
    try {
      const fid = transcriptId ?? source.id;
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
    try {
      const fid = transcriptId ?? source.id;
      const selected = Object.entries(speakerSelected)
        .filter(([, v]) => v)
        .map(([name]) => name);
      const res = await api.speakersMark({ fid, identifiers, custom_regex: customRegex, selected });
      setSpeakers([]);
      setSpeakerTurns([]);
      setPanelTab("transcript");
      await load();
      await useProjectStore.getState().refreshProject();
      setError(
        t("avCoder.speakersDone", {
          turns: String(res.turns_marked),
          codes: String(res.codes_created),
        }),
      );
    } catch (e) {
      setSpeakerError(e instanceof Error ? e.message : "Failed to mark speakers");
    } finally {
      setSpeakerBusy(false);
    }
  }

  const subtitleSegments = useMemo(
    () => (transcript ? parseTranscript(transcript.fulltext ?? "") : []),
    [transcript],
  );

  const activeSubtitle = useMemo(() => {
    let active: { startMs: number; endMs: number; text: string } | null = null;
    for (const seg of subtitleSegments) {
      if (seg.startMs <= currentMs) active = seg;
      else break;
    }
    return active;
  }, [subtitleSegments, currentMs]);

  useEffect(() => {
    if (!activeSubtitle) return;
    subtitleRef.current
      ?.querySelector(`[data-start="${activeSubtitle.startMs}"]`)
      ?.scrollIntoView({ block: "nearest" });
  }, [activeSubtitle]);

  function setSpeed(rate: number) {
    setPlaybackRate(rate);
    const el = mediaRef.current;
    if (el) {
      el.preservesPitch = true;
      el.playbackRate = rate;
    }
  }

  const pendingStartRef = useRef<number | null>(null);

  useEffect(() => {
    pendingStartRef.current = pendingStart;
  }, [pendingStart]);

  const colorByCid = useMemo(() => {
    const map = new Map<number, string>();
    for (const c of codes) if (c.kind === "code" && c.color) map.set(c.id, c.color);
    return map;
  }, [codes]);

  const nameByCid = useMemo(() => {
    const map = new Map<number, string>();
    for (const c of codes) if (c.kind === "code") map.set(c.id, c.name);
    return map;
  }, [codes]);

  const codeColor = (coding: AVCoding) => colorByCid.get(coding.cid) ?? "rgba(0,0,0,0.15)";

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [cs, flat] = await Promise.all([api.avCodings(source.id), api.codesFlat()]);
      setCodings(cs);
      setCodes(flat);
    } catch (e) {
      setError(e instanceof Error ? e.message : t("coder.loadCodingsError"));
    } finally {
      setLoading(false);
    }
  }, [source.id, t]);

  // The transcript source id may appear AFTER a background transcription
  // finishes (the store's sources list refreshes then) — track it live.
  const liveSource = useProjectStore((s) => s.sources.find((x) => x.id === source.id));
  const transcriptId = source.av_text_id ?? liveSource?.av_text_id ?? null;

  const loadTranscript = useCallback(async () => {
    if (!transcriptId) {
      setTranscript(null);
      return;
    }
    try {
      setTranscript(await api.getSource(transcriptId));
    } catch {
      setTranscript(null);
    }
  }, [transcriptId]);

  // Background transcription queue: reload the transcript when a job for
  // THIS source finishes and open the transcript panel automatically.
  useEffect(() => {
    const unsub = useProjectStore.subscribe((s, prev) => {
      if (s.transcribeJobs !== prev.transcribeJobs) {
        const done = s.transcribeJobs.find(
          (j) => j.sourceId === source.id && j.state === "done",
        );
        if (done && prev.transcribeJobs.find((j) => j.id === done.id)?.state !== "done") {
          void loadTranscript();
          setPanelVisible(true);
          setPanelTab("transcript");
        }
      }
    });
    return unsub;
  }, [source.id, loadTranscript]);

  useEffect(() => {
    void load();
    void loadTranscript();
  }, [load, loadTranscript]);

  // --- media element wiring --------------------------------------------

  useEffect(() => {
    // The media element only exists after the loading spinner unmounts;
    // an effect with [] deps would run against the spinner render and never
    // attach listeners (regression: duration never surfaced). Re-run once
    // the element is mounted and re-attach after every reload.
    if (loading) return;
    const el = mediaRef.current;
    if (!el) return;

    const onLoaded = () => setDurationMs(secondsToMs(el.duration || 0));
    const onTime = () => setCurrentMs(secondsToMs(el.currentTime || 0));
    const onPlay = () => setPlaying(true);
    const onPause = () => setPlaying(false);
    const onEnded = () => setPlaying(false);
    const onError = () => setMediaError(t("avCoder.loadFileError"));

    el.addEventListener("loadedmetadata", onLoaded);
    el.addEventListener("timeupdate", onTime);
    el.addEventListener("play", onPlay);
    el.addEventListener("pause", onPause);
    el.addEventListener("ended", onEnded);
    el.addEventListener("error", onError);
    return () => {
      el.removeEventListener("loadedmetadata", onLoaded);
      el.removeEventListener("timeupdate", onTime);
      el.removeEventListener("play", onPlay);
      el.removeEventListener("pause", onPause);
      el.removeEventListener("ended", onEnded);
      el.removeEventListener("error", onError);
    };
  }, [loading, t]);

  function togglePlay() {
    const el = mediaRef.current;
    if (!el) return;
    if (el.paused) void el.play().catch(() => setMediaError(t("avCoder.playbackFailed")));
    else el.pause();
  }

  function seekToMs(ms: number) {
    const el = mediaRef.current;
    if (!el || !durationMs) return;
    const clamped = Math.max(0, Math.min(ms, durationMs));
    el.currentTime = clamped / 1000;
    // Round: the backend AV segment schema requires integer milliseconds,
    // and a pixel-click ratio yields fractional values.
    setCurrentMs(Math.round(clamped));
  }

  function handleTimelineClick(e: React.MouseEvent) {
    const el = timelineRef.current;
    if (!el || !durationMs) return;
    const rect = el.getBoundingClientRect();
    const ratio = (e.clientX - rect.left) / rect.width;
    seekToMs(ratio * durationMs);
  }

  // --- coding flow ------------------------------------------------------

  function handleSetStart() {
    setStartMark(currentMs);
    setSelected(null);
  }

  function handleSetEnd() {
    if (startMark === null) return;
    if (currentMs <= startMark) {
      setError(t("avCoder.endAfterStart"));
      return;
    }
    setPendingStart(startMark);
    setStartMark(null);
    if (activeCodeId != null) {
      void codeRange(activeCodeId, startMark, currentMs);
    } else {
      setPickerOpen(true);
    }
  }

  /** Code the pending [pos0, pos1) range with the given code id. */
  async function codeRange(cid: number, pos0: number, pos1: number) {
    setPickerOpen(false);
    setError(null);
    try {
      await api.createAvCoding({
        id: source.id,
        pos0,
        pos1,
        cid,
        owner: "default",
      });
      setPendingStart(null);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : t("coder.createError"));
    }
  }

  // Clicking a code in the left sidebar assigns it to the pending range.
  useEffect(() => {
    const onAssign = (e: Event) => {
      const cid = (e as CustomEvent<{ cid: number }>).detail?.cid;
      if (typeof cid !== "number") return;
      setPickerOpen(false);
      const start = pendingStartRef.current;
      if (start !== null) void codeRange(cid, start, currentMs);
    };
    window.addEventListener("qc:assign-code", onAssign);
    return () => window.removeEventListener("qc:assign-code", onAssign);
  });

  async function handlePick(code: PickedCode) {
    setPickerOpen(false);
    if (pendingStart === null) return;
    await codeRange(code.cid, pendingStart, currentMs);
  }

  async function handleDelete(coding: AVCoding) {
    if (
      !window.confirm(
        t("avCoder.deleteConfirm", {
          name: nameByCid.get(coding.cid) ?? t("coder.plainCode"),
        }),
      )
    )
      return;
    try {
      await api.deleteAvCoding(coding.avid);
      setSelected(null);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : t("coder.deleteSegmentError"));
    }
  }

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center bg-bg text-text-secondary">
        <LoaderCircle size={18} className="animate-spin" aria-hidden /> {t("avCoder.loading")}
      </div>
    );
  }

  if (error && codings.length === 0 && !mediaError) {
    return (
      <div className="flex h-full items-center justify-center bg-bg">
        <div className="text-center">
          <p className="text-danger">{error}</p>
          <button
            type="button"
            onClick={() => void load()}
            className="mt-3 rounded-sm border border-border bg-surface px-3 py-1.5 text-sm hover:bg-surface-higher"
          >
            {t("common.retry")}
          </button>
        </div>
      </div>
    );
  }

  const isVideo = source.media_type === "video";

  return (
    <div className="flex h-full flex-col bg-bg">
      {/* Header: back button + file name + all playback/coding controls */}
      <header className="flex min-h-10 shrink-0 flex-wrap items-center gap-1.5 border-b border-border bg-surface px-3 py-1">
        <button
          type="button"
          onClick={() => setView({ kind: "files" })}
          aria-label={t("coder.back")}
          title={t("coder.back")}
          className="rounded-sm p-1.5 text-text-secondary hover:bg-surface-higher hover:text-text-primary"
        >
          <ArrowLeft size={16} aria-hidden />
        </button>
        <span className="max-w-40 truncate font-medium">{source.name}</span>
        {source.memo && (
          <span className="hidden max-w-40 truncate text-xs text-text-secondary xl:inline">{source.memo}</span>
        )}
        <span className="mx-1 h-4 w-px shrink-0 bg-border" aria-hidden />
        <button
          type="button"
          onClick={togglePlay}
          aria-label={playing ? t("avCoder.pause") : t("avCoder.play")}
          className="flex h-7 w-7 shrink-0 items-center justify-center rounded-sm bg-accent text-[var(--qc-bg)] hover:bg-accent-hover"
        >
          {playing ? <Pause size={14} aria-hidden /> : <Play size={14} aria-hidden />}
        </button>
        <span className="shrink-0 font-mono text-xs text-text-primary">{formatTime(currentMs)}</span>
        <span className="shrink-0 text-xs text-text-secondary">/ {formatTime(durationMs)}</span>
        <select
          value={playbackRate}
          onChange={(e) => setSpeed(Number(e.target.value))}
          aria-label={t("avCoder.speed")}
          title={t("avCoder.speedTitle")}
          className="h-7 shrink-0 rounded-sm border border-border bg-bg px-1 text-xs outline-none focus:border-accent"
        >
          {[0.5, 0.75, 1, 1.25, 1.5, 2].map((r) => (
            <option key={r} value={r}>
              {r}×
            </option>
          ))}
        </select>
        {source.media_type === "video" && (
          <button
            type="button"
            onClick={() => setVideoVisible((v) => !v)}
            className={`flex shrink-0 items-center gap-1 rounded-sm border border-border px-2 py-1 text-xs hover:bg-surface-higher ${
              videoVisible ? "border-accent text-accent" : "bg-bg text-text-secondary"
            }`}
          >
            <Video size={12} aria-hidden />
            {t("avCoder.video")}
          </button>
        )}
        <button
          type="button"
          onClick={() => {
            if (!panelVisible) {
              setPanelVisible(true);
              setPanelTab("transcript");
            } else if (panelTab !== "transcript") {
              setPanelTab("transcript");
            } else {
              setPanelVisible(false);
            }
          }}
          disabled={subtitleSegments.length === 0}
          className={`flex shrink-0 items-center gap-1 rounded-sm border border-border px-2 py-1 text-xs hover:bg-surface-higher disabled:opacity-40 ${
            panelVisible && panelTab === "transcript" ? "border-accent text-accent" : "bg-bg text-text-secondary"
          }`}
        >
          <Captions size={12} aria-hidden />
          {t("avCoder.transcript")}
        </button>
        <div className="flex-1" />
        <button
          type="button"
          onClick={() => void setAvBookmark()}
          title={t("avCoder.bookmarkSet")}
          className={`flex shrink-0 items-center gap-1 rounded-sm border border-border px-2 py-1 text-xs hover:bg-surface-higher ${
            avBookmarkFile === source.id ? "border-accent text-accent" : "bg-bg text-text-secondary"
          }`}
        >
          <Bookmark size={12} aria-hidden />
          {t("avCoder.bookmarkSet")}
        </button>
        <button
          type="button"
          onClick={() => void goAvBookmark()}
          disabled={avBookmarkFile == null}
          title={t("avCoder.bookmarkGo")}
          className="flex shrink-0 items-center gap-1 rounded-sm border border-border bg-bg px-2 py-1 text-xs hover:bg-surface-higher disabled:opacity-40"
        >
          <Bookmark size={12} className="fill-current" aria-hidden />
          {t("avCoder.bookmarkGo")}
        </button>
        <div className="relative shrink-0" data-transcribe-menu>
          <button
            type="button"
            onClick={() => setTranscribeMenuOpen((o) => !o)}
            aria-expanded={transcribeMenuOpen}
            title={t("transcribe.title")}
            className="flex items-center gap-1 rounded-sm border border-border bg-bg px-2 py-1 text-xs hover:bg-surface-higher"
          >
            <Mic size={12} aria-hidden />
            {t("transcribe.button")}
            <ChevronDown size={11} className="text-text-secondary" aria-hidden />
          </button>
          {transcribeMenuOpen && (
            <div className="absolute right-0 top-full z-50 mt-1 min-w-44 rounded-md border border-border bg-surface py-1 shadow-lg">
              <button
                type="button"
                onClick={() => {
                  setTranscribeMenuOpen(false);
                  setTranscribeOpen(true);
                }}
                className="flex w-full items-center gap-2 px-2 py-1.5 text-left text-sm hover:bg-surface-higher"
              >
                <Mic size={13} aria-hidden />
                {t("transcribe.button")}…
              </button>
              <button
                type="button"
                onClick={() => {
                  setTranscribeMenuOpen(false);
                  setPanelVisible(true);
                  setPanelTab("speakers");
                }}
                className="flex w-full items-center gap-2 px-2 py-1.5 text-left text-sm hover:bg-surface-higher"
              >
                <Users size={13} aria-hidden />
                {t("avCoder.markSpeakers")}
              </button>
            </div>
          )}
        </div>
        <button
          type="button"
          onClick={startMark !== null ? handleSetEnd : handleSetStart}
          disabled={!durationMs}
          className={`shrink-0 rounded-sm px-2 py-1 text-xs hover:bg-surface-higher disabled:opacity-50 ${
            startMark !== null
              ? "bg-accent font-medium text-[var(--qc-bg)] hover:bg-accent-hover"
              : "border border-border bg-bg"
          }`}
        >
          {startMark !== null ? t("avCoder.setEndAndCode") : t("avCoder.setStart")}
        </button>
        {startMark !== null && (
          <span className="flex shrink-0 items-center gap-1 text-xs text-accent">
            {t("avCoder.start", { time: formatTime(startMark) })}
            <button
              type="button"
              onClick={() => setStartMark(null)}
              aria-label={t("avCoder.clearStart")}
              className="rounded-sm p-0.5 text-text-secondary hover:text-text-primary"
            >
              <X size={12} aria-hidden />
            </button>
          </span>
        )}
      </header>

      {/* Media */}
      <div className="shrink-0 border-b border-border bg-surface">
        {isVideo ? (
          <video
            ref={mediaRef}
            src={sourceFileUrl(source.id)}
            preload="metadata"
            aria-label={source.name}
            className={`block max-h-[55vh] w-full bg-bg ${videoVisible ? "" : "hidden"}`}
          />
        ) : (
          <div className="flex items-center gap-3 px-4 py-6">
            <Music size={28} className="text-text-secondary" aria-hidden />
            <div className="min-w-0">
              <div className="truncate text-sm font-medium text-text-primary">{source.name}</div>
              <div className="text-xs text-text-secondary">{t("avCoder.audioFile")} · {durationMs ? formatTime(durationMs) : "…"}</div>
            </div>
          </div>
        )}
        {/* hidden audio element must exist in the DOM to play */}
        {!isVideo && <audio ref={mediaRef} src={sourceFileUrl(source.id)} preload="metadata" className="hidden" />}
      </div>

      {mediaError && (
        <div role="alert" className="border-b border-border bg-danger/10 px-3 py-1.5 text-xs text-danger">
          {mediaError}
        </div>
      )}
      {error && (
        <div role="alert" className="border-b border-border bg-danger/10 px-3 py-1.5 text-xs text-danger">
          {error}
        </div>
      )}

      {/* Timeline */}
      <div className="shrink-0 border-b border-border bg-surface px-3 py-2">
        <div
          ref={timelineRef}
          onClick={handleTimelineClick}
          className="relative h-8 cursor-pointer overflow-hidden rounded-sm border border-border bg-bg"
          role="slider"
          aria-label={t("avCoder.timeline")}
          aria-valuemin={0}
          aria-valuemax={Math.round(durationMs)}
          aria-valuenow={Math.round(currentMs)}
        >
          {codings.map((coding) => (
            <div
              key={coding.avid}
              onClick={(e) => {
                e.stopPropagation();
                seekToMs(coding.pos0);
                setSelected(coding);
              }}
              title={`${nameByCid.get(coding.cid) ?? t("coder.plainCode")} · ${formatTime(coding.pos0)} – ${formatTime(coding.pos1)}`}
              className="absolute top-0 h-full cursor-pointer border"
              style={{
                left: `${segmentLeft(coding.pos0, durationMs)}%`,
                width: `${segmentWidth(coding.pos0, coding.pos1, durationMs)}%`,
                backgroundColor: codeTint(codeColor(coding)),
                borderColor: codeColor(coding),
              }}
            />
          ))}
          {durationMs > 0 && (
            <div
              className="pointer-events-none absolute top-0 h-full w-px bg-text-primary"
              style={{ left: `${(currentMs / durationMs) * 100}%` }}
              aria-hidden
            />
          )}
        </div>
        <div className="mt-1 flex justify-between text-[10px] text-text-secondary">
          <span>0:00</span>
          <span>{durationMs ? formatTime(durationMs) : ""}</span>
        </div>
      </div>

      {/* Details panel */}
      {selected && (
        <div className="flex shrink-0 items-center gap-3 border-b border-border bg-surface px-3 py-2">
          <span
            className="h-3 w-3 shrink-0 rounded-sm border border-border"
            style={{ backgroundColor: codeColor(selected) }}
            aria-hidden
          />
          <span className="truncate text-sm font-medium text-text-primary">
            {nameByCid.get(selected.cid) ?? t("coder.fallbackCodePlain", { id: selected.cid })}
          </span>
          <span className="font-mono text-xs text-text-secondary">
            {formatTime(selected.pos0)} – {formatTime(selected.pos1)}
          </span>
          <span className="truncate text-xs text-text-secondary">{selected.memo || t("common.noMemo")}</span>
          <div className="flex-1" />
          <button
            type="button"
            onClick={() => void handleDelete(selected)}
            className="flex items-center gap-1 rounded-sm border border-danger/50 px-2 py-1 text-xs text-danger hover:bg-danger/10"
          >
            <Trash2 size={12} aria-hidden />
            {t("common.delete")}
          </button>
          <button
            type="button"
            onClick={() => setSelected(null)}
            className="rounded-sm border border-border bg-bg px-2 py-1 text-xs hover:bg-surface-higher"
          >
            {t("common.close")}
          </button>
        </div>
      )}

      {/* Combined transcript + speakers panel */}
      {panelVisible && (panelTab === "speakers" || transcript != null) && (
        <div className="flex min-h-0 flex-1 flex-col border-t border-border bg-bg">
          <div className="flex shrink-0 items-center gap-1 border-b border-border bg-surface px-3 py-1.5">
            <button
              type="button"
              onClick={() => setPanelTab("transcript")}
              disabled={subtitleSegments.length === 0}
              className={`flex items-center gap-1 rounded-sm px-2 py-0.5 text-xs font-medium ${
                panelTab === "transcript"
                  ? "bg-surface-higher text-accent"
                  : "text-text-secondary hover:text-text-primary"
              } disabled:opacity-40`}
            >
              <Captions size={12} aria-hidden />
              {t("avCoder.transcript")}
            </button>
            <button
              type="button"
              onClick={() => setPanelTab("speakers")}
              className={`flex items-center gap-1 rounded-sm px-2 py-0.5 text-xs font-medium ${
                panelTab === "speakers"
                  ? "bg-surface-higher text-accent"
                  : "text-text-secondary hover:text-text-primary"
              }`}
            >
              <Users size={12} aria-hidden />
              {t("avCoder.markSpeakers")}
            </button>
            <span className="ml-2 truncate text-xs text-text-secondary">{transcript?.name}</span>
            <div className="flex-1" />
            <button
              type="button"
              onClick={() => setPanelVisible(false)}
              aria-label={t("common.close")}
              title={t("common.close")}
              className="rounded-sm p-0.5 text-text-secondary hover:bg-surface-higher hover:text-text-primary"
            >
              <X size={14} aria-hidden />
            </button>
          </div>

          {panelTab === "transcript" ? (
            <div
              ref={subtitleRef}
              className="min-h-0 flex-1 overflow-y-auto px-4 py-3"
              role="log"
              aria-live="off"
            >
              {subtitleSegments.length === 0 ? (
                <p className="py-6 text-center text-sm text-text-secondary">
                  {t("avCoder.noTranscript")}
                </p>
              ) : (
                subtitleSegments.map((seg, i) => {
                  const active = activeSubtitle === seg;
                  return (
                    <p
                      key={`${seg.startMs}-${i}`}
                      data-start={seg.startMs}
                      className={`rounded-sm px-1.5 py-0.5 text-sm leading-6 ${
                        active
                          ? "bg-accent/15 font-medium text-text-primary"
                          : "text-text-secondary"
                      }`}
                    >
                      <span className="mr-2 font-mono text-[10px] text-text-secondary">
                        {formatTime(seg.startMs)}
                      </span>
                      {seg.text}
                    </p>
                  );
                })
              )}
            </div>
          ) : (
            <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3">
              <fieldset className="space-y-1">
                <legend className="mb-1 text-xs font-medium text-text-secondary">
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
                <input
                  value={customRegex}
                  onChange={(e) => setCustomRegex(e.target.value)}
                  placeholder={t("avCoder.speakersCustomPlaceholder")}
                  className="mt-2 h-8 w-full rounded-sm border border-border bg-bg px-2 text-sm outline-none focus:border-accent"
                />
              )}
              <div className="mt-3 flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => void detectSpeakers()}
                  disabled={speakerBusy || identifiers.length === 0}
                  className="rounded-sm border border-border bg-bg px-2.5 py-1 text-xs hover:bg-surface-higher disabled:opacity-50"
                >
                  {speakerBusy ? (
                    <LoaderCircle size={12} className="animate-spin" aria-hidden />
                  ) : (
                    <Users size={12} aria-hidden />
                  )}
                  {t("avCoder.speakersDetect")}
                </button>
              </div>
              {speakerError && <p className="mt-2 text-xs text-danger">{speakerError}</p>}
              {speakers.length > 0 && (
                <div className="mt-3 max-h-56 overflow-auto rounded-sm border border-border bg-bg">
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
              <div className="mt-3 flex items-center justify-between">
                <span className="text-xs text-text-secondary">
                  {speakerTurns.length > 0 ? `${speakerTurns.length} turn(s) detected` : ""}
                </span>
                <button
                  type="button"
                  onClick={() => void markSpeakers()}
                  disabled={speakerBusy || speakers.length === 0}
                  className="rounded-sm bg-accent px-3 py-1 text-xs font-medium text-[var(--qc-bg)] hover:bg-accent-hover disabled:opacity-50"
                >
                  {t("avCoder.speakersMark")}
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Hint */}
      {codings.length === 0 && !selected && (
        <div className="flex flex-1 items-center justify-center bg-bg text-sm text-text-secondary">
          {t("avCoder.hint")}
        </div>
      )}

      <CodePicker
        open={pickerOpen}
        codes={codes}
        onClose={() => {
          setPickerOpen(false);
          setPendingStart(null);
        }}
        onPick={(code) => void handlePick(code)}
      />

      {transcribeOpen && (
        <TranscribeDialog sourceId={source.id} onClose={() => setTranscribeOpen(false)} />
      )}
    </div>
  );
}
