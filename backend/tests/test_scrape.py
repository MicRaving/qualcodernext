"""URL import tests — Reddit/YouTube/article scraping, source persistence,
duplicate detection and audit."""

from __future__ import annotations

import base64
import csv
import io
import json
import sqlite3
import subprocess
from unittest.mock import patch

import pytest
import yt_dlp
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from qualcoder_api.api.v1.router import router as v1_router
from qualcoder_api.api.v1.scrape import router as scrape_router
from qualcoder_api.core.enums import MediaType
from qualcoder_api.services import scrape_service
from qualcoder_api.services.scrape_service import ScrapedContent, ScrapeError

# The scrape router is wired by the supervisor (v1/router.py); tests mount
# it themselves so this file stays independent of that wiring step.
app_with_scrape = FastAPI()
app_with_scrape.include_router(v1_router, prefix="/api/v1")
app_with_scrape.include_router(scrape_router, prefix="/api/v1")


# ----------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------

REDDIT_POST = {
    "kind": "Listing",
    "data": {
        "children": [
            {
                "kind": "t3",
                "data": {
                    "title": "My Reddit Thread",
                    "author": "op_user",
                    "selftext": "The selftext body.",
                    "score": 42,
                },
            }
        ]
    },
}

REDDIT_COMMENTS = {
    "kind": "Listing",
    "data": {
        "children": [
            {
                "kind": "t1",
                "data": {
                    "author": "alice",
                    "body": "Top level comment.",
                    "depth": 0,
                    "replies": {
                        "kind": "Listing",
                        "data": {
                            "children": [
                                {
                                    "kind": "t1",
                                    "data": {
                                        "author": "bob",
                                        "body": "Nested reply.",
                                        "depth": 1,
                                        "replies": "",
                                    },
                                }
                            ]
                        },
                    },
                },
            },
            {"kind": "more", "data": {"count": 7}},
        ]
    },
}


def reddit_payload() -> bytes:
    return json.dumps([REDDIT_POST, REDDIT_COMMENTS]).encode("utf-8")


ARTICLE_HTML = b"""<!DOCTYPE html>
<html>
<head><title>Testing Article</title></head>
<body>
  <main>
    <h1>Testing Article</h1>
    <p>The first paragraph of the article body with real content.</p>
    <p>A second paragraph follows it and adds more substance to the page
    so the extractor can tell the article from navigation chrome.</p>
    <p>A third paragraph rounds out the body with enough words for the
    extraction heuristic to accept the page as an article document.</p>
    <p>Finally a fourth paragraph confirms the main text is captured end
    to end, from the opening line down to the closing sentence.</p>
  </main>
  <nav>Navigation noise that should not appear.</nav>
</body>
</html>"""

VTT_CAPTIONS = b"""WEBVTT

00:00:01.000 --> 00:00:02.500
Hello caption <c>text</c>

00:00:03.000 --> 00:00:04.000
Second line
"""


def yt_completed(
    info: dict, returncode: int = 0, stderr: str = ""
) -> subprocess.CompletedProcess:
    """A canned yt-dlp subprocess result (exit 0 + JSON on stdout)."""
    return subprocess.CompletedProcess(
        ["python", "-m", "yt_dlp"],
        returncode,
        stdout=json.dumps(info).encode("utf-8"),
        stderr=stderr.encode("utf-8"),
    )


def record_yt_calls(mock) -> list[list[str]]:
    return [call.args[0] for call in mock.call_args_list]


class FakeYoutubeDL:
    """Minimal yt-dlp stand-in: extract_info returns a fixed info dict."""

    def __init__(self, options=None, info=None):
        self.options = options or {}
        self.info = info or {}

    def extract_info(self, url, download=False):
        return self.info

    def close(self):
        pass


def make_youtube_info(**overrides) -> dict:
    info = {
        "title": "Demo Video",
        "uploader": "Demo Channel",
        "duration": 83,
        "description": "A description.",
        "subtitles": {
            "en": [{"ext": "vtt", "url": "https://example.com/captions.vtt"}],
            "de": [{"ext": "vtt", "url": "https://example.com/captions-de.vtt"}],
        },
        "comments": [
            {"id": "1", "author": "viewer1", "text": "Great video", "parent": "video"},
            {"id": "2", "author": "viewer2", "text": "Agreed", "parent": "1"},
        ],
    }
    info.update(overrides)
    return info


def youtube_comment_table(text: str) -> list[list[str]]:
    """Rows after the ``author,likes,date,comment`` header line.

    Returns ``[]`` when the text has no header row (the caption block).
    """
    rows = list(csv.reader(io.StringIO(text)))
    for i, row in enumerate(rows):
        if row == ["author", "likes", "date", "comment"]:
            return rows[i + 1 :]
    return []


@pytest.fixture
async def scrape_client(tmp_path):
    """API client with a fresh open project (scrape router included)."""
    transport = ASGITransport(app=app_with_scrape)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        target = tmp_path / "scrape.qda"
        res = await client.post(
            "/api/v1/projects", json={"project_path": str(target), "codername": "tester"}
        )
        assert res.status_code == 200, res.text
        yield client, target
        await client.post("/api/v1/projects/close")


# ----------------------------------------------------------------------
# Mode detection / name sanitizing
# ----------------------------------------------------------------------

def test_detect_mode_reddit_youtube_article():
    assert scrape_service.detect_mode("https://www.reddit.com/r/x/comments/abc/") == "reddit"
    assert scrape_service.detect_mode("https://youtu.be/abc123") == "youtube"
    assert scrape_service.detect_mode("https://www.youtube.com/watch?v=abc") == "youtube"
    assert scrape_service.detect_mode("https://example.org/story") == "article"
    assert scrape_service.detect_mode("https://example.org/story", mode="html") == "html"
    assert scrape_service.detect_mode("https://example.org/story", mode="pdf") == "pdf"


def test_validate_url_rejects_non_http():
    for url in ("ftp://example.org/file", "file:///etc/passwd", "not a url"):
        with pytest.raises(ScrapeError, match="http"):
            scrape_service.validate_url(url)
    with pytest.raises(ScrapeError, match="empty"):
        scrape_service.validate_url("")


def test_sanitize_name_strips_path_characters():
    name = scrape_service.sanitize_name('a<b>:"/\\|?*c  spaced', "fallback")
    assert name == "abc spaced"
    assert scrape_service.sanitize_name("", "fallback") == "fallback"
    assert len(scrape_service.sanitize_name("x" * 300, "f")) <= 100


# ----------------------------------------------------------------------
# Reddit
# ----------------------------------------------------------------------

def test_reddit_parse_builds_indented_thread():
    with patch("qualcoder_api.services.scrape_service.fetch_url", return_value=reddit_payload()):
        content = scrape_service.scrape_reddit("https://www.reddit.com/r/Test/comments/abc123/")

    assert content.mode == "reddit"
    assert content.filename == "My Reddit Thread.txt"
    text = content.data.decode("utf-8")
    assert "My Reddit Thread" in text
    assert "Posted by u/op_user, 42 points" in text
    assert "The selftext body." in text
    assert "u/alice: Top level comment." in text
    assert "  u/bob: Nested reply." in text


def test_reddit_json_suffix_appended_and_query_kept():
    seen: list[str] = []

    def fake_fetch(url: str, **kwargs) -> bytes:
        seen.append(url)
        return reddit_payload()

    with patch("qualcoder_api.services.scrape_service.fetch_url", side_effect=fake_fetch):
        scrape_service.scrape_reddit("https://www.reddit.com/r/Test/comments/abc123/title/?sort=new")

    assert seen == ["https://www.reddit.com/r/Test/comments/abc123/title.json?sort=new"]


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (
            "https://old.reddit.com/r/Test/comments/abc123/some-slug/",
            "https://www.reddit.com/r/Test/comments/abc123/some-slug.json",
        ),
        (
            "https://np.reddit.com/r/Test/comments/abc123/some-slug",
            "https://www.reddit.com/r/Test/comments/abc123/some-slug.json",
        ),
        (
            "https://m.reddit.com/r/Test/comments/abc123/",
            "https://www.reddit.com/r/Test/comments/abc123.json",
        ),
        (
            "https://new.reddit.com/r/Test/comments/abc123/",
            "https://www.reddit.com/r/Test/comments/abc123.json",
        ),
        (
            "https://reddit.com/r/Test/comments/abc123/",
            "https://www.reddit.com/r/Test/comments/abc123.json",
        ),
        (
            "https://www.reddit.com/r/Test/comments/abc123/",
            "https://www.reddit.com/r/Test/comments/abc123.json",
        ),
    ],
)
def test_reddit_host_variants_normalize_to_www(url, expected):
    """old/np/m/new/bare reddit hosts all fetch through www.reddit.com."""
    seen: list[str] = []

    def fake_fetch(fetched: str, **kwargs) -> bytes:
        seen.append(fetched)
        return reddit_payload()

    with patch("qualcoder_api.services.scrape_service.fetch_url", side_effect=fake_fetch):
        content = scrape_service.scrape_reddit(url)

    assert seen == [expected]
    assert content.mode == "reddit"


def test_reddit_slug_form_keeps_sort_param():
    seen: list[str] = []

    def fake_fetch(fetched: str, **kwargs) -> bytes:
        seen.append(fetched)
        return reddit_payload()

    with patch("qualcoder_api.services.scrape_service.fetch_url", side_effect=fake_fetch):
        scrape_service.scrape_reddit(
            "https://old.reddit.com/r/Test/comments/abc123/title_with_underscores/?sort=confidence&t=all"
        )

    assert seen == [
        "https://www.reddit.com/r/Test/comments/abc123/title_with_underscores.json?sort=confidence&t=all"
    ]


def test_reddit_json_url_used_as_is():
    assert scrape_service._reddit_json_url("https://www.reddit.com/r/x/comments/a/b.json") == (
        "https://www.reddit.com/r/x/comments/a/b.json"
    )


