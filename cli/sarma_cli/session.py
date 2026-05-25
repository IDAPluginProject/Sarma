"""Audit session lifecycle — wraps IDE agent runtime for CLI use."""

from __future__ import annotations

import uuid
from typing import Any, AsyncIterator

from app.chat.agent_factory import AgentFactory
from app.chat.agent_runner import AgentRunner
from app.chat.mcp_pool import McpClientPool
from app.chat.models import ChatMessage, ResolvedSkill, StreamEvent
from app.chat.prompts import build_system_prompt
from shared.enums import StreamEventType

from sarma_cli.config import CliConfig
from sarma_cli.store import Store

_AUDIT_SKILL = ResolvedSkill(
    id=None,
    name="vuln-audit-workflow",
    system_prompt_suffix="",
    tool_allowlist=None,
    tool_denylist=None,
    preferred_model_name=None,
    temperature_override=None,
)

_AUDIT_SKILL_DICT: dict[str, Any] = {
    "id": None,
    "name": "vuln-audit-workflow",
    "system_prompt_template": "",
    "tool_allowlist_json": None,
    "tool_denylist_json": None,
    "model_override": None,
    "temperature_override": None,
}


class AuditSession:
    """Manages a single audit conversation with the LangGraph pipeline."""

    def __init__(self, config: CliConfig, store: Store) -> None:
        self._config = config
        self._store = store
        self._pool = McpClientPool()
        self._factory = AgentFactory(self._pool)
        self._conversation_id: str = ""
        self._history: list[ChatMessage] = []
        self._graph_state: dict[str, Any] = {
            "current_stage": "",
            "completed": set(),
            "failed": None,
            "gapfill_loops": 0,
            "feedback_loops": 0,
        }

    @property
    def graph_state(self) -> dict[str, Any]:
        return dict(self._graph_state)

    @property
    def conversation_id(self) -> str:
        return self._conversation_id

    @property
    def pool(self) -> McpClientPool:
        return self._pool

    @property
    def tool_count(self) -> int:
        return len(self._pool.tools)

    def new_conversation(self, title: str = "") -> str:
        self._conversation_id = self._store.create_conversation(
            title=title or "Audit session",
            model_name=self._config.provider.model_name,
        )
        self._history.clear()
        self._graph_state = {
            "current_stage": "",
            "completed": set(),
            "failed": None,
            "gapfill_loops": 0,
            "feedback_loops": 0,
        }
        return self._conversation_id

    def resume_conversation(self, cid: str) -> bool:
        messages = self._store.load_messages(cid)
        if not messages:
            return False
        self._conversation_id = cid
        self._history = [
            ChatMessage(
                id=m["id"],
                conversation_id=cid,
                turn_id=m["turn_id"],
                role=m["role"],
                content=m["content"],
                reasoning_content=m.get("reasoning"),
            )
            for m in messages
        ]
        return True

    async def run_turn(self, user_message: str) -> AsyncIterator[StreamEvent]:
        """Execute one audit turn, yielding StreamEvents."""
        if not self._conversation_id:
            self.new_conversation(title=user_message[:60])

        turn_id = uuid.uuid4().hex[:12]
        system_prompt = build_system_prompt(skill=_AUDIT_SKILL)

        # Persist user message
        self._store.save_message(
            self._conversation_id, turn_id, "user", user_message
        )
        self._history.append(ChatMessage(
            role="user", content=user_message,
            conversation_id=self._conversation_id, turn_id=turn_id,
        ))

        runner = AgentRunner(
            factory=self._factory,
            pool=self._pool,
            provider_dict=self._config.provider_dict,
            servers_list=self._config.mcp_server_dicts,
            skill_dict=_AUDIT_SKILL_DICT,
            history=self._history,
            system_prompt=system_prompt,
            conversation_id=self._conversation_id,
            turn_id=turn_id,
        )

        async for event in runner.run(user_message):
            self._track_graph_progress(event)
            yield event

        # Persist assistant response
        if runner.assistant_content:
            self._store.save_message(
                self._conversation_id, turn_id, "assistant",
                runner.assistant_content, reasoning=runner.reasoning_content or None,
            )
            self._history.append(ChatMessage(
                role="assistant", content=runner.assistant_content,
                conversation_id=self._conversation_id, turn_id=turn_id,
                reasoning_content=runner.reasoning_content or None,
            ))
            self._store.update_conversation(
                self._conversation_id, status="idle",
                title=user_message[:60] if not self._history else None,
            )

    def _track_graph_progress(self, event: StreamEvent) -> None:
        """Update graph state from subagent lifecycle events."""
        etype = event.type
        payload = event.payload

        if etype == StreamEventType.SUBAGENT_START:
            name = payload.get("subagent", "")
            if name:
                self._graph_state["current_stage"] = name

        elif etype == StreamEventType.SUBAGENT_COMPLETE:
            name = payload.get("subagent", "")
            if name:
                self._graph_state["completed"].add(name)
                if name == self._graph_state.get("current_stage"):
                    self._graph_state["current_stage"] = ""

        elif etype == StreamEventType.SUBAGENT_ERROR:
            name = payload.get("subagent", "")
            if name:
                self._graph_state["failed"] = name

    async def close(self) -> None:
        await self._pool.disconnect()
