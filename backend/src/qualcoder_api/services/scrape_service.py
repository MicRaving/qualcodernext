"""URL scraping service — Reddit threads, YouTube videos, web articles.

Each scraper returns a ``ScrapedContent`` (filename + file bytes); the
caller persists it through the regular file-import pipeline
(``ImportService.import_file``), so duplicate detection, attribute
placeholders and the source row behave exactly like any other file import.

Modes:
- ``reddit``  — submission selftext + flattened comment tree (indented by
  depth, authors prefixed ``u/<author>:``).

  ACCESS STRATEGY (facts researched August 2026):
  * Anonymous path: the ``.json`` endpoint is fetched from
    ``www.reddit.com`` first, then ``old.reddit.com``, with a unique
    descriptive User-Agent. Reddit blocks script access to the anonymous
    ``.json`` endpoints with HTTP 403 (live verification: both hosts
    answer ``403 "whoa there, pardner! ... please register or sign in
    with your developer credentials ... make sure your User-Agent is not
    empty and is something unique and descriptive"``; plain browser UAs
    are blocked too). Rate limiting surfaces as HTTP 429 with a
    ``Retry-After`` header (seconds) — the anonymous path sleeps and
    retries ONCE, then reports a clear rate-limit error.
  * OAuth path (when ``reddit_client_id`` + ``reddit_client_secret`` are
    configured in the user settings — app created at
    ``reddit.com/prefs/apps``, "script" type): app-only
    ``client_credentials`` flow per Reddit's OAuth2 wiki — ``POST
    https://www.reddit.com/api/v1/access_token`` with HTTP Basic auth
    (``client_id:client_secret``) and a form-encoded
    ``grant_type=client_credentials`` body, then the thread URL on
    ``https://oauth.reddit.com`` with ``Authorization: Bearer <token>``.
    Per the wiki, NO ``scope`` parameter is sent for app-only tokens —
    the app's configured scopes apply (script apps get ``read``). Tokens
    live 1 hour and app-only tokens have no refresh token, so one token
    is fetched per scrape (cheap). The payload parsing (post + comments
    array) is identical for both paths.
- ``youtube`` — when a project is open the comment thread is imported as
  STRUCTURED data through the survey row-import core: every comment
  becomes a case (``<video title> — Comment <n>``) with the ``author``,
  ``likes`` and ``date`` case attributes and the comment text as an
  analyzable text source (``<case name>_comment``) linked to the case and
  coded with a code named after the column (``comment``; the survey core
  has no code-name option — the column name is kept and the code renders
  gray). Replies are their own rows with a ``→ `` nesting prefix in the
  author column; only the first 300 comments are imported (the result
  note names the total). The result dict carries ``mode:
  "youtube-structured"`` + the counts and is recorded in the audit log.
  Fallbacks (legacy behavior, with a clear fallback marker): the comment
  list is empty (captions-only / no comments), the structured import
  fails (the comment table itself becomes the CSV so nothing is lost),
  extraction aborts/times out, or the installed yt-dlp predates comment
  extraction (2021.12.17) — the comment thread is then rendered as a
  proper RFC-4180 CSV file (``author,likes,date,comment`` header row,
  one row per comment). The CSV layout is the machine-readable contract:
  every row has exactly four fields written through the stdlib ``csv``
  module — cells containing commas or quotes are quoted (embedded quotes
  doubled), tabs/newlines inside a cell collapse to spaces, and missing
  likes/dates render as ``-``. The source contains ONLY the comments
  table — no title/uploader/duration/description header block. Comments
  are the primary content; caption tracks are NEVER substituted
  silently. When a video provably has no comments the table keeps the
  header row and a ``-,-,-,No comments`` row. When comments were
  REQUESTED but could not be retrieved (extraction timed out or aborted,
  or an empty comment list) and no captions exist, the same header row
  is kept with a ``-,-,-,<note>`` row explaining the missing columns;
  when caption text exists it is shown instead of the table as a
  ``# Comments unavailable (<reason>) — captions shown below`` note row
  followed by one row per transcript line (no header). If the installed
  yt-dlp predates comment extraction (2021.12.17) the header +
  ``-,-,-,<note>`` row is printed and captions are not fetched either.
- ``article`` — page fetched with urllib, cleaned with trafilatura
  (falling back to the project's own ``html_to_text``).
- ``html``    — offline snapshot: the page HTML with same-origin
  stylesheets inlined into ``<style>`` blocks and same-origin images
  and fonts inlined as ``data:`` URIs — one self-contained ``.html``
  file that renders without network access (scripts are never inlined
  or executed).
- ``pdf``     — page fetched with urllib and rendered to a PDF document
  with PyMuPDF's Story engine (mirroring the ``GET /sources/{id}/pdf``
  export; a text-only fallback PDF when the layout render fails). Stored
  as a ``.pdf`` source the PdfCoder can open.
"""

from __future__ import annotations

import asyncio
import base64
import concurrent.futures
import concurrent.futures.thread
import csv
import html
import io
import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import weakref
from collections.abc import Callable, Coroutine, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, TypeVar
from urllib.parse import urljoin, urlparse

import trafilatura
import yt_dlp
from sqlalchemy.ext.asyncio import async_sessionmaker

logger = logging.getLogger(__name__)

_T = TypeVar("_T")

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 QCnext/0.2.0"
)
FETCH_TIMEOUT = 45