def test_reddit_rejects_non_json_response():
    with patch("qualcoder_api.services.scrape_service.fetch_url", return_value=b"<html>"), pytest.raises(ScrapeError, match="not JSON"):
        scrape_service.scrape_reddit("https://www.reddit.com/r/x/comments/a/")

    with patch("qualcoder_api.services.scrape_service.fetch_url", return_value=b"{}"), pytest.raises(ScrapeError, match="response shape"):
        scrape_service.scrape_reddit("https://www.reddit.com/r/x/comments/a/")


@pytest.mark.parametrize(
    ("body", "message"),
    [
        (b'{"reason": "banned", "error": 403}', "as banned"),
        (b'{"reason": "quarantined", "error": 403}', "as quarantined"),
        (b'{"reason": "private", "error": 403}', "as private"),
    ],
)
def test_reddit_banned_and_quarantined_bodies_raise_clear_error(body, message):
    """Banned/quarantined subreddits answer 200 + a reason body — surface a
    clear error instead of the generic shape failure."""
    with (
        patch("qualcoder_api.services.scrape_service.fetch_url", return_value=body),
        pytest.raises(ScrapeError, match=message),
    ):
        scrape_service.scrape_reddit("https://www.reddit.com/r/Test/comments/abc123/")


def test_reddit_anonymous_403_error_body_raises_clear_error():
    with (
        patch("qualcoder_api.services.scrape_service.fetch_url", return_value=b'{"error": 403}'),
        pytest.raises(ScrapeError, match="private or blocked"),
    ):
        scrape_service.scrape_reddit("https://www.reddit.com/r/Test/comments/abc123/")


def test_reddit_accepts_single_listing_object():
    post_listing = {"kind": "Listing", "data": {"children": [REDDIT_POST["data"]["children"][0]]}}
    payload = json.dumps(post_listing).encode("utf-8")
    with patch("qualcoder_api.services.scrape_service.fetch_url", return_value=payload):
        content = scrape_service.scrape_reddit("https://www.reddit.com/r/Test/comments/abc123/")

    text = content.data.decode("utf-8")
    assert "My Reddit Thread" in text
    assert "The selftext body." in text
    assert "Comments" not in text


def test_reddit_429_retries_after_retry_after_then_succeeds():
    """A 429 with a Retry-After header sleeps for the header's seconds and
    retries once; the retry succeeding means the scrape succeeds."""
    err = ScrapeError(
        "server returned HTTP 429 for https://www.reddit.com/...",
        code=429,
        headers={"Retry-After": "2"},
    )
    seen: list[str] = []

    def fake_fetch(url: str, **kwargs) -> bytes:
        seen.append(url)
        if len(seen) == 1:
            raise err
        return reddit_payload()

    with (
        patch("qualcoder_api.services.scrape_service.time.sleep") as sleep,
        patch("qualcoder_api.services.scrape_service.fetch_url", side_effect=fake_fetch),
    ):
        content = scrape_service.scrape_reddit("https://www.reddit.com/r/Test/comments/abc123/")

    sleep.assert_called_once_with(2)
    assert seen == [
        "https://www.reddit.com/r/Test/comments/abc123.json",
        "https://www.reddit.com/r/Test/comments/abc123.json",
    ]
    assert content.mode == "reddit"
    assert "u/alice: Top level comment." in content.data.decode("utf-8")


def test_reddit_429_retries_once_then_raises_rate_limit_error():
    """A second 429 after the Retry-After retry surfaces a clear
    rate-limit error (no further retries, no host fallback)."""
    err = ScrapeError(
        "server returned HTTP 429 for https://www.reddit.com/...",
        code=429,
        headers={"Retry-After": "3"},
    )
    with (
        patch("qualcoder_api.services.scrape_service.time.sleep") as sleep,
        patch("qualcoder_api.services.scrape_service.fetch_url", side_effect=err),
        pytest.raises(ScrapeError, match="rate-limited"),
    ):
        scrape_service.scrape_reddit("https://www.reddit.com/r/Test/comments/abc123/")
    sleep.assert_called_once_with(3)


def test_reddit_429_without_retry_after_uses_default_delay():
    err = ScrapeError("server returned HTTP 429 for https://www.reddit.com/...", code=429)
    with (
        patch("qualcoder_api.services.scrape_service.time.sleep") as sleep,
        patch("qualcoder_api.services.scrape_service.fetch_url", side_effect=err),
        pytest.raises(ScrapeError, match="rate-limited"),
    ):
        scrape_service.scrape_reddit("https://www.reddit.com/r/Test/comments/abc123/")
    sleep.assert_called_once_with(60)


def test_reddit_403_tries_old_reddit_then_mentions_oauth():
    """A 403 (Reddit's network-policy block) falls back to old.reddit.com;
    when both hosts are blocked the error mentions the optional OAuth
    credentials instead of the old "private or blocked" message."""
    err = ScrapeError("server returned HTTP 403 for https://www.reddit.com/...", code=403)
    seen: list[str] = []

    def fake_fetch(url: str, **kwargs) -> bytes:
        seen.append(url)
        raise err

    with (
        patch("qualcoder_api.services.scrape_service.fetch_url", side_effect=fake_fetch),
        pytest.raises(ScrapeError, match="configure Reddit API credentials in Settings"),
    ):
        scrape_service.scrape_reddit("https://www.reddit.com/r/Test/comments/abc123/")
    assert seen == [
        "https://www.reddit.com/r/Test/comments/abc123.json",
        "https://old.reddit.com/r/Test/comments/abc123.json",
    ]


def test_reddit_403_on_www_recovers_on_old_reddit():
    """When www blocks the request but old.reddit.com answers, the scrape
    succeeds through the fallback host."""
    seen: list[str] = []

    def fake_fetch(url: str, **kwargs) -> bytes:
        seen.append(url)
        if "old.reddit.com" in url:
            return reddit_payload()
        raise ScrapeError("server returned HTTP 403 for " + url, code=403)

    with patch("qualcoder_api.services.scrape_service.fetch_url", side_effect=fake_fetch):
        content = scrape_service.scrape_reddit("https://www.reddit.com/r/Test/comments/abc123/")

    assert seen == [
        "https://www.reddit.com/r/Test/comments/abc123.json",
        "https://old.reddit.com/r/Test/comments/abc123.json",
    ]
    assert content.mode == "reddit"


def test_reddit_anonymous_fetch_uses_unique_user_agent():
    """The anonymous path must send the descriptive Reddit User-Agent, not
    the browser-spoofing default — Reddit blocks generic UAs."""
    calls: list[dict] = []

    def fake_fetch(url: str, **kwargs) -> bytes:
        calls.append({"url": url, **kwargs})
        return reddit_payload()

    with patch("qualcoder_api.services.scrape_service.fetch_url", side_effect=fake_fetch):
        scrape_service.scrape_reddit("https://www.reddit.com/r/Test/comments/abc123/")

    assert calls[0]["user_agent"] == scrape_service.REDDIT_USER_AGENT
    assert calls[0]["user_agent"] != scrape_service.USER_AGENT


# ----------------------------------------------------------------------
# Reddit — app-only OAuth (client_credentials)
# ----------------------------------------------------------------------

REDDIT_TOKEN_RESPONSE = {
    "access_token": "tok-123",
    "token_type": "bearer",
    "expires_in": 3600,
    "scope": "read",
}

REDDIT_CREDENTIALS = {"client_id": "qc-cid", "client_secret": "qc-secret"}


def test_reddit_oauth_path_fetches_token_then_oauth_listing():
    """Configured credentials: the app-only token is fetched with HTTP
    Basic auth (client_id:secret) + the form-encoded client_credentials
    grant, then the listing comes from oauth.reddit.com with the Bearer
    token — the payload parsing is identical to the anonymous path."""
    calls: list[tuple[str, dict]] = []

    def fake_fetch(url: str, **kwargs) -> bytes:
        calls.append((url, kwargs))
        if url == scrape_service._REDDIT_TOKEN_URL:
            return json.dumps(REDDIT_TOKEN_RESPONSE).encode("utf-8")
        return reddit_payload()

    with (
        patch(
            "qualcoder_api.services.user_settings.get_reddit_credentials",
            return_value=REDDIT_CREDENTIALS,
        ),
        patch("qualcoder_api.services.scrape_service.fetch_url", side_effect=fake_fetch),
    ):
        content = scrape_service.scrape_reddit("https://www.reddit.com/r/Test/comments/abc123/")

    token_url, token_kw = calls[0]
    assert token_url == "https://www.reddit.com/api/v1/access_token"
    assert token_kw["method"] == "POST"
    assert token_kw["data"] == b"grant_type=client_credentials"
    assert token_kw["user_agent"] == scrape_service.REDDIT_USER_AGENT
    expected_basic = "Basic " + base64.b64encode(b"qc-cid:qc-secret").decode("ascii")
    assert token_kw["extra_headers"]["Authorization"] == expected_basic
    assert token_kw["extra_headers"]["Content-Type"] == "application/x-www-form-urlencoded"

    listing_url, listing_kw = calls[1]
    assert listing_url == "https://oauth.reddit.com/r/Test/comments/abc123"
    assert listing_kw["extra_headers"]["Authorization"] == "Bearer tok-123"

    assert content.mode == "reddit"
    text = content.data.decode("utf-8")
    assert "My Reddit Thread" in text
    assert "u/alice: Top level comment." in text


def test_reddit_oauth_token_http_error_mentions_credentials():
    """A 401/400/403 from the token endpoint is a credential problem — the
    error points at the Settings instead of the raw HTTP status."""
    for code in (400, 401, 403):
        err = ScrapeError(
            f"server returned HTTP {code} for {scrape_service._REDDIT_TOKEN_URL}", code=code
        )
        with (
            patch(
                "qualcoder_api.services.user_settings.get_reddit_credentials",
                return_value=REDDIT_CREDENTIALS,
            ),
            patch("qualcoder_api.services.scrape_service.fetch_url", side_effect=err),
            pytest.raises(ScrapeError, match="rejected the API credentials"),
        ):
            scrape_service.scrape_reddit("https://www.reddit.com/r/Test/comments/abc123/")


