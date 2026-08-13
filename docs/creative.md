# Creative — creative coding panel

A MAXQDA-style creative coding scratchpad as a right-bar pane: collect
ideas, quotes and fragments, edit them inline, and promote an item into a
new code (coding the referenced source span when the item carries one).

## How to reach it

Ribbon → Creative (lightbulb icon, right side). Toggles the right-bar pane;
the center view stays whatever it showed.

## Layout slots used

- Right bar only: `CreativePanel` (LeftBar `borderSide="l"`), BarHeader +
  add-note textarea + search box + item list.
- Center/left bar: unchanged (the pane overlays the Inspector slot).

## Features

- **Add item**: textarea + Add button (Enter to submit); items are free-form
  ideas, quotes or fragments.
- **Item list**: each item shows its text and an optional note; sourced items
  (created with a source reference) show a source chip with the source name
  and quoted excerpt — clicking it jumps to the source file in the coder.
- **Inline edit**: pencil button (or click the item) swaps the row into a
  text + note editor with Save/Cancel.
- **Delete**: trash button per row.
- **Search**: filters items by text, note and source name.
- **Promote to code** (lightbulb button per row): dialog showing the item
  (and its source reference when present) with a code-name input (pre-filled
  from short items) and an optional parent category; promoting creates the
  new code — and when the item is sourced, additionally codes the referenced
  span with the new code. The project refreshes afterwards.

## API endpoints used

- `GET /creative`, `POST /creative`, `PATCH /creative/{item_id}`,
  `DELETE /creative/{item_id}`, `POST /creative/{item_id}/promote`

## Screenshot:

(to be inserted)
