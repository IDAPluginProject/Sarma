"""Sarma CLI entry point."""

from __future__ import annotations

import sys
from pathlib import Path

_IDE_ROOT = Path(__file__).resolve().parent.parent.parent / "ide"
if str(_IDE_ROOT) not in sys.path:
    sys.path.insert(0, str(_IDE_ROOT))

import asyncio

import click


@click.group(invoke_without_command=True)
@click.option("--model", "-m", default=None, help="Model name override.")
@click.option("--api-key", envvar="SARMA_API_KEY", default=None, help="API key.")
@click.option("--base-url", envvar="SARMA_BASE_URL", default=None, help="API base URL.")
@click.option(
    "--api-mode",
    type=click.Choice(["openai_compatible", "openai_responses", "anthropic"]),
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
def init():
    """Initialize .sarma/ in the current directory."""
    from sarma_cli.config import init_config
    init_config()
