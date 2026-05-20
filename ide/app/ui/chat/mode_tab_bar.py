"""Chat / Audit mode tab bar."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QWidget

MODE_CHAT = "chat"
MODE_AUDIT = "audit"


class ModeTabBar(QWidget):
    """Toggle between Chat and Audit modes."""

    mode_changed = Signal(str)  # "chat" or "audit"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._current_mode = MODE_AUDIT

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._btn_chat = self._make_button("Chat")
        self._btn_audit = self._make_button("Audit")

        self._btn_chat.clicked.connect(lambda: self._select(MODE_CHAT))
        self._btn_audit.clicked.connect(lambda: self._select(MODE_AUDIT))

        layout.addWidget(self._btn_chat)
        layout.addWidget(self._btn_audit)

        self._update_style()

    @property
    def current_mode(self) -> str:
        return self._current_mode

    def set_mode(self, mode: str) -> None:
        """Programmatically set mode without emitting signal."""
        if mode in (MODE_CHAT, MODE_AUDIT):
            self._current_mode = mode
            self._update_style()

    def _select(self, mode: str) -> None:
        if mode == self._current_mode:
            return
        self._current_mode = mode
        self._update_style()
        self.mode_changed.emit(mode)

    def _make_button(self, text: str) -> QPushButton:
        btn = QPushButton(text)
        btn.setFixedHeight(24)
        btn.setMinimumWidth(48)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setObjectName("modeTabButton")
        return btn

    def _update_style(self) -> None:
        active = "background: #3a3f4b; color: #e0e0e0; border: none; border-radius: 4px; padding: 2px 10px; font-weight: bold;"
        inactive = "background: transparent; color: #888; border: none; border-radius: 4px; padding: 2px 10px;"
        self._btn_chat.setStyleSheet(active if self._current_mode == MODE_CHAT else inactive)
        self._btn_audit.setStyleSheet(active if self._current_mode == MODE_AUDIT else inactive)
