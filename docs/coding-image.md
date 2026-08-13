# Image coder

View an image and create rectangular code regions on it.

## How to reach it

Files table → click an image source (`media_type == "image"`).

## Layout slots used

- Center: `ImageCoder` — `ViewHeader` (file name + "drag to mark" hint) +
  zoom toolbar + scrollable canvas.
- Left bar: Sidebar code tree; clicking a code assigns the pending
  rectangle (`qc:assign-code`).
- Right bar: Inspector.

## Features

- **Region coding**: drag a rectangle over the image (crosshair cursor); a
  live preview rect shows while dragging. Region coordinates are stored in
  image pixel space (`x1/y1/width/height` relative to the natural size).
  With an active sidebar code the region is created immediately; otherwise
  the CodePicker opens (search + create-new-code).
- **Coded regions**: colored overlays (code tint + code-color border),
  clickable; hidden codes are dimmed (`qc-seg-hidden`).
- **Zoom**: zoom out / zoom in buttons (10–300 %, step 10 %) with a live
  percentage readout, and Fit (scales to the container width on load too).
- **Details panel** (after selecting a region): code color swatch, code
  name, memo · size in px, Edit region (prompt for `x1,y1,width,height`),
  Delete (confirm), Close.
- **Save overlay**: a spinner overlay while a region coding is being saved.
- **Error states**: load error with Retry; image load error banner.

## API endpoints used

- `GET /sources/{id}`, `GET /sources/{id}/file` (image bytes)
- `GET /codings/image/{source_id}`, `POST /codings/image`,
  `PATCH /codings/image/{imid}`, `DELETE /codings/image/{imid}`
- `GET /codes` (flat)

## Screenshot:

(to be inserted)
