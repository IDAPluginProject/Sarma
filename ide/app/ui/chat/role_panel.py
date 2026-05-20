"""Role panel — vertical list of subagent role cards.

Each card represents a subagent (or the orchestrator) and shows its
name, status, and message count.  Clicking a card filters the message
list to show only that role's output.

Card order is fixed: orchestrator first, then the five audit subagents
in pipeline order (recon → decompile → vuln_hunt → cross_ref → reporter).
Additional roles discovered at runtime are appended at the bottom.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.chat.audit_subagents import AUDIT_SUBAGENT_ORDER

if TYPE_CHECKING:
    from app.i18n import I18n

STATUS_IDLE = "idle"
STATUS_RUNNING = "running"
STATUS_DONE = "done"
STATUS_FAILED = "failed"

_FIXED_ORDER: list[str] = ["orchestrator", *list(AUDIT_SUBAGENT_ORDER)]

_DEFAULT_LABELS: dict[str, str] = {
    "orchestrator": "Orchestrator",
    "recon": "Recon",
    "hunt": "Hunt",
    "validate": "Validate",
    "gapfill": "Gapfill",
    "dedupe": "Dedupe",
    "trace": "Trace",
    "feedback": "Feedback",
    "report": "Report",
}

_STATUS_GLYPHS: dict[str, str] = {
    STATUS_IDLE:    "○",
    STATUS_RUNNING: "◉",
    STATUS_DONE:    "✓",
    STATUS_FAILED:  "✗",
}


class _RoleCard(QFrame):
    """A single clickable role card."""

    clicked = Signal(str)  # role_id

    def __init__(self, role_id: str, label: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("roleCard")
        self._role_id = role_id
        self._status = STATUS_IDLE
        self._message_count = 0

        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(6)

        self._glyph = QLabel(_STATUS_GLYPHS[STATUS_IDLE])
        self._glyph.setObjectName("roleCardGlyph")
        self._glyph.setFixedWidth(16)
        self._glyph.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._glyph)

        self._label = QLabel(label)
        self._label.setObjectName("roleCardLabel")
        layout.addWidget(self._label, 1)

        self._count_label = QLabel("")
        self._count_label.setObjectName("roleCardCount")
        self._count_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        layout.addWidget(self._count_label)

    @property
    def role_id(self) -> str:
        return self._role_id

    def set_status(self, status: str) -> None:
        self._status = status
        self._glyph.setText(_STATUS_GLYPHS.get(status, _STATUS_GLYPHS[STATUS_IDLE]))
        self.setProperty("status", status)
        self.style().unpolish(self)
        self.style().polish(self)

    def set_message_count(self, count: int) -> None:
        self._message_count = count
        self._count_label.setText(str(count) if count else "")

    def set_selected(self, selected: bool) -> None:
        self.setProperty("selected", selected)
        self.style().unpolish(self)
        self.style().polish(self)

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._role_id)
        super().mousePressEvent(event)


class RolePanel(QWidget):
    """Vertical list of role cards for subagent message filtering.

    Emits ``role_selected(str)`` when the user clicks a card.
    """

    role_selected = Signal(str)

    def __init__(
        self,
        i18n: I18n | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("rolePanel")
        self._i18n = i18n

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        header = QLabel(self._t("chat.roles.title", default="Agents"))
        header.setObjectName("rolePanelTitle")
        outer.addWidget(header)

        self._cards: dict[str, _RoleCard] = {}
        self._card_order: list[str] = []
        self._selected: str | None = None

        self._container = QWidget()
        self._container.setObjectName("roleCardContainer")
        self._card_layout = QVBoxLayout(self._container)
        self._card_layout.setContentsMargins(0, 4, 0, 4)
        self._card_layout.setSpacing(2)
        self._card_layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidget(self._container)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setObjectName("rolePanelScroll")
        outer.addWidget(scroll, 1)

        # Pre-allocate fixed-order cards.
        for role_id in _FIXED_ORDER:
            self._ensure_card(role_id)

    def _t(self, key: str, default: str = "", **kwargs) -> str:
        if self._i18n is None:
            return default or key
        try:
            text = self._i18n.t(key, **kwargs)
        except Exception:
            return default or key
        if text == key and default:
            return default
        return text

    def _resolve_label(self, role_id: str) -> str:
        """Try i18n key `chat.workflow.node.<role_id>` first, then fall back."""
        if self._i18n is not None:
            key = f"chat.workflow.node.{role_id}"
            try:
                text = self._i18n.t(key)
                if text != key:
                    return text
            except Exception:
                pass
        return _DEFAULT_LABELS.get(role_id, role_id)

    def _ensure_card(self, role_id: str) -> _RoleCard:
        card = self._cards.get(role_id)
        if card is not None:
            return card

        label = self._resolve_label(role_id)
        card = _RoleCard(role_id, label)
        card.clicked.connect(self._on_card_clicked)
        # Insert before the trailing stretch.
        idx = self._card_layout.count() - 1
        self._card_layout.insertWidget(max(0, idx), card)
        self._cards[role_id] = card
        self._card_order.append(role_id)
        return card

    def _on_card_clicked(self, role_id: str) -> None:
        self.select_role(role_id)
        self.role_selected.emit(role_id)

    # -- public API --

    def select_role(self, role_id: str) -> None:
        if self._selected == role_id:
            return
        for cid, card in self._cards.items():
            card.set_selected(cid == role_id)
        self._selected = role_id

    def set_status(self, role_id: str, status: str) -> None:
        card = self._ensure_card(role_id)
        card.set_status(status)

    def increment_message_count(self, role_id: str) -> None:
        card = self._ensure_card(role_id)
        # Approximate count from the card's current label.
        card.set_message_count(card._message_count + 1)

    def reset_all(self) -> None:
        for card in self._cards.values():
            card.set_status(STATUS_IDLE)
            card.set_message_count(0)
        # Select orchestrator by default.
        self.select_role("orchestrator")

    @property
    def selected_role(self) -> str | None:
        return self._selected
