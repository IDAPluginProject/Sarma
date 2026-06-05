"""Sarma configuration management.

Configuration is split into TOML files across global and workspace scopes:

- ``models.toml``: named model providers.
- ``agents.toml``: workflow/agent model, MCP, and skill permissions.
- ``mcp.toml``: MCP server definitions.
- ``rag.toml``: RAG chunking model and knowledge base registry.

Global ``models.toml`` and ``agents.toml`` are the authoritative model and
workflow policy files. MCP servers and RAG knowledge bases are additive:
``~/.sarma`` entries remain available, while ``./.sarma`` can add new entries
or override entries with the same name. RAG embedding model settings are global;
RAG knowledge base registrations may live in either scope, while default Chroma
storage stays workspace-local.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sarma_cli import paths

API_MODES = ("openai_compatible", "openai_responses", "anthropic")
WILDCARD = "*"
WORKFLOWS = ("ruflo", "audit", "audit-slim")
LEGACY_WORKFLOW_ALIASES = {
    "chat": "ruflo",
}
_CONTEXT_WINDOW_UNITS = {
    "k": 1_000,
    "m": 1_000_000,
}

_DEFAULT_MODELS_TOML = """\
# Sarma model providers
# `active` is used when an agent does not specify its own model.
active = "default"

[[models]]
name = "default"
model_name = ""
api_key = ""
base_url = ""
api_mode = "openai_compatible"   # openai_compatible | openai_responses | anthropic
max_context_tokens = 128000
enabled = true
"""

_DEFAULT_AGENTS_TOML = """\
# Sarma workflow agent routing.
# `model` references a name from models.toml.
# `mcp` and `skills` accept ["*"] for all, or a list of names.

[[agents]]
name = "ruflo"
model = "default"
mcp = ["*"]
skills = []

[[agents]]
name = "audit"
model = "default"
mcp = ["*"]
skills = []

[[agents]]
name = "audit.recon"
model = "default"
mcp = ["*"]
skills = []

[[agents]]
name = "audit.hunt"
model = "default"
mcp = ["*"]
skills = []

[[agents]]
name = "audit.validate"
model = "default"
mcp = ["*"]
skills = []

[[agents]]
name = "audit.gapfill"
model = "default"
mcp = ["*"]
skills = []

[[agents]]
name = "audit.dedupe"
model = "default"
mcp = ["*"]
skills = []

[[agents]]
name = "audit.trace"
model = "default"
mcp = ["*"]
skills = []

[[agents]]
name = "audit.feedback"
model = "default"
mcp = ["*"]
skills = []

[[agents]]
name = "audit.report"
model = "default"
mcp = ["*"]
skills = []

[[agents]]
name = "audit-slim"
model = "default"
mcp = ["*"]
skills = []

[[agents]]
name = "audit-slim.recon"
model = "default"
mcp = ["*"]
skills = []

[[agents]]
name = "audit-slim.hunter"
model = "default"
mcp = ["*"]
skills = []

[[agents]]
name = "audit-slim.verify"
model = "default"
mcp = ["*"]
skills = []

[[agents]]
name = "audit-slim.report"
model = "default"
mcp = ["*"]
skills = []
"""

_DEFAULT_MCP_TOML = """\
# MCP servers (repeat [[mcp_servers]] for each server)

# [[mcp_servers]]
# name = "local-http-tools"
# transport = "http"  # stdio | http | sse
# url = "http://127.0.0.1:8000/mcp"
# enabled = true
"""

_DEFAULT_RAG_TOML = """\
# RAG knowledge base settings.
# `embedding_model` is independent from chat models in models.toml.
embedding_backend = "huggingface"  # huggingface | api
embedding_model = ""
embedding_api_base = ""
embedding_api_key = ""
embedding_local_path = ""
chunk_size = 1200
chunk_overlap = 150

