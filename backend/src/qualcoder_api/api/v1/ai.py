"""AI feature gate API — status, settings, chat, semantic search, prompts,
persistent index, MCP endpoint."""

from __future__ import annotations

import re

from fastapi import APIRouter, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field

from qualcoder_api.api.v1.deps import DbDep, OpenProjectDep, ServiceDep
from qualcoder_api.services import user_settings
from qualcoder_api.services.ai_prompts import is_custom_prompt_id
from qualcoder_api.services.ai_service import AiService, AiUnavailable

router = APIRouter(prefix="/ai", tags=["ai"])


class AiSettingsRequest(BaseModel):
    enabled: bool
    provider: str = Field(default="custom", max_length=64)
    api_base: str = Field(default="", max_length=2048)
    model: str = Field(default="", max_length=256)
    api_key: str = Field(default="", max_length=4096)
    # Actively start LM Studio + load the model when unreachable. None =
    # keep the stored value.
    auto_start_backend: bool | None = None
    # Optional: when omitted the stored value is kept (the AI tab no longer
    # manages permissions — that moved to the AI sidebar via /mcp-permissions).
    mcp_permissions: str | None = None
    # The AI-chat wrapping prompt. None = keep the stored value (the settings
    # tab auto-save must not clobber a custom wrapping prompt set in the
    # template creator); an empty string resets to the built-in default.
    wrapping_prompt: str | None = Field(default=None, max_length=8000)
    # MCP mode: "internal" (QCnext's own tools) or "external" (stdio server).
    mcp_mode: str | None = None
    # External MCP server connection (stdio).
    mcp_server_command: str | None = Field(default=None, max_length=512)
    mcp_server_args: list[str] | None = None
    mcp_server_env: dict[str, str] | None = None


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
    # Agentic chat: give the model the project's MCP tools and loop on its
    # tool calls (read tools always; write tools gated by mcp_permissions).
    agentic: bool = False
    # When agentic: pause before executing write tools and ask the user.
    confirm_writes: bool = False


class ChatApproveRequest(BaseModel):
    """User decision for a paused (agentic) chat turn's pending write tools."""
    token: str
    approve: bool
    chat_id: int | None = None


class ChatCreateRequest(BaseModel):
    title: str = ""


class ChatRenameRequest(BaseModel):
    title: str


class TemplateRequest(BaseModel):
    name: str
    description: str = ""
    text: str = ""


class PersonasRequest(BaseModel):
    """Per-mode persona overrides (mode -> custom system prompt; blank clears)."""
    personas: dict[str, str] = {}


class EditorTemplateRequest(BaseModel):
    """Save an editable template by its picker id (built-in / global: / custom:)."""
    id: str
    name: str = ""
    description: str = ""
    text: str = ""


class ResetTemplateRequest(BaseModel):
    """Restore a built-in template to its shipped text."""
    id: str


