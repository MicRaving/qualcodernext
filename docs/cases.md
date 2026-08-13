# Cases — cases and attributes

Manage study cases, their attributes (with value labels), and the files
linked to each case.

## How to reach it

Ribbon → Cases. The workspace splits into the shell's left bar (`CasesList`)
and the center (`CaseDetails`), sharing the selection via the project store.

## Layout slots used

- Left bar: `CasesList` (w-72) — search field + per-case rows.
- Center: `CaseDetails` — case name header, memo, properties, member files.
- Right bar: Inspector (default, unchanged).

## Features

- **Case list**: search box (matches name and memo); rows show name + date;
  selected row highlighted; inline rename (pencil icon or context menu,
  Tab moves the editor to the next row).
- **Add case**: header button creates an untitled case, selects it and opens
  its name editor immediately.
- **Row context menu** (right-click): Details / Rename / Delete (confirm).
- **Case details** (center):
  - Header: case name + created-by meta (date · owner).
  - **Memo**: textarea + Save (disabled until dirty).
  - **Properties**: the shared `AttributeEditor` for case-scoped attribute
    values — add/edit/remove attribute values; attribute names, types and
    value labels are defined via `GET/POST /attributes/types` and value
    labels map raw values to display labels (labels also surface in the
    Attributes report).
  - **Member files**: list of linked files with an unlink button per row.
  - **Link files**: dropdown of not-yet-linked sources + Link button; a hint
    appears when everything is linked.
- Cross-linking also possible from the Files screen (row context menu →
  Assign to case).

## API endpoints used

- `GET /cases`, `POST /cases`, `PATCH /cases/{caseid}`, `DELETE /cases/{caseid}`
- `GET /cases/{caseid}/files`, `POST /cases/{caseid}/files` (link),
  `DELETE /cases/{caseid}/files/{fid}` (unlink)
- `GET /attributes/types`, `POST /attributes/types`,
  `DELETE /attributes/types/{name}`, `GET /attributes/values`,
  `PUT /attributes/values/{name}`

## Screenshot:

(to be inserted)
