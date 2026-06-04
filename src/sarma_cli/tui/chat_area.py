"""Chat area widget for displaying conversation history."""

from __future__ import annotations

from typing import Any

import json

from rich.console import Group
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text
from textual.css.query import NoMatches
from textual.containers import VerticalScroll
from textual.widgets import Collapsible, Static


class UserMessage(Static):
    """A user message bubble."""

    def __init__(self, content: str) -> None:
        super().__init__()
        self._content = content

    def compose(self):
        yield Static(Text("You", style="bold #58a6ff"), classes="message-speaker")
        yield Static(Text(self._content, style="default"), classes="user-message")

    def on_mount(self) -> None:
        self.styles.height = "auto"


class SystemMessage(Static):
    """A non-streaming Sarma message."""

    def __init__(self, content: Any, speaker: str = "Sarma") -> None:
        super().__init__()
        self._content = content
        self._speaker = speaker

    def compose(self):
        yield Static(
            Text(self._speaker, style=_speaker_style(self._speaker)),
            classes="message-speaker",
        )
        if isinstance(self._content, str):
            content: Any = Text(self._content, style="default")
        else:
            content = self._content
        yield Static(content, classes="assistant-message")

    def on_mount(self) -> None:
        self.styles.height = "auto"


class AssistantMessage(Static):
    """An assistant message that supports streaming updates."""

    def __init__(self, speaker: str = "Sarma") -> None:
        super().__init__()
        self.speaker = speaker
        self._buffer: list[str] = []
        self._reasoning_buffer: list[str] = []

    def compose(self):
        yield Static(
            Text(self.speaker, style=_speaker_style(self.speaker)),
            classes="message-speaker",
        )
        yield Static(self._render_text(), classes="assistant-message assistant-body")

    def on_mount(self) -> None:
        self.styles.height = "auto"
        self._update_body(self._render_text())

    def _render_text(self) -> Any:
        content = "".join(self._buffer)
        if content.strip():
            return Markdown(content)
        return Text("…", style="dim")

    def feed_token(self, token: str) -> None:
        self._buffer.append(token)
        self._update_body(self._render_text())

    def feed_reasoning(self, token: str) -> None:
        self._reasoning_buffer.append(token)

    def has_visible_content(self) -> bool:
        return bool("".join(self._buffer).strip())

    def flush(self) -> str:
        content = "".join(self._buffer)
        self._buffer.clear()

        reasoning = "".join(self._reasoning_buffer)
        self._reasoning_buffer.clear()

        if content.strip() or reasoning.strip():
            self._update_body(self._render_final(content, reasoning))
        return content

    def _render_final(self, content: str, reasoning: str) -> Group:
        renderables: list[object] = []
        if content.strip():
            renderables.append(Markdown(content))
        if reasoning.strip():
            renderables.append(Panel(
                reasoning[:500],
                title="[dim]thinking[/]",
                border_style="dim",
                expand=False,
            ))
        return Group(*renderables)

    def _update_body(self, content: Any) -> None:
        try:
            self.query_one(".assistant-body", Static).update(content)
        except NoMatches:
            return


class ToolCallWidget(Collapsible):
    """Default-collapsed inline tool event."""

    def __init__(
        self,
        *,
        call_id: str,
        name: str,
        speaker: str,
        kind: str = "tool",
        args: Any = None,
        summary: str = "",
    ) -> None:
        self.call_id = call_id
        self.tool_name = name or kind
        self.speaker = speaker or "Sarma"
        self.kind = kind
        self.args = args
        self.summary = summary
        self.result = ""
        self.error = ""
        self.status = "running"
        super().__init__(
            Static(self._render_body(), classes="tool-call-body"),
            title=self._make_title(),
            collapsed=True,
            classes="tool-call",
        )

    def on_mount(self) -> None:
        self.styles.height = "auto"
        self._update_body()

    def complete(self, *, result: str = "", error: str = "") -> None:
        self.result = result
        self.error = error
        self.status = "error" if error else "done"
        self.title = self._make_title()
        self._update_body()

    def _make_title(self) -> str:
        marker = {
            "running": "...",
            "done": "✓",
            "error": "✗",
        }.get(self.status, "-")
        label = "tool"
        summary = f"  {self.summary}" if self.summary else ""
        return f"{self.speaker}  {marker} {label}: {self.tool_name}{summary}"

    def _render_body(self) -> Group:
        rows: list[object] = []
        if self.args not in (None, "", {}, []):
            rows.append(Text("args", style="bold dim"))
            rows.append(Text(_format_payload(self.args), style="dim"))
        if self.result:
            rows.append(Text("result", style="bold dim"))
            rows.append(Text(self.result, style="default"))
        if self.error:
            rows.append(Text("error", style="bold red"))
            rows.append(Text(self.error, style="red"))
        if not rows:
            rows.append(Text("running", style="dim"))
        return Group(*rows)

    def _update_body(self) -> None:
        try:
            self.query_one(".tool-call-body", Static).update(self._render_body())
        except NoMatches:
            return


class SubagentDivider(Static):
    """Subagent stage separator."""

    def __init__(self, line: Text) -> None:
        super().__init__()
        self._line = line

    def compose(self):
        yield Static(self._line, classes="subagent-divider")

    def on_mount(self) -> None:
        self.styles.height = "auto"


