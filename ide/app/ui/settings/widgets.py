"""Reusable utility widgets for the settings page."""

from __future__ import annotations

import re
from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import QComboBox, QDoubleSpinBox, QLineEdit, QSpinBox


class NoWheelSpinBox(QSpinBox):
    def wheelEvent(self, event) -> None:  # type: ignore[override]
        event.ignore()


class NoWheelComboBox(QComboBox):
    def wheelEvent(self, event) -> None:  # type: ignore[override]
        event.ignore()


class NoWheelDoubleSpinBox(QDoubleSpinBox):
    def wheelEvent(self, event) -> None:  # type: ignore[override]
        event.ignore()


# -- Token-count input with K/M suffix support --

_SUFFIX_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([kKmM]?)\s*$")
_SUFFIX_MULT = {"": 1, "k": 1_000, "K": 1_000, "m": 1_000_000, "M": 1_000_000}


def parse_token_text(text: str) -> int | None:
    """Parse a token-count string like ``"200K"`` or ``"1M"`` into an int.

    Returns ``None`` if *text* cannot be parsed.
    """
    m = _SUFFIX_RE.match(text)
    if not m:
        return None
    number = float(m.group(1))
    mult = _SUFFIX_MULT.get(m.group(2), 1)
    return int(number * mult)


def format_token_text(value: int) -> str:
    """Format a token count for display, using K/M suffixes when clean."""
    if value <= 0:
        return "0"
    if value % 1_000_000 == 0:
        return f"{value // 1_000_000}M"
    if value % 1_000 == 0:
        return f"{value // 1_000}K"
    return str(value)


class ContextTokenEdit(QLineEdit):
    """Single-line input that accepts token counts with optional K/M suffix.

    Internal value is always an ``int``.  Typing ``200K`` or ``1M`` is
    equivalent to ``200000`` or ``1000000`` respectively.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._value: int = 0
        self.setPlaceholderText("e.g. 200K, 1M, or 131072")
        self.setText("0")
        self.textChanged.connect(self._on_text_changed)

    # -- public API --

    def value(self) -> int:
        """Return the current token count as an integer."""
        return self._value

    def setValue(self, val: int) -> None:
        """Set the token count and update the displayed text."""
        self._value = max(0, val)
        # Block signals so we don't re-parse our own formatted text.
        self.blockSignals(True)
        self.setText(format_token_text(self._value))
        self.blockSignals(False)

    # -- internals --

    def _on_text_changed(self, text: str) -> None:
        parsed = parse_token_text(text)
        if parsed is not None:
            self._value = parsed

    def focusOutEvent(self, event):  # type: ignore[override]
        # Re-format on blur so the user sees the canonical form.
        self.blockSignals(True)
        self.setText(format_token_text(self._value))
        self.blockSignals(False)
        super().focusOutEvent(event)

    def keyPressEvent(self, event):  # type: ignore[override]
        # Allow free typing; validation happens silently.
        super().keyPressEvent(event)