def test_reddit_oauth_token_without_access_token_raises_clear_error():
    """A 200 without an access_token (invalid_grant etc.) is mapped to the
    same clear credential error."""
    with (
        patch(
            "qualcoder_api.services.user_settings.get_reddit_credentials",
            return_value=REDDIT_CREDENTIALS,
        ),
        patch(
            "qualcoder_api.services.scrape_service.fetch_url",
            return_value=json.dumps({"error": "invalid_grant"}).encode("utf-8"),
        ),
        pytest.raises(ScrapeError, match="rejected the API credentials"),
    ):
        scrape_service.scrape_reddit("https://www.reddit.com/r/Test/comments/abc123/")


def test_reddit_oauth_token_non_json_raises_clear_error():
    with (
        patch(
            "qualcoder_api.services.user_settings.get_reddit_credentials",
            return_value=REDDIT_CREDENTIALS,
        ),
        patch("qualcoder_api.services.scrape_service.fetch_url", return_value=b"<html>"),
        pytest.raises(ScrapeError, match="token response is not JSON"),
    ):
        scrape_service.scrape_reddit("https://www.reddit.com/r/Test/comments/abc123/")


def test_reddit_oauth_listing_403_mentions_scope_or_private():
    """A 403 on the OAuth listing itself is not the anonymous block — it
    points at the token scope or a private subreddit."""
    err = ScrapeError("server returned HTTP 403 for https://oauth.reddit.com/...", code=403)
    token_ok = json.dumps(REDDIT_TOKEN_RESPONSE).encode("utf-8")

    def fake_fetch(url: str, **kwargs) -> bytes:
        if url == scrape_service._REDDIT_TOKEN_URL:
            return token_ok
        raise err

    with (
        patch(
            "qualcoder_api.services.user_settings.get_reddit_credentials",
            return_value=REDDIT_CREDENTIALS,
        ),
        patch("qualcoder_api.services.scrape_service.fetch_url", side_effect=fake_fetch),
        pytest.raises(ScrapeError, match="read scope"),
    ):
        scrape_service.scrape_reddit("https://www.reddit.com/r/Test/comments/abc123/")


def test_reddit_without_credentials_uses_anonymous_only():
    """Unconfigured settings: the scraper never touches the token endpoint
    or oauth.reddit.com — it goes straight at the anonymous .json URL."""
    seen: list[str] = []

    def fake_fetch(url: str, **kwargs) -> bytes:
        seen.append(url)
        return reddit_payload()

    with (
        patch(
            "qualcoder_api.services.user_settings.get_reddit_credentials",
            return_value={"client_id": "", "client_secret": ""},
        ),
        patch("qualcoder_api.services.scrape_service.fetch_url", side_effect=fake_fetch),
    ):
        content = scrape_service.scrape_reddit("https://www.reddit.com/r/Test/comments/abc123/")

    assert seen == ["https://www.reddit.com/r/Test/comments/abc123.json"]
    assert content.mode == "reddit"


def test_reddit_partial_credentials_still_anonymous():
    """Only one of the two values set = not configured: anonymous path."""
    seen: list[str] = []

    def fake_fetch(url: str, **kwargs) -> bytes:
        seen.append(url)
        return reddit_payload()

    with (
        patch(
            "qualcoder_api.services.user_settings.get_reddit_credentials",
            return_value={"client_id": "only-an-id", "client_secret": ""},
        ),
        patch("qualcoder_api.services.scrape_service.fetch_url", side_effect=fake_fetch),
    ):
        scrape_service.scrape_reddit("https://www.reddit.com/r/Test/comments/abc123/")

    assert seen == ["https://www.reddit.com/r/Test/comments/abc123.json"]


def test_reddit_credentials_settings_roundtrip(tmp_path, monkeypatch):
    """The settings JSON stores the two credential keys; blanks are stored
    as-is (blank client ID = anonymous fallback)."""
    from qualcoder_api.services import user_settings

    monkeypatch.setattr(user_settings, "SETTINGS_FILE", tmp_path / "settings.json")
    assert user_settings.get_reddit_credentials() == {"client_id": "", "client_secret": ""}

    user_settings.save_reddit_credentials({"client_id": " a ", "client_secret": " b "})
    assert user_settings.get_reddit_credentials() == {"client_id": "a", "client_secret": "b"}

    user_settings.save_reddit_credentials({"client_id": "", "client_secret": ""})
    assert user_settings.get_reddit_credentials() == {"client_id": "", "client_secret": ""}


def test_save_ai_settings_bridges_reddit_credentials(tmp_path, monkeypatch):
    """The settings pane saves the Reddit credentials through the AI
    settings save (its only auto-save mechanism). Blank values keep the
    stored ones — the pane never reads them back, so a bare mount (or an
    unrelated AI edit) can never wipe saved credentials."""
    from qualcoder_api.services import user_settings

    monkeypatch.setattr(user_settings, "SETTINGS_FILE", tmp_path / "settings.json")
    ai = dict(user_settings.AI_DEFAULTS)
    ai["reddit_client_id"] = "cid"
    ai["reddit_client_secret"] = "secret"
    user_settings.save_ai_settings(ai)
    assert user_settings.get_reddit_credentials() == {"client_id": "cid", "client_secret": "secret"}

    user_settings.save_ai_settings(dict(user_settings.AI_DEFAULTS))
    assert user_settings.get_reddit_credentials() == {"client_id": "cid", "client_secret": "secret"}

    ai = dict(user_settings.AI_DEFAULTS)
    ai["reddit_client_secret"] = "new-secret"
    user_settings.save_ai_settings(ai)
    assert user_settings.get_reddit_credentials() == {
        "client_id": "cid",
        "client_secret": "new-secret",
    }


def test_reddit_json_suffix_handles_trailing_slash_after_json():
    assert scrape_service._reddit_json_url("https://www.reddit.com/r/x/comments/a/b.json/") == (
        "https://www.reddit.com/r/x/comments/a/b.json"
    )


def test_reddit_skips_removed_and_deleted_comments():
    comments_listing = {
        "kind": "Listing",
        "data": {
            "children": [
                {"kind": "t1", "data": {"author": "alice", "body": "Visible.", "replies": ""}},
                {"kind": "t1", "data": {"author": "bob", "body": "[removed]", "replies": ""}},
                {"kind": "t1", "data": {"author": "[deleted]", "body": "[deleted]", "replies": ""}},
            ]
        },
    }
    payload = json.dumps([REDDIT_POST, comments_listing]).encode("utf-8")
    with patch("qualcoder_api.services.scrape_service.fetch_url", return_value=payload):
        content = scrape_service.scrape_reddit("https://www.reddit.com/r/Test/comments/abc123/")

    text = content.data.decode("utf-8")
    assert "u/alice: Visible." in text
    assert "[removed]" not in text
    assert "u/[deleted]" not in text


# ----------------------------------------------------------------------
# Articles
# ----------------------------------------------------------------------

def test_article_extracts_text_from_html():
    with patch("qualcoder_api.services.scrape_service.fetch_url", return_value=ARTICLE_HTML):
        content = scrape_service.scrape_article("https://example.org/testing")

    assert content.mode == "article"
    assert content.filename == "Testing Article.txt"
    text = content.data.decode("utf-8")
    assert "first paragraph" in text
    assert "Navigation noise" not in text


def test_article_empty_page_raises():
    with patch("qualcoder_api.services.scrape_service.fetch_url", return_value=b"<html></html>"), pytest.raises(ScrapeError, match="extract any text"):
        scrape_service.scrape_article("https://example.org/empty")


# ----------------------------------------------------------------------
# YouTube
# ----------------------------------------------------------------------

def test_youtube_extracts_comments_instead_of_captions():
    """The subprocess path requests comments and renders ONLY the comment
    CSV — no title/uploader/duration/description block, no captions."""
    info = make_youtube_info(
        comments=[
            {
                "id": "1",
                "author": "alice",
                "text": "Loved it",
                "timestamp": 1700000000,
                "like_count": 12,
                "replies": [
                    {
                        "id": "2",
                        "author": "bob",
                        "text": "Me too",
                        "timestamp": 1700000100,
                        "like_count": 3,
                        "replies": [],
                    }
                ],
            },
            {"id": "3", "text": "No author,\nno\tmeta"},
        ]
    )
    with (
        patch("qualcoder_api.services.scrape_service.subprocess.run", return_value=yt_completed(info)) as run,
        patch("qualcoder_api.services.scrape_service.fetch_url") as fetch,
    ):
        content = scrape_service.scrape_youtube("https://www.youtube.com/watch?v=abc")

    commands = record_yt_calls(run)
    assert len(commands) == 1
    assert "--write-comments" in commands[0]
    assert "--dump-single-json" in commands[0]
    assert commands[0][-2:] == ["--", "https://www.youtube.com/watch?v=abc"]
    fetch.assert_not_called()  # captions are dropped when comments exist
    assert content.mode == "youtube"
    assert content.filename == "Demo Video.csv"
    text = content.data.decode("utf-8")
    # The source is ONLY the comment table: the CSV header row comes first
    # and the title/uploader/duration/description block is gone.
    assert text.startswith("author,likes,date,comment")
    assert "Demo Video" not in text
    assert "Uploader: Demo Channel" not in text
    assert "Duration:" not in text
    assert "A description." not in text
    # One CSV row per comment: author,likes,date,comment (commas in the
    # comment cell force RFC-4180 quoting).
    assert "alice,12 likes,2023-11-14 22:13,Loved it" in text
    assert "→ bob,3 likes,2023-11-14 22:15,Me too" in text
    assert 'unknown,-,-,"No author, no meta"' in text
    for row in youtube_comment_table(text):
        assert len(row) == 4
    assert "Captions" not in text
    assert "Hello caption text" not in text


