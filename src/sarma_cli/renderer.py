"""Rich terminal rendering for Sarma CLI TUI."""

from __future__ import annotations

import time

from rich.console import Console, Group
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text

console = Console()

_BANNER = r"""
  ___  __ _ _ __ _ __ ___   __ _
 / __|/ _` | '__| '_ ` _ \ / _` |
 \__ \ (_| | |  | | | | | | (_| |
 |___/\__,_|_|  |_| |_| |_|\__,_|
"""


def print_banner(model: str = "", mcp_count: int = 0) -> None:
    text = Text()
    text.append(_BANNER.strip(), style="magenta")
    text.append("\n")
    text.append("  Vulnerability Audit Agent", style="bold")
    text.append("\n")
    if model:
        text.append(f"  Model: {model}", style="green")
    if mcp_count:
        text.append(f"  │  MCP: {mcp_count} server(s)", style="cyan")
    text.append("\n  Type /help for commands, Ctrl+C to exit.", style="dim")
    console.print(Panel(text, border_style="magenta", expand=False))


def print_error(msg: str) -> None:
    console.print(f"[bold red]error:[/] {msg}")


def print_warning(msg: str) -> None:
    console.print(f"[yellow]warn:[/] {msg}")


def print_info(msg: str) -> None:
    console.print(f"[dim]{msg}[/]")


def print_success(msg: str) -> None:
    console.print(f"[green]{msg}[/]")


def print_markdown(content: str) -> None:
    if not content.strip():
        return
    console.print(Markdown(content))


def print_tool_start(name: str, args: str) -> None:
    console.print(f"  [cyan]▶ {name}[/] [dim]{_truncate(args, 100)}[/]")


def print_tool_result(name: str, result: str) -> None:
    console.print(f"  [green]✓ {name}[/] [dim]{_truncate(result, 160)}[/]")


def print_tool_error(name: str, error: str) -> None:
    console.print(f"  [red]✗ {name}[/] {_truncate(error, 160)}")


def print_subagent_start(name: str) -> None:
    console.print(f"\n[bold cyan]┌─ {name.upper()} ─────────────────────────[/]")


def print_subagent_done(name: str) -> None:
    console.print(f"[green]└─ {name} complete ─────────────────[/]\n")


def print_reasoning(content: str) -> None:
    if not content.strip():
        return
    console.print(Panel(
        _truncate(content, 500),
        title="[dim]thinking[/]",
        border_style="dim",
        expand=False,
    ))


class StreamPrinter:
    """Accumulates streaming tokens and renders live markdown.

    Uses Rich Live to progressively re-render the accumulated content
    as formatted Markdown. Refreshes at most every 80ms to avoid flicker.
    """

    # Minimum interval between Live refreshes (seconds).
    _REFRESH_INTERVAL = 0.08

    def __init__(self) -> None:
        self._buffer: list[str] = []
        self._reasoning_buffer: list[str] = []
        self._live: Live | None = None
        self._last_refresh: float = 0.0
        self._tool_lines: list[str] = []

    def _ensure_live(self) -> Live:
        if self._live is None:
            self._live = Live(
                Text(""), console=console, refresh_per_second=12, vertical_overflow="visible"
            )
            self._live.start()
        return self._live

    def feed_token(self, token: str) -> None:
        self._buffer.append(token)
        now = time.monotonic()
        if now - self._last_refresh >= self._REFRESH_INTERVAL:
            self._refresh()
            self._last_refresh = now

    def feed_reasoning(self, token: str) -> None:
        self._reasoning_buffer.append(token)

    def interrupt_for_tool(self, line: str) -> None:
        """Temporarily pause live rendering to print a tool line."""
        if self._live is not None:
            self._live.stop()
            self._live = None
        console.print(line, highlight=False)

    def flush(self) -> str:
        """Stop live rendering and return accumulated content."""
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
            live.update(Markdown(content))
        else:
            live.update(Text("…", style="dim"))


def _truncate(text: str, max_len: int) -> str:
    text = text.replace("\n", " ").strip()
    if len(text) > max_len:
        return text[: max_len - 3] + "..."
    return text
