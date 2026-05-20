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
from app.chat.errors import AgentBuildError, AgentRunError, McpConnectionError
from app.chat.mcp_pool import McpClientPool
from app.chat.models import Conversation, StreamEvent
from app.chat.persistence import ChatPersistence
from app.chat.streaming import (
    make_run_completed_event,
    make_run_failed_event,
)
from app.chat.turn_executor import TurnExecutor, TurnRequest
from shared.database import DatabaseStore
from shared.enums import StreamEventType

logger = logging.getLogger(__name__)


def _uid() -> str:
    return uuid.uuid4().hex[:12]


class ChatServiceWorker(QObject):
    """QThread shell: owns the asyncio event loop, delegates turn logic."""

    event_received = Signal(dict)
    conversation_updated = Signal(dict)

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
        self._turn_lock: asyncio.Lock | None = None
        self._stop_event: asyncio.Event | None = None

    # ------------------------------------------------------------------
    # QThread lifecycle
    # ------------------------------------------------------------------

    def start_loop(self) -> None:
        """Called when the hosting QThread starts. Runs the asyncio loop."""
        self._running = True
        self._loop = asyncio.new_event_loop()
        self._turn_lock = asyncio.Lock()
        self._stop_event = asyncio.Event()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._run_forever())
        finally:
            self._loop.close()
            self._loop = None
            self._running = False

    async def _run_forever(self) -> None:
        """Keep the event loop alive until stop_loop() signals shutdown."""
        await self._stop_event.wait()

    def stop_loop(self) -> None:
        """Signal the loop to stop."""
        self._running = False
        if self._stop_event and self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._stop_event.set)

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
            logger.warning("submit_message called before event loop started, message dropped")
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
        """Run one agent turn via TurnExecutor."""
        async with self._turn_lock:
            turn_id = _uid()
            cancel_event = asyncio.Event()
            self._active_turn = turn_id
            self._cancel_event = cancel_event

            request = TurnRequest(
                conversation_id=conversation_id,
                turn_id=turn_id,
                user_message=user_message,
                provider_dict=provider_dict,
                skill_dict=skill_dict,
                mcp_server_dicts=mcp_server_dicts,
                message_history_dicts=message_history_dicts,
            )
            executor = TurnExecutor(
                self._persistence, self._pool, self._factory
            )

            try:
                async for event in executor.execute(request):
                    if cancel_event.is_set():
                        self._cancel_turn(
                            conversation_id, turn_id,
                            executor.assistant_content,
                        )
                        break
                    self._emit(event)
                else:
                    self._emit(
                        make_run_completed_event(
                            conversation_id, turn_id,
                            executor.assistant_content,
                        )
                    )
                    executor.finalize_success(request)

            except McpConnectionError as exc:
                logger.error("MCP connection failed: %s", exc)
                error_detail = str(exc)
                if (
                    "ConnectError" in error_detail
                    or "connection attempts failed" in error_detail
                ):
                    error_text = (
                        f"MCP 连接失败：无法连接到 {exc.server_name}，"
                        "请确认服务已启动。"
                    )
                else:
                    error_text = error_detail.splitlines()[0]
                self._fail_turn(
                    conversation_id, turn_id, error_text,
                    executor.assistant_content,
                )

            except AgentBuildError as exc:
                logger.error("Agent build failed: %s", exc)
                self._fail_turn(
                    conversation_id, turn_id, str(exc),
                    executor.assistant_content,
                )

            except AgentRunError as exc:
                logger.error(
                    "Agent run failed (recoverable=%s): %s",
                    exc.recoverable, exc,
                )
                self._fail_turn(
                    conversation_id, turn_id, str(exc),
                    executor.assistant_content,
                )

            except Exception as exc:
                logger.exception("Unexpected error during agent run")
                error_text = str(exc)
                if exc.__class__.__name__ == "GraphRecursionError":
                    max_steps = 100_000
                    if executor.run_config is not None:
                        max_steps = executor.run_config.max_steps
                    error_text = (
                        f"Agent stopped after reaching the step limit "
                        f"({max_steps}). Try asking a narrower question "
                        "or increase the agent step limit."
                    )
                self._fail_turn(
                    conversation_id, turn_id, error_text,
                    executor.assistant_content,
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

    def _fail_turn(
        self,
        conversation_id: str,
        turn_id: str,
        error_text: str,
        partial_content: str = "",
    ) -> None:
        """Emit a run_failed event and mark the conversation as failed."""
        self._emit(
            make_run_failed_event(
                conversation_id, turn_id, error_text, partial_content
            )
        )
        self._persistence.update_conversation_by_pk(
            conversation_id, status="failed"
        )

    def _cancel_turn(
        self,
        conversation_id: str,
        turn_id: str,
        partial_content: str = "",
    ) -> None:
        """Handle user-initiated cancellation: emit run_failed but set idle."""
        self._emit(
            make_run_failed_event(
                conversation_id, turn_id, "Cancelled by user", partial_content
            )
        )
        self._persistence.update_conversation_by_pk(
            conversation_id, status="idle"
        )


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
        loop = self._loop()
        if self._worker and loop:
            future = asyncio.run_coroutine_threadsafe(
                self._worker.shutdown(), loop
            )
            try:
                future.result(timeout=2.0)
            except Exception:
                pass
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
        mode: str = "audit",
    ) -> Conversation:
        """Create a new conversation and persist it."""
        persistence = self.get_persistence()
        conv = Conversation(
            provider_id=provider_id,
            model_name_snapshot=model_name,
            skill_id=skill_id,
            mode=mode,
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
