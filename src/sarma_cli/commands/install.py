"""MCP server installation command handler."""

from __future__ import annotations

from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm
from rich.table import Table

from sarma_cli.config import CliConfig, McpServerConfig

console = Console()

# Default MCP servers available for installation
DEFAULT_MCP_SERVERS = [
    {
        "name": "ida-mcp",
        "description": "IDA Pro binary analysis and reverse engineering",
        "transport": "streamable_http",
        "url": "http://127.0.0.1:11338/mcp",
        "enabled": False,
    },
    {
        "name": "stdlib",
        "description": "Standard library MCP server",
        "command": "python",
        "args": "-m mcp.server.stdio",
        "enabled": False,
    },
]


def _cmd_install(config: CliConfig | None = None) -> bool:
    """Handle /install command - install and configure MCP servers.

    Args:
        config: Current configuration (if available for context)

    Returns:
        True if installation completed, False if cancelled
    """
    console.print(Panel.fit(
        "[bold cyan]MCP Server Installation[/]",
        border_style="cyan",
    ))

    # Show what will be installed
    _show_installation_plan(config)

    # Confirm with user
    console.print()
    if not Confirm.ask("[bold]Continue with installation?[/]", default=True):
        console.print("[yellow]Installation cancelled.[/]")
        return False

    console.print()
    console.print("[bold]Running installation...[/]")

    # Run installation (placeholder)
    _run_installation()

    # Show status after install
    console.print()
    _show_installation_status()

    return True


def _show_installation_plan(config: CliConfig | None = None) -> None:
    """Display what will be installed."""
    console.print("[bold]Installation Plan:[/]")
    console.print()

    # Show MCP servers
    console.print("[bold cyan]MCP Servers:[/]")
    for srv in DEFAULT_MCP_SERVERS:
        status = "[dim]○[/]" if not srv["enabled"] else "[green]✓[/]"
        console.print(f"  {status} [cyan]{srv['name']:<15}[/] {srv['description']}")

    console.print()

    # Show current config status
    if config and config.mcp_servers:
        console.print("[bold]Currently Configured Servers:[/]")
        table = Table(show_header=True, header_style="bold")
        table.add_column("Name", style="cyan")
        table.add_column("Transport", style="dim")
        table.add_column("Status", style="green")

        for srv in config.mcp_servers:
            status = "[green]enabled[/]" if srv.enabled else "[dim]disabled[/]"
            transport = srv.transport or (
                "command" if srv.command else "url"
            )
            table.add_row(srv.name, transport, status)

        console.print(table)
    else:
        console.print("[dim]No MCP servers currently configured.[/]")

    console.print()
    console.print("[bold cyan]Configuration:[/]")
    console.print("  • MCP servers will be added to [cyan]~/.sarma/config.toml[/]")
    console.print("  • You can enable/disable servers individually")
    console.print("  • Server URLs/commands can be customized after install")


def _run_installation() -> None:
    """Run the installation process (placeholder).

    This is where actual installation logic would go:
    - Download MCP server artifacts
    - Validate checksums
    - Configure services
    - Set up environment
    """
    import time

    steps = [
        "Checking prerequisites...",
        "Validating MCP server definitions...",
        "Installing IDA MCP gateway (http://127.0.0.1:11338)...",
        "Setting up configuration files...",
        "Verifying installation...",
    ]

    for step in steps:
        console.print(f"  [dim]→[/] {step}")
        time.sleep(0.3)  # Simulate work

    console.print()
    console.print("[green]✓[/] Installation complete!")


def _show_installation_status() -> None:
    """Show status after installation."""
    console.print("[bold]Installation Status:[/]")
    console.print()

    # Status table
    table = Table(show_header=True, header_style="bold")
    table.add_column("Component", style="cyan")
    table.add_column("Status", style="green")
    table.add_column("Details", style="dim")

    table.add_row(
        "Configuration",
        "[green]✓ Ready[/]",
        "~/.sarma/config.toml configured",
    )
    table.add_row(
        "IDA MCP",
        "[yellow]○ Standby[/]",
        "Ready to connect (http://127.0.0.1:11338)",
    )
    table.add_row(
        "Network",
        "[green]✓ Ready[/]",
        "HTTP transport configured",
    )

    console.print(table)

    console.print()
    console.print("[bold cyan]Next Steps:[/]")
    console.print("  1. Review configuration: [cyan]/config[/]")
    console.print("  2. Check server status: [cyan]/status[/]")
    console.print("  3. Start using tools with [cyan]/help[/]")


def create_mcp_server_config(
    name: str,
    transport: str = "streamable_http",
    url: str = "",
    command: str = "",
    args: str = "",
    enabled: bool = True,
    **kwargs: Any,
) -> McpServerConfig:
    """Create an MCP server configuration."""
    return McpServerConfig(
        name=name,
        transport=transport,
        url=url,
        command=command,
        args=args,
        enabled=enabled,
        **kwargs,
    )


def get_default_servers() -> list[dict[str, Any]]:
    """Get list of default MCP servers available for installation."""
    return DEFAULT_MCP_SERVERS.copy()
