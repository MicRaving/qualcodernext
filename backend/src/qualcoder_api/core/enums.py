"""Domain enums for the QualCoder v4 backend. No Qt, no I/O."""

from __future__ import annotations

from enum import StrEnum


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
        lower = mediapath.lower()
        if lower.endswith(("jpg", "png", "jpeg")):
            return cls.IMAGE
        if lower.endswith(("mp3", "wav", "m4a")):
            return cls.AUDIO
        if lower.endswith(("mkv", "mov", "mp4", "ogg", "wmv", "webm")):
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