#: Reddit's anonymous ``.json`` endpoint requires a UNIQUE, descriptive
#: User-Agent ("please use a unique User-Agent" / "whoa there, pardner").
#: Browser-spoofing UAs and empty/generic UAs are blocked (403) and
#: rate-limited (429) much faster. Used for BOTH the anonymous path and
#: the OAuth token/list requests (Reddit inspects it on every call).
REDDIT_USER_AGENT = "QCnext/0.2.0 (+contact@example.org)"

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

    def __init__(
        self,
        message: str,
        *,
        code: int | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        """``code`` carries the HTTP status when the failure came from a
        server; ``headers`` carries the response headers (lower-cased names)
        so callers can honor e.g. ``Retry-After`` on a 429."""
        super().__init__(message)
        self.code = code
        self.headers = headers


@dataclass(frozen=True)
class ScrapedContent:
    """A page/thread/video reduced to a file ready for the import pipeline.

    ``structured`` carries the result dict of a structured import (YouTube
    comments as cases/attributes/coded sources) or the fallback marker:
    ``None`` when the scrape ran in plain file mode.
    """

    filename: str
    data: bytes
    mode: str
    structured: dict | None = None


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


def fetch_url(
    url: str,
    timeout: int = FETCH_TIMEOUT,
    *,
    user_agent: str = USER_AGENT,
    extra_headers: Mapping[str, str] | None = None,
    method: str | None = None,
    data: bytes | None = None,
) -> bytes:
    """Fetch a URL (redirects followed), mapping HTTP/network failures to
    ``ScrapeError`` (with the status ``code`` and response ``headers``).

    ``user_agent`` overrides the default browser-like UA (Reddit's
    ``.json`` endpoint requires a unique descriptive app UA);
    ``extra_headers`` are merged over the defaults; ``method``/``data``
    build custom requests (the OAuth token POST).
    """
    headers = {
        "User-Agent": user_agent,
        "Accept": "text/html,application/xhtml+xml,application/json,*/*;q=0.8",
    }
    if extra_headers:
        headers.update(extra_headers)
    request = urllib.request.Request(url, headers=headers, method=method, data=data)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except urllib.error.HTTPError as err:
        raise ScrapeError(
            f"server returned HTTP {err.code} for {url}",
            code=err.code,
            headers={k.lower(): v for k, v in err.headers.items()},
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

#: Host order for the anonymous path: ``www`` first, ``old`` as the
#: fallback — the two surfaces Reddit's network-policy block hits least.
_REDDIT_ANON_HOSTS = ("www.reddit.com", "old.reddit.com")

#: App-only OAuth endpoints (Reddit OAuth2 wiki, August 2026).
_REDDIT_TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
_REDDIT_OAUTH_HOST = "oauth.reddit.com"

#: 429 default/cap: Reddit usually sends a numeric ``Retry-After``; a
#: missing/unparseable value falls back to the default, and a hostile
#: value cannot stall the scrape beyond the cap.
_REDDIT_RETRY_DEFAULT_SECONDS = 60
_REDDIT_RETRY_MAX_SECONDS = 60

_REDDIT_403_MESSAGE = (
    "Reddit blocked anonymous access (403) — configure Reddit API "
    "credentials in Settings for reliable access, or retry later."
)
_REDDIT_429_MESSAGE = (
    "Reddit rate-limited (429) — wait a moment and try again, or "
    "configure Reddit API credentials in Settings"
)
_REDDIT_CREDENTIALS_MESSAGE = (
    "Reddit rejected the API credentials (HTTP {code}) — check the "
    "client ID and secret in Settings"
)


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


def _reddit_anon_candidates(url: str) -> list[str]:
    """The thread URL on each anonymous host as a ``.json`` URL.

    Host order is ``www`` first, ``old`` second — the fallback surface
    for the network-policy 403 block.
    """
    parsed = urlparse(url)
    return [
        _reddit_json_url(parsed._replace(netloc=host).geturl())
        for host in _REDDIT_ANON_HOSTS
    ]


def _reddit_retry_after_seconds(headers: Mapping[str, str] | None) -> int:
    """Seconds to wait before a 429 retry, from the ``Retry-After`` header.

    Reddit sends a numeric number of seconds; an unparseable value (e.g.
    the rare HTTP-date form) falls back to the default, and the value is
    capped so a hostile/erroneous header cannot stall the scrape.
    """
    if headers:
        value = headers.get("retry-after") or headers.get("Retry-After") or ""
        try:
            return min(max(1, int(value)), _REDDIT_RETRY_MAX_SECONDS)
        except (TypeError, ValueError):
            pass
    return _REDDIT_RETRY_DEFAULT_SECONDS


def _reddit_fetch_with_429_retry(url: str) -> bytes:
    """Fetch an anonymous Reddit URL with one Retry-After-aware 429 retry.

    The first 429 sleeps for the ``Retry-After`` duration and retries
    once; a second 429 surfaces the clear rate-limit error (other errors
    propagate untouched).
    """
    try:
        return fetch_url(url, user_agent=REDDIT_USER_AGENT)
    except ScrapeError as first:
        if first.code != 429:
            raise
        delay = _reddit_retry_after_seconds(first.headers)
        logger.warning("Reddit rate-limited (429) %s — retrying in %ss", url, delay)
        time.sleep(delay)
        try:
            return fetch_url(url, user_agent=REDDIT_USER_AGENT)
        except ScrapeError as second:
            if second.code == 429:
                raise ScrapeError(_REDDIT_429_MESSAGE) from second
            raise


def _reddit_fetch_anonymous(url: str) -> bytes:
    """Fetch an anonymous ``.json`` thread: ``www`` then ``old`` host.

    A 403 (Reddit's network-policy block) moves on to the next host; any
    other error propagates. When every host is blocked the final error
    mentions the optional OAuth configuration.
    """
    blocked: list[ScrapeError] = []
    for candidate in _reddit_anon_candidates(url):
        try:
            return _reddit_fetch_with_429_retry(candidate)
        except ScrapeError as err:
            if err.code != 403:
                raise
            blocked.append(err)
    raise ScrapeError(_REDDIT_403_MESSAGE) from (blocked[-1] if blocked else None)


def _reddit_oauth_token(client_id: str, client_secret: str) -> str:
    """App-only access token via the ``client_credentials`` grant.

    ``POST https://www.reddit.com/api/v1/access_token`` with HTTP Basic
    auth (``client_id:client_secret``) and a form-encoded
    ``grant_type=client_credentials`` body. Per Reddit's OAuth2 wiki no
    ``scope`` parameter is sent for app-only tokens — the app's
    configured scopes apply (script apps get ``read``). Tokens live one
    hour and app-only tokens never receive a refresh token, so one is
    fetched per scrape (cheap).
    """
    auth = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode("ascii")
    body = urllib.parse.urlencode({"grant_type": "client_credentials"}).encode("ascii")
    try:
        raw = fetch_url(
            _REDDIT_TOKEN_URL,
            user_agent=REDDIT_USER_AGENT,
            method="POST",
            data=body,
            extra_headers={
                "Authorization": f"Basic {auth}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
    except ScrapeError as err:
        if err.code in (400, 401, 403):
            raise ScrapeError(
                _REDDIT_CREDENTIALS_MESSAGE.format(code=err.code)
            ) from err
        if err.code == 429:
            raise ScrapeError(_REDDIT_429_MESSAGE) from err
        raise
    try:
        payload = json.loads(raw.decode("utf-8", errors="replace"))
    except ValueError as err:
        raise ScrapeError("Reddit token response is not JSON") from err
    token = payload.get("access_token") if isinstance(payload, dict) else None
    if not isinstance(token, str) or not token:
        detail = payload.get("error") if isinstance(payload, dict) else None
        raise ScrapeError(
            "Reddit rejected the API credentials "
            f"({detail or 'no access_token in response'}) — check the "
            "client ID and secret in Settings"
        )
    return token


def _reddit_oauth_url(url: str) -> str:
    """The thread URL on ``oauth.reddit.com`` (no ``.json`` suffix needed)."""
    parsed = urlparse(_reddit_normalize_host(url))
    path = parsed.path.rstrip("/") or "/"
    if path.endswith(".json"):
        path = path[: -len(".json")] or "/"
    return parsed._replace(netloc=_REDDIT_OAUTH_HOST, path=path).geturl()


def _reddit_fetch_oauth(url: str, token: str) -> bytes:
    """Fetch an authenticated thread listing with ``Authorization: Bearer``."""
    try:
        return fetch_url(
            url,
            user_agent=REDDIT_USER_AGENT,
            extra_headers={"Authorization": f"Bearer {token}"},
        )
    except ScrapeError as err:
        if err.code == 403:
            raise ScrapeError(
                "Reddit rejected the OAuth request (403) — the API token "
                "may lack the read scope, or the subreddit is private"
            ) from err
        if err.code == 429:
            raise ScrapeError(_REDDIT_429_MESSAGE) from err
        raise


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
    """Fetch a Reddit submission + comments (anonymous ``.json`` or OAuth).

    When ``reddit_client_id`` AND ``reddit_client_secret`` are configured
    in the user settings the scraper uses Reddit's app-only
    ``client_credentials`` OAuth flow (token via HTTP Basic auth, then
    ``oauth.reddit.com`` with a Bearer token). Otherwise the anonymous
    path runs: ``www.reddit.com`` then ``old.reddit.com`` ``.json`` with
    a unique descriptive User-Agent, a single Retry-After-aware 429
    retry, and a 403 mapped to a message that points at the optional
    credentials.
    """
    from qualcoder_api.services.user_settings import get_reddit_credentials

    credentials = get_reddit_credentials()
    client_id = credentials.get("client_id") or ""
    client_secret = credentials.get("client_secret") or ""
    if client_id and client_secret:
        raw = _reddit_fetch_oauth(
            _reddit_oauth_url(url), _reddit_oauth_token(client_id, client_secret)
        )
    else:
        raw = _reddit_fetch_anonymous(url)
    return _reddit_parse(raw, url)


def _reddit_parse(raw: bytes, url: str) -> ScrapedContent:
    """Parse a fetched Reddit JSON payload into the thread text source."""
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

#: Header row of the comment CSV — the first row of every table-shaped
#: scrape; every following row has exactly four fields. RFC-4180 quoting
#: is done by the stdlib ``csv`` module so the file opens directly in any
#: spreadsheet.
_COMMENT_HEADER = ("author", "likes", "date", "comment")

#: Structured import layout: the four CSV contract columns become one case
#: column (unique per comment) plus three case attributes and the
#: qualitative ``comment`` column — one text source per row, coded with a
#: code named after the column (the survey row-import core names codes
#: after their column and has no code-name option, so the column name is
#: kept and documented).
_YT_STRUCTURED_HEADERS = ("case", "author", "likes", "date", "comment")
_YT_QUALITATIVE_HEADER = "comment"

#: Cap for the structured import — YouTube comment threads can run into
#: the thousands; importing all of them would swamp the project with
#: cases and sources. Only the FIRST comments (in the order yt-dlp
#: returned them) are imported; the result note names the total.
_YT_COMMENT_CAP = 300


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


#: When False, ``--write-comments`` is not requested and the scraper
#: reports the ``No comments`` row (captions are not fetched either).
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
    """``like_count`` -> ``"N likes"`` (``-`` when the field is missing)."""
    count = _as_int(value)
    if count is None:
        return "-"
    return f"{count:,} likes"


def _format_comment_timestamp(value: object) -> str:
    """Unix epoch seconds -> ``YYYY-MM-DD HH:MM`` UTC (``-`` when unknown)."""
    ts = _as_int(value)
    if ts is None:
        return "-"
    try:
        return datetime.fromtimestamp(ts, tz=UTC).strftime("%Y-%m-%d %H:%M")
    except (OverflowError, OSError, ValueError):
        return "-"


def _normalize_column(value: str) -> str:
    """Collapse tabs/newlines to spaces so one comment stays a single row."""
    return re.sub(r"[\t\r\n]+", " ", value).strip()


def _comment_row(author: str, likes: str, date: str, text: str) -> tuple[str, str, str, str]:
    """The four cells of one comment row, normalized for CSV output.

    Cells are passed through ``_normalize_column`` so one comment always
    stays a single row; the ``csv`` writer then quotes any cell containing
    commas or quotes (doubling embedded quotes) when the row is rendered.
    """
    return (
        _normalize_column(author),
        _normalize_column(likes),
        _normalize_column(date),
        _normalize_column(text),
    )


def _render_csv(rows: list[tuple[str, str, str, str]], *, header: bool = True) -> str:
    """RFC-4180 CSV text: the ``author,likes,date,comment`` header row plus
    one row per comment, joined with CRLF line endings.

    Every row is written through the stdlib ``csv`` writer with minimal
    quoting: cells containing commas, quotes or line breaks are wrapped in
    quotes and embedded quotes are doubled, so the file opens directly in
    any spreadsheet. ``header=False`` renders a bare cell block — the
    caption fallback, where the column header would be misleading.
    """
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer)
    if header:
        writer.writerow(_COMMENT_HEADER)
    writer.writerows(rows)
    return buffer.getvalue()


def _comment_lines(comment: dict, depth: int) -> list[tuple[str, str, str, str]]:
    """Render one comment plus its nested ``replies`` as CSV rows.

    Each row is ``(author, likes, date, comment)`` with exactly four cells.
    Replies are their own row with a ``→ `` prefix (one per depth level)
    in the author column only; missing likes/dates render as ``-``.
    """
    lines: list[tuple[str, str, str, str]] = []
    text = _normalize_column(comment.get("text") or "")
    if text:
        author = _normalize_column(comment.get("author") or "") or "unknown"
        if depth:
            author = "→ " * depth + author
        lines.append(
            _comment_row(
                author,
                _format_likes(comment.get("like_count")),
                _format_comment_timestamp(comment.get("timestamp")),
                text,
            )
        )
    replies = comment.get("replies")
    if isinstance(replies, list):
        for reply in replies:
            if isinstance(reply, dict):
                lines.extend(_comment_lines(reply, depth + 1))
    return lines


def _youtube_comments(info: dict) -> list[tuple[str, str, str, str]]:
    """Flatten the comment list into CSV rows; replies get a ``→ `` nesting
    prefix in the author column (one per depth level).

    Handles both yt-dlp layouts defensively: nested ``replies`` lists
    (``{author, text, timestamp, like_count, replies: [...]}``) and the
    flat list where every comment carries ``id``/``parent`` references.
    Missing fields fall back to ``unknown`` / ``-``.
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
    lines: list[tuple[str, str, str, str]] = []
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
#: Matches the frontend dialog's 240s wait so a real comment extraction on a
#: large thread can finish; the per-call executor already prevents wedging,
#: so a long extraction only costs this call.
_YT_TIMEOUT_SECONDS = 240
#: Shown when yt-dlp signals an internal abort (never a "real" failure).
_YT_ABORT_MESSAGE = (
    "YouTube extraction was interrupted — try again, or import the "
    "video page as 'Article' mode instead"
)
_YT_TIMEOUT_MESSAGE = (
    f"YouTube extraction timed out after {_YT_TIMEOUT_SECONDS} seconds — "
    "try again, or import the video page as 'Article' mode instead"
)
#: Notes used when comments were REQUESTED but did not come back — the
#: output must explain the missing columns, never silently substitute
#: captions. Without captions the note becomes the ``-,-,-,<note>`` row
#: under the table header; with captions it leads as a ``#`` note row.
_YT_COMMENTS_TIMEOUT_NOTE = (
    "Comments could not be retrieved (extraction timed out) — the "
    "video may have comments disabled or be very large"
)
_YT_COMMENTS_ABORT_NOTE = (
    "Comments could not be retrieved (extraction aborted) — the "
    "video may have comments disabled or be very large"
)
_YT_COMMENTS_UNSUPPORTED_NOTE = (
    "Comments could not be retrieved (the installed yt-dlp version "
    "does not support comment extraction — 2021.12.17 or newer is required)"
)
#: ``<reason>`` in the ``# Comments unavailable (<reason>) — captions shown
#: below`` line when caption text is shown instead of the table.
_YT_COMMENTS_CAPTION_REASONS = {
    "aborted": "extraction aborted",
    "empty": "the video has no comments",
}
#: Markers some platforms report through ``DownloadError`` when yt-dlp
#: aborts (e.g. "signal aborted without reason") instead of raising.
_YT_ABORT_MARKERS = ("signal aborted", "aborted", "interrupted")


def _yt_subprocess_enabled() -> bool:
    """True when yt-dlp can run as a subprocess (``sys.executable -m yt_dlp``).

    A PyInstaller-frozen build sets ``sys.frozen`` and runs from the app
    exe (``qualcoder-backend.exe``) — NOT a Python interpreter — so ``-m
    yt_dlp`` can never work there and the in-process fallback is the only
    option. Everything else (dev, tests, server venv) runs yt-dlp in a
    subprocess.
    """
    return not getattr(sys, "frozen", False)


#: The in-process path is a PyInstaller-frozen fallback: ``sys.executable
#: -m yt_dlp`` cannot work inside the packaged exe, so frozen builds run
#: yt-dlp in-process (with the abort guards below). Everything else runs
#: yt-dlp in a SUBPROCESS, which isolates its internal signals
#: (KeyboardInterrupt/SystemExit raised out of ``extract_info``, SIGINT/
#: SIGTERM delivery, "signal aborted without reason" aborts) — they can no
#: longer propagate into the backend process and surface only as clean
#: exit codes, and a hung extraction can be killed hard instead of leaving
#: an unkillable thread behind.
_YT_SUBPROCESS_ENABLED = _yt_subprocess_enabled()


class _YouTubeAbortError(ScrapeError):
    """yt-dlp's internal abort signal surfaced as a retryable error."""


class _YouTubeTimeoutError(ScrapeError):
    """yt-dlp exceeded the extraction timeout (fatal for this call)."""


def _is_yt_abort(err: BaseException) -> bool:
    """True when a yt-dlp error is the internal abort signal, not a real failure."""
    message = str(err).lower()
    return any(marker in message for marker in _YT_ABORT_MARKERS)


def _yt_cli_command(url: str, getcomments: bool) -> list[str]:
    """Build the yt-dlp CLI command for a metadata-only extraction.

    ``--dump-single-json`` prints the sanitized info dict as JSON on
    stdout; ``--no-progress`` keeps progress bars out of stderr. Comments
    are included ONLY when ``--write-comments`` is passed (the CLI
    defaults it to False; ``--getcomments`` is NOT a valid flag — optparse
    rejects it as "no such option" and the subprocess dies). The URL is
    isolated behind ``--`` so it can never be parsed as an option.
    """
    command = [
        sys.executable,
        "-m",
        "yt_dlp",
        "--dump-single-json",
        "--no-download",
        "--no-playlist",
        "--no-warnings",
        "--no-progress",
        "--socket-timeout",
        "30",
    ]
    if getcomments:
        command.append("--write-comments")
    command.extend(["--", url])
    return command


def _yt_parse_dump(stdout: bytes) -> dict:
    """Parse the ``--dump-single-json`` stdout into an info dict."""
    try:
        info = json.loads(stdout.decode("utf-8", errors="replace"))
    except ValueError as err:
        raise ScrapeError("YouTube returned no metadata") from err
    if isinstance(info, dict) and info.get("_type") in ("playlist", "multi_video"):
        entries = info.get("entries")
        info = entries[0] if isinstance(entries, list) and entries else {}
    if not isinstance(info, dict) or not info:
        raise ScrapeError("YouTube returned no metadata")
    return info


def _yt_subprocess_error(stderr: bytes) -> str | None:
    """The last ``ERROR:`` line yt-dlp wrote to stderr (its failure detail)."""
    text = stderr.decode("utf-8", errors="replace")
    for line in reversed(text.splitlines()):
        if "ERROR:" in line:
            return line.split("ERROR:", 1)[1].strip()
    return None


def _yt_subprocess_is_abort(returncode: int, stderr: bytes) -> bool:
    """Map a yt-dlp subprocess exit onto the internal-abort bucket.

    yt-dlp's CLI turns a ``KeyboardInterrupt`` into ``SystemExit(1)`` with
    "ERROR: Interrupted by user" on stderr, and a cancelled download into
    exit 101 ("Aborting remaining downloads"). Signal deaths (negative
    return codes on POSIX) count as aborts too.
    """
    if returncode == 101 or returncode < 0:
        return True
    if returncode != 1:
        return False
    text = stderr.decode("utf-8", errors="replace").lower()
    return "interrupted" in text or "aborting" in text


def _yt_extract_subprocess(url: str, getcomments: bool) -> dict:
    """Run yt-dlp in a separate process; parse the JSON info from stdout.

    A subprocess fully isolates yt-dlp's internal signal handling: any
    KeyboardInterrupt/SystemExit it raises inside ``extract_info`` is
    caught by its own CLI and becomes an exit code, never an exception in
    this process. On timeout the child is killed hard (it cannot linger as
    an unkillable thread), and ``CREATE_NO_WINDOW`` keeps the packaged app
    from flashing a console window on Windows.
    """
    if getattr(sys, "frozen", False):
        # Defense in depth: a frozen build has no ``python.exe``, so this
        # command would launch the app exe itself (``qualcoder-backend.exe
        # -m yt_dlp``). ``_yt_dlp_extract`` already skips this path there,
        # but never let it run even if it is misrouted — the OSError
        # triggers the in-process fallback.
        raise OSError("no Python interpreter available in a frozen build")
    command = _yt_cli_command(url, getcomments)
    logger.debug("Running yt-dlp subprocess (%s comments)", "with" if getcomments else "without")
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            timeout=_YT_TIMEOUT_SECONDS,
            creationflags=creationflags,
        )
    except subprocess.TimeoutExpired as err:
        raise _YouTubeTimeoutError(_YT_TIMEOUT_MESSAGE) from err
    if completed.returncode == 0:
        return _yt_parse_dump(completed.stdout)
    detail = _yt_subprocess_error(completed.stderr)
    if _yt_subprocess_is_abort(completed.returncode, completed.stderr):
        raise _YouTubeAbortError(_YT_ABORT_MESSAGE)
    raise ScrapeError(
        f"YouTube extraction failed: {detail or f'exit code {completed.returncode}'}"
    )


class _FallbackExecutor(concurrent.futures.ThreadPoolExecutor):
    """Single-slot executor whose worker thread is a daemon.

    A timed-out yt-dlp call keeps its worker thread alive (threads cannot
    be killed — it lingers inside yt-dlp until the network unwinds). Every
    fallback call gets its OWN instance, so one stuck extraction can never
    block the next scrape's slot; and the daemon worker means it can never
    block the packaged app's interpreter shutdown either.
    """

    def _adjust_thread_count(self):
        if self._idle_semaphore.acquire(timeout=0):
            return

        def weakref_cb(_, q=self._work_queue):
            q.put(None)

        num_threads = len(self._threads)
        if num_threads < self._max_workers:
            thread_name = f"{self._thread_name_prefix or self}_{num_threads}"
            thread = threading.Thread(
                name=thread_name,
                target=concurrent.futures.thread._worker,
                args=(
                    weakref.ref(self, weakref_cb),
                    self._work_queue,
                    self._initializer,
                    self._initargs,
                ),
            )
            thread.daemon = True
            thread.start()
            self._threads.add(thread)
            concurrent.futures.thread._threads_queues[thread] = self._work_queue


def _yt_extract_fallback_sync(url: str, getcomments: bool) -> dict:
    """In-process yt-dlp fallback for frozen (PyInstaller) builds.

    Kept from the previous in-process design: yt-dlp can abort long
    extractions (e.g. huge comment threads) by raising
    ``KeyboardInterrupt``/``SystemExit`` out of ``extract_info`` — or a
    ``DownloadError`` naming the abort on some platforms. Both are mapped
    to a friendly, actionable ``ScrapeError`` instead of the raw signal
    propagating into the import pipeline.
    """
    options = {
        "noplaylist": True,
        "skip_download": True,
        "writesubtitles": False,
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": 30,
    }
    if getcomments:
        options["getcomments"] = True
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


def _yt_extract_fallback(url: str, getcomments: bool) -> dict:
    """Run the in-process fallback off-loop with an abort + timeout guard.

    The yt-dlp call runs in a per-call single-slot executor under
    ``asyncio.wait_for`` so a hung network cannot block the import: the
    timeout surfaces a friendly error. A timed-out call's worker thread
    lingers inside yt-dlp until the network unwinds, but because every
    call gets its own daemon-slot executor, a stuck extraction never
    blocks a later scrape's slot or interpreter shutdown. When no event
    loop is running (the API's worker thread, unit tests) the guard drives
    its own loop; inside an async caller the guard runs on a private loop
    in a thread so the caller's loop is never blocked.
    """

    async def _guarded() -> dict:
        loop = asyncio.get_running_loop()
        return await asyncio.wait_for(
            loop.run_in_executor(
                _FallbackExecutor(max_workers=1, thread_name_prefix="yt-extract"),
                _yt_extract_fallback_sync,
                url,
                getcomments,
            ),
            timeout=_YT_TIMEOUT_SECONDS,
        )

    def _run_guarded() -> dict:
        try:
            return asyncio.run(_guarded())
        except TimeoutError as err:
            raise _YouTubeTimeoutError(_YT_TIMEOUT_MESSAGE) from err

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return _run_guarded()

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(_run_guarded)
        try:
            return future.result(timeout=_YT_TIMEOUT_SECONDS + 15)
        except TimeoutError as err:
            raise _YouTubeTimeoutError(_YT_TIMEOUT_MESSAGE) from err


def _yt_dlp_extract(url: str, getcomments: bool) -> dict:
    """Extract video metadata (+ comments when requested) from a URL.

    The subprocess path is the default: it isolates yt-dlp's internal
    signals completely and can be killed on timeout. When the subprocess
    cannot be used (PyInstaller-frozen package, ``sys.executable -m
    yt_dlp`` unavailable) or fails to start, the in-process fallback runs
    with its abort + timeout guards instead. The returned info dict carries
    a ``_qc_comments_requested`` marker so the caller can prove whether
    comments were actually requested before choosing a caption fallback.
    The marker records the LAST call's flag: when ``scrape_youtube`` retries
    an abort without comments, the retried info says False even though the
    original request asked for comments — the caller keeps that intent
    separately.
    """
    if _YT_SUBPROCESS_ENABLED and not getattr(sys, "frozen", False):
        try:
            info = _yt_extract_subprocess(url, getcomments)
        except (OSError, subprocess.SubprocessError) as err:
            logger.warning(
                "yt-dlp subprocess failed to start (%s) — falling back to in-process", err
            )
            info = _yt_extract_fallback(url, getcomments)
    else:
        info = _yt_extract_fallback(url, getcomments)
    info["_qc_comments_requested"] = getcomments
    return info


# ----------------------------------------------------------------------
# YouTube — structured import (cases + attributes + coded comment sources)
# ----------------------------------------------------------------------

def _run_async_guarded(make_coro: Callable[[], Coroutine[Any, Any, _T]]) -> _T:
    """Run ``make_coro()`` on a private event loop, safe from any context.

    ``scrape_youtube`` runs inside the API's ``asyncio.to_thread`` worker
    or a plain test call — neither has a running loop, so ``asyncio.run``
    drives the async import there. When a loop IS running (defensive
    call), the coroutine is created inside a worker thread so it still
    completes on its own loop. aiosqlite connections are loop-agnostic,
    so sessions created on a private loop stay usable afterwards.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(make_coro())
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(lambda: asyncio.run(make_coro())).result()


async def _import_youtube_comments(
    session_factory: async_sessionmaker,
    rows: list[tuple[str, str, str, str]],
    *,
    title_base: str,
    project_path: str,
) -> dict:
    """Import comment rows through the survey row-import core.

    The table carries the four CSV contract columns as its fields: the
    ``case`` column (first — holds the unique case name), then ``author``,
    ``likes``, ``date`` and the qualitative ``comment`` column. The survey
    core turns every row into a case, the non-qualitative columns into
    case attribute types (text), and the ``comment`` column into one text
    source per row (``<case name>_comment``) linked to the case and coded
    with a code named after the column — ``comment`` — because the core
    names codes after their column and has no code-name option (the code
    is gray, no category). Replies carry their ``→ `` nesting prefix in
    the author column; missing likes/dates render as ``-``.
    """
    from qualcoder_api.interchange.importers import _import_survey_rows
    from qualcoder_api.services.user_settings import resolve_owner

    headers = list(_YT_STRUCTURED_HEADERS)
    data = [
        [f"{title_base} — Comment {index}", author, likes, date, text]
        for index, (author, likes, date, text) in enumerate(rows, start=1)
    ]
    return await _import_survey_rows(
        session_factory,
        headers,
        data,
        resolve_owner(None),
        qualitative_headers=[_YT_QUALITATIVE_HEADER],
        pseudonyms_dir=str(project_path),
    )


def _record_scrape_audit(session_factory: async_sessionmaker, detail: dict) -> None:
    """Record the structured-import outcome in the project's audit log.

    One ``scrape.import`` row carrying the full result dict (mode + counts,
    or the fallback marker) — the same pattern the interchange importers
    use for their result dicts.
    """

    def _make() -> Coroutine[Any, Any, None]:
        async def _record() -> None:
            from qualcoder_api.services import audit
            from qualcoder_api.services.user_settings import get_codername

            async with session_factory() as session:
                await audit.record(
                    session,
                    user=get_codername(),
                    action="scrape.import",
                    entity="source",
                    detail=detail,
                )

        return _record()

    return _run_async_guarded(_make)


def _youtube_csv_fallback(
    title_base: str,
    text: str,
    *,
    session_factory: async_sessionmaker | None,
    fallback: str | None,
) -> ScrapedContent:
    """Assemble a CSV-mode result — the legacy plain-text source.

    When ``session_factory`` is given the structured import was attempted;
    the result dict then carries the ``fallback`` marker and is recorded
    in the project's audit log so the reason is never silent.
    """
    structured = None
    if session_factory is not None and fallback:
        structured = {"mode": "youtube", "fallback": fallback}
        _record_scrape_audit(session_factory, structured)
    return ScrapedContent(
        filename=f"{sanitize_name(title_base, 'youtube-video')}.csv",
        data=text.encode("utf-8"),
        mode="youtube",
        structured=structured,
    )


def _structured_project() -> dict:
    """Keyword args of the currently OPEN project for the structured import.

    ``{}`` when no project is open — the scraper then falls back to the
    plain CSV text source. The project service lives in
    ``qualcoder_api.main`` (the same process-wide lookup the API's
    ``ServiceDep`` uses); the import is lazy so this module never creates
    an import cycle.
    """
    from qualcoder_api.main import service

    if service.session_factory is not None and service.project_path:
        return {
            "session_factory": service.session_factory,
            "project_path": service.project_path,
        }
    return {}


def scrape_youtube(
    url: str,
    *,
    session_factory: async_sessionmaker | None = None,
    project_path: str | None = None,
) -> ScrapedContent:
    """Extract the comment thread as STRUCTURED data, or as a CSV text source.

    Structured mode is the default when a project is open — ``scrape_url``
    passes the open project's ``session_factory`` + ``project_path`` (the
    API runs the scrape in an ``asyncio.to_thread`` worker; a plain call
    without them keeps the legacy CSV behavior). Every comment becomes a
    case named ``<video title> — Comment <n>`` with the ``author``,
    ``likes`` and ``date`` case attributes (text; ``-`` when missing), and
    the comment text becomes an analyzable text source
    (``<case name>_comment``) linked to the case and coded with a code
    named ``comment`` (the survey row-import core names codes after their
    column — it has no code-name option — and renders the code gray,
    without a category). Replies are their own rows with the ``→ `` nesting
    prefix in the author column only. Only the first ``_YT_COMMENT_CAP``
    comments are imported; the result note says e.g. ``first 300 of 512
    comments imported``. The result dict (``ScrapedContent.structured``
    and the project's audit log) carries ``mode: "youtube-structured"``
    plus the counts (``cases``, ``attributes``, ``files``, ``codings``,
    ``comments_total``, ``comments_imported``, ``attribute_types``).

    FALLBACKS — the legacy CSV-text source (``_render_csv``) with a clear
    fallback marker in the result/audit whenever the structured import
    cannot run:
    - the comment list is empty (captions-only / no comments / extraction
      aborted or unsupported) — the existing caption- or note-CSV;
    - the structured import itself fails — the comment table stays the CSV
      so no comments are lost.

    When the structured import succeeds the returned ``data`` is empty
    (the API's file-import pipeline still registers the empty ``.csv``
    row, but the comments themselves live in the structured
    cases/sources — never in a text file).

    Extraction runs in a SEPARATE yt-dlp subprocess (the in-process path
    is the PyInstaller-frozen fallback only), so yt-dlp's internal abort
    signal can never propagate into the backend process. The first abort
    is retried once WITHOUT ``--write-comments`` so the import survives
    with an explanatory note; a second abort — or a timeout when comments
    were not requested — surfaces a friendly error. A timeout when
    comments WERE requested keeps the header row plus the ``-,-,-,
    <note>`` row (no info dict came back, so captions cannot be fetched
    either).
    """
    getcomments = _YT_DLP_COMMENTS_SUPPORTED
    comments_failure: str | None = None
    try:
        info = _yt_dlp_extract(url, getcomments)
    except _YouTubeAbortError:
        if not getcomments:
            raise
        # Comment extraction can abort on very large threads — retry once
        # with metadata only. Comments were still requested, so the output
        # below must explain their absence; captions are never substituted
        # silently.
        logger.warning(
            "YouTube comment extraction aborted for %s — retrying without comments", url
        )
        comments_failure = "aborted"
        info = _yt_dlp_extract(url, False)
    except _YouTubeTimeoutError:
        if not getcomments:
            raise
        # The comment extraction exceeded the timeout and no info dict came
        # back, so captions cannot be fetched either: keep the table header
        # and explain the missing columns instead of failing or substituting
        # captions silently.
        logger.warning("YouTube comment extraction timed out for %s", url)
        text = _render_csv([("-", "-", "-", _YT_COMMENTS_TIMEOUT_NOTE)])
        return _youtube_csv_fallback(
            "", text,
            session_factory=session_factory,
            fallback="extraction timed out",
        )
    if not isinstance(info, dict):
        raise ScrapeError("YouTube returned no metadata")

    title = (info.get("title") or "").strip() or "youtube-video"
    title_base = sanitize_name(title, "youtube-video")

    # Comments were requested either way — the original call, or the abort
    # retry that ran metadata-only (its marker reads False): a missing
    # comment list must always be explained in the output.
    comments_requested = getcomments or bool(info.get("_qc_comments_requested"))
    rows: list[tuple[str, str, str, str]] = []
    if comments_requested:
        rows = _youtube_comments(info)

    # Structured import: every comment becomes a case with attributes and a
    # coded text source through the survey row-import core.
    if rows and session_factory is not None and project_path:
        capped = rows[:_YT_COMMENT_CAP]
        note = (
            f"first {len(capped)} of {len(rows)} comments imported"
            if len(capped) < len(rows)
            else None
        )
        try:
            result = _run_async_guarded(
                lambda: _import_youtube_comments(
                    session_factory, capped, title_base=title_base, project_path=project_path
                )
            )
        except Exception as err:  # the CSV fallback keeps the comments
            logger.warning("YouTube structured import failed for %s: %s", url, err)
            return _youtube_csv_fallback(
                title_base, _render_csv(rows),
                session_factory=session_factory,
                fallback=f"structured import failed: {err}",
            )
        result.update(
            {
                "mode": "youtube-structured",
                "comments_total": len(rows),
                "comments_imported": len(capped),
                "attribute_types": len(_YT_STRUCTURED_HEADERS) - 2,
            }
        )
        if note:
            result["note"] = note
        _record_scrape_audit(session_factory, result)
        return ScrapedContent(
            filename=f"{title_base}.csv",
            data=b"",
            mode="youtube-structured",
            structured=result,
        )

    fallback: str | None = None
    if rows:
        text = _render_csv(rows)
    elif _YT_DLP_COMMENTS_SUPPORTED:
        logger.warning("YouTube comments unavailable for %s", url)
        caption_text = _youtube_captions(info)
        if caption_text:
            reason = _YT_COMMENTS_CAPTION_REASONS[comments_failure or "empty"]
            note = f"# Comments unavailable ({reason}) — captions shown below"
            caption_rows = [(note, "", "", "")]
            caption_rows.extend(
                (_normalize_column(line), "", "", "") for line in caption_text.splitlines()
            )
            text = _render_csv(caption_rows, header=False)
            fallback = (
                f"comments unavailable ({reason})"
                if comments_failure
                else "the video has no comments"
            )
        elif comments_failure:
            rows = [("-", "-", "-", _YT_COMMENTS_ABORT_NOTE)]
            text = _render_csv(rows)
            fallback = "extraction aborted"
        else:
            rows = [("-", "-", "-", "No comments")]
            text = _render_csv(rows)
            fallback = "the video has no comments"
    else:
        logger.warning("YouTube comment extraction unsupported for %s", url)
        rows = [("-", "-", "-", _YT_COMMENTS_UNSUPPORTED_NOTE)]
        text = _render_csv(rows)
        fallback = "yt-dlp comment extraction unsupported"

    if not text.strip():
        raise ScrapeError("YouTube video contains no text")
    return _youtube_csv_fallback(
        title_base, text, session_factory=session_factory, fallback=fallback
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


# ----------------------------------------------------------------------
# Offline HTML snapshot (mode="html")
# ----------------------------------------------------------------------

#: Per-resource caps for the snapshot; a sub-resource that exceeds its cap
#: (or cannot be fetched) keeps its original URL instead of breaking the
#: capture. Data URIs keep the result a single self-contained file.
_HTML_CSS_MAX_BYTES = 2 * 1024 * 1024
_HTML_FONT_MAX_BYTES = 2 * 1024 * 1024
_HTML_IMAGE_MAX_BYTES = 1 * 1024 * 1024
_HTML_IMAGE_TOTAL_MAX_BYTES = 25 * 1024 * 1024

_IMAGE_MIME_BY_SUFFIX = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".svg": "image/svg+xml",
    ".webp": "image/webp",
    ".avif": "image/avif",
    ".bmp": "image/bmp",
    ".ico": "image/x-icon",
}
_FONT_MIME_BY_SUFFIX = {
    ".woff2": "font/woff2",
    ".woff": "font/woff",
    ".ttf": "font/ttf",
    ".otf": "font/otf",
    ".eot": "application/vnd.ms-fontobject",
}

#: Magic-byte sniffing for images served without a recognizable suffix.
_IMAGE_MAGIC = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
)

_SRC_ATTR_RE = re.compile(r"""\bsrc\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))""", re.IGNORECASE)


def _fetch_resource(url: str, max_bytes: int) -> bytes | None:
    """Fetch a snapshot sub-resource, honoring a byte cap.

    Returns ``None`` (leave the original URL in place) when the resource
    cannot be fetched or exceeds ``max_bytes``. Goes through the module's
    ``fetch_url`` so tests mock one spot for page + sub-resources alike.
    """
    try:
        data = fetch_url(url)
    except ScrapeError as err:
        logger.debug("snapshot: skipping %s (%s)", url, err)
        return None
    if len(data) > max_bytes:
        logger.debug("snapshot: skipping %s (%d bytes, cap %d)", url, len(data), max_bytes)
        return None
    return data


def _is_same_origin(page_url: str, resource_url: str) -> bool:
    """True when a resource URL is http(s) on the page's own origin."""
    page = urlparse(page_url)
    resource = urlparse(resource_url)
    return (
        resource.scheme in ("http", "https")
        and resource.scheme == page.scheme
        and resource.netloc.lower() == page.netloc.lower()
    )


