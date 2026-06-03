"""LangGraph ReAct Agent factory."""

from __future__ import annotations

import json
import logging
from typing import Any

from sarma_cli.engine.errors import AgentBuildError, ProviderNotConfiguredError
from sarma_cli.engine.mcp_pool import McpClientPool
from sarma_cli.engine.models import AgentRunConfig, ResolvedSkill

logger = logging.getLogger(__name__)


def _extract_reasoning_content(data: Any) -> str | None:
    """Return provider-specific reasoning_content from OpenAI-like payloads."""
    if not isinstance(data, dict):
        return None

    value = data.get("reasoning_content")
    if not isinstance(value, str):
        value = data.get("reasoning")
    if isinstance(value, str):
        return value

    extra = data.get("model_extra")
    if isinstance(extra, dict):
        value = extra.get("reasoning_content") or extra.get("reasoning")
        if isinstance(value, str):
            return value

    return None


class ReasoningChatOpenAIMixin:
    """Preserve reasoning_content for OpenAI-compatible thinking models.

    Several OpenAI-compatible providers return a non-standard
    ``reasoning_content`` field and require it to be sent back when a tool call
    is followed by another model call.  LangChain's generic ChatOpenAI drops
    that field, so we patch both streaming/non-streaming reads and request
    serialization here.
    """

    def _create_chat_result(
        self, response: Any, generation_info: dict[str, Any] | None = None
    ) -> Any:
        result = super()._create_chat_result(response, generation_info)
        if isinstance(response, dict):
            response_dict = response
        elif hasattr(response, "model_dump"):
            response_dict = response.model_dump(exclude_none=False)
        else:
            response_dict = response.dict()
        choices = response_dict.get("choices") or []
        for index, choice in enumerate(choices):
            if index >= len(result.generations):
                break
            rc = _extract_reasoning_content(choice.get("message", {}))
            if rc is not None:
                result.generations[index].message.additional_kwargs[
                    "reasoning_content"
                ] = rc
        return result

    def _convert_chunk_to_generation_chunk(
        self,
        chunk: dict[str, Any],
        default_chunk_class: type,
        base_generation_info: dict[str, Any] | None,
    ) -> Any:
        generation_chunk = super()._convert_chunk_to_generation_chunk(
            chunk, default_chunk_class, base_generation_info
        )
        if generation_chunk is None:
            return None

        choices = chunk.get("choices") or chunk.get("chunk", {}).get("choices", [])
        first_choice = choices[0] if choices and isinstance(choices[0], dict) else {}
        if first_choice:
            rc = _extract_reasoning_content(first_choice.get("delta", {}))
            if rc is not None:
                generation_chunk.message.additional_kwargs[
                    "reasoning_content"
                ] = rc
        return generation_chunk

    def _get_request_payload(
        self, input_: Any, *, stop: list[str] | None = None, **kwargs: Any
    ) -> dict[str, Any]:
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)
        msg_dicts = payload.get("messages")
        if not isinstance(msg_dicts, list):
            return payload

        from langchain_core.messages import AIMessage, HumanMessage

        messages = self._convert_input(input_).to_messages()

        last_user_idx = -1
        for idx, msg in enumerate(messages):
            if isinstance(msg, HumanMessage):
                last_user_idx = idx

        for idx, (orig, msg_dict) in enumerate(zip(messages, msg_dicts)):
            if idx >= len(messages) or idx >= len(msg_dicts):
                break
            if not isinstance(orig, AIMessage) or not isinstance(msg_dict, dict):
                continue
            rc = orig.additional_kwargs.get("reasoning_content")
            if rc is not None and idx > last_user_idx:
                msg_dict["reasoning_content"] = rc
            else:
                msg_dict.pop("reasoning_content", None)
        return payload


def _reasoning_chat_openai_class() -> type:
    from langchain_openai import ChatOpenAI

    class ReasoningChatOpenAI(ReasoningChatOpenAIMixin, ChatOpenAI):
        pass

    return ReasoningChatOpenAI


