"""AI feature gate API — status, settings, chat, semantic search, prompts,
persistent index, MCP endpoint."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from qualcoder_api.api.v1.deps import DbDep, ServiceDep
from qualcoder_api.services import user_settings
from qualcoder_api.services.ai_service import AiService, AiUnavailable

router = APIRouter(prefix="/ai", tags=["ai"])


class AiSettingsRequest(BaseModel):
    enabled: bool
    provider: str = "custom"
    api_base: str
    model: str
    api_key: str = ""
    mcp_permissions: str = "read"


class ChatRequest(BaseModel):
    message: str
    context: str = ""
    mode: str = "general"  # general | help | topic_exploration | code_analysis | text_analysis | memo_analysis
    prompt_id: str | None = None
    memo_ids: list[int] | None = None


class SearchRequest(BaseModel):
    query: str
    limit: int = 10


class IndexRequest(BaseModel):
    rebuild: bool = False


def _provider_headers(provider: str, api_key: str) -> dict[str, str]:
    """Auth headers per provider for the /models list.

    Gemini's NATIVE REST endpoint authenticates with ``x-goog-api-key``;
    Claude requires ``x-api-key`` plus ``anthropic-version`` (Bearer is
    rejected with 401). GPT and OpenAI-compatible/local servers use
    ``Authorization: Bearer``; local providers need none.
    """
    if provider == "gemini" and api_key:
        return {"x-goog-api-key": api_key}
    if provider == "claude" and api_key:
        return {"x-api-key": api_key, "anthropic-version": "2023-06-01"}
    if api_key:
        return {"Authorization": f"Bearer {api_key}"}
    return {}


def _provider_requires_key(provider: str) -> bool:
    return provider in ("gemini", "gpt", "claude")


def _models_urls(
    provider: str, api_base: str, api_key: str = ""
) -> list[tuple[str, dict[str, str]]]:
    """Candidate (url, auth headers) pairs for the /models list.

    OpenAI-compatible servers serve the list at ``<base>/v1/models``
    (Ollama, LM Studio, opencode-go); when the base URL already ends in /v1
    use ``<base>/models``. GPT advertises it at ``<base>/models`` with /v1
    already in the base.

    Gemini's openai-compat shim does NOT reliably implement the /models
    route, so the list is fetched from the NATIVE REST endpoint
    ``<native>/v1beta/models`` instead — the configured base is usually
    ``https://generativelanguage.googleapis.com/v1beta/openai``, from which
    the native host is derived by stripping the ``/v1beta/openai`` (or
    ``/openai``) suffix (otherwise the base is used as-is). The key travels
    as the ``x-goog-api-key`` header; a ``?key=`` query variant is tried
    second, without an auth header. Claude's native list lives at
    ``<base>/models`` and needs ``x-api-key`` plus ``anthropic-version``
    (Bearer is rejected with 401).
    """
    from urllib.parse import quote

    headers = _provider_headers(provider, api_key)
    base = api_base.rstrip("/")
    if provider == "gemini" and api_key:
        native = base
        for suffix in ("/v1beta/openai", "/openai"):
            if base.endswith(suffix):
                native = base[: -len(suffix)]
                break
        url = f"{native}/v1beta/models"
        return [(url, headers), (f"{url}?key={quote(api_key)}", {})]
    if provider == "claude":
        return [(f"{base}/models", headers)]
    if base.endswith("/v1"):
        urls = [f"{base}/models", f"{base.rsplit('/v1', 1)[0]}/v1/models"]
    elif provider in ("ollama", "lmstudio", "opencode-go"):
        urls = [f"{base}/v1/models", f"{base}/models"]
    else:
        urls = [f"{base}/models"]
    return [(url, headers) for url in urls]


@router.get("/models")
async def ai_models(
    provider: str | None = Query(None),
    api_base: str | None = Query(None),
    api_key: str | None = Query(None),
) -> dict:
    """List the models the configured provider advertises (per-provider
    ``/models`` endpoints). Local providers (ollama/lmstudio/opencode-go)
    answer quickly; cloud providers need an API key, so failures return
    empty.

    Query params (``provider``/``api_base``/``api_key``), when provided,
    override the saved settings for this fetch only — they are never saved.
    An empty-string api_key is treated the same as None.

    The list is FILTERED per provider: chat models only, newest generations —
    Gemini/GPT video, TTS, embedding and image models are dropped — and
    deduplicated (Ollama/LM Studio tag variants collapse to one entry).
    """
    import re

    import httpx

    ai = user_settings.get_ai_settings()
    provider = provider or ai.get("provider", "custom")
    api_base = (api_base or ai.get("api_base") or "").rstrip("/")
    if not api_base:
        return {"models": []}
    api_key = api_key or ai.get("api_key") or ""
    if _provider_requires_key(provider) and not api_key.strip():
        return {"models": []}
    data: dict | None = None
    for url, req_headers in _models_urls(provider, api_base, api_key):
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(url, headers=req_headers)
                resp.raise_for_status()
                data = resp.json()
            break
        except Exception:
            continue
    if data is None:
        return {"models": []}
    if provider == "gemini":
        # Native REST shape: {"models": [{"name": "models/gemini-2.5-flash", ...}]}
        ids = sorted(
            m.get("name", "").removeprefix("models/")
            for m in data.get("models", [])
            if m.get("name")
        )
    else:
        # OpenAI-compatible shape: {"data": [{"id": "..."}]}
        ids = sorted(m.get("id") for m in data.get("data", []) if m.get("id"))

    if provider == "gemini":
        keep = re.compile(r"^gemini-[0-9]")
        drop = re.compile(
            r"(video|audio|tts|embedding|imagen|image|veo|live|exp|whisper|meet|nanoda|pali|music)"
        )
    elif provider == "gpt":
        keep = re.compile(r"^gpt-(4|5|o[34])")
        drop = re.compile(r"(audio|video|tts|embedding|realtime|image|dall|speech|gpt-4\.5-can|vega)")
    elif provider == "claude":
        keep = re.compile(r"^claude-(sonnet|opus|haiku)")
        drop = re.compile(r"(aws|bedrock|agent|vertex)")
    else:
        # Local / custom providers: everything they advertise is a candidate.
        keep = re.compile(r".+")
        drop = None

    seen: set[str] = set()
    models: list[str] = []
    for m in ids:
        if not keep.match(m) or (drop is not None and drop.search(m)):
            continue
        # Ollama/LM Studio serve tags ("llama3.2:latest"); collapse variants
        # to the base name so the dropdown shows each model once.
        base = m.split(":")[0] if provider in ("ollama", "lmstudio") else m
        if base not in seen:
            seen.add(base)
            models.append(base)
    return {"models": sorted(models)}


async def _probe_provider(ai: dict) -> tuple[bool | None, str]:
    """Live reachability check of the configured provider's /v1/models.

    This exercises a real provider endpoint (the models list), so it also
    validates the API key when one is needed — Gemini is probed against its
    native ``/v1beta/models`` endpoint, with the ``?key=`` fallback.
    """
    import httpx

    provider = ai.get("provider", "custom")
    api_base = (ai.get("api_base") or "").rstrip("/")
    if not api_base:
        return None, "no api base configured"
    api_key = ai.get("api_key") or ""
    if _provider_requires_key(provider) and not api_key.strip():
        return False, "API key required for this provider"
    for url, headers in _models_urls(provider, api_base, api_key):
        try:
            async with httpx.AsyncClient(timeout=2.5) as client:
                resp = await client.get(url, headers=headers)
                resp.raise_for_status()
            return True, ""
        except Exception as err:
            last_error = str(err)
    return False, last_error


@router.get("/status")
async def ai_status(probe: bool = False) -> dict:
    ai = user_settings.get_ai_settings()
    configured, reason = AiService.is_configured(ai)
    api_base = ai.get("api_base") or ""
    out = {
        "enabled": ai["enabled"],
        "configured": configured,
        "reason": reason,
        "provider": ai.get("provider", "custom"),
        "base_url": api_base,
        "model": ai["model"],
        "mcp_permissions": ai.get("mcp_permissions", "read"),
        "reachable": None,
        "probe_error": "",
    }
    if probe:
        reachable, probe_error = await _probe_provider(ai)
        out["reachable"] = reachable
        out["probe_error"] = probe_error
    return out


@router.put("/settings")
async def save_ai_settings(req: AiSettingsRequest) -> dict:
    return user_settings.save_ai_settings(req.model_dump())


@router.post("/chat")
async def ai_chat(req: ChatRequest, svc: ServiceDep, session: DbDep) -> dict:
    ai = user_settings.get_ai_settings()
    try:
        return await AiService(svc.session_factory).chat(
            ai, req.message, req.context, mode=req.mode, prompt_id=req.prompt_id,
            memo_ids=req.memo_ids,
        )
    except AiUnavailable as err:
        raise HTTPException(status_code=503, detail=str(err)) from err


@router.get("/prompts")
async def ai_prompts() -> dict:
    """The prompt library (upstream ai_prompt_library catalog)."""
    from qualcoder_api.services.ai_prompts import CATALOG

    return {
        "prompts": [
            {
                "id": prompt.id,
                "mode": prompt.mode,
                "name": prompt.name,
                "description": prompt.description,
            }
            for prompt in CATALOG.prompts
        ]
    }


@router.post("/search")
async def ai_search(req: SearchRequest, svc: ServiceDep, session: DbDep) -> dict:
    ai = user_settings.get_ai_settings()
    try:
        return await AiService(svc.session_factory).semantic_search(ai, req.query, req.limit)
    except AiUnavailable as err:
        raise HTTPException(status_code=503, detail=str(err)) from err


@router.get("/index")
async def ai_index_status(svc: ServiceDep) -> dict:
    """Status of the persistent vector index (project-local sqlite)."""
    from qualcoder_api.services import ai_index

    if svc.project_path == "":
        raise HTTPException(status_code=409, detail="no project is open")
    return ai_index.index_status(svc.project_path)


@router.post("/index")
async def ai_index_build(req: IndexRequest, svc: ServiceDep) -> dict:
    """Build (or rebuild) the persistent embedding index."""
    from qualcoder_api.services import ai_index

    if svc.project_path == "" or svc.session_factory is None:
        raise HTTPException(status_code=409, detail="no project is open")
    ai = user_settings.get_ai_settings()
    try:
        return await ai_index.rebuild_index(svc.session_factory, svc.project_path, ai)
    except AiUnavailable as err:
        raise HTTPException(status_code=503, detail=str(err)) from err


@router.delete("/index", status_code=204)
async def ai_index_delete(svc: ServiceDep) -> None:
    """Delete the persistent embedding index."""
    from qualcoder_api.services import ai_index

    if svc.project_path == "":
        raise HTTPException(status_code=409, detail="no project is open")
    ai_index.delete_index(svc.project_path)


@router.post("/mcp")
async def ai_mcp(request: Request, svc: ServiceDep):
    """MCP (Model Context Protocol) JSON-RPC 2.0 endpoint.

    Accepts a single request or a batch. Write tools are gated by the
    ``mcp_permissions`` AI setting (read | write | full).
    """
    from qualcoder_api.services.mcp_service import McpService

    payload = await request.json()
    ai = user_settings.get_ai_settings()
    service = McpService(svc.session_factory, permissions=ai.get("mcp_permissions", "read"))
    if isinstance(payload, list):
        responses = []
        for item in payload:
            response = await service.handle(item)
            if response is not None:
                responses.append(response)
        return responses
    response = await service.handle(payload)
    if response is None:
        return {}
    return response