def _url_suffix(url: str) -> str:
    return os.path.splitext(urlparse(url).path.lower())[1]


def _guess_image_mime(data: bytes, url: str) -> str | None:
    """MIME type for an image, from its suffix or magic bytes (None = unknown)."""
    known = _IMAGE_MIME_BY_SUFFIX.get(_url_suffix(url))
    if known:
        return known
    for magic, mime in _IMAGE_MAGIC:
        if data.startswith(magic):
            return mime
    if b"<svg" in data[:256].lower():
        return "image/svg+xml"
    return None


def _data_uri(data: bytes, mime: str) -> str:
    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"


def _rewrite_css_fonts(css: str, css_url: str, page_url: str) -> str:
    """Inline same-origin ``@font-face`` sources as ``data:`` URIs.

    URL resolution happens against the stylesheet's own URL (that is where
    relative CSS paths resolve); the same-origin check is against the page
    so cross-origin font CDNs are left as links. Only known font suffixes
    are inlined — background-image URLs keep their URLs.
    """
    font_re = re.compile(r"""url\(\s*(['"]?)(.*?)\1\s*\)""", re.IGNORECASE | re.DOTALL)

    def _replace(match: re.Match) -> str:
        quote, raw = match.group(1), match.group(2).strip()
        if raw.lower().startswith(("data:", "blob:", "javascript:")):
            return match.group(0)
        absolute = urljoin(css_url, raw)
        if not _is_same_origin(page_url, absolute):
            return match.group(0)
        mime = _FONT_MIME_BY_SUFFIX.get(_url_suffix(absolute))
        if mime is None:
            return match.group(0)
        data = _fetch_resource(absolute, _HTML_FONT_MAX_BYTES)
        if data is None:
            return match.group(0)
        return f'url("{_data_uri(data, mime)}")' if not quote else f"url('{_data_uri(data, mime)}')"

    return font_re.sub(_replace, css)