def _build_openai_model(
    *,
    model_name: str,
    api_key: str,
    base_url: str,
    temperature: float,
    top_p: float,
) -> Any:
    ReasoningChatOpenAI = _reasoning_chat_openai_class()

    kwargs: dict[str, Any] = {
        "model": model_name,
        "temperature": temperature,
        "top_p": top_p,
    }
    if api_key:
        kwargs["api_key"] = api_key
    if base_url:
        kwargs["base_url"] = base_url
    return ReasoningChatOpenAI(**kwargs)


def _build_openai_responses_model(
    *,
    model_name: str,
    api_key: str,
    base_url: str,
    temperature: float,
    top_p: float,
) -> Any:
    ReasoningChatOpenAI = _reasoning_chat_openai_class()

    kwargs: dict[str, Any] = {
        "model": model_name,
        "temperature": temperature,
        "top_p": top_p,
        "use_responses_api": True,
        "output_version": "responses/v1",
    }
    if api_key:
        kwargs["api_key"] = api_key
    if base_url:
        kwargs["base_url"] = base_url
    return ReasoningChatOpenAI(**kwargs)


def _build_anthropic_model(
    *,
    model_name: str,
    api_key: str,
    base_url: str,
    temperature: float,
    top_p: float,
) -> Any:
    from langchain_anthropic import ChatAnthropic

    kwargs: dict[str, Any] = {
        "model": model_name,
        "temperature": temperature,
        "top_p": top_p,
    }
    if api_key:
        kwargs["api_key"] = api_key
    if base_url:
        kwargs["base_url"] = base_url
    return ChatAnthropic(**kwargs)


# Maps api_mode → builder function.
_MODEL_BUILDERS: dict[str, Any] = {
    "openai_responses": _build_openai_responses_model,
    "openai_compatible": _build_openai_model,
    "anthropic": _build_anthropic_model,
}


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


class AgentFactory:
    """Builds a LangGraph agent from runtime configuration."""

    def __init__(
        self, pool: McpClientPool, workspace_path: str = ""
    ) -> None:
        self._pool = pool
        self._workspace_path = workspace_path
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

        # 3. Apply skill tool filter
        tools = self._apply_skill_filter(all_tools, config.skill)

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
            )

        if config.mode == "ruflo":
            from langgraph.prebuilt import create_react_agent
            from sarma_cli.engine.ruflo import build_delegate_tool, build_ruflo_prompt

            system_prompt = build_ruflo_prompt(config.system_prompt or "")
            ruflo_tools = [*tools, build_delegate_tool(model, tools)]
            return create_react_agent(
                model, ruflo_tools, prompt=system_prompt
            )

        from langgraph.prebuilt import create_react_agent

        system_prompt = config.system_prompt or ""
        return create_react_agent(
            model, tools, prompt=system_prompt
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
        }
        return json.dumps(data, sort_keys=True, default=str)

    def _init_model(self, provider: Any, skill: ResolvedSkill | None) -> Any:
        """Initialize a LangChain language model based on api_mode."""
        api_mode = provider.api_mode
        builder = _MODEL_BUILDERS.get(api_mode)
        if builder is None:
            raise ProviderNotConfiguredError(
                f"Unsupported api_mode: {api_mode!r}"
            )

        model_name = (
            skill.preferred_model_name
            if skill and skill.preferred_model_name
            else provider.model_name
        )

        temperature = provider.temperature
        if skill and skill.temperature_override is not None:
            temperature = skill.temperature_override

        return builder(
            model_name=model_name,
            api_key=provider.api_key,
            base_url=provider.base_url,
            temperature=temperature,
            top_p=provider.top_p,
        )

    def _apply_skill_filter(
        self,
        tools: list[Any],
        skill: ResolvedSkill | None,
    ) -> list[Any]:
        """Filter tools based on skill allow/deny lists."""
        if skill is None:
            return tools
        return self._pool.filter_tools(
            tools,
            allowlist=skill.tool_allowlist,
            denylist=skill.tool_denylist,
        )

    def _load_subagent_models(self, providers: dict[str, Any]) -> dict[str, Any]:
        models: dict[str, Any] = {}
        for name, provider in providers.items():
            models[name] = self._init_model(provider, None)
        return models
