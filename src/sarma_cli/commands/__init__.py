"""Unified command handler for Sarma CLI.

Routes slash commands to appropriate handlers based on current workflow.
Supports: /help, /status, /graph, /workflow, /plugin, /models, /history,
/resume, /clear, /compact, /config, /exit
"""

from __future__ import annotations

from typing import Any

from rich.console import Console
from rich.table import Table
from rich.text import Text

from sarma_cli.config import CliConfig
from sarma_cli.store import Store

console = Console()

COMMANDS: dict[str, str] = {
    "/help": "Show available commands",
    "/status": "Show model, MCP servers, and skills status",
    "/graph": "Show current workflow execution graph",
    "/workflow": "List workflows or switch workflow (/workflow <name>)",
    "/plugin": "Manage MCP and skill plugins",
    "/restart": "Restart current workflow runtime",
    "/models": "Show configured models",
    "/history": "List past conversations",
    "/resume": "Resume a previous conversation (/resume <id>)",
    "/clear": "Clear current session history",
    "/compact": "Compact conversation context",
    "/config": "Add or edit named models (saves to ./.sarma/models.toml)",
    "/exit": "Exit Sarma CLI",
}


async def handle_command(
    cmd: str,
    *,
    config: CliConfig,
    store: Store,
    graph_state: dict[str, Any],
    session: Any | None = None,
) -> bool | str:
    """Handle a slash command.

    Routes to workflow-specific handlers when available, falls back to
    unified handlers for global commands.

    Args:
        cmd: The command string (e.g., "/help", "/workflow audit")
        config: CLI configuration
        store: Conversation store
        graph_state: Current workflow graph state

    Returns:
        True if handled successfully
        False if unknown command
        'exit' to quit the application
        'clear' to clear session history
        'compact' to summarize old context
        'restart' to rebuild runtime resources
        'resume:id' to resume a conversation by ID
    """
    parts = cmd.strip().split(maxsplit=1)
    command = parts[0].lower()
    arg = parts[1] if len(parts) > 1 else ""

    # Global command handlers
    if command == "/help":
        _cmd_help()
        return True
    elif command == "/status":
        await _cmd_status(config, session=session)
        return True
    elif command == "/graph":
        _cmd_graph(graph_state)
        return True
    elif command == "/workflow":
        from sarma_cli.commands.workflow import cmd_workflow

        return cmd_workflow(arg)
    elif command == "/plugin":
        from sarma_cli.commands.plugins import cmd_plugin

        if await cmd_plugin(config):
            return "restart"
        return True
    elif command == "/restart":
        return "restart"
    elif command == "/models":
        from sarma_cli.commands.models import cmd_models

        cmd_models(config)
        return True
    elif command == "/history":
        from sarma_cli.commands.history import cmd_history

        cmd_history(store)
        return True
    elif command == "/resume":
        from sarma_cli.commands.history import cmd_resume

        return cmd_resume(arg)
    elif command == "/clear":
        return "clear"
    elif command == "/compact":
        return "compact"
    elif command == "/config":
        from sarma_cli.commands.models import cmd_config

        await cmd_config(config)
        return True
    elif command in ("/exit", "/quit", "/q"):
        return "exit"

    return False


def _cmd_help() -> None:
    """Display help for all available commands."""
    table = Table(
        title="[bold bright_blue]Sarma Commands[/bold bright_blue]",
        show_header=True,
        header_style="bold dim",
        border_style="bright_black",
        padding=(0, 1),
    )
    table.add_column("Command", style="bold cyan", no_wrap=True)
    table.add_column("Description", style="default")

    for cmd, desc in COMMANDS.items():
        table.add_row(cmd, desc)

    console.print(table)


async def _cmd_status(config: CliConfig, *, session: Any | None = None) -> None:
    """Display status of model, MCP servers, and skills."""
    from sarma_cli.status import render_status_panel
    from sarma_cli.workflows import get_registry

    mcp_error = ""
    if session is not None:
        try:
            await session.ensure_mcp_connected(get_registry().current_name() or "ruflo")
        except Exception as exc:
            mcp_error = str(exc)
    console.print(render_status_panel(
        config,
        pool=session.pool if session is not None else None,
        mcp_error=mcp_error,
    ))


def _cmd_graph(graph_state: dict[str, Any]) -> None:
    """Display the current workflow execution graph."""
    from sarma_cli.workflows import get_registry

    registry = get_registry()
    current = registry.current()

    if current:
        console.print(current.render_graph(**graph_state))
    else:
        console.print("[yellow]No workflow active[/]")
