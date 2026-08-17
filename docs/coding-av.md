# Audio / Video Coder — timeline coding, transcripts, transcription, speakers

The audio/video coder plays media, codes **time ranges** on a timeline, shows
the transcript (automatic or manual) as a full text-coder surface, and provides
automatic and manual transcription plus speaker detection.

![Audio/video coder](screenshots/08-coder-av.png)

## How to reach it

- File manager → click an audio or video file. Segments are stored in
  **milliseconds** (`pos0`/`pos1`).

## The layout on this screen

- **Center**: media element, transport row, a clickable timeline, and the
  transcript panel.
- **Left bar**: the code tree; clicking a code completes a pending range or
  transcript selection.
- **Right bar**: the Inspector.

## Features

### Playback

- Video shows in a resizeable pane (hide/show via the **Video** toggle, drag
  the divider to resize); audio shows a placeholder (icon + name + duration).
- Transport row: **play/pause**, current time / total, a **playback-speed**
  selector (0.5×–2×), and the clickable timeline.
- **Keyboard/media keys**: Space toggles play/pause (not while typing), F9 and
  Ctrl+Space work even inside the transcript editor, and OS media keys
  (Play/Pause, Previous/Next = ±10 s) work via the Media Session API.

### Timeline coding

1. **Set start** (the button becomes primary and shows the start time; a small
   X clears it).
2. **Play / seek**, then **Set end and code**.
3. With an active sidebar code the range is coded immediately; otherwise the
   CodePicker opens.

Coded ranges render as code-colored **blocks on the timeline**; clicking one
seeks and selects it. The details panel shows code, time range, memo, and
Delete. Blocks of hidden codes are dimmed.

### The transcript panel

- Shows the transcript as `[mm:ss] text` lines. During playback the **active
  line scrolls into view and highlights**; clicking a line seeks to it.
- The transcript is a **full text-coder surface**: select text → floating
  toolbar with Code / Annotate / Copy & Paste segment link / Send to QTT;
  coded text is highlighted in place.
- The **Autocode** button runs the shared autocode dialog on the transcript.

### Automatic transcription

The **Transcribe** button opens the transcription dialog:

- **Model, language, translate, VAD, beam size, timestamps**, and optional
  **segment coding** (code each detected segment with a target code).
- The job runs in the **background queue** (see
  [status-and-tasks.md](status-and-tasks.md)). While it runs, the transcript
  panel **live-previews** partial `[mm:ss] text` output; on completion the
  panel auto-opens with the new transcript.

### Manual transcription mode

For audio you transcribe yourself:

- **Transcribe mode** turns the transcript into an editable draft.
- **Enter** (or the clock button) inserts `[mm:ss]` at the caret for the
  current playback position.
- **Ctrl/Cmd+S** saves; codings and annotations are re-anchored (timeline
  codings are unaffected). Space/F9/media keys keep working while typing.

### Speaker detection & marking

Inside the transcription dialog: **detect speaker turns** from transcript
identifiers (name / hash / @-mention / `[brackets]` / `{braces}` / a custom
regex), review the detected speakers with turn counts and examples, select
which to keep, then **mark turns** — QCnext creates a speaker code per speaker
and codes each turn. This gives you speaker-level analysis without manual work.

### Bookmarks

- AV bookmark at the current position; go-to seeks (or opens the bookmarked
  file).

## High-level logic

- **Media** is streamed from the project folder; transcript text is stored as a
  companion text source linked to the AV file, so it can be coded with the
  ordinary text-coder machinery.
- **Transcription jobs** run as background processes (Whisper-based); results
  are persisted to sidecar files and finalized exactly once even if the app is
  closed mid-run (finished transcripts are swept back in on the next open).
- Timeline codings and transcript codings are separate data: timeline =
  milliseconds; transcript = character offsets.
