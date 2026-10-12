"""Meta-analysis paper download — native OA candidate resolver + Zotero reuse.

Zotero has no public machine API to "find a PDF for a DOI" — its retrieval is
internal (an Unpaywall data mirror plus custom resolver prefs run inside the
client). This module therefore reimplements the resolver semantics natively,
adapted from the reference ``Inoculation_Meta`` acquisition scripts but async
and Selenium-free: it builds an ordered candidate list from OpenAlex, Unpaywall,
Europe PMC, the Crossref landing page and finally the DOI resolver, preferring
repository/OA mirrors over publisher PDFs, and attempts each until a PDF is
retrieved. Anything the chain misses falls back to a running local Zotero
(localhost:23119) and then to manual assignment in the UI.
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
#: Offered on every download so publishers that gate on the Accept header still
#: serve the PDF (an HTML landing page is rejected by the magic-byte check).
DOWNLOAD_ACCEPT = "application/pdf,application/octet-stream,*/*"
HTTP_TIMEOUT = 45
ZOTERO_API = "http://localhost:23119"
EUROPEPMC_SEARCH = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
#: Hard ceiling for a downloaded paper. A paywalled/redirected response can be
#: arbitrarily large (HTML, media); buffering it whole would exhaust memory.
MAX_PDF_BYTES = 40 * 1024 * 1024


def _is_pdf(content_type: str, chunk: bytes) -> bool:
    ctype = (content_type or "").lower()
    if "application/pdf" in ctype or ctype.endswith("pdf"):
        return True
    return chunk[:5] == b"%PDF-"


# ── resolvers ────────────────────────────────────────────────────────────

def _note_unpaywall_email(info: dict | None, reason: str) -> None:
    """Record that Unpaywall could not be queried for want of a valid email.

    A placeholder/invalid email makes Unpaywall answer HTTP 422 (not 200 with
    an empty body), so the caller surfaces it once as an actionable hint
    instead of silently discarding the source.
    """
    if info is None or info.get("unpaywall_email"):
        return
    logger.info("Unpaywall email unavailable (%s) — add one for more OA sources", reason)
    info["unpaywall_email"] = True


async def _openalex_candidates(
    client: httpx.AsyncClient, doi: str, found: list[dict]
) -> None:
    """Candidate PDFs from every OpenAlex location (each location's PDF or a
    landing-page PDF), carrying the source type so repositories sort first."""
    try:
        resp = await client.get(f"https://api.openalex.org/works/doi:{doi}")
    except httpx.HTTPError:
        return
    if resp.status_code != 200:
        return
    try:
        work = resp.json()
    except ValueError:
        return
    locations = work.get("locations")
    if not isinstance(locations, list):
        locations = []
    # ``best_oa_location`` is a reference to one of ``locations`` on recent
    # records, but older payloads may not echo it — include it defensively.
    best = work.get("best_oa_location")
    if isinstance(best, dict) and best not in locations:
        locations = [*locations, best]
    for loc in locations:
        if not isinstance(loc, dict):
            continue
        source = loc.get("source")
        host_type = str(source.get("type") or "") if isinstance(source, dict) else ""
        pdf_url = loc.get("pdf_url")
        landing = loc.get("landing_page_url")
        if pdf_url:
            found.append({"url": pdf_url, "method": "openalex", "host_type": host_type})
        elif landing and (loc.get("is_oa") or host_type == "repository"):
            resolved = await resolve_landing_page(client, str(landing))
            if resolved:
                found.append(
                    {"url": resolved, "method": "openalex-landing", "host_type": host_type}
                )


async def _unpaywall_candidates(
    client: httpx.AsyncClient, doi: str, email: str, info: dict | None, found: list[dict]
) -> None:
    """Candidate PDFs from every Unpaywall ``oa_locations`` entry."""
    if not email:
        _note_unpaywall_email(info, "no email configured")
        return
    try:
        resp = await client.get(f"https://api.unpaywall.org/v2/{doi}?email={email}")
    except httpx.HTTPError:
        return
    if resp.status_code != 200:
        if resp.status_code == 422:
            _note_unpaywall_email(info, "email rejected (HTTP 422)")
        return
    try:
        data = resp.json()
    except ValueError:
        return
    locations = data.get("oa_locations")
    if not isinstance(locations, list) or not locations:
        best = data.get("best_oa_location")
        locations = [best] if isinstance(best, dict) else []
    for loc in locations:
        if not isinstance(loc, dict):
            continue
        url = loc.get("url_for_pdf") or loc.get("url")
        if not url:
            continue
        found.append(
            {
                "url": url,
                "method": "unpaywall",
                "host_type": str(loc.get("host_type") or ""),
            }
        )


async def _europepmc_candidates(
    client: httpx.AsyncClient, doi: str, found: list[dict]
) -> None:
    """Europe PMC's rendered-PDF link for the DOI's PMCID, when one exists."""
    url = f'{EUROPEPMC_SEARCH}?query=DOI:"{doi}"&format=json'
    try:
        resp = await client.get(url)
    except httpx.HTTPError:
        return
    if resp.status_code != 200:
        return
    try:
        data = resp.json()
    except ValueError:
        return
    results = (data.get("resultList") or {}).get("result")
    if not isinstance(results, list):
        return
    for item in results:
        if not isinstance(item, dict):
            continue
        pmcid = item.get("pmcid")
        if pmcid:
            found.append(
                {
                    "url": f"https://europepmc.org/articles/{pmcid}?pdf=render",
                    "method": "europepmc",
                    "host_type": "repository",
                }
            )
            return


def _crossref_candidates(metadata: dict | None, doi: str, found: list[dict]) -> None:
    """Crossref registration landing URL, then the bare DOI resolver."""
    landing = (metadata or {}).get("url")
    if landing:
        found.append(
            {"url": landing, "method": "crossref-landing", "host_type": "publisher"}
        )
    if doi:
        found.append({"url": f"https://doi.org/{doi}", "method": "resolver", "host_type": ""})


def _candidate_rank(candidate: dict) -> int:
    """Sort key: repository OA mirrors, then other OA PDFs, then landing URLs."""
    if candidate.get("host_type") == "repository":
        return 0
    method = candidate.get("method")
    if method == "crossref-landing":
        return 2
    if method == "resolver":
        return 3
    return 1


async def resolve_candidates(
    client: httpx.AsyncClient, doi: str, email: str, *, info: dict | None = None
) -> list[dict]:
    """Ordered, unique download candidates for ``doi``.

    Sources are queried OpenAlex → Unpaywall → Europe PMC → Crossref → DOI
    resolver, then stable-sorted so repository/OA mirrors precede publisher
    PDFs and landing/resolver URLs. Each candidate is
    ``{"url", "method", "host_type"}``.

    ``info`` is an optional out-dict the caller may pass to learn why a source
    contributed nothing (currently ``unpaywall_email`` and ``crossref``).
    """
    found: list[dict] = []
    await _openalex_candidates(client, doi, found)
    await _unpaywall_candidates(client, doi, email, info, found)
    await _europepmc_candidates(client, doi, found)
    metadata = await resolve_crossref(client, doi)
    _crossref_candidates(metadata, doi, found)
    if info is not None:
        info["crossref"] = metadata

    ordered: list[dict] = []
    seen: set[str] = set()
    for candidate in sorted(found, key=_candidate_rank):
        url = str(candidate.get("url") or "")
        if not url or url in seen:
            continue
        seen.add(url)
        ordered.append(
            {
                "url": url,
                "method": str(candidate.get("method") or ""),
                "host_type": str(candidate.get("host_type") or ""),
            }
        )
    return ordered


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


async def download_pdf(
    client: httpx.AsyncClient, url: str, dest: Path, *, detail: dict | None = None
) -> bool:
    """Download ``url`` into ``dest`` if it looks like a PDF; True on success.

    The first five bytes are validated as soon as they are available (before
    the rest of the body is buffered) and the download is aborted past
    ``MAX_PDF_BYTES`` so a hostile or misdirected response cannot exhaust
    memory. When ``detail`` is passed it is filled with ``status`` /
    ``content_type`` / ``reason`` describing why a failed attempt was rejected.
    """
    def _fail(reason: str, status: int | None = None, content_type: str = "") -> bool:
        if detail is not None:
            if status is not None:
                detail["status"] = status
            if content_type:
                detail["content_type"] = content_type
            detail["reason"] = reason
        return False

    try:
        async with client.stream(
            "GET",
            url,
            follow_redirects=True,
            headers={**HEADERS, "Accept": DOWNLOAD_ACCEPT},
        ) as resp:
            if resp.status_code != 200:
                return _fail(f"HTTP {resp.status_code}", status=resp.status_code)
            content_type = resp.headers.get("content-type", "")
            first: bytes = b""
            total = 0
            out: list[bytes] = []
            async for chunk in resp.aiter_bytes():
                if not chunk:
                    continue
                if len(first) < 5:
                    first = (first + chunk)[:5]
                    # Validate immediately once the magic block is present.
                    if len(first) >= 5 and not _is_pdf(content_type, first):
                        return _fail("not a PDF response", status=200, content_type=content_type)
                total += len(chunk)
                if total > MAX_PDF_BYTES:
                    logger.warning("Download aborted (> %d bytes): %s", MAX_PDF_BYTES, url)
                    return _fail(
                        f"file too large (> {MAX_PDF_BYTES} bytes)",
                        status=200,
                        content_type=content_type,
                    )
                out.append(chunk)
            if not _is_pdf(content_type, first):
                return _fail("not a PDF response", status=200, content_type=content_type)
            dest.write_bytes(b"".join(out))
            return True
    except httpx.HTTPError as err:
        return _fail(f"request failed ({err.__class__.__name__})")


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
    """Backward-compatible wrapper: the first candidate's URL/method + metadata.

    Prefer :func:`resolve_candidates` when every fallback should be attempted.
    """
    info: dict = {}
    candidates = await resolve_candidates(client, doi, email, info=info)
    metadata = info.get("crossref")
    if not candidates:
        return None, None, metadata
    first = candidates[0]
    return first["url"], first["method"], metadata


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

                info: dict = {}
                candidates = await resolve_candidates(client, doi, email, info=info)
                metadata = info.get("crossref")
                target = Path(project_path) / ".meta" / "downloads"
                target.mkdir(parents=True, exist_ok=True)
                dest = target / build_target_filename(hit, metadata)
                dest.unlink(missing_ok=True)

                downloaded = False
                method: str | None = None
                pdf_url: str | None = None
                last_detail: dict = {}
                for candidate in candidates:
                    detail: dict = {}
                    if await download_pdf(client, candidate["url"], dest, detail=detail):
                        downloaded = True
                        method = candidate["method"]
                        pdf_url = candidate["url"]
                        break
                    if detail:
                        last_detail = detail
                if not downloaded:
                    # Zotero reuse (best-effort), tried only once every OA
                    # candidate has been exhausted.
                    zotero_ok, _ = await try_zotero_pdf(client, doi, dest)
                    if zotero_ok:
                        method = "zotero"
                        pdf_url = f"https://doi.org/{doi}"
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
                    if not candidates:
                        status = "unretrievable"
                        message = f"no open-access copy found (DOI {doi})"
                    else:
                        reason = str(last_detail.get("reason") or "unknown error")
                        status = "failed"
                        message = f"all {len(candidates)} sources blocked (last: {reason})"
                    if info.get("unpaywall_email"):
                        message = f"{message}; add an Unpaywall email to broaden retrieval"
                    await repo.patch_document_status(hit.hit_id, status, message)
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
