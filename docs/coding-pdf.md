# PDF Coder — code PDF pages and extracted text

The PDF coder lets you work with PDF documents in two complementary ways: draw
**rectangle regions** directly on the rendered pages, and code the PDF's
**extracted plain text** side by side. Both views stay in sync.

![PDF coder](screenshots/05-coder-pdf.png)

## How to reach it

- File manager → click a file ending in `.pdf`. The PDF viewer is loaded
  on demand (it is the app's largest optional component).

## The layout on this screen

- **Center**: the PDF canvas pane and/or a plain-text pane, split by a
  draggable divider.
- **Left bar**: the code tree; clicking a code assigns it to a pending drag.
- **Right bar**: the Inspector.

## Features

### Rendering and navigation

- Pages render as crisp canvas images (pdf.js). Continuous scrolling is the
  default; a **single-page mode** shows prev/next buttons and a page-number
  input.
- **Zoom**: Fit-width plus 50 % / 75 % / 100 % / 150 %; fit re-measures when
  the window resizes.

### Region coding (on the rendered page)

- **Drag a rectangle** anywhere on a page (minimum 5 px). A live preview rect
  shows while dragging. With an active sidebar code the region is coded
  immediately; otherwise the CodePicker opens (search + create-new code).
- Regions are stored in **PDF coordinates per page** and render as colored
  overlays (code tint + border). Clicking a region shows its details panel:
  code swatch + name + memo · "page · date", plus **Edit region** (prompt for
  `x1,y1,width,height`) and **Delete** (confirm).

### Text coding (on the page or in the plain-text pane)

- Drags that start **on a pdf.js text item** select the covered text; QCnext
  locates that text in the backend-extracted full text (with a multi-level
  fallback for ligatures, soft hyphens and line breaks) and stores a **regular
  text coding** — identical to one made in the plain-text pane.
- Both ways, the coding appears in **both** panes.

### Plain text / PDF split

- **Plain text** and **PDF view** toggles (never both off).
- With both on, a draggable divider resizes the text pane. The plain-text pane
  is a full text coder in controlled mode — codings, annotations and codes are
  shared with the PDF pane, so highlights stay in sync both ways.
- **Rendered mode** returns from the plain-text view to the rendered pages.

### More

- **Hidden codes**: overlays of hidden codes are dimmed.
- **Autocode**: opens the shared autocode dialog (see
  [coding-text.md](coding-text.md)); after it finishes the text and region
  codings and the code tree refresh.
- **CodePicker** supports search + create-new-code for pending actions.
- **Escape** cancels a drag, pending rect, selection or picker.

## High-level logic

- PDF text is extracted once on the backend. Rendering and text selection
  happen in the browser; a selection is translated back to character offsets in
  the extracted text via a **confidence-ranked matching chain** (exact →
  normalized → word-sequence → anchor → fuzzy). "Exact" matches are
  unambiguous; lower-confidence matches are still usable.
- Region codings live in their own coordinate space (page + rectangle); text
  codings use character offsets — which is why the two panes can share text
  codings while the page overlays add the geometry.
