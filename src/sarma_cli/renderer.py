"""Rich terminal rendering for Sarma CLI TUI."""

from __future__ import annotations

import time
from typing import Any

from rich.console import Console, Group
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

console = Console()

PRIMARY = "#58a6ff"
SUCCESS = "#3fb950"
ERROR = "#f85149"
WARNING = "#d29922"
INFO = "#7d8590"
PURPLE = "#a371f7"

BANNER_GRADIENT = (PRIMARY, "#6f8cff", "#8b7cf6", PURPLE)

_BANNER = r"""
  ___  __ _ _ __ _ __ ___   __ _
 / __|/ _` | '__| '_ ` _ \ / _` |
 \__ \ (_| | |  | | | | | | (_| |
 |___/\__,_|_|  |_| |_| |_|\__,_|
"""


def _eye_logo() -> Text:
    """Build an eye-shaped pixel logo with gradient colors."""
    logo = Text()
    # Each line: (text, style) — iris/pupil colored with theme accents
    lines = [
        ("      ┌─────────┐      ", f"bold {PRIMARY}"),
        ("      │         │      ", f"bold #4f8dff"),
        ("      │  ░░░░░  │      ", f"bold #5b6ff0"),
        ("      │  ░   ░  │      ", f"bold #6a60e8"),
        ("      │  ░ ◆ ░  │      ", f"bold {PURPLE}"),
        ("      │  ░   ░  │      ", f"bold #8b57e8"),
        ("      │  ░░░░░  │      ", f"bold #9a4adf"),
        ("      │         │      ", f"bold {PURPLE}"),
        ("      └─────────┘      ", f"bold #7c3aed"),
    ]
    for line_text, style in lines:
        logo.append(line_text, style=style)
        logo.append("\n")
    return logo


def print_banner(model: str = "", mcp_count: int = 0) -> None:
    """Print the Sarma banner with shield logo and status info."""
    # Left column: eye logo
    eye = _eye_logo()

    # Right column: info lines
    info = Text()
    info.append("Sarma\n", style=f"bold {PRIMARY}")
    info.append("Vulnerability Audit Agent\n", style=f"dim {INFO}")
    info.append("─" * 26 + "\n", style="dim")
    if model:
        info.append("Model  ", style="dim")
        info.append(f"{model}\n", style=f"bold {SUCCESS}")
    else:
        info.append("Model  ", style="dim")
        info.append("not configured\n", style="dim italic")
    if mcp_count:
        info.append("MCP    ", style="dim")
        info.append(f"{mcp_count} server(s)\n", style=f"bold {PURPLE}")
    else:
        info.append("MCP    ", style="dim")
        info.append("none\n", style="dim italic")
    info.append("\n/help for commands  ·  Ctrl+C to exit", style=f"dim {INFO}")

    # Combine into a table for alignment
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("logo", justify="center", vertical="middle")
    table.add_column("info", vertical="middle")
    table.add_row(eye, info)

    console.print(
        Panel(
            table,
            border_style=PURPLE,
            expand=False,
            padding=(1, 2),
        )
    )


def print_error(msg: str) -> None:
    console.print(_message_line("ERROR", msg, ERROR, "✗"))


def print_warning(msg: str) -> None:
    console.print(_message_line("WARN", msg, WARNING, "!"))


def print_info(msg: str) -> None:
    console.print(_message_line("INFO", msg, INFO, "i"))


def print_success(msg: str) -> None:
    console.print(_message_line("OK", msg, SUCCESS, "✓"))


def print_markdown(content: str) -> None:
    if not content.strip():
        return
    console.print(Markdown(content))


def print_tool_start(name: str, args: str) -> None:
    console.print(_tool_line("RUN", name, _truncate(args, 100), PRIMARY, "▶"))


def print_tool_result(name: str, result: str) -> None:
    console.print(_tool_line("DONE", name, _truncate(result, 160), SUCCESS, "✓"))


def print_tool_error(name: str, error: str) -> None:
    console.print(_tool_line("FAIL", name, _truncate(error, 160), ERROR, "✗"))


def print_subagent_start(name: str) -> None:
    console.print()
    console.print(Text(f"╭─ {name.upper()} ", style=f"bold {PRIMARY}") + Text("─" * 32, style=PURPLE))


def print_subagent_done(name: str) -> None:
    console.print(Text(f"╰─ {name} complete ", style=f"bold {SUCCESS}") + Text("─" * 24, style=INFO))
    console.print()


def print_reasoning(content: str) -> None:
    if not content.strip():
        return
    console.print(Panel(
        Text(_truncate(content, 500), style=INFO),
        title=f"[bold {INFO}] thinking [/bold {INFO}]",
        border_style=INFO,
        expand=False,
        padding=(0, 1),
    ))