def test_youtube_comment_rows_have_exactly_four_fields():
    """Flat-layout comments: every row is 4 fields, missing likes/date are
    ``-``, and tabs/newlines inside a comment collapse to spaces."""
    info = make_youtube_info(
        comments=[
            {"id": "1", "author": "alice", "text": "Top", "like_count": 5, "timestamp": 1700000000},
            {"id": "2", "author": "bob", "text": "Reply", "parent": "1"},
            {"id": "3", "author": "carol", "text": "Flat\ttab\nnewline"},
        ]
    )
    with patch("qualcoder_api.services.scrape_service.subprocess.run", return_value=yt_completed(info)):
        content = scrape_service.scrape_youtube("https://www.youtube.com/watch?v=abc")

    rows = youtube_comment_table(content.data.decode("utf-8"))
    assert len(rows) == 3
    for row in rows:
        assert len(row) == 4
    assert rows[0] == ["alice", "5 likes", "2023-11-14 22:13", "Top"]
    assert rows[1] == ["→ bob", "-", "-", "Reply"]
    assert rows[2] == ["carol", "-", "-", "Flat tab newline"]


def test_youtube_nested_replies_keep_four_fields_with_author_prefix():
    """Nested ``replies`` lists: each reply is its own 4-field row with the
    ``→ `` nesting prefix in the author column only."""
    info = make_youtube_info(
        comments=[
            {
                "id": "1",
                "author": "alice",
                "text": "Top level",
                "like_count": 2,
                "timestamp": 1700000000,
                "replies": [
                    {
                        "id": "2",
                        "author": "bob",
                        "text": "Nested reply",
                        "replies": [
                            {"id": "3", "author": "carol", "text": "Deep reply"},
                        ],
                    }
                ],
            }
        ]
    )
    with patch("qualcoder_api.services.scrape_service.subprocess.run", return_value=yt_completed(info)):
        content = scrape_service.scrape_youtube("https://www.youtube.com/watch?v=abc")

    rows = youtube_comment_table(content.data.decode("utf-8"))
    for row in rows:
        assert len(row) == 4
    assert rows == [
        ["alice", "2 likes", "2023-11-14 22:13", "Top level"],
        ["→ bob", "-", "-", "Nested reply"],
        ["→ → carol", "-", "-", "Deep reply"],
    ]


def test_comment_row_normalizes_stray_tabs_and_newlines():
    """Every cell is normalized so one comment always stays a single row."""
    row = scrape_service._comment_row("a\tb", "1", "x", "text\nmore")
    assert row == ("a b", "1", "x", "text more")


def test_youtube_subprocess_parses_playlist_wrapper():
    """--no-playlist can still yield a playlist wrapper; the first entry wins."""
    info = make_youtube_info(comments=[])
    wrapper = {"_type": "playlist", "entries": [info]}
    with (
        patch("qualcoder_api.services.scrape_service.subprocess.run", return_value=yt_completed(wrapper)),
        patch("qualcoder_api.services.scrape_service.fetch_url", return_value=VTT_CAPTIONS),
    ):
        content = scrape_service.scrape_youtube("https://www.youtube.com/watch?v=abc")

    assert content.mode == "youtube"
    assert "[00:01] Hello caption text" in content.data.decode("utf-8")


def test_youtube_captions_shown_with_note_when_comments_requested_but_missing():
    """Comments were requested and came back empty: captions are NOT
    substituted silently — the transcript is led by a visible
    ``# Comments unavailable ...`` note row (single-cell CSV rows, no
    column header) so the missing columns are explained. No
    title/uploader/duration/description block either."""
    info = make_youtube_info(comments=[])
    with (
        patch("qualcoder_api.services.scrape_service.subprocess.run", return_value=yt_completed(info)),
        patch("qualcoder_api.services.scrape_service.fetch_url", return_value=VTT_CAPTIONS),
    ):
        content = scrape_service.scrape_youtube("https://www.youtube.com/watch?v=abc")

    text = content.data.decode("utf-8")
    assert text == (
        "# Comments unavailable (the video has no comments) — captions shown below,,,\r\n"
        "[00:01] Hello caption text,,,\r\n"
        "[00:03] Second line,,,\r\n"
    )
    assert "Demo Video" not in text
    assert "Uploader:" not in text
    assert "A description." not in text
    assert "author,likes,date,comment" not in text


def test_youtube_without_comments_or_captions_reports_no_comments():
    """No comments + no captions still prints the header row and a
    ``-,-,-,No comments`` placeholder row — and nothing else."""
    info = make_youtube_info(subtitles={}, automatic_captions={}, comments=[])
    with (
        patch("qualcoder_api.services.scrape_service.subprocess.run", return_value=yt_completed(info)),
        patch("qualcoder_api.services.scrape_service.fetch_url") as fetch,
    ):
        content = scrape_service.scrape_youtube("https://www.youtube.com/watch?v=abc")

    fetch.assert_not_called()
    assert content.filename == "Demo Video.csv"
    text = content.data.decode("utf-8")
    assert text == "author,likes,date,comment\r\n-,-,-,No comments\r\n"
    assert "Demo Video" not in text
    assert "A description." not in text
    assert "Captions" not in text
    assert youtube_comment_table(text) == [["-", "-", "-", "No comments"]]


def test_youtube_notes_when_comment_extraction_unsupported():
    """Old yt-dlp: no ``--write-comments`` flag, no captions — the source
    keeps the header row plus a ``-,-,-,<note>`` row explaining that the
    installed yt-dlp cannot extract comments (never a bare ``No comments``)."""
    info = make_youtube_info()
    with (
        patch.object(scrape_service, "_YT_DLP_COMMENTS_SUPPORTED", False),
        patch("qualcoder_api.services.scrape_service.subprocess.run", return_value=yt_completed(info)) as run,
        patch("qualcoder_api.services.scrape_service.fetch_url") as fetch,
    ):
        content = scrape_service.scrape_youtube("https://www.youtube.com/watch?v=abc")

    assert "--write-comments" not in record_yt_calls(run)[0]
    fetch.assert_not_called()
    text = content.data.decode("utf-8")
    assert text == (
        "author,likes,date,comment\r\n"
        "-,-,-,Comments could not be retrieved (the installed yt-dlp version "
        "does not support comment extraction — 2021.12.17 or newer is required)\r\n"
    )
    assert "Demo Video" not in text
    assert "u/viewer1" not in text
    assert "Captions" not in text


def test_youtube_caption_fetch_failure_keeps_no_comments_row():
    """A failing caption fetch must not break the import — the table keeps
    the header row + the ``No comments`` row."""
    info = make_youtube_info(comments=[])
    with (
        patch("qualcoder_api.services.scrape_service.subprocess.run", return_value=yt_completed(info)),
        patch(
            "qualcoder_api.services.scrape_service.fetch_url",
            side_effect=ScrapeError("server returned HTTP 403"),
        ),
    ):
        content = scrape_service.scrape_youtube("https://www.youtube.com/watch?v=abc")

    text = content.data.decode("utf-8")
    assert text == "author,likes,date,comment\r\n-,-,-,No comments\r\n"
    assert "Demo Video" not in text
    assert "Captions" not in text


def test_youtube_subprocess_abort_retries_without_comments_with_note():
    """An aborting subprocess (exit 1 + 'Interrupted by user') is retried once
    without --write-comments; captions are then shown WITH a visible note
    explaining the abort — never silently."""
    abort = yt_completed({}, returncode=1, stderr="ERROR: Interrupted by user\n")
    ok_without_comments = yt_completed(make_youtube_info(comments=[]))
    with (
        patch(
            "qualcoder_api.services.scrape_service.subprocess.run",
            side_effect=[abort, ok_without_comments],
        ) as run,
        patch("qualcoder_api.services.scrape_service.fetch_url", return_value=VTT_CAPTIONS),
    ):
        content = scrape_service.scrape_youtube("https://www.youtube.com/watch?v=abc")

    commands = record_yt_calls(run)
    assert len(commands) == 2
    assert "--write-comments" in commands[0]
    assert "--write-comments" not in commands[1]
    text = content.data.decode("utf-8")
    assert "Demo Video" not in text
    assert text.startswith("# Comments unavailable (extraction aborted) — captions shown below,,,")
    assert "[00:01] Hello caption text" in text


def test_youtube_abort_without_captions_keeps_header_and_abort_note():
    """Abort retry succeeds but no captions exist: the output keeps the
    column header plus a ``-,-,-,<note>`` row explaining the aborted
    comments — never a silent bare ``No comments`` row."""
    abort = yt_completed({}, returncode=1, stderr="ERROR: Interrupted by user\n")
    ok_without_comments = yt_completed(
        make_youtube_info(subtitles={}, automatic_captions={}, comments=[])
    )
    with (
        patch(
            "qualcoder_api.services.scrape_service.subprocess.run",
            side_effect=[abort, ok_without_comments],
        ) as run,
        patch("qualcoder_api.services.scrape_service.fetch_url") as fetch,
    ):
        content = scrape_service.scrape_youtube("https://www.youtube.com/watch?v=abc")

    assert len(record_yt_calls(run)) == 2
    fetch.assert_not_called()
    text = content.data.decode("utf-8")
    assert text == (
        "author,likes,date,comment\r\n"
        "-,-,-,Comments could not be retrieved (extraction aborted) — "
        "the video may have comments disabled or be very large\r\n"
    )


def test_youtube_subprocess_abort_without_retry_maps_to_friendly_error():
    """When comments are unsupported there is nothing to retry: the abort
    surfaces as the friendly, actionable message — not the raw signal."""
    abort = yt_completed({}, returncode=1, stderr="ERROR: Interrupted by user\n")
    with (
        patch.object(scrape_service, "_YT_DLP_COMMENTS_SUPPORTED", False),
        patch("qualcoder_api.services.scrape_service.subprocess.run", return_value=abort),
        pytest.raises(ValueError, match="was interrupted"),
    ):
        scrape_service.scrape_youtube("https://www.youtube.com/watch?v=abc")


