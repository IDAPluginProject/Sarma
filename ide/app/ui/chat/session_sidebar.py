"""Session sidebar — conversation list for multi-conversation management.

Shows a scrollable list of conversations with titles, timestamps, and status
indicators. Users can switch between conversations, create new ones, and
delete old ones.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.chat.models import Conversation

if TYPE_CHECKING:
    from app.chat.persistence import ChatPersistence
    from app.i18n import I18n


class ConversationItem(QFrame):
    """A single conversation entry in the sidebar."""

    clicked = Signal(str)   # conversation_id
    delete_requested = Signal(str)  # conversation_id

    def __init__(
        self,
        conversation: Conversation,
        i18n: I18n,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._i18n = i18n
        self._conv_id = conversation.id
        self._conv_title: str = conversation.title  # may be ""
        self.setObjectName("sessionItem")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(48)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._active = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(2)

        # Top row: title + delete button
        top_row = QWidget()
        top_layout = QHBoxLayout(top_row)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(4)

        title = conversation.title or i18n.t("chat.session.untitled")
        self._title_label = QLabel(title)
        self._title_label.setObjectName("sessionItemTitle")
        self._title_label.setWordWrap(False)
        top_layout.addWidget(self._title_label, 1)

        self._del_button = QPushButton("\u00d7")  # ×
        self._del_button.setObjectName("sessionDeleteButton")
        self._del_button.setFixedSize(18, 18)
        self._del_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._del_button.setToolTip(i18n.t("chat.session.delete"))
        self._del_button.clicked.connect(
            lambda: self.delete_requested.emit(self._conv_id)
        )
        top_layout.addWidget(self._del_button)

        layout.addWidget(top_row)

        # Timestamp row
        ts = conversation.updated_at or ""
        if len(ts) > 16:
            ts = ts[:16].replace("T", " ")
        self._meta_label = QLabel(ts)
        self._meta_label.setObjectName("sessionItemMeta")
        layout.addWidget(self._meta_label)

    @property
    def conversation_id(self) -> str:
        return self._conv_id

    def set_active(self, active: bool) -> None:
        self._active = active
        self.setProperty("active", active)
        self.style().unpolish(self)
        self.style().polish(self)

    def update_conversation(self, conv: Conversation) -> None:
        """Update title and timestamp from conversation data.

        Only overwrites the title label when *conv.title* is non-empty.
        When the DB title is empty (e.g. inference hasn't run yet),
        the previous display — typically the i18n fallback set during
        ``__init__`` — is preserved.
        """
        if conv.title:
            self._conv_title = conv.title
            self._title_label.setText(conv.title)
        ts = conv.updated_at or ""
        if len(ts) > 16:
            ts = ts[:16].replace("T", " ")
        self._meta_label.setText(ts)

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._conv_id)
        super().mousePressEvent(event)


class SessionSidebar(QWidget):
    """Left sidebar showing conversation list."""

    conversation_selected = Signal(str)  # conversation_id
    new_conversation_requested = Signal()
    conversation_deleted = Signal(str)  # conversation_id

    def __init__(
        self,
        i18n: I18n,
        persistence: ChatPersistence | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._i18n = i18n
        self._persistence = persistence
        self._active_id: str | None = None
        self._items: dict[str, ConversationItem] = {}
        self._mode_filter: str | None = None

        self._build_ui()

    def _t(self, key: str, **kwargs: object) -> str:
        return self._i18n.t(key, **kwargs)

    def retranslate(self) -> None:
        """Refresh all translatable text after a language change."""
        self._title_label.setText(self._t("chat.session.title"))
        self._new_button.setToolTip(self._t("chat.new_conversation"))
        for item in self._items.values():
            item._del_button.setToolTip(self._t("chat.session.delete"))
            # Re-apply the i18n fallback for untitled conversations so
            # the language switch is reflected immediately.
            if not item._conv_title:
                item._title_label.setText(self._t("chat.session.untitled"))

    def _build_ui(self) -> None:
        self.setObjectName("sessionSidebar")
        self.setFixedWidth(220)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Header
        header = QFrame()
        header.setObjectName("sessionSidebarHeader")
        header.setFixedHeight(40)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(12, 0, 8, 0)

        self._title_label = QLabel(self._t("chat.session.title"))
        self._title_label.setObjectName("sessionSidebarTitle")
        header_layout.addWidget(self._title_label)
        header_layout.addStretch(1)

        self._new_button = QPushButton("+")
        self._new_button.setObjectName("sessionNewButton")
        self._new_button.setFixedSize(24, 24)
        self._new_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._new_button.setToolTip(self._t("chat.new_conversation"))
        self._new_button.clicked.connect(self.new_conversation_requested.emit)
        header_layout.addWidget(self._new_button)

        outer.addWidget(header)

        # Scrollable conversation list
        self._list_container = QWidget()
        self._list_container.setObjectName("sessionListContainer")
        self._list_layout = QVBoxLayout(self._list_container)
        self._list_layout.setContentsMargins(4, 4, 4, 4)
        self._list_layout.setSpacing(2)
        self._list_layout.addStretch(1)
        self._list_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        scroll = QScrollArea()
        scroll.setWidget(self._list_container)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setObjectName("sessionScrollArea")

        outer.addWidget(scroll, 1)

    def set_persistence(self, persistence: ChatPersistence) -> None:
        self._persistence = persistence

    def set_mode_filter(self, mode: str) -> None:
        """Filter sidebar to only show conversations for the given mode."""
        self._mode_filter = mode
        self.refresh()

    def refresh(self) -> None:
        """Reload conversation list from persistence."""
        if self._persistence is None:
            return

        # Clear existing items
        for item in self._items.values():
            self._list_layout.removeWidget(item)
            item.deleteLater()
        self._items.clear()

        conversations = self._persistence.list_conversations()
        for conv in conversations:
            if self._mode_filter and getattr(conv, "mode", None) != self._mode_filter:
                continue
            self._add_item(conv)

        # Restore active selection
        if self._active_id and self._active_id in self._items:
            self._items[self._active_id].set_active(True)
        elif self._active_id:
            # Active conversation no longer exists
            self._active_id = None

    def set_active(self, conversation_id: str | None) -> None:
        """Highlight the active conversation."""
        # Deactivate old
        if self._active_id and self._active_id in self._items:
            self._items[self._active_id].set_active(False)

        self._active_id = conversation_id

        # Activate new
        if conversation_id and conversation_id in self._items:
            self._items[conversation_id].set_active(True)

    def add_conversation(self, conv: Conversation) -> None:
        """Add a new conversation to the top of the list."""
        self._add_item(conv, index=0)
        self.set_active(conv.id)

    def remove_conversation(self, conversation_id: str) -> None:
        """Remove a conversation from the list."""
        if conversation_id in self._items:
            item = self._items.pop(conversation_id)
            self._list_layout.removeWidget(item)
            item.deleteLater()
            if self._active_id == conversation_id:
                self._active_id = None

    def update_conversation(self, conv: Conversation) -> None:
        """Update an existing conversation's display."""
        if conv.id in self._items:
            self._items[conv.id].update_conversation(conv)

    def _add_item(self, conv: Conversation, index: int | None = None) -> None:
        item = ConversationItem(conv, self._i18n)
        item.clicked.connect(self._on_item_clicked)
        item.delete_requested.connect(self._on_delete_requested)

        if index is not None:
            self._list_layout.insertWidget(index, item)
        else:
            # Insert before the stretch
            count = self._list_layout.count()
            self._list_layout.insertWidget(count - 1, item)

        self._items[conv.id] = item

    def _on_item_clicked(self, conversation_id: str) -> None:
        self.set_active(conversation_id)
        self.conversation_selected.emit(conversation_id)

    def _on_delete_requested(self, conversation_id: str) -> None:
        self.conversation_deleted.emit(conversation_id)