class StreamPrinter:
    """Accumulates streaming tokens and renders live markdown.

    Uses Rich Live to progressively re-render the accumulated content
    as formatted Markdown. Refreshes at most every 80ms to avoid flicker.

    Features:
      - Thinking spinner during reasoning
      - Blinking typing cursor during token streaming
      - Tool / subagent execution timing
    """

    # Minimum interval between Live refreshes (seconds).
    _REFRESH_INTERVAL = 0.08
    _TYPING_CURSOR = "▌"
    _THINKING_SPINNER = "dots2"

    def __init__(self) -> None:
        self._buffer: list[str] = []
        self._reasoning_buffer: list[str] = []
        self._live: Live | None = None
        self._last_refresh: float = 0.0
        self._tool_lines: list[str] = []
        self._thinking_status: Any | None = None
        self._tool_starts: dict[str, float] = {}
        self._subagent_starts: dict[str, float] = {}

    def _ensure_live(self) -> Live:
        if self._live is None:
            live = Live(
                Text(""), console=console, refresh_per_second=12, vertical_overflow="visible"
            )
            live.start()
            self._live = live
        return self._live

    def _start_thinking(self) -> None:
        """Show a thinking spinner when model is reasoning."""
        if self._thinking_status is None and self._live is None:
            self._thinking_status = console.status(
                "[dim]thinking...[/]", spinner=self._THINKING_SPINNER
            )
            self._thinking_status.start()

    def _stop_thinking(self) -> None:
        """Hide the thinking spinner."""
        if self._thinking_status is not None:
            self._thinking_status.stop()
            self._thinking_status = None

    def start_tool(self, name: str) -> None:
        """Record tool execution start time."""
        self._tool_starts[name] = time.monotonic()

    def end_tool(self, name: str) -> float:
        """Return elapsed seconds for a tool execution."""
        started = self._tool_starts.pop(name, None)
        return time.monotonic() - started if started is not None else 0.0

    def start_subagent(self, name: str) -> None:
        """Record subagent execution start time."""
        self._subagent_starts[name] = time.monotonic()

    def end_subagent(self, name: str) -> float:
        """Return elapsed seconds for a subagent execution."""
        started = self._subagent_starts.pop(name, None)
        return time.monotonic() - started if started is not None else 0.0

    def feed_token(self, token: str) -> None:
        self._stop_thinking()
        self._buffer.append(token)
        now = time.monotonic()
        if now - self._last_refresh >= self._REFRESH_INTERVAL:
            self._refresh()
            self._last_refresh = now

    def feed_reasoning(self, token: str) -> None:
        self._reasoning_buffer.append(token)
        if len(self._reasoning_buffer) == 1:
            self._start_thinking()

    def interrupt_for_tool(self, line: str) -> None:
        """Temporarily pause live rendering to print a tool line."""
        self._stop_thinking()
        if self._live is not None:
            self._live.stop()
            self._live = None
        console.print(line, highlight=False)

    def flush(self) -> str:
        """Stop live rendering and return accumulated content."""
        self._stop_thinking()
        content = "".join(self._buffer)

        if self._live is not None:
            # Final render with complete content
            if content.strip():
                self._live.update(Markdown(content))
            self._live.stop()
            self._live = None
        elif content.strip():
            # Never started live (e.g. empty stream) — just print
            console.print(Markdown(content))

        self._buffer.clear()

        reasoning = "".join(self._reasoning_buffer)
        if reasoning:
            print_reasoning(reasoning)
        self._reasoning_buffer.clear()

        return content

    def _refresh(self) -> None:
        """Re-render current buffer as Markdown in the Live display."""
        live = self._ensure_live()
        content = "".join(self._buffer)
        if content.strip():
            live.update(Group(
                Markdown(content),
                Text(self._TYPING_CURSOR, style="dim blink")
            ))
        else:
            live.update(Text("…", style=INFO))


def _badge(label: str, color: str, symbol: str = "") -> Text:
    badge = Text(" ")
    if symbol:
        badge.append(f"{symbol} ", style=f"bold white on {color}")
    badge.append(label, style=f"bold white on {color}")
    badge.append(" ", style=f"bold white on {color}")
    return badge


def _message_line(label: str, msg: str, color: str, symbol: str) -> Text:
    line = Text("  ")
    line += _badge(label, color, symbol)
    line.append(f" {msg}", style="default")
    return line


def _tool_line(label: str, name: str, detail: str, color: str, symbol: str) -> Text:
    line = Text("  ")
    line += _badge(label, color, symbol)
    line.append(f" {name}", style=f"bold {color}")
    if detail:
        line.append(f"  {detail}", style=INFO)
    return line


def _truncate(text: str, max_len: int) -> str:
    text = text.replace("\n", " ").strip()
    if len(text) > max_len:
        return text[: max_len - 3] + "..."
    return text
