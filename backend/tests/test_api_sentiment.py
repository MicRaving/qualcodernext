"""API + service tests for the sentiment report.

VADER scoring is checked against known fixtures ("I love this!" positive,
"This is terrible." negative); the AI mode fakes the HTTP layer by
monkeypatching ``AsyncClient`` in ``qualcoder_api.services.ai_service`` —
no network is ever touched.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from qualcoder_api.api.v1.sentiment import router as sentiment_router
from qualcoder_api.main import app
from qualcoder_api.services import ai_service as ai_service_module
from qualcoder_api.services import sentiment_service

app.include_router(sentiment_router, prefix="/api/v1")


class FakeResponse:
    status_code = 200

    def __init__(self, payload, status_code=None):
        self._payload = payload
        if status_code is not None:
            self.status_code = status_code

    def json(self):
        return self._payload

    def raise_for_status(self):
        pass


class SentimentFakeClient:
    """Answers /chat/completions with a sentiment label derived from the
    message content, so each segment in the batch gets its own label."""

    def __init__(self):
        self.calls: list[dict] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        pass

    async def post(self, url: str, **kwargs):
        self.calls.append({"url": url, **kwargs})
        messages = (kwargs.get("json") or {}).get("messages") or []
        content = str(messages[-1].get("content", "")) if messages else ""
        if "terrible" in content or "hate" in content:
            label = "negative"
        elif "love" in content or "great" in content:
            label = "positive"
        else:
            label = "neutral"
        reply = f"{label}. The text expresses {label} feelings."
        return FakeResponse({"choices": [{"message": {"content": reply}}]})


def patch_client(monkeypatch) -> SentimentFakeClient:
    fake = SentimentFakeClient()
    monkeypatch.setattr(ai_service_module, "AsyncClient", lambda **kw: fake)
    return fake


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    """Keep the developer's real AI settings out of the run."""
    from qualcoder_api.services import user_settings

    monkeypatch.setattr(user_settings, "SETTINGS_FILE", tmp_path / "settings.json")


