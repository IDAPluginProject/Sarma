"""Bottom input bar for user messages and commands."""

from __future__ import annotations

from pathlib import Path

from textual import events
from textual.containers import Horizontal
from textual.message import Message
from textual.widgets import Button, Input

from sarma_cli.commands import COMMANDS
from sarma_cli.config import WORKFLOWS
from sarma_cli.tui.input_history import (
    MAX_HISTORY_ENTRIES,
    append_input_history,
    load_input_history,
)


class UserInputSubmitted(Message):
    """Message sent when the user submits input."""

    def __init__(self, content: str) -> None:
        super().__init__()
        self.content = content


class HistoryInput(Input):
    """Input widget with shell-like history and lightweight completion."""

    def __init__(self, *, history_path: Path | None = None) -> None:
        super().__init__(
            placeholder="Type a message or /command...",
            id="user-input",
        )
        self._history_path = history_path
        self._history = load_input_history(history_path)
        self._history_index: int | None = None
        self._draft = ""
        self._completion_prefix = ""
        self._completion_matches: list[str] = []
        self._completion_index = -1

    def on_key(self, event: events.Key) -> None:
        if event.key == "up":
            event.prevent_default().stop()
            self._previous_history()
            return
        if event.key == "down":
            event.prevent_default().stop()
            self._next_history()
            return
        if event.key == "tab":
            event.prevent_default().stop()
            self._complete()

    def remember(self, content: str) -> None:
        entry = content.strip()
        if not entry:
            return
        self._remember_in_memory(entry)
        self._history_index = None
        self._draft = ""
        self._reset_completion()
        if self.is_attached:
            self.app.run_worker(
                lambda: append_input_history(entry, self._history_path),
                thread=True,
                exit_on_error=False,
            )
        else:
            append_input_history(entry, self._history_path)

    def _remember_in_memory(self, entry: str) -> None:
        if entry in self._history:
            self._history.remove(entry)
        self._history.append(entry)
        self._history = self._history[-MAX_HISTORY_ENTRIES:]

    def _previous_history(self) -> None:
        if not self._history:
            return
        if self._history_index is None:
            self._draft = self.value
            self._history_index = len(self._history) - 1
        else:
            self._history_index = max(0, self._history_index - 1)
        self._set_value(self._history[self._history_index])

    def _next_history(self) -> None:
        if self._history_index is None:
            return
        if self._history_index >= len(self._history) - 1:
            self._history_index = None
            self._set_value(self._draft)
            return
        self._history_index += 1
        self._set_value(self._history[self._history_index])

    def _complete(self) -> None:
        prefix = self.value
        matches = self._completion_candidates(prefix)
        if not matches:
            self._reset_completion()
            return
        if prefix != self._completion_prefix or matches != self._completion_matches:
            self._completion_prefix = prefix
            self._completion_matches = matches
            self._completion_index = 0
        else:
            self._completion_index = (self._completion_index + 1) % len(matches)
        self._set_value(matches[self._completion_index])

    def _completion_candidates(self, value: str) -> list[str]:
        text = value.strip()
        if not text:
            return ["/"]
        if text.startswith("/workflow "):
            prefix = text.rsplit(" ", 1)[-1]
            return [
                f"/workflow {workflow}"
                for workflow in WORKFLOWS
                if workflow.startswith(prefix)
            ]
        if text.startswith("/"):
            matches = [command for command in COMMANDS if command.startswith(text)]
            return [
                command + (" " if command not in {"/help", "/status", "/models", "/history", "/clear", "/compact", "/config", "/plugin", "/restart", "/exit"} else "")
                for command in matches
            ]
        return [entry for entry in reversed(self._history) if entry.startswith(text)]

    def _set_value(self, value: str) -> None:
        self.value = value
        self.cursor_position = len(value)

    def _reset_completion(self) -> None:
        self._completion_prefix = ""
        self._completion_matches = []
        self._completion_index = -1


class InputBar(Horizontal):
    """Bottom input bar with text input and send button."""

    def __init__(self, *, history_path: Path | None = None) -> None:
        super().__init__(id="input-bar")
        self._history_path = history_path

    def compose(self):
        yield HistoryInput(history_path=self._history_path)
        yield Button("Send", id="send-button", variant="primary")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle Enter key in input field."""
        self._submit_input()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle Send button click."""
        if event.button.id == "send-button":
            self._submit_input()

    def _submit_input(self) -> None:
        """Get input content and post message."""
        input_widget = self.query_one("#user-input", HistoryInput)
        content = input_widget.value.strip()
        if content:
            input_widget.remember(content)
            self.post_message(UserInputSubmitted(content))
            input_widget.value = ""

    def focus_input(self) -> None:
        """Focus the input field."""
        self.query_one("#user-input", Input).focus()