def test_youtube_subprocess_exit_101_maps_to_friendly_error():
    """DownloadCancelled exits 101 ('Aborting remaining downloads')."""
    cancelled = yt_completed({}, returncode=101, stderr="")
    with (
        patch("qualcoder_api.services.scrape_service.subprocess.run", return_value=cancelled),
        pytest.raises(ValueError, match="was interrupted"),
    ):
        scrape_service.scrape_youtube("https://www.youtube.com/watch?v=abc")


def test_youtube_subprocess_real_failure_surfaces_stderr_detail():
    err = yt_completed({}, returncode=1, stderr="ERROR: Unsupported URL: https://x\n")
    with (
        patch("qualcoder_api.services.scrape_service.subprocess.run", return_value=err),
        pytest.raises(ScrapeError, match=r"extraction failed: Unsupported URL: https://x"),
    ):
        scrape_service.scrape_youtube("https://www.youtube.com/watch?v=abc")


def test_youtube_subprocess_garbage_stdout_maps_to_no_metadata():
    garbage = subprocess.CompletedProcess(["python", "-m", "yt_dlp"], 0, stdout=b"not json")
    with (
        patch("qualcoder_api.services.scrape_service.subprocess.run", return_value=garbage),
        pytest.raises(ScrapeError, match="no metadata"),
    ):
        scrape_service.scrape_youtube("https://www.youtube.com/watch?v=abc")


def test_youtube_timeout_with_comments_requested_keeps_header_and_note_row():
    """subprocess.run raises TimeoutExpired (it killed the child already)
    while comments were requested: the scrape must NOT raise or silently
    fall back to captions — the output keeps the column header plus a
    ``-,-,-,<note>`` CSV row explaining the missing columns."""
    with (
        patch.object(scrape_service, "_YT_TIMEOUT_SECONDS", 0.2),
        patch(
            "qualcoder_api.services.scrape_service.subprocess.run",
            side_effect=subprocess.TimeoutExpired(["python", "-m", "yt_dlp"], 0.2),
        ) as run,
        patch("qualcoder_api.services.scrape_service.fetch_url") as fetch,
    ):
        content = scrape_service.scrape_youtube("https://www.youtube.com/watch?v=abc")

    assert "--write-comments" in record_yt_calls(run)[0]
    fetch.assert_not_called()  # no info dict came back — captions are untouchable
    assert content.filename == "youtube-video.csv"
    text = content.data.decode("utf-8")
    assert text == (
        "author,likes,date,comment\r\n"
        "-,-,-,Comments could not be retrieved (extraction timed out) — "
        "the video may have comments disabled or be very large\r\n"
    )
    # The note is a real CSV row: four cells that round-trip through csv.reader.
    assert youtube_comment_table(text) == [
        ["-", "-", "-", "Comments could not be retrieved (extraction timed out) — "
         "the video may have comments disabled or be very large"]
    ]


def test_youtube_timeout_without_comments_requested_raises_friendly_error():
    """Only when comments were NOT requested (old yt-dlp) does the timeout
    surface as the friendly error."""
    with (
        patch.object(scrape_service, "_YT_DLP_COMMENTS_SUPPORTED", False),
        patch.object(scrape_service, "_YT_TIMEOUT_SECONDS", 0.2),
        patch(
            "qualcoder_api.services.scrape_service.subprocess.run",
            side_effect=subprocess.TimeoutExpired(["python", "-m", "yt_dlp"], 0.2),
        ),
        pytest.raises(ScrapeError, match="timed out"),
    ):
        scrape_service.scrape_youtube("https://www.youtube.com/watch?v=abc")


def test_yt_timeout_seconds_matches_frontend_dialog_wait():
    """The backend extraction timeout must match the frontend dialog's 240s
    wait so real comment extractions on large threads can complete."""
    assert scrape_service._YT_TIMEOUT_SECONDS == 240


# ----------------------------------------------------------------------
# YouTube — structured import (cases + attributes + coded comment sources)
# ----------------------------------------------------------------------

STRUCTURED_COMMENTS = [
    {
        "id": "1",
        "author": "alice",
        "text": "Loved it",
        "timestamp": 1700000000,
        "like_count": 12,
        "replies": [
            {
                "id": "2",
                "author": "bob",
                "text": "Me too",
                "timestamp": 1700000100,
                "like_count": 3,
                "replies": [],
            }
        ],
    },
    {"id": "3", "text": "No author,\nno\tmeta"},
]


def make_yt_comment(index: int) -> dict:
    """One flat-layout comment with deterministic author/text/likes/date."""
    return {
        "id": str(index),
        "author": f"user{index}",
        "text": f"Comment {index} text",
        "timestamp": 1700000000 + index,
        "like_count": index * 10,
    }


def open_project_factory(target) -> tuple:
    """(session_factory, project_path) of the project the client opened."""
    from qualcoder_api.main import service

    assert service.session_factory is not None
    return service.session_factory, str(target)


async def test_youtube_structured_import_creates_cases_attributes_and_codings(scrape_client):
    """POST /scrape/import with a YouTube URL imports every comment as a
    CASE with author/likes/date attributes and a CODED comment source —
    the CSV contract columns become real fields, not a text file."""
    client, target = scrape_client
    info = make_youtube_info(comments=STRUCTURED_COMMENTS)
    with (
        patch("qualcoder_api.services.scrape_service.subprocess.run", return_value=yt_completed(info)) as run,
        patch("qualcoder_api.services.scrape_service.fetch_url") as fetch,
    ):
        res = await client.post(
            "/api/v1/scrape/import", json={"url": "https://www.youtube.com/watch?v=abc"}
        )
    assert res.status_code == 200, res.text
    body = res.json()
    assert "--write-comments" in record_yt_calls(run)[0]
    fetch.assert_not_called()  # captions are never fetched while comments exist
    assert body["mode"] == "youtube-structured"
    assert body["name"] == "Demo Video.csv"
    assert body["text_length"] == 0  # the comments live as data, not file text

    with sqlite3.connect(str(target / "data.qda")) as conn:
        # One case per comment (replies included), named after the video.
        names = sorted(r[0] for r in conn.execute("SELECT name FROM cases"))
        assert names == [
            "Demo Video — Comment 1",
            "Demo Video — Comment 2",
            "Demo Video — Comment 3",
        ]
        # Attribute types: author/likes/date (case scope, text).
        assert {
            r[0]: (r[1], r[2])
            for r in conn.execute("SELECT name, caseOrFile, valuetype FROM attribute_type")
        } == {
            "author": ("case", "text"),
            "likes": ("case", "text"),
            "date": ("case", "text"),
        }
        # Attribute values per case (replies keep the ``→ `` prefix).
        attrs = {
            (r[0], r[1]): r[2]
            for r in conn.execute(
                "SELECT a.name, c.name, a.value FROM attribute a "
                "JOIN cases c ON c.caseid = a.id WHERE a.attr_type = 'case'"
            )
        }
        assert attrs == {
            ("author", "Demo Video — Comment 1"): "alice",
            ("likes", "Demo Video — Comment 1"): "12 likes",
            ("date", "Demo Video — Comment 1"): "2023-11-14 22:13",
            ("author", "Demo Video — Comment 2"): "→ bob",
            ("likes", "Demo Video — Comment 2"): "3 likes",
            ("date", "Demo Video — Comment 2"): "2023-11-14 22:15",
            ("author", "Demo Video — Comment 3"): "unknown",
            ("likes", "Demo Video — Comment 3"): "-",
            ("date", "Demo Video — Comment 3"): "-",
        }
        # One analyzable text source per comment, coded with the column
        # name as the code (the survey core names codes after columns).
        # The API's file-import pipeline also registers the empty
        # ``Demo Video.csv`` row — the comments themselves never travel
        # as file text.
        assert sorted(r[0] for r in conn.execute("SELECT name FROM source")) == [
            "Demo Video — Comment 1_comment",
            "Demo Video — Comment 2_comment",
            "Demo Video — Comment 3_comment",
            "Demo Video.csv",
        ]
        fulltext = dict(conn.execute("SELECT name, fulltext FROM source"))
        assert fulltext["Demo Video — Comment 1_comment"] == "Loved it"
        assert fulltext["Demo Video — Comment 2_comment"] == "Me too"
        assert fulltext["Demo Video — Comment 3_comment"] == "No author, no meta"
        assert fulltext["Demo Video.csv"] == ""
        assert [(r[0], r[1]) for r in conn.execute("SELECT name, color FROM code_name")] == [
            ("comment", "#B8B8B8")
        ]
        assert conn.execute("SELECT COUNT(*) FROM code_text").fetchone()[0] == 3
        codings = {
            seltext: (fid, cid)
            for fid, cid, seltext in conn.execute("SELECT fid, cid, seltext FROM code_text")
        }
        assert set(codings) == {"Loved it", "Me too", "No author, no meta"}
        assert conn.execute("SELECT COUNT(*) FROM case_text").fetchone()[0] == 3
        # The audit records the structured outcome with the counts.
        rows = conn.execute(
            "SELECT detail FROM audit_log WHERE action = 'scrape.import'"
        ).fetchall()
        details = [json.loads(r[0]) for r in rows]
        assert any(
            d.get("mode") == "youtube-structured" and d.get("cases") == 3
            and d.get("qualitative_files") == 3 and d.get("qualitative_codings") == 3
            for d in details
        )
        assert any(d.get("mode") == "youtube-structured" for d in details)


