"""Sarma CLI entry point."""

from __future__ import annotations

import asyncio

import click

from sarma_cli.config import API_MODES


@click.group(invoke_without_command=True)
@click.option("--model", "-m", default=None, help="Model name override.")
@click.option("--api-key", envvar="SARMA_API_KEY", default=None, help="API key.")
@click.option("--base-url", envvar="SARMA_BASE_URL", default=None, help="API base URL.")
@click.option(
    "--api-mode",
    type=click.Choice(list(API_MODES)),
    default=None,
    help="API mode.",
)
@click.option("--message", "-c", default=None, help="Single message (non-interactive).")
@click.version_option(package_name="sarma-cli")
@click.pass_context
def main(ctx, model, api_key, base_url, api_mode, message):
    """Sarma — AI-powered vulnerability audit agent (CLI)."""
    ctx.ensure_object(dict)
    ctx.obj["overrides"] = {
        "model": model,
        "api_key": api_key,
        "base_url": base_url,
        "api_mode": api_mode,
    }

    if ctx.invoked_subcommand is not None:
        return

    from sarma_cli.app import run_interactive, run_oneshot
    from sarma_cli.config import load_config

    config = load_config(**ctx.obj["overrides"])

    if message:
        asyncio.run(run_oneshot(config, message))
    else:
        asyncio.run(run_interactive(config))


@main.command()
@click.option("--local", is_flag=True, help="Write a per-workspace ./.sarma/config.toml override instead of the global one.")
def init(local):
    """Initialize Sarma config (global ~/.sarma by default; --local for this workspace)."""
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
      sarma workflow chat     # switch to chat mode
    """
    from rich.console import Console
    from sarma_cli.workflows import get_registry, init_workflows

    init_workflows()
    registry = get_registry()
    console = Console()

    if not name:
        console.print("[bold]Available Workflows:[/]")
        for wf in registry.list_workflows():
            marker = "[bold cyan]▶[/]" if wf.name == registry.current_name() else "[dim]○[/]"
            console.print(f"  {marker} [cyan]{wf.name:<10}[/] {wf.description}")
    else:
        if registry.switch(name):
            console.print(f"[green]Switched to[/] [cyan]{name}[/] workflow")
        else:
            console.print(f"[red]Unknown workflow:[/] {name}")
            raise SystemExit(1)


@main.command()
def install():
    """Install and configure MCP servers."""
    from sarma_cli.commands.install import _cmd_install
    _cmd_install()


if __name__ == "__main__":
    main()
