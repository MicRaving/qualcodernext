"""URL scraping service — Reddit threads, YouTube videos, web articles.

Each scraper returns a ``ScrapedContent`` (filename + file bytes); the
caller persists it through the regular file-import pipeline
(``ImportService.import_file``), so duplicate detection, attribute
placeholders and the source row behave exactly like any other file import.

Modes:
- ``reddit``  — anonymous ``.json`` API: submission selftext + flattened
  comment tree (indented by depth, authors prefixed ``u/<author>:``).
- ``youtube`` — yt-dlp metadata (title/uploader/duration/description) and
  the comment thread: top-level comments with author, like count and UTC
  timestamp, replies indented by depth. Comments are the primary content;
  caption tracks are fetched ONLY as a fallback when a video has no
  comments (e.g. disabled) — when comments exist, captions are dropped
  entirely. If the installed yt-dlp predates comment extraction
  (2021.12.17) the output is header + description only, with a note in
  the text, and captions are not fetched either.
- ``article`` — page fetched with urllib, cleaned with trafilatura
  (falling back to the project's own ``html_to_text``).
- ``html``    — raw page HTML saved verbatim as a ``.html`` source.
- ``pdf``     — page fetched with urllib and rendered to a PDF document
  with PyMuPDF's Story engine (mirroring the ``GET /sources/{id}/pdf``
  export; a text-only fallback PDF when the layout render fails). Stored
  as a ``.pdf`` source the PdfCoder can open.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import logging
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlparse

import trafilatura
import yt_dlp

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 QCnext/0.2.0"
)
FETCH_TIMEOUT = 45

REDDIT_HOSTS = (
    "reddit.com",
    "www.reddit.com",
    "old.reddit.com",
    "m.reddit.com",
    "np.reddit.com",
    "new.reddit.com",
)
YOUTUBE_HOSTS = ("youtube.com", "m.youtube.com", "youtu.be")

_PREFERRED_CAPTION_LANGS = ("en", "en-US", "en-GB", "en-orig")
_CUE_RE = re.compile(r"^(\d{1,2}):(\d{2}):(\d{2})[.,]\d{0,3}\s*-->")


class ScrapeError(ValueError):
    """A URL could not be fetched or parsed (surfaces as HTTP 422)."""

    def __init__(self, message: str, *, code: int | None = None) -> None:
        """``code`` carries the HTTP status when the failure came from a server."""
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ScrapedContent:
    """A page/thread/video reduced to a file ready for the import pipeline."""

    filename: str
    data: bytes
    mode: str


def validate_url(url: str) -> None:
    """Reject anything that is not an http(s) URL."""
    if not url.strip():
        raise ScrapeError("URL is empty")
    try:
        scheme = urlparse(url.strip()).scheme.lower()
    except ValueError as err:
        raise ScrapeError("invalid URL") from err
    if scheme not in ("http", "https"):
        raise ScrapeError("only http and https URLs are supported")


def detect_mode(url: str, mode: str = "auto") -> str:
    """Resolve the ``auto`` mode from the hostname."""
    if mode and mode != "auto":
        return mode
    host = urlparse(url).netloc.lower()
    if host == "reddit.com" or host.endswith(".reddit.com"):
        return "reddit"
    if host == "youtu.be" or host.endswith("youtube.com"):
        return "youtube"
    return "article"


def fetch_url(url: str, timeout: int = FETCH_TIMEOUT) -> bytes:
    """Fetch a URL with a browser-like User-Agent (redirects followed)."""
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/json,*/*;q=0.8",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except urllib.error.HTTPError as err:
        raise ScrapeError(
            f"server returned HTTP {err.code} for {url}", code=err.code
        ) from err
    except urllib.error.URLError as err:
        raise ScrapeError(f"could not reach {url}: {err.reason}") from err


def sanitize_name(title: str, fallback: str) -> str:
    """Turn a page/thread title into a safe filename base (no path chars)."""
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", title or "").strip()
    name = re.sub(r"\s+", " ", name).strip(". ")
    if not name:
        name = fallback
    return name[:100].strip(". ")


def _hostname(url: str) -> str:
    try:
        host = urlparse(url).netloc.lower()
    except ValueError as err:
        raise ScrapeError("invalid URL") from err
    return host


def _host_for_name(url: str) -> str:
    return _hostname(url).removeprefix("www.")


def _page_title(html: str) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    if not match:
        return ""
    return re.sub(r"\s+", " ", match.group(1)).strip()


def _as_int(value: object) -> int | None:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _format_duration(seconds: object) -> str:
    total = _as_int(seconds)
    if total is None:
        return str(seconds)
    if total < 0:
        return "0:00"
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


# ----------------------------------------------------------------------
# Reddit
# ----------------------------------------------------------------------

#: Every subdomain variant serves the same anonymous ``.json`` API —
#: normalize to the canonical host so old/np/m links behave identically.
_REDDIT_CANONICAL_HOST = "www.reddit.com"


def _reddit_normalize_host(url: str) -> str:
    """Map old/m/np/new/wwww reddit hosts onto www.reddit.com."""
    parsed = urlparse(url)
    host = (parsed.netloc or "").lower()
    if host in REDDIT_HOSTS:
        return parsed._replace(netloc=_REDDIT_CANONICAL_HOST).geturl()
    return url


def _reddit_json_url(url: str) -> str:
    """Append ``.json`` to the path, keeping the query string and fragment."""
    parsed = urlparse(url)
    path = parsed.path.rstrip("/") or "/"
    if not path.endswith(".json"):
        path += ".json"
    return parsed._replace(path=path).geturl()


def _reddit_listing_payload(payload: object) -> tuple[dict, dict]:
    """Split a Reddit JSON payload into (post listing, comments listing).

    Reddit serves the comments endpoint either as a two-element array
    ``[post_listing, comments_listing]`` (www/old/m.reddit, including the
    new reddit API) or as a single listing object
    ``{"data": {"children": [...]}}`` on some API paths.
    """
    if isinstance(payload, list):
        post = payload[0] if payload and isinstance(payload[0], dict) else {}
        comments = payload[1] if len(payload) > 1 and isinstance(payload[1], dict) else {}
        return post, comments
    if isinstance(payload, dict) and "data" in payload:
        return payload, {}
    raise ScrapeError("unexpected Reddit response shape")


def _first_child(listing: object) -> dict:
    children = (
        listing.get("data", {}).get("children", [])
        if isinstance(listing, dict)
        else []
    )
    for child in children:
        data = child.get("data") if isinstance(child, dict) else None
        if isinstance(data, dict):
            return data
    return {}


def _reddit_comments(comments_listing: object) -> list[str]:
    """Flatten the comment tree, indenting by depth (``u/<author>: body``)."""
    lines: list[str] = []

    def walk(children: object, depth: int) -> None:
        for child in children if isinstance(children, list) else []:
            data = child.get("data") if isinstance(child, dict) else None
            if not isinstance(data, dict):
                continue
            body = (data.get("body") or "").strip()
            if body and not body.startswith("[deleted]") and not body.startswith("[removed]"):
                author = data.get("author") or "unknown"
                prefix = f"u/{author}: " if author != "[deleted]" else ""
                lines.append("  " * depth + prefix + body)
            replies = data.get("replies")
            if isinstance(replies, dict):
                kids = replies.get("data", {}).get("children", [])
                if kids:
                    walk(kids, depth + 1)

    root = (
        comments_listing.get("data", {}).get("children", [])
        if isinstance(comments_listing, dict)
        else []
    )
    walk(root, 0)
    return lines


def _reddit_block_reason(payload: object) -> str | None:
    """A clear error for banned/quarantined/blocked JSON bodies.

    Reddit answers some blocked requests with HTTP 200 plus a small JSON
    object (``{"reason": "banned", "error": 403}``, ``{"reason":
    "quarantined"}``) instead of an HTTP error — surface those instead of
    failing on the generic "unexpected Reddit response shape" path.
    """
    if not isinstance(payload, dict) or "data" in payload:
        return None
    reason = payload.get("reason")
    if isinstance(reason, str):
        return (
            f"Reddit reports this page as {reason} — it cannot be "
            "fetched anonymously"
        )
    if payload.get("error") == 403:
        return "subreddit may be private or blocked"
    return None


def scrape_reddit(url: str) -> ScrapedContent:
    """Fetch a Reddit submission + comments through the anonymous .json API."""
    try:
        raw = fetch_url(_reddit_json_url(_reddit_normalize_host(url)))
    except ScrapeError as err:
        if err.code == 403:
            raise ScrapeError(
                "subreddit may be private or blocked — it cannot be fetched anonymously"
            ) from err
        if err.code == 429:
            raise ScrapeError("Reddit rate-limited — wait a minute and retry") from err
        raise

    try:
        payload = json.loads(raw.decode("utf-8", errors="replace"))
    except ValueError as err:
        raise ScrapeError("Reddit response is not JSON") from err

    blocked = _reddit_block_reason(payload)
    if blocked is not None:
        raise ScrapeError(blocked)

    post_listing, comments_listing = _reddit_listing_payload(payload)
    post = _first_child(post_listing)
    if not post:
        raise ScrapeError("unexpected Reddit response shape")

    title = (post.get("title") or "").strip()
    author = post.get("author") or "unknown"
    selftext = (post.get("selftext") or "").strip()

    lines: list[str] = [title] if title else []
    lines.append(f"Posted by u/{author}, {post.get('score') or 0} points")
    lines.append(f"URL: {url}")
    if selftext:
        lines.append("")
        lines.append(selftext)

    comment_lines = _reddit_comments(comments_listing)
    if comment_lines:
        lines.append("")
        lines.append("Comments")
        lines.append("")
        lines.extend(comment_lines)

    text = "\n".join(lines).strip()
    if not text:
        raise ScrapeError("Reddit thread contains no text")
    return ScrapedContent(
        filename=f"{sanitize_name(title, 'reddit-post')}.txt",
        data=text.encode("utf-8"),
        mode="reddit",
    )


# ----------------------------------------------------------------------
# YouTube (yt-dlp)
# ----------------------------------------------------------------------

#: yt-dlp gained comment extraction (``getcomments``) in 2021.12.17.
_YT_DLP_COMMENTS_MIN_VERSION = (2021, 12, 17)


def _yt_dlp_comments_supported() -> bool:
    """Whether the installed yt-dlp can extract comments (checked at import)."""
    try:
        from yt_dlp.version import __version__
    except ImportError:
        return True
    parts = [int(part) for part in __version__.split(".") if part.isdigit()]
    if len(parts) < 3:
        return True
    return tuple(parts[:3]) >= _YT_DLP_COMMENTS_MIN_VERSION


#: When False, ``getcomments`` is not requested and the scraper falls back
#: to caption-free header + description (with a note in the output text).
_YT_DLP_COMMENTS_SUPPORTED = _yt_dlp_comments_supported()


def _pick_caption_language(langs: dict) -> list:
    for lang in _PREFERRED_CAPTION_LANGS:
        if lang in langs:
            return langs[lang]
    return next(iter(langs.values())) if langs else []


def _pick_vtt_track(entries: list) -> dict | None:
    for entry in entries:
        if isinstance(entry, dict) and (entry.get("ext") or "").lower() == "vtt":
            return entry
    for entry in entries:
        if isinstance(entry, dict) and entry.get("url"):
            return entry
    return None


def _parse_vtt(text: str) -> str:
    lines: list[str] = []
    stamp: str | None = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("WEBVTT", "NOTE", "X-")):
            stamp = None
            continue
        cue = _CUE_RE.match(line)
        if cue:
            _, minute, second = (int(cue.group(i)) for i in (1, 2, 3))
            stamp = f"[{minute:02d}:{second:02d}]"
            continue
        if line.startswith(("Kind:", "Language:")) or re.fullmatch(r"\d+", line):
            continue
        clean = re.sub(r"<[^>]+>", "", line).strip()
        if clean:
            lines.append(f"{stamp} {clean}".strip() if stamp else clean)
    return "\n".join(lines)


def _collect_json_text(value: object, out: list[str]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key in ("text", "caption", "content", "s") and isinstance(item, str) and item.strip():
                out.append(item.strip())
            elif isinstance(item, (dict, list)):
                _collect_json_text(item, out)
    elif isinstance(value, list):
        for item in value:
            _collect_json_text(item, out)


def _caption_text(raw: bytes) -> str:
    text = raw.decode("utf-8", errors="replace")
    if text.lstrip().startswith("WEBVTT"):
        return _parse_vtt(text)
    try:
        payload = json.loads(text)
    except ValueError:
        return "\n".join(
            line.strip() for line in text.splitlines() if line.strip() and "-->" not in line
        )
    out: list[str] = []
    _collect_json_text(payload, out)
    return "\n".join(out)


def _youtube_captions(info: dict) -> str:
    """Best caption track: manual (``subtitles``) over automatic."""
    for key in ("subtitles", "automatic_captions"):
        langs = info.get(key)
        if not isinstance(langs, dict) or not langs:
            continue
        track = _pick_vtt_track(_pick_caption_language(langs))
        if track is None or not track.get("url"):
            continue
        try:
            raw = fetch_url(track["url"])
        except ScrapeError as err:
            logger.warning("YouTube caption fetch failed: %s", err)
            continue
        text = _caption_text(raw).strip()
        if text:
            return text
    return ""


def _format_likes(value: object) -> str:
    """``like_count`` -> ``"N likes"`` ("" when the field is missing)."""
    count = _as_int(value)
    if count is None:
        return ""
    return f"{count:,} likes"


def _format_comment_timestamp(value: object) -> str:
    """Unix epoch seconds -> ``YYYY-MM-DD HH:MM`` UTC ("" when unknown)."""
    ts = _as_int(value)
    if ts is None:
        return ""
    try:
        return datetime.fromtimestamp(ts, tz=UTC).strftime("%Y-%m-%d %H:%M")
    except (OverflowError, OSError, ValueError):
        return ""


def _comment_lines(comment: dict, depth: int) -> list[str]:
    """Render one comment plus its nested ``replies`` (indented by depth)."""
    lines: list[str] = []
    text = (comment.get("text") or "").strip()
    if text:
        author = (comment.get("author") or "unknown").strip() or "unknown"
        meta = ", ".join(
            part
            for part in (
                _format_likes(comment.get("like_count")),
                _format_comment_timestamp(comment.get("timestamp")),
            )
            if part
        )
        label = f"u/{author}: {text}" if not meta else f"u/{author} ({meta}): {text}"
        lines.append("  " * depth + label)
    replies = comment.get("replies")
    if isinstance(replies, list):
        for reply in replies:
            if isinstance(reply, dict):
                lines.extend(_comment_lines(reply, depth + 1))
    return lines


def _youtube_comments(info: dict) -> list[str]:
    """Flatten the comment list; replies are indented one level per depth.

    Handles both yt-dlp layouts defensively: nested ``replies`` lists
    (``{author, text, timestamp, like_count, replies: [...]}``) and the
    flat list where every comment carries ``id``/``parent`` references.
    Missing fields fall back to ``unknown`` / no metadata.
    """
    comments = info.get("comments")
    if not isinstance(comments, list) or not comments:
        return []
    by_id: dict = {}
    for comment in comments:
        if isinstance(comment, dict) and comment.get("id"):
            by_id[comment["id"]] = comment

    def depth_of(comment: dict) -> int:
        depth = 0
        current = comment
        seen: set[object] = set()
        while depth < 10:
            parent = current.get("parent")
            if not parent or parent in seen:
                return depth
            parent_comment = by_id.get(parent)
            if not isinstance(parent_comment, dict):
                return depth
            seen.add(current.get("id"))
            current = parent_comment
            depth += 1
        return depth

    emitted: set[object] = set()
    lines: list[str] = []
    for comment in comments:
        if not isinstance(comment, dict):
            continue
        comment_id = comment.get("id")
        if comment_id is not None and comment_id in emitted:
            continue
        lines.extend(_comment_lines(comment, depth_of(comment)))
        if comment_id is not None:
            emitted.add(comment_id)
    return lines


#: Hard cap for a single yt-dlp extraction — it can hang on flaky networks.
_YT_TIMEOUT_SECONDS = 90
#: Shown when yt-dlp signals an internal abort (never a "real" failure).
_YT_ABORT_MESSAGE = (
    "YouTube extraction was interrupted — try again, or import the "
    "video page as 'Article' mode instead"
)
_YT_TIMEOUT_MESSAGE = (
    f"YouTube extraction timed out after {_YT_TIMEOUT_SECONDS} seconds — "
    "try again, or import the video page as 'Article' mode instead"
)
#: Markers some platforms report through ``DownloadError`` when yt-dlp
#: aborts (e.g. "signal aborted without reason") instead of raising.
_YT_ABORT_MARKERS = ("signal aborted", "aborted", "interrupted")
#: Dedicated executor for yt-dlp extractions: a timed-out call keeps its
#: thread (threads cannot be killed) but must never block loop teardown.
_YT_EXTRACTOR_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
    max_workers=1, thread_name_prefix="yt-extract"
)


class _YouTubeAbortError(ScrapeError):
    """yt-dlp's internal abort signal surfaced as a retryable error."""


