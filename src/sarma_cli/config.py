"""Sarma configuration management.

Layered TOML config, highest priority last:
  CLI flags  >  env vars  >  local ./.sarma/config.toml  >  global ~/.sarma/config.toml

The global file (``sarma init``) holds your base provider + MCP servers; a local
file (``sarma init --local``) overrides individual fields per workspace.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from typing import Any

from sarma_cli import paths

API_MODES = ("openai_compatible", "openai_responses", "anthropic")

_DEFAULT_CONFIG_TOML = """\
# Sarma CLI configuration
# Docs: https://github.com/Captain-AI-Hub/Sarma
#
# Provider: add as many as you like with [[providers]].
# The one with default = true (or the first listed) is active.

[[providers]]
name = "Default"
model_name = ""
api_key = ""
base_url = ""
api_mode = "openai_compatible"   # openai_compatible | openai_responses | anthropic
temperature = 0.7
top_p = 1.0
max_context_tokens = 128000
default = true

# MCP servers (repeat [[mcp_servers]] for each server)
# [[mcp_servers]]
# name = "ida-mcp"
# transport = "streamable_http"
# url = "http://127.0.0.1:11338/mcp"
# enabled = true

# Agent: which skills to load and which MCP servers the agent may call.
# The agent's model is driven by the active provider above.
[agent]
# Skill directory names under ~/.sarma/skills or ./.sarma/skills.
skills = []
# Restrict the agent to a subset of configured servers by name.
# Empty = all enabled [[mcp_servers]].
mcp_servers = []
"""


@dataclass(slots=True)
class ProviderConfig:
    name: str = ""            # human-readable label
    model_name: str = ""
    api_key: str = ""
    base_url: str = ""
    api_mode: str = "openai_compatible"
    temperature: float = 0.7
    top_p: float = 1.0
    max_context_tokens: int = 128_000
    default: bool = False     # the active provider


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
class AgentConfig:
    """Which skills the chat agent loads and which MCP servers it may call.

    The agent's *model* is ``[provider].model_name`` (a single source of truth).
    ``skills`` are directory names under ``~/.sarma/skills`` or ``./.sarma/skills``.
    ``mcp_servers`` restricts the agent to a subset of the configured servers by
    name; empty means "all enabled servers".
    """
    skills: list[str] = field(default_factory=list)
    mcp_servers: list[str] = field(default_factory=list)


@dataclass(slots=True)
class CliConfig:
    providers: list[ProviderConfig] = field(default_factory=list)
    mcp_servers: list[McpServerConfig] = field(default_factory=list)
    agent: AgentConfig = field(default_factory=AgentConfig)

    @property
    def provider(self) -> ProviderConfig:
        """Convenience: the active (default-marked) provider, or the first, or a blank."""
        for p in self.providers:
            if p.default:
                return p
        if self.providers:
            return self.providers[0]
        return ProviderConfig()

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
        return self._server_dicts(None)

    @property
    def agent_mcp_server_dicts(self) -> list[dict[str, Any]]:
        """Servers the chat agent may call: [agent].mcp_servers, or all if empty."""
        allow = self.agent.mcp_servers
        return self._server_dicts(set(allow) if allow else None)

    def _server_dicts(self, allow: set[str] | None) -> list[dict[str, Any]]:
        result = []
        for s in self.mcp_servers:
            if not s.enabled:
                continue
            if allow is not None and s.name not in allow:
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


def _read_toml(path: Any) -> dict[str, Any]:
    """Read a TOML file into a dict, or empty dict if it doesn't exist."""
    if not path.exists():
        return {}
    with open(path, "rb") as f:
        return tomllib.load(f)


