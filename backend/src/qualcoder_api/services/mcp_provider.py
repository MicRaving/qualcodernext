"""Unified MCP tool provider abstraction for the agentic chat loop.

Two implementations:

- ``InternalMcpProvider`` — wraps QCnext's own hand-rolled ``McpService``
  (in-process, no external dependencies).
- ``ExternalMcpProvider`` — connects to a local MCP server via the
  official ``mcp`` SDK over stdio, giving the agentic chat access to
  the server's full tool set.

``make_provider(ai, session_factory)`` resolves the right one from the
``mcp_mode`` user setting.
"""

from __future__ import annotations

import contextlib
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


class McpProvider:
    """Unified interface for providing MCP tools to the agentic chat.

    ``tools`` is a list of dicts (``name``, ``description``, ``inputSchema``)
    — the shape the OpenAI function-calling converter expects.
    """

    def __init__(self) -> None:
        self.tools: list[dict[str, Any]] = []

    async def __aenter__(self) -> McpProvider:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        pass

    async def call(self, name: str, args: dict[str, Any]) -> str:
        raise NotImplementedError


# ------------------------------------------------------------------
# Internal (QCnext's own hand-rolled MCP service)
# ------------------------------------------------------------------


class InternalMcpProvider(McpProvider):
    """Wraps the existing ``McpService`` — all tools run in-process."""

    def __init__(self, session_factory: Any, permissions: str = "read") -> None:
        from qualcoder_api.services.mcp_service import McpService

        self._service = McpService(session_factory, permissions)
        self.tools = self._service.tools

    async def call(self, name: str, args: dict[str, Any]) -> str:
        result = await self._service._call_tool({"name": name, "arguments": args})
        content = result.get("content") or []
        if content:
            return content[0].get("text") or "{}"
        return json.dumps(result, ensure_ascii=False)


# ------------------------------------------------------------------
# External (local stdio MCP server via the official SDK)
# ------------------------------------------------------------------


class ExternalMcpProvider(McpProvider):
    """Connects to a local MCP server via the ``mcp`` SDK over stdio."""

    def __init__(
        self,
        command: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
    ) -> None:
        self._command = command
        self._args = args or []
        self._env = env or {}
        self._session: Any = None
        self._transport_cm: Any = None
        self._session_cm: Any = None

    async def __aenter__(self) -> ExternalMcpProvider:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        params = StdioServerParameters(
            command=self._command,
            args=self._args,
            env=self._env or None,
        )
        self._transport_cm = stdio_client(params)
        read, write = await self._transport_cm.__aenter__()
        self._session_cm = ClientSession(read, write)
        self._session = await self._session_cm.__aenter__()
        await self._session.initialize()
        result = await self._session.list_tools()
        self.tools = [
            {
                "name": t.name,
                "description": t.description or "",
                "inputSchema": (
                    t.inputSchema
                    if isinstance(t.inputSchema, dict)
                    else (t.inputSchema.model_dump() if hasattr(t.inputSchema, "model_dump") else {})
                ),
            }
            for t in result.tools
        ]
        logger.info("external MCP connected: %d tools from %s", len(self.tools), self._command)
        return self

    async def __aexit__(self, *_exc: object) -> None:
        if self._session_cm is not None:
            with contextlib.suppress(Exception):
                await self._session_cm.__aexit__(None, None, None)
            self._session_cm = None
            self._session = None
        if self._transport_cm is not None:
            with contextlib.suppress(Exception):
                await self._transport_cm.__aexit__(None, None, None)
            self._transport_cm = None

    async def call(self, name: str, args: dict[str, Any]) -> str:
        if self._session is None:
            raise RuntimeError("external MCP server not connected")
        result = await self._session.call_tool(name, arguments=args)
        parts: list[str] = []
        for block in result.content:
            if hasattr(block, "text"):
                parts.append(block.text)
            else:
                parts.append(str(block))
        return "\n".join(parts) if parts else "{}"


# ------------------------------------------------------------------
# Factory
# ------------------------------------------------------------------


def make_provider(ai: dict, session_factory: Any) -> McpProvider:
    """Create the right provider from the user's ``mcp_mode`` setting.

    Raises ``AiUnavailable`` when external mode is selected but the
    server command is empty.
    """
    if ai.get("mcp_mode") == "external":
        from qualcoder_api.services.ai_service import AiUnavailable

        command = str(ai.get("mcp_server_command") or "").strip()
        if not command:
            raise AiUnavailable(
                "External MCP mode is enabled but no server command is configured. "
                "Set a command in Settings \u2192 AI Assistant \u2192 MCP Mode."
            )
        return ExternalMcpProvider(
            command=command,
            args=ai.get("mcp_server_args") or [],
            env=ai.get("mcp_server_env") or {},
        )
    return InternalMcpProvider(session_factory, ai.get("mcp_permissions", "read"))