class ChatArea(VerticalScroll):
    """Scrollable chat history area."""

    DEFAULT_CSS = """
    ChatArea {
        scrollbar-background: #0d1117;
        scrollbar-color: #30363d;
        scrollbar-color-hover: #58a6ff;
    }
    """

    def __init__(self) -> None:
        super().__init__(id="chat-area")
        self._current_assistant: AssistantMessage | None = None
        self._tool_calls: dict[str, ToolCallWidget] = {}
        self._tool_counter = 0
        self._auto_follow = True

    def add_user_message(self, content: str) -> None:
        """Add a user message to the chat."""
        msg = UserMessage(content)
        follow = True
        self.mount(msg)
        self.follow_if(follow)

    def add_system_message(self, content: Any, speaker: str = "Sarma") -> None:
        """Add a non-streaming assistant or system message to the chat."""
        msg = SystemMessage(content, speaker)
        follow = self.should_follow()
        self.mount(msg)
        self.follow_if(follow)

    def start_assistant_message(self, speaker: str = "Sarma") -> AssistantMessage:
        """Start a new assistant message and return it for streaming."""
        msg = AssistantMessage(speaker)
        self._current_assistant = msg
        follow = self.should_follow()
        self.mount(msg)
        self.follow_if(follow)
        return msg

    def get_current_assistant(self, speaker: str | None = None) -> AssistantMessage | None:
        """Get the current assistant message being streamed."""
        if speaker and self._current_assistant and self._current_assistant.speaker != speaker:
            self.end_assistant_message()
            return None
        return self._current_assistant

    def ensure_assistant_message(self, speaker: str = "Sarma") -> AssistantMessage:
        """Return the active assistant message, switching speakers if needed."""
        assistant = self.get_current_assistant(speaker)
        if assistant is None:
            assistant = self.start_assistant_message(speaker)
        return assistant

    def end_assistant_message(self) -> str:
        """Finalize the current assistant message."""
        if self._current_assistant is None:
            return ""
        content = self._current_assistant.flush()
        self._current_assistant = None
        return content

    def add_tool_line(self, line: Text) -> None:
        """Add a tool call line."""
        widget = Static(line, classes="tool-line")
        follow = self.should_follow()
        self.mount(widget)
        self.follow_if(follow)

    def add_skill_trigger(self, name: str, speaker: str = "Sarma") -> None:
        """Insert a compact skill-trigger line at the current stream position."""
        self.end_assistant_message()
        line = Text("  ")
        line.append(f"{speaker}  ", style="dim")
        line.append("skill: ", style="bold #d29922")
        line.append(name, style="bold #d29922")
        self.add_tool_line(line)

    def add_tool_call(
        self,
        *,
        call_id: str,
        name: str,
        speaker: str,
        args: Any = None,
        summary: str = "",
        kind: str = "tool",
    ) -> str:
        """Insert a collapsed tool block at the current stream position."""
        self.end_assistant_message()
        key = call_id or self._next_tool_id()
        widget = ToolCallWidget(
            call_id=key,
            name=name,
            speaker=speaker,
            kind=kind,
            args=args,
            summary=summary,
        )
        self._tool_calls[key] = widget
        follow = self.should_follow()
        self.mount(widget)
        self.follow_if(follow)
        return key

    def update_tool_call(
        self,
        call_id: str,
        *,
        name: str = "",
        speaker: str = "Sarma",
        result: str = "",
        error: str = "",
    ) -> str:
        """Mark a tool block complete, inserting one if the start was missed."""
        key = call_id or self._find_pending_tool(name, speaker) or self._next_tool_id()
        widget = self._tool_calls.get(key)
        if widget is None:
            widget = ToolCallWidget(
                call_id=key,
                name=name,
                speaker=speaker,
            )
            self._tool_calls[key] = widget
            follow = self.should_follow()
            self.mount(widget)
        else:
            follow = self.should_follow()
        widget.complete(result=result, error=error)
        self.follow_if(follow)
        return key

    def add_subagent_divider(self, line: Text) -> None:
        """Add a subagent stage divider."""
        widget = SubagentDivider(line)
        follow = self.should_follow()
        self.mount(widget)
        self.follow_if(follow)

    def clear_chat(self) -> None:
        """Clear all messages."""
        self.remove_children()
        self._current_assistant = None
        self._tool_calls.clear()

    def should_follow(self) -> bool:
        """Return whether new content should keep the viewport at the bottom."""
        if self._is_near_vertical_end():
            self._auto_follow = True
        return self._auto_follow

    def follow_if(self, follow: bool) -> None:
        if follow:
            self._auto_follow = True
            self._scroll_to_end()
            self.call_after_refresh(self._scroll_to_end)
            self.call_later(self._scroll_to_end)

    def watch_scroll_y(self, old_value: float, new_value: float) -> None:
        """Track whether the user is still pinned to the bottom."""
        super().watch_scroll_y(old_value, new_value)
        self._auto_follow = self._is_near_vertical_end()

    def _is_near_vertical_end(self) -> bool:
        """Return True when the viewport is at, or very close to, the bottom."""
        if self.is_vertical_scroll_end:
            return True
        try:
            return (float(self.max_scroll_y) - float(self.scroll_y)) <= 2.0
        except (TypeError, ValueError):
            return False

    def _scroll_to_end(self) -> None:
        self.scroll_end(animate=False, immediate=True)

    def _next_tool_id(self) -> str:
        self._tool_counter += 1
        return f"local-tool-{self._tool_counter}"

    def _find_pending_tool(self, name: str, speaker: str) -> str | None:
        for key, widget in reversed(list(self._tool_calls.items())):
            if widget.status == "running" and widget.tool_name == name and widget.speaker == speaker:
                return key
        return None


def _speaker_style(speaker: str) -> str:
    if speaker == "Sarma":
        return "bold #a371f7"
    return "bold #3fb950"


def _format_payload(value: Any) -> str:
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, indent=2, default=str)
    except TypeError:
        return str(value)
