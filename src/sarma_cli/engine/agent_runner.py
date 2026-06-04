"""Agent construction and streaming execution for Ruflo and audit turns.

For audit-mode runs, uses LangGraph subgraph streaming
(``subgraphs=True, version="v2"``) so that every token / tool call /
result is attributable to either the orchestrator or a named subagent.
The :class:`EventTranslator` resolves namespace tuples into subagent
names and emits :class:`StreamEvent` instances with a ``subagent``
field on every payload.

For Ruflo, uses a primary LangGraph ReAct agent with controlled delegation.
"""

from __future__ import annotations

import logging
from typing import Any, AsyncIterator

from sarma_cli.engine.agent_factory import AgentFactory
from sarma_cli.engine.dto import McpServerDTO, ModelProviderDTO
from sarma_cli.engine.errors import AgentRunError
from sarma_cli.engine.mcp_pool import McpClientPool
from sarma_cli.engine.models import (
    AgentRunConfig,
    ConversationMessage,
    ResolvedSkill,
    StreamEvent,
)
from sarma_cli.engine.streaming import EventTranslator
from sarma_cli.engine.enums import StreamEventType

logger = logging.getLogger(__name__)


class AgentRunner:
    """Build a LangGraph agent, run it with streaming, and yield events."""

    def __init__(
        self,
        factory: AgentFactory,
        pool: McpClientPool,
        provider: ModelProviderDTO,
        enabled_servers: list[McpServerDTO],
        skill: ResolvedSkill | None,
        history: list[ConversationMessage],
        system_prompt: str,
        conversation_id: str,
        turn_id: str,
        mode: str = "audit",
        subagent_providers: dict[str, ModelProviderDTO] | None = None,
        subagent_mcp_allow: dict[str, list[str] | None] | None = None,
        subagent_skills: dict[str, ResolvedSkill | None] | None = None,
    ) -> None:
        self._factory = factory
        self._pool = pool
        self._provider = provider
        self._enabled_servers = enabled_servers
        self._skill = skill
        self._history = history
        self._system_prompt = system_prompt
        self._conversation_id = conversation_id
        self._turn_id = turn_id
        self._mode = mode
        self._subagent_providers = subagent_providers or {}
        self._subagent_mcp_allow = subagent_mcp_allow or {}
        self._subagent_skills = subagent_skills or {}
        self.assistant_content = ""
        self.reasoning_content = ""
        self.tool_calls: list[StreamEvent] = []
        self.run_config: AgentRunConfig | None = None

    async def run(self, message: str) -> AsyncIterator[StreamEvent]:
        self.run_config = AgentRunConfig(
            conversation_id=self._conversation_id,
            provider=self._provider,
            skill=self._skill,
            enabled_servers=self._enabled_servers,
            message_history=self._history,
            user_message=message,
            system_prompt=self._system_prompt,
            mode=self._mode,
            subagent_providers=self._subagent_providers,
            subagent_mcp_allow=self._subagent_mcp_allow,
            subagent_skills=self._subagent_skills,
        )

        agent, _tools = await self._factory.build(self.run_config)
        input_messages = self._build_input_messages(self._history, message)
        graph_input = self._build_graph_input(input_messages, message, self._mode)

        translator = EventTranslator(self._conversation_id, self._turn_id)

        try:
            async for chunk in agent.astream(
                graph_input,
                stream_mode=["messages", "updates", "custom"],
                subgraphs=True,
                version="v2",
                config={"recursion_limit": self.run_config.max_steps},
            ):
                self._accumulate_reasoning(chunk)

                for stream_event in translator.translate(chunk):
                    self._accumulate_event(stream_event)
                    yield stream_event
        except AgentRunError:
            raise
        except Exception as exc:
            logger.error("Agent execution failed: %s", exc, exc_info=True)
            raise AgentRunError(
                str(exc), recoverable=not isinstance(exc, (KeyboardInterrupt, SystemExit))
            ) from exc

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
        if stream_event.type == StreamEventType.TOKEN:
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
        elif stream_event.type == StreamEventType.TOOL_START:
            self.tool_calls.append(stream_event)

    @staticmethod
    def _build_input_messages(
        history: list[ConversationMessage], user_message: str
    ) -> list[Any]:
        from langchain_core.messages import HumanMessage

        messages: list[Any] = [msg.to_langchain_message() for msg in history]
        messages.append(HumanMessage(content=user_message))
        return messages

    @staticmethod
    def _build_graph_input(
        messages: list[Any],
        user_message: str,
        mode: str,
    ) -> dict[str, Any]:
        graph_input: dict[str, Any] = {"messages": messages}
        if mode in ("audit", "audit-slim"):
            graph_input["audit_task"] = user_message
            graph_input["stage_outputs"] = {}
            graph_input["gapfill_count"] = 0
            graph_input["feedback_count"] = 0
            graph_input["current_stage"] = ""
        return graph_input
