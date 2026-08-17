/**
 * AvCoder — audio/video playback with time-range coding on a timeline.
 *
 * Segment positions (pos0/pos1) are stored in milliseconds.
 */
import { Fragment, useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useAsyncEffect } from "@/lib/useAsync";
import {
  Bookmark,
  BookmarkCheck,
  Captions,
  Check,
  Clock,
  Code,
  Link as LinkIcon,
  LoaderCircle,
  Mic,
  Minus,
  Music,
  Pause,
  Pencil,
  Play,
  Plus,
  Sparkles,
  Star,
  StickyNote,
  Tag,
  Trash2,
  Video,
  X,
} from "lucide-react";
import {
  api,
  ApiError,
  fetchWithTimeout,
  initApiBase,
  invalidateApiBase,
  sourceFileUrl,
  type AVCoding,
  type Coding,
  type Source,
} from "@/lib/api";
import { patchCodingWeight, useCodeMaps } from "@/features/coding/codingApi";
import { useCoder } from "@/features/coding/useCoder";
import { CodePicker, type PickedCode } from "@/features/coding/CodePicker";
import { AutocodeDialog } from "@/features/coding/AutocodeDialog";
import { TranscribeDialog } from "@/features/coding/TranscribeDialog";
import { formatTime, insertTimestampAtCaret, parseTranscript, segmentLeft, secondsToMs, segmentWidth, buildCrAt, rawToRendered, renderedToRaw, stripCr, normalizeCodingPositions } from "@/features/coding/media";
import { getSelectionOffsets } from "@/features/coding/selection";
import { FALLBACK_CODE_COLOR, codeTint } from "@/features/coding/tint";
import {
  copyLinkPayload,
  createLink,
  readLinkPayload,
  type LinkSpanTarget,
} from "@/features/coding/links";
import { canTranscribeSource } from "@/lib/media";
import { cn, errorMessage } from "@/lib/utils";
import { useI18n } from "@/lib/i18n";
import {
  Button,
  ErrorBanner,
  IconButton,
  Input,
  LoadingState,
  Select,
  Textarea,
  ViewHeader,
} from "@/components/ui/orchestrator";
import { useCoderStore } from "@/stores/coder";
import { usePrefsStore } from "@/stores/prefs";
import { useWorkspaceStore } from "@/stores/workspace";
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

/** PATCH a transcript text coding's memo/important with a local fetch,
 *  mirroring codingApi's pattern — no lib/api.ts additions needed. */