# [[knowledge_bases]]
# name = "project-docs"
# docs_path = ""
# chroma_path = ""
# enabled = true
"""


@dataclass(slots=True)
class ProviderConfig:
    name: str = "default"
    model_name: str = ""
    api_key: str = ""
    base_url: str = ""
    api_mode: str = "openai_compatible"
    temperature: float = 0.0
    top_p: float = 1.0
    max_context_tokens: int = 128_000
    enabled: bool = True


@dataclass(slots=True)
class McpServerConfig:
    name: str = ""
    transport: str = "stdio"
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
    name: str = "ruflo"
    model: str = "default"
    mcp: list[str] = field(default_factory=lambda: [WILDCARD])
    skills: list[str] = field(default_factory=list)

    def allows_all_mcp(self) -> bool:
        return WILDCARD in self.mcp

    def allows_all_skills(self) -> bool:
        return WILDCARD in self.skills


@dataclass(slots=True)
class KnowledgeBaseConfig:
    name: str = ""
    docs_path: str = ""
    chroma_path: str = ""
    enabled: bool = True


@dataclass(slots=True)
class RagConfig:
    embedding_backend: str = "huggingface"
    embedding_model: str = ""
    embedding_api_base: str = ""
    embedding_api_key: str = ""
    embedding_local_path: str = ""
    chunk_size: int = 1200
    chunk_overlap: int = 150
    knowledge_bases: list[KnowledgeBaseConfig] = field(default_factory=list)


@dataclass(slots=True)
class CliConfig:
    active_model: str = "default"
    models: list[ProviderConfig] = field(default_factory=list)
    mcp_servers: list[McpServerConfig] = field(default_factory=list)
    agents: list[AgentConfig] = field(default_factory=list)
    rag: RagConfig = field(default_factory=RagConfig)

    @property
    def provider(self) -> ProviderConfig:
        return self.get_model(self.active_model)

    def get_model(self, name: str | None = None) -> ProviderConfig:
        target = name or self.active_model
        for model in self.models:
            if model.name == target and model.enabled:
                return model
        for model in self.models:
            if model.enabled:
                return model
        return ProviderConfig(name=target or "default")

    def upsert_model(self, provider: ProviderConfig) -> None:
        for idx, existing in enumerate(self.models):
            if existing.name == provider.name:
                self.models[idx] = provider
                return
        self.models.append(provider)


def _provider_to_dict(p: ProviderConfig) -> dict[str, Any]:
    return {
        "id": None,
        "name": p.name,
        "model_name": p.model_name,
        "api_mode": p.api_mode,
        "api_key": p.api_key,
        "base_url": p.base_url,
        "max_context_tokens": p.max_context_tokens,
        "enabled": p.enabled,
    }


def parse_context_window(value: Any, default: int = 128_000) -> int:
    """Parse a context window token count.

    Supports integer values and shorthand strings such as ``200K`` and ``1M``.
    """
    if value is None:
        return default
    if isinstance(value, str):
        text = value.strip().replace("_", "").replace(",", "")
        if not text:
            return default
        unit = text[-1].lower()
        multiplier = _CONTEXT_WINDOW_UNITS.get(unit)
        if multiplier is not None:
            number = text[:-1].strip()
            tokens = int(float(number) * multiplier)
        else:
            tokens = int(float(text))
    else:
        tokens = int(value)
    if tokens <= 0:
        raise ValueError("Max context window must be greater than 0.")
    return tokens


def _read_toml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with open(path, "rb") as f:
        return tomllib.load(f)


def _ensure_global_config_suite() -> None:
    g = paths.global_dir()
    g.mkdir(parents=True, exist_ok=True)
    (g / "skills").mkdir(exist_ok=True)
    paths.rag_models_dir().mkdir(parents=True, exist_ok=True)
    defaults = {
        paths.MODELS_NAME: _DEFAULT_MODELS_TOML,
        paths.AGENTS_NAME: _DEFAULT_AGENTS_TOML,
        paths.MCP_NAME: _DEFAULT_MCP_TOML,
        paths.RAG_NAME: _DEFAULT_RAG_TOML,
    }
    for filename, text in defaults.items():
        target = g / filename
        if not target.exists():
            target.write_text(text, encoding="utf-8")


def ensure_workspace_config() -> None:
    """Create local workspace directories without copying global config files."""
    _ensure_global_config_suite()
    local = paths.local_dir()
    local.mkdir(parents=True, exist_ok=True)
    (local / "skills").mkdir(exist_ok=True)
    paths.rag_docs_dir().mkdir(parents=True, exist_ok=True)
    paths.rag_chroma_dir().mkdir(parents=True, exist_ok=True)


def _parse_models(data: dict[str, Any]) -> tuple[str, list[ProviderConfig]]:
    models = []
    for raw in data.get("models", []):
        models.append(ProviderConfig(
            name=str(raw.get("name", "default")),
            model_name=str(raw.get("model_name", "")),
            api_key=str(raw.get("api_key", "")),
            base_url=str(raw.get("base_url", "")),
            api_mode=str(raw.get("api_mode", "openai_compatible")),
            temperature=0.0,
            top_p=1.0,
            max_context_tokens=parse_context_window(raw.get("max_context_tokens")),
            enabled=bool(raw.get("enabled", True)),
        ))
    if not models:
        models.append(ProviderConfig())
    return str(data.get("active") or models[0].name), models


def _parse_mcp(data: dict[str, Any]) -> list[McpServerConfig]:
    servers = []
    for srv in data.get("mcp_servers", []):
        servers.append(McpServerConfig(
            name=str(srv.get("name", "")),
            transport=str(srv.get("transport", "stdio")),
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
    return servers


def _parse_agents(data: dict[str, Any]) -> list[AgentConfig]:
    agents = []
    seen: set[str] = set()
    for raw in data.get("agents", []):
        name = _normalize_agent_name(str(raw.get("name", "ruflo")))
        if name in seen:
            continue
        seen.add(name)
        agents.append(AgentConfig(
            name=name,
            model=str(raw.get("model", "default")),
            mcp=[str(x) for x in raw.get("mcp", [WILDCARD])],
            skills=[str(x) for x in raw.get("skills", [])],
        ))
    if not agents:
        agents.append(AgentConfig())
    return agents


def _parse_rag(data: dict[str, Any]) -> RagConfig:
    chunk_size = int(data.get("chunk_size", 1200))
    chunk_overlap = int(data.get("chunk_overlap", 150))
    if chunk_size <= 0:
        chunk_size = 1200
    if chunk_overlap < 0:
        chunk_overlap = 0
    if chunk_overlap >= chunk_size:
        chunk_overlap = max(0, chunk_size // 4)
    knowledge_bases = [
        KnowledgeBaseConfig(
            name=str(raw.get("name", "")),
            docs_path=str(raw.get("docs_path", "")),
            chroma_path=str(raw.get("chroma_path", "")),
            enabled=bool(raw.get("enabled", True)),
        )
        for raw in data.get("knowledge_bases", [])
    ]
    embedding_backend = str(data.get("embedding_backend", "huggingface")).lower()
    if embedding_backend not in {"huggingface", "api"}:
        embedding_backend = "huggingface"
    return RagConfig(
        embedding_backend=embedding_backend,
        embedding_model=str(data.get("embedding_model") or data.get("model", "")),
        embedding_api_base=str(data.get("embedding_api_base", "")),
        embedding_api_key=str(data.get("embedding_api_key", "")),
        embedding_local_path=str(data.get("embedding_local_path", "")),
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        knowledge_bases=knowledge_bases,
    )


def _merge_named(
    global_items: list[Any],
    local_items: list[Any],
) -> list[Any]:
    by_name: dict[str, Any] = {}
    order: list[str] = []
    for item in [*global_items, *local_items]:
        name = str(getattr(item, "name", "")).strip()
        if not name:
            continue
        if name not in by_name:
            order.append(name)
        by_name[name] = item
    return [by_name[name] for name in order]


def load_global_mcp_servers() -> list[McpServerConfig]:
    """Load global MCP server definitions only."""
    _ensure_global_config_suite()
    return _parse_mcp(_read_toml(paths.global_mcp_file()))


def load_local_mcp_servers() -> list[McpServerConfig]:
    """Load workspace MCP server definitions only."""
    ensure_workspace_config()
    return _parse_mcp(_read_toml(paths.local_mcp_file()))


def load_global_rag_config() -> RagConfig:
    """Load global RAG model settings and global KB registrations."""
    _ensure_global_config_suite()
    return _parse_rag(_read_toml(paths.global_rag_file()))


def load_local_rag_config() -> RagConfig:
    """Load workspace RAG KB registrations only."""
    ensure_workspace_config()
    return _parse_rag(_read_toml(paths.local_rag_file()))


def _normalize_agent_name(name: str) -> str:
    workflow, dot, subagent = name.partition(".")
    workflow = LEGACY_WORKFLOW_ALIASES.get(workflow, workflow)
    return f"{workflow}.{subagent}" if dot else workflow


def load_config() -> CliConfig:
    """Load the effective config suite using global defaults plus local overlays."""
    ensure_workspace_config()
    active, models = _parse_models(_read_toml(paths.global_models_file()))
    agents = _parse_agents(_read_toml(paths.global_agents_file()))
    global_rag = load_global_rag_config()
    local_rag = load_local_rag_config()
    rag = RagConfig(
        embedding_backend=global_rag.embedding_backend,
        embedding_model=global_rag.embedding_model,
        embedding_api_base=global_rag.embedding_api_base,
        embedding_api_key=global_rag.embedding_api_key,
        embedding_local_path=global_rag.embedding_local_path,
        chunk_size=global_rag.chunk_size,
        chunk_overlap=global_rag.chunk_overlap,
        knowledge_bases=_merge_named(
            global_rag.knowledge_bases,
            local_rag.knowledge_bases,
        ),
    )
    return CliConfig(
        active_model=active,
        models=models,
        mcp_servers=_merge_named(load_global_mcp_servers(), load_local_mcp_servers()),
        agents=agents,
        rag=rag,
    )


def init_config(local: bool = False) -> None:
    """Initialize global and workspace config files."""
    from rich.console import Console
    console = Console()

    _ensure_global_config_suite()
    if local:
        ensure_workspace_config()
        console.print(f"[green]Workspace config ready:[/] [cyan]{paths.local_dir()}[/]")
        return

    ensure_workspace_config()
    console.print(f"[green]Global config ready:[/] [cyan]{paths.global_dir()}[/]")
    console.print(f"[green]Workspace config ready:[/] [cyan]{paths.local_dir()}[/]")


def _toml_value(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(_toml_value(x) for x in v) + "]"
    return '"' + str(v).replace("\\", "\\\\").replace('"', '\\"') + '"'


def save_models(config: CliConfig) -> Path:
    """Persist the global models.toml file."""
    lines = [f"active = {_toml_value(config.active_model)}", ""]
    for model in config.models:
        lines.append("[[models]]")
        for key, value in _provider_to_dict(model).items():
            if key == "id":
                continue
            lines.append(f"{key} = {_toml_value(value)}")
        lines.append("")
    target = paths.global_models_file()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return target


def save_agents(config: CliConfig) -> Path:
    """Persist the global agents.toml file."""
    lines = [
        "# Sarma workflow agent routing.",
        "# `model` references a name from models.toml.",
        '# `mcp` and `skills` accept ["*"] for all, or a list of names.',
        "",
    ]
    for agent in sorted(config.agents, key=_agent_sort_key):
        lines.append("[[agents]]")
        lines.append(f"name = {_toml_value(agent.name)}")
        lines.append(f"model = {_toml_value(agent.model)}")
        lines.append(f"mcp = {_toml_value(agent.mcp)}")
        lines.append(f"skills = {_toml_value(agent.skills)}")
        lines.append("")
    target = paths.global_agents_file()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return target


def _agent_sort_key(agent: AgentConfig) -> tuple[int, int, str]:
    workflow = agent.name.split(".", 1)[0]
    try:
        workflow_index = WORKFLOWS.index(workflow)
    except ValueError:
        workflow_index = len(WORKFLOWS)
    is_subagent = 1 if "." in agent.name else 0
    return workflow_index, is_subagent, agent.name


def save_mcp_servers(
    servers: list[McpServerConfig],
    *,
    scope: str = "local",
) -> Path:
    """Persist a concrete MCP server list to local or global scope."""
    lines = ["# MCP servers (repeat [[mcp_servers]] for each server)", ""]
    for server in servers:
        lines.append("[[mcp_servers]]")
        for key in (
            "name",
            "transport",
            "command",
            "args",
            "env",
            "cwd",
            "url",
            "headers",
            "enabled",
            "encoding",
            "timeout",
            "sse_read_timeout",
        ):
            lines.append(f"{key} = {_toml_value(getattr(server, key))}")
        lines.append("")
    target = paths.global_mcp_file() if _scope(scope) == "global" else paths.local_mcp_file()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return target


def save_rag_config(rag: RagConfig, *, scope: str = "local") -> Path:
    """Persist a concrete RAG config to local or global scope."""
    is_global = _scope(scope) == "global"
    lines = [
        "# RAG knowledge base settings.",
    ]
    if is_global:
        lines.extend([
            "# `embedding_model` is independent from chat models in models.toml.",
            f"embedding_backend = {_toml_value(rag.embedding_backend)}",
            f"embedding_model = {_toml_value(rag.embedding_model)}",
            f"embedding_api_base = {_toml_value(rag.embedding_api_base)}",
            f"embedding_api_key = {_toml_value(rag.embedding_api_key)}",
            f"embedding_local_path = {_toml_value(rag.embedding_local_path)}",
            f"chunk_size = {_toml_value(rag.chunk_size)}",
            f"chunk_overlap = {_toml_value(rag.chunk_overlap)}",
            "",
        ])
    else:
        lines.extend([
            "# Workspace files register local/private knowledge bases only.",
            "# RAG embedding model settings are loaded from ~/.sarma/rag.toml.",
            "",
        ])

    for kb in rag.knowledge_bases:
        lines.append("[[knowledge_bases]]")
        lines.append(f"name = {_toml_value(kb.name)}")
        lines.append(f"docs_path = {_toml_value(kb.docs_path)}")
        lines.append(f"chroma_path = {_toml_value(kb.chroma_path)}")
        lines.append(f"enabled = {_toml_value(kb.enabled)}")
        lines.append("")
    target = paths.global_rag_file() if is_global else paths.local_rag_file()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return target


def save_rag_model(config: CliConfig) -> Path:
    """Persist global RAG model settings while preserving global KB entries."""
    global_rag = load_global_rag_config()
    rag = RagConfig(
        embedding_backend=config.rag.embedding_backend,
        embedding_model=config.rag.embedding_model,
        embedding_api_base=config.rag.embedding_api_base,
        embedding_api_key=config.rag.embedding_api_key,
        embedding_local_path=config.rag.embedding_local_path,
        chunk_size=config.rag.chunk_size,
        chunk_overlap=config.rag.chunk_overlap,
        knowledge_bases=global_rag.knowledge_bases,
    )
    return save_rag_config(rag, scope="global")


def save_rag_knowledge_bases(
    knowledge_bases: list[KnowledgeBaseConfig],
    *,
    scope: str = "local",
) -> Path:
    """Persist RAG knowledge base registrations in local or global scope."""
    base = load_global_rag_config() if _scope(scope) == "global" else RagConfig()
    base.knowledge_bases = knowledge_bases
    return save_rag_config(base, scope=scope)


def _scope(value: str) -> str:
    scope = value.strip().lower()
    if scope not in {"local", "workspace", "global"}:
        raise ValueError("Scope must be local, workspace, or global.")
    return "local" if scope == "workspace" else scope
