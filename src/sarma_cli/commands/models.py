"""Model-related slash commands."""

from __future__ import annotations

from rich.console import Console
from rich.table import Table

from sarma_cli.config import CliConfig, save_agents, save_models

console = Console()


def cmd_models(config: CliConfig) -> None:
    """Display configured models."""
    table = Table(
        title="[bold bright_blue]Configured Models[/bold bright_blue]",
        show_header=True,
        header_style="bold dim",
        border_style="bright_black",
        padding=(0, 1),
    )
    table.add_column("Active", width=3, justify="center")
    table.add_column("Name", style="bold cyan")
    table.add_column("Model", style="green")
    table.add_column("API Mode", style="magenta")
    table.add_column("Base URL", style="dim")
    table.add_column("API Key")

    for model in config.models:
        marker = "[bold green]●[/]" if model.name == config.active_model else ""
        key = f"[dim]••••[/] [green]{model.api_key[-4:]}[/]" if model.api_key else "[bold red]⚠ missing[/]"
        table.add_row(
            marker,
            model.name,
            model.model_name or "[dim italic](not set)[/]",
            model.api_mode,
            model.base_url or "[dim italic](provider default)[/]",
            key,
        )

    console.print(table)


async def cmd_config(config: CliConfig) -> None:
    """Open the full-screen workspace configuration TUI."""
    from sarma_cli.tui.config_app import configure_workspace_tui

    result = await configure_workspace_tui(config)
    if result is None:
        console.print("[dim]Config closed without saving.[/]")
        return

    config.models = result.models
    config.active_model = result.active_model
    config.agents = result.agents
    try:
        models_path = save_models(config)
        agents_path = save_agents(config)
    except Exception as exc:
        console.print(f"[bold white on #f85149] ERROR [/] Could not save config: {exc}")
        return

    active = config.provider.name or "default"
    model_info = config.provider.model_name or "not set"
    console.print(
        f"[bold white on #3fb950] OK [/] Config saved to [bright_blue]{models_path}[/] and [bright_blue]{agents_path}[/]\n"
        f"      Active model: [bold bright_blue]{active}[/] [dim]({model_info})[/]"
    )
