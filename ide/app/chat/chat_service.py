"""Chat service — QThread + asyncio orchestration for the agent runtime.

The ChatService runs in a QThread with its own asyncio event loop.
The UI communicates via Qt signals/slots.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from PySide6.QtCore import QObject, Signal, QThread

from app.chat.agent_factory import AgentFactory
from app.chat.errors import AgentBuildError, AgentRunError
from app.chat.mcp_pool import McpClientPool
from app.chat.models import (
    AgentRunConfig,
    ChatMessage,
    Conversation,
    ResolvedSkill,
    StreamEvent,
)
from app.chat.persistence import ChatPersistence
from app.chat.prompts import build_system_prompt
from app.chat.streaming import (
    make_run_completed_event,
    make_run_failed_event,
    make_run_started_event,
    normalize_langgraph_events,
)
from shared.database import DatabaseStore

logger = logging.getLogger(__name__)


def _uid() -> str:
    return uuid.uuid4().hex[:12]


class ChatServiceWorker(QObject):
    """Runs inside a QThread, owns the asyncio event loop and agent runtime."""

    # Signals emitted to the UI thread
    event_received = Signal(dict)  # StreamEvent.to_dict()
    conversation_updated = Signal(dict)  # Conversation.to_dict()

    def __init__(
        self, db: DatabaseStore, workspace_path: str = ""
    ) -> None:
        super().__init__()
        self._db = db
        self._persistence = ChatPersistence(db)
        self._pool = McpClientPool()
        self._factory = AgentFactory(self._pool, workspace_path=workspace_path)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._running = False
        self._active_turn: str | None = None
        self._cancel_event: asyncio.Event | None = None

    # ------------------------------------------------------------------
    # QThread lifecycle
    # ------------------------------------------------------------------

    def start_loop(self) -> None:
        """Called when the hosting QThread starts. Runs the asyncio loop."""
        self._running = True
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._run_forever())
        finally:
            self._loop.close()
            self._loop = None
            self._running = False

    async def _run_forever(self) -> None:
        """Keep the event loop alive to process submitted coroutines."""
        while self._running:
            await asyncio.sleep(0.1)

    def stop_loop(self) -> None:
        """Signal the loop to stop."""
        self._running = False
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._running.__class__.__bool__, False)

    # ------------------------------------------------------------------
    # Public methods (called from UI thread via QMetaObject.invokeMethod
    # or queued connection)
    # ------------------------------------------------------------------

    def submit_message(
        self,
        conversation_id: str,
        user_message: str,
        provider: dict[str, Any],
        skill: dict[str, Any] | None,
        mcp_servers: list[dict[str, Any]],
        message_history: list[dict[str, Any]],
    ) -> None:
        """Submit a user message for agent processing.

        Thread-safe: schedules work on the asyncio loop.
        """
        if self._loop is None:
            return

        asyncio.run_coroutine_threadsafe(
            self._handle_message(
                conversation_id=conversation_id,
                user_message=user_message,
                provider_dict=provider,
                skill_dict=skill,
                mcp_server_dicts=mcp_servers,
                message_history_dicts=message_history,
            ),
            self._loop,
        )

    def cancel_turn(self) -> None:
        """Cancel the active agent turn."""
        if self._cancel_event and self._loop:
            self._loop.call_soon_threadsafe(self._cancel_event.set)

    async def shutdown(self) -> None:
        """Clean shutdown of all resources."""
        self._running = False
        await self._pool.disconnect()

    # ------------------------------------------------------------------
    # Core agent execution
    # ------------------------------------------------------------------

    async def _handle_message(
        self,
        conversation_id: str,
        user_message: str,
        provider_dict: dict[str, Any],
        skill_dict: dict[str, Any] | None,
        mcp_server_dicts: list[dict[str, Any]],
        message_history_dicts: list[dict[str, Any]],
    ) -> None:
        """Run one agent turn: build agent, stream response, persist."""
        turn_id = _uid()
        self._active_turn = turn_id
        self._cancel_event = asyncio.Event()

        # Emit run_started
        self._emit(make_run_started_event(conversation_id, turn_id))

        # Parse inputs
        provider = self._parse_provider(provider_dict)
        skill = self._parse_skill(skill_dict)
        servers = self._parse_servers(mcp_server_dicts)
        history = [ChatMessage.from_dict(d) for d in message_history_dicts]

        # Save user message
        user_msg = ChatMessage(
            conversation_id=conversation_id,
            turn_id=turn_id,
            role="user",
            content=user_message,
        )
        self._persistence.save_message(user_msg)

        # Build system prompt
        system_prompt = build_system_prompt(
            skill=skill,
            override=None,
        )

        # Update conversation status
        self._persistence.update_conversation_by_pk(
            conversation_id, status="running"
        )

        # Build run config
        run_config = AgentRunConfig(
            conversation_id=conversation_id,
            provider=provider,
            skill=skill,
            enabled_servers=servers,
            message_history=history,
            user_message=user_message,
            system_prompt=system_prompt,
        )

        # Accumulate assistant content and reasoning content (thinking-mode LLMs)
        assistant_content = ""
        reasoning_content = ""

        # Track tool calls for persistence (tool_call_id → ChatMessage).
        # Using tool_call_id (unique per invocation) instead of tool_name
        # avoids data loss when the same tool is called multiple times.
        pending_tool_msgs: dict[str, ChatMessage] = {}

        try:
            # Build agent
            agent, _tools = await self._factory.build(run_config)

            # Prepare input messages for LangGraph
            input_messages = self._build_input_messages(
                history,
                user_message,
                max_context_tokens=provider.max_context_tokens,
            )

            # Stream agent execution
            async for event_bundle in agent.astream(
                {"messages": input_messages},
                stream_mode=["messages", "updates"],
                config={"recursion_limit": run_config.max_steps},
            ):
                # Check cancellation
                if self._cancel_event.is_set():
                    self._emit(
                        make_run_failed_event(
                            conversation_id,
                            turn_id,
                            "Cancelled by user",
                            partial_content=assistant_content,
                        )
                    )
                    break

                # event_bundle from multi-mode stream is (mode, data)
                if not isinstance(event_bundle, tuple) or len(event_bundle) < 2:
                    continue

                mode, data = event_bundle[0], event_bundle[1]

                # Extract reasoning_content from thinking-mode LLMs (DeepSeek-R1 etc.)
                if mode == "messages":
                    msg = data[0] if isinstance(data, tuple) and len(data) > 0 else None
                    if msg is not None:
                        rc = getattr(msg, "reasoning_content", None)
                        if not rc and hasattr(msg, "additional_kwargs"):
                            rc = msg.additional_kwargs.get("reasoning_content")
                        if rc and isinstance(rc, str):
                            reasoning_content += rc

                stream_events = normalize_langgraph_events(
                    mode, data, conversation_id, turn_id
                )
                for stream_event in stream_events:
                    # Accumulate tokens
                    if stream_event.type == "token":
                        chunk = stream_event.payload.get("content", "")
                        if isinstance(chunk, list):
                            # Safety: join list blocks into a string
                            parts = []
                            for b in chunk:
                                if isinstance(b, str):
                                    parts.append(b)
                                elif isinstance(b, dict) and b.get("type") == "text":
                                    parts.append(b.get("text", ""))
                            chunk = "".join(parts)
                        if chunk:
                            assistant_content += chunk

                    elif stream_event.type == "tool_start":
                        # Flush accumulated assistant text as a segment before
                        # the tool message, so DB order is correct on reload.
                        if assistant_content:
                            seg_msg = ChatMessage(
                                conversation_id=conversation_id,
                                turn_id=turn_id,
                                role="assistant",
                                content=assistant_content,
                                reasoning_content=reasoning_content or None,
                            )
                            self._persistence.save_message(seg_msg)
                            assistant_content = ""
                            reasoning_content = ""

                        # Persist tool call start
                        tool_name = stream_event.payload.get("tool_name", "")
                        tool_call_id = stream_event.payload.get("tool_call_id", "")
                        args = stream_event.payload.get("args", {})
                        try:
                            import json as _json
                            args_json = _json.dumps(args, ensure_ascii=False)
                        except (TypeError, ValueError):
                            args_json = str(args)
                        tool_msg = ChatMessage(
                            conversation_id=conversation_id,
                            turn_id=turn_id,
                            role="tool",
                            content=args_json,
                            tool_name=tool_name,
                            tool_call_id=tool_call_id,
                        )
                        self._persistence.save_message(tool_msg)
                        # Use tool_call_id as key — unique per invocation,
                        # unlike tool_name which collides on repeated calls.
                        pending_tool_msgs[tool_call_id or tool_name] = tool_msg

                    elif stream_event.type in ("tool_result", "tool_error"):
                        # Update persisted tool message with result
                        tool_call_id = stream_event.payload.get("tool_call_id", "")
                        tool_name = stream_event.payload.get("tool_name", "")
                        key = tool_call_id or tool_name
                        result = stream_event.payload.get("result", "")
                        error = stream_event.payload.get("error", "")
                        combined = result or error or ""
                        if key in pending_tool_msgs:
                            # Update the existing message with the result
                            msg_id = pending_tool_msgs[key].id
                            old_content = pending_tool_msgs[key].content or ""
                            try:
                                import json as _json
                                combined_data = {
                                    "args": _json.loads(old_content),
                                    "result": combined,
                                }
                                new_content = _json.dumps(combined_data, ensure_ascii=False)
                            except (ValueError, TypeError, _json.JSONDecodeError):
                                new_content = f"Args: {old_content}\nResult: {combined}"
                            self._persistence.update_message_content(msg_id, new_content)
                            del pending_tool_msgs[key]

                    self._emit(stream_event)

            else:
                # Normal completion (no break from cancel)
                self._emit(
                    make_run_completed_event(
                        conversation_id, turn_id, assistant_content
                    )
                )

                # Save assistant message
                assistant_msg = ChatMessage(
                    conversation_id=conversation_id,
                    turn_id=turn_id,
                    role="assistant",
                    content=assistant_content,
                    reasoning_content=reasoning_content or None,
                )
                self._persistence.save_message(assistant_msg)

                # Update conversation
                updates: dict[str, Any] = {
                    "status": "idle",
                    "updated_at": ChatMessage().created_at,
                }
                inferred = self._infer_title(user_message, assistant_content)
                if inferred:
                    updates["title"] = inferred
                self._persistence.update_conversation_by_pk(
                    conversation_id,
                    **updates,
                )

        except AgentBuildError as exc:
            logger.error("Agent build failed: %s", exc)
            self._emit(
                make_run_failed_event(
                    conversation_id, turn_id, str(exc), assistant_content
                )
            )
            self._persistence.update_conversation_by_pk(
                conversation_id, status="failed"
            )

        except Exception as exc:
            logger.exception("Unexpected error during agent run")
            error_text = str(exc)
            if exc.__class__.__name__ == "GraphRecursionError":
                error_text = (
                    f"Agent stopped after reaching the step limit "
                    f"({run_config.max_steps}). Try asking a narrower question "
                    "or increase the agent step limit."
                )
            self._emit(
                make_run_failed_event(
                    conversation_id, turn_id, error_text, assistant_content
                )
            )
            self._persistence.update_conversation_by_pk(
                conversation_id, status="failed"
            )

        finally:
            self._active_turn = None
            self._cancel_event = None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _emit(self, event: StreamEvent) -> None:
        """Emit a StreamEvent to the UI thread."""
        self.event_received.emit(event.to_dict())

    @staticmethod
    def _parse_provider(data: dict[str, Any]) -> Any:
        """Parse provider dict into a ModelProvider-like object."""
        from supervisor.models import ModelProvider

        return ModelProvider.from_dict(data)

    @staticmethod
    def _parse_skill(data: dict[str, Any] | None) -> ResolvedSkill | None:
        """Parse skill dict into a ResolvedSkill."""
        if not data:
            return None

        import json

        allowlist = None
        denylist = None

        allow_json = data.get("tool_allowlist_json")
        if allow_json:
            try:
                allowlist = set(json.loads(allow_json))
            except (json.JSONDecodeError, TypeError):
                pass

        deny_json = data.get("tool_denylist_json")
        if deny_json:
            try:
                denylist = set(json.loads(deny_json))
            except (json.JSONDecodeError, TypeError):
                pass

        return ResolvedSkill(
            id=data.get("id"),
            name=data.get("name", ""),
            system_prompt_suffix=data.get("system_prompt_template", ""),
            tool_allowlist=allowlist,
            tool_denylist=denylist,
            preferred_model_name=data.get("model_override") or None,
            temperature_override=data.get("temperature_override"),
        )

    @staticmethod
    def _parse_servers(data_list: list[dict[str, Any]]) -> list[Any]:
        """Parse server dicts into McpServerEntry-like objects."""
        from supervisor.models import McpServerEntry

        return [McpServerEntry.from_dict(d) for d in data_list]

    @staticmethod
    def _build_input_messages(
        history: list[ChatMessage],
        user_message: str,
        max_context_tokens: int = 0,
    ) -> list[Any]:
        """Build langchain-compatible message list from history + new message."""
        from langchain_core.messages import HumanMessage, SystemMessage

        messages: list[Any] = []
        compacted_summary, history = ChatServiceWorker._compact_history(
            history, user_message, max_context_tokens
        )

        if compacted_summary:
            messages.append(SystemMessage(content=compacted_summary))

        for msg in history:
            messages.append(msg.to_langchain_message())

        messages.append(HumanMessage(content=user_message))
        return messages

    @staticmethod
    def _compact_history(
        history: list[ChatMessage],
        user_message: str,
        max_context_tokens: int,
    ) -> tuple[str | None, list[ChatMessage]]:
        """Keep recent history within the configured context budget.

        ``max_context_tokens <= 0`` means no compaction.  Token counting is an
        intentionally conservative approximation so this works without
        provider-specific tokenizers.
        """
        if max_context_tokens <= 0 or not history:
            return None, history

        # Leave room for the system prompt, tool schemas, model output, and
        # tokenizer variance.  The retained chat history gets the rest.
        budget = max(512, int(max_context_tokens * 0.55))
        used = ChatServiceWorker._estimate_text_tokens(user_message) + 8
        kept: list[ChatMessage] = []
        omitted: list[ChatMessage] = []

        for msg in reversed(history):
            cost = ChatServiceWorker._estimate_message_tokens(msg)
            if used + cost > budget:
                omitted.append(msg)
                continue
            kept.append(msg)
            used += cost

        kept.reverse()
        omitted.reverse()

        # Avoid replaying orphan tool messages if compaction cut off the
        # corresponding assistant tool-call request.
        while kept and kept[0].role == "tool":
            omitted.append(kept.pop(0))

        if not omitted:
            return None, kept

        summary = ChatServiceWorker._build_compaction_summary(omitted)
        return summary, kept

    @staticmethod
    def _estimate_message_tokens(msg: ChatMessage) -> int:
        text = msg.content or ""
        if msg.reasoning_content:
            text += "\n" + msg.reasoning_content
        if msg.tool_name:
            text += "\n" + msg.tool_name
        return ChatServiceWorker._estimate_text_tokens(text) + 8

    @staticmethod
    def _estimate_text_tokens(text: str) -> int:
        return max(1, (len(text) + 3) // 4)

    @staticmethod
    def _build_compaction_summary(messages: list[ChatMessage]) -> str:
        lines = [
            "Earlier conversation was compacted to fit the model context.",
            "Use this summary as background; ask for details if needed.",
        ]
        char_budget = 3000
        used = sum(len(line) for line in lines)
        for msg in messages:
            role = msg.role
            if msg.tool_name:
                role = f"{role}:{msg.tool_name}"
            content = " ".join((msg.content or "").split())
            if not content:
                continue
            line = f"- {role}: {content[:400]}"
            if used + len(line) > char_budget:
                lines.append("- ... additional older messages omitted ...")
                break
            lines.append(line)
            used += len(line)
        return "\n".join(lines)

    @staticmethod
    def _infer_title(user_message: str, assistant_content: str) -> str:
        """Infer a conversation title from the first exchange."""
        # Take first line of user message, truncated
        first_line = user_message.strip().split("\n")[0]
        if len(first_line) > 60:
            first_line = first_line[:57] + "..."
        return first_line


class ChatService(QObject):
    """UI-facing chat service. Owns the worker thread.

    Usage:
        service = ChatService(db)
        service.start()
        service.send_message(...)
        service.stop()
    """

    event_received = Signal(dict)
    conversation_updated = Signal(dict)

    def __init__(
        self,
        db: DatabaseStore | None = None,
        workspace_path: str = "",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._db = db or DatabaseStore()
        self._workspace_path = workspace_path
        self._thread: QThread | None = None
        self._worker: ChatServiceWorker | None = None

    @property
    def is_running(self) -> bool:
        return (
            self._thread is not None
            and self._thread.isRunning()
        )

    def start(self) -> None:
        """Start the worker thread."""
        if self.is_running:
            return

        self._thread = QThread(self)
        self._worker = ChatServiceWorker(
            self._db, workspace_path=self._workspace_path
        )
        self._worker.moveToThread(self._thread)

        # Wire signals
        self._worker.event_received.connect(self.event_received.emit)
        self._worker.conversation_updated.connect(
            self.conversation_updated.emit
        )

        # Start the asyncio loop when thread starts
        self._thread.started.connect(self._worker.start_loop)
        self._thread.start()

    def stop(self) -> None:
        """Stop the worker thread cleanly."""
        if self._worker and self._loop():
            asyncio.run_coroutine_threadsafe(
                self._worker.shutdown(), self._loop()
            )
        if self._worker:
            self._worker.stop_loop()
        if self._thread:
            self._thread.quit()
            self._thread.wait(3000)
            self._thread = None
        self._worker = None

    def _loop(self) -> asyncio.AbstractEventLoop | None:
        if self._worker:
            return self._worker._loop
        return None

    # ------------------------------------------------------------------
    # Persistence helpers (run on UI thread, SQLite is fast enough)
    # ------------------------------------------------------------------

    def get_persistence(self) -> ChatPersistence:
        return ChatPersistence(self._db)

    def create_conversation(
        self,
        provider_id: int | None = None,
        model_name: str = "",
        skill_id: int | None = None,
    ) -> Conversation:
        """Create a new conversation and persist it."""
        persistence = self.get_persistence()
        conv = Conversation(
            provider_id=provider_id,
            model_name_snapshot=model_name,
            skill_id=skill_id,
        )
        persistence.create_conversation(conv)
        return conv

    # ------------------------------------------------------------------
    # Message submission
    # ------------------------------------------------------------------

    def send_message(
        self,
        conversation_id: str,
        user_message: str,
        provider: dict[str, Any],
        skill: dict[str, Any] | None = None,
        mcp_servers: list[dict[str, Any]] | None = None,
        message_history: list[dict[str, Any]] | None = None,
    ) -> None:
        """Submit a user message to the agent.

        Args:
            conversation_id: Active conversation.
            user_message: User's text input.
            provider: ModelProvider.to_dict().
            skill: Skill config dict or None.
            mcp_servers: List of enabled McpServerEntry.to_dict().
            message_history: List of ChatMessage.to_dict() for context.
        """
        if not self._worker:
            logger.warning("ChatService not started, cannot send message")
            return

        self._worker.submit_message(
            conversation_id=conversation_id,
            user_message=user_message,
            provider=provider,
            skill=skill,
            mcp_servers=mcp_servers or [],
            message_history=message_history or [],
        )

    def cancel_turn(self) -> None:
        """Cancel the active agent turn."""
        if self._worker:
            self._worker.cancel_turn()