async function patchTextCodingRow(
  id: number,
  body: { memo?: string; important?: number },
): Promise<unknown> {
  const path = `/codings/text/${id}`;
  const doFetch = async (): Promise<unknown> => {
    const base = await initApiBase();
    const res = await fetchWithTimeout(`${base}${path}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      let detail: unknown;
      try {
        detail = (await res.json()).detail;
      } catch {
        /* non-JSON error body */
      }
      const suffix = typeof detail === "string" && detail ? `: ${detail}` : "";
      throw new ApiError(res.status, `API error ${res.status} on ${path}${suffix}`, detail);
    }
    return (await res.json()) as unknown;
  };
  try {
    return await doFetch();
  } catch (err) {
    if (err instanceof ApiError) throw err;
    return doFetch();
  }
}

export function AvCoder({ source }: { source: Source }) {
  const { t } = useI18n();
  const storeCodeTree = useProjectStore((s) => s.codeTree);
  const [transcribeOpen, setTranscribeOpen] = useState(false);
  const activeCodeId = useCoderStore((s) => s.activeCodeId);
  const hiddenCodes = useCoderStore((s) => s.hiddenCodes);
  /** When OFF, creating a coding does NOT auto-select it in the details
   *  footer (clicking a segment still views it). */
  const autoShowDetails = usePrefsStore((s) => s.autoShowSegmentDetails);
  const mediaRef = useRef<HTMLVideoElement & HTMLAudioElement>(null);
  const timelineRef = useRef<HTMLDivElement>(null);

  // The transcript source id may change AFTER this view mounts: background
  // transcription links a companion, manual transcription creates one, and
  // transcript deletion clears the link. The store's sources list refreshes
  // in every one of those cases, so the LIVE value wins; the prop only
  // serves as a mount-time fallback BEFORE the store has the source.
  // NOTE: this must not be written with `??`: after a transcript delete the
  // live value is explicitly null, and a null-coalescing fallback would
  // resurrect the stale prop id (CodingWorkspace fetched the prop source
  // once, so it still carries the deleted companion) — the view would keep
  // believing a transcript exists. The prop is consulted only when the live
  // source is not in the store at all.
  const liveSource = useProjectStore((s) => s.sources.find((x) => x.id === source.id));
  const transcriptId = liveSource ? liveSource.av_text_id : (source.av_text_id ?? null);
  /** Live id for the continuous-save helpers (timers and the unmount flush
   *  run outside renders, where the state value would be stale). */
  const transcribeIdRef = useRef(transcriptId);
  transcribeIdRef.current = transcriptId;

  const { loading, error, setError, codings, codes, reload } = useCoder(
    source,
    api.avCodings,
    t("coder.loadCodingsError"),
  );

  const [durationMs, setDurationMs] = useState(0);
  const [currentMs, setCurrentMs] = useState(0);
  const currentMsRef = useRef(0);
  const seekTargetRef = useRef<number | null>(null);
  const seekAtRef = useRef(0);
  const [playing, setPlaying] = useState(false);
  const [mediaError, setMediaError] = useState<string | null>(null);
  // The media element needs a streaming URL (a fetched blob would load the
  // whole file and lose Range support), so the src is built from
  // sourceFileUrl() — correct because the App boot gate holds the whole UI
  // until initApiBase() settles. If the element still errors (backend
  // restarted on a new ephemeral port) the base is invalidated and
  // re-resolved once before the real error surfaces.
  const [mediaSrc, setMediaSrc] = useState(() => sourceFileUrl(source.id));
  const mediaRetriedRef = useRef(false);

  const [startMark, setStartMark] = useState<number | null>(null);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [pendingStart, setPendingStart] = useState<number | null>(null);
  const [selected, setSelected] = useState<AVCoding | null>(null);
  /** The transcript text coding whose details the footer shows (click a
   *  coded transcript segment). */
  const [selectedText, setSelectedText] = useState<Coding | null>(null);
  /** Draft while the footer's memo field is being edited inline (null =
   *  not editing). */
  const [memoDraft, setMemoDraft] = useState<string | null>(null);
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
  // user types while controlling playback with Space/F9/media keys. With no
  // transcript (or only an EMPTY companion) the mode is implicit — the panel
  // IS the transcription editor, so there is no toggle button.
  const [transcribeMode, setTranscribeMode] = useState(() => transcriptId == null);
  const [transcribeDraft, setTranscribeDraft] = useState("");
  const [transcribeSaving, setTranscribeSaving] = useState(false);
  const [transcribeBusy, setTranscribeBusy] = useState(false);
  const transcribeAreaRef = useRef<HTMLTextAreaElement | null>(null);
  /** The companion this view created itself — the transcriptId switch it
   *  causes must not tear down the transcription mode it just entered. */
  const createdTranscriptRef = useRef<number | null>(null);
  /** A companion creation is in flight — skip repeat POSTs while the first
   *  keystroke's transcriptId has not arrived yet. */
  const transcribeCreatingRef = useRef(false);
  /** A transcription job for this source ran since the last effect pass —
   *  its completion (or failure) transition is handled once by the mode
   *  effect below. */
  const jobWasRunningRef = useRef(false);

  // Continuous saving (mirrors the text coder's edit mode): every keystroke
  // schedules a debounced commitEdit, and the latest draft lives in a ref so
  // explicit flush points (insert, exit, unmount) always persist the newest
  // text even while an earlier commit is still in flight.
  const transcribeDraftRef = useRef("");
  /** The last draft text known to be persisted (stored companion text on
   *  entry, committed drafts afterwards). */
  const transcribeSavedRef = useRef("");
  const transcribeSaveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const transcribeSavingRef = useRef(false);
  /** A flush was requested while a commit was in flight — run one more
   *  once it finishes so newer keystrokes are never skipped. */
  const transcribeNeedsAnotherRef = useRef(false);

  // Bookmark
  const [avBookmarkMs, setAvBookmarkMs] = useState<number | null>(null);
  const [avBookmarkFile, setAvBookmarkFile] = useState<number | null>(null);

  useAsyncEffect(async (signal) => {
    try {
      const b = await api.bookmarks();
      signal.throwIfAborted();
      setAvBookmarkFile(b.av_bookmark_file_id);
      setAvBookmarkMs(b.av_bookmark_msec);
    } catch {
      /* a bookmark fetch failure should not disturb the AV coder */
    }
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
      useWorkspaceStore.getState().setView({ kind: "coding", sourceId: avBookmarkFile });
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
  /** The transcription job for THIS source in any state. While it is
   *  queued/running the manual editor must yield to it (the panel shows
   *  the live preview), and a finished job's transcript replaces any
   *  manual draft — the backend folds the result into the companion,
   *  overwriting its fulltext. */
  const transcribeJob = useProjectStore((s) =>
    s.tasks.find((j) => j.kind === "transcribe" && j.sourceId === source.id),
  );
  const transcribeJobState = transcribeJob?.state ?? null;
  const jobTranscriptSourceId = transcribeJob?.transcriptSourceId ?? null;
  const jobPending = transcribeJobState === "running" || transcribeJobState === "queued";
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
  const [tInVivoOpen, setTInVivoOpen] = useState(false);
  const [tInVivoName, setTInVivoName] = useState("");
  const [tInVivoCat, setTInVivoCat] = useState<number | null>(null);
  const [tInVivoBusy, setTInVivoBusy] = useState(false);
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

  useAsyncEffect(async (signal) => {
    const target = await readLinkPayload();
    signal.throwIfAborted();
    setClipboardLink(target);
  }, [tSel]);

  async function copyTranscriptLink() {
    const sel = tSelRef.current;
    if (!sel || transcriptId == null || jobPending) return;
    try {
      const pos0 = renderedToRaw(transcriptRaw, crAt, sel.start);
      const pos1 = renderedToRaw(transcriptRaw, crAt, sel.end);
      await copyLinkPayload(transcriptId, pos0, pos1);
      setClipboardLink({ fid: transcriptId, pos0, pos1 });
      setLinkCopied(true);
      if (linkCopiedTimer.current) clearTimeout(linkCopiedTimer.current);
      linkCopiedTimer.current = setTimeout(() => setLinkCopied(false), 1500);
    } catch (e) {
      setTError(errorMessage(e, t("coder.linkCopyError")));
    }
  }

  /** One link from the current transcript selection to the copied segment. */
  async function pasteTranscriptLink() {
    const sel = tSelRef.current;
    const target = clipboardLink;
    if (!sel || transcriptId == null || jobPending || !target) return;
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
      setTError(errorMessage(e, t("coder.linkCreateError")));
    }
  }

  function onTranscriptMouseUp() {
    const container = transcriptTextRef.current;
    // The live preview while a job runs is transient — never select/code
    // it (the offsets would not survive the job's finalize).
    if (!container || transcriptId == null || jobPending) return;
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
    if (!sel || transcriptId == null || jobPending) return;
    setTSel(null);
    try {
      const pos0 = renderedToRaw(transcriptRaw, crAt, sel.start);
      const pos1 = renderedToRaw(transcriptRaw, crAt, sel.end);
      const created = await api.createTextCoding({
        cid,
        fid: transcriptId,
        seltext: transcriptRaw.slice(pos0, pos1),
        pos0,
        pos1,
      });
      await useProjectStore.getState().refreshProject();
      const next = await loadTranscriptCodings();
      // Auto-show the freshly created coding (gated on the
      // "Auto-show segment details" pref).
      if (autoShowDetails) {
        setSelected(null);
        setSelectedText(next.find((c) => c.ctid === created.ctid) ?? null);
        setMemoDraft(null);
      } else {
        setSelectedText(null);
        setMemoDraft(null);
      }
    } catch (e) {
      setTError(errorMessage(e, t("coder.createError")));
    }
  }

  /** In-vivo coding: create a NEW code from the selected transcript text,
   *  then code the current transcript selection with it. */
  async function codeTranscriptInVivo() {
    const name = tInVivoName.trim();
    const sel = tSelRef.current;
    if (!name || tInVivoBusy || !sel || transcriptId == null || jobPending) return;
    setTInVivoBusy(true);
    setTError(null);
    try {
      const res = await api.createCode(name, { catid: tInVivoCat });
      const pos0 = renderedToRaw(transcriptRaw, crAt, sel.start);
      const pos1 = renderedToRaw(transcriptRaw, crAt, sel.end);
      const created = await api.createTextCoding({
        cid: res.cid,
        fid: transcriptId,
        seltext: transcriptRaw.slice(pos0, pos1),
        pos0,
        pos1,
      });
      setTSel(null);
      setTInVivoOpen(false);
      await useProjectStore.getState().refreshProject();
      const next = await loadTranscriptCodings();
      // Auto-show the freshly created coding (gated on the
      // "Auto-show segment details" pref).
      if (autoShowDetails) {
        setSelected(null);
        setSelectedText(next.find((c) => c.ctid === created.ctid) ?? null);
        setMemoDraft(null);
      } else {
        setSelectedText(null);
        setMemoDraft(null);
      }
    } catch (e) {
      setTError(errorMessage(e, t("coder.inVivoCreateError")));
    } finally {
      setTInVivoBusy(false);
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
    if (!sel || transcriptId == null || jobPending) return;
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
      setTError(errorMessage(e, t("coder.annotationCreateError")));
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
          className="cursor-pointer rounded-sm qc-seg"
          style={{ backgroundColor: codeTint(color ?? FALLBACK_CODE_COLOR) }}
          onClick={() => {
            // A click on a coded transcript segment opens its details in
            // the bottom footer (pure client state — no fetch).
            setSelected(null);
            setSelectedText(c);
            setMemoDraft(null);
            setTSel(null);
          }}
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

  const { colorByCid, nameByCid } = useCodeMaps(codes);

  /** Top-level code categories for the in-vivo popover's optional target. */
  const categories = useMemo(
    () => storeCodeTree.filter((c) => c.kind === "category"),
    [storeCodeTree],
  );

  const codeColor = (coding: AVCoding) => colorByCid.get(coding.cid) ?? "rgba(0,0,0,0.15)";

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
    void loadTranscript();
  }, [loadTranscript]);

  // --- transcript codings (highlight the already coded text) ---
  const [transcriptCodings, setTranscriptCodings] = useState<Coding[]>([]);

  const loadTranscriptCodings = useCallback(async (): Promise<Coding[]> => {
    if (transcriptId == null) {
      setTranscriptCodings([]);
      return [];
    }
    try {
      const codings = await api.sourceCoding(transcriptId);
      // Codings created by builds predating the CRLF handling were stored
      // in rendered space (their seltext then contains text from the
      // following line); normalize every coding to raw space so the
      // highlights land where they were marked.
      const next = codings.map((c) => normalizeCodingPositions(transcriptRaw, crAt, c));
      setTranscriptCodings(next);
      return next;
    } catch {
      setTranscriptCodings([]);
      return [];
    }
  }, [transcriptId, transcriptRaw, crAt]);

  useEffect(() => {
    void loadTranscriptCodings();
  }, [loadTranscriptCodings]);

  // History undo/redo: reload transcript codings when the audit log reverts
  // a change (the shell only refreshes project metadata).
  useEffect(() => {
    const handle = () => void loadTranscriptCodings();
    window.addEventListener("qc:codings-changed", handle);
    return () => window.removeEventListener("qc:codings-changed", handle);
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
    const onError = () => {
      // A stale base (backend restarted on a new ephemeral port) surfaces
      // as a media load error — invalidate + re-resolve the base and
      // rebuild the src once before giving up with the real error message.
      if (!mediaRetriedRef.current) {
        mediaRetriedRef.current = true;
        invalidateApiBase();
        void initApiBase().then(() => setMediaSrc(sourceFileUrl(source.id)));
        return;
      }
      setMediaError(t("avCoder.loadFileError"));
    };

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
  }, [loading, source.id, t]);

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

  /** Create the EMPTY transcript companion lazily, on the first keystroke
   *  of a transcript-less source (POST /sources/{id}/transcript). The
   *  editor is already on screen; the companion only appears once the user
   *  actually starts typing, so opening a media file for coding alone never
   *  pollutes the project with an empty transcript. The draft written
   *  before the companion arrives is flushed by the companion-switch
   *  effect once the transcriptId it causes lands. */
  async function ensureTranscribeCompanion() {
    if (transcriptId != null || transcribeCreatingRef.current) return;
    transcribeCreatingRef.current = true;
    setTranscribeBusy(true);
    setTError(null);
    try {
      const companion = await api.createTranscript(source.id);
      createdTranscriptRef.current = companion.id;
      await useProjectStore.getState().refreshProject();
    } catch (e) {
      setTError(errorMessage(e, t("avCoder.transcribeCreateError")));
    } finally {
      transcribeCreatingRef.current = false;
      setTranscribeBusy(false);
    }
  }

  /** Insert "[mm:ss] " for the current playback position at the caret.
   *  On an empty draft this is a plain pre-fill ("[00:00] ", caret after) —
   *  no leading newline — so the very first insert press can start typing. */
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
    transcribeDraftRef.current = text;
    void flushTranscribeSave();
    // An insert press on a transcript-less source is a first write too —
    // make sure the draft has a save target (the companion-switch effect
    // persists the draft once the transcriptId arrives).
    if (transcriptId == null) void ensureTranscribeCompanion();
    // Re-apply the caret once React has committed the new value.
    requestAnimationFrame(() => {
      el.focus();
      el.setSelectionRange(caret, caret);
    });
  }

  /** Tab: force a NEW segment — a line break plus the current timestamp,
   *  even MID-TEXT. Enter only prefixes a timestamp when the caret is at a
   *  line start; Tab always starts a fresh segment, so every timestamped
   *  entry stays parseable as its own line. At a line start (or on an empty
   *  draft) no break is added: the timestamp simply pre-fills the line. */
  function insertNewSegment() {
    const el = transcribeAreaRef.current;
    if (!el) return;
    const caret = el.selectionStart;
    const end = el.selectionEnd;
    const before = transcribeDraft.slice(0, caret);
    const ts = transcriptTimestamp(currentMsRef.current);
    const insertion = before === "" || before.endsWith("\n") ? `${ts} ` : `\n${ts} `;
    const text = transcribeDraft.slice(0, caret) + insertion + transcribeDraft.slice(end);
    setTranscribeDraft(text);
    transcribeDraftRef.current = text;
    void flushTranscribeSave();
    if (transcriptId == null) void ensureTranscribeCompanion();
    requestAnimationFrame(() => {
      el.focus();
      el.setSelectionRange(caret + insertion.length, caret + insertion.length);
    });
  }

  /** Delete the transcript companion entirely (text codings on it are
   *  removed with it) and clear the av_text_id link. */
  async function deleteTranscript() {
    if (transcriptId == null || transcribeBusy) return;
    if (!window.confirm(t("avCoder.deleteTranscriptConfirm"))) return;
    setTranscribeBusy(true);
    setTError(null);
    // No commit may still target a companion that is about to disappear.
    if (transcribeSaveTimer.current) {
      clearTimeout(transcribeSaveTimer.current);
      transcribeSaveTimer.current = null;
    }
    transcribeNeedsAnotherRef.current = false;
    try {
      await api.deleteTranscript(source.id);
      transcribeDraftRef.current = "";
      transcribeSavedRef.current = "";
      setTranscript(null);
      setTranscribeMode(false);
      setTranscribeDraft("");
      await useProjectStore.getState().refreshProject();
    } catch (e) {
      setTError(errorMessage(e, t("avCoder.deleteTranscriptError")));
    } finally {
      setTranscribeBusy(false);
    }
  }

  /** Debounced commit after typing stops (800 ms), mirroring the text
   *  coder's edit mode. */
  function scheduleTranscribeSave() {
    if (transcribeSaveTimer.current) clearTimeout(transcribeSaveTimer.current);
    transcribeSaveTimer.current = setTimeout(() => void flushTranscribeSave(), 800);
  }

  /** Persist the draft through the commit-edit path, which re-anchors (and
   *  reports deletions of) existing text codings, case text and
   *  annotations; timeline codings live on the media file and are never
   *  affected. Commits are serialized so the server applies them in order
   *  and always ends on the newest draft. On failure the inline error
   *  shows and the next change/exit retries. */
  async function flushTranscribeSave() {
    if (transcribeSaveTimer.current) {
      clearTimeout(transcribeSaveTimer.current);
      transcribeSaveTimer.current = null;
    }
    const tid = transcribeIdRef.current;
    if (tid == null) return;
    const draft = transcribeDraftRef.current;
    if (transcribeSavingRef.current) {
      // A commit is in flight — one more run once it finishes, so newer
      // keystrokes are never skipped.
      transcribeNeedsAnotherRef.current = true;
      return;
    }
    if (transcribeSavedRef.current === draft) return;
    transcribeSavingRef.current = true;
    setTranscribeSaving(true);
    try {
      await api.commitEdit({ fid: tid, new_text: draft });
      if (transcribeIdRef.current === tid) {
        transcribeSavedRef.current = draft;
        setTError(null);
      }
      void loadTranscriptCodings();
    } catch (e) {
      setTError(errorMessage(e, t("coder.saveError")));
    } finally {
      transcribeSavingRef.current = false;
      setTranscribeSaving(false);
      if (transcribeNeedsAnotherRef.current) {
        transcribeNeedsAnotherRef.current = false;
        transcribeSaveTimer.current = setTimeout(() => void flushTranscribeSave(), 800);
      }
    }
  }

  // Latest helper so the unmount flush always commits the newest draft.
  const flushTranscribeSaveRef = useRef(flushTranscribeSave);
  flushTranscribeSaveRef.current = flushTranscribeSave;

  // Persist anything still unsaved when the view unmounts mid-typing.
  useEffect(() => {
    return () => {
      if (transcribeSaveTimer.current) {
        clearTimeout(transcribeSaveTimer.current);
        transcribeSaveTimer.current = null;
      }
      void flushTranscribeSaveRef.current();
    };
  }, []);

  // The transcript companion may switch (re-transcription) — never keep a
  // draft that belongs to another source's text. Exception: the companion
  // this view created to enter transcription mode (the transcriptId switch
  // it causes must not cancel the mode it was created for).
  useEffect(() => {
    if (createdTranscriptRef.current != null && transcriptId === createdTranscriptRef.current) {
      createdTranscriptRef.current = null;
      // The keystrokes that created the companion arrived before it
      // existed — persist them now that there is a save target.
      void flushTranscribeSaveRef.current();
      return;
    }
    // The draft belongs to the OLD companion — cancel pending saves instead
    // of committing it to the new one.
    if (transcribeSaveTimer.current) {
      clearTimeout(transcribeSaveTimer.current);
      transcribeSaveTimer.current = null;
    }
    transcribeNeedsAnotherRef.current = false;
    transcribeDraftRef.current = "";
    transcribeSavedRef.current = "";
    setTranscribeMode(false);
    setTranscribeDraft("");
    setTSel(null);
    setTInVivoOpen(false);
    setTInVivoName("");
  }, [transcriptId]);

  // Transcription mode is implicit for sources without transcript CONTENT:
  // no companion yet, or a companion whose fulltext is still empty (the
  // importer pre-creates those). The panel shows the empty editor by
  // default; a companion is created lazily on the first keystroke. Once
  // real content exists the panel is read-only — the transition is handled
  // here (a background result) or by the companion-switch effect above.
  // A background transcription job (queued or running) OVERRIDES the mode:
  // the manual editor is suppressed so the panel shows the live preview
  // instead, and a finished job's transcript replaces any manual draft
  // (the backend folds the result into the companion, overwriting its
  // fulltext — so a stale draft must never be kept over it). A failed job
  // returns the editor with the draft intact.
  useEffect(() => {
    if (jobPending) {
      if (transcribeMode) {
        // The job owns the transcript from here on: cancel pending
        // debounced commits and flush the current draft, so no stale
        // commit can land after the job's finalize. The draft ref
        // survives — a failed job returns the editor with it.
        if (transcribeSaveTimer.current) {
          clearTimeout(transcribeSaveTimer.current);
          transcribeSaveTimer.current = null;
        }
        transcribeNeedsAnotherRef.current = false;
        void flushTranscribeSaveRef.current();
        setTranscribeMode(false);
      }
      jobWasRunningRef.current = true;
      return;
    }
    if (jobWasRunningRef.current) {
      jobWasRunningRef.current = false;
      if (transcribeJobState === "done" && jobTranscriptSourceId != null) {
        // The finished auto transcript replaced any manual draft.
        transcribeDraftRef.current = "";
        transcribeSavedRef.current = "";
        setTranscribeDraft("");
        // The transcript (re)load lands right behind the task update —
        // stay read-only this pass, or the editor flashes over a
        // finished transcript.
        const reloadPending =
          transcriptId !== jobTranscriptSourceId ||
          (transcriptId != null && (transcript == null || transcript.fulltext === ""));
        if (reloadPending) {
          setTranscribeMode(false);
          return;
        }
      } else if (transcribeDraftRef.current !== "") {
        // The job failed or finished without producing a transcript: the
        // manual draft is still the companion's content — return to the
        // editor with it.
        setTranscribeMode(true);
        return;
      }
    }
    const noContent = transcriptId == null || (transcript != null && transcript.fulltext === "");
    if (noContent) {
      if (!transcribeMode) {
        setTranscribeMode(true);
      }
      return;
    }
    // Real content arrived: back to the read-only view — but never tear
    // down an editor that still holds unpersisted user text.
    if (transcribeMode && transcribeDraftRef.current === "") {
      setTranscribeMode(false);
    }
  }, [transcriptId, transcript, transcribeMode, transcribeJobState, jobPending, jobTranscriptSourceId]);

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
      const created = await api.createAvCoding({
        id: source.id,
        pos0,
        pos1,
        cid,
        owner: "default",
      });
      setPendingStart(null);
      const fresh = await reload();
      // Show the details of the freshly assigned segment automatically
      // (gated on the "Auto-show segment details" pref).
      if (autoShowDetails) {
        setSelected(fresh.find((c) => c.avid === created.avid) ?? null);
      } else {
        setSelected(null);
      }
      setSelectedText(null);
      setMemoDraft(null);
    } catch (e) {
      setError(errorMessage(e, t("coder.createError")));
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

  /** Segment weight (backend rows carry it; 0 = no weight). */
  const avWeight = (coding: AVCoding | Coding): number =>
    (coding as (AVCoding | Coding) & { weight?: number }).weight ?? 0;

  /** Stepper update of a time-range coding's weight (0-100; 0 = no weight). */
  function updateCodingWeight(coding: AVCoding, weight: number) {
    void (async () => {
      try {
        await patchCodingWeight("av", coding.avid, weight);
        const fresh = await reload();
        setSelected(fresh.find((c) => c.avid === coding.avid) ?? null);
      } catch (e) {
        setError(errorMessage(e, t("coder.weightError")));
      }
    })();
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
      await reload();
    } catch (e) {
      setError(errorMessage(e, t("coder.deleteSegmentError")));
    }
  }

  /* --------------------------------------- transcript coding details row */

  /** Stepper update of a transcript coding's weight (0-100; 0 = no weight). */
  function updateTranscriptWeight(row: Coding, weight: number) {
    void (async () => {
      try {
        await patchCodingWeight("text", row.ctid, weight);
        await loadTranscriptCodings();
      } catch (e) {
        setTError(errorMessage(e, t("coder.weightError")));
      }
    })();
  }

  /** Open the footer's inline memo editor for the selected transcript coding. */
  function startEditTranscriptMemo() {
    if (!selectedText) return;
    setMemoDraft(selectedText.memo ?? "");
  }

  /** Save the memo draft of the selected transcript coding, then refresh. */
  function saveTranscriptMemo() {
    if (memoDraft == null || !selectedText) return;
    const draft = memoDraft;
    setMemoDraft(null);
    void (async () => {
      try {
        await patchTextCodingRow(selectedText.ctid, { memo: draft });
        await loadTranscriptCodings();
      } catch (e) {
        setTError(errorMessage(e, t("htmlCoder.updateError")));
      }
    })();
  }

  /** Toggle the important flag of the selected transcript coding. */
  function toggleTranscriptImportant() {
    if (!selectedText) return;
    const next = selectedText.important ? 0 : 1;
    void (async () => {
      try {
        await patchTextCodingRow(selectedText.ctid, { important: next });
        await loadTranscriptCodings();
      } catch (e) {
        setTError(errorMessage(e, t("htmlCoder.updateError")));
      }
    })();
  }

  /** Delete a transcript text coding (the timeline/AV codings are removed
   *  via handleDelete). */
  function handleTranscriptDelete(row: Coding) {
    if (
      !window.confirm(
        t("avCoder.deleteConfirm", {
          name: nameByCid.get(row.cid) ?? t("coder.plainCode"),
        }),
      )
    )
      return;
    void (async () => {
      try {
        await api.deleteTextCoding(row.ctid);
        setSelectedText(null);
        setMemoDraft(null);
        await loadTranscriptCodings();
      } catch (e) {
        setTError(errorMessage(e, t("coder.removeError")));
      }
    })();
  }

  // Escape closes the details footer (timeline segment or transcript coding).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      if (selected == null && selectedText == null) return;
      setSelected(null);
      setSelectedText(null);
      setMemoDraft(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  if (loading) {
    return <LoadingState>{t("avCoder.loading")}</LoadingState>;
  }

  if (error && codings.length === 0 && !mediaError) {
    return (
      <div className="flex h-full items-center justify-center bg-bg">
        <div className="text-center">
          <p className="text-danger">{error}</p>
          <Button variant="secondary" className="mt-3" onClick={() => void reload()}>
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
            <Button
              variant="toolbarIconPrimary"
              className="shrink-0"
              onClick={togglePlay}
              aria-label={playing ? t("avCoder.pause") : t("avCoder.play")}
              icon={playing ? <Pause size={14} aria-hidden /> : <Play size={14} aria-hidden />}
            />
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
                    setSelectedText(null);
                    setMemoDraft(null);
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
              {transcriptId != null && !transcribeMode && !jobPending && (
                <span className="ml-1 truncate text-[10px] text-text-secondary">
                  {t("avCoder.transcriptSelectHint")}
                </span>
              )}
              {transcribeMode && (
                <span className="ml-1 truncate text-[10px] text-accent">
                  {t("avCoder.transcribeHint")}
                </span>
              )}
              {jobPending && (
                <span className="ml-1 flex shrink-0 items-center gap-1 text-[10px] text-accent" role="status">
                  <LoaderCircle size={10} className="animate-spin" aria-hidden />
                  {t("transcribe.running")}
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
                </>
              ) : (
                transcriptId != null && (
                  <Button
                    variant="toolbar"
                    onClick={() => setAutoOpen((o) => !o)}
                    icon={<Sparkles size={12} aria-hidden />}
                  >
                    {t("coder.autocode")}
                  </Button>
                )
              )}
              {transcriptId != null && !transcribeSaving && (
                <Button
                  variant="toolbarDanger"
                  icon={<Trash2 size={12} aria-hidden />}
                  onClick={() => void deleteTranscript()}
                  disabled={transcribeBusy}
                  title={t("avCoder.deleteTranscriptTitle")}
                >
                  {t("avCoder.deleteTranscript")}
                </Button>
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
                onChange={(e) => {
                  // First character of an EMPTY draft: pre-fill the current
                  // playback position as "[mm:ss] " in front of the typed
                  // text — transcription starts with the very first
                  // keystroke, no insert press needed. A transcript-less
                  // source also gets its companion created lazily here.
                  let v = e.target.value;
                  if (transcribeDraft === "" && v !== "") {
                    v = `${transcriptTimestamp(currentMsRef.current)} ${v}`;
                  }
                  setTranscribeDraft(v);
                  transcribeDraftRef.current = v;
                  if (transcriptId == null) {
                    void ensureTranscribeCompanion();
                  } else {
                    scheduleTranscribeSave();
                  }
                }}
                onKeyDown={(e) => {
                  if (e.key === "Tab") {
                    // New segment: a line break + current timestamp even
                    // mid-text; never move focus out of the textarea.
                    e.preventDefault();
                    insertNewSegment();
                    return;
                  }
                  if (e.key === "Enter" && !e.shiftKey && !e.ctrlKey && !e.metaKey && !e.altKey) {
                    e.preventDefault();
                    insertTranscriptTimestamp();
                    return;
                  }
                  if ((e.ctrlKey || e.metaKey) && e.key === "s") {
                    e.preventDefault();
                    void flushTranscribeSave();
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
                jobPending ? (
                  <p className="py-6 text-center text-sm text-text-secondary" role="status">
                    {t("avCoder.transcribingJob")}
                  </p>
                ) : (
                  <p className="py-6 text-center text-sm text-text-secondary">
                    {t("avCoder.noTranscript")}
                  </p>
                )
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
            {tSel && !tAnnotateOpen && !tInVivoOpen && (
              <div
                className={`${cls.popup} fixed z-40 flex items-center gap-1 p-1`}
                style={{ left: Math.min(tSel.left, window.innerWidth - 200), top: tSel.top }}
                role="toolbar"
                aria-label={t("coder.selectionActions")}
              >
                <Button
                  variant="primary"
                  icon={<Code size={12} aria-hidden />}
                  className="max-w-56"
                  onClick={() => {
                    const activeCodeId = useCoderStore.getState().activeCodeId;
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
                  icon={<Tag size={12} aria-hidden />}
                  onClick={() => {
                    setTInVivoName("");
                    setTInVivoCat(null);
                    setTAnnotateOpen(false);
                    setTInVivoOpen(true);
                  }}
                  title={t("coder.inVivo")}
                >
                  {t("coder.inVivo")}
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
            {/* In-vivo popover: create a new code and code the selection */}
            {tInVivoOpen && (
              <div
                className={`fixed z-40 w-64 p-2 ${cls.popup}`}
                style={{ left: Math.min(tSel?.left ?? 0, window.innerWidth - 280), top: tSel?.top ?? 0 }}
                role="dialog"
                aria-modal="true"
                aria-label={t("coder.inVivo")}
              >
                <Input
                  autoFocus
                  value={tInVivoName}
                  onChange={(e) => setTInVivoName(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") void codeTranscriptInVivo();
                  }}
                  placeholder={t("coder.inVivoNamePlaceholder")}
                  aria-label={t("coder.inVivoNamePlaceholder")}
                />
                <Select
                  value={tInVivoCat ?? ""}
                  onChange={(e) =>
                    setTInVivoCat(e.target.value === "" ? null : Number(e.target.value))
                  }
                  aria-label={t("coder.inVivoCategory")}
                  className="mt-1.5 w-full"
                >
                  <option value="">{t("coder.inVivoNoCategory")}</option>
                  {categories.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                    </option>
                  ))}
                </Select>
                <div className="mt-2 flex justify-end gap-1.5">
                  <Button variant="secondary" onClick={() => setTInVivoOpen(false)}>
                    {t("common.cancel")}
                  </Button>
                  <Button
                    variant="primary"
                    icon={
                      tInVivoBusy ? (
                        <LoaderCircle size={12} className="animate-spin" aria-hidden />
                      ) : (
                        <Tag size={12} aria-hidden />
                      )
                    }
                    onClick={() => void codeTranscriptInVivo()}
                    disabled={tInVivoBusy || tInVivoName.trim() === ""}
                  >
                    {t("common.create")}
                  </Button>
                </div>
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
                  src={mediaSrc}
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
              {!isVideo && <audio ref={mediaRef} src={mediaSrc} preload="metadata" className="hidden" />}
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

      {/* Details panel: a timeline AVCoding or a transcript text coding
          (clicked `.qc-seg` in the transcript panel). Renders purely from
          client state — nothing is fetched on open. */}
      {(selected || selectedText) && (
        <div className="flex shrink-0 flex-wrap items-center gap-3 border-b border-border bg-surface px-3 py-2">
          {selected && (
            <>
              <span
                className="h-3 w-3 shrink-0 rounded-sm border border-border"
                style={{ backgroundColor: codeColor(selected) }}
                aria-hidden
              />
              <span className="truncate text-sm font-medium text-text-primary" title={selected.date}>
                {nameByCid.get(selected.cid) ?? t("coder.fallbackCodePlain", { id: selected.cid })}
              </span>
              <span className="font-mono text-xs text-text-secondary">
                {formatTime(selected.pos0)} – {formatTime(selected.pos1)}
              </span>
              <span className="truncate text-xs text-text-secondary">{selected.memo || t("common.noMemo")}</span>
              <span className="flex items-center gap-1">
                <span className="text-xs text-text-secondary">{t("coder.weight")}</span>
                <Button
                  variant="toolbarIcon"
                  icon={<Minus size={12} aria-hidden />}
                  title={t("coder.weightDec")}
                  aria-label={t("coder.weightDec")}
                  disabled={avWeight(selected) === 0}
                  onClick={() => updateCodingWeight(selected, avWeight(selected) - 1)}
                />
                <span className="min-w-5 text-center text-xs text-text-secondary" aria-label={t("coder.weight")}>
                  {avWeight(selected)}
                </span>
                <Button
                  variant="toolbarIcon"
                  icon={<Plus size={12} aria-hidden />}
                  title={t("coder.weightInc")}
                  aria-label={t("coder.weightInc")}
                  disabled={avWeight(selected) >= 100}
                  onClick={() => updateCodingWeight(selected, avWeight(selected) + 1)}
                />
              </span>
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
            </>
          )}
          {!selected && selectedText && (
            <>
              <span
                className="h-3 w-3 shrink-0 rounded-sm border border-border"
                style={{ backgroundColor: colorByCid.get(selectedText.cid) ?? FALLBACK_CODE_COLOR }}
                aria-hidden
              />
              <span className="truncate text-sm font-medium text-text-primary" title={selectedText.date}>
                {nameByCid.get(selectedText.cid) ?? t("coder.fallbackCode", { id: selectedText.cid })}
              </span>
              {selectedText.seltext && (
                <span
                  className="max-w-56 truncate text-xs text-text-secondary"
                  title={selectedText.seltext}
                >
                  {selectedText.seltext}
                </span>
              )}
              {memoDraft != null ? (
                <div className="flex items-center gap-1">
                  <Input
                    value={memoDraft}
                    placeholder={t("pdfCoder.memoPlaceholder")}
                    aria-label={t("pdfCoder.memoPlaceholder")}
                    className="w-48"
                    onChange={(e) => setMemoDraft(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") void saveTranscriptMemo();
                    }}
                  />
                  <Button
                    variant="toolbarIconPrimary"
                    icon={<Check size={12} aria-hidden />}
                    title={t("common.save")}
                    aria-label={t("common.save")}
                    onClick={() => void saveTranscriptMemo()}
                  />
                  <Button
                    variant="toolbarIcon"
                    icon={<X size={12} aria-hidden />}
                    title={t("common.cancel")}
                    aria-label={t("common.cancel")}
                    onClick={() => setMemoDraft(null)}
                  />
                </div>
              ) : (
                <button
                  type="button"
                  onClick={startEditTranscriptMemo}
                  title={t("pdfCoder.editMemo")}
                  className="flex min-w-0 max-w-64 items-center gap-1 text-left text-xs text-text-secondary hover:text-text-primary"
                >
                  {selectedText.memo ? (
                    <span className="truncate">{selectedText.memo}</span>
                  ) : (
                    <span className="italic">{t("coder.noMemoInline")}</span>
                  )}
                  <Pencil size={10} aria-hidden />
                </button>
              )}
              <span className="flex items-center gap-1">
                <span className="text-xs text-text-secondary">{t("coder.weight")}</span>
                <Button
                  variant="toolbarIcon"
                  icon={<Minus size={12} aria-hidden />}
                  title={t("coder.weightDec")}
                  aria-label={t("coder.weightDec")}
                  disabled={avWeight(selectedText) === 0}
                  onClick={() => updateTranscriptWeight(selectedText, avWeight(selectedText) - 1)}
                />
                <span className="min-w-5 text-center text-xs text-text-secondary" aria-label={t("coder.weight")}>
                  {avWeight(selectedText)}
                </span>
                <Button
                  variant="toolbarIcon"
                  icon={<Plus size={12} aria-hidden />}
                  title={t("coder.weightInc")}
                  aria-label={t("coder.weightInc")}
                  disabled={avWeight(selectedText) >= 100}
                  onClick={() => updateTranscriptWeight(selectedText, avWeight(selectedText) + 1)}
                />
              </span>
              <IconButton
                label={t("pdfCoder.importantToggle")}
                title={t("pdfCoder.importantToggle")}
                size="sm"
                className={cn(selectedText.important !== 0 && "text-warning")}
                onClick={toggleTranscriptImportant}
              >
                <Star
                  size={14}
                  className={selectedText.important !== 0 ? "fill-current" : ""}
                  aria-hidden
                />
              </IconButton>
              <div className="flex-1" />
              <Button
                variant="danger"
                icon={<Trash2 size={12} aria-hidden />}
                onClick={() => void handleTranscriptDelete(selectedText)}
              >
                {t("common.delete")}
              </Button>
              <Button
                variant="secondary"
                onClick={() => {
                  setSelectedText(null);
                  setMemoDraft(null);
                }}
              >
                {t("common.close")}
              </Button>
            </>
          )}
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
