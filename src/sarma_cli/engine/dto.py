"""Data transfer objects for cross-layer communication.

These are the only types that should cross the supervisor → app boundary.
The app layer must not import from supervisor.models directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ModelProviderDTO:
    id: int | None
    name: str
    model_name: str
    api_mode: str
    api_key: str
    base_url: str
    temperature: float
    top_p: float
    max_context_tokens: int
    enabled: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "model_name": self.model_name,
            "api_mode": self.api_mode,
            "api_key": self.api_key,
            "base_url": self.base_url,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "max_context_tokens": self.max_context_tokens,
            "enabled": self.enabled,
        }


@dataclass
class McpServerDTO:
    id: int | None
    name: str
    transport: str
    enabled: bool
    command: str
    args: str
    env: str
    cwd: str
    encoding: str
    url: str
    headers: str
    timeout: float
    sse_read_timeout: float

    def to_langchain_config(self) -> dict[str, Any]:
        import json

        transport = "streamable_http" if self.transport == "http" else self.transport
        config: dict[str, Any] = {"transport": transport}
        if self.transport == "stdio":
            config["command"] = self.command
            if self.args:
                try:
                    config["args"] = json.loads(self.args)
                except (json.JSONDecodeError, TypeError):
                    config["args"] = []
            if self.env:
                try:
                    config["env"] = json.loads(self.env)
                except (json.JSONDecodeError, TypeError):
                    pass
            if self.cwd:
                config["cwd"] = self.cwd
            if self.encoding and self.encoding != "utf-8":
                config["encoding"] = self.encoding
        else:
            config["url"] = self.url
            if self.headers:
                try:
                    config["headers"] = json.loads(self.headers)
                except (json.JSONDecodeError, TypeError):
                    pass
            if self.timeout and self.transport in ("http", "streamable_http", "sse"):
                config["timeout"] = self.timeout
            if self.sse_read_timeout and self.transport == "sse":
                config["sse_read_timeout"] = self.sse_read_timeout
        return config

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "transport": self.transport,
            "enabled": self.enabled,
            "command": self.command,
            "args": self.args,
            "env": self.env,
            "cwd": self.cwd,
            "encoding": self.encoding,
            "url": self.url,
            "headers": self.headers,
            "timeout": self.timeout,
            "sse_read_timeout": self.sse_read_timeout,
        }