def _is_yt_abort(err: BaseException) -> bool:
    """True when a yt-dlp error is the internal abort signal, not a real failure."""
    message = str(err).lower()
    return any(marker in message for marker in _YT_ABORT_MARKERS)


def _yt_extract_sync(url: str, options: dict) -> dict:
    """Blocking yt-dlp call: video metadata (+ comments when requested).

    yt-dlp aborts long extractions (e.g. huge comment threads) by raising
    ``KeyboardInterrupt``/``SystemExit`` out of ``extract_info`` — or a
    ``DownloadError`` naming the abort on some platforms. Both are mapped
    to a friendly, actionable ``ScrapeError`` instead of the raw signal
    propagating into the import pipeline.
    """
    try:
        ydl = yt_dlp.YoutubeDL(options)
        try:
            info = ydl.extract_info(url, download=False)
        except (KeyboardInterrupt, SystemExit) as err:
            raise _YouTubeAbortError(_YT_ABORT_MESSAGE) from err
        finally:
            ydl.close()
    except yt_dlp.utils.DownloadError as err:
        if _is_yt_abort(err):
            raise _YouTubeAbortError(_YT_ABORT_MESSAGE) from err
        raise ScrapeError(f"YouTube extraction failed: {err}") from err
    if not isinstance(info, dict):
        raise ScrapeError("YouTube returned no metadata")
    return info


