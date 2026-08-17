"""Optional AI feature gate — talks to any OpenAI-compatible backend via httpx.

Supports chat completions and embeddings (Ollama, LM Studio, OpenAI,
gateways). Pure async, no langchain/torch/faiss/sentence-transformers — the
``httpx`` dependency is already part of the dev toolchain.
"""

from __future__ import annotations

import httpx
from httpx import AsyncClient

from qualcoder_api.core.models import Source
from qualcoder_api.persistence import tables

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

# Project-context injection for chat (permission-gated, read-only queries).
PROJECT_CONTEXT_MAX_CHARS = 3000
PROJECT_CONTEXT_MODES = ("general", "topic_exploration", "code_analysis", "text_analysis")
PROJECT_CONTEXT_CODE_LINES = 30
PROJECT_CONTEXT_SOURCE_LINES = 20

# Code-analysis context: the code tree (name + category path) plus per-code
# memo, coding count and 1-2 example coded segments, whole block capped.
CODE_ANALYSIS_MAX_CHARS = 5000
CODE_ANALYSIS_MAX_CODES = 30
CODE_ANALYSIS_MEMO_CHARS = 200
CODE_ANALYSIS_EXAMPLE_CHARS = 120
CODE_ANALYSIS_EXAMPLES_PER_CODE = 2
CODE_ANALYSIS_PATH_DEPTH = 5

# Text-analysis context: fulltext of the open source, capped.
SOURCE_CONTEXT_MAX_CHARS = 6000
# Several selected sources together: per-source cap above, whole block capped.
SOURCE_SELECTION_MAX_CHARS = 12000
# Topic exploration with explicit selections: union of the selected memos,
# codes and sources, capped defensively (each part is capped individually).
TOPIC_SELECTION_MAX_CHARS = 12000
# Combined per-mode context (primary kind + additive kinds) — the joined
# block is truncated at this budget no matter which kinds were selected.
CHAT_CONTEXT_MAX_CHARS = 12000


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


def _truncate_memo(memo: str, max_chars: int = CHUNK_MAX_CHARS) -> str:
    """Truncate a memo to the same char budget text chunks use."""
    memo = memo.strip()
    return memo if len(memo) <= max_chars else memo[:max_chars]