def test_youtube_structured_cap_notes_first_n_of_total(scrape_client):
    """Only the first _YT_COMMENT_CAP comments are imported; the result
    dict and the audit note say ``first n of N comments imported``."""
    _, target = scrape_client
    info = make_youtube_info(comments=[make_yt_comment(i) for i in range(5)])
    with (
        patch.object(scrape_service, "_YT_COMMENT_CAP", 2),
        patch("qualcoder_api.services.scrape_service.subprocess.run", return_value=yt_completed(info)),
    ):
        content = scrape_service.scrape_youtube(
            "https://www.youtube.com/watch?v=abc",
            session_factory=open_project_factory(target)[0],
            project_path=open_project_factory(target)[1],
        )

    assert content.mode == "youtube-structured"
    assert content.data == b""  # no comment text travels as a file
    result = content.structured
    assert result["mode"] == "youtube-structured"
    assert result["cases"] == 2
    assert result["comments_total"] == 5
    assert result["comments_imported"] == 2
    assert result["note"] == "first 2 of 5 comments imported"
    assert result["attribute_types"] == 3
    with sqlite3.connect(str(target / "data.qda")) as conn:
        assert conn.execute("SELECT COUNT(*) FROM cases").fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM source").fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM code_text").fetchone()[0] == 2
        # The audit carries the result dict including the cap note.
        rows = conn.execute(
            "SELECT detail FROM audit_log WHERE action = 'scrape.import'"
        ).fetchall()
    details = [json.loads(r[0]) for r in rows]
    assert any(d.get("note") == "first 2 of 5 comments imported" for d in details)


def test_youtube_structured_falls_back_to_csv_when_no_comments(scrape_client):
    """A video with no comments keeps the captions-with-note CSV and the
    result dict marks the fallback — no cases are created."""
    _, target = scrape_client
    info = make_youtube_info(comments=[])
    with (
        patch("qualcoder_api.services.scrape_service.subprocess.run", return_value=yt_completed(info)),
        patch("qualcoder_api.services.scrape_service.fetch_url", return_value=VTT_CAPTIONS),
    ):
        content = scrape_service.scrape_youtube(
            "https://www.youtube.com/watch?v=abc",
            session_factory=open_project_factory(target)[0],
            project_path=open_project_factory(target)[1],
        )

    assert content.mode == "youtube"
    assert content.structured == {"mode": "youtube", "fallback": "the video has no comments"}
    text = content.data.decode("utf-8")
    assert text.startswith("# Comments unavailable (the video has no comments) — captions shown below,,,")
    assert "[00:01] Hello caption text" in text
    with sqlite3.connect(str(target / "data.qda")) as conn:
        assert conn.execute("SELECT COUNT(*) FROM cases").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM source").fetchone()[0] == 0


def test_youtube_structured_failure_falls_back_to_csv(scrape_client):
    """A failing row import must not lose the comments: the comment table
    stays the CSV text source and the result marks the fallback."""
    _, target = scrape_client
    info = make_youtube_info(comments=STRUCTURED_COMMENTS)
    with (
        patch("qualcoder_api.services.scrape_service.subprocess.run", return_value=yt_completed(info)),
        patch(
            "qualcoder_api.interchange.importers._import_survey_rows",
            side_effect=ValueError("boom"),
        ),
    ):
        content = scrape_service.scrape_youtube(
            "https://www.youtube.com/watch?v=abc",
            session_factory=open_project_factory(target)[0],
            project_path=open_project_factory(target)[1],
        )

    assert content.mode == "youtube"
    assert content.structured["mode"] == "youtube"
    assert content.structured["fallback"].startswith("structured import failed")
    text = content.data.decode("utf-8")
    assert text.startswith("author,likes,date,comment")
    assert "alice,12 likes,2023-11-14 22:13,Loved it" in text
    assert "→ bob,3 likes,2023-11-14 22:15,Me too" in text
    assert 'unknown,-,-,"No author, no meta"' in text
    with sqlite3.connect(str(target / "data.qda")) as conn:
        assert conn.execute("SELECT COUNT(*) FROM cases").fetchone()[0] == 0


# ----------------------------------------------------------------------
# YouTube — in-process fallback (PyInstaller-frozen builds)
# ----------------------------------------------------------------------

def test_youtube_fallback_abort_signal_maps_to_friendly_error():
    """The frozen-build fallback still maps yt-dlp's internal abort
    (KeyboardInterrupt out of extract_info) to the friendly error."""

    class AbortingYoutubeDL(FakeYoutubeDL):
        def extract_info(self, url, download=False):
            raise KeyboardInterrupt("signal aborted without reason")

    with (
        patch.object(scrape_service, "_YT_SUBPROCESS_ENABLED", False),
        patch(
            "qualcoder_api.services.scrape_service.yt_dlp.YoutubeDL",
            return_value=AbortingYoutubeDL(info=make_youtube_info()),
        ),
        pytest.raises(ValueError, match="was interrupted"),
    ):
        scrape_service.scrape_youtube("https://www.youtube.com/watch?v=abc")


def test_youtube_fallback_abort_string_in_download_error_maps_to_friendly_error():
    """Some platforms report the abort as a DownloadError naming the signal
    instead of a KeyboardInterrupt."""

    class AbortingYoutubeDL(FakeYoutubeDL):
        def extract_info(self, url, download=False):
            raise yt_dlp.utils.DownloadError("signal aborted without reason")

    with (
        patch.object(scrape_service, "_YT_SUBPROCESS_ENABLED", False),
        patch(
            "qualcoder_api.services.scrape_service.yt_dlp.YoutubeDL",
            return_value=AbortingYoutubeDL(info=make_youtube_info()),
        ),
        pytest.raises(ScrapeError, match="was interrupted"),
    ):
        scrape_service.scrape_youtube("https://www.youtube.com/watch?v=abc")


def test_youtube_fallback_abort_during_comments_retries_without_getcomments():
    """The fallback retries an abort on the comment-extracting call once with
    metadata only; captions are then shown WITH a visible note — never
    silently."""
    created: list[FakeYoutubeDL] = []

    def factory(options=None):
        if options and options.get("getcomments"):
            class AbortOnce(FakeYoutubeDL):
                def extract_info(self, url, download=False):
                    raise KeyboardInterrupt("signal aborted without reason")

            ydl: FakeYoutubeDL = AbortOnce(options=options, info=make_youtube_info())
        else:
            ydl = FakeYoutubeDL(options=options, info=make_youtube_info(comments=[]))
        created.append(ydl)
        return ydl

    with (
        patch.object(scrape_service, "_YT_SUBPROCESS_ENABLED", False),
        patch("qualcoder_api.services.scrape_service.yt_dlp.YoutubeDL", side_effect=factory),
        patch("qualcoder_api.services.scrape_service.fetch_url", return_value=VTT_CAPTIONS),
    ):
        content = scrape_service.scrape_youtube("https://www.youtube.com/watch?v=abc")

    assert len(created) == 2
    assert created[0].options.get("getcomments") is True
    assert created[1].options.get("getcomments") is not True
    text = content.data.decode("utf-8")
    assert "Demo Video" not in text
    assert text.startswith("# Comments unavailable (extraction aborted) — captions shown below")
    assert "[00:01] Hello caption text" in text


def test_youtube_fallback_hang_with_comments_requested_keeps_header_and_note_row():
    """A hanging fallback extractor (frozen build) with comments requested:
    the output keeps the column header plus the timeout note row instead of
    raising or substituting captions."""
    import time

    class SlowYoutubeDL(FakeYoutubeDL):
        def extract_info(self, url, download=False):
            time.sleep(2)
            return self.info

    with (
        patch.object(scrape_service, "_YT_SUBPROCESS_ENABLED", False),
        patch.object(scrape_service, "_YT_TIMEOUT_SECONDS", 0.2),
        patch(
            "qualcoder_api.services.scrape_service.yt_dlp.YoutubeDL",
            return_value=SlowYoutubeDL(info=make_youtube_info()),
        ),
    ):
        content = scrape_service.scrape_youtube("https://www.youtube.com/watch?v=abc")

    text = content.data.decode("utf-8")
    assert text == (
        "author,likes,date,comment\r\n"
        "-,-,-,Comments could not be retrieved (extraction timed out) — "
        "the video may have comments disabled or be very large\r\n"
    )


def test_youtube_fallback_runs_when_subprocess_cannot_start():
    """A spawn failure (OSError, e.g. the interpreter is gone) must degrade
    to the in-process path instead of failing the import."""
    info = make_youtube_info(comments=[])
    with (
        patch("qualcoder_api.services.scrape_service.subprocess.run", side_effect=OSError("no python")),
        patch("qualcoder_api.services.scrape_service.yt_dlp.YoutubeDL", return_value=FakeYoutubeDL(info=info)),
        patch("qualcoder_api.services.scrape_service.fetch_url", return_value=VTT_CAPTIONS),
    ):
        content = scrape_service.scrape_youtube("https://www.youtube.com/watch?v=abc")

    assert "Demo Video" not in content.data.decode("utf-8")
    assert "[00:01] Hello caption text" in content.data.decode("utf-8")


def test_youtube_subprocess_not_used_in_frozen_builds():
    """PyInstaller-frozen builds have no ``sys.executable -m yt_dlp``; the
    subprocess path is disabled at import time there."""
    assert scrape_service._YT_SUBPROCESS_ENABLED is True  # dev/tests run unfrozen
    assert hasattr(scrape_service, "_yt_cli_command")


def test_frozen_build_disables_subprocess_path(monkeypatch):
    """``sys.frozen`` truthy (a PyInstaller build) must disable the
    subprocess path: ``sys.executable`` there is the app exe
    (``qualcoder-backend.exe``), not a Python interpreter."""
    assert scrape_service._yt_subprocess_enabled() is True  # dev/tests run unfrozen
    monkeypatch.setattr(scrape_service.sys, "frozen", True, raising=False)
    assert scrape_service._yt_subprocess_enabled() is False
    monkeypatch.setattr(scrape_service.sys, "frozen", False)
    assert scrape_service._yt_subprocess_enabled() is True
    # The module constant is derived from the very same check.
    assert scrape_service._YT_SUBPROCESS_ENABLED is True


