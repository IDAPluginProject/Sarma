"""Chat page — sidebar + workflow DAG + role panel + message list + composer.

Layout
======

::

    QSplitter (Horizontal)
    ├── SessionSidebar  (left, hidden by default; toggle via ≡ button)
    └── QVBoxLayout (center)
        ├── Toggle row (≡ button)
        ├── QSplitter (Vertical) – main area
        │   ├── QSplitter (Horizontal) – workflow row (~260 px)
        │   │   ├── WorkflowDagView       (left, flex)
        │   │   └── ActivityList           (right, 280 px)
        │   ├── QSplitter (Horizontal) – messages row (flex)
        │   │   ├── RolePanel              (left, 170 px)
        │   │   └── MessageList            (right, flex)
        │   └── Composer (bottom, prototype-style border)
        └── (end)

Tool-call cards no longer appear in the message list — they live in the
activity panel alongside the workflow DAG.  Token events are routed to
the message list with a ``subagent`` annotation so the role-panel filter
can show / hide blocks by agent.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from app.chat.chat_service import ChatService
from app.chat.persistence import ChatPersistence
from app.presenters.chat_presenter import ChatPresenter, MessageViewModel
from app.ui.chat.composer import Composer
from app.ui.chat.message_list import MessageList
from app.ui.chat.provider_selector import ProviderSelector
from app.ui.chat.role_panel import RolePanel
from app.services.supervisor_client import SupervisorClient
from app.ui.chat.session_sidebar import SessionSidebar
from app.ui.chat.workflow_view import WorkflowDagView, _ActivityList

if TYPE_CHECKING:
    from app.i18n import I18n

logger = logging.getLogger(__name__)


class ChatPage(QWidget):
    """Main Chat page widget."""

    conversation_created = Signal(str)  # conversation_id

    def __init__(
        self,
        i18n: I18n,
        supervisor_client: SupervisorClient | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("chatPage")

        self._i18n = i18n
        self._supervisor_client: SupervisorClient | None = supervisor_client
        self._presenter = ChatPresenter(supervisor_client)
        self._chat_service: ChatService | None = None
        self._persistence: ChatPersistence | None = None
        self._current_conversation_id: str | None = None
        self._current_provider_id: int | None = None
        self._current_skill_id: int | None = None
        self._is_running: bool = False
        self._current_assistant_content: str = ""

        self._build_ui()

    def _t(self, key: str, **kwargs: object) -> str:
        return self._i18n.t(key, **kwargs)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Horizontal splitter: sidebar | center
        self._h_splitter = QSplitter(Qt.Orientation.Horizontal)
        self._h_splitter.setChildrenCollapsible(True)
        self._h_splitter.setHandleWidth(1)

        # --- Session sidebar (left, collapsed by default) ---
        self._sidebar = SessionSidebar(self._i18n)
        self._sidebar.conversation_selected.connect(self._on_conversation_selected)
        self._sidebar.new_conversation_requested.connect(self._on_new_conversation)
        self._sidebar.conversation_deleted.connect(self._on_conversation_deleted)
        self._sidebar.hide()
        self._h_splitter.addWidget(self._sidebar)

        # --- Center: vertical stack ---
        center = QWidget()
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(0)

        # Toggle row
        toggle_row = QWidget()
        toggle_layout = QHBoxLayout(toggle_row)
        toggle_layout.setContentsMargins(8, 6, 8, 2)
        toggle_layout.setSpacing(0)
        self._sidebar_toggle = QPushButton("≡")
        self._sidebar_toggle.setObjectName("sidebarToggleButton")
        self._sidebar_toggle.setCheckable(True)
        self._sidebar_toggle.setFixedSize(28, 24)
        self._sidebar_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self._sidebar_toggle.setToolTip(self._t("chat.session.title"))
        self._sidebar_toggle.toggled.connect(self._on_sidebar_toggled)
        toggle_layout.addWidget(self._sidebar_toggle)
        toggle_layout.addStretch(1)
        center_layout.addWidget(toggle_row)

        # --- Main vertical splitter ---
        self._v_splitter = QSplitter(Qt.Orientation.Vertical)
        self._v_splitter.setChildrenCollapsible(False)
        self._v_splitter.setHandleWidth(1)

        # ---- 1. Workflow row (DAG fills full width) ----
        self._workflow_view = WorkflowDagView(self._i18n)
        self._v_splitter.addWidget(self._workflow_view)

        # ---- 2. Messages row: RolePanel | MessageList | Activity ----
        messages_row = QSplitter(Qt.Orientation.Horizontal)
        messages_row.setHandleWidth(1)

        self._role_panel = RolePanel(self._i18n)
        self._role_panel.setMinimumWidth(160)
        self._role_panel.setMaximumWidth(200)
        self._role_panel.role_selected.connect(self._on_role_selected)
        messages_row.addWidget(self._role_panel)

        self._message_list = MessageList()
        messages_row.addWidget(self._message_list)

        # Activity panel (MCP / Skills) on the right
        activity_wrapper = QWidget()
        activity_wrapper.setObjectName("activityWrapper")
        aw_layout = QVBoxLayout(activity_wrapper)
        aw_layout.setContentsMargins(0, 0, 0, 0)
        aw_layout.setSpacing(0)
        activity_title = QLabel(self._t("chat.activity.title", default="MCP / Skills"))
        activity_title.setObjectName("activityTitle")
        aw_layout.addWidget(activity_title)
        self._activity_list = _ActivityList()
        self._workflow_view.attach_activity_list(self._activity_list)
        aw_layout.addWidget(self._activity_list, 1)
        self._activity_wrapper = activity_wrapper
        messages_row.addWidget(activity_wrapper)

        messages_row.setSizes([170, 600, 280])
        messages_row.setStretchFactor(0, 0)
        messages_row.setStretchFactor(1, 1)
        messages_row.setStretchFactor(2, 0)
        self._v_splitter.addWidget(messages_row)

        # ---- 3. Composer ----
        self._composer = Composer(self._i18n)
        self._composer.set_prototype_style(True)
        self._composer.message_submitted.connect(self._on_message_submitted)
        self._composer.stop_requested.connect(self._on_stop_requested)
        self._composer.clear_requested.connect(self._on_clear_requested)

        self._provider_selector = ProviderSelector(self._i18n)
        self._provider_selector.provider_changed.connect(self._on_provider_changed)
        self._composer.add_selector(self._provider_selector)
        self._v_splitter.addWidget(self._composer)

        # Initial sizes: workflow half, messages half, composer compact
        self._v_splitter.setSizes([350, 350, 120])
        self._v_splitter.setStretchFactor(0, 1)  # workflow row
        self._v_splitter.setStretchFactor(1, 1)  # messages row
        self._v_splitter.setStretchFactor(2, 0)  # composer

        center_layout.addWidget(self._v_splitter, 1)
        self._h_splitter.addWidget(center)
        self._h_splitter.setSizes([0, 1220])
        self._h_splitter.setStretchFactor(0, 0)
        self._h_splitter.setStretchFactor(1, 1)

        layout.addWidget(self._h_splitter, 1)

        self._refresh_models()
        self._refresh_skills()

    # ------------------------------------------------------------------
    # Sidebar toggle
    # ------------------------------------------------------------------

    def _on_sidebar_toggled(self, checked: bool) -> None:
        if checked:
            self._sidebar.show()
            self._h_splitter.setSizes([220, max(1000, self.width() - 220)])
        else:
            self._sidebar.hide()
            self._h_splitter.setSizes([0, max(1, self.width())])

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def refresh_providers(self) -> None:
        self._refresh_models()

    def retranslate(self) -> None:
        self._sidebar.retranslate()
        self._composer.retranslate()
        self._provider_selector.update_providers(
            self._provider_selector._models,
            self._provider_selector._active_id,
        )

    def set_chat_service(self, service: ChatService) -> None:
        self._chat_service = service
        self._persistence = service.get_persistence()
        self._sidebar.set_persistence(self._persistence)
        self._refresh_skills()
        self._chat_service.event_received.connect(self._on_stream_event)
        self._sidebar.refresh()

    def load_conversation(self, conversation_id: str) -> None:
        if self._persistence is None:
            return

        self._current_conversation_id = conversation_id
        self._message_list.clear_messages()

        messages = self._persistence.load_messages(conversation_id)
        message_vms = self._presenter.parse_messages_for_display(
            messages,
            unknown_label=self._t("chat.tool.unknown"),
            done_label=self._t("chat.tool.done"),
            completed_label=self._t("chat.tool.completed"),
        )
        for vm in message_vms:
            if vm.role == "user":
                self._message_list.append_message("user", vm.content)
            elif vm.role == "assistant":
                self._message_list.append_message(
                    "assistant", vm.content, show_role=vm.show_role
                )
            elif vm.role == "tool":
                # Tool traces are now rendered in the workflow activity
                # panel, not the message list.  Skip silently.
                pass

        self._sidebar.set_active(conversation_id)

        conv = self._persistence.get_conversation(conversation_id)
        if conv and conv.provider_id is not None:
            self._current_provider_id = conv.provider_id
            self._provider_selector.update_providers(
                self._provider_selector._models,
                self._current_provider_id,
            )

        if conv and conv.status == "running":
            self._is_running = True
            self._composer.set_running(True)
            self._message_list.show_thinking()
        else:
            self._is_running = False
            self._composer.set_running(False)
            self._message_list.hide_thinking()

    def on_stream_event(self, event_dict: dict) -> None:
        if event_dict.get("conversation_id") != self._current_conversation_id:
            return

        event_type = event_dict.get("type", "")
        payload = event_dict.get("payload", {})

        # ---- workflow visualiser always sees everything ----
        self._workflow_view.handle_event(event_dict)

        # ---- event dispatch ----
        if event_type == "run_started":
            self._on_run_started()
        elif event_type == "token":
            self._on_token(payload)
        elif event_type == "tool_start":
            self._on_tool_start(payload)
        elif event_type == "tool_result":
            self._on_tool_result(payload)
        elif event_type == "tool_error":
            self._on_tool_error(payload)
        elif event_type == "subagent_start":
            self._on_subagent_start(payload)
        elif event_type == "subagent_complete":
            self._on_subagent_finish(payload, failed=False)
        elif event_type == "subagent_error":
            self._on_subagent_finish(payload, failed=True)
        elif event_type == "skill_triggered":
            pass  # handled by workflow_view.handle_event above
        elif event_type == "run_completed":
            self._on_run_completed(payload)
        elif event_type == "run_failed":
            self._on_run_failed(payload)

    # ------------------------------------------------------------------
    # Manager access
    # ------------------------------------------------------------------

    def _get_current_model_name(self) -> str:
        return self._presenter.get_provider_display_name(self._current_provider_id)

    # ------------------------------------------------------------------
    # Session sidebar handlers
    # ------------------------------------------------------------------

    def _on_conversation_selected(self, conversation_id: str) -> None:
        self.load_conversation(conversation_id)

    def _on_new_conversation(self) -> None:
        if self._chat_service is None:
            return
        conv = self._chat_service.create_conversation(
            provider_id=self._current_provider_id,
            model_name=self._get_current_model_name(),
        )
        self._sidebar.add_conversation(conv)
        self.load_conversation(conv.id)
        self.conversation_created.emit(conv.id)

    def _on_conversation_deleted(self, conversation_id: str) -> None:
        if self._persistence is None:
            return
        self._persistence.delete_conversation(conversation_id)
        self._sidebar.remove_conversation(conversation_id)
        if self._current_conversation_id == conversation_id:
            self._current_conversation_id = None
            self._message_list.clear_messages()

    # ------------------------------------------------------------------
    # Role panel
    # ------------------------------------------------------------------

    def _on_role_selected(self, role_id: str) -> None:
        self._message_list.set_subagent_filter(role_id)

    # ------------------------------------------------------------------
    # Message submission
    # ------------------------------------------------------------------

    def _on_stop_requested(self) -> None:
        if self._is_running and self._chat_service:
            self._chat_service.cancel_turn()

    def _on_clear_requested(self) -> None:
        self._message_list.clear_messages()
        self._workflow_view.begin_run()
        self._role_panel.reset_all()
        if self._current_conversation_id and self._persistence:
            self._persistence.delete_conversation(self._current_conversation_id)
            self._sidebar.remove_conversation(self._current_conversation_id)
            self._current_conversation_id = None

    def _on_message_submitted(self, text: str) -> None:
        if self._is_running:
            return
        if self._chat_service is None:
            logger.warning("ChatService not set, ignoring message")
            return

        self._is_running = True
        self._composer.set_running(True)

        provider_dict, servers_list, skill_dict, history_dicts = self._get_current_config()
        if not provider_dict:
            self._is_running = False
            self._composer.set_running(False)
            self._message_list.append_message(
                "assistant", self._t("chat.error.no_provider")
            )
            return

        if self._current_conversation_id is None:
            conv = self._chat_service.create_conversation(
                provider_id=self._current_provider_id,
                model_name=self._get_current_model_name(),
            )
            self._current_conversation_id = conv.id
            self._sidebar.add_conversation(conv)
            self.conversation_created.emit(conv.id)

        self._message_list.append_message("user", text)
        self._chat_service.send_message(
            conversation_id=self._current_conversation_id,
            user_message=text,
            provider=provider_dict,
            skill=skill_dict,
            mcp_servers=servers_list,
            message_history=history_dicts,
        )

    def _get_current_config(self) -> tuple[dict, list[dict], dict | None, list[dict]]:
        history_dicts: list[dict[str, Any]] = []
        if self._persistence and self._current_conversation_id:
            history = self._persistence.load_messages(
                self._current_conversation_id, limit=50
            )
            history_dicts = [
                m.to_dict()
                for m in history
                if m.role in ("user", "assistant", "tool")
            ]

        config = self._presenter.prepare_submission_config(
            conversation_id=self._current_conversation_id or "",
            provider_id=self._current_provider_id,
            skill_id=self._current_skill_id,
            message_history=history_dicts,
        )
        if config is None:
            return {}, [], None, []
        return config.provider_dict, config.servers_list, config.skill_dict, config.history_dicts

    # ------------------------------------------------------------------
    # Provider selector
    # ------------------------------------------------------------------

    def _on_provider_changed(self, provider_id: int) -> None:
        self._current_provider_id = provider_id

    def _refresh_models(self) -> None:
        provider_vms = self._presenter.get_enabled_providers()
        if not provider_vms:
            self._provider_selector.update_providers([], None)
            return

        model_data = [(p.id, p.display_name, p.api_mode) for p in provider_vms]
        active_id = self._current_provider_id
        valid_ids = {p.id for p in provider_vms}
        if active_id not in valid_ids:
            active_id = None
            self._current_provider_id = None
        self._provider_selector.update_providers(model_data, active_id)

    def _refresh_skills(self) -> None:
        try:
            skills = self._presenter.list_available_skills()
            if skills and self._current_skill_id is None:
                self._current_skill_id = skills[0]["id"]
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Stream event handlers
    # ------------------------------------------------------------------

    def _on_run_started(self) -> None:
        self._current_assistant_content = ""
        self._message_list.show_thinking()
        self._role_panel.reset_all()
        self._role_panel.set_status("orchestrator", "running")

    def _on_token(self, payload: dict) -> None:
        content = payload.get("content", "")
        if not content:
            return
        subagent = payload.get("subagent", "orchestrator")
        self._current_assistant_content += content
        self._message_list.hide_thinking()
        self._message_list.append_chunk(content, subagent=subagent)
        # Keep the role card message count roughly in sync.
        self._role_panel.increment_message_count(subagent)

    def _on_subagent_start(self, payload: dict) -> None:
        name = payload.get("subagent", "")
        if name:
            self._role_panel.set_status(name, "running")

    def _on_subagent_finish(self, payload: dict, failed: bool = False) -> None:
        name = payload.get("subagent", "")
        if name:
            self._role_panel.set_status(name, "failed" if failed else "done")

    def _on_tool_start(self, payload: dict) -> None:
        # Tool calls render in the workflow activity panel exclusively.
        self._message_list.hide_thinking()
        # activity list is fed by WorkflowDagView.handle_event already.

    def _on_tool_result(self, payload: dict) -> None:
        pass  # activity panel only

    def _on_tool_error(self, payload: dict) -> None:
        pass  # activity panel only

    def _on_run_completed(self, payload: dict) -> None:
        self._is_running = False
        self._composer.set_running(False)
        self._composer.clear_input()
        self._message_list.hide_thinking()
        self._role_panel.set_status("orchestrator", "done")
        if self._current_conversation_id and self._persistence:
            conv = self._persistence.get_conversation(self._current_conversation_id)
            if conv:
                self._sidebar.update_conversation(conv)

    def _on_run_failed(self, payload: dict) -> None:
        self._is_running = False
        self._composer.set_running(False)
        self._message_list.hide_thinking()
        error = payload.get("error", self._t("chat.tool.unknown_error"))
        self._message_list.append_message(
            "assistant", self._t("chat.error.prefix", error=error)
        )
        self._role_panel.set_status("orchestrator", "failed")

    # ------------------------------------------------------------------
    # Slot wrapper
    # ------------------------------------------------------------------

    def _on_stream_event(self, event_dict: dict) -> None:
        self.on_stream_event(event_dict)