def _yt_dlp_extract(url: str, options: dict) -> dict:
    """Run ``_yt_extract_sync`` off-loop with an abort + timeout guard.

    The yt-dlp call runs in a thread under ``asyncio.wait_for`` so a hung
    network cannot block the import: the timeout surfaces a friendly
    error. When no event loop is running (the API's worker thread, unit
    tests) the guard drives its own loop; inside an async caller the guard
    runs on a private loop in a thread so the caller's loop is never
    blocked.
    """
    async def _guarded() -> dict:
        loop = asyncio.get_running_loop()
        return await asyncio.wait_for(
            loop.run_in_executor(_YT_EXTRACTOR_EXECUTOR, _yt_extract_sync, url, options),
            timeout=_YT_TIMEOUT_SECONDS,
        )

    def _run_guarded() -> dict:
        try:
            return asyncio.run(_guarded())
        except TimeoutError as err:
            raise ScrapeError(_YT_TIMEOUT_MESSAGE) from err

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return _run_guarded()

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(_run_guarded)
        try:
            return future.result(timeout=_YT_TIMEOUT_SECONDS + 15)
        except TimeoutError as err:
            raise ScrapeError(_YT_TIMEOUT_MESSAGE) from err


def scrape_youtube(url: str) -> ScrapedContent:
    """Extract video metadata and the comment thread (captions only as fallback).

    Comments are the primary content: when the video has any, captions are
    dropped entirely. Caption text is fetched only when comments are
    unavailable (e.g. disabled). When the installed yt-dlp cannot extract
    comments (``_YT_DLP_COMMENTS_SUPPORTED`` False), the output is header
    + description only, with a note, and captions are not fetched either.

    The yt-dlp call is guarded against its internal abort signal (huge
    comment threads can abort extraction): the first abort is retried once
    WITHOUT ``getcomments`` so the metadata survives and the import falls
    back to captions or the plain header; a second abort — or a timeout —
    surfaces a friendly error instead of the raw signal.
    """
    options = {
        "noplaylist": True,
        "skip_download": True,
        "writesubtitles": False,
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": 30,
    }
    if _YT_DLP_COMMENTS_SUPPORTED:
        options["getcomments"] = True
    try:
        info = _yt_dlp_extract(url, options)
    except _YouTubeAbortError:
        if not options.get("getcomments"):
            raise
        # Comment extraction can abort on very large threads — retry once
        # with metadata only; the normal flow then falls back to captions
        # or the plain header.
        logger.warning(
            "YouTube comment extraction aborted for %s — retrying without comments", url
        )
        info = _yt_dlp_extract(url, {**options, "getcomments": False})
    if not isinstance(info, dict):
        raise ScrapeError("YouTube returned no metadata")

    title = (info.get("title") or "").strip() or "youtube-video"
    uploader = (info.get("uploader") or info.get("channel") or "").strip()
    duration = info.get("duration")
    description = (info.get("description") or "").strip()

    lines = [title]
    if uploader:
        lines.append(f"Uploader: {uploader}")
    if duration:
        lines.append(f"Duration: {_format_duration(duration)}")
    lines.append(f"URL: {url}")
    if description:
        lines.append("")
        lines.append(description)

    if _YT_DLP_COMMENTS_SUPPORTED:
        comment_lines = _youtube_comments(info)
        if comment_lines:
            lines.append("")
            lines.append("Comments")
            lines.append("")
            lines.extend(comment_lines)
        else:
            caption_text = _youtube_captions(info)
            if caption_text:
                logger.info("YouTube comments unavailable; falling back to captions for %s", url)
                lines.append("")
                lines.append("Captions")
                lines.append("")
                lines.append(caption_text)
            else:
                logger.warning("YouTube comments unavailable for %s", url)
    else:
        note = (
            "Note: comments are unavailable — the installed yt-dlp "
            "version cannot extract comments."
        )
        logger.warning("YouTube comment extraction unsupported: %s (%s)", note, url)
        lines.append("")
        lines.append(note)

    text = "\n".join(lines).strip()
    if not text:
        raise ScrapeError("YouTube video contains no text")
    return ScrapedContent(
        filename=f"{sanitize_name(title, 'youtube-video')}.txt",
        data=text.encode("utf-8"),
        mode="youtube",
    )