def _cap_text(text: str, max_chars: int) -> str:
    """Truncate without stripping — preserves already-trimmed blocks."""
    return text if len(text) <= max_chars else text[:max_chars]


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
        memo_ids: list[int] | None = None,
        source_id: int | None = None,
        code_ids: list[int] | None = None,
        source_ids: list[int] | None = None,
    ) -> dict:
        ok, _ = self.is_configured(ai)
        if not ok:
            raise AiUnavailable("AI is not configured")
        # Per-mode context, assembled from the mode's picker selections.
        # Each analysis mode builds its PRIMARY context plus the other
        # selected kinds (additive pickers):
        # - memo_analysis   → memos (all when none selected) + codes +
        #                     sources when their ids are provided
        # - code_analysis   → the selected codes (memo + counts + examples)
        #                     + memos + sources when provided
        # - text_analysis   → the selected sources' fulltext (open source
        #                     ``source_id`` still works; falls back to the
        #                     project summary when nothing matches) + memos
        #                     + codes when provided
        # - topic_exploration → union of the selected memos/codes/sources,
        #                     else the default project summary
        # - search          → index-based, no chat context
        # The joined block is truncated at ``CHAT_CONTEXT_MAX_CHARS``.
        blocks: list[str] = []
        if mode == "memo_analysis":
            block = await self._memo_context(memo_ids)
            if block:
                blocks.append(block)
        elif mode == "code_analysis":
            block = await self._code_analysis_context(ai, code_ids)
            if block:
                blocks.append(block)
        elif mode == "text_analysis":
            ids = source_ids if source_ids else ([source_id] if source_id is not None else None)
            block = await self._text_analysis_context(ai, ids)
            if not block:
                # Unknown/empty sources fall back to the project summary.
                block = await self._project_context(ai)
            if block:
                blocks.append(block)
        elif mode == "topic_exploration":
            if memo_ids or code_ids or source_ids:
                block = await self._selection_context(ai, memo_ids, code_ids, source_ids)
            else:
                block = await self._project_context(ai)
            if block:
                blocks.append(block)
        elif mode in PROJECT_CONTEXT_MODES:
            block = await self._project_context(ai)
            if block:
                blocks.append(block)
        # Additive kinds: extra context attached to the primary one. Only
        # explicit selections are included (never the whole project), and
        # topic_exploration already builds the union itself.
        if mode != "topic_exploration":
            if memo_ids and mode != "memo_analysis":
                block = await self._memo_context(memo_ids)
                if block:
                    blocks.append(block)
            if code_ids and mode != "code_analysis":
                block = await self._code_analysis_context(ai, code_ids)
                if block:
                    blocks.append(block)
            if source_ids and mode != "text_analysis":
                block = await self._text_analysis_context(ai, source_ids)
                if block:
                    blocks.append(block)
        if blocks:
            joined = _cap_text("\n\n".join(blocks), CHAT_CONTEXT_MAX_CHARS)
            context = f"{joined}\n\n{context}" if context else joined
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

    async def _memo_context(self, memo_ids: list[int] | None = None) -> str:
        """Assemble labelled memo excerpts (file + code memos) for chat.

        Reuses the GET /memos queries (``source.memo`` and ``code_name.memo``).
        Each memo is truncated to the text-chunk budget; ``memo_ids`` filters
        to the requested memos, ``None`` includes every memo in the project.
        """
        if self.session_factory is None:
            return ""
        from sqlalchemy import select

        blocks: list[str] = []
        async with self.session_factory() as session:
            file_query = select(
                tables.source.c.id, tables.source.c.name, tables.source.c.memo
            ).where(tables.source.c.memo.is_not(None))
            if memo_ids:
                file_query = file_query.where(tables.source.c.id.in_(memo_ids))
            for sid, name, memo in await session.execute(file_query):
                if memo and str(memo).strip():
                    blocks.append(f"# {name or sid} (file memo):\n{_truncate_memo(str(memo))}")
            code_query = select(
                tables.code_name.c.cid, tables.code_name.c.name, tables.code_name.c.memo
            ).where(tables.code_name.c.memo.is_not(None))
            if memo_ids:
                code_query = code_query.where(tables.code_name.c.cid.in_(memo_ids))
            for cid, name, memo in await session.execute(code_query):
                if memo and str(memo).strip():
                    blocks.append(f"# {name or cid} (code memo):\n{_truncate_memo(str(memo))}")
        return "\n\n".join(blocks)

    async def _project_context(self, ai: dict) -> str:
        """Compact read-only summary of the open project, for the chat prompt.

        Gives the model real context about the project the user is working
        in: the code tree (names with coding counts), the open source files
        (first 20, with media type), total codings and the case count.

        Permission-gated: injected only when AI is enabled AND
        ``mcp_permissions`` is ``"read"`` or ``"full"`` — the ``"write"``
        profile gets no project context. No project open (no session
        factory) or any query failure is skipped gracefully ("").
        """
        if self.session_factory is None:
            return ""
        if not ai.get("enabled"):
            return ""
        if ai.get("mcp_permissions", "read") not in ("read", "full"):
            return ""
        from sqlalchemy import func, select

        from qualcoder_api.core.enums import MediaType
        try:
            async with self.session_factory() as session:
                code_rows = (
                    await session.execute(
                        select(tables.code_name.c.cid, tables.code_name.c.name).order_by(
                            tables.code_name.c.name
                        )
                    )
                ).all()
                counts: dict[int, int] = {}
                total_codings = 0
                for table in (tables.code_text, tables.code_image, tables.code_av):
                    for cid, n in await session.execute(
                        select(table.c.cid, func.count()).group_by(table.c.cid)
                    ):
                        counts[cid] = counts.get(cid, 0) + n
                        total_codings += n
                source_rows = (
                    await session.execute(
                        select(tables.source.c.name, tables.source.c.mediapath).order_by(
                            tables.source.c.name
                        )
                    )
                ).all()
                case_count = (
                    await session.execute(select(func.count()).select_from(tables.cases))
                ).scalar_one()
        except Exception:
            # The chat must never fail because the summary query broke.
            return ""
        lines = [
            "PROJECT CONTEXT",
            f"Sources: {len(source_rows)} total, {PROJECT_CONTEXT_SOURCE_LINES} shown",
        ]
        for name, mediapath in source_rows[:PROJECT_CONTEXT_SOURCE_LINES]:
            lines.append(f"- {name} ({MediaType.from_mediapath(mediapath).value})")
        lines.append(f"Codes: {len(code_rows)} total, {PROJECT_CONTEXT_CODE_LINES} shown")
        for cid, name in code_rows[:PROJECT_CONTEXT_CODE_LINES]:
            lines.append(f"- {name}: {counts.get(cid, 0)} codings")
        lines.append(f"Total codings: {total_codings}")
        lines.append(f"Cases: {case_count}")
        return _truncate_memo("\n".join(lines), PROJECT_CONTEXT_MAX_CHARS)

    async def _code_analysis_context(
        self, ai: dict, code_ids: list[int] | None = None
    ) -> str:
        """Code-aware context for the ``code_analysis`` chat mode.

        Shares the code tree (names with their category/sub-code path)
        plus, per code: the memo/explanation (truncated to 200 chars), the
        coding count, and up to 2 example coded segments (seltext,
        truncated to 120 chars, with the source file name). At most 30
        codes are shown and the whole block is capped at
        ``CODE_ANALYSIS_MAX_CHARS``.

        ``code_ids`` restricts the block to those codes (still capped);
        ``None`` shares the default code tree.

        Same gating and failure behavior as ``_project_context`` (read-only
        queries, skipped gracefully on any error).
        """
        if self.session_factory is None:
            return ""
        if not ai.get("enabled"):
            return ""
        if ai.get("mcp_permissions", "read") not in ("read", "full"):
            return ""
        from sqlalchemy import func, select

        try:
            async with self.session_factory() as session:
                code_rows = (
                    await session.execute(
                        select(
                            tables.code_name.c.cid,
                            tables.code_name.c.name,
                            tables.code_name.c.memo,
                            tables.code_name.c.catid,
                            tables.code_name.c.supercid,
                        ).order_by(tables.code_name.c.name)
                    )
                ).all()
                cat_rows = (
                    await session.execute(
                        select(
                            tables.code_cat.c.catid,
                            tables.code_cat.c.name,
                            tables.code_cat.c.supercatid,
                        )
                    )
                ).all()
                counts: dict[int, int] = {}
                for table in (tables.code_text, tables.code_image, tables.code_av):
                    for cid, n in await session.execute(
                        select(table.c.cid, func.count()).group_by(table.c.cid)
                    ):
                        counts[cid] = counts.get(cid, 0) + n
                if code_ids:
                    wanted = set(code_ids)
                    selected = [row for row in code_rows if row.cid in wanted]
                else:
                    selected = code_rows[:CODE_ANALYSIS_MAX_CODES]
                cid_list = [row.cid for row in selected]
                examples: dict[int, list[tuple[str, str]]] = {cid: [] for cid in cid_list}
                if cid_list:
                    example_rows = (
                        await session.execute(
                            select(
                                tables.code_text.c.cid,
                                tables.code_text.c.seltext,
                                tables.source.c.name,
                            )
                            .join(tables.source, tables.source.c.id == tables.code_text.c.fid)
                            .where(tables.code_text.c.seltext.is_not(None))
                            .where(tables.code_text.c.cid.in_(cid_list))
                            .order_by(tables.code_text.c.ctid)
                        )
                    ).all()
                    for cid, seltext, source_name in example_rows:
                        if len(examples[cid]) >= CODE_ANALYSIS_EXAMPLES_PER_CODE:
                            continue
                        examples[cid].append((str(seltext), str(source_name) if source_name else ""))
        except Exception:
            # The chat must never fail because the summary query broke.
            return ""
        cats = {row.catid: (row.name, row.supercatid) for row in cat_rows}

        def _tree_path(row) -> str:
            """Ancestor names (category chain, then sub-code chain), root-first."""
            parts: list[str] = []
            catid = row.catid
            depth = 0
            while catid is not None and catid in cats and depth < CODE_ANALYSIS_PATH_DEPTH:
                name, supercatid = cats[catid]
                parts.append(name)
                catid = supercatid
                depth += 1
            supercid = row.supercid
            depth = 0
            while supercid is not None and depth < CODE_ANALYSIS_PATH_DEPTH:
                parent = next((r for r in code_rows if r.cid == supercid), None)
                if parent is None:
                    break
                parts.append(parent.name)
                supercid = parent.supercid
                depth += 1
            return " / ".join(reversed(parts))

        lines = [
            "CODE ANALYSIS CONTEXT",
            (
                f"Codes: {len(code_rows)} total, {len(selected)} selected"
                if code_ids
                else f"Codes: {len(code_rows)} total, {len(selected)} shown"
            ),
        ]
        for row in selected:
            name = row.name or f"code {row.cid}"
            path = _tree_path(row)
            lines.append(f"- {name} (path: {path})" if path else f"- {name}")
            lines.append(f"  Codings: {counts.get(row.cid, 0)}")
            if row.memo and str(row.memo).strip():
                memo = _truncate_memo(str(row.memo), CODE_ANALYSIS_MEMO_CHARS)
                lines.append(f"  Memo: {memo}")
            for seltext, source_name in examples.get(row.cid, []):
                sample = _truncate_memo(seltext, CODE_ANALYSIS_EXAMPLE_CHARS)
                source = f" ({source_name})" if source_name else ""
                lines.append(f'  Example: "{sample}"{source}')
        return _truncate_memo("\n".join(lines), CODE_ANALYSIS_MAX_CHARS)

    async def _source_context(self, ai: dict, source_id: int | None) -> str:
        """Fulltext of one open source for the ``text_analysis`` chat mode.

        Prefixed with the file name and capped at ``SOURCE_CONTEXT_MAX_CHARS``.
        ``None``/unknown ids and empty fulltext produce "" — the caller then
        falls back to the generic project summary. Same gating and failure
        behavior as ``_project_context``.
        """
        if self.session_factory is None or source_id is None:
            return ""
        if not ai.get("enabled"):
            return ""
        if ai.get("mcp_permissions", "read") not in ("read", "full"):
            return ""
        from sqlalchemy import select

        try:
            async with self.session_factory() as session:
                row = (
                    await session.execute(
                        select(tables.source.c.name, tables.source.c.fulltext).where(
                            tables.source.c.id == source_id
                        )
                    )
                ).one_or_none()
        except Exception:
            # The chat must never fail because the summary query broke.
            return ""
        if row is None:
            return ""
        name, fulltext = row
        fulltext = (fulltext or "").strip()
        if not fulltext:
            return ""
        text = _truncate_memo(fulltext, SOURCE_CONTEXT_MAX_CHARS)
        return f"TEXT ANALYSIS SOURCE\n# {name or source_id}\n\n{text}"

    async def _text_analysis_context(
        self, ai: dict, source_ids: list[int] | None
    ) -> str:
        """Fulltext of the selected sources for the ``text_analysis`` mode.

        Reuses ``_source_context`` per id (each source capped at
        ``SOURCE_CONTEXT_MAX_CHARS``); the joined block is capped at
        ``SOURCE_SELECTION_MAX_CHARS``. ``None``/empty ids and sources
        without fulltext produce "" — the caller falls back to the generic
        project summary. Same gating as ``_source_context``.
        """
        if not source_ids:
            return ""
        blocks: list[str] = []
        for source_id in source_ids:
            block = await self._source_context(ai, source_id)
            if block:
                blocks.append(block)
        if not blocks:
            return ""
        return _cap_text("\n\n".join(blocks), SOURCE_SELECTION_MAX_CHARS)

    async def _selection_context(
        self,
        ai: dict,
        memo_ids: list[int] | None,
        code_ids: list[int] | None,
        source_ids: list[int] | None,
    ) -> str:
        """Union of the explicitly selected entities for topic exploration.

        Combines the selected memos, codes (memo + coding counts + example
        segments) and source fulltexts into one labelled block, capped
        defensively at ``TOPIC_SELECTION_MAX_CHARS`` (each part is already
        capped individually).
        """
        blocks: list[str] = []
        memo_block = await self._memo_context(memo_ids)
        if memo_block:
            blocks.append(memo_block)
        code_block = await self._code_analysis_context(ai, code_ids)
        if code_block:
            blocks.append(code_block)
        source_block = await self._text_analysis_context(ai, source_ids)
        if source_block:
            blocks.append(source_block)
        if not blocks:
            return ""
        return _cap_text("\n\n".join(blocks), TOPIC_SELECTION_MAX_CHARS)

    async def semantic_search(
        self, ai: dict, query: str, limit: int = 10, source_ids: list[int] | None = None
    ) -> dict:
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
                        results = await ai_index.search_index(
                            project_path, ai, query, limit, source_ids=source_ids
                        )
                        return {"results": results, "indexed": True}
                    except AiUnavailable:
                        pass

        api_base = ai["api_base"].rstrip("/")
        url = f"{api_base}{EMBEDDINGS_PATH}"

        # Text sources WITH their fulltext (the list endpoint deliberately
        # omits fulltext; the search index needs it).
        from sqlalchemy import select

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
        if source_ids:
            # The files context picker acts as a search filter: only the
            # chunks of the selected sources are embedded and scored.
            allowed = set(source_ids)
            chunks = [c for c in chunks if c["source_id"] in allowed]
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
