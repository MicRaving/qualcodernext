# Graphs — the code-map editor and model generators

The Graphs workspace is a visual map of your analysis: an SVG canvas with
draggable nodes (categories, codes, cases, files, free text, memos), relation
lines with labels and arrow styles, and **six analytical model generators**
that build a graph from your data automatically.

It lives under the Analysis area: Ribbon → **Reports** → **Graphs** (left-bar
entry).

## The layout on this screen

- **Center**: the graph toolbar + the SVG canvas.
- **Left bar**: the standard file-groups sidebar (the graph list moved into
  the center toolbar).
- **Right bar**: the **graph inspector** — node/line details.

## The toolbar

- **Graph `<select>`**: all graphs in the project; **Add** (name dialog) and
  **Delete** (confirm dialog).
- **Models** (the generator dialog — see below).
- **Zoom in/out + percentage** and **Connect** (link mode).

## The canvas

- **Pan** by dragging the background; **zoom** via the wheel or buttons
  (25–250 %); a dotted grid matches the graph's scene size.
- **Double-click** the canvas opens a context menu to add a node — each kind
  (category, code, case, file, free text, memo) opens its picker dialog; free
  text takes a text input.

## Nodes and lines

- **Nodes** are colored rounded rectangles with a label; font size and bold
  are per-node. **Drag to move** — positions save automatically on mouseup.
- **Lines** connect nodes with color, width, dashed/solid, arrow mode
  (solid/dotted × with/without arrow) and an optional mid-line label. Create
  them in **Connect mode**: select a node → link button → click a second node.
- The **right-bar inspector** edits the selection:
  - Node: label (inline, saves on blur), Bold toggle, Font +, Delete.
  - Line: relation label, arrow-mode select, Delete.
- Errors surface in an error banner or the inspector footer.

## The Models dialog

Generate a graph from one of six analytical models (`GRAPH_MODELS`):

| Model | What it produces |
|---|---|
| Category hierarchy | Categories and codes as a tree |
| File hierarchy | Files with the cases/codes beneath them |
| File comparison | Files and the codes they use |
| Case hierarchy | Cases with their files/codes |
| Case comparison | Cases and the codes used in their files |
| Co-occurrence network | Codes as nodes connected when they co-occur |

Each generator takes a graph name and optional file/case id lists (comma
separated) to restrict the map.

## High-level logic

Graphs are stored as data (nodes and lines referencing real project entities),
not as rendered pictures — so a code node still points at its code, and the
Inspector can show details. The model generators query the same coding data as
the reports and lay the results out automatically; you then refine positions,
labels and styling by hand.