# ----------------------------------------------------------------------
# Article / raw HTML
# ----------------------------------------------------------------------

def _decode_html(raw: bytes) -> str:
    return raw.decode("utf-8", errors="replace")


def scrape_article(url: str) -> ScrapedContent:
    """Fetch a page and extract its main text with trafilatura."""
    raw = fetch_url(url)
    html = _decode_html(raw)
    text = ""
    try:
        text = trafilatura.extract(raw) or ""
    except Exception as err:  # extraction must never break the import
        logger.warning("trafilatura extraction failed: %s", err)
    if not text.strip():
        from qualcoder_api.services.import_service import html_to_text

        text = html_to_text(html).strip()
    if not text.strip():
        raise ScrapeError("could not extract any text from the page")
    title = _page_title(html) or _host_for_name(url)
    return ScrapedContent(
        filename=f"{sanitize_name(title, 'article')}.txt",
        data=text.strip().encode("utf-8"),
        mode="article",
    )


def scrape_html(url: str) -> ScrapedContent:
    """Capture mode: save the raw page HTML as a .html source."""
    raw = fetch_url(url)
    html = _decode_html(raw)
    title = _page_title(html) or _host_for_name(url)
    return ScrapedContent(
        filename=f"{sanitize_name(title, 'page')}.html",
        data=raw,
        mode="html",
    )


