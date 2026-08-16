"""URL scraping service — YouTube videos, web articles, raw HTML, PDF.

Each scraper returns a ``ScrapedContent`` (filename + file bytes); the
caller persists it through the regular file-import pipeline
(``ImportService.import_file``), so duplicate detection, attribute
placeholders and the source row behave exactly like any other file import.

Modes:
- ``youtube`` — the video's comment thread as ONE four-column CSV file
  (``<video title>.csv``): the ``author,likes,date,comment`` header row
  plus one row per comment. Replies are their own rows with a ``→ `` (one
  per depth level) nesting prefix in the author column only; missing
  likes/dates render as ``-``. The file is written through the stdlib
  ``csv`` module (RFC-4180 quoting, embedded quotes doubled), so it opens
  directly in any spreadsheet, and the source contains ONLY the comments
  table — no title/uploader/duration/description header block. Comment
  extraction runs in a SEPARATE yt-dlp subprocess (an in-process path is
  the PyInstaller-frozen fallback only); the first abort is retried once
  without comment extraction and a second abort — or a timeout when
  comments were not requested — surfaces a friendly error.

  Fallbacks (legacy behavior, never a silent substitution): when the
  comment list is empty and caption tracks exist, the table is replaced
  by a ``# Comments unavailable (<reason>) — captions shown below`` note
  row followed by one row per transcript line (no header). When comments
  were REQUESTED but could not be retrieved (extraction timed out or
  aborted) and no captions exist, the table keeps its header row plus a
  ``-,-,-,<note>`` row explaining the missing columns. When the video
  provably has no comments the header row is kept with a ``-,-,-,No
  comments`` row. If the installed yt-dlp predates comment extraction
  (2021.12.17) the header + ``-,-,-,<note>`` row is printed and captions
  are not fetched either.
- ``article`` — page fetched with urllib, cleaned with trafilatura
  (falling back to the project's own ``html_to_text``). This is also the
  destination for ``reddit.com`` links: the dedicated Reddit scraper was
  removed, so they flow through the generic article extraction and still
  produce a source (plain page text).
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
import urllib.error
import urllib.request
import weakref
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urljoin, urlparse

import trafilatura
import yt_dlp

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 QCnext/0.2.0"
)
FETCH_TIMEOUT = 45

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
    """Resolve the ``auto`` mode from the hostname.

    Reddit links have no dedicated scraper anymore — they fall through to
    the generic ``article`` path (see the module docstring).
    """
    if mode and mode != "auto":
        return mode
    host = urlparse(url).netloc.lower()
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

    ``user_agent`` overrides the default browser-like UA;
    ``extra_headers`` are merged over the defaults; ``method``/``data``
    build custom requests.
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
# YouTube (yt-dlp)
# ----------------------------------------------------------------------

#: yt-dlp gained comment extraction (``getcomments``) in 2021.12.17.
_YT_DLP_COMMENTS_MIN_VERSION = (2021, 12, 17)

#: Header row of the comment CSV — the first row of every table-shaped
#: scrape; every following row has exactly four fields. RFC-4180 quoting
#: is done by the stdlib ``csv`` module so the file opens directly in any
#: spreadsheet.
_COMMENT_HEADER = ("author", "likes", "date", "comment")


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


def _youtube_scraped(title_base: str, text: str) -> ScrapedContent:
    """Assemble the single CSV-mode result: ONE source file named after the
    video (``<title>.csv``) holding the four-column comment table — or the
    note/caption fallback rows — as its complete content."""
    return ScrapedContent(
        filename=f"{sanitize_name(title_base, 'youtube-video')}.csv",
        data=text.encode("utf-8"),
        mode="youtube",
    )


def scrape_youtube(url: str) -> ScrapedContent:
    """Extract the comment thread as ONE four-column CSV text source.

    The result is always a single ``<video title>.csv`` file: the
    ``author,likes,date,comment`` header row plus one row per comment —
    ALL comments yt-dlp returned (no cap, no per-comment cases/sources).
    Replies are their own rows with a ``→ `` nesting prefix in the author
    column only; missing likes/dates render as ``-``. The file is written
    through the stdlib ``csv`` module (RFC-4180 quoting, embedded quotes
    doubled, tabs/newlines inside cells collapsed), so it opens directly
    in any spreadsheet, and the source contains ONLY the comments table —
    no title/uploader/duration/description header block. Comments are the
    primary content; caption tracks are NEVER substituted silently.

    When comments were REQUESTED but could not be retrieved (extraction
    timed out or aborted, or an empty comment list) and no captions exist,
    the table keeps its header row plus a ``-,-,-,<note>`` row explaining
    the missing columns; when caption text exists it is shown instead of
    the table as a ``# Comments unavailable (<reason>) — captions shown
    below`` note row followed by one row per transcript line (no header).
    When the video provably has no comments the table keeps the header row
    and a ``-,-,-,No comments`` row. If the installed yt-dlp predates
    comment extraction (2021.12.17) the header + ``-,-,-,<note>`` row is
    printed and captions are not fetched either.

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
        return _youtube_scraped("", text)
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
        elif comments_failure:
            rows = [("-", "-", "-", _YT_COMMENTS_ABORT_NOTE)]
            text = _render_csv(rows)
        else:
            rows = [("-", "-", "-", "No comments")]
            text = _render_csv(rows)
    else:
        logger.warning("YouTube comment extraction unsupported for %s", url)
        rows = [("-", "-", "-", _YT_COMMENTS_UNSUPPORTED_NOTE)]
        text = _render_csv(rows)

    if not text.strip():
        raise ScrapeError("YouTube video contains no text")
    return _youtube_scraped(title_base, text)


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

    YouTube URLs resolve to a single four-column comment CSV
    (``scrape_youtube``). ``reddit.com`` links no longer have a dedicated
    scraper — auto-detection routes them to the generic article
    extraction, so they still produce a source (plain page text) instead
    of failing.
    """
    url = url.strip()
    validate_url(url)
    resolved = detect_mode(url, mode)
    if resolved == "youtube":
        return scrape_youtube(url)
    if resolved == "html":
        return scrape_html(url)
    if resolved == "pdf":
        return scrape_pdf(url)
    return scrape_article(url)
