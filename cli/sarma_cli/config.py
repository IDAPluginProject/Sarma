""".sarma/ configuration management.

Reads .sarma/config.toml in the working directory.
Falls back to IDE database if no local config exists.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SARMA_DIR = Path.cwd() / ".sarma"
CONFIG_FILE = SARMA_DIR / "config.toml"

_DEFAULT_CONFIG_TOML = """\
# Sarma CLI configuration
# Docs: https://github.com/Captain-AI-Hub/Sarma

[provider]
model_name = ""
api_key = ""
base_url = ""
api_mode = "openai_compatible"   # openai_compatible | openai_responses | anthropic
temperature = 0.7
top_p = 1.0
max_context_tokens = 128000

# MCP servers (repeat [[mcp_servers]] for each server)
# [[mcp_servers]]
# name = "ida-mcp"
# transport = "streamable_http"
# url = "http://127.0.0.1:11338/mcp"
# enabled = true
"""


@dataclass(slots=True)
class ProviderConfig:
    model_name: str = ""
    api_key: str = ""
    base_url: str = ""
    api_mode: str = "openai_compatible"
    temperature: float = 0.7
    top_p: float = 1.0
    max_context_tokens: int = 128_000


@dataclass(slots=True)
class McpServerConfig:
    name: str = ""
    transport: str = "streamable_http"
    command: str = ""
    args: str = ""
    env: str = ""
    cwd: str = ""
    url: str = ""
    headers: str = ""
    enabled: bool = True
    encoding: str = "utf-8"
    timeout: float = 60.0
    sse_read_timeout: float = 300.0


@dataclass(slots=True)
class CliConfig:
    provider: ProviderConfig = field(default_factory=ProviderConfig)
    mcp_servers: list[McpServerConfig] = field(default_factory=list)

    @property
    def provider_dict(self) -> dict[str, Any]:
        p = self.provider
        return {
            "id": None,
            "name": "cli",
            "model_name": p.model_name,
            "api_mode": p.api_mode,
            "api_key": p.api_key,
            "base_url": p.base_url,
            "temperature": p.temperature,
            "top_p": p.top_p,
            "max_context_tokens": p.max_context_tokens,
            "enabled": True,
        }

    @property
    def mcp_server_dicts(self) -> list[dict[str, Any]]:
        result = []
        for s in self.mcp_servers:
            if not s.enabled:
                continue
            result.append({
                "id": None,
                "name": s.name,
                "transport": s.transport,
                "enabled": True,
                "command": s.command,
                "args": s.args,
                "env": s.env,
                "cwd": s.cwd,
                "url": s.url,
                "headers": s.headers,
                "encoding": s.encoding,
                "timeout": s.timeout,
                "sse_read_timeout": s.sse_read_timeout,
            })
        return result


def _parse_toml(data: dict[str, Any]) -> CliConfig:
    """Parse a TOML dict into CliConfig."""
    config = CliConfig()
    if prov := data.get("provider"):
        config.provider = ProviderConfig(
            model_name=str(prov.get("model_name", "")),
            api_key=str(prov.get("api_key", "")),
            base_url=str(prov.get("base_url", "")),
            api_mode=str(prov.get("api_mode", "openai_compatible")),
            temperature=float(prov.get("temperature", 0.7)),
            top_p=float(prov.get("top_p", 1.0)),
            max_context_tokens=int(prov.get("max_context_tokens", 128_000)),
        )
    for srv in data.get("mcp_servers", []):
        config.mcp_servers.append(McpServerConfig(
            name=str(srv.get("name", "")),
            transport=str(srv.get("transport", "streamable_http")),
            command=str(srv.get("command", "")),
            args=str(srv.get("args", "")),
            env=str(srv.get("env", "")),
            cwd=str(srv.get("cwd", "")),
            url=str(srv.get("url", "")),
            headers=str(srv.get("headers", "")),
            enabled=bool(srv.get("enabled", True)),
            encoding=str(srv.get("encoding", "utf-8")),
            timeout=float(srv.get("timeout", 60.0)),
            sse_read_timeout=float(srv.get("sse_read_timeout", 300.0)),
        ))
    return config


def _load_from_ide_database() -> CliConfig | None:
    """Fallback: load config from IDE database if available."""
    try:
        from shared.database import DatabaseStore
        db = DatabaseStore()
    except Exception:
        return None

    config = CliConfig()
    providers = db.load_rows("model_providers")
    for p in providers:
        if p.get("enabled"):
            config.provider = ProviderConfig(
                model_name=p.get("model_name", ""),
                api_key=p.get("api_key", ""),
                base_url=p.get("base_url", ""),
                api_mode=p.get("api_mode", "openai_compatible"),
                temperature=float(p.get("temperature", 0.7)),
                top_p=float(p.get("top_p", 1.0)),
                max_context_tokens=int(p.get("max_context_tokens", 128_000)),
            )
            break

    for s in db.load_rows("mcp_servers"):
        if s.get("enabled"):
            config.mcp_servers.append(McpServerConfig(
                name=s.get("name", ""),
                transport=s.get("transport", "streamable_http"),
                command=s.get("command", ""),
                args=s.get("args", ""),
                env=s.get("env", ""),
                cwd=s.get("cwd", ""),
                url=s.get("url", ""),
                headers=s.get("headers", ""),
                enabled=True,
                encoding=s.get("encoding", "utf-8"),
                timeout=float(s.get("timeout", 60.0)),
                sse_read_timeout=float(s.get("sse_read_timeout", 300.0)),
            ))
    return config


def load_config(
    *,
    model: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    api_mode: str | None = None,
) -> CliConfig:
    """Load config with priority: CLI flags > env > .sarma/config.toml > IDE DB."""
    import os

    config: CliConfig | None = None

    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, "rb") as f:
            config = _parse_toml(tomllib.load(f))
    else:
        config = _load_from_ide_database()

    if config is None:
        config = CliConfig()

    # Environment variable overrides
    if env_key := os.environ.get("SARMA_API_KEY"):
        config.provider.api_key = env_key
    if env_url := os.environ.get("SARMA_BASE_URL"):
        config.provider.base_url = env_url
    if env_model := os.environ.get("SARMA_MODEL"):
        config.provider.model_name = env_model
    if env_mode := os.environ.get("SARMA_API_MODE"):
        config.provider.api_mode = env_mode

    # CLI flag overrides (highest priority)
    if model:
        config.provider.model_name = model
    if api_key:
        config.provider.api_key = api_key
    if base_url:
        config.provider.base_url = base_url
    if api_mode:
        config.provider.api_mode = api_mode

    return config


def init_config() -> None:
    """Create .sarma/config.toml with defaults."""
    from rich.console import Console
    console = Console()

    SARMA_DIR.mkdir(parents=True, exist_ok=True)
    if CONFIG_FILE.exists():
        console.print("[yellow].sarma/config.toml already exists.[/]")
        return

    CONFIG_FILE.write_text(_DEFAULT_CONFIG_TOML, encoding="utf-8")
    (SARMA_DIR / "skills").mkdir(exist_ok=True)
    console.print("[green]Created .sarma/config.toml[/] — edit it to configure your provider.")
