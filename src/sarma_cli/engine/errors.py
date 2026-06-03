"""Runtime exceptions and error types."""

from __future__ import annotations


class SarmaRuntimeError(Exception):
    """Base exception for Sarma runtime failures."""


class ProviderNotConfiguredError(SarmaRuntimeError):
    """No model provider is configured or the selected one is invalid."""


class McpConnectionError(SarmaRuntimeError):
    """Failed to connect to an MCP server."""

    def __init__(self, server_name: str, detail: str = "") -> None:
        self.server_name = server_name
        msg = f"MCP connection failed: {server_name}"
        if detail:
            msg += f" — {detail}"
        super().__init__(msg)


class AgentBuildError(SarmaRuntimeError):
    """Failed to construct the LangGraph agent."""


class AgentRunError(SarmaRuntimeError):
    """Agent execution failed during streaming."""

    def __init__(self, detail: str = "", *, recoverable: bool = True) -> None:
        self.recoverable = recoverable
        super().__init__(detail)


class PersistenceError(SarmaRuntimeError):
    """Database operation for runtime data failed."""

    def __init__(self, operation: str = "", detail: str = "") -> None:
        self.operation = operation
        msg = (
            f"Runtime persistence failed: {operation}"
            if operation
            else "Runtime persistence failed"
        )
        if detail:
            msg += f" — {detail}"
        super().__init__(msg)
