"""Media-type detection unit tests — every supported extension.

Covers ``import_service.detect_media_type`` (import/classification) and
``MediaType.from_mediapath`` (the API model derivation), which must agree
on the same extension sets (they share ``core/enums.py``).
"""

from __future__ import annotations

import pytest

from qualcoder_api.core.enums import (
    AUDIO_EXTENSIONS,
    DOCUMENT_EXTENSIONS,
    IMAGE_EXTENSIONS,
    VIDEO_EXTENSIONS,
    MediaType,
)
from qualcoder_api.services.import_service import detect_media_type

AUDIO_NAMES = [
    f"clip{ext}"
    for ext in (".wav", ".mp3", ".m4a", ".opus", ".oga", ".ogg", ".aac", ".flac", ".wma", ".amr")
]
VIDEO_NAMES = [
    f"clip{ext}"
    for ext in (".mkv", ".mov", ".mp4", ".webm", ".wmv", ".m4v", ".avi", ".mpg", ".mpeg", ".3gp", ".ts")
]
IMAGE_NAMES = [
    f"pic{ext}"
    for ext in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tif", ".tiff", ".svg", ".heic")
]
DOCUMENT_NAMES = [
    f"doc{ext}"
    for ext in (".txt", ".md", ".odt", ".rtf", ".docx", ".htm", ".html", ".epub", ".tex", ".log", ".csv")
]


@pytest.mark.parametrize("name", AUDIO_NAMES)
def test_detect_audio(name: str) -> None:
    assert detect_media_type(name) == MediaType.AUDIO


@pytest.mark.parametrize("name", VIDEO_NAMES)
def test_detect_video(name: str) -> None:
    assert detect_media_type(name) == MediaType.VIDEO


@pytest.mark.parametrize("name", IMAGE_NAMES)
def test_detect_image(name: str) -> None:
    assert detect_media_type(name) == MediaType.IMAGE


@pytest.mark.parametrize("name", DOCUMENT_NAMES)
def test_detect_text_documents(name: str) -> None:
    assert detect_media_type(name) == MediaType.TEXT


def test_detect_pdf() -> None:
    assert detect_media_type("paper.pdf") == MediaType.PDF


def test_detect_case_insensitive() -> None:
    assert detect_media_type("CLIP.OPUS") == MediaType.AUDIO
    assert detect_media_type("Clip.M4V") == MediaType.VIDEO
    assert detect_media_type("Pic.WebP") == MediaType.IMAGE


def test_detect_unknown_falls_back_to_text() -> None:
    assert detect_media_type("archive.zip") == MediaType.TEXT
    assert detect_media_type("noextension") == MediaType.TEXT


def test_detect_no_shared_suffix_confusion() -> None:
    # .ogg is audio (Vorbis/Opus); .webm stays video.
    assert detect_media_type("talk.ogg") == MediaType.AUDIO
    assert detect_media_type("talk.webm") == MediaType.VIDEO


@pytest.mark.parametrize("mediapath", [f"/audio/{n}" for n in AUDIO_NAMES])
def test_from_mediapath_audio(mediapath: str) -> None:
    assert MediaType.from_mediapath(mediapath) == MediaType.AUDIO


@pytest.mark.parametrize("mediapath", [f"/video/{n}" for n in VIDEO_NAMES])
def test_from_mediapath_video(mediapath: str) -> None:
    assert MediaType.from_mediapath(mediapath) == MediaType.VIDEO


@pytest.mark.parametrize("mediapath", [f"/images/{n}" for n in IMAGE_NAMES])
def test_from_mediapath_image(mediapath: str) -> None:
    assert MediaType.from_mediapath(mediapath) == MediaType.IMAGE


@pytest.mark.parametrize(
    "mediapath",
    [
        "/docs/interview.log",
        "docs:linked.csv",
        "/docs/report.docx",
        None,
        "",
        "/misc/archive.zip",
    ],
)
def test_from_mediapath_text(mediapath: str | None) -> None:
    assert MediaType.from_mediapath(mediapath) == MediaType.TEXT


@pytest.mark.parametrize(
    "mediapath",
    [
        "audio:recording.opus",
        "audio:podcast.ogg",
        "video:interview.m4v",
        "video:old.3gp",
        "images:scan.tiff",
        "images:logo.svg",
    ],
)
def test_from_mediapath_external_links(mediapath: str) -> None:
    expected = {
        "audio": MediaType.AUDIO,
        "video": MediaType.VIDEO,
        "images": MediaType.IMAGE,
    }[mediapath.split(":", 1)[0]]
    assert MediaType.from_mediapath(mediapath) == expected


def test_sets_are_disjoint() -> None:
    all_exts = (
        set(DOCUMENT_EXTENSIONS) | set(IMAGE_EXTENSIONS)
        | set(AUDIO_EXTENSIONS) | set(VIDEO_EXTENSIONS)
    )
    total = (
        len(DOCUMENT_EXTENSIONS) + len(IMAGE_EXTENSIONS)
        + len(AUDIO_EXTENSIONS) + len(VIDEO_EXTENSIONS)
    )
    # No extension may map to two kinds at once (e.g. the old .ogg -> video).
    assert len(all_exts) == total
    assert ".ogg" in AUDIO_EXTENSIONS
    assert ".ogg" not in VIDEO_EXTENSIONS
