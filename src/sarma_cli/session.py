"""Session lifecycle — wraps IDE agent runtime for CLI use.

Workflow-aware: reads the current workflow from the registry on each turn
to determine execution mode (chat vs audit pipeline).
"""

from __future__ import annotations

import uuid
from typing import Any, AsyncIterator

from sarma_cli.engine.agent_factory import AgentFactory
from sarma_cli.engine.agent_runner import AgentRunner
from sarma_cli.engine.mcp_pool import McpClientPool
from sarma_cli.engine.models import ChatMessage, StreamEvent, resolve_skill
from sarma_cli.engine.prompts import build_system_prompt
from sarma_cli.engine.enums import StreamEventType

from sarma_cli.config import CliConfig
from sarma_cli.store import Store

_AUDIT_SKILL_DICT: dict[str, Any] = {
    "id": None,
    "name": "vuln-audit-workflow",
    "system_prompt_template": "",
    "tool_allowlist_json": None,
    "tool_denylist_json": None,
    "model_override": None,
    "temperature_override": None,
}


class Session:
    """Manages a conversation with the LangGraph agent pipeline.

    Workflow-aware: reads the current workflow from the registry on each
    turn to determine execution mode. Switching /workflow takes effect on
    the next turn — no session restart needed.
    """

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
        from sarma_cli.workflows import get_registry
        mode = get_registry().current_name()
        self._conversation_id = self._store.create_conversation(
            title=title or f"{mode.title()} session",
            model_name=self._config.provider.model_name,
        )
        self._history.clear()
        self._reset_graph_state()
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
        """Execute one turn, yielding StreamEvents.

        Reads the current workflow from the registry to determine execution
        mode. Switching /workflow changes what runs on the next turn.
        """
        from sarma_cli.workflows import get_registry

        if not self._conversation_id:
            self.new_conversation(title=user_message[:60])

        # Determine mode from current workflow
        registry = get_registry()
        current_wf = registry.current()
        mode = current_wf.name if current_wf else "chat"

        turn_id = uuid.uuid4().hex[:12]

        # Audit modes use the built-in audit skill; chat mode loads any
        # skills configured in [agent].skills (model + MCP servers come from
        # the provider/agent config).
        if mode in ("audit", "audit-slim"):
            skill_dict = _AUDIT_SKILL_DICT
        else:
            from sarma_cli.skills import load_skills
            skill_dict = load_skills(self._config.agent.skills)
        skill = resolve_skill(skill_dict)
        system_prompt = build_system_prompt(skill=skill, mode=mode)

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
            servers_list=self._config.agent_mcp_server_dicts,
            skill_dict=skill_dict,
            history=self._history,
            system_prompt=system_prompt,
            conversation_id=self._conversation_id,
            turn_id=turn_id,
            mode=mode,
        )

        async for event in runner.run(user_message):
            if mode in ("audit", "audit-slim"):
                self._track_graph_progress(event)
            yield event

        # Persist assistant response
        if runner.assistant_content:
            self._store.save_message(
                self._conversation_id, turn_id, "assistant",
                runner.assistant_content,
                reasoning=runner.reasoning_content or None,
            )
            self._history.append(ChatMessage(
                role="assistant", content=runner.assistant_content,
                conversation_id=self._conversation_id, turn_id=turn_id,
                reasoning_content=runner.reasoning_content or None,
            ))
            update_fields: dict[str, Any] = {"status": "idle"}
            # Set a title from the first user message only if none was set yet.
            existing = self._store.get_conversation(self._conversation_id)
            if existing is not None and not (existing.get("title") or "").strip():
                update_fields["title"] = user_message[:60] or "Untitled session"
            self._store.update_conversation(self._conversation_id, **update_fields)

    def _reset_graph_state(self) -> None:
        self._graph_state = {
            "current_stage": "",
            "completed": set(),
            "failed": None,
            "gapfill_loops": 0,
            "feedback_loops": 0,
        }

    def _track_graph_progress(self, event: StreamEvent) -> None:
        """Update graph state from subagent lifecycle events (audit mode only)."""
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
