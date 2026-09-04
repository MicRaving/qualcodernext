"""Source file path resolution and thumbnails for the sources API."""

from __future__ import annotations

import asyncio
from io import BytesIO
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from qualcoder_api.core.enums import MediaType

_INTERNAL_FOLDERS = {
    "/docs/": "documents",
    "/images/": "images",
    "/audio/": "audio",
    "/video/": "video",
}

_EXTERNAL_PREFIXES = ("docs:", "images:", "audio:", "video:")

_CONTENT_TYPES = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".m4a": "audio/mp4",
    ".ogg": "audio/ogg",
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".mkv": "video/x-matroska",
    ".mov": "video/quicktime",
    ".wmv": "video/x-ms-wmv",
    ".txt": "text/plain",
}


def resolve_source_path(project_path: str, mediapath: str | None, name: str) -> str | None:
    """Resolve a source's mediapath to an absolute file path on disk.

    Internal prefixes map to project subfolders: /docs/ -> documents,
    /images/ -> images, /audio/ -> audio, /video/ -> video.
    External link prefixes (docs:, images:, audio:, video:) resolve to the
    path after the colon in local (desktop) mode only — server mode never
    serves arbitrary filesystem paths (see plan invariant #5).
    Returns None when the path cannot be resolved safely.
    """
    if not mediapath:
        return None
    for prefix, folder in _INTERNAL_FOLDERS.items():
        if mediapath.startswith(prefix):
            basename = Path(mediapath).name
            if basename in ("", ".", ".."):
                return None
            project_root = Path(project_path).resolve()
            candidate = (project_root / folder / basename).resolve()
            try:
                if candidate.is_relative_to(project_root):
                    return str(candidate)
            except ValueError:
                return None
            return None
    if mediapath.startswith(_EXTERNAL_PREFIXES):
        from qualcoder_api.core.server_config import is_server_mode

        if is_server_mode():
            return None
        return mediapath.split(":", 1)[1]
    return None


def is_path_under_project(project_path: str, path: str | None) -> bool:
    """True when an already-resolved path stays inside the project folder."""
    if not path:
        return False
    try:
        root = Path(project_path).resolve()
        candidate = Path(path).resolve()
        return candidate == root or candidate.is_relative_to(root)
    except (OSError, ValueError):
        return False


def content_type_for(filename: str) -> str:
    """Map a filename to a content type by its lowercase extension."""
    return _CONTENT_TYPES.get(Path(filename).suffix.lower(), "application/octet-stream")


def _thumbnail_image(path: str, max_size: int) -> bytes | None:
    try:
        with Image.open(path) as img:
            img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
            rgb = img.convert("RGB")
            buf = BytesIO()
            rgb.save(buf, format="PNG")
            return buf.getvalue()
    except (UnidentifiedImageError, OSError, ValueError):
        return None


def _thumbnail_pdf(path: str, max_size: int) -> bytes | None:
    try:
        import fitz

        with fitz.open(path) as doc:
            page = doc[0]
            longest = max(page.rect.width, page.rect.height)
            zoom = max_size / longest
            pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
            return pix.tobytes("png")
    except Exception:
        return None


async def build_thumbnail(
    path: str, media_type: MediaType, filename: str, max_size: int
) -> bytes | None:
    """Build a PNG thumbnail for a source file; None when unsupported."""
    if media_type == MediaType.IMAGE:
        return await asyncio.to_thread(_thumbnail_image, path, max_size)
    if media_type == MediaType.TEXT and filename.lower().endswith(".pdf"):
        return await asyncio.to_thread(_thumbnail_pdf, path, max_size)
    return None
