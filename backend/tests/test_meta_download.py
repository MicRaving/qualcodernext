"""Tests for the meta paper-download candidate resolver and pipeline.

The network is faked with a tiny client (``FakeClient``) so candidate ordering,
the Europe PMC / Unpaywall fallbacks and the download pipeline are exercised
without touching the internet.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from qualcoder_api.persistence.database import (
    create_all_tables,
    create_project_engine,
    create_session_factory,
    dispose_engine,
)
from qualcoder_api.persistence.repo.meta_repo import MetaRepository
from qualcoder_api.services import import_service, meta_download

# ── fake httpx client ────────────────────────────────────────────────────


class _Resp:
    def __init__(self, status=200, payload=None, text="", headers=None, url="http://fake"):
        self.status_code = status
        self._payload = payload
        self.text = text
        self.headers = headers or {}
        self.url = url

    def json(self):
        if self._payload is None:
            raise ValueError("no json body")
        return self._payload


class _Stream:
    def __init__(self, status=200, headers=None, chunks=None):
        self.status_code = status
        self.headers = headers or {}
        self._chunks = chunks if chunks is not None else []

    async def aiter_bytes(self):
        for chunk in self._chunks:
            yield chunk


class _StreamCtx:
    def __init__(self, stream: _Stream):
        self._stream = stream

    async def __aenter__(self) -> _Stream:
        return self._stream

    async def __aexit__(self, *exc) -> bool:
        return False


class FakeClient:
    """Routes ``.get`` by URL substring; ``.stream`` by URL substring too."""

    def __init__(self, get_routes=None, stream_routes=None):
        self.get_routes = get_routes or {}
        self.stream_routes = stream_routes or {}
        self.get_calls: list[str] = []
        self.stream_calls: list[str] = []

    async def get(self, url, **_kwargs):
        self.get_calls.append(url)
        for needle, response in self.get_routes.items():
            if needle in url:
                return response() if callable(response) else response
        return _Resp(status=404)

    def stream(self, _method, url, **_kwargs):
        self.stream_calls.append(url)
        for needle, stream in self.stream_routes.items():
            if needle in url:
                resolved = stream() if callable(stream) else stream
                return _StreamCtx(resolved)
        return _StreamCtx(_Stream(status=404))


# ── resolve_candidates ───────────────────────────────────────────────────

DOI = "10.1234/abc"


def _order_routes() -> dict:
    work = {
        "locations": [
            {  # publisher PDF first in the payload …
                "is_oa": True,
                "pdf_url": "https://publisher.example/paper.pdf",
                "landing_page_url": "https://publisher.example/paper",
                "source": {"type": "journal"},
            },
            {  # … a repository that only offers a landing page …
                "is_oa": True,
                "pdf_url": None,
                "landing_page_url": "https://repo.example/landing",
                "source": {"type": "repository"},
            },
            {  # … and a repository with a direct PDF.
                "is_oa": True,
                "pdf_url": "https://repo.example/paper.pdf",
                "landing_page_url": None,
                "source": {"type": "repository"},
            },
        ],
    }
    unpaywall = {
        "oa_locations": [
            {"host_type": "publisher", "url_for_pdf": "https://publisher.example/paper.pdf"},
            {"host_type": "repository", "url_for_pdf": "https://repo.example/paper.pdf"},
        ]
    }
    crossref = {"message": {"title": ["T"], "URL": "https://doi.org/10.1234/abc"}}
    return {
        "api.openalex.org": _Resp(payload=work),
        "api.unpaywall.org": _Resp(payload=unpaywall),
        "europepmc": _Resp(payload={"resultList": {"result": []}}),
        "api.crossref.org": _Resp(payload=crossref),
        "repo.example/landing": _Resp(
            text='<meta name="citation_pdf_url" content="https://repo.example/landing.pdf">'
        ),
    }


async def test_resolve_candidates_prefers_repository_over_publisher():
    client = FakeClient(get_routes=_order_routes())
    candidates = await meta_download.resolve_candidates(client, DOI, "me@example.org")

    urls = [c["url"] for c in candidates]
    methods = [c["method"] for c in candidates]
    # Repository/OA mirrors sort ahead of the publisher PDF.
    assert candidates[0]["host_type"] == "repository"
    assert urls.index("https://repo.example/paper.pdf") < urls.index(
        "https://publisher.example/paper.pdf"
    )
    # The landing-page-only repository location contributes a resolved PDF.
    assert "https://repo.example/landing.pdf" in urls
    assert "openalex-landing" in methods
    # Repository candidates appear before any non-repository candidate.
    first_non_repo = next(i for i, c in enumerate(candidates) if c["host_type"] != "repository")
    assert all(c["host_type"] == "repository" for c in candidates[:first_non_repo])
    # The DOI resolver duplicates the Crossref landing URL, so it is deduped.
    assert urls.count("https://doi.org/10.1234/abc") == 1
    assert len(urls) == len(set(urls))


async def test_resolve_candidates_adds_europepmc_render_link():
    routes = _order_routes()
    routes["europepmc"] = _Resp(
        payload={"resultList": {"result": [{"pmcid": "PMC7654321"}]}}
    )
    client = FakeClient(get_routes=routes)
    candidates = await meta_download.resolve_candidates(client, DOI, "me@example.org")

    europepmc = [c for c in candidates if c["method"] == "europepmc"]
    assert len(europepmc) == 1
    assert europepmc[0]["url"] == "https://europepmc.org/articles/PMC7654321?pdf=render"
    assert europepmc[0]["host_type"] == "repository"


async def test_resolve_candidates_tolerates_unpaywall_422():
    routes = _order_routes()
    routes["api.unpaywall.org"] = _Resp(status=422)
    client = FakeClient(get_routes=routes)

    info: dict = {}
    candidates = await meta_download.resolve_candidates(
        client, DOI, "placeholder@example.com", info=info
    )

    # No crash, no unpaywall candidates, but the other sources still resolve.
    assert all(c["method"] != "unpaywall" for c in candidates)
    assert candidates
    assert info["unpaywall_email"] is True


async def test_resolve_candidates_notes_missing_email_without_requesting():
    routes = _order_routes()
    client = FakeClient(get_routes=routes)

    info: dict = {}
    await meta_download.resolve_candidates(client, DOI, "", info=info)

    assert info["unpaywall_email"] is True
    assert not any("api.unpaywall.org" in url for url in client.get_calls)


async def test_resolve_pdf_chain_wraps_first_candidate():
    client = FakeClient(get_routes=_order_routes())
    url, method, metadata = await meta_download.resolve_pdf_chain(client, DOI, "me@example.org")

    assert method == "openalex-landing" or method == "openalex"
    assert url is not None
    assert metadata is not None and metadata["title"] == "T"


# ── download_pdf detail reporting ────────────────────────────────────────


async def test_download_pdf_reports_blocking_status(tmp_path):
    dest = tmp_path / "paper.pdf"
    client = FakeClient(stream_routes={"publisher.example": _Stream(status=403)})

    detail: dict = {}
    assert await meta_download.download_pdf(
        client, "https://publisher.example/paper.pdf", dest, detail=detail
    ) is False
    assert detail["status"] == 403
    assert detail["reason"] == "HTTP 403"


async def test_download_pdf_reports_non_pdf(tmp_path):
    dest = tmp_path / "paper.pdf"
    client = FakeClient(
        stream_routes={
            "publisher.example": _Stream(
                status=200,
                headers={"content-type": "text/html"},
                chunks=[b"<html>nope</html>"],
            )
        }
    )

    detail: dict = {}
    assert await meta_download.download_pdf(
        client, "https://publisher.example/paper.pdf", dest, detail=detail
    ) is False
    assert detail["reason"] == "not a PDF response"
    assert detail["content_type"] == "text/html"


# ── run_downloads pipeline ───────────────────────────────────────────────


@pytest.fixture
async def project_factory(tmp_path):
    engine = create_project_engine(tmp_path / "pipeline.qda")
    await create_all_tables(engine)
    factory = create_session_factory(engine)
    yield factory
    await dispose_engine(engine)


class _FakeImport:
    def __init__(self, project_path, session_factory):
        self.project_path = project_path

    async def import_file(self, path, *, owner, filename):
        return SimpleNamespace(id=4242)


async def _seed_hit(factory, doi: str) -> int:
    async with factory() as session:
        hit = await MetaRepository(session).add_hit(title="Study A", doi=doi)
        return hit.hit_id


async def _noop_link(*_args, **_kwargs):
    return None


async def test_run_downloads_falls_through_to_later_candidate(project_factory, tmp_path, monkeypatch):
    hit_id = await _seed_hit(project_factory, DOI)
    attempted: list[str] = []

    async def fake_candidates(_client, _doi, _email, *, info=None):
        return [
            {"url": "https://publisher.example/paper.pdf", "method": "openalex", "host_type": "journal"},
            {"url": "https://repo.example/paper.pdf", "method": "unpaywall", "host_type": "repository"},
        ]

    async def fake_download(_client, url, dest, *, detail=None):
        attempted.append(url)
        if "publisher" in url:
            if detail is not None:
                detail.update({"status": 403, "reason": "HTTP 403"})
            return False
        dest.write_bytes(b"%PDF-1.4\n" + b"x" * 64)
        return True

    async def fake_zotero(_client, _doi, _dest):
        return False, "none"

    monkeypatch.setattr(meta_download, "resolve_candidates", fake_candidates)
    monkeypatch.setattr(meta_download, "download_pdf", fake_download)
    monkeypatch.setattr(meta_download, "try_zotero_pdf", fake_zotero)
    monkeypatch.setattr(meta_download, "_link_study_case", _noop_link)
    monkeypatch.setattr(import_service, "ImportService", _FakeImport)

    result = await meta_download.run_downloads(
        project_factory,
        project_path=str(tmp_path / "proj"),
        hit_ids=[hit_id],
        owner="tester",
        email="me@example.org",
    )

    assert attempted[0] == "https://publisher.example/paper.pdf"
    assert attempted[1] == "https://repo.example/paper.pdf"
    assert result["ok"] == 1 and result["failed"] == 0

    async with project_factory() as session:
        doc = await MetaRepository(session).get_document_for_hit(hit_id)
    assert doc is not None
    assert doc.status == "done"
    assert doc.retrieval_method == "unpaywall"
    assert doc.url == "https://repo.example/paper.pdf"


async def test_run_downloads_marks_unretrievable_without_candidates(
    project_factory, tmp_path, monkeypatch
):
    hit_id = await _seed_hit(project_factory, DOI)

    async def fake_candidates(_client, _doi, _email, *, info=None):
        return []

    async def fake_zotero(_client, _doi, _dest):
        return False, "none"

    monkeypatch.setattr(meta_download, "resolve_candidates", fake_candidates)
    monkeypatch.setattr(meta_download, "try_zotero_pdf", fake_zotero)

    result = await meta_download.run_downloads(
        project_factory,
        project_path=str(tmp_path / "proj"),
        hit_ids=[hit_id],
        owner="tester",
        email="",
    )

    assert result["failed"] == 1 and result["ok"] == 0
    async with project_factory() as session:
        doc = await MetaRepository(session).get_document_for_hit(hit_id)
    assert doc is not None
    assert doc.status == "unretrievable"
    assert doc.message is not None and "no open-access copy found" in doc.message


async def test_run_downloads_failed_message_names_last_status_and_email_hint(
    project_factory, tmp_path, monkeypatch
):
    hit_id = await _seed_hit(project_factory, DOI)

    async def fake_candidates(_client, _doi, _email, *, info=None):
        if info is not None:
            info["unpaywall_email"] = True
        return [
            {"url": "https://publisher.example/a.pdf", "method": "openalex", "host_type": "journal"},
            {"url": "https://publisher.example/b.pdf", "method": "unpaywall", "host_type": "publisher"},
        ]

    async def fake_download(_client, _url, _dest, *, detail=None):
        if detail is not None:
            detail.update({"status": 403, "reason": "HTTP 403"})
        return False

    async def fake_zotero(_client, _doi, _dest):
        return False, "none"

    monkeypatch.setattr(meta_download, "resolve_candidates", fake_candidates)
    monkeypatch.setattr(meta_download, "download_pdf", fake_download)
    monkeypatch.setattr(meta_download, "try_zotero_pdf", fake_zotero)

    result = await meta_download.run_downloads(
        project_factory,
        project_path=str(tmp_path / "proj"),
        hit_ids=[hit_id],
        owner="tester",
        email="bad",
    )

    assert result["failed"] == 1
    async with project_factory() as session:
        doc = await MetaRepository(session).get_document_for_hit(hit_id)
    assert doc is not None
    assert doc.status == "failed"
    assert doc.message is not None
    assert "all 2 sources blocked" in doc.message
    assert "HTTP 403" in doc.message
    assert "Unpaywall email" in doc.message


# ── repository status counts ─────────────────────────────────────────────


async def test_document_status_counts(project_factory):
    async with project_factory() as session:
        repo = MetaRepository(session)
        for i in (1, 2, 3, 4):
            await repo.add_hit(title=f"Study {i}", doi=f"10.1/{i}")
        await repo.upsert_document(hit_id=1, status="done")
        await repo.upsert_document(hit_id=2, status="failed")
        await repo.upsert_document(hit_id=3, status="done")
        await repo.upsert_document(hit_id=4, status="unretrievable")

        counts = await repo.document_status_counts()

    assert counts == {"done": 2, "failed": 1, "unretrievable": 1}
