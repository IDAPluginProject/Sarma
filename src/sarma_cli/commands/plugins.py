"""Plugin slash commands."""

from __future__ import annotations

from rich.console import Console

from sarma_cli.config import CliConfig, save_mcp_servers

console = Console()


async def cmd_plugin(config: CliConfig) -> bool:
    """Open the full-screen plugin manager."""
    from sarma_cli.tui.plugin_app import manage_plugins_tui

    result = await manage_plugins_tui(config)
    if result is None:
        console.print("[dim]Plugin manager closed without saving MCP changes.[/]")
        return False

    config.mcp_servers = result.mcp_servers
    try:
        local_path = save_mcp_servers(result.local_mcp_servers, scope="local")
        global_path = save_mcp_servers(result.global_mcp_servers, scope="global")
    except Exception as exc:
        console.print(f"[bold white on #f85149] ERROR [/] Could not save plugin config: {exc}")
        return False
    console.print(
        "[bold white on #3fb950] OK [/] Plugin config saved: "
        f"[bright_blue]{local_path}[/], [bright_blue]{global_path}[/]"
    )
    return result.restart_requested
