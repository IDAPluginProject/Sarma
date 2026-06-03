"""Conversation history slash commands."""

from __future__ import annotations

from rich.console import Console
from rich.table import Table

from sarma_cli.store import Store

console = Console()


def cmd_history(store: Store) -> None:
    """Display list of past conversations."""
    convs = store.list_conversations()
    if not convs:
        console.print("[dim]No conversations yet.[/]")
        return

    table = Table(
        title="[bold bright_blue]Conversation History[/bold bright_blue]",
        show_header=True,
        header_style="bold dim",
        border_style="bright_black",
        padding=(0, 1),
    )
    table.add_column("ID", style="bold cyan", width=14)
    table.add_column("Title", min_width=30, style="default")
    table.add_column("Model", style="green")
    table.add_column("Updated", style="dim")

    for c in convs:
        conv_id = c.get("id", "unknown")
        title = c.get("title", "Untitled")[:50]
        model_name = c.get("model_name", "unknown")
        updated = c.get("updated_at", "unknown")[:16]
        table.add_row(conv_id, title, model_name, updated)

    console.print(table)


def cmd_resume(arg: str) -> bool | str:
    """Return resume signal for the main loop."""
    conv_id = arg.strip()
    if conv_id:
        return f"resume:{conv_id}"
    console.print("[bold white on #d29922] USAGE [/] /resume [dim]<conversation_id>[/]")
    return True
