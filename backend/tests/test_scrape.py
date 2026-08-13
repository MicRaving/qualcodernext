"""URL import tests — Reddit/YouTube/article scraping, source persistence,
duplicate detection and audit."""

from __future__ import annotations

import json
import sqlite3
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from qualcoder_api.api.v1.router import router as v1_router
from qualcoder_api.api.v1.scrape import router as scrape_router
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


class FakeYoutubeDL:
    """Minimal yt-dlp stand-in: extract_info returns a fixed info dict."""

    def __init__(self, options=None, info=None):
        self.options = options or {}
        self.info = info or {}

    def extract_info(self, url, download=False):
        return self.info

    def close(self):
        pass


def make_ydl_factory(info: dict) -> tuple[list, ...]:
    """Patch side_effect that builds a FakeYoutubeDL and records its options."""
    created: list[FakeYoutubeDL] = []

    def factory(options=None):
        ydl = FakeYoutubeDL(options=options, info=info)
        created.append(ydl)
        return ydl

    return factory, created


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

    def fake_fetch(url: str, timeout: int = 45) -> bytes:
        seen.append(url)
        return reddit_payload()

    with patch("qualcoder_api.services.scrape_service.fetch_url", side_effect=fake_fetch):
        scrape_service.scrape_reddit("https://www.reddit.com/r/Test/comments/abc123/title/?sort=new")

    assert seen == ["https://www.reddit.com/r/Test/comments/abc123/title.json?sort=new"]


def test_reddit_json_url_used_as_is():
    assert scrape_service._reddit_json_url("https://www.reddit.com/r/x/comments/a/b.json") == (
        "https://www.reddit.com/r/x/comments/a/b.json"
    )


def test_reddit_rejects_non_json_response():
    with patch("qualcoder_api.services.scrape_service.fetch_url", return_value=b"<html>"), pytest.raises(ScrapeError, match="not JSON"):
        scrape_service.scrape_reddit("https://www.reddit.com/r/x/comments/a/")

    with patch("qualcoder_api.services.scrape_service.fetch_url", return_value=b"{}"), pytest.raises(ScrapeError, match="response shape"):
        scrape_service.scrape_reddit("https://www.reddit.com/r/x/comments/a/")


def test_reddit_accepts_single_listing_object():
    post_listing = {"kind": "Listing", "data": {"children": [REDDIT_POST["data"]["children"][0]]}}
    payload = json.dumps(post_listing).encode("utf-8")
    with patch("qualcoder_api.services.scrape_service.fetch_url", return_value=payload):
        content = scrape_service.scrape_reddit("https://www.reddit.com/r/Test/comments/abc123/")

    text = content.data.decode("utf-8")
    assert "My Reddit Thread" in text
    assert "The selftext body." in text
    assert "Comments" not in text


@pytest.mark.parametrize("code", [403, 429])
def test_reddit_http_block_maps_to_rate_limit_message(code):
    err = ScrapeError(f"server returned HTTP {code} for https://www.reddit.com/...", code=code)
    with (
        patch("qualcoder_api.services.scrape_service.fetch_url", side_effect=err),
        pytest.raises(ScrapeError, match="rate-limited"),
    ):
        scrape_service.scrape_reddit("https://www.reddit.com/r/Test/comments/abc123/")


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
            {"id": "3", "text": "No author, no meta"},
        ]
    )
    factory, created = make_ydl_factory(info)
    with (
        patch("qualcoder_api.services.scrape_service.yt_dlp.YoutubeDL", side_effect=factory),
        patch("qualcoder_api.services.scrape_service.fetch_url") as fetch,
    ):
        content = scrape_service.scrape_youtube("https://www.youtube.com/watch?v=abc")

    assert created[0].options.get("getcomments") is True
    fetch.assert_not_called()  # captions are dropped when comments exist
    assert content.mode == "youtube"
    assert content.filename == "Demo Video.txt"
    text = content.data.decode("utf-8")
    assert "Demo Video" in text
    assert "Uploader: Demo Channel" in text
    assert "Duration: 1:23" in text
    assert "A description." in text
    assert "u/alice (12 likes, 2023-11-14 22:13): Loved it" in text
    assert "  u/bob (3 likes, 2023-11-14 22:15): Me too" in text
    assert "u/unknown: No author, no meta" in text
    assert "Captions" not in text
    assert "Hello caption text" not in text


def test_youtube_falls_back_to_captions_when_comments_missing():
    info = make_youtube_info(comments=[])
    with (
        patch("qualcoder_api.services.scrape_service.yt_dlp.YoutubeDL", return_value=FakeYoutubeDL(info=info)),
        patch("qualcoder_api.services.scrape_service.fetch_url", return_value=VTT_CAPTIONS),
    ):
        content = scrape_service.scrape_youtube("https://www.youtube.com/watch?v=abc")

    text = content.data.decode("utf-8")
    assert "[00:01] Hello caption text" in text
    assert "[00:03] Second line" in text
    assert "Comments" not in text


def test_youtube_without_comments_or_captions_keeps_header():
    info = make_youtube_info(subtitles={}, automatic_captions={}, comments=[])
    with (
        patch("qualcoder_api.services.scrape_service.yt_dlp.YoutubeDL", return_value=FakeYoutubeDL(info=info)),
        patch("qualcoder_api.services.scrape_service.fetch_url") as fetch,
    ):
        content = scrape_service.scrape_youtube("https://www.youtube.com/watch?v=abc")

    fetch.assert_not_called()
    text = content.data.decode("utf-8")
    assert "Demo Video" in text
    assert "A description." in text
    assert "Captions" not in text
    assert "Comments" not in text


def test_youtube_reports_when_comment_extraction_unsupported():
    info = make_youtube_info()
    factory, created = make_ydl_factory(info)
    with (
        patch.object(scrape_service, "_YT_DLP_COMMENTS_SUPPORTED", False),
        patch("qualcoder_api.services.scrape_service.yt_dlp.YoutubeDL", side_effect=factory),
        patch("qualcoder_api.services.scrape_service.fetch_url") as fetch,
    ):
        content = scrape_service.scrape_youtube("https://www.youtube.com/watch?v=abc")

    assert "getcomments" not in created[0].options
    fetch.assert_not_called()
    text = content.data.decode("utf-8")
    assert "Demo Video" in text
    assert "u/viewer1" not in text
    assert "Captions" not in text
    assert "cannot extract comments" in text


def test_youtube_caption_fetch_failure_keeps_header():
    info = make_youtube_info(comments=[])
    with (
        patch("qualcoder_api.services.scrape_service.yt_dlp.YoutubeDL", return_value=FakeYoutubeDL(info=info)),
        patch(
            "qualcoder_api.services.scrape_service.fetch_url",
            side_effect=ScrapeError("server returned HTTP 403"),
        ),
    ):
        content = scrape_service.scrape_youtube("https://www.youtube.com/watch?v=abc")

    text = content.data.decode("utf-8")
    assert "Demo Video" in text
    assert "Captions" not in text


# ----------------------------------------------------------------------
# Raw HTML capture
# ----------------------------------------------------------------------

def test_html_mode_keeps_raw_bytes():
    with patch("qualcoder_api.services.scrape_service.fetch_url", return_value=ARTICLE_HTML):
        content = scrape_service.scrape_html("https://example.org/page")

    assert content.mode == "html"
    assert content.filename == "Testing Article.html"
    assert content.data == ARTICLE_HTML


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