def test_yt_extract_subprocess_refuses_frozen_build(monkeypatch):
    """The subprocess entry point itself refuses to run when frozen — a
    misroute degrades to the in-process fallback via the OSError handler
    instead of launching ``qualcoder-backend.exe -m yt_dlp``."""
    monkeypatch.setattr(scrape_service.sys, "frozen", True, raising=False)
    with pytest.raises(OSError, match="frozen"):
        scrape_service._yt_extract_subprocess("https://www.youtube.com/watch?v=abc", True)


def test_frozen_build_skips_subprocess_and_runs_in_process_with_getcomments(monkeypatch):
    """Frozen builds run yt-dlp IN-PROCESS with ``getcomments``; the
    subprocess is never attempted and the four-column CSV renders."""
    created: list[FakeYoutubeDL] = []

    def factory(options=None):
        ydl = FakeYoutubeDL(options=options, info=make_youtube_info())
        created.append(ydl)
        return ydl

    monkeypatch.setattr(scrape_service.sys, "frozen", True, raising=False)
    with (
        patch.object(scrape_service, "_YT_SUBPROCESS_ENABLED", False),
        patch(
            "qualcoder_api.services.scrape_service.subprocess.run",
            side_effect=AssertionError("subprocess must not run in a frozen build"),
        ),
        patch("qualcoder_api.services.scrape_service.yt_dlp.YoutubeDL", side_effect=factory),
    ):
        content = scrape_service.scrape_youtube("https://www.youtube.com/watch?v=abc")

    assert len(created) == 1
    assert created[0].options.get("getcomments") is True
    text = content.data.decode("utf-8")
    assert text.startswith("author,likes,date,comment")
    assert "viewer1,-,-,Great video" in text
    assert "→ viewer2,-,-,Agreed" in text


def test_frozen_build_never_attempts_subprocess_even_if_flag_wrong(monkeypatch):
    """Defense in depth: even if ``_YT_SUBPROCESS_ENABLED`` were forced on,
    the in-function frozen re-check must skip straight to the in-process
    path — the subprocess command could never work in a frozen build."""
    monkeypatch.setattr(scrape_service.sys, "frozen", True, raising=False)
    with (
        patch.object(scrape_service, "_YT_SUBPROCESS_ENABLED", True),
        patch(
            "qualcoder_api.services.scrape_service.subprocess.run",
            side_effect=AssertionError("subprocess attempted in frozen build"),
        ),
        patch(
            "qualcoder_api.services.scrape_service.yt_dlp.YoutubeDL",
            return_value=FakeYoutubeDL(info=make_youtube_info()),
        ),
    ):
        content = scrape_service.scrape_youtube("https://www.youtube.com/watch?v=abc")

    text = content.data.decode("utf-8")
    assert "viewer1,-,-,Great video" in text
    assert "→ viewer2,-,-,Agreed" in text


def test_yt_dlp_extract_marks_comments_requested():
    """The info dict carries the ``_qc_comments_requested`` marker so the
    caption fallback can only replace the table when comments are provably
    absent."""
    info = make_youtube_info()
    with patch(
        "qualcoder_api.services.scrape_service.subprocess.run", return_value=yt_completed(info)
    ):
        result = scrape_service._yt_dlp_extract("https://www.youtube.com/watch?v=abc", True)
    assert result["_qc_comments_requested"] is True
    with patch(
        "qualcoder_api.services.scrape_service.subprocess.run", return_value=yt_completed(info)
    ):
        result = scrape_service._yt_dlp_extract("https://www.youtube.com/watch?v=abc", False)
    assert result["_qc_comments_requested"] is False


def test_comment_row_exact_cells_with_likes_and_date():
    """The machine-readable row contract, verbatim: the four normalized
    cells (author, likes, date, text) — nothing padded or aligned."""
    assert scrape_service._comment_row("alice", "12 likes", "2023-11-14 22:13", "Loved it") == (
        ("alice", "12 likes", "2023-11-14 22:13", "Loved it")
    )


def test_comment_row_exact_cells_reply_prefix():
    """A reply carries the ``→ `` nesting prefix in the author column only."""
    assert scrape_service._comment_row("→ bob", "3 likes", "2023-11-14 22:15", "Me too") == (
        ("→ bob", "3 likes", "2023-11-14 22:15", "Me too")
    )


def test_youtube_csv_quotes_commas_and_quotes_and_normalizes_newlines():
    """RFC-4180 quoting: cells containing commas or quotes are quoted with
    embedded quotes doubled; tabs/newlines collapse to spaces so one
    comment stays one row. The rendered file round-trips through
    ``csv.reader`` with exactly four cells per row."""
    info = make_youtube_info(
        comments=[
            {"id": "1", "author": "alice", "text": 'He said "hi", then left'},
            {"id": "2", "author": "bob", "text": "multi\nline\ttab"},
        ]
    )
    with patch("qualcoder_api.services.scrape_service.subprocess.run", return_value=yt_completed(info)):
        content = scrape_service.scrape_youtube("https://www.youtube.com/watch?v=abc")

    assert content.filename == "Demo Video.csv"
    text = content.data.decode("utf-8")
    assert text.startswith("author,likes,date,comment\r\n")
    assert 'alice,-,-,"He said ""hi"", then left"' in text
    assert "bob,-,-,multi line tab" in text
    rows = youtube_comment_table(text)
    assert rows == [
        ["alice", "-", "-", 'He said "hi", then left'],
        ["bob", "-", "-", "multi line tab"],
    ]


def test_youtube_csv_classifies_as_text_source():
    """The saved ``.csv`` is a text source: detect_media_type maps ``.csv``
    to TEXT, so the file flows through the normal text-import pipeline."""
    from qualcoder_api.services.import_service import detect_media_type

    assert detect_media_type("Demo Video.csv") == MediaType.TEXT


def test_youtube_fallback_integration_renders_four_column_table():
    """The in-process fallback (the packaged-build path) renders the exact
    CSV comment table end to end: header first, one row per comment,
    replies prefixed, likes/dates formatted, captions never fetched while
    comments exist."""
    info = make_youtube_info(
        comments=[
            {
                "id": "1",
                "author": "alice",
                "text": "Loved it",
                "timestamp": 1700000000,
                "like_count": 12,
                "replies": [
                    {
                        "id": "2",
                        "author": "bob",
                        "text": "Me too",
                        "timestamp": 1700000100,
                        "like_count": 3,
                        "replies": [],
                    }
                ],
            },
            {"id": "3", "text": "No author,\nno\tmeta"},
        ]
    )
    with (
        patch.object(scrape_service, "_YT_SUBPROCESS_ENABLED", False),
        patch(
            "qualcoder_api.services.scrape_service.yt_dlp.YoutubeDL",
            return_value=FakeYoutubeDL(info=info),
        ),
        patch("qualcoder_api.services.scrape_service.fetch_url") as fetch,
    ):
        content = scrape_service.scrape_youtube("https://www.youtube.com/watch?v=abc")

    fetch.assert_not_called()  # captions never replace a comment list
    assert content.filename == "Demo Video.csv"
    text = content.data.decode("utf-8")
    assert text == (
        "author,likes,date,comment\r\n"
        "alice,12 likes,2023-11-14 22:13,Loved it\r\n"
        "→ bob,3 likes,2023-11-14 22:15,Me too\r\n"
        'unknown,-,-,"No author, no meta"\r\n'
    )
    for row in youtube_comment_table(text):
        assert len(row) == 4


def test_youtube_captions_never_replace_extracted_comments():
    """Even when caption tracks exist, a non-empty comment list always
    wins: the four-column CSV renders and captions are not fetched."""
    info = make_youtube_info()  # default: comments present + en captions
    with (
        patch.object(scrape_service, "_YT_SUBPROCESS_ENABLED", False),
        patch(
            "qualcoder_api.services.scrape_service.yt_dlp.YoutubeDL",
            return_value=FakeYoutubeDL(info=info),
        ),
        patch("qualcoder_api.services.scrape_service.fetch_url") as fetch,
    ):
        content = scrape_service.scrape_youtube("https://www.youtube.com/watch?v=abc")

    fetch.assert_not_called()
    text = content.data.decode("utf-8")
    assert text.startswith("author,likes,date,comment")
    assert "Hello caption text" not in text
    assert "viewer1,-,-,Great video" in text


# ----------------------------------------------------------------------
# Raw HTML capture (offline snapshot)
# ----------------------------------------------------------------------

SNAPSHOT_PAGE = b"""<!DOCTYPE html>
<html>
<head>
<title>Snapshot Page</title>
<link rel="stylesheet" href="/styles/main.css">
</head>
<body>
<img src="images/pic.png" alt="A picture">
<p>Offline-ready text.</p>
</body>
</html>"""

SNAPSHOT_CSS = b"""@font-face { font-family: "Custom"; src: url("fonts/custom.woff2") format("woff2"); }
body { background: url(https://other.example/bg.png); }
"""

SNAPSHOT_PNG = b"\x89PNG\r\n\x1a\n" + b"0123456789"
SNAPSHOT_FONT = b"wOF2-fake-font-bytes"


def snapshot_resources() -> dict:
    """Page + sub-resources keyed by the absolute URL the rewriter resolves."""
    return {
        "https://example.org/page": SNAPSHOT_PAGE,
        "https://example.org/styles/main.css": SNAPSHOT_CSS,
        "https://example.org/images/pic.png": SNAPSHOT_PNG,
        "https://example.org/styles/fonts/custom.woff2": SNAPSHOT_FONT,
    }


