"""AI feature gate API — status, settings, chat, semantic search, prompts,
persistent index, MCP endpoint."""

from __future__ import annotations

import re

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
    # auto derives the mode from the picker selections (codes → code_analysis,
    # memos → memo_analysis, sources → text_analysis, several kinds →
    # topic_exploration, none → general); an explicit mode is honored as-is.
    mode: str = "auto"
    prompt_id: str | None = None
    memo_ids: list[int] | None = None
    # text_analysis: the source currently open in the coder, so the chat
    # can share its fulltext instead of the generic project summary.
    source_id: int | None = None
    # code_analysis / topic_exploration: focus the code block (memo, coding
    # counts, example segments) on these codes.
    code_ids: list[int] | None = None
    # text_analysis / topic_exploration: share the fulltext of these
    # sources (the files context picker).
    source_ids: list[int] | None = None
    # Session id: when given, the exchange is appended to that chat; when
    # None, a new chat session is created for the turn.
    chat_id: int | None = None


class ChatCreateRequest(BaseModel):
    title: str = ""


class ChatRenameRequest(BaseModel):
    title: str


class TemplateRequest(BaseModel):
    name: str
    description: str = ""
    text: str = ""


class SearchRequest(BaseModel):
    query: str
    limit: int = 10
    # Optional filter: restrict the semantic search to these text sources.
    source_ids: list[int] | None = None


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


# Friendly display names for the cloud providers (used in error messages).
_PROVIDER_LABELS = {"gemini": "Gemini", "gpt": "OpenAI", "claude": "Anthropic"}


def _provider_label(provider: str) -> str:
    return _PROVIDER_LABELS.get(provider, provider)


# Local models that are NOT usable as a chat model: embedding (bge /
# nomic-embed / *-embed*), speech (whisper / tts / speech) and vision-only
# (llava, bakllava, moondream, minicpm-v, *-vl, *-vision) families. Coder
# models (qwen2.5-coder, ...) carry none of these markers and stay — they are
# fully chat-capable. Best-effort heuristic: a falsely-dropped model can
# still be chosen by typing its name manually (or via "custom").
_LOCAL_NON_CHAT = re.compile(
    r"(embed|bge|nomic-embed|whisper|speech|tts|llava|bakllava|moondream|"
    r"minicpm-v|-vl(?:[-0-9:]|$)|vision|multimodal)",
    re.IGNORECASE,
)


# LM Studio serves quant suffixes ("llama-3.1-8b-instruct:q4_k_m" /
# "@q4_k_m"); collapse variants of the same base model to the bare name.
_LMSTUDIO_QUANT = re.compile(
    r"[:@](?:q\d+[a-z0-9_]*|(?:b|f|fp|bf)16|int\d+)$", re.IGNORECASE
)


def _ollama_base_and_tag(model_id: str) -> tuple[str, str]:
    """Split an Ollama tag id ("llama3.2:3b") into base name and tag."""
    if ":" in model_id:
        base, _, tag = model_id.partition(":")
        return base, tag
    return model_id, ""


def _better_ollama_variant(a: str, b: str) -> bool:
    """True when variant ``a`` wins over ``b`` for the same base name:
    bare name > ``:latest`` > shortest tag."""
    _, ta = _ollama_base_and_tag(a)
    _, tb = _ollama_base_and_tag(b)
    if ta == tb:
        return False
    if not ta or (ta == "latest" and tb):
        return True
    if not tb or (tb == "latest" and ta):
        return False
    return len(ta) < len(tb)


def _dedupe_local_models(ids: list[str], provider: str) -> list[str]:
    """Collapse tag variants of the same base model to one entry.

    Ollama tags ("llama3.2:latest", "llama3.2:3b") collapse to the preferred
    variant (bare name > ``:latest`` > shortest tag). LM Studio quant
    suffixes ("llama-3.1-8b-instruct:q4_k_m") collapse to the bare base name.
    """
    best: dict[str, str] = {}
    for model_id in ids:
        if provider == "ollama":
            base, _ = _ollama_base_and_tag(model_id)
            if base not in best or _better_ollama_variant(model_id, best[base]):
                best[base] = model_id
        elif provider == "lmstudio":
            base = _LMSTUDIO_QUANT.sub("", model_id)
            best.setdefault(base, base)
        else:
            best.setdefault(model_id, model_id)
    return sorted(best.values())


