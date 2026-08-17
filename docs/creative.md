# Creative — the creative coding scratchpad

A MAXQDA-style **creative coding** panel that opens in the right bar: collect
ideas, quotes and fragments as you read, edit them inline, and **promote** an
item into a real code (coding the referenced source passage when the item
carries one). It is the place for half-formed thoughts that aren't codes yet.

## How to reach it

- Ribbon → **Creative** (lightbulb icon, right side). Toggles the right-bar
  pane; the center view stays whatever it showed.

## Features

- **Add item**: a textarea + Add button (Enter to submit). Items are
  free-form ideas, quotes or fragments.
- **Item list**: each item shows its text and an optional note. Items created
  with a source reference show a **source chip** (source name + quoted
  excerpt); clicking it jumps to the source file in the coder.
- **Inline edit**: pencil button (or click the item) swaps the row into a
  text + note editor with Save/Cancel.
- **Delete**: trash button per row.
- **Search**: filters items by text, note and source name.

### Promote to code

The lightbulb button per row opens the **promote dialog**:

- Shows the item (and its source reference when present).
- A **code-name** input (pre-filled from short items) and an optional **parent
  category**.
- Promoting creates the new code — and when the item is sourced, additionally
  **codes the referenced span** with the new code. The project refreshes
  afterwards.

## High-level logic

Creative items are lightweight records with an optional source-span
attachment. Promoting converts a record into the durable project structures
(a code row, and — when sourced — a coding), so the scratchpad is the
"incubator" in front of the codebook rather than a parallel data store.
