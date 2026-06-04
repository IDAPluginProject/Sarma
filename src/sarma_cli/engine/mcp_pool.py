"""MCP client pool — persistent MultiServerMCPClient lifecycle management."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any

from sarma_cli.engine.errors import McpConnectionError

logger = logging.getLogger(__name__)
DEFAULT_MCP_CONNECT_TIMEOUT = 20.0


@dataclass(frozen=True, slots=True)
class McpServerStatus:
    """Connection summary for one configured MCP server."""

    name: str
    connected: bool
    tool_count: int = 0
    error: str = ""


def _config_fingerprint(configs: dict[str, dict[str, Any]]) -> str:
    """Stable serialization of server configs for equality comparison."""
    try:
        return json.dumps(configs, sort_keys=True, default=str)
    except (TypeError, ValueError):
        return ""


def _connect_timeout(configs: dict[str, dict[str, Any]]) -> float:
    timeouts = [DEFAULT_MCP_CONNECT_TIMEOUT]
    for config in configs.values():
        timeout = config.get("timeout")
        if isinstance(timeout, (int, float)) and timeout > 0:
            timeouts.append(float(timeout))
    return min(timeouts)


class McpClientPool:
    """Manages persistent MCP client connections.

    Lazy-connects on first tool request, keeps clients alive for reuse,
    and provides health-check / reconnect on failure.
    """

    def __init__(self) -> None:
        self._client: Any | None = None  # MultiServerMCPClient
        self._server_configs: dict[str, dict[str, Any]] = {}
        self._config_fingerprint: str = ""
        self._tools: list[Any] = []  # list[BaseTool]
        self._connected: bool = False
        self._server_statuses: dict[str, McpServerStatus] = {}

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def tools(self) -> list[Any]:
        return list(self._tools)

    @property
    def server_statuses(self) -> list[McpServerStatus]:
        return list(self._server_statuses.values())

    async def connect(
        self, server_configs: dict[str, dict[str, Any]]
    ) -> list[Any]:
        """Connect (or reconnect) to MCP servers and return available tools.

        Args:
            server_configs: Dict mapping server name → connection config,
                            as produced by McpServerEntry.to_langchain_config().
        """
        fingerprint = _config_fingerprint(server_configs)
        if self._connected and fingerprint and fingerprint == self._config_fingerprint:
            return self._tools

        # Disconnect previous client if any
        await self.disconnect()

        self._server_configs = dict(server_configs)
        self._config_fingerprint = fingerprint
        self._server_statuses = {
            name: McpServerStatus(name=name, connected=False)
            for name in server_configs
        }

        if not server_configs:
            self._tools = []
            self._connected = True
            return self._tools

        try:
            from langchain_mcp_adapters.client import MultiServerMCPClient

            self._client = MultiServerMCPClient(
                server_configs, tool_name_prefix=True
            )
            self._tools = await asyncio.wait_for(
                self._client.get_tools(),
                timeout=_connect_timeout(server_configs),
            )
            self._connected = True
            self._server_statuses = {
                name: McpServerStatus(
                    name=name,
                    connected=True,
                    tool_count=self._count_server_tools(name),
                )
                for name in server_configs
            }
            logger.info(
                "MCP pool connected: %d tools from %d servers",
                len(self._tools),
                len(server_configs),
            )
            return self._tools
        except Exception as exc:
            await self.disconnect()
            self._server_configs = dict(server_configs)
            self._server_statuses = {
                name: McpServerStatus(
                    name=name,
                    connected=False,
                    error=str(exc),
                )
                for name in server_configs
            }
            logger.error("MCP pool connection failed: %s", exc)
            raise McpConnectionError(
                ", ".join(server_configs.keys()), str(exc)
            ) from exc

    async def reconnect(self) -> list[Any]:
        """Reconnect using the last known server configs."""
        if not self._server_configs:
            return []
        return await self.connect(self._server_configs)

    async def disconnect(self) -> None:
        """Cleanly close all MCP connections."""
        if self._client is not None:
            try:
                if hasattr(self._client, "close"):
                    await self._client.close()
            except Exception as exc:
                logger.warning("Error closing MCP client: %s", exc)
            finally:
                self._client = None
        self._tools = []
        self._connected = False
        self._config_fingerprint = ""
        self._server_statuses = {
            name: McpServerStatus(name=name, connected=False)
            for name in self._server_configs
        }

    def filter_tools(
        self,
        tools: list[Any],
        allowlist: set[str] | None = None,
        denylist: set[str] | None = None,
    ) -> list[Any]:
        """Apply allow/deny lists to a set of tools."""
        result = tools
        if allowlist is not None:
            result = [t for t in result if t.name in allowlist]
        if denylist is not None:
            result = [t for t in result if t.name not in denylist]
        return result

    def _count_server_tools(self, server_name: str) -> int:
        return sum(
            1
            for tool in self._tools
            if _tool_belongs_to_server(getattr(tool, "name", ""), server_name)
        )


def _tool_belongs_to_server(tool_name: str, server_name: str) -> bool:
    return (
        tool_name == server_name
        or tool_name.startswith(f"{server_name}_")
        or tool_name.startswith(f"{server_name}__")
        or tool_name.startswith(f"{server_name}.")
        or tool_name.startswith(f"{server_name}:")
    )