# ----------------------------------------------------------------------
# PDF capture (PyMuPDF Story render)
# ----------------------------------------------------------------------

#: Applied on top of PyMuPDF's default stylesheet — the same treatment the
#: HTML-source export uses in ``api/v1/sources.py``.
_PDF_USER_CSS = (
    "body { font-family: sans-serif; font-size: 10pt; line-height: 1.5; "
    "color: #1a1a1a; }"
)


def _story_render(html: str, css: str | None) -> bytes:
    """Render an HTML string to PDF bytes through PyMuPDF's Story engine.

    The pagination callback receives ``(page_number, filled)`` and returns
    the ``(mediabox, content rect, transform)`` for the next page; the
    DocumentWriter creates pages automatically as the content overflows.
    MuPDF substitutes its embedded fallback fonts for characters the page's
    own fonts cannot cover, so arbitrary unicode round-trips intact.
    """
    from io import BytesIO

    import fitz

    buf = BytesIO()
    writer = fitz.DocumentWriter(buf)
    rect = fitz.paper_rect("a4")
    story = fitz.Story(html=html, user_css=css)
    story.write(writer, lambda _number, _filled: (rect, rect, fitz.Identity))
    writer.close()
    return buf.getvalue()


def _text_pdf(text: str) -> bytes:
    """Fallback: the extracted plain text as a minimal escaped-PDF document.

    Rendered through the same Story engine WITHOUT any CSS, so it cannot
    fail on unsupported styles and keeps unicode via MuPDF's fallback
    fonts — plain ``insert_text`` with a base-14 font would corrupt
    non-WinAnsi characters, so it is avoided here.
    """
    import html as html_module

    paragraphs: list[str] = []
    for block in (text or "").split("\n\n"):
        block = block.strip()
        if not block:
            continue
        paragraphs.append(html_module.escape(block).replace("\n", "<br/>"))
    body = "".join(f"<p>{p}</p>" for p in paragraphs)
    return _story_render(f"<html><body>{body}</body></html>", None)


