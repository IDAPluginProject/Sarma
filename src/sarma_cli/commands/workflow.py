"""Workflow slash commands."""

from __future__ import annotations

from rich.console import Console
from rich.table import Table
from rich.text import Text

console = Console()


def cmd_workflow(arg: str) -> bool | str:
    """List workflows or switch to a workflow."""
    from sarma_cli.workflows import get_registry

    registry = get_registry()
    if not arg:
        table = Table(
            title="[bold bright_blue]Available Workflows[/bold bright_blue]",
            show_header=True,
            header_style="bold dim",
            border_style="bright_black",
            padding=(0, 1),
        )
        table.add_column("Status", width=3, justify="center")
        table.add_column("Name", style="bold cyan")
        table.add_column("Description", style="default")

        for wf in registry.list_workflows():
            is_active = wf.name == registry.current_name()
            marker = "[bold green]●[/]" if is_active else ""
            name_style = "bold bright_blue" if is_active else "cyan"
            table.add_row(marker, Text(wf.name, style=name_style), wf.description)
        console.print(table)
        return True

    workflow_name = arg.strip()
    if registry.switch(workflow_name):
        console.print(f"[bold white on #3fb950] OK [/] Switched to [bold bright_blue]{workflow_name}[/] workflow")
    else:
        console.print(f"[bold white on #f85149] ERROR [/] Unknown workflow: [bold]{workflow_name}[/]")
    return True
