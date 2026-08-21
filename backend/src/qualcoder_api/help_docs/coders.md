# Coding Files

[← Back to Documentation Hub](README.md)

QCnext features six specialized coding environments tailored to different media types: Plain Text, PDF documents, Images, CSV/Spreadsheet tables, Webpages, and Audio/Video media. 



The left sidebar manages codes and categories. Right-click any code to rename, edit memo, merge into another code, or delete. You can also organize codes in categories and promote/demote them in the right-click menu. Codes can be rearranged via drag and drop. You can also assign custom palette colors to codes. Clicking a code swatch toggles visibility of its highlights in the active coder.



Click **Autocode** in any coder to open the dialog and code via AI Autocode using natural language or Dictionaries using word list dictionaries to automatically code target terms across documents.



Across all text-based coders (Text, PDF, CSV, Webpage, AV Transcripts), selecting content triggers the floating **Selection Toolbar**:

!\[Text Coder](screenshots/coder.jpg)



Toolbar Actions

* **🏷️ Code**: Immediately codes the selection with the currently **active code** (selected in the left sidebar code tree). If no code is active, opens the Code Picker.
* **✨ Code as new code**: Creates a brand-new code using the selected text string as its name and codes the passage immediately.
* **💬 Annotate**: Opens a popover to attach a text note directly to the passage without assigning a code.
* **📥 Send to Crafter**: Sends the selected quote directly to a Crafter worksheet as an analytical segment item.

### Highlighting \& Overlaps

* Coded passages are highlighted in the color assigned to the code.
* When multiple codes overlap on the same text, their colors stack.
* Hovering over a coded segment displays a tooltip with code names and memos; clicking opens the **Segment Details Inspector**.

\---

## Text Coder

The **Text Coder** is the primary workspace for interview transcripts, field notes, survey text, and imported documents (`.txt`, `.md`, `.docx`).

* **Document Reading \& Highlights**: Rendered text displays code highlights, annotation underlines (dashed), and outgoing segment links (wavy underline).
* **Live Document Editing**: Toggle **Edit mode** to correct transcription typos directly inside the coder:

  * Text shifts are automatically tracked and debounced.
  * Upon saving (`Ctrl/Cmd+S`), all character offsets for existing codings and annotations are re-anchored instantly.
* **Code Tree Integration**: Single-clicking a code in the left bar sets it as active; double-clicking opens its Inspector details.

\---

## PDF Coder

The **PDF Coder** combines visual page region drawing with extracted plain-text coding in a dual-pane environment.

* **PDF**: Shows the PDF view with continuous scrolling or single-page view.
* **Plain text**: Display extracted plain text; PDF and Plain text can be shown in split view.
* **Coding**: You can code either text or rectangular regions anywhere on a PDF page to code charts, diagrams, formulas, or non-extractable text. Coordinates are stored in vector page relative space.

\---

## Image Coder

The **Image Coder** allows researchers to mark and code graphic material (`.png`, `.jpg`, `.webp`, `.svg`). Click and drag over photos, diagrams, or scans to mark rectangular regions.

\---

## CSV / Table Coder

The **CSV / Table Coder** provides cell-level text coding for survey data, tabular datasets, and social media exports.

* **Cell-Level Character Coding**: Code specific words or phrases *inside* individual cells rather than marking entire table rows.
* **Plain Text Fallback**: Toggle to view the raw tabular document in the standard text coder if preferred.

\---

## Webpage Coder

The **Webpage Coder** handles HTML page captures and web articles imported via URL.

* **Split View Layout**: Displays the raw rendered HTML snapshot alongside clean extracted article text, similar to PDFs.
* **Coding**: Select text on the rendered webpage to code it directly like in other text modes.

\---

## Audio / Video Coder \& Transcripts

The **Audio / Video Coder** integrates media playback, timeline range coding, transcript synchronization, Whisper automated transcription, and speaker detection.

### Playback \& Timeline Coding

* **Transport Row**: Play/pause, playback speed selector (0.5× to 2.0×), and a clickable timeline.
* **Keyboard \& Media Keys**: `Space` toggles play/pause, `F9` inserts timestamps, and hardware media keys control playback.
* **Timeline Range Coding**:

  1. Click **Set start** at the desired playback timestamp.
  2. Play or seek to the end timestamp.
  3. Click **Set end and code** to code the millisecond interval (`pos0` to `pos1`).
  4. Coded ranges appear as interactive colored blocks on the media timeline.

### Transcribe

* Click **Transcribe** to launch background transcription powered by Whisper models.
* **Options**: Model size, language selection, translation to English, Voice Activity Detection (VAD), and automatic turn coding.
* **Live Preview**: Progress streams live into the transcript pane as `\[mm:ss] text` while transcription runs in the background queue.

### Manual Transcription \& Speaker Detection

* **Manual Mode**: Turn on **Transcribe mode** to type transcripts manually. Pressing `Enter` or `F9` auto-inserts timestamp markers `\[mm:ss]`.
* **Speaker Detection**: Automatically detect speaker turns from transcript identifiers (e.g., `Speaker 1:`, `\[Alice]`, `{@Bob}`) or custom regex patterns. QCnext automatically generates speaker codes and codes every turn across the transcript.

\---

[← Back to Documentation Hub](README.md)