def _merge_raw(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Merge two raw TOML dicts; ``override`` wins.

    - ``providers``: merged by ``name`` (override replaces a same-named provider
      and appends new ones). ``default`` is cleared from all providers, then set
      on the override's default (or the first).
    - ``mcp_servers``: merged by ``name``.
    """
    merged: dict[str, Any] = {}

    provs: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for raw_p in list(base.get("providers") or []) + list(override.get("providers") or []):
        name = str(raw_p.get("name", ""))
        if name not in provs:
            order.append(name)
        provs[name] = {**provs.get(name, {}), **raw_p}
    # After merging, exactly one provider should be default: the last one
    # in the override that explicitly set default = true. If none did,
    # fall back to the last in the base, then the first in the merged list.
    if order:
        default_candidate: str | None = None
        # Walk in reverse — last override with default=true wins.
        for raw_p in reversed(list(override.get("providers") or [])):
            if raw_p.get("default"):
                default_candidate = str(raw_p.get("name", ""))
                break
        if default_candidate is None:
            for raw_p in reversed(list(base.get("providers") or [])):
                if raw_p.get("default"):
                    default_candidate = str(raw_p.get("name", ""))
                    break
        if default_candidate is None:
            default_candidate = order[0]
        # Clear all defaults, then set the winner
        for n in provs:
            provs[n]["default"] = False
        provs[default_candidate]["default"] = True
        merged["providers"] = [provs[n] for n in order]

    # Backward-compat: old single [provider] as the merge anchor
    bp = dict(base.get("provider") or {})
    op = dict(override.get("provider") or {})
    bp.update(op)
    if bp:
        bp["name"] = str(bp.get("name", "Default"))
        merged["provider"] = bp
        # If we also parsed providers above, ensure we have a default.
        if "providers" not in merged:
            merged["providers"] = [bp]

    servers: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for srv in list(base.get("mcp_servers") or []) + list(override.get("mcp_servers") or []):
        name = str(srv.get("name", ""))
        if name not in servers:
            order.append(name)
        servers[name] = {**servers.get(name, {}), **srv}
    if order:
        merged["mcp_servers"] = [servers[n] for n in order]

    # agent table: merged key-by-key (a key present in override wins)
    agent = dict(base.get("agent") or {})
    agent.update(override.get("agent") or {})
    if agent:
        merged["agent"] = agent

    return merged


def _parse_toml(data: dict[str, Any]) -> CliConfig:
    """Parse a TOML dict into CliConfig."""
    config = CliConfig()
    # providers: list of [[providers]] tables (TOML array of tables)
    for raw_p in data.get("providers", []):
        config.providers.append(ProviderConfig(
            name=str(raw_p.get("name", "")),
            model_name=str(raw_p.get("model_name", "")),
            api_key=str(raw_p.get("api_key", "")),
            base_url=str(raw_p.get("base_url", "")),
            api_mode=str(raw_p.get("api_mode", "openai_compatible")),
            temperature=float(raw_p.get("temperature", 0.7)),
            top_p=float(raw_p.get("top_p", 1.0)),
            max_context_tokens=int(raw_p.get("max_context_tokens", 128_000)),
            default=bool(raw_p.get("default", False)),
        ))
    # Backward-compat: a flat [provider] table maps to one default provider.
    if prov := data.get("provider"):
        config.providers.append(ProviderConfig(
            name=str(prov.get("name", "Default")),
            model_name=str(prov.get("model_name", "")),
            api_key=str(prov.get("api_key", "")),
            base_url=str(prov.get("base_url", "")),
            api_mode=str(prov.get("api_mode", "openai_compatible")),
            temperature=float(prov.get("temperature", 0.7)),
            top_p=float(prov.get("top_p", 1.0)),
            max_context_tokens=int(prov.get("max_context_tokens", 128_000)),
            default=True,
        ))
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
    if agent := data.get("agent"):
        config.agent = AgentConfig(
            skills=[str(s) for s in (agent.get("skills") or [])],
            mcp_servers=[str(s) for s in (agent.get("mcp_servers") or [])],
        )
    return config




def load_config(
    *,
    model: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    api_mode: str | None = None,
) -> CliConfig:
    """Load layered config: CLI flags > env > local ./.sarma > global ~/.sarma."""
    import os

    # File layer: global base, then local override (merged at the raw-TOML level
    # so a field present in the local file wins over the global one).
    raw = _merge_raw(
        _read_toml(paths.global_config_file()),
        _read_toml(paths.local_config_file()),
    )
    config = _parse_toml(raw)

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


def init_config(local: bool = False) -> None:
    """Initialize Sarma config.

    Default: ensure a global ``~/.sarma/config.toml`` exists, then copy it into
    the working dir's ``./.sarma/config.toml`` so this project has its own
    editable copy. Since local overrides global, the workspace copy is what
    gets used — convenient for per-project tweaks without touching the global.

    ``--local``: only create the local ``./.sarma/config.toml`` (from the global
    if present, else defaults); never write the global file.
    """
    from rich.console import Console
    console = Console()

    g = paths.global_config_file()
    l = paths.local_config_file()

    # Ensure the global config exists (unless we were told to stay local-only).
    if not local and not g.exists():
        g.parent.mkdir(parents=True, exist_ok=True)
        g.write_text(_DEFAULT_CONFIG_TOML, encoding="utf-8")
        (g.parent / "skills").mkdir(exist_ok=True)
        console.print(f"[green]Created global config[/] [cyan]{g}[/]")

    # Create the local copy for this workspace.
    l.parent.mkdir(parents=True, exist_ok=True)
    (l.parent / "skills").mkdir(exist_ok=True)
    if l.exists():
        console.print(f"[yellow]Local config already exists:[/] [cyan]{l}[/] (left untouched)")
        return

    seed = g.read_text(encoding="utf-8") if g.exists() else _DEFAULT_CONFIG_TOML
    source = "global config" if g.exists() else "defaults"
    l.write_text(seed, encoding="utf-8")
    console.print(
        f"[green]Created local config[/] [cyan]{l}[/] [dim](from {source})[/]\n"
        "  This workspace copy overrides the global config — edit it freely."
    )


def _toml_value(v: Any) -> str:
    """Serialize a scalar (or list of scalars) to a TOML literal."""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(_toml_value(x) for x in v) + "]"
    return '"' + str(v).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _dump_toml(data: dict[str, Any]) -> str:
    """Minimal TOML writer for our schema (providers, agent, mcp_servers)."""
    lines: list[str] = []
    provs = data.get("providers")
    if provs:
        for prov in provs:
            lines.append("[[providers]]")
            for k, v in prov.items():
                lines.append(f"{k} = {_toml_value(v)}")
            lines.append("")
    # backward-compat: single [provider] table
    elif data.get("provider"):
        lines.append("[provider]")
        for k, v in data["provider"].items():
            lines.append(f"{k} = {_toml_value(v)}")
        lines.append("")
    agent = data.get("agent")
    if agent:
        lines.append("[agent]")
        for k, v in agent.items():
            lines.append(f"{k} = {_toml_value(v)}")
        lines.append("")
    for srv in data.get("mcp_servers", []):
        lines.append("[[mcp_servers]]")
        for k, v in srv.items():
            lines.append(f"{k} = {_toml_value(v)}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def save_all_providers(providers: list[ProviderConfig]) -> Any:
    """Persist the full providers list to the effective config file.

    Like ``save_global_provider``, targets local first, falls back to global.
    """
    target = paths.local_config_file()
    if not target.exists():
        target = paths.global_config_file()
    raw = _read_toml(target)
    raw["providers"] = [
        {
            "name": p.name, "model_name": p.model_name, "api_key": p.api_key,
            "base_url": p.base_url, "api_mode": p.api_mode,
            "temperature": p.temperature, "top_p": p.top_p,
            "max_context_tokens": p.max_context_tokens, "default": p.default,
        }
        for p in providers
    ]
    raw.pop("provider", None)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_dump_toml(raw), encoding="utf-8")
    return target


def save_global_provider(provider: ProviderConfig) -> Any:
    """Persist provider settings to the effective config file.

    Targets the local ``./.sarma/config.toml`` when it exists, otherwise the
    global ``~/.sarma/config.toml``.  Reads only that one raw file so other
    layers/vars never leak in, replaces the matched provider by name (or appends
    it), and writes it back.  Returns the path written.
    """
    target = paths.local_config_file()
    if not target.exists():
        target = paths.global_config_file()
    raw = _read_toml(target)

    prov_dict = {
        "name": provider.name,
        "model_name": provider.model_name,
        "api_key": provider.api_key,
        "base_url": provider.base_url,
        "api_mode": provider.api_mode,
        "temperature": provider.temperature,
        "top_p": provider.top_p,
        "max_context_tokens": provider.max_context_tokens,
        "default": provider.default,
    }

    provs = raw.get("providers") or []
    replaced = False
    for i, p in enumerate(provs):
        if isinstance(p, dict) and p.get("name") == provider.name:
            provs[i] = prov_dict
            replaced = True
            break
    if not replaced:
        provs.append(prov_dict)
    raw["providers"] = provs

    # Drop the old single-provider key so readers don't see a stale copy.
    raw.pop("provider", None)

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_dump_toml(raw), encoding="utf-8")
    return target


