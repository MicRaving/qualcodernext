"""Bundled in-app help — markdown topics shipped under ``qualcoder_api.help_docs``.

Topics mirror the repo's ``docs/*.md`` files (copied verbatim into the package
at build time) so the help bar works offline in the packaged app. The library
is loaded at import time and exposed through list / get / search functions.
"""

from __future__ import annotations

import importlib.resources
import re
from dataclasses import dataclass

MAX_DESCRIPTION = 160
MAX_SNIPPET = 120

_LINK_ONLY_RE = re.compile(r"^!?\[[^\]]*\]\([^)]*\)\s*$")

#: Markdown punctuation that may appear backslash-escaped in the bundled docs
#: (generated from a converter that escapes every special character). The
#: help bar renders the content as markdown, so the escapes are resolved at
#: load time — otherwise the user sees a literal ``\&`` instead of ``&``.
_ESCAPE_RE = re.compile(r"\\([\\`*_{}\[\]()#+\-.!|&])")


def _unescape_markdown(text: str) -> str:
    """Resolve backslash escapes, then collapse doubled backslashes (a
    converter that escaped ``\\`` twice yields four — reduce to one)."""
    return _ESCAPE_RE.sub(r"\1", text).replace("\\\\", "\\")


@dataclass(frozen=True)
class Topic:
    id: str
    title: str
    content: str


def _description(content: str) -> str:
    """First non-heading paragraph, truncated to ~160 chars.

    Navigation lines (``[← Back …](…)``) and images are skipped so the
    description reads as prose instead of a back link.
    """
    para: list[str] = []
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped:
            if para:
                break
            continue
        if stripped.startswith("#"):
            continue
        if _LINK_ONLY_RE.match(stripped):
            continue
        para.append(stripped)
    text = " ".join(para)
    if len(text) <= MAX_DESCRIPTION:
        return text
    return text[: MAX_DESCRIPTION - 3] + "..."


def _snippet(content: str, start: int, end: int) -> tuple[str, int, int]:
    """~120 chars around a match in the content, ellipsized at the edges.

    Returns the snippet plus the match span (``rel0``/``rel1``) relative to
    the snippet so the frontend can highlight the hit.
    """
    lo = max(0, start - MAX_SNIPPET // 2)
    hi = min(len(content), end + MAX_SNIPPET // 2)
    prefix = "..." if lo > 0 else ""
    suffix = "..." if hi < len(content) else ""
    return (
        prefix + content[lo:hi] + suffix,
        len(prefix) + (start - lo),
        len(prefix) + (end - lo),
    )


def _parse(topic_id: str, text: str) -> Topic:
    text = _unescape_markdown(text)
    title = topic_id
    for line in text.splitlines():
        if line.startswith("# "):
            title = line[2:].strip()
            break
    return Topic(id=topic_id, title=title, content=text)


def _load_topics() -> dict[str, Topic]:
    topics: dict[str, Topic] = {}
    package = "qualcoder_api.help_docs"
    try:
        files = importlib.resources.files(package)
        for file in files.iterdir():
            if file.is_file() and file.name.endswith(".md"):
                text = file.read_text(encoding="utf-8")
                topic_id = file.name[: -len(".md")]
                topics[topic_id] = _parse(topic_id, text)
    except (ModuleNotFoundError, OSError):  # pragma: no cover - package data absent
        return {}
    return topics


LIBRARY = _load_topics()


def list_topics() -> list[dict]:
    return [
        {
            "id": topic.id,
            "title": topic.title,
            "description": _description(topic.content),
        }
        for topic in sorted(LIBRARY.values(), key=lambda t: t.id)
    ]


def get_topic(topic_id: str) -> dict | None:
    topic = LIBRARY.get(topic_id)
    if topic is None:
        return None
    return {"id": topic.id, "title": topic.title, "content": topic.content}


def search_topics(query: str, *, regex: bool = False) -> list[dict]:
    from qualcoder_api.core.pattern import compile_user_pattern

    pattern = (
        compile_user_pattern(query, ignore_case=True)
        if regex
        else re.compile(re.escape(query), re.IGNORECASE)
    )
    results: list[dict] = []
    for topic in sorted(LIBRARY.values(), key=lambda t: t.id):
        if pattern.search(topic.title) is None and pattern.search(topic.content) is None:
            continue
        match = pattern.search(topic.content)
        if match is not None:
            snippet, rel0, rel1 = _snippet(topic.content, match.start(), match.end())
        else:
            snippet, rel0, rel1 = _snippet(topic.content, 0, 0)
        results.append(
            {"id": topic.id, "title": topic.title, "snippet": snippet, "rel0": rel0, "rel1": rel1}
        )
    return results
