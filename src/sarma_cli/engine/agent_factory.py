"""LangGraph ReAct Agent factory."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from typing import Any

from sarma_cli.engine.errors import AgentBuildError, ProviderNotConfiguredError
from sarma_cli.engine.mcp_pool import McpClientPool
from sarma_cli.engine.models import AgentRunConfig, ResolvedSkill
from sarma_cli.engine.model_factory import ModelFactory
from sarma_cli.runtime.middleware import build_agent_middleware_for_model
from sarma_cli.runtime.services import AgentRuntimeServices
from sarma_cli.resources.network_tools import (
    build_http_exchange_tool,
    build_packet_exchange_tool,
)
from sarma_cli.resources.rag import build_rag_search_tool
from sarma_cli.resources.web_tools import build_web_search_tool

logger = logging.getLogger(__name__)


def _provider_key(provider: Any) -> dict[str, Any]:
    if hasattr(provider, "to_dict"):
        return provider.to_dict()
    return {
        "name": getattr(provider, "name", ""),
        "model_name": getattr(provider, "model_name", ""),
        "api_mode": getattr(provider, "api_mode", ""),
        "api_key": getattr(provider, "api_key", ""),
        "base_url": getattr(provider, "base_url", ""),
        "temperature": getattr(provider, "temperature", None),
        "top_p": getattr(provider, "top_p", None),
    }


def _skill_key(skill: ResolvedSkill | None) -> dict[str, Any] | None:
    if skill is None:
        return None
    return {
        "id": skill.id,
        "name": skill.name,
        "system_prompt_suffix": skill.system_prompt_suffix,
        "tool_allowlist": None if skill.tool_allowlist is None else sorted(skill.tool_allowlist),
        "tool_denylist": None if skill.tool_denylist is None else sorted(skill.tool_denylist),
        "preferred_model_name": skill.preferred_model_name,
        "temperature_override": skill.temperature_override,
    }


def _rag_key(rag: Any) -> dict[str, Any]:
    try:
        return asdict(rag)
    except TypeError:
        return {}


class AgentFactory:
    """Builds a LangGraph agent from runtime configuration."""

    def __init__(
        self,
        pool: McpClientPool,
        workspace_path: str = "",
        model_factory: ModelFactory | None = None,
        runtime_services: AgentRuntimeServices | None = None,
    ) -> None:
        self._pool = pool
        self._workspace_path = workspace_path
        self._model_factory = model_factory or ModelFactory()
        self._runtime_services = runtime_services
        self._agent_cache: dict[str, tuple[Any, list[Any]]] = {}
        self._agent_cache_limit = 8

    async def build(
        self, config: AgentRunConfig
    ) -> tuple[Any, list[Any]]:
        """Build and return (compiled_graph, tools).

        Args:
            config: Full run configuration.

        Returns:
            Tuple of (compiled LangGraph agent, list of LangChain tools).

        Raises:
            ProviderNotConfiguredError: If the provider is invalid.
            AgentBuildError: If agent construction fails.
        """
        provider = config.provider

        # Validate provider has minimum fields
        if not provider.model_name:
            raise ProviderNotConfiguredError(
                "Model name is required for the selected provider."
            )

        # 1. Build MCP server configs from enabled servers
        server_configs: dict[str, dict[str, Any]] = {}
        for server in config.enabled_servers:
            server_configs[server.name] = server.to_langchain_config()

        # 2. Connect / reuse MCP client pool and get tools
        all_tools = await self._pool.connect(server_configs)

        # 3. Apply skill tool filter and append built-in local tools.
        tools = self._apply_skill_filter(all_tools, config.skill)
        tools.extend(self._build_builtin_tools(config))

        if not tools:
            logger.info(
                "No MCP tools available (no servers connected or all filtered "
                "out). Agent will answer from its own knowledge."
            )

        cache_key = self._agent_cache_key(config, server_configs, tools)
        cached = self._agent_cache.get(cache_key)
        if cached is not None:
            logger.info(
                "Agent cache hit: mode=%s model=%s tools=%d skill=%s",
                config.mode,
                provider.model_name,
                len(tools),
                config.skill.name if config.skill else "none",
            )
            return cached

        # 4. Initialize LLM
        try:
            model = self._init_model(provider, config.skill)
        except Exception as exc:
            raise AgentBuildError(
                f"Failed to initialize model: {exc}"
            ) from exc

        # 5. Build agent. Audit modes use fixed pipelines; Ruflo uses a
        #    primary ReAct agent with a controlled subagent delegation tool.
        try:
            agent = self._create_agent(config, model, tools)
        except Exception as exc:
            raise AgentBuildError(
                f"Failed to create agent: {exc}"
            ) from exc

        logger.info(
            "Agent built: model=%s, tools=%d, skill=%s",
            provider.model_name,
            len(tools),
            config.skill.name if config.skill else "none",
        )

        self._agent_cache[cache_key] = (agent, tools)
        if len(self._agent_cache) > self._agent_cache_limit:
            self._agent_cache.pop(next(iter(self._agent_cache)))
        return agent, tools

    def _create_agent(
        self,
        config: AgentRunConfig,
        model: Any,
        tools: list[Any],
    ) -> Any:
        if config.mode in ("audit", "audit-slim"):
            subagent_models = self._load_subagent_models(config.subagent_providers)
            subagent_models.pop("orchestrator", None)
            compile_kwargs = (
                self._runtime_services.compile_kwargs()
                if self._runtime_services is not None
                else {}
            )

            if config.mode == "audit-slim":
                from sarma_cli.engine.audit_slim_graph import build_audit_slim_graph
                from sarma_cli.engine.audit_slim_subagents import AUDIT_SLIM_SUBAGENTS

                return build_audit_slim_graph(
                    model=model,
                    tools=tools,
                    system_prompt=config.system_prompt or "",
                    subagent_specs=AUDIT_SLIM_SUBAGENTS,
                    subagent_models=subagent_models or None,
                    subagent_mcp_allow=config.subagent_mcp_allow,
                    subagent_skills=config.subagent_skills,
                    compile_kwargs=compile_kwargs,
                )

            from sarma_cli.engine.audit_graph import build_audit_graph
            from sarma_cli.engine.audit_subagents import AUDIT_SUBAGENTS

            return build_audit_graph(
                model=model,
                tools=tools,
                system_prompt=config.system_prompt or "",
                subagent_specs=AUDIT_SUBAGENTS,
                subagent_models=subagent_models or None,
                subagent_mcp_allow=config.subagent_mcp_allow,
                subagent_skills=config.subagent_skills,
                compile_kwargs=compile_kwargs,
            )

        if config.mode == "ruflo":
            from langchain.agents import create_agent
            from sarma_cli.engine.ruflo import build_delegate_tool, build_ruflo_prompt

            system_prompt = build_ruflo_prompt(config.system_prompt or "")
            ruflo_tools = [*tools, build_delegate_tool(model, tools)]
            agent_kwargs = (
                self._runtime_services.create_agent_kwargs()
                if self._runtime_services is not None
                else {}
            )
            return create_agent(
                model,
                ruflo_tools,
                system_prompt=system_prompt,
                middleware=build_agent_middleware_for_model(model),
                **agent_kwargs,
            )

        from langchain.agents import create_agent

        system_prompt = config.system_prompt or ""
        agent_kwargs = (
            self._runtime_services.create_agent_kwargs()
            if self._runtime_services is not None
            else {}
        )
        return create_agent(
            model,
            tools,
            system_prompt=system_prompt,
            middleware=build_agent_middleware_for_model(model),
            **agent_kwargs,
        )

    def _agent_cache_key(
        self,
        config: AgentRunConfig,
        server_configs: dict[str, dict[str, Any]],
        tools: list[Any],
    ) -> str:
        data = {
            "mode": config.mode,
            "provider": _provider_key(config.provider),
            "skill": _skill_key(config.skill),
            "servers": server_configs,
            "tools": [getattr(tool, "name", repr(tool)) for tool in tools],
            "system_prompt": config.system_prompt or "",
            "subagent_providers": {
                name: _provider_key(provider)
                for name, provider in sorted(config.subagent_providers.items())
            },
            "subagent_mcp_allow": {
                name: None if allow is None else sorted(allow)
                for name, allow in sorted(config.subagent_mcp_allow.items())
            },
            "subagent_skills": {
                name: _skill_key(skill)
                for name, skill in sorted(config.subagent_skills.items())
            },
            "rag": _rag_key(config.rag),
        }
        return json.dumps(data, sort_keys=True, default=str)

    def _init_model(self, provider: Any, skill: ResolvedSkill | None) -> Any:
        """Initialize a LangChain language model based on api_mode."""
        return self._model_factory.init_model(provider, skill)

    def _apply_skill_filter(
        self,
        tools: list[Any],
        skill: ResolvedSkill | None,
    ) -> list[Any]:
        """Filter tools based on skill allow/deny lists."""
        if skill is None:
            return list(tools)
        return list(
            self._pool.filter_tools(
                tools,
                allowlist=skill.tool_allowlist,
                denylist=skill.tool_denylist,
            )
        )

    def _load_subagent_models(self, providers: dict[str, Any]) -> dict[str, Any]:
        models: dict[str, Any] = {}
        for name, provider in providers.items():
            models[name] = self._init_model(provider, None)
        return models

    def _build_builtin_tools(self, config: AgentRunConfig) -> list[Any]:
        tools = [
            build_web_search_tool(),
            build_http_exchange_tool(),
            build_packet_exchange_tool(),
        ]
        if any(kb.enabled and kb.name for kb in config.rag.knowledge_bases):
            tools.append(build_rag_search_tool(config.rag))
        return tools