class SearchRequest(BaseModel):
    query: str
    limit: int = 10
    # Optional filter: restrict the semantic search to these text sources.
    source_ids: list[int] | None = None
    # Optional filter: restrict the semantic search to sources coded under
    # this category subtree.
    category_id: int | None = None


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
    provider: str | None = Query(None, max_length=64),
    api_base: str | None = Query(None, max_length=2048),
    api_key: str | None = Query(None, max_length=4096, include_in_schema=False),
    x_api_key: str | None = Header(None, alias="X-Api-Key"),
) -> dict:
    """List the models the configured provider advertises (per-provider
    ``/models`` endpoints). Local providers (ollama/lmstudio/opencode-go)
    answer quickly; cloud providers need an API key — a missing key returns a
    friendly ``error`` detail, and failures return an empty list plus a
    sanitized ``error`` (the last exception, key-redacted; 401/403 map to a
    "rejected the API key" message).

    ``provider``/``api_base`` query params, when provided, override the saved
    settings for this fetch only — they are never saved. The API key prefers
    the ``X-Api-Key`` header (query ``api_key`` remains as a deprecated
    fallback to avoid breaking older clients, but header use avoids leaking
    the key into logs/history).

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
    # Header preferred; query fallback deprecated (leaks into logs/URLs).
    api_key = (x_api_key or api_key) or ai.get("api_key") or ""
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
            async with httpx.AsyncClient(timeout=15.0) as client:
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
            async with httpx.AsyncClient(timeout=15.0) as client:
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
        "mcp_mode": ai.get("mcp_mode", "internal"),
        "wrapping_prompt": user_settings.get_wrapping_prompt(),
        "reachable": None,
        "probe_error": "",
    }
    if probe:
        reachable, probe_error = await _probe_provider(ai)
        out["reachable"] = reachable
        out["probe_error"] = probe_error
    return out


@router.put("/settings")
async def save_ai_settings(req: AiSettingsRequest, request: Request) -> dict:
    from qualcoder_api.core.security import validate_mcp_command
    from qualcoder_api.core.server_config import is_server_mode

    try:
        validate_mcp_command(req.mcp_server_command, req.mcp_server_args)
    except ValueError as err:
        raise HTTPException(status_code=422, detail=str(err)) from err
    if req.mcp_server_args is not None and len(req.mcp_server_args) > 64:
        raise HTTPException(status_code=422, detail="too many mcp server args")
    if req.mcp_server_env is not None:
        if len(req.mcp_server_env) > 64:
            raise HTTPException(status_code=422, detail="too many mcp env vars")
        for k, v in req.mcp_server_env.items():
            if len(k) > 256 or len(v) > 4096 or "\x00" in k or "\x00" in v:
                raise HTTPException(status_code=422, detail="invalid mcp env var") from None
    # Server mode: configuring an external stdio command is privileged —
    # it spawns a local binary during agentic chat. Require admin.
    if is_server_mode() and (req.mcp_mode == "external" or (req.mcp_server_command or "").strip()):
        from fastapi import Depends  # noqa: F401 - keep import local to avoid cycle

        from qualcoder_api.api.v1.auth_deps import get_current_user

        auth = request.headers.get("authorization", "")
        user = await get_current_user(auth)
        if user.get("role") != "admin":
            raise HTTPException(status_code=403, detail="admin role required for external MCP")
    return user_settings.save_ai_settings(req.model_dump())


@router.post("/ensure-backend")
async def ensure_ai_backend() -> dict:
    """Actively start the configured local backend and load the model.

    Currently implemented for the ``lmstudio`` provider: runs ``lms server
    start`` (when nothing listens on the configured port) and ``lms load
    <model>`` (when the model is not yet served). Idempotent — every step is
    skipped when its goal is already met. Long-running: a cold model load can
    take minutes, so callers should treat this as a progress-y operation.
    """
    import asyncio

    from qualcoder_api.services import lmstudio_service

    ai = user_settings.get_ai_settings()
    provider = ai.get("provider") or ""
    if provider != "lmstudio":
        raise HTTPException(
            status_code=422,
            detail="Auto-start is only supported for the lmstudio provider",
        )
    if not ai.get("auto_start_backend", True):
        raise HTTPException(
            status_code=422,
            detail="Auto-start of the local backend is disabled in Settings",
        )
    return await asyncio.to_thread(
        lmstudio_service.ensure_lmstudio,
        (ai.get("api_base") or "").strip(),
        (ai.get("model") or "").strip(),
    )


class McpPermissionsRequest(BaseModel):
    mcp_permissions: str = "read"


@router.put("/mcp-permissions")
async def save_ai_mcp_permissions(req: McpPermissionsRequest) -> dict:
    """Change the MCP access level from the AI sidebar (no full settings body)."""
    if req.mcp_permissions not in ("read", "write", "full"):
        raise HTTPException(status_code=422, detail="mcp_permissions must be read, write or full")
    ai = user_settings.get_ai_settings()
    ai["mcp_permissions"] = req.mcp_permissions
    saved = user_settings.save_ai_settings(ai)
    return {"mcp_permissions": saved["mcp_permissions"]}


@router.get("/mcp-tools")
async def ai_mcp_tools() -> dict:
    """The MCP tools the AI sidebar exposes, grouped by access level.

    Read tools are always available; write tools only when ``mcp_permissions``
    is "write" or "full". The sidebar lists them so the user can see exactly
    what the assistant may do, alongside the permission selector.
    """
    ai = user_settings.get_ai_settings()
    permissions = ai.get("mcp_permissions", "read")
    from qualcoder_api.services.mcp_service import READ_TOOLS, WRITE_TOOLS

    return {
        "permissions": permissions,
        "write_enabled": permissions in ("write", "full"),
        "read_tools": READ_TOOLS,
        "write_tools": WRITE_TOOLS,
        "mcp_mode": ai.get("mcp_mode", "internal"),
    }


class WrappingPromptRequest(BaseModel):
    text: str


@router.get("/wrapping-prompt")
async def ai_wrapping_prompt() -> dict:
    """The effective AI-chat wrapping prompt (custom or the built-in default)."""
    from qualcoder_api.services.user_settings import DEFAULT_WRAPPING_PROMPT, get_wrapping_prompt

    return {"text": get_wrapping_prompt(), "default": DEFAULT_WRAPPING_PROMPT}


@router.put("/wrapping-prompt")
async def save_ai_wrapping_prompt(req: WrappingPromptRequest) -> dict:
    """Persist the AI-chat wrapping prompt (blank resets to the default)."""
    from qualcoder_api.services.user_settings import DEFAULT_WRAPPING_PROMPT, save_wrapping_prompt

    text = save_wrapping_prompt(req.text)
    return {"text": text, "default": DEFAULT_WRAPPING_PROMPT}


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
            agentic=req.agentic, confirm_writes=req.confirm_writes,
        )
    except AiUnavailable as err:
        raise HTTPException(status_code=503, detail=str(err)) from err
    if result.get("status") == "awaiting_approval":
        return {
            "chat_id": chat_id,
            "status": "awaiting_approval",
            "token": result["token"],
            "pending_tools": result["pending_tools"],
        }
    tool_calls = result.get("tool_calls", [])
    await ai_history.append_message(
        session,
        chat_id,
        "assistant",
        result["reply"],
        request_json=json.dumps({"tool_calls": tool_calls}, ensure_ascii=False),
    )
    await ai_history.ensure_title(session, chat_id, req.message)
    return {
        "chat_id": chat_id,
        "reply": result["reply"],
        "model": result["model"],
        "tool_calls": tool_calls,
    }


@router.post("/chat/approve")
async def ai_chat_approve(req: ChatApproveRequest, svc: ServiceDep, session: DbDep) -> dict:
    """Continue a paused agentic turn after the user decided on its pending
    write tools; the final assistant reply is appended to the chat."""
    import json

    from qualcoder_api.services import ai_history
    from qualcoder_api.services.ai_service import AiService

    try:
        result = await AiService(svc.session_factory).approve_agentic(req.token, req.approve)
    except AiUnavailable as err:
        raise HTTPException(status_code=503, detail=str(err)) from err
    if result.get("status") == "awaiting_approval":
        return {
            "chat_id": req.chat_id,
            "status": "awaiting_approval",
            "token": result["token"],
            "pending_tools": result["pending_tools"],
        }
    chat_id = req.chat_id
    if chat_id is not None:
        await ai_history.append_message(
            session,
            chat_id,
            "assistant",
            result["reply"],
            request_json=json.dumps(
                {"tool_calls": result.get("tool_calls", [])}, ensure_ascii=False
            ),
        )
        await ai_history.ensure_title(session, chat_id, "AI chat")
    return {
        "chat_id": chat_id,
        "reply": result["reply"],
        "model": result["model"],
        "tool_calls": result.get("tool_calls", []),
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


@router.get("/personas")
async def ai_personas_list() -> dict:
    """Per-mode personas with their built-in default and current text."""
    from qualcoder_api.services import user_settings
    from qualcoder_api.services.ai_prompts import MODE_SYSTEM_PROMPTS

    overrides = user_settings.get_ai_personas()
    personas = [
        {"mode": mode, "default": default, "text": overrides.get(mode, default)}
        for mode, default in MODE_SYSTEM_PROMPTS.items()
    ]
    return {"personas": personas}


@router.put("/personas")
async def ai_personas_save(req: PersonasRequest) -> dict:
    """Persist per-mode persona overrides (blank text restores the default)."""
    from qualcoder_api.services import user_settings

    saved = user_settings.save_ai_personas(req.personas)
    return {"personas": [{"mode": mode, "text": text} for mode, text in saved.items()]}


@router.get("/templates/all")
async def ai_templates_editor(session: DbDep) -> dict:
    """Everything the template editor can edit (built-in / app / project)."""
    from qualcoder_api.services import ai_templates

    return {"templates": await ai_templates.list_editor_templates(session)}


@router.put("/templates/all")
async def ai_templates_editor_save(req: EditorTemplateRequest, session: DbDep) -> dict:
    """Save an editable template.

    Built-in ids write an app-wide override; ``global:`` ids update an
    app-wide template; ``custom:`` ids update the project's row.
    """
    from qualcoder_api.services import ai_templates, user_settings

    if not req.text.strip():
        raise HTTPException(status_code=422, detail="text is required")
    if is_custom_prompt_id(req.id):
        row_id = ai_templates.resolve_custom_row_id(req.id)
        if row_id is None:
            raise HTTPException(status_code=422, detail="invalid custom template id")
        updated = await ai_templates.update_template(
            session, row_id, name=req.name, description=req.description, text=req.text
        )
        if updated is None:
            raise HTTPException(status_code=404, detail="template not found")
        return updated
    if req.id.startswith("global:"):
        return user_settings.save_ai_global_prompt(
            {
                "id": req.id[len("global:"):],
                "name": req.name,
                "description": req.description,
                "text": req.text,
            }
        )
    user_settings.save_ai_prompt_override(req.id, req.text)
    return {"id": req.id, "name": req.name, "description": req.description, "text": req.text}


@router.post("/templates/all/reset")
async def ai_templates_editor_reset(req: ResetTemplateRequest) -> dict:
    """Restore a built-in template to its shipped text."""
    from qualcoder_api.services import user_settings
    from qualcoder_api.services.ai_prompts import CATALOG

    if CATALOG.by_id(req.id) is None:
        raise HTTPException(status_code=422, detail="not a built-in template")
    user_settings.reset_ai_prompt_override(req.id)
    return {"id": req.id, "reset": True}


@router.post("/templates/global")
async def ai_templates_global_create(req: TemplateRequest) -> dict:
    """Create an app-wide template, available in every project."""
    from qualcoder_api.services import user_settings

    if not req.name.strip() or not req.text.strip():
        raise HTTPException(status_code=422, detail="name and text are required")
    return user_settings.save_ai_global_prompt(
        {"name": req.name, "description": req.description, "text": req.text}
    )


@router.delete("/templates/global/{prompt_id}", status_code=204)
async def ai_templates_global_delete(prompt_id: str) -> None:
    from qualcoder_api.services import user_settings

    if not user_settings.delete_ai_global_prompt(prompt_id):
        raise HTTPException(status_code=404, detail="template not found")


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
            ai, req.query, req.limit, source_ids=req.source_ids, category_id=req.category_id
        )
    except AiUnavailable as err:
        raise HTTPException(status_code=503, detail=str(err)) from err


@router.get("/index")
async def ai_index_status(svc: OpenProjectDep) -> dict:
    """Status of the persistent vector index (project-local sqlite)."""
    from qualcoder_api.services import ai_index

    return ai_index.index_status(svc.project_path)


@router.post("/index")
async def ai_index_build(req: IndexRequest, svc: OpenProjectDep) -> dict:
    """Build (or rebuild) the persistent embedding index."""
    from qualcoder_api.services import ai_index

    assert svc.session_factory is not None
    ai = user_settings.get_ai_settings()
    try:
        return await ai_index.rebuild_index(svc.session_factory, svc.project_path, ai)
    except AiUnavailable as err:
        raise HTTPException(status_code=503, detail=str(err)) from err


@router.delete("/index", status_code=204)
async def ai_index_delete(svc: OpenProjectDep) -> None:
    """Delete the persistent embedding index."""
    from qualcoder_api.services import ai_index

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
