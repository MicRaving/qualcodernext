# PDF coder

PDF coding workspace: pdf.js page rendering, rectangle region selection with
the shared CodePicker, per-page coded overlays with an inline details/delete
panel, and a plain-text mode side by side.

## How to reach it

Files table → click a PDF (a `media_type == "text"` source whose name ends
in `.pdf`). The `PdfCoder` is lazy-loaded (pdfjs-dist worker).

## Layout slots used

- Center: `PdfCoder` — wrapping `ViewHeader` + split area (PDF canvas pane
  and/or plain-text pane).
- Left bar: Sidebar code tree; clicking a code assigns it to the pending
  drag (`qc:assign-code`).
- Right bar: Inspector.

## Features

- **PDF rendering**: pdf.js canvas pages, continuous-scroll or single-page
  mode (single page shows prev/next + page-number input).
- **Zoom**: Fit width + 50% / 75% / 100% / 150% buttons; fit re-measures on
  container resize.
- **Two coding gestures** (drag on a page):
  - *Region coding*: drag a rectangle anywhere (min 5 px); a preview rect
    shows while dragging; the rect is stored in PDF units per page and
    rendered as a colored overlay (code tint + border). With an active
    sidebar code the coding is created immediately, otherwise the CodePicker
    opens.
  - *Text coding*: drags that start on a pdf.js text item select the covered
    text items; the extracted text is located in the backend plain text
    (`POST /sources/{id}/pdf-text-locate`) and stored as a regular text
    coding — shared with the plain-text pane and shown as per-item overlays
    on the rendered pages (best-effort word matching).
- **Per-page overlays**: clickable; the details panel shows code swatch +
    name + memo + "page · date", with Edit region (prompt for
    x1,y1,width,height) and Delete (confirm).
- **Plain text / PDF split**: "Plain text" and "PDF view" toggles (never both
  off); with both on, a draggable divider resizes the text pane. The plain
  text pane is a bare `TextCoder` (controlled mode — codings/annotations/
  codes shared with the PDF pane, so highlights stay in sync both ways).
  "Rendered mode" button returns from PDF plain text to the rendered view.
- **Hidden codes**: overlays of hidden codes are dimmed (`qc-seg-hidden`).
- **Autocode**: opens the shared `AutocodeDialog`; done → refresh text +
  region codings and codes.
- **CodePicker**: search + create-new-code support for pending actions.
- **Escape**: cancels drag/pending rect/selection/picker.

## API endpoints used

- `GET /sources/{id}`, `GET /sources/{id}/file` (PDF bytes)
- `GET /codings/image/{source_id}`, `POST /codings/image`,
  `PATCH /codings/image/{imid}`, `DELETE /codings/image/{imid}`
- `GET /codings/text/{fid}`, `POST /codings/text`, `GET /annotations/{fid}`
- `GET /codes` (flat), `POST /codings/autocode`
- `POST /sources/{id}/pdf-text-locate`

## Screenshot:

(to be inserted)
