"""Agent construction and streaming execution for chat turns.

Uses deepagents v0.6+ subgraph streaming (``subgraphs=True, version="v2"``)
so that every token / tool call / result is attributable to either the
orchestrator or a named subagent (recon, decompile, vuln_hunt, cross_ref,
reporter).  The :class:`EventTranslator` resolves namespace tuples into
human-readable subagent names and emits :class:`StreamEvent` instances with
a ``subagent`` field on every payload.
"""

from __future__ import annotations

from typing import Any, AsyncIterator

from app.chat.agent_factory import AgentFactory
from app.chat.mcp_pool import McpClientPool
from app.chat.models import AgentRunConfig, ChatMessage, ResolvedSkill, StreamEvent, resolve_skill
from app.chat.streaming import EventTranslator


class AgentRunner:
    """Build a LangGraph agent, run it with streaming, and yield events."""

    def __init__(
        self,
        factory: AgentFactory,
        pool: McpClientPool,
        provider_dict: dict[str, Any],
        servers_list: list[dict[str, Any]],
        skill_dict: dict[str, Any] | None,
        history: list[ChatMessage],
        system_prompt: str,
        conversation_id: str,
        turn_id: str,
    ) -> None:
        self._factory = factory
        self._pool = pool
        self._provider_dict = provider_dict
        self._servers_list = servers_list
        self._skill_dict = skill_dict
        self._history = history
        self._system_prompt = system_prompt
        self._conversation_id = conversation_id
        self._turn_id = turn_id
        self.assistant_content = ""
        self.reasoning_content = ""
        self.tool_calls: list[StreamEvent] = []
        self.run_config: AgentRunConfig | None = None

    async def run(self, message: str) -> AsyncIterator[StreamEvent]:
        provider = self._parse_provider(self._provider_dict)
        skill = self._parse_skill(self._skill_dict)
        servers = self._parse_servers(self._servers_list)
        self.run_config = AgentRunConfig(
            conversation_id=self._conversation_id,
            provider=provider,
            skill=skill,
            enabled_servers=servers,
            message_history=self._history,
            user_message=message,
            system_prompt=self._system_prompt,
        )

        agent, _tools = await self._factory.build(self.run_config)
        input_messages = self._build_input_messages(self._history, message)

        translator = EventTranslator(self._conversation_id, self._turn_id)

        async for chunk in agent.astream(
            {"messages": input_messages},
            stream_mode=["messages", "updates", "custom"],
            subgraphs=True,
            version="v2",
            config={"recursion_limit": self.run_config.max_steps},
        ):
            self._accumulate_reasoning(chunk)

            for stream_event in translator.translate(chunk):
                self._accumulate_event(stream_event)
                yield stream_event

    def _accumulate_reasoning(self, chunk: Any) -> None:
        """Extract reasoning_content from chunk in v2 subgraph format.

        chunk is a dict: {"type": "messages"|"updates", "ns": (...), "data": ...}
        For type="messages", data is (msg, metadata).
        """
        if not isinstance(chunk, dict):
            return
        if chunk.get("type") != "messages":
            return
        data = chunk.get("data")
        if not isinstance(data, tuple) or len(data) < 2:
            return
        msg = data[0]
        if msg is None:
            return
        reasoning_content = getattr(msg, "reasoning_content", None)
        if not reasoning_content and hasattr(msg, "additional_kwargs"):
            reasoning_content = msg.additional_kwargs.get("reasoning_content")
        if reasoning_content and isinstance(reasoning_content, str):
            self.reasoning_content += reasoning_content

    def _accumulate_event(self, stream_event: StreamEvent) -> None:
        if stream_event.type == "token":
            chunk = stream_event.payload.get("content", "")
            if isinstance(chunk, list):
                parts = []
                for block in chunk:
                    if isinstance(block, str):
                        parts.append(block)
                    elif isinstance(block, dict) and block.get("type") == "text":
                        parts.append(block.get("text", ""))
                chunk = "".join(parts)
            if chunk:
                self.assistant_content += chunk
        elif stream_event.type == "tool_start":
            self.tool_calls.append(stream_event)

    @staticmethod
    def _build_input_messages(
        history: list[ChatMessage], user_message: str
    ) -> list[Any]:
        from langchain_core.messages import HumanMessage

        messages: list[Any] = [msg.to_langchain_message() for msg in history]
        messages.append(HumanMessage(content=user_message))
        return messages

    @staticmethod
    def _parse_provider(data: dict[str, Any]) -> Any:
        from shared.dto import ModelProviderDTO
        return ModelProviderDTO(**{k: v for k, v in data.items() if k in ModelProviderDTO.__dataclass_fields__})

    @staticmethod
    def _parse_skill(data: dict[str, Any] | None) -> ResolvedSkill | None:
        return resolve_skill(data)

    @staticmethod
    def _parse_servers(data_list: list[dict[str, Any]]) -> list[Any]:
        from shared.dto import McpServerDTO
        return [McpServerDTO(**{k: v for k, v in d.items() if k in McpServerDTO.__dataclass_fields__}) for d in data_list]