def scrape_pdf(url: str) -> ScrapedContent:
    """Capture mode: render the page's HTML to a PDF document.

    Mirrors the ``GET /sources/{id}/pdf`` export: the fetched HTML goes
    through PyMuPDF's Story layout engine on A4 pages. When the layout
    render fails (unsupported CSS/markup) a minimal text-only PDF is
    produced instead, so the import always yields a parseable document
    the PdfCoder can open.
    """
    from qualcoder_api.services.import_service import (
        decode_text_with_best_encoding,
        html_to_text,
    )

    raw = fetch_url(url)
    html = decode_text_with_best_encoding(raw)
    title = _page_title(html) or _host_for_name(url)
    try:
        data = _story_render(html, _PDF_USER_CSS)
    except Exception as err:  # any render failure -> text-only fallback
        logger.warning("HTML -> PDF render failed for %s: %s", url, err)
        text = html_to_text(html).strip()
        if not text:
            raise ScrapeError("could not render the page to PDF") from err
        try:
            data = _text_pdf(text)
        except Exception as err2:  # pragma: no cover - minimal render never fails
            raise ScrapeError("could not render the page to PDF") from err2
    return ScrapedContent(
        filename=f"{sanitize_name(title, 'page')}.pdf",
        data=data,
        mode="pdf",
    )


# ----------------------------------------------------------------------
# Orchestrator
# ----------------------------------------------------------------------

def scrape_url(url: str, mode: str = "auto") -> ScrapedContent:
    """Fetch + parse a URL into (filename, file bytes, resolved mode)."""
    url = url.strip()
    validate_url(url)
    resolved = detect_mode(url, mode)
    if resolved == "reddit":
        return scrape_reddit(url)
    if resolved == "youtube":
        return scrape_youtube(url)
    if resolved == "html":
        return scrape_html(url)
    if resolved == "pdf":
        return scrape_pdf(url)
    return scrape_article(url)
