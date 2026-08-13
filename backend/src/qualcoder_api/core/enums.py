"""Domain enums for the QualCoder v4 backend. No Qt, no I/O."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

#: Single source of truth for the extension → media-kind map. Both the
#: import pipeline (``detect_media_type``) and the API models
#: (``MediaType.from_mediapath``) classify by these sets, so the two can
#: never disagree.
DOCUMENT_EXTENSIONS = (
    ".txt", ".md", ".odt", ".rtf", ".docx", ".htm", ".html", ".epub", ".tex",
    ".log", ".csv", ".pdf",
)
IMAGE_EXTENSIONS = (
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tif", ".tiff",
    # SVG is view-only (the browser rasterises it — PIL cannot, so no
    # thumbnail); HEIC is best-effort (PIL needs pillow-heif).
    ".svg", ".heic",
)
AUDIO_EXTENSIONS = (
    ".wav", ".mp3", ".m4a", ".opus", ".oga", ".ogg", ".aac", ".flac",
    ".wma", ".amr",
)
VIDEO_EXTENSIONS = (
    ".mkv", ".mov", ".mp4", ".webm", ".wmv", ".m4v", ".avi", ".mpg",
    ".mpeg", ".3gp", ".ts",
)


class MediaType(StrEnum):
    """Kind of a source file, derived from its mediapath (legacy semantics).

    Mirrors the legacy ``helpers.get_media_type``: anything under ``/docs/``
    or ``docs:`` is TEXT (PDF handling is decided separately by file
    extension), images/audio/video are classified by file extension.
    """

    TEXT = "text"
    PDF = "pdf"
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"

    @classmethod
    def from_mediapath(cls, mediapath: str | None) -> MediaType:
        """Derive the media type from a mediapath string."""
        if not mediapath or len(mediapath) < 6:
            return cls.TEXT
        if mediapath.startswith(("/docs/", "docs:")):
            return cls.TEXT
        ext = Path(mediapath).suffix.lower()
        if ext in IMAGE_EXTENSIONS:
            return cls.IMAGE
        if ext in AUDIO_EXTENSIONS:
            return cls.AUDIO
        if ext in VIDEO_EXTENSIONS:
            return cls.VIDEO
        return cls.TEXT


def is_pdf_filename(filename: str) -> bool:
    """True when a document should be opened with the PDF coder."""
    return filename.lower().endswith(".pdf")


class AttributeScope(StrEnum):
    """Whether an attribute type applies to files or cases."""

    CASE = "case"
    FILE = "file"


class AttributeValueType(StrEnum):
    """Value kind of an attribute type."""

    TEXT = "text"
    NUMBER = "number"
    DATE = "date"
    BOOLEAN = "boolean"
