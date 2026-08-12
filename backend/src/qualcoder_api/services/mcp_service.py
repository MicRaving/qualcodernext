"""MCP (Model Context Protocol) endpoint — JSON-RPC 2.0 over HTTP.

A compact, dependency-free adaptation of the upstream ``ai_mcp_server``:
the backend exposes ``POST /ai/mcp`` accepting JSON-RPC 2.0 requests
(``initialize``, ``tools/list``, ``tools/call``, ``resources/list``,
``resources/read``, ``ping``). Write tools are gated by the AI setting
``mcp_permissions``: ``read`` (default) exposes only read tools, ``write``
additionally allows code/coding/case edits. Every write is audit-logged.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from qualcoder_api.persistence import tables
from qualcoder_api.persistence.repositories import CodeRepository, CodingRepository
from qualcoder_api.services import audit

logger = logging.getLogger(__name__)

PROTOCOL_VERSION = "2025-06-18"

READ_TOOLS: list[dict] = [
    {"name": "get_code_tree", "description": "Return the full codebook tree (categories and codes).", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "get_sources", "description": "List all source files in the project.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "get_source_text", "description": "Return a source's stored text.", "inputSchema": {"type": "object", "properties": {"source_id": {"type": "integer"}}, "required": ["source_id"]}},
    {"name": "get_cases", "description": "List all cases.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "get_codings_for_file", "description": "List text codings of one file.", "inputSchema": {"type": "object", "properties": {"fid": {"type": "integer"}}, "required": ["fid"]}},
    {"name": "search_text", "description": "Regex/plain search over text sources.", "inputSchema": {"type": "object", "properties": {"pattern": {"type": "string"}, "regex": {"type": "boolean"}}, "required": ["pattern"]}},
    {"name": "get_project_summary", "description": "Project statistics.", "inputSchema": {"type": "object", "properties": {}}},
]

WRITE_TOOLS: list[dict] = [
    {"name": "create_code", "description": "Create a code (optionally in a category).", "inputSchema": {"type": "object", "properties": {"name": {"type": "string"}, "catid": {"type": "integer"}, "memo": {"type": "string"}}, "required": ["name"]}},
    {"name": "rename_code", "description": "Rename a code.", "inputSchema": {"type": "object", "properties": {"cid": {"type": "integer"}, "name": {"type": "string"}}, "required": ["cid", "name"]}},
    {"name": "update_code_memo", "description": "Set a code's memo.", "inputSchema": {"type": "object", "properties": {"cid": {"type": "integer"}, "memo": {"type": "string"}}, "required": ["cid", "memo"]}},
    {"name": "delete_code", "description": "Delete a code and its codings.", "inputSchema": {"type": "object", "properties": {"cid": {"type": "integer"}}, "required": ["cid"]}},
    {"name": "create_category", "description": "Create a category.", "inputSchema": {"type": "object", "properties": {"name": {"type": "string"}, "supercatid": {"type": "integer"}}, "required": ["name"]}},
    {"name": "create_coding", "description": "Create a text coding.", "inputSchema": {"type": "object", "properties": {"cid": {"type": "integer"}, "fid": {"type": "integer"}, "pos0": {"type": "integer"}, "pos1": {"type": "integer"}, "seltext": {"type": "string"}}, "required": ["cid", "fid", "pos0", "pos1"]}},
    {"name": "delete_coding", "description": "Delete a text coding by ctid.", "inputSchema": {"type": "object", "properties": {"ctid": {"type": "integer"}}, "required": ["ctid"]}},
    {"name": "create_case", "description": "Create a case.", "inputSchema": {"type": "object", "properties": {"name": {"type": "string"}, "memo": {"type": "string"}}, "required": ["name"]}},
    {"name": "update_case", "description": "Update a case name/memo.", "inputSchema": {"type": "object", "properties": {"caseid": {"type": "integer"}, "name": {"type": "string"}, "memo": {"type": "string"}}, "required": ["caseid"]}},
    {"name": "set_attribute_value", "description": "Set an attribute value for a file or case.", "inputSchema": {"type": "object", "properties": {"name": {"type": "string"}, "attr_type": {"type": "string"}, "entity_id": {"type": "integer"}, "value": {"type": "string"}}, "required": ["name", "attr_type", "entity_id", "value"]}},
]


class McpService:
    """JSON-RPC 2.0 MCP handler over the open project."""

    def __init__(self, session_factory: async_sessionmaker | None, permissions: str = "read"):
        self.session_factory = session_factory
        self.permissions = permissions  # "read" | "write" | "full"
        self.tools = list(READ_TOOLS)
        if self.permissions in ("write", "full"):
            self.tools += list(WRITE_TOOLS)

    # ------------------------------------------------------------------
    # Protocol plumbing
    # ------------------------------------------------------------------

    async def handle(self, request: dict) -> dict | None:
        """Dispatch one JSON-RPC request; returns the response (None for
        notifications)."""
        if not isinstance(request, dict):
            return self._error(None, -32600, "invalid request")
        method = request.get("method")
        params = request.get("params") or {}
        request_id = request.get("id")
        if "id" not in request:
            # notification — acknowledge silently (except initialized).
            return None
        try:
            result = await self._dispatch(str(method or ""), params)
        except McpError as err:
            return self._error(request_id, err.code, str(err))
        except Exception as err:  # pragma: no cover - defensive
            logger.exception("MCP tool error: %s", err)
            return self._error(request_id, -32603, str(err))
        return self._result(request_id, result)

    async def _dispatch(self, method: str, params: dict) -> Any:
        if method == "initialize":
            return {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}, "resources": {}},
                "serverInfo": {"name": "qualcoder-mcp", "version": "1.0.0"},
            }
        if method == "ping":
            return {}
        if method == "tools/list":
            return {"tools": self.tools}
        if method == "tools/call":
            return await self._call_tool(params)
        if method == "resources/list":
            return {"resources": self._resources()}
        if method == "resources/read":
            return await self._read_resource(params)
        if method == "prompts/list":
            return {"prompts": []}
        raise McpError(-32601, f"method not found: {method}")

    def _resources(self) -> list[dict]:
        return [
            {"uri": "qualcoder://codes", "name": "Codebook tree"},
            {"uri": "qualcoder://sources", "name": "Source files"},
            {"uri": "qualcoder://cases", "name": "Cases"},
            {"uri": "qualcoder://summary", "name": "Project summary"},
        ]

    async def _read_resource(self, params: dict) -> dict:
        uri = str(params.get("uri") or "")
        async with self._session() as session:
            if uri == "qualcoder://codes":
                text_ = json.dumps(await self._code_tree(session), ensure_ascii=False, indent=2)
            elif uri == "qualcoder://sources":
                text_ = json.dumps(
                    [{"id": r.id, "name": r.name, "media_type": str(r.media_type.value)} for r in
                     (await session.execute(select(tables.source))).scalars()],
                    ensure_ascii=False, indent=2,
                )
            elif uri == "qualcoder://cases":
                text_ = json.dumps(
                    [{"caseid": r.caseid, "name": r.name, "memo": r.memo} for r in
                     (await session.execute(select(tables.cases))).scalars()],
                    ensure_ascii=False, indent=2,
                )
            elif uri == "qualcoder://summary":
                from qualcoder_api.persistence.repositories import ProjectRepository

                text_ = json.dumps(await ProjectRepository(session).get_summary(), ensure_ascii=False, indent=2)
            else:
                raise McpError(-32002, f"unknown resource: {uri}")
        return {"contents": [{"uri": uri, "mimeType": "application/json", "text": text_}]}

    def _session(self):
        if self.session_factory is None:
            raise McpError(-32001, "no project is open")
        return self.session_factory()

    # ------------------------------------------------------------------
    # Tools
    # ------------------------------------------------------------------

    async def _call_tool(self, params: dict) -> dict:
        name = params.get("name")
        args = params.get("arguments") or {}
        handler = getattr(self, f"_tool_{name}", None)
        if handler is None:
            raise McpError(-32602, f"unknown tool: {name}")
        async with self._session() as session:
            result = await handler(session, args)
            return {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=2)}]}

    @staticmethod
    async def _code_tree(session: AsyncSession) -> list[dict]:
        repo = CodeRepository(session)
        categories = await repo.list_categories()
        codes = await repo.list_codes()
        items = [
            {"kind": "category", "id": cat.catid, "name": cat.name, "parent_id": cat.supercatid}
            for cat in categories
        ]
        items += [
            {"kind": "code", "id": code.cid, "name": code.name, "color": code.color,
             "parent_id": code.supercid or code.catid}
            for code in codes
        ]
        return items

    async def _tool_get_code_tree(self, session: AsyncSession, args: dict) -> dict:
        return {"codes": await self._code_tree(session)}

    async def _tool_get_sources(self, session: AsyncSession, args: dict) -> dict:
        rows = await session.execute(
            select(tables.source.c.id, tables.source.c.name, tables.source.c.mediapath)
        )
        return {
            "sources": [
                {"id": rid, "name": name, "mediapath": mediapath or ""} for rid, name, mediapath in rows
            ]
        }

    async def _tool_get_source_text(self, session: AsyncSession, args: dict) -> dict:
        source_id = int(args.get("source_id", 0))
        row = (
            await session.execute(
                select(tables.source.c.name, tables.source.c.fulltext).where(
                    tables.source.c.id == source_id
                )
            )
        ).first()
        if row is None:
            raise McpError(-32002, f"source {source_id} not found")
        return {"source_id": source_id, "name": row[0], "fulltext": row[1] or ""}

    async def _tool_get_cases(self, session: AsyncSession, args: dict) -> dict:
        rows = await session.execute(select(tables.cases))
        return {
            "cases": [
                {"caseid": r.caseid, "name": r.name, "memo": r.memo or ""} for r in rows
            ]
        }

    async def _tool_get_codings_for_file(self, session: AsyncSession, args: dict) -> dict:
        fid = int(args.get("fid", 0))
        rows = await session.execute(
            select(tables.code_text).where(tables.code_text.c.fid == fid).order_by(tables.code_text.c.pos0)
        )
        return {"fid": fid, "codings": [dict(r._mapping) for r in rows]}

    async def _tool_search_text(self, session: AsyncSession, args: dict) -> dict:
        pattern = str(args.get("pattern") or "")
        if not pattern:
            raise McpError(-32602, "pattern is required")
        use_regex = bool(args.get("regex", False))
        try:
            compiled = re.compile(pattern) if use_regex else re.compile(re.escape(pattern))
        except re.error as err:
            raise McpError(-32602, f"invalid regex: {err}") from err
        rows = await session.execute(
            select(tables.source.c.id, tables.source.c.name, tables.source.c.fulltext).where(
                tables.source.c.fulltext.is_not(None)
            )
        )
        hits = []
        for sid, name, fulltext in rows:
            text_ = fulltext or ""
            for match in compiled.finditer(text_):
                start = max(0, match.start() - 60)
                end = min(len(text_), match.end() + 120)
                hits.append(
                    {"source_id": sid, "file_name": name, "pos0": match.start(),
                     "pos1": match.end(), "context": text_[start:end]}
                )
        return {"hits": hits[:200]}

    async def _tool_get_project_summary(self, session: AsyncSession, args: dict) -> dict:
        from qualcoder_api.persistence.repositories import ProjectRepository

        return {"summary": await ProjectRepository(session).get_summary()}

    # ------------------------------------------------------------------
    # Write tools (audit-logged)
    # ------------------------------------------------------------------

    def _require_write(self) -> None:
        if self.permissions not in ("write", "full"):
            raise McpError(-32004, "write permission denied — enable MCP write access in AI settings")

    async def _tool_create_code(self, session: AsyncSession, args: dict) -> dict:
        self._require_write()
        name = str(args.get("name") or "").strip()
        if not name:
            raise McpError(-32602, "name is required")
        from qualcoder_api.services.user_settings import get_codername

        code = await CodeRepository(session).add_code(
            name=name, owner=get_codername(), catid=args.get("catid"), memo=str(args.get("memo") or "")
        )
        if code is None:
            raise McpError(-32002, f"duplicate code name: {name}")
        await audit.record(session, user=get_codername(), action="code.create", entity="code",
                           entity_id=code.cid, detail=code.model_dump())
        return {"code": code.model_dump()}

    async def _tool_rename_code(self, session: AsyncSession, args: dict) -> dict:
        self._require_write()
        from qualcoder_api.services.user_settings import get_codername

        cid = int(args.get("cid", 0))
        name = str(args.get("name") or "").strip()
        if not name:
            raise McpError(-32602, "name is required")
        from sqlalchemy import select

        from qualcoder_api.persistence import tables

        old_row = (
            await session.execute(select(tables.code_name.c.name).where(tables.code_name.c.cid == cid))
        ).first()
        old_name = old_row[0] if old_row is not None else None
        code = await CodeRepository(session).rename_code(cid, name)
        if code is None:
            raise McpError(-32002, f"code {cid} not found")
        await audit.record(session, user=get_codername(), action="code.rename", entity="code",
                           entity_id=cid, detail={"cid": cid, "old_name": old_name, "new_name": name})
        return {"code": code.model_dump()}

    async def _tool_update_code_memo(self, session: AsyncSession, args: dict) -> dict:
        self._require_write()
        from qualcoder_api.services.user_settings import get_codername

        cid = int(args.get("cid", 0))
        await session.execute(
            update(tables.code_name).where(tables.code_name.c.cid == cid).values(memo=str(args.get("memo") or ""))
        )
        await session.commit()
        await audit.record(session, user=get_codername(), action="code.memo", entity="code",
                           entity_id=cid, detail={"memo": str(args.get("memo") or "")})
        return {"ok": True}

    async def _tool_delete_code(self, session: AsyncSession, args: dict) -> dict:
        self._require_write()
        from qualcoder_api.services.user_settings import get_codername

        cid = int(args.get("cid", 0))
        await CodeRepository(session).delete_code(cid)
        await audit.record(session, user=get_codername(), action="code.delete", entity="code",
                           entity_id=cid)
        return {"ok": True}

    async def _tool_create_category(self, session: AsyncSession, args: dict) -> dict:
        self._require_write()
        from qualcoder_api.services.user_settings import get_codername

        name = str(args.get("name") or "").strip()
        if not name:
            raise McpError(-32602, "name is required")
        category = await CodeRepository(session).add_category(
            name=name, owner=get_codername(), supercatid=args.get("supercatid")
        )
        if category is None:
            raise McpError(-32002, f"duplicate category name: {name}")
        await audit.record(session, user=get_codername(), action="category.create", entity="code_cat",
                           entity_id=category.catid, detail={"name": name})
        return {"category": category.model_dump()}

    async def _tool_create_coding(self, session: AsyncSession, args: dict) -> dict:
        self._require_write()
        from qualcoder_api.services.user_settings import get_codername

        cid = int(args.get("cid", 0))
        fid = int(args.get("fid", 0))
        pos0 = int(args.get("pos0", 0))
        pos1 = int(args.get("pos1", 0))
        seltext = str(args.get("seltext") or "")
        if pos1 <= pos0:
            raise McpError(-32602, "pos1 must be greater than pos0")
        if not seltext:
            row = (
                await session.execute(
                    select(tables.source.c.fulltext).where(tables.source.c.id == fid)
                )
            ).first()
            if row is not None and row[0]:
                seltext = row[0][pos0:pos1]
        try:
            coding = await CodingRepository(session).add_text_coding(
                cid=cid, fid=fid, seltext=seltext, pos0=pos0, pos1=pos1,
                owner=get_codername(),
            )
        except Exception:
            raise McpError(-32002, "coding insert failed (duplicate or invalid ids)") from None
        await audit.record(session, user=get_codername(), action="coding.create", entity="code_text",
                           entity_id=coding.ctid, source_id=fid, detail=coding.model_dump())
        return {"coding": coding.model_dump()}

    async def _tool_delete_coding(self, session: AsyncSession, args: dict) -> dict:
        self._require_write()
        from qualcoder_api.services.user_settings import get_codername

        ctid = int(args.get("ctid", 0))
        row = (
            await session.execute(select(tables.code_text).where(tables.code_text.c.ctid == ctid))
        ).first()
        detail = dict(row._mapping) if row is not None else {}
        await CodingRepository(session).delete_text_coding(ctid)
        await audit.record(session, user=get_codername(), action="coding.delete", entity="code_text",
                           entity_id=ctid, source_id=detail.get("fid"), detail=detail)
        return {"ok": True}

    async def _tool_create_case(self, session: AsyncSession, args: dict) -> dict:
        self._require_write()
        from qualcoder_api.persistence.repositories import CaseRepository
        from qualcoder_api.services.user_settings import get_codername

        name = str(args.get("name") or "").strip()
        if not name:
            raise McpError(-32602, "name is required")
        case = await CaseRepository(session).add_case(name=name, owner=get_codername(),
                                                      memo=str(args.get("memo") or ""))
        if case is None:
            raise McpError(-32002, f"duplicate case name: {name}")
        await audit.record(session, user=get_codername(), action="case.create", entity="case",
                           entity_id=case.caseid, detail=case.model_dump())
        return {"case": case.model_dump()}

    async def _tool_update_case(self, session: AsyncSession, args: dict) -> dict:
        self._require_write()
        from qualcoder_api.persistence.repositories import CaseRepository
        from qualcoder_api.services.user_settings import get_codername

        caseid = int(args.get("caseid", 0))
        values = {}
        if args.get("name") is not None:
            values["name"] = str(args["name"]).strip()
        if args.get("memo") is not None:
            values["memo"] = str(args["memo"])
        case = await CaseRepository(session).update_case(caseid, **values)
        if case is None:
            raise McpError(-32002, f"case {caseid} not found")
        await audit.record(session, user=get_codername(), action="case.update", entity="case",
                           entity_id=caseid, detail=values)
        return {"case": case.model_dump()}

    async def _tool_set_attribute_value(self, session: AsyncSession, args: dict) -> dict:
        self._require_write()
        from qualcoder_api.persistence.repositories import AttributeRepository
        from qualcoder_api.services.user_settings import get_codername

        attr = await AttributeRepository(session).set_value(
            name=str(args.get("name") or ""),
            attr_type=str(args.get("attr_type") or "case"),
            value=str(args.get("value") or ""),
            entity_id=int(args.get("entity_id", 0)),
            owner=get_codername(),
        )
        await audit.record(session, user=get_codername(), action="attribute.set_value", entity="attribute",
                           entity_id=attr.id, detail={"name": attr.name, "value": attr.value})
        return {"attribute": attr.model_dump()}

    # ------------------------------------------------------------------
    # Response helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _result(request_id, result: Any) -> dict:
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    @staticmethod
    def _error(request_id, code: int, message: str) -> dict:
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


class McpError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code