class _SnapshotRewriter(html.parser.HTMLParser):
    """Rewrite a fetched page into a self-contained offline snapshot.

    - Same-origin ``<link rel="stylesheet">`` -> ``<style>`` blocks, with
      same-origin ``@font-face`` sources inside the CSS inlined as data.
    - Same-origin ``<img src>`` -> ``data:`` URIs (per-image and total
      caps).
    - Scripts are NOT inlined or executed (view-only snapshot; the sandbox
      would not run them anyway) — ``<script src>`` tags stay as-is.
    - Cross-origin and oversized/failed resources keep their original URLs.

    Everything else (markup, attributes, entities) is re-emitted verbatim,
    so a page without sub-resources round-trips byte-for-byte.
    """

    def __init__(self, page_url: str) -> None:
        super().__init__(convert_charrefs=False)
        self._page_url = page_url
        self.parts: list[str] = []
        self._image_bytes_total = 0

    def _emit(self, text: str) -> None:
        self.parts.append(text)

    def _render_tag(self, tag: str, attrs: list[tuple[str, str | None]], close: bool) -> str:
        out = [f"<{tag}"]
        for name, value in attrs:
            if value is None:
                out.append(f" {name}")
            else:
                out.append(f' {name}="{html.escape(value, quote=True)}"')
        if close:
            out.append(" /")
        out.append(">")
        return "".join(out)

    def _raw_or_render(
        self, tag: str, attrs: list[tuple[str, str | None]], close: bool
    ) -> str:
        raw = self.get_starttag_text()
        return raw if raw is not None else self._render_tag(tag, attrs, close)

    def _inlinable_image(self, url: str) -> bool:
        if not _is_same_origin(self._page_url, url):
            return False
        if _url_suffix(url) in _IMAGE_MIME_BY_SUFFIX:
            return True
        page = urlparse(self._page_url)
        resource = urlparse(url)
        same_document = (page.scheme, page.netloc, page.path, page.query) == (
            resource.scheme,
            resource.netloc,
            resource.path,
            resource.query,
        )
        return not same_document

    def _try_inline_stylesheet(self, attrs: list[tuple[str, str | None]]) -> bool:
        """Inline a same-origin stylesheet; True when the tag was consumed."""
        attr_map = {name.lower(): value for name, value in attrs if value is not None}
        rel = attr_map.get("rel") or ""
        href = attr_map.get("href")
        if "stylesheet" not in rel.lower().split() or not href:
            return False
        absolute = urljoin(self._page_url, href)
        if not _is_same_origin(self._page_url, absolute):
            return False
        data = _fetch_resource(absolute, _HTML_CSS_MAX_BYTES)
        if data is None:
            return False
        css = _rewrite_css_fonts(data.decode("utf-8", errors="replace"), absolute, self._page_url)
        # A literal "</style" inside the CSS would close the block early.
        css = re.sub(r"(?i)</style", r"<\\/style", css)
        media = attr_map.get("media")
        media_attr = f' media="{html.escape(media, quote=True)}"' if media else ""
        self._emit(f"<style{media_attr}>" + css + "</style>")
        return True

    def _substitute_src(self, raw: str, src_value: str, replacement: str) -> str:
        def _replace(match: re.Match) -> str:
            value = match.group(1) or match.group(2) or match.group(3) or ""
            if value == src_value:
                return f'src="{replacement}"'
            return match.group(0)

        return _SRC_ATTR_RE.sub(_replace, raw, count=1)

    def _rewrite_img(self, tag: str, attrs: list[tuple[str, str | None]], close: bool) -> None:
        src_value = next((v for n, v in attrs if n.lower() == "src" and v), None)
        if src_value is None:
            self._emit(self._raw_or_render(tag, attrs, close))
            return
        if src_value.lower().startswith(("data:", "blob:", "javascript:", "#")):
            self._emit(self._raw_or_render(tag, attrs, close))
            return
        absolute = urljoin(self._page_url, src_value)
        if not self._inlinable_image(absolute):
            self._emit(self._raw_or_render(tag, attrs, close))
            return
        data = _fetch_resource(absolute, _HTML_IMAGE_MAX_BYTES)
        mime = _guess_image_mime(data, absolute) if data is not None else None
        if (
            data is not None
            and mime is not None
            and self._image_bytes_total + len(data) <= _HTML_IMAGE_TOTAL_MAX_BYTES
        ):
            self._image_bytes_total += len(data)
            replacement = _data_uri(data, mime)
            raw = self.get_starttag_text()
            if raw is not None:
                self._emit(self._substitute_src(raw, src_value, replacement))
            else:  # pragma: no cover - the parser always exposes the raw tag
                rewritten = [
                    (name, replacement if name.lower() == "src" and value == src_value else value)
                    for name, value in attrs
                ]
                self._emit(self._render_tag(tag, rewritten, close))
            return
        self._emit(self._raw_or_render(tag, attrs, close))

    def _handle_tag(self, tag: str, attrs: list[tuple[str, str | None]], close: bool) -> None:
        if tag == "link" and self._try_inline_stylesheet(attrs):
            return
        if tag == "img":
            self._rewrite_img(tag, attrs, close)
            return
        if tag == "head":
            self._emit(
                self._raw_or_render(tag, attrs, close) + '<meta charset="utf-8">'
            )
            return
        self._emit(self._raw_or_render(tag, attrs, close))

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._handle_tag(tag, attrs, close=False)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._handle_tag(tag, attrs, close=True)

    def handle_endtag(self, tag: str) -> None:
        self._emit(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        self._emit(data)

    def handle_entityref(self, name: str) -> None:
        self._emit(f"&{name};")

    def handle_charref(self, name: str) -> None:
        self._emit(f"&#{name};")

    def handle_comment(self, data: str) -> None:
        self._emit(f"<!--{data}-->")

    def handle_decl(self, decl: str) -> None:
        self._emit(f"<!{decl}>")

    def handle_pi(self, data: str) -> None:
        self._emit(f"<?{data}>")


def scrape_html(url: str) -> ScrapedContent:
    """Capture mode: offline snapshot of the page as a self-contained .html.

    Same-origin stylesheets are inlined into ``<style>`` blocks (fonts
    referenced from them become ``data:`` URIs), same-origin images are
    inlined as ``data:`` URIs, and the encoding is pinned to UTF-8 — the
    saved file renders offline with no asset folder. Cross-origin and
    oversized/failing sub-resources keep their original URLs; scripts are
    never inlined or executed.
    """
    from qualcoder_api.services.import_service import decode_text_with_best_encoding

    raw = fetch_url(url)
    html_text = decode_text_with_best_encoding(raw)
    rewriter = _SnapshotRewriter(url)
    rewriter.feed(html_text)
    rewriter.close()
    title = _page_title(html_text) or _host_for_name(url)
    return ScrapedContent(
        filename=f"{sanitize_name(title, 'page')}.html",
        data="".join(rewriter.parts).encode("utf-8"),
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
    """Fetch + parse a URL into (filename, file bytes, resolved mode).

    YouTube comments are imported as STRUCTURED data when a project is
    open (see ``scrape_youtube``): every comment becomes a case with
    author/likes/date attributes and a coded text source instead of a
    plain CSV file.
    """
    url = url.strip()
    validate_url(url)
    resolved = detect_mode(url, mode)
    if resolved == "reddit":
        return scrape_reddit(url)
    if resolved == "youtube":
        return scrape_youtube(url, **_structured_project())
    if resolved == "html":
        return scrape_html(url)
    if resolved == "pdf":
        return scrape_pdf(url)
    return scrape_article(url)
