"""URL scraping service — Reddit threads, YouTube videos, web articles.

Each scraper returns a ``ScrapedContent`` (filename + file bytes); the
caller persists it through the regular file-import pipeline
(``ImportService.import_file``), so duplicate detection, attribute
placeholders and the source row behave exactly like any other file import.

Modes:
- ``reddit``  — anonymous ``.json`` API: submission selftext + flattened
  comment tree (indented by depth, authors prefixed ``u/<author>:``).
- ``youtube`` — yt-dlp metadata (title/uploader/duration/description),
  the best available caption track (manual over automatic) fetched from
  its subtitle URL, and comments when present.
- ``article`` — page fetched with urllib, cleaned with trafilatura
  (falling back to the project's own ``html_to_text``).
- ``html``    — raw page HTML saved verbatim as a ``.html`` source.
"""

from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from urllib.parse import urlparse

import trafilatura
import yt_dlp

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 QCnext/0.2.0"
)
FETCH_TIMEOUT = 45

REDDIT_HOSTS = ("reddit.com", "old.reddit.com", "m.reddit.com")
YOUTUBE_HOSTS = ("youtube.com", "m.youtube.com", "youtu.be")

_PREFERRED_CAPTION_LANGS = ("en", "en-US", "en-GB", "en-orig")
_CUE_RE = re.compile(r"^(\d{1,2}):(\d{2}):(\d{2})[.,]\d{0,3}\s*-->")


class ScrapeError(ValueError):
    """A URL could not be fetched or parsed (surfaces as HTTP 422)."""


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
        raise ScrapeError(f"server returned HTTP {err.code} for {url}") from err
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

def _reddit_json_url(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path
    if not path.endswith(".json"):
        path = path.rstrip("/") + ".json"
    return parsed._replace(path=path).geturl()


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


def scrape_reddit(url: str) -> ScrapedContent:
    """Fetch a Reddit submission + comments through the anonymous .json API."""
    raw = fetch_url(_reddit_json_url(url))
    try:
        listing = json.loads(raw.decode("utf-8", errors="replace"))
    except ValueError as err:
        raise ScrapeError("Reddit response is not JSON") from err
    if not isinstance(listing, list) or len(listing) < 2:
        raise ScrapeError("unexpected Reddit response shape")

    post = _first_child(listing[0])
    title = (post.get("title") or "").strip()
    author = post.get("author") or "unknown"
    selftext = (post.get("selftext") or "").strip()

    lines: list[str] = [title] if title else []
    lines.append(f"Posted by u/{author}, {post.get('score') or 0} points")
    lines.append(f"URL: {url}")
    if selftext:
        lines.append("")
        lines.append(selftext)

    comment_lines = _reddit_comments(listing[1])
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


def _youtube_comments(info: dict) -> list[str]:
    """Flatten the comments list; replies are indented one level per parent."""
    comments = info.get("comments")
    if not isinstance(comments, list) or not comments:
        return []
    by_id: dict = {}
    for comment in comments:
        if isinstance(comment, dict) and comment.get("id"):
            by_id[comment["id"]] = comment

    def indent_of(comment: dict, depth: int = 0) -> int:
        if depth >= 5:
            return depth
        parent = comment.get("parent")
        if parent and parent in by_id:
            return indent_of(by_id[parent], depth + 1)
        return depth

    lines: list[str] = []
    for comment in comments:
        if not isinstance(comment, dict):
            continue
        text = (comment.get("text") or "").strip()
        if not text:
            continue
        author = (comment.get("author") or "unknown").strip()
        lines.append("  " * indent_of(comment) + f"u/{author}: {text}")
    return lines


def scrape_youtube(url: str) -> ScrapedContent:
    """Extract video metadata, the best caption track and comments."""
    options = {
        "noplaylist": True,
        "skip_download": True,
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": 30,
    }
    try:
        ydl = yt_dlp.YoutubeDL(options)
        try:
            info = ydl.extract_info(url, download=False)
        finally:
            ydl.close()
    except yt_dlp.utils.DownloadError as err:
        raise ScrapeError(f"YouTube extraction failed: {err}") from err
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

    caption_text = _youtube_captions(info)
    if caption_text:
        lines.append("")
        lines.append("Captions")
        lines.append("")
        lines.append(caption_text)

    comment_lines = _youtube_comments(info)
    if comment_lines:
        lines.append("")
        lines.append("Comments")
        lines.append("")
        lines.extend(comment_lines)

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
    return scrape_article(url)