def test_html_mode_inlines_css_images_and_fonts():
    """The offline snapshot inlines same-origin stylesheets (with their
    fonts rewritten to data: URIs, resolved against the CSS's own URL) and
    images; cross-origin resources stay as links; no relative URLs remain."""
    resources = snapshot_resources()

    def fake_fetch(url: str, timeout: int = 45) -> bytes:
        return resources[url]

    with patch("qualcoder_api.services.scrape_service.fetch_url", side_effect=fake_fetch):
        content = scrape_service.scrape_html("https://example.org/page")

    assert content.mode == "html"
    assert content.filename == "Snapshot Page.html"
    text = content.data.decode("utf-8")
    # CSS inlined into a <style> block with the font as a data: URI
    assert "<style>" in text
    assert "</style>" in text
    assert "@font-face" in text
    assert "data:font/woff2;base64," in text
    assert "custom.woff2" not in text
    assert "https://example.org/styles/fonts/custom.woff2" not in text
    # Image inlined as a data: URI
    assert 'src="data:image/png;base64,' in text
    assert "images/pic.png" not in text
    # Stylesheet link consumed; cross-origin CSS reference kept
    assert "/styles/main.css" not in text
    assert "https://other.example/bg.png" in text
    # Encoding pinned so the saved file re-renders its own text
    assert '<meta charset="utf-8">' in text
    assert "Offline-ready text." in text


def test_html_mode_keeps_original_urls_when_subresources_fail():
    """A sub-resource that cannot be fetched must not break the capture —
    its original URL stays in place."""

    def fake_fetch(url: str, timeout: int = 45) -> bytes:
        if url == "https://example.org/page":
            return SNAPSHOT_PAGE
        raise ScrapeError("server returned HTTP 404 for " + url, code=404)

    with patch("qualcoder_api.services.scrape_service.fetch_url", side_effect=fake_fetch):
        content = scrape_service.scrape_html("https://example.org/page")

    text = content.data.decode("utf-8")
    assert 'href="/styles/main.css"' in text
    assert 'src="images/pic.png"' in text
    assert "data:" not in text
    assert "Offline-ready text." in text


def test_html_mode_skips_oversized_images():
    """Images over the 1 MB per-image cap keep their original URL."""
    resources = snapshot_resources()
    page = resources["https://example.org/page"].replace(b"images/pic.png", b"/huge.png")
    resources["https://example.org/page"] = page

    def fake_fetch(url: str, timeout: int = 45) -> bytes:
        if url == "https://example.org/huge.png":
            return b"x" * (1 * 1024 * 1024 + 1)
        return resources[url]

    with patch("qualcoder_api.services.scrape_service.fetch_url", side_effect=fake_fetch):
        content = scrape_service.scrape_html("https://example.org/page")

    text = content.data.decode("utf-8")
    assert 'src="/huge.png"' in text
    assert "data:image" not in text


def test_html_mode_rewrites_page_without_subresources():
    """A page with no sub-resources round-trips: markup and text preserved,
    the encoding meta added, nothing inlined."""
    with patch("qualcoder_api.services.scrape_service.fetch_url", return_value=ARTICLE_HTML):
        content = scrape_service.scrape_html("https://example.org/page")

    assert content.mode == "html"
    assert content.filename == "Testing Article.html"
    text = content.data.decode("utf-8")
    assert "The first paragraph of the article body with real content." in text
    assert "Navigation noise that should not appear." in text
    assert '<meta charset="utf-8">' in text
    assert "data:" not in text


# ----------------------------------------------------------------------
# PDF capture
# ----------------------------------------------------------------------

def test_pdf_mode_renders_page_to_pdf():
    import fitz

    with patch("qualcoder_api.services.scrape_service.fetch_url", return_value=ARTICLE_HTML):
        content = scrape_service.scrape_pdf("https://example.org/page")

    assert content.mode == "pdf"
    assert content.filename == "Testing Article.pdf"
    assert content.data.startswith(b"%PDF")
    with fitz.open(stream=content.data, filetype="pdf") as doc:
        assert doc.page_count >= 1
        text = "".join(page.get_text() for page in doc)
        # MuPDF extracts ligatures (\ufb01 = "fi"), so avoid "fi" substrings.
        assert "article body with real content" in text


def test_pdf_mode_falls_back_to_text_pdf_when_render_fails(monkeypatch):
    """A failing Story layout render must not break the import — the plain
    text of the page is rendered into a minimal text-only PDF instead."""
    import fitz

    real_render = scrape_service._story_render

    def layout_boom(html: str, css: str | None) -> bytes:
        if css is not None:
            raise RuntimeError("css boom")
        return real_render(html, css)

    monkeypatch.setattr(scrape_service, "_story_render", layout_boom)
    with patch("qualcoder_api.services.scrape_service.fetch_url", return_value=ARTICLE_HTML):
        content = scrape_service.scrape_pdf("https://example.org/page")

    assert content.mode == "pdf"
    assert content.filename == "Testing Article.pdf"
    assert content.data.startswith(b"%PDF")
    with fitz.open(stream=content.data, filetype="pdf") as doc:
        text = "".join(page.get_text() for page in doc)
        assert "article body with real content" in text


def test_pdf_mode_raises_when_render_fails_and_page_has_no_text(monkeypatch):
    def boom(*_args, **_kwargs):
        raise RuntimeError("css boom")

    monkeypatch.setattr(scrape_service, "_story_render", boom)
    with (
        patch("qualcoder_api.services.scrape_service.fetch_url", return_value=b"<html></html>"),
        pytest.raises(ScrapeError, match="render"),
    ):
        scrape_service.scrape_pdf("https://example.org/empty")


# ----------------------------------------------------------------------
# API endpoint
# ----------------------------------------------------------------------

async def test_scrape_import_creates_source_and_audits(scrape_client):
    client, target = scrape_client
    with patch("qualcoder_api.services.scrape_service.fetch_url", return_value=reddit_payload()):
        res = await client.post(
            "/api/v1/scrape/import", json={"url": "https://www.reddit.com/r/Test/comments/abc/"}
        )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["mode"] == "reddit"
    assert body["name"] == "My Reddit Thread.txt"
    assert body["text_length"] > 0

    got = await client.get(f"/api/v1/sources/{body['source_id']}")
    assert got.status_code == 200
    assert got.json()["name"] == "My Reddit Thread.txt"
    assert (target / "documents" / "My Reddit Thread.txt").exists()

    with sqlite3.connect(str(target / "data.qda")) as conn:
        row = conn.execute(
            "SELECT action, entity, entity_id, detail FROM audit_log ORDER BY ts DESC LIMIT 1"
        ).fetchone()
    assert row[0] == "scrape.import"
    assert row[1] == "source"
    assert row[2] == body["source_id"]
    assert "reddit" in json.loads(row[3])["mode"]


async def test_scrape_import_article_default_mode(scrape_client):
    client, _ = scrape_client
    with patch("qualcoder_api.services.scrape_service.fetch_url", return_value=ARTICLE_HTML):
        res = await client.post(
            "/api/v1/scrape/import", json={"url": "https://example.org/testing"}
        )
    assert res.status_code == 200, res.text
    assert res.json()["mode"] == "article"


async def test_scrape_import_duplicate_returns_409(scrape_client):
    client, _ = scrape_client
    with patch("qualcoder_api.services.scrape_service.fetch_url", return_value=reddit_payload()):
        first = await client.post(
            "/api/v1/scrape/import", json={"url": "https://www.reddit.com/r/Test/comments/abc/"}
        )
        assert first.status_code == 200, first.text
        second = await client.post(
            "/api/v1/scrape/import", json={"url": "https://www.reddit.com/r/Test/comments/abc/"}
        )
    assert second.status_code == 409
    assert "duplicate" in second.json()["detail"]


async def test_scrape_import_bad_url_returns_422(scrape_client):
    client, _ = scrape_client
    res = await client.post("/api/v1/scrape/import", json={"url": "ftp://example.org/x"})
    assert res.status_code == 422
    assert "http" in res.json()["detail"]


async def test_scrape_import_unknown_mode_returns_422(scrape_client):
    client, _ = scrape_client
    res = await client.post(
        "/api/v1/scrape/import", json={"url": "https://example.org/x", "mode": "rss"}
    )
    assert res.status_code == 422


async def test_scrape_import_without_project_returns_409(scrape_client):
    client, _ = scrape_client
    await client.post("/api/v1/projects/close")
    res = await client.post(
        "/api/v1/scrape/import", json={"url": "https://www.reddit.com/r/Test/comments/abc/"}
    )
    assert res.status_code == 409


def test_scrape_url_auto_dispatch_returns_content():
    with patch("qualcoder_api.services.scrape_service.fetch_url", return_value=ARTICLE_HTML):
        content = scrape_service.scrape_url("https://example.org/testing", mode="auto")
    assert isinstance(content, ScrapedContent)
    assert content.filename.endswith(".txt")


def test_scrape_url_pdf_dispatch_returns_pdf_content():
    with patch("qualcoder_api.services.scrape_service.fetch_url", return_value=ARTICLE_HTML):
        content = scrape_service.scrape_url("https://example.org/page", mode="pdf")
    assert content.mode == "pdf"
    assert content.filename == "Testing Article.pdf"
    assert content.data.startswith(b"%PDF")


async def test_scrape_import_pdf_mode_creates_pdf_source(scrape_client):
    """mode=pdf persists through the file-import pipeline as a .pdf source
    with extracted fulltext (the PdfCoder path)."""
    client, target = scrape_client
    with patch("qualcoder_api.services.scrape_service.fetch_url", return_value=ARTICLE_HTML):
        res = await client.post(
            "/api/v1/scrape/import", json={"url": "https://example.org/page", "mode": "pdf"}
        )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["mode"] == "pdf"
    assert body["name"] == "Testing Article.pdf"
    assert body["text_length"] > 0

    stored = target / "documents" / "Testing Article.pdf"
    assert stored.exists()

    import fitz

    with fitz.open(stream=stored.read_bytes(), filetype="pdf") as doc:
        assert doc.page_count >= 1
        text = "".join(page.get_text() for page in doc)
        assert "article body with real content" in text

    got = await client.get(f"/api/v1/sources/{body['source_id']}")
    assert got.status_code == 200
    # PDF sources live under /docs/ as TEXT with a .pdf name — exactly the
    # shape the frontend's usesPdfCoder() routes to the PdfCoder.
    assert got.json()["media_type"] == "text"
    assert got.json()["name"] == "Testing Article.pdf"
