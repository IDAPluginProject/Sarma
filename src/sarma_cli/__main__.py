"""Sarma CLI entry point."""

from __future__ import annotations

import asyncio
import sys

import click

# Ensure UTF-8 output on Windows terminals for Unicode banner/icons
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


@click.group(invoke_without_command=True)
@click.option("--message", "-c", default=None, help="Single message (non-interactive).")
@click.version_option(package_name="sarma-cli")
@click.pass_context
def main(ctx, message):
    """Sarma — AI-powered vulnerability audit agent (CLI)."""
    ctx.ensure_object(dict)

    if ctx.invoked_subcommand is not None:
        return

    from sarma_cli.app import run_interactive, run_oneshot
    from sarma_cli.config import load_config

    config = load_config()

    if message:
        asyncio.run(run_oneshot(config, message))
    else:
        asyncio.run(run_interactive(config))


@main.command()
@click.option("--local", is_flag=True, help="Ensure this workspace has ./.sarma/*.toml copied from global config.")
def init(local):
    """Initialize Sarma config files."""
    from sarma_cli.config import init_config
    init_config(local=local)


@main.command()
@click.argument("name", required=False)
def workflow(name):
    """List available workflows or switch to one.

    \b
    Examples:
      sarma workflow          # list all workflows
      sarma workflow audit    # switch to audit pipeline
      sarma workflow ruflo    # switch to Ruflo mode
    """
    from rich.console import Console
    from sarma_cli.workflows import get_registry, init_workflows

    init_workflows()
    registry = get_registry()
    console = Console()

    if not name:
        console.print("[bold]Available Workflows:[/]")
        for wf in registry.list_workflows():
            marker = "[bold cyan]*[/]" if wf.name == registry.current_name() else "[dim]-[/]"
            console.print(f"  {marker} [cyan]{wf.name:<10}[/] {wf.description}")
    else:
        if registry.switch(name):
            console.print(f"[green]Switched to[/] [cyan]{name}[/] workflow")
        else:
            console.print(f"[red]Unknown workflow:[/] {name}")
            raise SystemExit(1)


@main.command()
def plugin():
    """Manage MCP and skill plugins."""
    from sarma_cli.commands.plugins import cmd_plugin
    from sarma_cli.config import load_config

    restart = asyncio.run(cmd_plugin(load_config()))
    if restart:
        from rich.console import Console

        Console().print("[dim]Restart applies automatically in interactive sessions.[/]")


if __name__ == "__main__":
    main()
