# Audio/Video coder

Playback with time-range coding on a timeline, plus a transcript panel with
full text-coder functions, automatic and manual transcription, and speaker
detection/marking.

## How to reach it

Files table → click an audio or video source. Segments are stored in
milliseconds (`pos0/pos1`).

## Layout slots used

- Center: `AvCoder` — wrapping `ViewHeader` (file name + memo + controls),
  media element, transport row, timeline, and the transcript panel.
- Left bar: Sidebar code tree; clicking a code completes the pending range
  or transcript selection (`qc:assign-code`).
- Right bar: Inspector.

## Features

- **Media playback**: video element (resizable height via a draggable
  divider, hide/show via the Video toggle) or audio placeholder (icon +
  name + duration); transport row: play/pause button, current time / total,
  playback-speed selector (0.5×–2×), and a clickable timeline.
- **Timeline coding**: Set start → (play/seek) → "Set end and code" (the
  same button becomes primary and shows the start time; a small X clears
  the start mark). With an active sidebar code the range is coded
  immediately, otherwise the CodePicker opens. Coded ranges render as
  code-colored blocks on the timeline (click to seek + select).
- **Keyboard/media keys**: Space toggles play/pause (not while typing in
  inputs/buttons), F9 and Ctrl+Space work even inside the transcript
  textarea, OS media keys (Play/Pause toggle, Previous/Next = ±10 s) via the
  Media Session API; playback state mirrors to the OS.
- **Transcript panel**: shows the auto-generated transcript as `[mm:ss]`
  lines; the active line scrolls into view and highlights during playback;
  clicking a line seeks to it. The transcript is a full text-coder surface:
  select text → floating toolbar with Code (codes the transcript file),
  Annotate, Copy segment link, Paste link here; coded text is highlighted
  in place (CRLF-aware positions). Autocode button (on the transcript).
- **Auto transcription**: "Transcribe" button opens `TranscribeDialog`
  (model, language, translate, VAD, beam size, timestamps, segment coding
  with a target code). The job runs in the background queue; while it runs
  the transcript panel live-previews the partial `[mm:ss] text` output; when
  it finishes the panel auto-opens with the new transcript.
- **Manual transcription mode**: "Transcribe mode" turns the transcript into
  an editable draft; Enter (or the clock button) inserts `[mm:ss]` at the
  caret for the current playback position; Ctrl/Cmd+S saves via
  `commit-edit` (which re-anchors codings/annotations; timeline codings are
  unaffected); Space/F9/media keys keep working while typing.
- **Speaker detection/marking** (inside TranscribeDialog): detect speaker
  turns from transcript identifiers (name / hash / @-mention / [brackets] /
  {braces} / custom regex), review detected speakers with turn counts and
  examples, select which to keep, then mark turns → codes speakers by
  creating speaker codes and coding each turn.
- **Bookmarks**: AV bookmark at the current position; go-to seeks (or opens
  the bookmarked file).
- **Segment details panel**: code, time range, memo, Delete (confirm).
- **Hidden codes**: timeline blocks of hidden codes are dimmed.

## API endpoints used

- `GET /sources/{id}`, `GET /sources/{id}/file` (media bytes)
- `GET /codings/av/{source_id}`, `POST /codings/av`,
  `DELETE /codings/av/{avid}`
- `GET /codings/text/{fid}` (transcript), `POST /codings/text`,
  `POST /annotations`, `POST /codings/autocode`
- `GET/PUT /bookmarks/av` (AV bookmark), `GET/PUT /bookmarks` (shared state)
- `GET /transcribe/status`, `POST /transcribe`, `GET /transcribe/jobs/{id}`
  (live transcript polling)
- `POST /tools/speakers/detect`, `POST /tools/speakers/mark`
- `POST /codings/commit-edit` (manual transcription save)
- `POST /links` + `GET /links` (transcript segment links)

## Screenshot:

(to be inserted)
