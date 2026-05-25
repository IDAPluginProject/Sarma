"""Rich terminal rendering for Sarma CLI TUI."""

from __future__ import annotations

from rich.console import Console
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
    text.append("  (audit workflow only)\n", style="dim")
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
    """Accumulates streaming tokens and renders them incrementally."""

    def __init__(self) -> None:
        self._buffer: list[str] = []
        self._reasoning_buffer: list[str] = []

    def feed_token(self, token: str) -> None:
        self._buffer.append(token)
        console.print(token, end="", highlight=False)

    def feed_reasoning(self, token: str) -> None:
        self._reasoning_buffer.append(token)

    def flush(self) -> str:
        content = "".join(self._buffer)
        if self._buffer:
            console.print()
        self._buffer.clear()

        reasoning = "".join(self._reasoning_buffer)
        if reasoning:
            print_reasoning(reasoning)
        self._reasoning_buffer.clear()

        return content


def _truncate(text: str, max_len: int) -> str:
    text = text.replace("\n", " ").strip()
    if len(text) > max_len:
        return text[: max_len - 3] + "..."
    return text
