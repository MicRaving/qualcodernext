"""Meta-analysis paper download — native OA resolver chain + Zotero reuse.

Zotero has no public machine API to "find a PDF for a DOI" — its retrieval is
internal (an Unpaywall data mirror plus custom resolver prefs run inside the
client). This module therefore reimplements the resolver semantics natively
(OpenAlex → Unpaywall → Crossref landing page), adapted from the reference
``Inoculation_Meta/meta/core/downloader.py`` but async and Selenium-free, and
additionally tries a running local Zotero (localhost:23119) for PDFs the user
already has. Anything the chain misses is handled by manual assignment in the
UI.
"""

from __future__ import annotations

import contextlib
import logging
import re
from pathlib import Path

import httpx
from sqlalchemy.ext.asyncio import async_sessionmaker

from qualcoder_api.core.models import MetaHit
from qualcoder_api.persistence.repo.meta_repo import MetaRepository

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; QCnextMeta/1.0; +https://github.com/ccsb-scripps/QualCoder)"
}
HTTP_TIMEOUT = 45
ZOTERO_API = "http://localhost:23119"


def _is_pdf(content_type: str, chunk: bytes) -> bool:
    ctype = (content_type or "").lower()
    if "application/pdf" in ctype or ctype.endswith("pdf"):
        return True
    return chunk[:5] == b"%PDF-"


# ── resolvers ────────────────────────────────────────────────────────────

async def resolve_openalex(client: httpx.AsyncClient, doi: str) -> str | None:
    """Direct PDF URL from OpenAlex ``best_oa_location``."""
    try:
        resp = await client.get(f"https://api.openalex.org/works/doi:{doi}")
        if resp.status_code != 200:
            return None
        work = resp.json()
        for loc in (work.get("best_oa_location"), work.get("primary_location")):
            if loc and loc.get("pdf_url"):
                return loc["pdf_url"]
    except httpx.HTTPError:
        return None
    return None


async def resolve_unpaywall(client: httpx.AsyncClient, doi: str, email: str) -> str | None:
    """Direct PDF URL from Unpaywall ``best_oa_location``."""
    if not email:
        return None
    try:
        resp = await client.get(f"https://api.unpaywall.org/v2/{doi}?email={email}")
        if resp.status_code != 200:
            return None
        best = resp.json().get("best_oa_location") or {}
        return best.get("url_for_pdf") or best.get("url")
    except httpx.HTTPError:
        return None
    return None


async def resolve_crossref(client: httpx.AsyncClient, doi: str) -> dict | None:
    """Metadata (title/authors/year) + landing URL from Crossref."""
    try:
        resp = await client.get(f"https://api.crossref.org/works/{doi}")
        if resp.status_code != 200:
            return None
        msg = resp.json().get("message") or {}
        authors = msg.get("author") or []
        surname = ""
        if authors and "family" in authors[0]:
            surname = str(authors[0].get("family") or "")
        year = None
        for key in ("published-print", "published-online", "issued"):
            parts = msg.get(key, {}).get("date-parts", [[None]])
            if parts and parts[0] and parts[0][0]:
                year = parts[0][0]
                break
        return {
            "surname": surname,
            "year": year,
            "title": (msg.get("title") or [""])[0],
            "url": (msg.get("URL") or "") or (f"https://doi.org/{doi}" if doi else ""),
        }
    except httpx.HTTPError:
        return None
    return None


