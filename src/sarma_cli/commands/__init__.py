"""Unified command handler for Sarma CLI.

Routes slash commands to appropriate handlers based on current workflow.
Supports: /help, /status, /graph, /workflow, /install, /models, /history,
/resume, /clear, /config, /exit
"""

from __future__ import annotations

from typing import Any

from rich.console import Console
from rich.table import Table

from sarma_cli.config import CliConfig
from sarma_cli.store import Store
from sarma_cli.workflows import get_registry

console = Console()

COMMANDS: dict[str, str] = {
    "/help": "Show available commands",
    "/status": "Show MCP, model, gateway, and skills status",
    "/graph": "Show current workflow execution graph",
    "/workflow": "List workflows or switch workflow (/workflow <name>)",
    "/install": "Install MCP servers and dependencies",
    "/models": "Show configured model",
    "/history": "List past conversations",
    "/resume": "Resume a previous conversation (/resume <id>)",
    "/clear": "Clear current session history",
    "/config": "Configure model / API mode / key / base URL (saves to ~/.sarma)",
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
    """Handle a slash command.

    Routes to workflow-specific handlers when available, falls back to
    unified handlers for global commands.

    Args:
        cmd: The command string (e.g., "/help", "/workflow audit")
        config: CLI configuration
        store: Conversation store
        graph_state: Current workflow graph state
        mcp_tool_count: Number of available MCP tools

    Returns:
        True if handled successfully
        False if unknown command
        'exit' to quit the application
        'clear' to clear session history
        'install' to run MCP installation
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
        _cmd_status(config, mcp_tool_count)
        return True
    elif command == "/graph":
        _cmd_graph(graph_state)
        return True
    elif command == "/workflow":
        return _cmd_workflow(arg)
    elif command == "/install":
        return _cmd_install()
    elif command == "/models":
        _cmd_models(config)
        return True
    elif command == "/history":
        _cmd_history(store)
        return True
    elif command == "/resume":
        return _cmd_resume(arg)
    elif command == "/clear":
        return "clear"
    elif command == "/config":
        _cmd_config(config)
        return True
    elif command in ("/exit", "/quit", "/q"):
        return "exit"

    return False


def _cmd_help() -> None:
    """Display help for all available commands."""
    console.print("[bold]Commands:[/]")
    for cmd, desc in COMMANDS.items():
        console.print(f"  [cyan]{cmd:<12}[/] {desc}")


def _cmd_status(config: CliConfig, mcp_tool_count: int) -> None:
    """Display status of model, MCP servers, gateway, and skills."""
    from sarma_cli.status import render_status_panel

    console.print(render_status_panel(config, mcp_tool_count))


def _cmd_graph(graph_state: dict[str, Any]) -> None:
    """Display the current workflow execution graph."""
    registry = get_registry()
    current = registry.current()

    if current:
        console.print(current.render_graph(**graph_state))
    else:
        console.print("[yellow]No workflow active[/]")


def _cmd_workflow(arg: str) -> bool | str:
    """Handle workflow command: list all or switch to one.

    Usage:
        /workflow          - List all workflows
        /workflow <name>   - Switch to workflow
    """
    registry = get_registry()

    if not arg:
        # List workflows
        console.print("[bold]Available Workflows:[/]")
        for wf in registry.list_workflows():
            marker = "▶" if wf.name == registry.current_name() else "○"
            console.print(f"  {marker} [cyan]{wf.name:<10}[/] {wf.description}")
        return True

    # Switch workflow
    workflow_name = arg.strip()
    if registry.switch(workflow_name):
        console.print(f"[green]✓[/] Switched to [cyan]{workflow_name}[/] workflow")
        return True
    else:
        console.print(f"[red]✗[/] Unknown workflow: {workflow_name}")
        return True


def _cmd_install() -> bool | str:
    """Handle install command for MCP servers and dependencies.

    Returns True if installation completed, 'install' to signal main loop.
    """
    from sarma_cli.commands.install import _cmd_install as install_handler

    if install_handler():
        return True
    return True


def _cmd_models(config: CliConfig) -> None:
    """Display the currently configured model."""
    model = config.provider.model_name or "(not set)"
    api_mode = config.provider.api_mode or "unknown"
    console.print(f"[bold]Model:[/] [green]{model}[/] ({api_mode})")


def _cmd_history(store: Store) -> None:
    """Display list of past conversations."""
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
        conv_id = c.get("id", "unknown")
        title = c.get("title", "Untitled")[:50]
        model_name = c.get("model_name", "unknown")
        updated = c.get("updated_at", "unknown")[:16]
        table.add_row(conv_id, title, model_name, updated)

    console.print(table)


def _cmd_resume(arg: str) -> bool | str:
    """Handle resume command to restore a previous conversation.

    Usage:
        /resume <id>   - Resume conversation by ID

    Returns 'resume:id' to signal the main loop to load the conversation.
    """
    conv_id = arg.strip()
    if conv_id:
        return f"resume:{conv_id}"
    else:
        console.print("[yellow]Usage: /resume <conversation_id>[/]")
        return True


def _cmd_config(config: CliConfig) -> None:
    """Interactively configure the provider and save to ~/.sarma/config.toml.

    Prompts for model, API mode, base URL, and API key. Press Enter to keep
    the current value. Changes apply to the live session immediately (next
    turn) and are persisted to the global config.
    """
    from rich.prompt import Prompt
    from sarma_cli.config import API_MODES, save_global_provider

    p = config.provider
    console.print("[bold]Configure provider[/] [dim](Enter keeps current value)[/]")

    # Model name
    model = Prompt.ask("  Model name", default=p.model_name or None) or ""

    # API mode
    console.print(f"  API mode options: [dim]{', '.join(API_MODES)}[/]")
    api_mode = Prompt.ask(
        "  API mode",
        choices=list(API_MODES),
        default=p.api_mode or API_MODES[0],
    )

    # Base URL (blank = provider default)
    base_url = Prompt.ask(
        "  Base URL [dim](blank for provider default)[/]",
        default=p.base_url or "",
        show_default=bool(p.base_url),
    )

    # API key (masked default)
    masked = ("***" + p.api_key[-4:]) if p.api_key else "(not set)"
    entered = Prompt.ask(
        f"  API key [dim](current: {masked}; Enter keeps)[/]",
        default="",
        password=True,
        show_default=False,
    )
    api_key = entered if entered else p.api_key

    # Apply to live session (Session holds config by reference)
    p.model_name = model.strip()
    p.api_mode = api_mode
    p.base_url = base_url.strip()
    p.api_key = api_key

    # Persist to global config
    try:
        path = save_global_provider(p)
        console.print(f"[green]✓[/] Saved to [cyan]{path}[/]")
    except Exception as exc:
        console.print(f"[red]✗[/] Could not save config: {exc}")
        return

    if p.model_name:
        console.print(f"[dim]Active model:[/] [green]{p.model_name}[/] ({p.api_mode})")
    else:
        console.print("[yellow]No model set yet — run /config again to set one.[/]")
