# Graphs — graph editor and models

The code-map editor (upstream view_graph / graph models): an SVG canvas with
draggable nodes, relation lines with labels and arrow styles, and six
analytical model generators. Lives under the Analysis area ("Graphs" entry in
the reports left bar).

## How to reach it

Ribbon → Reports → Graphs (left bar entry). The center becomes the graph
editor; the right bar becomes the graph inspector.

## Layout slots used

- Center: `GraphsView` — menu bar (the only view using the `menuBar`-style
  toolbar, rendered as the first row of the center) + SVG canvas.
- Left bar: the standard `Sidebar` (file groups) — the graph list moved into
  the center toolbar.
- Right bar: `GraphsInspector` (LeftBar borderSide="l") — node/line details.

## Features

- **Graph toolbar**: graph `<select>` (all graphs), Add (name dialog),
  Delete (confirm dialog), spacer, Models (generator dialog), zoom in/out +
  percentage, and Connect (link mode).
- **Canvas**: pan by dragging the background; zoom via wheel or buttons
  (25–250 %); dotted grid background matching the graph's scene size.
- **Nodes**: categories, codes, cases, files, free text and memos — each a
  colored rounded rect with label, font size, bold flag. Drag to move
  (positions save automatically on mouseup). Double-click the canvas opens a
  context menu to add a node (each kind opens a picker dialog; free text
  takes a text input).
- **Lines**: relation lines between nodes with color, width, dashed/solid,
  arrow mode (solid/dotted × with/without arrow), and an optional label
  rendered mid-line. Created via Connect mode (select a node → link button →
  click a second node).
- **Node details (right bar)**: label (inline edit on blur), Bold toggle,
  Font +, Delete.
- **Line details (right bar)**: relation label edit, arrow-mode select,
  Delete.
- **Models dialog**: generate a graph from the six models
  (`GRAPH_MODELS`): category hierarchy, code hierarchy, file hierarchy,
  file comparison, case hierarchy, case comparison — with a graph name and
  optional comma-separated file/case id lists.
- Errors surface in an ErrorBanner or the inspector footer.

## API endpoints used

- `GET /graphs`, `POST /graphs`, `GET /graphs/{grid}`, `PATCH /graphs/{grid}`,
  `DELETE /graphs/{grid}`
- `POST /graphs/{grid}/items/cdct|case|file|free|memo`, PATCH/DELETE per item
- `POST /graphs/{grid}/lines/cdct`, `POST /graphs/{grid}/lines/entity`,
  PATCH/DELETE per line
- `POST /graphs/models` (model generation)

## Screenshot:

(to be inserted)