async def resolve_landing_page(client: httpx.AsyncClient, url: str) -> str | None:
    """Find a PDF link on a landing page (citation meta or PDF anchors)."""
    if not url:
        return None
    try:
        resp = await client.get(url, follow_redirects=True, headers=HEADERS)
    except httpx.HTTPError:
        return None
    if resp.status_code != 200:
        return None
    html = resp.text[:2_000_000]
    m = re.search(r'<meta[^>]+name=["\']citation_pdf_url["\'][^>]+content=["\']([^"\']+)', html, re.I)
    if m:
        return m.group(1)
    # Also accept attribute order variants.
    m = re.search(r'<meta[^>]+content=["\']([^"\']+\.pdf[^"\']*)["\'][^>]+name=["\']citation_pdf_url["\']', html, re.I)
    if m:
        return m.group(1)
    for match in re.finditer(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>', html, re.I):
        href = match.group(1)
        if href.lower().endswith(".pdf") or ".pdf?" in href.lower():
            return href if href.startswith("http") else f"{resp.url}{href}"
    return None


async def download_pdf(client: httpx.AsyncClient, url: str, dest: Path) -> bool:
    """Download ``url`` into ``dest`` if it looks like a PDF; True on success."""
    try:
        async with client.stream("GET", url, follow_redirects=True, headers=HEADERS) as resp:
            if resp.status_code != 200:
                return False
            content_type = resp.headers.get("content-type", "")
            first: bytes = b""
            out: list[bytes] = []
            async for chunk in resp.aiter_bytes():
                if len(first) < 5:
                    first += chunk
                    first = first[:5]
                out.append(chunk)
            if not _is_pdf(content_type, first):
                return False
            dest.write_bytes(b"".join(out))
            return True
    except httpx.HTTPError:
        return False


# ── Zotero reuse (best-effort) ───────────────────────────────────────────

def _zotero_doi(value: object) -> str:
    return str(value or "").strip().lower().replace("https://doi.org/", "").replace("http://doi.org/", "")


async def try_zotero_pdf(client: httpx.AsyncClient, doi: str, dest: Path) -> tuple[bool, str]:
    """Look up the DOI in the running local Zotero and try to grab its PDF.

    Best-effort: Zotero 7 serves item metadata over ``localhost:23119``; the
    file endpoint needs the web API key when the local API restricts file
    access, so a 403 simply falls through to manual assignment. Returns
    (ok, method_hint).
    """
    target_doi = _zotero_doi(doi)
    try:
        resp = await client.get(
            f"{ZOTERO_API}/api/users/0/items?format=json&limit=500", timeout=10
        )
        if resp.status_code != 200:
            return False, "zotero_api_unreachable"
        items = resp.json()
        target_key = None
        for item in items:
            data = item.get("data") or {}
            if _zotero_doi(data.get("DOI")) == target_doi:
                target_key = item.get("key")
                break
        if target_key is None:
            return False, "zotero_doi_not_found"

        # Attachments are children of the parent item; the local API also
        # returns them inline in the item list (match on parentItem). Fall
        # back to the dedicated children endpoint when the list was paged.
        children = [
            it for it in items if (it.get("data") or {}).get("parentItem") == target_key
        ]
        if not children:
            try:
                child_resp = await client.get(
                    f"{ZOTERO_API}/api/users/0/items/{target_key}/children?format=json",
                    timeout=10,
                )
                if child_resp.status_code == 200:
                    children = child_resp.json()
            except httpx.HTTPError:
                pass

        for item in children:
            data = item.get("data") or {}
            if data.get("itemType") != "attachment":
                continue
            key = item.get("key")
            content_type = str(data.get("contentType") or "").lower()
            if not key or ("pdf" not in content_type and content_type not in ("", "application/octet-stream")):
                continue
            file_resp = await client.get(
                f"{ZOTERO_API}/api/users/0/items/{key}/file", timeout=30
            )
            if file_resp.status_code == 200 and _is_pdf(
                file_resp.headers.get("content-type", ""), file_resp.content[:5]
            ):
                dest.write_bytes(file_resp.content)
                return True, "zotero"
    except (httpx.HTTPError, ValueError):
        return False, "zotero_error"
    return False, "zotero_no_pdf"


# ── per-hit pipeline ─────────────────────────────────────────────────────

async def resolve_pdf_chain(
    client: httpx.AsyncClient, doi: str, email: str
) -> tuple[str | None, str | None, dict | None]:
    """Try OpenAlex → Unpaywall → Crossref landing page. Returns
    (pdf_url, method, metadata)."""
    metadata = await resolve_crossref(client, doi)
    landing = (metadata or {}).get("url")
    pdf_url = await resolve_openalex(client, doi)
    if pdf_url:
        return pdf_url, "openalex", metadata
    pdf_url = await resolve_unpaywall(client, doi, email)
    if pdf_url:
        return pdf_url, "unpaywall", metadata
    pdf_url = await resolve_landing_page(client, landing or f"https://doi.org/{doi}")
    if pdf_url:
        return pdf_url, "landing", metadata
    return None, None, metadata


def _sanitize(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "", name) or "Unknown"


def build_target_filename(hit: MetaHit, metadata: dict | None) -> str:
    """[Author][Year].pdf style filename from Crossref metadata or DOI."""
    if metadata and metadata.get("surname") and metadata.get("year"):
        base = f"{_sanitize(str(metadata['surname']))}{metadata['year']}"
    elif hit.doi:
        base = _sanitize(str(hit.doi).replace("/", "_").replace(":", "_"))
    else:
        base = _sanitize(str(hit.title or "untitled")[:40])
    return f"{base}.pdf"


async def run_downloads(
    session_factory: async_sessionmaker,
    *,
    project_path: str,
    hit_ids: list[int] | None,
    owner: str,
    email: str = "",
    progress_cb=None,
    should_stop=None,
) -> dict:
    """Run the automatic retrieval chain over included hits.

    For each hit: resolve → download → import as a QCnext source → link via
    ``meta_document``. Hits the chain cannot fetch stay ``failed`` and are
    left for manual assignment. Returns a summary dict.
    """
    progress_cb = progress_cb or (lambda done, total, msg="": None)
    should_stop = should_stop or (lambda: False)

    from qualcoder_api.services.import_service import ImportService

    from .meta_eligibility import eligible_hit_ids

    timeout = httpx.Timeout(HTTP_TIMEOUT)
    async with httpx.AsyncClient(timeout=timeout, headers=HEADERS) as client:  # noqa: SIM117 - lifetimes overlap
        async with session_factory() as session:
            repo = MetaRepository(session)
            if hit_ids:
                hits = [h for h in [await repo.get_hit(hid) for hid in hit_ids] if h is not None]
            else:
                # Whole-queue mode: only included hits (all criteria Yes).
                all_hits = await repo.list_hits()
                eligible = await eligible_hit_ids(session, all_hits)
                hits = [h for h in all_hits if h.hit_id in eligible]

            total = len(hits)
            done = 0
            ok = 0
            failed = 0
            stopped = False

            for hit in hits:
                if should_stop():
                    stopped = True
                    break
                doc = await repo.get_document_for_hit(hit.hit_id)
                if doc is not None and doc.status == "done":
                    done += 1
                    ok += 1
                    continue

                doi = (hit.doi or "").strip()
                await repo.upsert_document(
                    hit_id=hit.hit_id, status="working", message="resolving..."
                )
                if not doi:
                    await repo.patch_document_status(
                        hit.hit_id, "failed", "no DOI — assign a PDF manually"
                    )
                    failed += 1
                    done += 1
                    progress_cb(done, total, hit.title)
                    continue

                pdf_url, method, metadata = await resolve_pdf_chain(client, doi, email)
                target = Path(project_path) / ".meta" / "downloads"
                target.mkdir(parents=True, exist_ok=True)
                dest = target / build_target_filename(hit, metadata)
                dest.unlink(missing_ok=True)

                downloaded = False
                if pdf_url:
                    downloaded = await download_pdf(client, pdf_url, dest)
                    if not downloaded:
                        pdf_url = None
                if not pdf_url or not downloaded:
                    # Zotero reuse (best-effort).
                    zotero_ok, _ = await try_zotero_pdf(client, doi, dest)
                    if zotero_ok:
                        method = "zotero"
                        downloaded = True

                if downloaded and dest.exists() and dest.stat().st_size > 0:
                    importer = ImportService(project_path, session_factory)
                    filename = f"meta_{hit.hit_id}_{dest.name}"
                    source = await importer.import_file(str(dest), owner=owner, filename=filename)
                    if source is None:
                        await repo.patch_document_status(
                            hit.hit_id,
                            "failed",
                            "retrieved but import failed (duplicate name) — assign manually",
                        )
                        failed += 1
                    else:
                        await repo.upsert_document(
                            hit_id=hit.hit_id,
                            source_id=source.id,
                            retrieval_method=method,
                            url=pdf_url or f"https://doi.org/{doi}",
                            status="done",
                            message=f"retrieved via {method}",
                        )
                        await repo.set_hit_status(hit.hit_id, "downloaded")
                        await _link_study_case(session, hit=hit, source_id=source.id, owner=owner)
                        ok += 1
                else:
                    await repo.patch_document_status(
                        hit.hit_id, "failed", "automated retrieval failed — assign manually"
                    )
                    failed += 1
                done += 1
                progress_cb(done, total, hit.title)
                if dest.exists():
                    with contextlib.suppress(OSError):
                        dest.unlink()

    return {"total": total, "done": done, "ok": ok, "failed": failed, "stopped": stopped}


async def _link_study_case(session, *, hit: MetaHit, source_id: int, owner: str) -> None:
    """Merge a downloaded paper into its study's QCnext case.

    One Case per study, with the acquired source linked as a child
    (``case_text``) — the hybrid model: the meta tables stay the pipeline
    source of truth while the case links the fulltext into the project's
    Cases view / attributes. Idempotent (name match + link check).
    """
    from qualcoder_api.persistence.repo.case_repo import CaseRepository

    repo = CaseRepository(session)
    name = (hit.title or f"Study {hit.hit_id}").strip()[:120] or f"Study {hit.hit_id}"
    case = next((c for c in await repo.list_cases() if c.name == name), None)
    if case is None:
        case = await repo.add_case(name=name, owner=owner, memo="")
    if case is None:
        return
    linked = {row["id"] for row in await repo.case_files(case.caseid)}
    if source_id not in linked:
        await repo.link_file(caseid=case.caseid, fid=source_id, owner=owner)
