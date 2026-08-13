/**
 * AvCoder — audio/video playback with time-range coding on a timeline.
 *
 * Segment positions (pos0/pos1) are stored in milliseconds.
 */
import { Fragment, useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  Bookmark,
  BookmarkCheck,
  Captions,
  Check,
  Clock,
  Code,
  FilePen,
  Link as LinkIcon,
  LoaderCircle,
  Mic,
  Music,
  Pause,
  Play,
  Save,
  Sparkles,
  StickyNote,
  Trash2,
  Video,
  X,
} from "lucide-react";
import { api, sourceFileUrl, type AVCoding, type CodeTreeItem, type Coding, type Source } from "@/lib/api";
import { CodePicker, type PickedCode } from "@/features/coding/CodePicker";
import { AutocodeDialog } from "@/features/coding/AutocodeDialog";
import { TranscribeDialog } from "@/features/coding/TranscribeDialog";
import { formatTime, insertTimestampAtCaret, parseTranscript, segmentLeft, secondsToMs, segmentWidth, buildCrAt, rawToRendered, renderedToRaw, stripCr, normalizeCodingPositions } from "@/features/coding/media";
import { getSelectionOffsets } from "@/features/coding/selection";
import { codeTint } from "@/features/coding/tint";
import {
  copyLinkPayload,
  createLink,
  readLinkPayload,
  type LinkSpanTarget,
} from "@/features/coding/links";
import { canTranscribeSource } from "@/lib/media";
import { cn } from "@/lib/utils";
import { useI18n } from "@/lib/i18n";
import {
  Button,
  ErrorBanner,
  IconButton,
  LoadingState,
  Select,
  Textarea,
  ViewHeader,
} from "@/components/ui/orchestrator";
import { useProjectStore } from "@/stores/project";
import { cls } from "@/components/ui/tokens";

/** "[mm:ss]" (or "[hh:mm:ss]") timestamp, matching the stored transcript
 *  text so selection offsets stay aligned. */
function transcriptTimestamp(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  if (h > 0) {
    return `[${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}]`;
  }
  return `[${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}]`;
}

