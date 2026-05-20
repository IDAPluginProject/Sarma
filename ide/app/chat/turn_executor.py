"""Single-turn agent execution: parse → compact → build → stream → persist."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, AsyncIterator

from app.chat.agent_factory import AgentFactory
from app.chat.agent_runner import AgentRunner
from app.chat.history_compactor import HistoryCompactor
from app.chat.mcp_pool import McpClientPool
from app.chat.message_persister import MessagePersister
from app.chat.models import ChatMessage, ResolvedSkill, StreamEvent, resolve_skill
from app.chat.persistence import ChatPersistence
from app.chat.prompts import build_system_prompt
from app.chat.streaming import make_run_started_event
from shared.enums import StreamEventType

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class TurnRequest:
    """All inputs needed to execute one agent turn."""

    conversation_id: str
    turn_id: str
    user_message: str
    provider_dict: dict[str, Any]
    skill_dict: dict[str, Any] | None
    mcp_server_dicts: list[dict[str, Any]]
    message_history_dicts: list[dict[str, Any]]


class TurnExecutor:
    """Execute a single agent turn: build -> stream -> persist.

    Pure async logic with no Qt dependency. Yields StreamEvents that the
    caller (ChatServiceWorker) forwards to the UI via signals.
    """

    def __init__(
        self,
        persistence: ChatPersistence,
        pool: McpClientPool,
        factory: AgentFactory,
    ) -> None:
        self._persistence = persistence
        self._pool = pool
        self._factory = factory
        self.assistant_content: str = ""
        self.reasoning_content: str = ""
        self.run_config: Any = None

    async def execute(self, request: TurnRequest) -> AsyncIterator[StreamEvent]:
        """Yield StreamEvents for one complete turn.

        The caller is responsible for cancellation checks and signal emission.
        On normal completion the caller should call ``finalize_success()``.
        """
        yield make_run_started_event(request.conversation_id, request.turn_id)

        provider = self._parse_provider(request.provider_dict)
        skill = self._parse_skill(request.skill_dict)
        history = [ChatMessage.from_dict(d) for d in request.message_history_dicts]
        history = HistoryCompactor(
            self._persistence, provider.max_context_tokens
        ).compact(request.conversation_id, history)

        persister = MessagePersister(self._persistence)
        persister.save_user_message(
            request.conversation_id, request.turn_id, request.user_message
        )

        conv = self._persistence.get_conversation(request.conversation_id)
        prompt_override = conv.system_prompt_override if conv else None
        system_prompt = build_system_prompt(skill=skill, override=prompt_override)

        self._persistence.update_conversation_by_pk(
            request.conversation_id, status="running"
        )

        runner = AgentRunner(
            factory=self._factory,
            pool=self._pool,
            provider_dict=request.provider_dict,
            servers_list=request.mcp_server_dicts,
            skill_dict=request.skill_dict,
            history=history,
            system_prompt=system_prompt,
            conversation_id=request.conversation_id,
            turn_id=request.turn_id,
        )

        async for stream_event in runner.run(request.user_message):
            if stream_event.type == StreamEventType.TOOL_START and runner.assistant_content:
                persister.save_assistant_message(
                    request.conversation_id,
                    request.turn_id,
                    runner.assistant_content,
                    runner.reasoning_content or None,
                )
                runner.assistant_content = ""
                runner.reasoning_content = ""

            if stream_event.type in (
                StreamEventType.TOOL_START,
                StreamEventType.TOOL_RESULT,
                StreamEventType.TOOL_ERROR,
            ):
                persister.save_tool_execution(stream_event)

            yield stream_event

        self.assistant_content = runner.assistant_content
        self.reasoning_content = runner.reasoning_content
        self.run_config = runner.run_config

    def finalize_success(self, request: TurnRequest) -> None:
        """Persist final assistant message and mark conversation idle."""
        persister = MessagePersister(self._persistence)
        persister.save_assistant_message(
            request.conversation_id,
            request.turn_id,
            self.assistant_content,
            self.reasoning_content or None,
        )
        updates: dict[str, Any] = {
            "status": "idle",
            "updated_at": ChatMessage().created_at,
        }
        title = self._infer_title(request.user_message)
        if title:
            updates["title"] = title
        self._persistence.update_conversation_by_pk(
            request.conversation_id, **updates
        )

    @staticmethod
    def _parse_provider(data: dict[str, Any]) -> Any:
        from shared.dto import ModelProviderDTO
        return ModelProviderDTO(**{
            k: v for k, v in data.items()
            if k in ModelProviderDTO.__dataclass_fields__
        })

    @staticmethod
    def _parse_skill(data: dict[str, Any] | None) -> ResolvedSkill | None:
        return resolve_skill(data)

    @staticmethod
    def _infer_title(user_message: str) -> str:
        first_line = user_message.strip().split("\n")[0]
        if len(first_line) > 60:
            first_line = first_line[:57] + "..."
        return first_line
