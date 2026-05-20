"""LangGraph ReAct Agent factory."""

from __future__ import annotations

import logging
from typing import Any

from app.chat.errors import AgentBuildError, ProviderNotConfiguredError
from app.chat.mcp_pool import McpClientPool
from app.chat.models import AgentRunConfig, ResolvedSkill

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


class AgentFactory:
    """Builds a deepagents agent from runtime configuration."""

    def __init__(
        self, pool: McpClientPool, workspace_path: str = ""
    ) -> None:
        self._pool = pool
        self._workspace_path = workspace_path

    async def build(
        self, config: AgentRunConfig
    ) -> tuple[Any, list[Any]]:
        """Build and return (compiled_graph, tools).

        Args:
            config: Full run configuration.

        Returns:
            Tuple of (compiled deepagents agent, list of LangChain tools).

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
            logger.warning(
                "No tools available after filtering. "
                "Agent will run without tool access."
            )

        # 4. Initialize LLM
        try:
            model = self._init_model(provider, config.skill)
        except Exception as exc:
            raise AgentBuildError(
                f"Failed to initialize model: {exc}"
            ) from exc

        # 5. Build agent — use audit pipeline only when skill requests it,
        #    otherwise build a simple ReAct agent.
        try:
            use_audit_pipeline = (
                config.skill is not None
                and config.skill.name
                and "audit" in config.skill.name.lower()
            )

            if use_audit_pipeline:
                from deepagents import create_deep_agent
                from app.chat.audit_subagents import (
                    build_runtime_subagents,
                    get_orchestrator_prompt,
                )

                orch_prompt = get_orchestrator_prompt()
                if config.system_prompt:
                    system_prompt = config.system_prompt + "\n\n" + orch_prompt
                else:
                    system_prompt = orch_prompt

                subagent_models = self._load_subagent_models(provider)
                orch_model = subagent_models.pop("orchestrator", None) or model

                kwargs: dict[str, Any] = {
                    "model": orch_model,
                    "tools": tools,
                    "system_prompt": system_prompt,
                    "subagents": build_runtime_subagents(
                        tools, subagent_models=subagent_models or None
                    ),
                }
                if self._workspace_path:
                    from deepagents.backends import LocalShellBackend

                    kwargs["backend"] = LocalShellBackend(
                        root_dir=self._workspace_path
                    )
                agent = create_deep_agent(**kwargs)
            else:
                from langgraph.prebuilt import create_react_agent

                system_prompt = config.system_prompt or ""
                agent = create_react_agent(
                    model, tools, prompt=system_prompt
                )
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

        return agent, tools

    def _init_model(self, provider: Any, skill: ResolvedSkill | None) -> Any:
        """Initialize a langchain chat model directly based on api_mode."""
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

    def _load_subagent_models(self, default_provider: Any) -> dict[str, Any]:
        """Load per-agent model assignments from the database.

        Returns a dict mapping agent_name → initialized BaseChatModel.
        Only agents with a non-null provider_id are included.
        """
        try:
            from shared.database import DatabaseStore
            from shared.paths import get_ide_user_config_root

            db = DatabaseStore()
            rows = db.load_rows("audit_agent_models")
            if not rows:
                return {}

            providers_by_id: dict[int, dict] = {}
            for p in db.load_rows("model_providers"):
                providers_by_id[p["id"]] = p

            models: dict[str, Any] = {}
            for row in rows:
                pid = row.get("provider_id")
                if not pid:
                    continue
                provider_row = providers_by_id.get(pid)
                if not provider_row:
                    continue
                agent_name = row.get("agent_name", "")
                api_mode = provider_row.get("api_mode", "openai_compatible")
                builder = _MODEL_BUILDERS.get(api_mode)
                if not builder:
                    continue
                models[agent_name] = builder(
                    model_name=provider_row.get("model_name", ""),
                    api_key=provider_row.get("api_key", ""),
                    base_url=provider_row.get("base_url", ""),
                    temperature=float(provider_row.get("temperature", 0.7)),
                    top_p=float(provider_row.get("top_p", 1.0)),
                )
            return models
        except Exception as exc:
            logger.warning("Failed to load subagent models: %s", exc)
            return {}
