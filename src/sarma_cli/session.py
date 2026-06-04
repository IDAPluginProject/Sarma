"""Session lifecycle — wraps IDE agent runtime for CLI use.

Workflow-aware: reads the current workflow from the registry on each turn
to determine execution mode (ruflo vs audit pipeline).
"""

from __future__ import annotations

import uuid
from typing import Any, AsyncIterator

from sarma_cli.engine.agent_factory import AgentFactory
from sarma_cli.engine.agent_runner import AgentRunner
from sarma_cli.engine.mcp_pool import McpClientPool
from sarma_cli.engine.models import ConversationMessage, StreamEvent
from sarma_cli.engine.enums import StreamEventType
from sarma_cli.context.compaction import (
    STRUCTURED_MEMORY_PROMPT,
    ContextCompactor,
    ContextWindowPolicy,
    estimate_static_prompt_tokens,
)

from sarma_cli.config import CliConfig
from sarma_cli.runtime.resolver import RuntimePolicyResolver
from sarma_cli.store import Store


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
        self._resolver = RuntimePolicyResolver(config)
        self._conversation_id: str = ""
        self._history: list[ConversationMessage] = []
        self._graph_state: dict[str, Any] = {
            "current_stage": "",
            "completed": set(),
            "failed": None,
            "gapfill_loops": 0,
            "feedback_loops": 0,
        }
        self._compact_trigger_ratio = 0.90
        self._compact_target_ratio = 0.55

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

    async def ensure_mcp_connected(self, workflow: str) -> None:
        """Connect the runtime MCP pool for the given workflow without building an agent."""
        run_plan = self._resolver.resolve(workflow)
        server_configs = {
            server.name: server.to_langchain_config()
            for server in run_plan.enabled_servers
        }
        await self._pool.connect(server_configs)

    async def restart_runtime(self) -> None:
        """Rebuild runtime resources while preserving conversation history."""
        await self._pool.disconnect()
        self._pool = McpClientPool()
        self._factory = AgentFactory(self._pool)
        self._resolver = RuntimePolicyResolver(self._config)
        self._reset_graph_state()

    def new_conversation(self, title: str = "") -> str:
        from sarma_cli.workflows import get_registry
        mode = get_registry().current_name()
        provider = self._resolver.provider_for(mode or "ruflo")
        self._conversation_id = self._store.create_conversation(
            title=title or f"{mode.title()} session",
            model_name=provider.model_name,
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
            ConversationMessage(
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

    async def compact_context(
        self,
        *,
        force: bool = True,
        workflow: str = "ruflo",
        upcoming_text: str = "",
        system_prompt: str = "",
    ) -> bool:
        """Compact history into structured memory near the context limit."""
        compactor = self._compactor_for_workflow(
            workflow,
            system_prompt=system_prompt,
        )
        changed, new_history, memory = await compactor.compact(
            self._history,
            lambda messages: self._summarize_messages(messages, workflow=workflow),
            conversation_id=self._conversation_id,
            upcoming_text=upcoming_text,
            force=force,
        )
        if not changed:
            return False

        source_count = len(self._history) - (len(new_history) - 1)
        self._history = new_history
        if self._conversation_id:
            self._store.save_memory_artifact(
                self._conversation_id,
                memory,
                source_count=max(source_count, 0),
            )
            self._store.replace_messages(self._conversation_id, self._history)
        return True

    async def run_turn(self, user_message: str) -> AsyncIterator[StreamEvent]:
        """Execute one turn, yielding StreamEvents.

        Reads the current workflow from the registry to determine execution
        mode. Switching /workflow changes what runs on the next turn.
        """
        from sarma_cli.workflows import get_registry

        # Determine mode from current workflow
        registry = get_registry()
        current_wf = registry.current()
        mode = current_wf.name if current_wf else "ruflo"
        if not self._conversation_id:
            self.new_conversation(title=user_message[:60])

        turn_id = uuid.uuid4().hex[:12]
        run_plan = self._resolver.resolve(mode)

        await self.compact_context(
            force=False,
            workflow=mode,
            upcoming_text=user_message,
            system_prompt=run_plan.system_prompt,
        )

        runner_history = list(self._history)

        # Persist user message
        self._store.save_message(
            self._conversation_id, turn_id, "user", user_message
        )
        self._history.append(ConversationMessage(
            role="user", content=user_message,
            conversation_id=self._conversation_id, turn_id=turn_id,
        ))

        runner = AgentRunner(
            factory=self._factory,
            pool=self._pool,
            provider=run_plan.provider,
            enabled_servers=run_plan.enabled_servers,
            skill=run_plan.skill,
            history=runner_history,
            system_prompt=run_plan.system_prompt,
            conversation_id=self._conversation_id,
            turn_id=turn_id,
            mode=mode,
            subagent_providers=run_plan.subagent_providers,
            subagent_mcp_allow=run_plan.subagent_mcp_allow,
            subagent_skills=run_plan.subagent_skills,
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
            self._history.append(ConversationMessage(
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

    def _should_compact(self, budget: int, *, upcoming_text: str = "") -> bool:
        compactor = ContextCompactor(ContextWindowPolicy(
            max_context_tokens=budget,
            trigger_ratio=self._compact_trigger_ratio,
            raw_tail_ratio=self._compact_target_ratio,
        ))
        return compactor.plan(
            self._history,
            upcoming_text=upcoming_text,
        ).should_compact

    def _context_budget(self, workflow: str) -> int:
        provider = self._resolver.provider_for(workflow)
        return max(int(provider.max_context_tokens or 128_000), 1)

    def _split_for_compaction(
        self,
        budget: int,
    ) -> tuple[list[ConversationMessage], list[ConversationMessage]]:
        return ContextCompactor(ContextWindowPolicy(
            max_context_tokens=budget,
            trigger_ratio=self._compact_trigger_ratio,
            raw_tail_ratio=self._compact_target_ratio,
        )).split_raw_tail(self._history)

    def _estimate_history_tokens(self, messages: list[ConversationMessage]) -> int:
        return ContextCompactor(ContextWindowPolicy(
            max_context_tokens=128_000,
        )).estimate_history_tokens(messages)

    @staticmethod
    def _estimate_message_tokens(message: ConversationMessage) -> int:
        return ContextCompactor.estimate_message_tokens(message)

    @staticmethod
    def _estimate_text_tokens(text: str) -> int:
        return ContextCompactor.estimate_text_tokens(text)

    def _compactor_for_workflow(
        self,
        workflow: str,
        *,
        system_prompt: str = "",
    ) -> ContextCompactor:
        return ContextCompactor(ContextWindowPolicy(
            max_context_tokens=self._context_budget(workflow),
            trigger_ratio=self._compact_trigger_ratio,
            raw_tail_ratio=self._compact_target_ratio,
            static_prompt_tokens=estimate_static_prompt_tokens(
                system_prompt,
                self.tool_count,
            ),
        ))

    async def _summarize_messages(
        self,
        messages: list[ConversationMessage],
        *,
        workflow: str = "ruflo",
    ) -> str:
        from langchain_core.messages import HumanMessage, SystemMessage

        provider = self._resolver.provider_for(workflow)
        model = self._factory._init_model(provider, None)
        transcript = "\n\n".join(
            f"{message.role.upper()}: {message.content}"
            for message in messages
            if message.content
        )
        result = await model.ainvoke([
            SystemMessage(content=STRUCTURED_MEMORY_PROMPT),
            HumanMessage(content=transcript),
        ])
        return str(getattr(result, "content", "") or "")

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

        elif etype == StreamEventType.CUSTOM_PROGRESS:
            data = payload.get("data", {})
            if isinstance(data, dict) and data.get("type") == "audit_route":
                loop = data.get("loop", "")
                count = data.get("count")
                if loop == "gapfill" and count is not None:
                    self._graph_state["gapfill_loops"] = int(count)
                elif loop == "feedback" and count is not None:
                    self._graph_state["feedback_loops"] = int(count)

    async def close(self) -> None:
        await self._pool.disconnect()
