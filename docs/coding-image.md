# Image Coder — code rectangular regions of images

View an image and mark meaningful regions with codes — e.g. the area of a
photo that shows a particular activity, or a diagram element.

![Image coder](screenshots/06-coder-image.png)

## How to reach it

- File manager → click an image file (PNG, JPG, GIF, WebP, …).

## The layout on this screen

- **Center**: the image with a zoom toolbar and a scrollable canvas.
- **Left bar**: the code tree; clicking a code assigns it to a pending
  rectangle.
- **Right bar**: the Inspector.

## Features

### Region coding

- **Drag a rectangle** over the image (crosshair cursor); a live preview rect
  shows while dragging. With an active sidebar code the region is created
  immediately; otherwise the CodePicker opens (search + create-new code).
- Region coordinates are stored in **image pixel space** (`x1/y1/width/height`
  relative to the natural image size), so the region stays anchored no matter
  how you zoom or scroll.

### Coded regions

- Colored overlays (code tint + a border in the code's color). Clicking a
  region opens its **details panel**: code swatch, code name, memo · size in
  px, **Edit region** (prompt for `x1,y1,width,height`), **Delete** (confirm),
  Close.
- Regions of hidden codes are dimmed.

### Zoom

- Zoom out / zoom in buttons (10–300 %, step 10 %) with a live percentage
  readout, and **Fit** (scales to the container width — also applied on load).

### States

- Loading spinner while a region coding is being saved.
- Load-error state with a **Retry** button; image-load error banner.

## High-level logic

Regions are rectangles in pixel coordinates, stored per source. This is the
same model used for PDF page regions (which add a page number). Because the
coordinates are relative to the image's natural size, the same coding renders
correctly at any zoom level.