export function AvCoder({ source }: { source: Source }) {
  const { t } = useI18n();
  const storeCodeTree = useProjectStore((s) => s.codeTree);
  const [transcribeOpen, setTranscribeOpen] = useState(false);
  const activeCodeId = useProjectStore((s) => s.activeCodeId);
  const hiddenCodes = useProjectStore((s) => s.hiddenCodes);
  const mediaRef = useRef<HTMLVideoElement & HTMLAudioElement>(null);
  const timelineRef = useRef<HTMLDivElement>(null);

  const [codings, setCodings] = useState<AVCoding[]>([]);
  const [codes, setCodes] = useState<CodeTreeItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [durationMs, setDurationMs] = useState(0);
  const [currentMs, setCurrentMs] = useState(0);
  const currentMsRef = useRef(0);
  const seekTargetRef = useRef<number | null>(null);
  const seekAtRef = useRef(0);
  const [playing, setPlaying] = useState(false);
  const [mediaError, setMediaError] = useState<string | null>(null);

  const [startMark, setStartMark] = useState<number | null>(null);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [pendingStart, setPendingStart] = useState<number | null>(null);
  const [selected, setSelected] = useState<AVCoding | null>(null);
  const [transcript, setTranscript] = useState<Source | null>(null);
  const [playbackRate, setPlaybackRate] = useState(1);
  const [videoVisible, setVideoVisible] = useState(true);
  const [videoH, setVideoH] = useState(260);
  const [videoDragging, setVideoDragging] = useState(false);
  const videoResizeRef = useRef<{ startY: number; startH: number } | null>(null);

  function startVideoResize(e: React.MouseEvent) {
    e.preventDefault();
    videoResizeRef.current = { startY: e.clientY, startH: videoH };
    setVideoDragging(true);
  }

  useEffect(() => {
    if (!videoDragging) return;
    const onMove = (e: MouseEvent) => {
      const drag = videoResizeRef.current;
      if (!drag) return;
      setVideoH(Math.min(560, Math.max(100, Math.round(drag.startH + (e.clientY - drag.startY)))));
    };
    const onUp = () => {
      videoResizeRef.current = null;
      setVideoDragging(false);
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, [videoDragging]);

  // Lower-half panel: the transcript with text-coder functions
  const [transcriptVisible, setTranscriptVisible] = useState(true);
  const [tError, setTError] = useState<string | null>(null);

  // Manual transcription mode: the transcript becomes an editable draft the
  // user types while controlling playback with Space/F9/media keys.
  const [transcribeMode, setTranscribeMode] = useState(false);
  const [transcribeDraft, setTranscribeDraft] = useState("");
  const [transcribeSaving, setTranscribeSaving] = useState(false);
  const transcribeAreaRef = useRef<HTMLTextAreaElement | null>(null);

  // Bookmark
  const [avBookmarkMs, setAvBookmarkMs] = useState<number | null>(null);
  const [avBookmarkFile, setAvBookmarkFile] = useState<number | null>(null);

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

  // Live transcript preview: while a job for this source runs, poll it and
  // show the partial "[mm:ss] text" output as it is transcribed.
  const [liveTranscript, setLiveTranscript] = useState<string | null>(null);
  const runningJobId = useProjectStore((s) =>
    s.tasks.find(
      (j) => j.kind === "transcribe" && j.sourceId === source.id && j.state === "running",
    )?.id,
  );
  useEffect(() => {
    if (!runningJobId) {
      setLiveTranscript(null);
      return;
    }
    let cancelled = false;
    const poll = async () => {
      try {
        const j = await api.transcribeJob(runningJobId);
        if (!cancelled && j.state === "running" && j.live_text) {
          setLiveTranscript(j.live_text);
        } else if (!cancelled && j.state !== "running") {
          setLiveTranscript(null);
        }
      } catch {
        /* transient — the next poll retries */
      }
    };
    void poll();
    const timer = setInterval(() => void poll(), 3000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [runningJobId]);

  /** The exact "[mm:ss] text" lines as stored, BUT with CR characters
   *  removed: legacy projects store transcripts with CRLF line endings
   *  while the panel renders "\n"-only lines, so the rendered text and
   *  the stored text would otherwise disagree by one character per line.
   *  Stored positions stay in RAW space (crAt converts both ways). */
  const transcriptRaw = liveTranscript ?? transcript?.fulltext ?? "";
  const crAt = useMemo(() => buildCrAt(transcriptRaw), [transcriptRaw]);
  const transcriptText = useMemo(() => stripCr(transcriptRaw), [transcriptRaw]);

  const subtitleSegments = useMemo(
    () => parseTranscript(transcriptText),
    [transcriptText],
  );

  // --- transcript selection coding (text-coder functions in the view) ---
  const transcriptTextRef = useRef<HTMLDivElement | null>(null);
  const [tSel, setTSel] = useState<{ start: number; end: number; left: number; top: number } | null>(null);
  const [tAnnotateOpen, setTAnnotateOpen] = useState(false);
  const [tAnnotateMemo, setTAnnotateMemo] = useState("");
  const [tPickerOpen, setTPickerOpen] = useState(false);
  const tSelRef = useRef(tSel);
  tSelRef.current = tSel;
  /** Which coding gesture the user last performed: a transcript text
   *  selection or a timeline range mark. Only the LAST intent may react to
   *  a sidebar code click, so one click never creates two codings. */
  const codingIntentRef = useRef<"text" | "range" | null>(null);

  // Segment-link clipboard for the transcript (text spans in stored/raw
  // space, matching the positions TextCoder uses for the transcript file).
  const [clipboardLink, setClipboardLink] = useState<LinkSpanTarget | null>(null);
  const [linkCopied, setLinkCopied] = useState(false);
  const linkCopiedTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    let cancelled = false;
    void readLinkPayload().then((target) => {
      if (!cancelled) setClipboardLink(target);
    });
    return () => {
      cancelled = true;
    };
  }, [tSel]);

  async function copyTranscriptLink() {
    const sel = tSelRef.current;
    if (!sel || transcriptId == null) return;
    try {
      const pos0 = renderedToRaw(transcriptRaw, crAt, sel.start);
      const pos1 = renderedToRaw(transcriptRaw, crAt, sel.end);
      await copyLinkPayload(transcriptId, pos0, pos1);
      setClipboardLink({ fid: transcriptId, pos0, pos1 });
      setLinkCopied(true);
      if (linkCopiedTimer.current) clearTimeout(linkCopiedTimer.current);
      linkCopiedTimer.current = setTimeout(() => setLinkCopied(false), 1500);
    } catch (e) {
      setTError(e instanceof Error ? e.message : t("coder.linkCopyError"));
    }
  }

  /** One link from the current transcript selection to the copied segment. */
  async function pasteTranscriptLink() {
    const sel = tSelRef.current;
    const target = clipboardLink;
    if (!sel || transcriptId == null || !target) return;
    setTSel(null);
    try {
      const pos0 = renderedToRaw(transcriptRaw, crAt, sel.start);
      const pos1 = renderedToRaw(transcriptRaw, crAt, sel.end);
      await createLink({
        from_fid: transcriptId,
        from_pos0: pos0,
        from_pos1: pos1,
        to_fid: target.fid,
        to_pos0: target.pos0,
        to_pos1: target.pos1,
      });
      await useProjectStore.getState().refreshProject();
    } catch (e) {
      setTError(e instanceof Error ? e.message : t("coder.linkCreateError"));
    }
  }

  function onTranscriptMouseUp() {
    const container = transcriptTextRef.current;
    if (!container || transcriptId == null) return;
    const sel = getSelectionOffsets(container, window.getSelection());
    if (!sel || sel.start === sel.end) {
      setTSel(null);
      return;
    }
    const rect = window.getSelection()?.getRangeAt(0).getBoundingClientRect();
    setTSel({
      start: sel.start,
      end: sel.end,
      left: rect ? rect.left : 0,
      top: rect ? rect.bottom + 4 : 0,
    });
    codingIntentRef.current = "text";
  }

  async function codeTranscriptSelection(cid: number) {
    const sel = tSelRef.current;
    if (!sel || transcriptId == null) return;
    setTSel(null);
    try {
      const pos0 = renderedToRaw(transcriptRaw, crAt, sel.start);
      const pos1 = renderedToRaw(transcriptRaw, crAt, sel.end);
      await api.createTextCoding({
        cid,
        fid: transcriptId,
        seltext: transcriptRaw.slice(pos0, pos1),
        pos0,
        pos1,
      });
      await useProjectStore.getState().refreshProject();
      await loadTranscriptCodings();
    } catch (e) {
      setTError(e instanceof Error ? e.message : t("coder.createError"));
    }
  }

  // Clicking a code in the left sidebar codes the selected transcript part.
  // The listener must always use the LATEST handler: a fresh closure would
  // capture the first render's transcriptId (null before the transcript
  // exists), so the highlight reload would silently no-op.
  const codeTranscriptSelectionRef = useRef(codeTranscriptSelection);
  codeTranscriptSelectionRef.current = codeTranscriptSelection;
  useEffect(() => {
    const onAssign = (e: Event) => {
      const cid = (e as CustomEvent<{ cid: number }>).detail?.cid;
      if (typeof cid !== "number") return;
      setTPickerOpen(false);
      if (codingIntentRef.current === "text" && tSelRef.current) {
        void codeTranscriptSelectionRef.current(cid);
      }
    };
    window.addEventListener("qc:assign-code", onAssign);
    return () => window.removeEventListener("qc:assign-code", onAssign);
  }, []);

  async function saveTranscriptAnnotation() {
    const sel = tSelRef.current;
    if (!sel || transcriptId == null) return;
    setTSel(null);
    setTAnnotateOpen(false);
    setTAnnotateMemo("");
    try {
      const pos0 = renderedToRaw(transcriptRaw, crAt, sel.start);
      const pos1 = renderedToRaw(transcriptRaw, crAt, sel.end);
      await api.createAnnotation({
        fid: transcriptId,
        pos0,
        pos1,
        memo: tAnnotateMemo.trim(),
      });
      await useProjectStore.getState().refreshProject();
    } catch (e) {
      setTError(e instanceof Error ? e.message : t("coder.annotationCreateError"));
    }
  }

  // --- transcript autocode ---
  const [autoOpen, setAutoOpen] = useState(false);

  function handleAutocodeDone() {
    void useProjectStore.getState().refreshProject();
    void loadTranscriptCodings();
  }

  /** Render the coded subranges of one transcript line (absolute offsets
   *  include the "[mm:ss] " prefixes). Stored positions are in RAW space
   *  (CRLF line endings), the rendered line in normalized space.
   *  Overlapping codings are CLIPPED to the not-yet-rendered portion so
   *  the line's text is never duplicated in the DOM (duplicated text
   *  would skew every later selection offset). */
  function renderCodedLine(textStart: number, text: string): ReactNode {
    const out: ReactNode[] = [];
    let cursor = 0;
    const overlaps = transcriptCodings
      .map((c) => ({ ...c, r0: rawToRendered(crAt, c.pos0), r1: rawToRendered(crAt, c.pos1) }))
      .filter((c) => c.r1 > textStart && c.r0 < textStart + text.length)
      .sort((a, b) => a.r0 - b.r0 || a.r1 - b.r1);
    for (const c of overlaps) {
      const s = Math.max(cursor, Math.max(0, c.r0 - textStart));
      const e = Math.min(text.length, c.r1 - textStart);
      if (e <= s) continue;
      if (s > cursor) out.push(text.slice(cursor, s));
      const color = colorByCid.get(c.cid);
      out.push(
        <span
          key={c.ctid}
          className="rounded-sm"
          style={{ backgroundColor: codeTint(color ?? "var(--qc-accent)") }}
        >
          {text.slice(s, e)}
        </span>,
      );
      cursor = e;
    }
    if (cursor < text.length) out.push(text.slice(cursor));
    return out;
  }

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
    transcriptTextRef.current
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
      if (s.tasks !== prev.tasks) {
        const done = s.tasks.find(
          (j) => j.kind === "transcribe" && j.sourceId === source.id && j.state === "done",
        );
        if (done && prev.tasks.find((j) => j.id === done.id)?.state !== "done") {
          void loadTranscript();
          setTranscriptVisible(true);
        }
      }
    });
    return unsub;
  }, [source.id, loadTranscript]);

  useEffect(() => {
    void load();
    void loadTranscript();
  }, [load, loadTranscript]);

  // --- transcript codings (highlight the already coded text) ---
  const [transcriptCodings, setTranscriptCodings] = useState<Coding[]>([]);

  const loadTranscriptCodings = useCallback(async () => {
    if (transcriptId == null) {
      setTranscriptCodings([]);
      return;
    }
    try {
      const codings = await api.sourceCoding(transcriptId);
      // Codings created by builds predating the CRLF handling were stored
      // in rendered space (their seltext then contains text from the
      // following line); normalize every coding to raw space so the
      // highlights land where they were marked.
      setTranscriptCodings(codings.map((c) => normalizeCodingPositions(transcriptRaw, crAt, c)));
    } catch {
      setTranscriptCodings([]);
    }
  }, [transcriptId, transcriptRaw, crAt]);

  useEffect(() => {
    void loadTranscriptCodings();
  }, [loadTranscriptCodings]);

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
    const onTime = () => {
      const ms = secondsToMs(el.currentTime || 0);
      // A seek's timeupdate may report the PRE-seek position (the media
      // seek is async) — while a seek is in flight, keep the intended
      // target so a quick mark-start → seek → mark-end sequence is exact.
      const target = seekTargetRef.current;
      if (target !== null) {
        const within = Date.now() - seekAtRef.current;
        if (within < 300) {
          // Right after a seek only the target itself (or a tiny playback
          // step) can be valid; anything further away is the stale
          // pre-seek position — a backward seek while paused otherwise
          // freezes the display at the old position forever.
          if (Math.abs(ms - target) > 300) return;
          seekTargetRef.current = null;
        } else if (within < 1500 && ms < target) {
          // Forward seek in flight: ignore positions before the target.
          return;
        } else {
          seekTargetRef.current = null;
        }
      }
      currentMsRef.current = ms;
      setCurrentMs(ms);
    };
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
    // and a pixel-click ratio yields fractional values. The ref keeps the
    // latest intended position even before the media's timeupdate fires.
    seekTargetRef.current = Math.round(clamped);
    seekAtRef.current = Date.now();
    currentMsRef.current = Math.round(clamped);
    setCurrentMs(Math.round(clamped));
  }

  // --- transport keys + manual transcription ---------------------------

  // Latest handlers, so window listeners registered once never go stale.
  const togglePlayRef = useRef(togglePlay);
  togglePlayRef.current = togglePlay;
  const seekByRef = useRef((delta: number) => seekToMs(currentMsRef.current + delta));
  seekByRef.current = (delta: number) => seekToMs(currentMsRef.current + delta);

  // Space toggles play/pause while the coder is focused (skips inputs and
  // buttons — in the textarea Space types). F9 and Ctrl+Space work even
  // inside the textarea, so transcription never needs a pedal.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.code === "F9" || e.key === "F9") {
        e.preventDefault();
        if (!e.repeat) togglePlayRef.current();
        return;
      }
      if ((e.ctrlKey || e.metaKey) && e.code === "Space") {
        e.preventDefault();
        if (!e.repeat) togglePlayRef.current();
        return;
      }
      if (e.code !== "Space" || e.ctrlKey || e.metaKey || e.altKey || e.repeat) return;
      const target = e.target instanceof HTMLElement ? e.target : null;
      const tag = target?.tagName ?? "";
      const inEditable =
        tag === "TEXTAREA" || tag === "INPUT" || tag === "SELECT" || (target?.isContentEditable ?? false);
      const inControl = tag === "BUTTON" || tag === "A" || tag === "LABEL";
      if (inEditable || inControl) return;
      e.preventDefault();
      togglePlayRef.current();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  // OS media keys (WebView2/Chromium): Play/Pause drive the same transport,
  // Previous/Next track jump 10s back/forward. The API may be unavailable
  // (or reject individual actions) — guard everything; F9/Space still work.
  useEffect(() => {
    const ms = (navigator as Navigator & { mediaSession?: MediaSession }).mediaSession;
    if (!ms) return;
    try {
      if (typeof MediaMetadata !== "undefined") {
        ms.metadata = new MediaMetadata({
          title: source.name,
          artist: "QualCoder",
          album: "QualCoder",
        });
      }
    } catch {
      /* metadata is optional */
    }
    const setHandler = (action: MediaSessionAction, handler: MediaSessionActionHandler | null) => {
      try {
        ms.setActionHandler(action, handler);
      } catch {
        /* action unsupported — keep the rest wired */
      }
    };
    setHandler("play", () => togglePlayRef.current());
    setHandler("pause", () => togglePlayRef.current());
    setHandler("previoustrack", () => seekByRef.current(-10000));
    setHandler("nexttrack", () => seekByRef.current(10000));
    return () => {
      setHandler("play", null);
      setHandler("pause", null);
      setHandler("previoustrack", null);
      setHandler("nexttrack", null);
    };
  }, [source.name, source.id]);

  // Mirror the transport state to the OS (media keys + shell indicators).
  useEffect(() => {
    const ms = (navigator as Navigator & { mediaSession?: MediaSession }).mediaSession;
    if (ms) ms.playbackState = playing ? "playing" : "paused";
  }, [playing]);

  // --- manual transcription mode ----------------------------------------

  function toggleTranscribeMode() {
    setTSel(null);
    if (transcribeMode) {
      if (transcribeDraft !== transcriptText && !window.confirm(t("coder.discardConfirm"))) return;
      setTranscribeMode(false);
      setTranscribeDraft("");
    } else {
      setTranscribeDraft(transcriptText);
      setTranscribeMode(true);
      requestAnimationFrame(() => transcribeAreaRef.current?.focus());
    }
  }

  /** Insert "[mm:ss] " for the current playback position at the caret. */
  function insertTranscriptTimestamp() {
    const el = transcribeAreaRef.current;
    if (!el) return;
    const { text, caret } = insertTimestampAtCaret(
      el.value,
      el.selectionStart,
      el.selectionEnd,
      transcriptTimestamp(currentMsRef.current),
    );
    setTranscribeDraft(text);
    // Re-apply the caret once React has committed the new value.
    requestAnimationFrame(() => {
      el.focus();
      el.setSelectionRange(caret, caret);
    });
  }

  /** Persist the manual transcript through the commit-edit path, which
   *  re-anchors (and reports deletions of) existing text codings, case text
   *  and annotations; timeline codings live on the media file and are never
   *  affected. */
  async function saveTranscribe() {
    if (transcriptId == null) return;
    setTranscribeSaving(true);
    setTError(null);
    try {
      await api.commitEdit({ fid: transcriptId, new_text: transcribeDraft });
      setTranscribeMode(false);
      setTranscribeDraft("");
      await loadTranscript();
      await loadTranscriptCodings();
    } catch (e) {
      setTError(e instanceof Error ? e.message : t("coder.saveError"));
    } finally {
      setTranscribeSaving(false);
    }
  }

  // The transcript companion may switch (re-transcription) — never keep a
  // draft that belongs to another source's text.
  useEffect(() => {
    setTranscribeMode(false);
    setTranscribeDraft("");
    setTSel(null);
  }, [transcriptId]);

  function handleTimelineClick(e: React.MouseEvent) {
    const el = timelineRef.current;
    if (!el || !durationMs) return;
    const rect = el.getBoundingClientRect();
    const ratio = (e.clientX - rect.left) / rect.width;
    seekToMs(ratio * durationMs);
  }

  // --- coding flow ------------------------------------------------------

  function handleSetStart() {
    setStartMark(currentMsRef.current);
    setSelected(null);
    // Marking a range switches the coding intent away from any transcript
    // text selection (otherwise one sidebar click could code both).
    setTSel(null);
    codingIntentRef.current = "range";
  }

  function handleSetEnd() {
    const now = currentMsRef.current;
    if (startMark === null) return;
    if (now <= startMark) {
      setError(t("avCoder.endAfterStart"));
      return;
    }
    setPendingStart(startMark);
    setStartMark(null);
    codingIntentRef.current = "range";
    if (activeCodeId != null) {
      void codeRange(activeCodeId, startMark, now);
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
      if (codingIntentRef.current === "range" && start !== null) {
        void codeRange(cid, start, currentMs);
      }
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
    return <LoadingState>{t("avCoder.loading")}</LoadingState>;
  }

  if (error && codings.length === 0 && !mediaError) {
    return (
      <div className="flex h-full items-center justify-center bg-bg">
        <div className="text-center">
          <p className="text-danger">{error}</p>
          <Button variant="secondary" className="mt-3" onClick={() => void load()}>
            {t("common.retry")}
          </Button>
        </div>
      </div>
    );
  }

  const isVideo = source.media_type === "video";

  return (
    <div className="flex h-full flex-col bg-bg">
      {/* Header: back button + file name + transcription/coding controls.
          Playback lives in the transport bar below the media. */}
      <ViewHeader
        wrap
        title={source.name}
        meta={source.memo}
        actions={
          <>
            {canTranscribeSource(source) && (
              <Button
                variant="secondary"
                onClick={() => setTranscribeOpen(true)}
                title={t("transcribe.title")}
                className="shrink-0"
                icon={<Mic size={12} aria-hidden />}
              >
                {t("transcribe.button")}
              </Button>
            )}
            <Button
              variant="secondary"
              onClick={() => setTranscriptVisible((v) => !v)}
              aria-pressed={transcriptVisible}
              title={t("avCoder.transcript")}
              className={cn(
                "shrink-0",
                transcriptVisible ? "border-accent text-accent" : "bg-bg text-text-secondary",
              )}
              icon={<Captions size={12} aria-hidden />}
            >
              {t("avCoder.transcript")}
            </Button>
            <Button
              variant="secondary"
              onClick={toggleTranscribeMode}
              aria-pressed={transcribeMode}
              disabled={transcriptId == null}
              title={t("avCoder.transcribeHint")}
              className={cn(
                "shrink-0",
                transcribeMode ? "border-accent text-accent" : "bg-bg text-text-secondary",
              )}
              icon={<FilePen size={12} aria-hidden />}
            >
              {t("avCoder.transcribeMode")}
            </Button>
            {source.media_type === "video" && (
              <Button
                variant="secondary"
                onClick={() => setVideoVisible((v) => !v)}
                aria-pressed={videoVisible}
                title={t("avCoder.video")}
                className={cn(
                  "shrink-0",
                  videoVisible ? "border-accent text-accent" : "bg-bg text-text-secondary",
                )}
                icon={<Video size={12} aria-hidden />}
              >
                {t("avCoder.video")}
              </Button>
            )}
            <div className="flex-1" />
            <IconButton
              label={t("avCoder.bookmarkSet")}
              title={t("avCoder.bookmarkSet")}
              onClick={() => void setAvBookmark()}
              className={cn(avBookmarkFile === source.id && "text-accent")}
            >
              <Bookmark
                size={16}
                className={avBookmarkFile === source.id ? "fill-current" : ""}
                aria-hidden
              />
            </IconButton>
            <IconButton
              label={t("avCoder.bookmarkGo")}
              title={t("avCoder.bookmarkGo")}
              onClick={() => void goAvBookmark()}
              disabled={avBookmarkFile == null}
            >
              <BookmarkCheck size={16} aria-hidden />
            </IconButton>
            <Button
              variant={startMark !== null ? "primary" : "secondary"}
              onClick={startMark !== null ? handleSetEnd : handleSetStart}
              disabled={!durationMs}
              className="shrink-0"
            >
              {startMark !== null ? t("avCoder.setEndAndCode") : t("avCoder.setStart")}
            </Button>
            {startMark !== null && (
              <span className="flex shrink-0 items-center gap-1 text-xs text-accent">
                {t("avCoder.start", { time: formatTime(startMark) })}
                <IconButton
                  label={t("avCoder.clearStart")}
                  size="sm"
                  onClick={() => setStartMark(null)}
                >
                  <X size={12} aria-hidden />
                </IconButton>
              </span>
            )}
          </>
        }
      />

      {/* Playback + timeline on ONE row: play / time / speed / progress */}
      {(() => {
        const transportRow = (
          <div className="flex shrink-0 items-center gap-1.5 border-b border-border bg-surface px-3 py-1.5">
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
            <Select
              value={playbackRate}
              onChange={(e) => setSpeed(Number(e.target.value))}
              aria-label={t("avCoder.speed")}
              title={t("avCoder.speedTitle")}
              className="shrink-0"
            >
              {[0.5, 0.75, 1, 1.25, 1.5, 2].map((r) => (
                <option key={r} value={r}>
                  {r}×
                </option>
              ))}
            </Select>
            <div
              ref={timelineRef}
              onClick={handleTimelineClick}
              className="relative h-7 min-w-0 flex-1 cursor-pointer overflow-hidden rounded-sm border border-border bg-bg"
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
                  className={`absolute top-0 h-full cursor-pointer border qc-seg ${
                    hiddenCodes.includes(coding.cid) ? "qc-seg-hidden" : ""
                  }`}
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
          </div>
        );

        const transcriptPanel = (
          <div className="flex min-h-0 flex-1 flex-col bg-bg">
            <div className="flex shrink-0 items-center gap-1 border-b border-border bg-surface px-3 py-1.5">
              <Captions size={12} className="text-text-secondary" aria-hidden />
              <span className="text-xs font-medium text-text-primary">{t("avCoder.transcript")}</span>
              <span className="ml-2 truncate text-xs text-text-secondary">{transcript?.name}</span>
              {transcriptId != null && !transcribeMode && (
                <span className="ml-1 truncate text-[10px] text-text-secondary">
                  {t("avCoder.transcriptSelectHint")}
                </span>
              )}
              {transcribeMode && (
                <span className="ml-1 truncate text-[10px] text-accent">
                  {t("avCoder.transcribeHint")}
                </span>
              )}
              <div className="flex-1" />
              {transcribeMode ? (
                <>
                  {transcribeSaving && (
                    <span className="flex items-center gap-1 text-xs text-text-secondary" role="status">
                      <LoaderCircle size={12} className="animate-spin" aria-hidden />
                      {t("coder.saving")}
                    </span>
                  )}
                  <IconButton
                    label={t("avCoder.transcribeInsert")}
                    title={t("avCoder.transcribeInsert")}
                    size="sm"
                    onClick={insertTranscriptTimestamp}
                  >
                    <Clock size={14} aria-hidden />
                  </IconButton>
                  <Button
                    variant="primary"
                    className="h-6 px-1.5"
                    icon={<Save size={12} aria-hidden />}
                    onClick={() => void saveTranscribe()}
                    disabled={transcribeSaving}
                  >
                    {t("avCoder.transcribeSave")}
                  </Button>
                  <Button
                    variant="secondary"
                    className="h-6 px-1.5"
                    onClick={toggleTranscribeMode}
                    disabled={transcribeSaving}
                  >
                    {t("common.cancel")}
                  </Button>
                </>
              ) : (
                transcriptId != null && (
                  <Button
                    variant="secondary"
                    className="h-6 px-1.5"
                    onClick={() => setAutoOpen((o) => !o)}
                    icon={<Sparkles size={12} aria-hidden />}
                  >
                    {t("coder.autocode")}
                  </Button>
                )
              )}
              {tError && <span className="text-xs text-danger">{tError}</span>}
              <IconButton
                label={t("common.close")}
                title={t("common.close")}
                size="sm"
                onClick={() => setTranscriptVisible(false)}
              >
                <X size={14} aria-hidden />
              </IconButton>
            </div>
            {transcribeMode ? (
              <textarea
                ref={transcribeAreaRef}
                value={transcribeDraft}
                onChange={(e) => setTranscribeDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey && !e.ctrlKey && !e.metaKey && !e.altKey) {
                    e.preventDefault();
                    insertTranscriptTimestamp();
                  }
                  if ((e.ctrlKey || e.metaKey) && e.key === "s") {
                    e.preventDefault();
                    void saveTranscribe();
                  }
                }}
                spellCheck={false}
                aria-label={t("avCoder.transcribeMode")}
                className="qc-scroll min-h-0 w-full flex-1 resize-none bg-transparent px-4 py-3 font-mono text-sm leading-6 text-text-primary outline-none"
              />
            ) : (
            <div
              ref={transcriptTextRef}
              onMouseUp={onTranscriptMouseUp}
              className="qc-selectable qc-scroll min-h-0 flex-1 overflow-y-auto px-4 py-3 text-sm leading-6 text-text-primary"
              role="log"
              aria-live="off"
            >
              {subtitleSegments.length === 0 ? (
                <p className="py-6 text-center text-sm text-text-secondary">
                  {t("avCoder.noTranscript")}
                </p>
              ) : (
                (() => {
                  // Absolute text offsets per line (timestamps included) so
                  // the coding highlights line up with the stored text.
                  let lineStart = 0;
                  return subtitleSegments.map((seg, i) => {
                    const active = activeSubtitle === seg;
                    const tsLen = transcriptTimestamp(seg.startMs).length;
                    const textStart = lineStart + tsLen + 1;
                    const line = (
                      <div
                        data-start={seg.startMs}
                        onClick={() => {
                          const sel = window.getSelection();
                          if (sel && !sel.isCollapsed) return;
                          setTSel(null);
                          seekToMs(seg.startMs);
                        }}
                        title={t("avCoder.seekTo", { time: formatTime(seg.startMs) })}
                        className={`flex items-baseline gap-2 rounded-sm ${
                          active ? "bg-accent/15 font-medium" : ""
                        }`}
                      >
                        <span className="w-14 shrink-0 text-right font-mono text-[10px] text-text-secondary">
                          {transcriptTimestamp(seg.startMs)}
                        </span>
                        <span className="min-w-0 flex-1">
                          {" "}
                          {renderCodedLine(textStart, seg.text)}
                        </span>
                      </div>
                    );
                    lineStart = textStart + seg.text.length + 1;
                    return (
                      <Fragment key={`${seg.startMs}-${i}`}>
                        {i > 0 && "\n"}
                        {line}
                      </Fragment>
                    );
                  });
                })()
              )}
            </div>
            )}
            {/* Floating selection toolbar (code / annotate) */}
            {tSel && !tAnnotateOpen && (
              <div
                className="fixed z-40 flex items-center gap-1 rounded-md border border-border bg-surface p-1 shadow-lg"
                style={{ left: Math.min(tSel.left, window.innerWidth - 200), top: tSel.top }}
                role="toolbar"
                aria-label={t("coder.selectionActions")}
              >
                <Button
                  variant="primary"
                  icon={<Code size={12} aria-hidden />}
                  className="max-w-56"
                  onClick={() => {
                    const activeCodeId = useProjectStore.getState().activeCodeId;
                    if (activeCodeId != null) void codeTranscriptSelection(activeCodeId);
                    else setTPickerOpen(true);
                  }}
                >
                  <span className="truncate">{t("coder.codeAction")}</span>
                </Button>
                <Button
                  variant="secondary"
                  icon={<StickyNote size={12} aria-hidden />}
                  onClick={() => {
                    setTAnnotateMemo("");
                    setTAnnotateOpen(true);
                  }}
                >
                  {t("coder.annotate")}
                </Button>
                <Button
                  variant="secondary"
                  icon={<LinkIcon size={12} aria-hidden />}
                  onClick={() => void copyTranscriptLink()}
                  title={t("coder.linkCopied")}
                >
                  {linkCopied ? t("coder.copyLinkDone") : t("coder.copyLink")}
                </Button>
                {clipboardLink && (
                  <Button
                    variant="secondary"
                    icon={<LinkIcon size={12} aria-hidden />}
                    onClick={() => void pasteTranscriptLink()}
                    title={t("coder.linkCopied")}
                  >
                    {t("coder.pasteLinkHere")}
                  </Button>
                )}
              </div>
            )}
            {/* Annotate popover */}
            {tAnnotateOpen && (
              <div
                className={`fixed z-40 w-72 p-2 ${cls.popup}`}
                style={{ left: Math.min(tSel?.left ?? 0, window.innerWidth - 300), top: tSel?.top ?? 0 }}
                role="dialog"
                aria-modal="true"
                aria-label={t("coder.addAnnotation")}
              >
                <Textarea
                  autoFocus
                  value={tAnnotateMemo}
                  onChange={(e) => setTAnnotateMemo(e.target.value)}
                  placeholder={t("coder.annotationMemoPlaceholder")}
                  className="h-20 w-full resize-none p-1.5"
                />
                <div className="mt-2 flex justify-end gap-1.5">
                  <Button variant="secondary" onClick={() => setTAnnotateOpen(false)}>
                    {t("common.cancel")}
                  </Button>
                  <Button
                    variant="primary"
                    icon={<Check size={12} aria-hidden />}
                    onClick={() => void saveTranscriptAnnotation()}
                  >
                    {t("common.save")}
                  </Button>
                </div>
              </div>
            )}
            <CodePicker
              open={tPickerOpen}
              codes={storeCodeTree}
              onClose={() => setTPickerOpen(false)}
              onPick={(picked) => void codeTranscriptSelection(picked.cid)}
            />
          </div>
        );

        // Media on top, transport row below it, transcript in the lower
        // half (video and audio alike — the transcript never hides). The
        // border between the video and the rest is draggable.
        return (
          <>
            <div className="shrink-0 border-b border-border bg-surface">
              {isVideo ? (
                <video
                  ref={mediaRef}
                  src={sourceFileUrl(source.id)}
                  preload="metadata"
                  aria-label={source.name}
                  style={videoVisible ? { height: videoH } : undefined}
                  className={`block max-h-[70vh] w-full bg-bg ${videoVisible ? "" : "hidden"}`}
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
              {!isVideo && <audio ref={mediaRef} src={sourceFileUrl(source.id)} preload="metadata" className="hidden" />}
            </div>
            {/* Draggable divider: resize the video / transcript split */}
            {isVideo && videoVisible && (
              <div
                onMouseDown={startVideoResize}
                className={`h-1 shrink-0 cursor-row-resize border-b border-border ${
                  videoDragging ? "bg-accent/40" : "bg-surface hover:bg-accent/40"
                }`}
                role="separator"
                aria-orientation="horizontal"
                aria-label={t("avCoder.resizeVideo")}
              />
            )}
            {transportRow}
            {transcriptVisible && <div className="flex min-h-0 flex-1 flex-col border-t border-border">{transcriptPanel}</div>}
            {!transcriptVisible && codings.length === 0 && !selected && (
              <div className="flex flex-1 items-center justify-center bg-bg text-sm text-text-secondary">
                {t("avCoder.hint")}
              </div>
            )}
          </>
        );
      })()}

      {mediaError && <ErrorBanner>{mediaError}</ErrorBanner>}
      {error && <ErrorBanner>{error}</ErrorBanner>}

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
          <Button
            variant="danger"
            icon={<Trash2 size={12} aria-hidden />}
            onClick={() => void handleDelete(selected)}
          >
            {t("common.delete")}
          </Button>
          <Button variant="secondary" onClick={() => setSelected(null)}>
            {t("common.close")}
          </Button>
        </div>
      )}

      <CodePicker
        open={pickerOpen}
        codes={storeCodeTree}
        onClose={() => {
          setPickerOpen(false);
          setPendingStart(null);
        }}
        onPick={(code) => void handlePick(code)}
      />

      <AutocodeDialog
        open={autoOpen}
        onClose={() => setAutoOpen(false)}
        fid={transcriptId}
        codes={storeCodeTree}
        onDone={handleAutocodeDone}
      />

      {transcribeOpen && (
        <TranscribeDialog sourceId={source.id} onClose={() => setTranscribeOpen(false)} />
      )}
    </div>
  );
}