@pytest.fixture
async def project_client(tmp_path):
    """API client with a fresh open project."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        target = tmp_path / "sentiment.qda"
        res = await c.post(
            "/api/v1/projects", json={"project_path": str(target), "codername": "tester"}
        )
        assert res.status_code == 200, res.text
        yield c, target
        await c.post("/api/v1/projects/close")


@pytest.fixture
async def sentiment_dataset(project_client):
    """Two sources with positive/negative/neutral coded segments."""
    client, _ = project_client

    res = await client.post(
        "/api/v1/sources/import",
        files={"file": ("happy.txt", "I love this! Everything is wonderful.", "text/plain")},
    )
    assert res.status_code == 200, res.text
    happy_fid = res.json()["id"]

    res = await client.post(
        "/api/v1/sources/import",
        files={"file": ("sad.txt", "This is terrible. What a disaster.", "text/plain")},
    )
    assert res.status_code == 200, res.text
    sad_fid = res.json()["id"]

    res = await client.post(
        "/api/v1/sources/import",
        files={"file": ("flat.txt", "The sky is blue.", "text/plain")},
    )
    assert res.status_code == 200, res.text
    flat_fid = res.json()["id"]

    code_pos = await client.post("/api/v1/codes", json={"name": "Positive"})
    assert code_pos.status_code == 201, code_pos.text
    code_neg = await client.post("/api/v1/codes", json={"name": "Negative"})
    assert code_neg.status_code == 201, code_neg.text
    cids = {"pos": code_pos.json()["cid"], "neg": code_neg.json()["cid"]}

    segments = [
        (cids["pos"], happy_fid, "I love this!", 0, 13),
        (cids["neg"], sad_fid, "This is terrible.", 0, 17),
        (cids["pos"], flat_fid, "The sky is blue.", 0, 16),
    ]
    for cid, fid, seltext, pos0, pos1 in segments:
        res = await client.post(
            "/api/v1/codings/text",
            json={"cid": cid, "fid": fid, "seltext": seltext, "pos0": pos0, "pos1": pos1},
        )
        assert res.status_code == 201, res.text

    return {"fids": {"happy": happy_fid, "sad": sad_fid, "flat": flat_fid}, "cids": cids}


# ----------------------------------------------------------------------
# Lexicon scoring (VADER)
# ----------------------------------------------------------------------


async def test_segments_sentiment_vader_fixtures(project_client, sentiment_dataset):
    client, _ = project_client
    body = (await client.get("/api/v1/reports/sentiment")).json()
    assert body["mode"] == "lexicon"
    assert body["scope"] == "segments"
    assert len(body["rows"]) == 3

    by_seltext = {r["seltext"]: r for r in body["rows"]}
    positive = by_seltext["I love this!"]
    assert positive["file_name"] == "happy.txt"
    assert positive["code_name"] == "Positive"
    assert positive["compound"] >= 0.05
    assert positive["pos"] > positive["neg"]

    negative = by_seltext["This is terrible."]
    assert negative["file_name"] == "sad.txt"
    assert negative["code_name"] == "Negative"
    assert negative["compound"] <= -0.05
    assert negative["neg"] > negative["pos"]

    neutral = by_seltext["The sky is blue."]
    assert neutral["compound"] > -0.05
    assert neutral["compound"] < 0.05


async def test_segments_sentiment_distribution(project_client, sentiment_dataset):
    client, _ = project_client
    summary = (await client.get("/api/v1/reports/sentiment")).json()["summary"]
    assert summary["positive"] == 1
    assert summary["negative"] == 1
    assert summary["neutral"] == 1
    assert summary["total"] == 3
    assert summary["avg_compound"] is not None


async def test_segments_sentiment_filters(project_client, sentiment_dataset):
    client, _ = project_client
    fid = sentiment_dataset["fids"]["happy"]
    rows = (await client.get(f"/api/v1/reports/sentiment?fid={fid}")).json()["rows"]
    assert len(rows) == 1
    assert rows[0]["file_name"] == "happy.txt"

    cid = sentiment_dataset["cids"]["pos"]
    rows = (await client.get(f"/api/v1/reports/sentiment?cid={cid}")).json()["rows"]
    assert len(rows) == 2
    assert {r["code_name"] for r in rows} == {"Positive"}

    rows = (await client.get(f"/api/v1/reports/sentiment?fid={fid}&cid={cid}")).json()["rows"]
    assert len(rows) == 1
    assert rows[0]["file_name"] == "happy.txt"


async def test_sources_sentiment_scores_whole_texts(project_client, sentiment_dataset):
    client, _ = project_client
    body = (await client.get("/api/v1/reports/sentiment?scope=sources")).json()
    assert body["scope"] == "sources"
    by_name = {r["file_name"]: r for r in body["rows"]}
    assert by_name["happy.txt"]["compound"] >= 0.05
    assert by_name["sad.txt"]["compound"] <= -0.05
    # Whole-source rows carry no code columns.
    assert "code_name" not in by_name["happy.txt"]
    summary = body["summary"]
    assert summary["positive"] == 1
    assert summary["negative"] == 1
    assert summary["neutral"] == 1
    assert summary["total"] == 3


async def test_sources_sentiment_fid_filter(project_client, sentiment_dataset):
    client, _ = project_client
    fid = sentiment_dataset["fids"]["sad"]
    body = (await client.get(f"/api/v1/reports/sentiment?scope=sources&fid={fid}")).json()
    assert [r["file_name"] for r in body["rows"]] == ["sad.txt"]


async def test_invalid_scope_and_mode(project_client):
    client, _ = project_client
    res = await client.get("/api/v1/reports/sentiment?scope=paragraphs")
    assert res.status_code == 422
    res = await client.get("/api/v1/reports/sentiment?mode=deep")
    assert res.status_code == 422


# ----------------------------------------------------------------------
# AI mode
# ----------------------------------------------------------------------

async def configure_ai(client, tmp_path, monkeypatch, enabled=True) -> None:
    from qualcoder_api.services import user_settings

    monkeypatch.setattr(user_settings, "SETTINGS_FILE", tmp_path / "settings.json")
    res = await client.put(
        "/api/v1/ai/settings",
        json={
            "enabled": enabled,
            "provider": "ollama",
            "api_base": "http://localhost:11434/v1",
            "model": "llama3.2",
            "api_key": "",
        },
    )
    assert res.status_code == 200, res.text


async def test_ai_mode_requires_configuration(project_client, sentiment_dataset):
    client, _ = project_client
    res = await client.get("/api/v1/reports/sentiment?mode=ai")
    assert res.status_code == 409
    assert res.json()["detail"] == "AI not configured"


async def test_ai_mode_rejects_sources_scope(project_client, tmp_path, monkeypatch, sentiment_dataset):
    client, _ = project_client
    await configure_ai(client, tmp_path, monkeypatch)
    res = await client.get("/api/v1/reports/sentiment?mode=ai&scope=sources")
    assert res.status_code == 422


async def test_ai_mode_batches_segments(project_client, tmp_path, monkeypatch, sentiment_dataset):
    client, _ = project_client
    await configure_ai(client, tmp_path, monkeypatch)
    fake = patch_client(monkeypatch)

    body = (await client.get("/api/v1/reports/sentiment?mode=ai")).json()
    assert body["mode"] == "ai"
    assert len(body["rows"]) == 3

    by_seltext = {r["seltext"]: r for r in body["rows"]}
    assert by_seltext["I love this!"]["sentiment"] == "positive"
    assert by_seltext["This is terrible."]["sentiment"] == "negative"
    assert by_seltext["The sky is blue."]["sentiment"] == "neutral"
    assert all(r["reason"] for r in body["rows"])
    # Every row carries the same columns as the lexicon segment report.
    assert by_seltext["I love this!"]["code_name"] == "Positive"

    summary = body["summary"]
    assert summary["positive"] == 1
    assert summary["negative"] == 1
    assert summary["neutral"] == 1
    assert summary["total"] == 3
    assert summary["avg_compound"] is None

    # One chat call per segment, each with the sentiment prompt.
    assert len(fake.calls) == 3
    for call in fake.calls:
        assert call["url"].endswith("/chat/completions")
        content = call["json"]["messages"][1]["content"]
        assert content.startswith("Instructions:\n")
        assert "Classify the sentiment" in content


async def test_ai_mode_batch_cap(project_client, tmp_path, monkeypatch, sentiment_dataset):
    client, _ = project_client
    await configure_ai(client, tmp_path, monkeypatch)
    fake = patch_client(monkeypatch)

    body = (await client.get("/api/v1/reports/sentiment?mode=ai&limit=2")).json()
    assert len(body["rows"]) == 2
    assert len(fake.calls) == 2
    assert body["summary"]["total"] == 2


# ----------------------------------------------------------------------
# Service-level units
# ----------------------------------------------------------------------

def test_score_text_known_fixtures():
    positive = sentiment_service.score_text("I love this!")
    assert positive["compound"] >= 0.05
    assert positive["pos"] > positive["neg"]
    assert sentiment_service.compound_class(positive["compound"]) == "positive"

    negative = sentiment_service.score_text("This is terrible.")
    assert negative["compound"] <= -0.05
    assert negative["neg"] > negative["pos"]
    assert sentiment_service.compound_class(negative["compound"]) == "negative"

    neutral = sentiment_service.score_text("The sky is blue.")
    assert neutral["compound"] > -0.05
    assert neutral["compound"] < 0.05
    assert sentiment_service.compound_class(neutral["compound"]) == "neutral"


def test_compound_thresholds():
    assert sentiment_service.compound_class(0.05) == "positive"
    assert sentiment_service.compound_class(-0.05) == "negative"
    assert sentiment_service.compound_class(0.0) == "neutral"


def test_summarize_counts():
    summary = sentiment_service.summarize([0.9, -0.9, 0.0, 0.5, -0.1])
    assert summary["positive"] == 2
    assert summary["negative"] == 2
    assert summary["neutral"] == 1
    assert summary["total"] == 5
    assert summary["avg_compound"] is not None

    empty = sentiment_service.summarize([])
    assert empty["total"] == 0
    assert empty["avg_compound"] is None


def test_classify_ai_reply():
    assert sentiment_service.classify_ai_reply("positive. Uplifting tone.") == (
        "positive",
        "positive. Uplifting tone.",
    )
    assert sentiment_service.classify_ai_reply("Negative — discouraging.")[0] == "negative"
    assert sentiment_service.classify_ai_reply("Neutral: factual statement.")[0] == "neutral"
    # Unrecognized replies fall back to neutral, keeping the text as reason.
    sentiment, reason = sentiment_service.classify_ai_reply("Hmm, ambiguous.")
    assert sentiment == "neutral"
    assert reason == "Hmm, ambiguous."
