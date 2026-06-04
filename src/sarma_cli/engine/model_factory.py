"""Language model construction for Sarma runtimes."""

from __future__ import annotations

from typing import Any

from sarma_cli.engine.errors import ProviderNotConfiguredError
from sarma_cli.engine.models import ResolvedSkill


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
    """Preserve reasoning_content for OpenAI-compatible thinking models."""

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


_MODEL_BUILDERS: dict[str, Any] = {
    "openai_responses": _build_openai_responses_model,
    "openai_compatible": _build_openai_model,
    "anthropic": _build_anthropic_model,
}


class ModelFactory:
    """Build provider-backed LangChain chat models."""

    def init_model(self, provider: Any, skill: ResolvedSkill | None = None) -> Any:
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
