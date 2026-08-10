"""Optional AI feature gate — talks to any OpenAI-compatible backend via httpx.

Supports chat completions and embeddings (Ollama, LM Studio, OpenAI,
gateways). Pure async, no langchain/torch/faiss/sentence-transformers — the
``httpx`` dependency is already part of the dev toolchain.
"""

from __future__ import annotations

import httpx
from httpx import AsyncClient

from qualcoder_api.core.models import Source

CHAT_PATH = "/chat/completions"
EMBEDDINGS_PATH = "/embeddings"

# Providers that authenticate with an API key (local ones ignore it).
CLOUD_PROVIDERS = ("gemini", "gpt", "claude")
SYSTEM_PROMPT = (
    "You are a research assistant for qualitative data analysis. "
    "Answer concisely and helpfully."
)
SIMILARITY_THRESHOLD = 0.15
CHUNK_MAX_CHARS = 2000


class AiUnavailable(Exception):
    """Raised when the AI backend is unreachable or misconfigured."""


def _body_snippet(response: httpx.Response) -> str:
    """Short human-readable slice of a failed response body."""
    try:
        return str(response.json())[:200]
    except Exception:
        return (getattr(response, "text", "") or "")[:200] or "no body"


def _cosine(a: list[float], b: list[float]) -> float:
    """Pure-Python cosine similarity (no numpy dependency)."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def _chunk_text(source, fulltext: str, max_chars: int = CHUNK_MAX_CHARS) -> list[dict]:
    """Split a source's fulltext into chunks of at most ``max_chars`` chars.

    Paragraphs are merged while they fit; over-long paragraphs are hard-split.
    Each chunk carries the source id and file name for reporting.
    """
    chunks: list[str] = []
    for paragraph in fulltext.split("\n\n"):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        while len(paragraph) > max_chars:
            chunks.append(paragraph[:max_chars])
            paragraph = paragraph[max_chars:]
        if chunks and len(chunks[-1]) + len(paragraph) + 2 <= max_chars:
            chunks[-1] += "\n\n" + paragraph
        else:
            chunks.append(paragraph)
    return [
        {"source_id": source.id, "file_name": source.name, "text": text}
        for text in chunks
    ]


class AiService:
    """Async client for OpenAI-compatible chat and embeddings endpoints."""

    def __init__(self, session_factory):
        self.session_factory = session_factory

    @staticmethod
    def is_configured(ai: dict) -> tuple[bool, str]:
        """(True, "") when the ai dict is usable, else (False, reason)."""
        api_base = (ai.get("api_base") or "").strip()
        model = (ai.get("model") or "").strip()
        provider = ai.get("provider") or "custom"
        if not api_base:
            return False, "AI is not configured: api_base is empty"
        if not model:
            return False, "AI is not configured: model is empty"
        # Cloud providers authenticate with an API key; local ones don't.
        if provider in CLOUD_PROVIDERS and not (ai.get("api_key") or "").strip():
            return False, f"{provider} requires an API key — paste it in Settings."
        return True, ""

    @staticmethod
    def _headers(ai: dict) -> dict:
        api_key = (ai.get("api_key") or "").strip()
        if not api_key:
            return {}
        headers = {"Authorization": f"Bearer {api_key}"}
        provider = ai.get("provider") or "custom"
        if provider == "claude":
            # Anthropic's OpenAI-compat layer accepts the bearer token and
            # expects the version header on every request.
            headers["anthropic-version"] = "2023-06-01"
        return headers

    async def chat(
        self,
        ai: dict,
        message: str,
        context: str = "",
        mode: str = "general",
        prompt_id: str | None = None,
    ) -> dict:
        ok, _ = self.is_configured(ai)
        if not ok:
            raise AiUnavailable("AI is not configured")
        from qualcoder_api.services.ai_prompts import prompt_for, system_prompt_for

        system_prompt = system_prompt_for(mode)
        extra_prompt = prompt_for(prompt_id, mode)
        api_base = ai["api_base"].rstrip("/")
        url = f"{api_base}{CHAT_PATH}"
        content = message
        if context:
            content = f"{context}\n\n{message}"
        if extra_prompt:
            content = f"Instructions:\n{extra_prompt}\n\n---\n\n{content}"
        payload = {
            "model": ai["model"],
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": content},
            ],
            "stream": False,
        }
        try:
            async with AsyncClient(timeout=60) as client:
                response = await client.post(url, json=payload, headers=self._headers(ai))
        except httpx.RequestError as err:
            raise AiUnavailable(
                f"AI backend unreachable at {api_base} — start Ollama/LM Studio or check Settings."
            ) from err
        if response.status_code >= 400:
            raise AiUnavailable(f"AI backend error {response.status_code}: {_body_snippet(response)}")
        data = response.json()
        content = ""
        choices = data.get("choices") or []
        if choices:
            content = (choices[0].get("message") or {}).get("content") or ""
        return {"reply": content, "model": ai["model"]}

    async def semantic_search(self, ai: dict, query: str, limit: int = 10) -> dict:
        ok, _ = self.is_configured(ai)
        if not ok:
            raise AiUnavailable("AI is not configured")

        # Use the persistent index when one exists for the same project
        # (built via POST /ai/index); otherwise fall back to the stateless
        # on-the-fly embedding path below.
        if self.session_factory is not None:
            from qualcoder_api.main import service
            from qualcoder_api.services import ai_index

            project_path = service.project_path
            if project_path:
                status = ai_index.index_status(project_path)
                if status.get("indexed") and status.get("model") == ai.get("model"):
                    try:
                        results = await ai_index.search_index(project_path, ai, query, limit)
                        return {"results": results, "indexed": True}
                    except AiUnavailable:
                        pass

        api_base = ai["api_base"].rstrip("/")
        url = f"{api_base}{EMBEDDINGS_PATH}"

        # Text sources WITH their fulltext (the list endpoint deliberately
        # omits fulltext; the search index needs it).
        from sqlalchemy import select

        from qualcoder_api.persistence import tables

        async with self.session_factory() as session:
            rows = await session.execute(
                select(
                    tables.source.c.id,
                    tables.source.c.name,
                    tables.source.c.fulltext,
                    tables.source.c.mediapath,
                ).where(tables.source.c.fulltext.is_not(None))
            )
            sources = [
                Source.model_validate(
                    {"id": r[0], "name": r[1], "fulltext": r[2], "mediapath": r[3]}
                )
                for r in rows
            ]
        chunks: list[dict] = []
        for source in sources:
            fulltext = (source.fulltext or "").strip()
            if not fulltext:
                continue
            mediapath = source.mediapath or ""
            if mediapath and not mediapath.startswith(("/docs/", "docs:")):
                continue
            chunks.extend(_chunk_text(source, fulltext))
        if not chunks:
            return {"results": [], "indexed": False}

        payload = {"model": ai["model"], "input": [query] + [c["text"] for c in chunks]}
        try:
            async with AsyncClient(timeout=60) as client:
                response = await client.post(url, json=payload, headers=self._headers(ai))
        except httpx.RequestError as err:
            raise AiUnavailable(
                f"AI backend unreachable at {api_base} — start Ollama/LM Studio or check "
                "Settings. The /embeddings call failed, so this backend may not support "
                "embeddings."
            ) from err
        if response.status_code >= 400:
            raise AiUnavailable(
                f"AI backend error {response.status_code}: {_body_snippet(response)} "
                "(embeddings may not be supported by this backend)"
            )

        data = response.json()
        raw = [item.get("embedding") or [] for item in (data.get("data") or [])]
        if not raw:
            return {"results": [], "indexed": False}
        query_vector = raw[0]
        results = []
        for vector, chunk in zip(raw[1:], chunks, strict=False):
            score = _cosine(query_vector, vector)
            if score >= SIMILARITY_THRESHOLD:
                results.append(
                    {
                        "source_id": chunk["source_id"],
                        "file_name": chunk["file_name"],
                        "text": chunk["text"],
                        "score": round(score, 4),
                    }
                )
        results.sort(key=lambda item: item["score"], reverse=True)
        return {"results": results[: max(0, limit)], "indexed": False}