def _sanitize_error(detail: str) -> str:
    """Trim an exception message and redact anything key-like.

    httpx exceptions carry the request URL, and the Gemini ``?key=``
    fallback puts the API key in the query string — never echo it back.
    """
    import re

    detail = detail.strip()
    detail = re.sub(r"([?&]key=)[^&\s\"']*", r"\1***", detail)
    detail = re.sub(r"\bAIza[0-9A-Za-z_-]+", "AIza***", detail)
    detail = re.sub(r"\bsk-[0-9A-Za-z_-]+", "sk-***", detail)
    return detail[:300]


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
    answer quickly; cloud providers need an API key — a missing key returns a
    friendly ``error`` detail, and failures return an empty list plus a
    sanitized ``error`` (the last exception, key-redacted; 401/403 map to a
    "rejected the API key" message).

    Query params (``provider``/``api_base``/``api_key``), when provided,
    override the saved settings for this fetch only — they are never saved.
    An empty-string api_key is treated the same as None.

    The list is FILTERED per provider: chat models only, newest generations —
    Gemini/GPT video, TTS, embedding and image models are dropped — and
    deduplicated (Ollama/LM Studio tag variants collapse to one entry; local
    embedding/speech/vision-only models are dropped too).
    """
    import httpx

    ai = user_settings.get_ai_settings()
    provider = provider or ai.get("provider", "custom")
    api_base = (api_base or ai.get("api_base") or "").rstrip("/")
    if not api_base:
        return {"models": []}
    api_key = api_key or ai.get("api_key") or ""
    if _provider_requires_key(provider) and not api_key.strip():
        return {
            "models": [],
            "error": (
                f"{_provider_label(provider)} requires a valid API key before its "
                "models can be listed — enter your API key in Settings."
            ),
        }
    data: dict | None = None
    last_error = ""
    for url, req_headers in _models_urls(provider, api_base, api_key):
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(url, headers=req_headers)
                resp.raise_for_status()
                data = resp.json()
            break
        except httpx.HTTPStatusError as err:
            code = err.response.status_code
            if code in (401, 403):
                # The key is rejected — the fallback URLs carry the same
                # key, so report it and stop.
                last_error = (
                    f"{_provider_label(provider)} rejected the API key ({code}) "
                    "— check the key in Settings."
                )
                break
            last_error = str(err)
        except Exception as err:
            last_error = str(err)
    if data is None:
        return {
            "models": [],
            "error": _sanitize_error(last_error) or "all model endpoints failed",
        }
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
    elif provider in ("ollama", "lmstudio", "opencode-go"):
        # Local providers: embedding / speech / vision-only models are not
        # chat candidates — see _LOCAL_NON_CHAT for the documented rules.
        keep = re.compile(r".+")
        drop = _LOCAL_NON_CHAT
    else:
        # Custom providers: everything they advertise is a candidate.
        keep = re.compile(r".+")
        drop = None

    models = [
        m for m in ids if keep.match(m) and not (drop is not None and drop.search(m))
    ]
    if provider in ("ollama", "lmstudio"):
        models = _dedupe_local_models(models, provider)
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
            last_error = _sanitize_error(str(err))
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
    import json

    from qualcoder_api.services import ai_history
    from qualcoder_api.services.ai_service import derive_mode

    ai = user_settings.get_ai_settings()
    chat_id = req.chat_id
    try:
        if chat_id is None:
            chat = await ai_history.create_chat(session)
            chat_id = chat["id"]
        else:
            existing = await ai_history.get_chat(session, chat_id)
            if existing is None:
                raise HTTPException(status_code=404, detail="chat session not found")
        envelope = json.dumps(
            {
                "mode": req.mode,
                "mode_derived": derive_mode(
                    req.mode, req.memo_ids, req.code_ids, req.source_ids, req.source_id
                ),
                "prompt_id": req.prompt_id,
                "memo_ids": req.memo_ids,
                "code_ids": req.code_ids,
                "source_ids": req.source_ids,
            },
            ensure_ascii=False,
        )
        await ai_history.append_message(
            session, chat_id, "user", req.message, request_json=envelope
        )
        result = await AiService(svc.session_factory).chat(
            ai, req.message, req.context, mode=req.mode, prompt_id=req.prompt_id,
            memo_ids=req.memo_ids, source_id=req.source_id,
            code_ids=req.code_ids, source_ids=req.source_ids,
        )
    except AiUnavailable as err:
        raise HTTPException(status_code=503, detail=str(err)) from err
    await ai_history.append_message(session, chat_id, "assistant", result["reply"])
    await ai_history.ensure_title(session, chat_id, req.message)
    return {
        "chat_id": chat_id,
        "reply": result["reply"],
        "model": result["model"],
    }


@router.get("/chats")
async def ai_chats(session: DbDep) -> dict:
    """Saved AI chat sessions (most recently updated first)."""
    from qualcoder_api.services import ai_history

    return {"chats": await ai_history.list_chats(session)}


@router.post("/chats", status_code=201)
async def ai_chat_create(req: ChatCreateRequest, session: DbDep) -> dict:
    from qualcoder_api.services import ai_history

    return await ai_history.create_chat(session, req.title)


@router.get("/chats/{chat_id}")
async def ai_chat_get(chat_id: int, session: DbDep) -> dict:
    from qualcoder_api.services import ai_history

    chat = await ai_history.get_chat(session, chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="chat session not found")
    return chat


@router.patch("/chats/{chat_id}")
async def ai_chat_rename(chat_id: int, req: ChatRenameRequest, session: DbDep) -> dict:
    from qualcoder_api.services import ai_history

    if not req.title.strip():
        raise HTTPException(status_code=422, detail="title is empty")
    if not await ai_history.rename_chat(session, chat_id, req.title):
        raise HTTPException(status_code=404, detail="chat session not found")
    return {"id": chat_id, "title": req.title.strip()}


@router.delete("/chats/{chat_id}", status_code=204)
async def ai_chat_delete(chat_id: int, session: DbDep) -> None:
    from qualcoder_api.services import ai_history

    if not await ai_history.delete_chat(session, chat_id):
        raise HTTPException(status_code=404, detail="chat session not found")


@router.get("/prompts")
async def ai_prompts(svc: ServiceDep, session: DbDep) -> dict:
    """The merged prompt catalog: built-in library + user templates."""
    from qualcoder_api.services import ai_templates

    return {"prompts": await ai_templates.list_catalog(session)}


@router.get("/templates")
async def ai_templates_list(session: DbDep) -> dict:
    """User-defined instruction templates (with full bodies for editing)."""
    from qualcoder_api.services import ai_templates

    return {"templates": await ai_templates.list_templates(session)}


@router.post("/templates", status_code=201)
async def ai_templates_create(req: TemplateRequest, session: DbDep) -> dict:
    from qualcoder_api.services import ai_templates

    if not req.name.strip() or not req.text.strip():
        raise HTTPException(status_code=422, detail="name and text are required")
    return await ai_templates.create_template(session, req.name, req.description, req.text)


@router.put("/templates/{template_id}")
async def ai_templates_update(template_id: int, req: TemplateRequest, session: DbDep) -> dict:
    from qualcoder_api.services import ai_templates

    if not req.name.strip() or not req.text.strip():
        raise HTTPException(status_code=422, detail="name and text are required")
    updated = await ai_templates.update_template(
        session, template_id, name=req.name, description=req.description, text=req.text
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="template not found")
    return updated


@router.delete("/templates/{template_id}", status_code=204)
async def ai_templates_delete(template_id: int, session: DbDep) -> None:
    from qualcoder_api.services import ai_templates

    if not await ai_templates.delete_template(session, template_id):
        raise HTTPException(status_code=404, detail="template not found")


@router.post("/search")
async def ai_search(req: SearchRequest, svc: ServiceDep, session: DbDep) -> dict:
    ai = user_settings.get_ai_settings()
    try:
        return await AiService(svc.session_factory).semantic_search(
            ai, req.query, req.limit, source_ids=req.source_ids
        )
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
