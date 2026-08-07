"""AI feature gate API — status, settings, chat, semantic search, prompts,
persistent index, MCP endpoint."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
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
    mode: str = "general"  # general | help | topic_exploration | code_analysis | text_analysis
    prompt_id: str | None = None


class SearchRequest(BaseModel):
    query: str
    limit: int = 10


class IndexRequest(BaseModel):
    rebuild: bool = False


@router.get("/status")
async def ai_status() -> dict:
    ai = user_settings.get_ai_settings()
    configured, reason = AiService.is_configured(ai)
    api_base = ai.get("api_base") or ""
    return {
        "enabled": ai["enabled"],
        "configured": configured,
        "reason": reason,
        "provider": ai.get("provider", "custom"),
        "base_url": api_base,
        "model": ai["model"],
        "mcp_permissions": ai.get("mcp_permissions", "read"),
    }


@router.put("/settings")
async def save_ai_settings(req: AiSettingsRequest) -> dict:
    return user_settings.save_ai_settings(req.model_dump())


@router.post("/chat")
async def ai_chat(req: ChatRequest, svc: ServiceDep, session: DbDep) -> dict:
    ai = user_settings.get_ai_settings()
    try:
        return await AiService(svc.session_factory).chat(
            ai, req.message, req.context, mode=req.mode, prompt_id=req.prompt_id
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
