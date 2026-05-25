"""Slash commands for the Sarma CLI REPL."""

from __future__ import annotations

from typing import Any

from rich.console import Console
from rich.table import Table

from sarma_cli.config import CliConfig
from sarma_cli.graph_view import render_graph
from sarma_cli.status import render_status_panel
from sarma_cli.store import Store

console = Console()

COMMANDS: dict[str, str] = {
    "/help": "Show available commands",
    "/status": "Show MCP, model, gateway, and skills status",
    "/graph": "Show audit pipeline DAG with current progress",
    "/models": "Show configured model",
    "/history": "List past audit conversations",
    "/resume": "Resume a previous conversation (/resume <id>)",
    "/clear": "Clear current session history",
    "/config": "Show current configuration",
    "/exit": "Exit Sarma CLI",
}


def handle_command(
    cmd: str,
    *,
    config: CliConfig,
    store: Store,
    graph_state: dict[str, Any],
    mcp_tool_count: int = 0,
) -> bool | str:
    """Handle a slash command. Returns True if handled, 'exit' to quit, False if unknown."""
    parts = cmd.strip().split(maxsplit=1)
    command = parts[0].lower()
    arg = parts[1] if len(parts) > 1 else ""

    if command == "/help":
        _cmd_help()
        return True
    elif command == "/status":
        console.print(render_status_panel(config, mcp_tool_count))
        return True
    elif command == "/graph":
        console.print(render_graph(**graph_state))
        return True
    elif command == "/models":
        _cmd_models(config)
        return True
    elif command == "/history":
        _cmd_history(store)
        return True
    elif command == "/resume":
        return f"resume:{arg.strip()}" if arg.strip() else True
    elif command == "/clear":
        return "clear"
    elif command == "/config":
        _cmd_config(config)
        return True
    elif command in ("/exit", "/quit", "/q"):
        return "exit"

    return False


def _cmd_help() -> None:
    console.print("[bold]Commands:[/]")
    for cmd, desc in COMMANDS.items():
        console.print(f"  [cyan]{cmd:<12}[/] {desc}")


def _cmd_models(config: CliConfig) -> None:
    model = config.provider.model_name or "(not set)"
    console.print(f"[bold]Model:[/] [green]{model}[/] ({config.provider.api_mode})")


def _cmd_history(store: Store) -> None:
    convs = store.list_conversations()
    if not convs:
        console.print("[dim]No conversations yet.[/]")
        return
    table = Table(title="Conversations", show_lines=False)
    table.add_column("ID", style="cyan", width=14)
    table.add_column("Title", min_width=30)
    table.add_column("Model", style="green")
    table.add_column("Updated", style="dim")
    for c in convs:
        table.add_row(c["id"], c["title"][:50], c["model_name"], c["updated_at"][:16])
    console.print(table)


def _cmd_config(config: CliConfig) -> None:
    console.print("[bold]Configuration:[/]")
    console.print(f"  Model:      [green]{config.provider.model_name or '(not set)'}[/]")
    console.print(f"  API mode:   {config.provider.api_mode}")
    console.print(f"  Base URL:   {config.provider.base_url or '(default)'}")
    key = config.provider.api_key
    console.print(f"  API key:    {'***' + key[-4:] if key else '(not set)'}")
    console.print(f"  Temp:       {config.provider.temperature}")
    if config.mcp_servers:
        names = [s.name for s in config.mcp_servers if s.enabled]
        console.print(f"  MCP:        {', '.join(names)}")
