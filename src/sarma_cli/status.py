"""Status detection for MCP servers, models, and skills."""

from __future__ import annotations

import urllib.request
import urllib.error
from pathlib import Path
from typing import Any

from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from sarma_cli.config import CliConfig
from sarma_cli import paths


def _check_server(name: str, url: str) -> tuple[str, str]:
    """Ping an MCP server endpoint; returns (status_icon, status_text)."""
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=3) as resp:
            if resp.status == 200:
                return ("[green]✓[/]", "[green]online[/]")
            return ("[yellow]?[/]", f"[yellow]HTTP {resp.status}[/]")
    except Exception:
        return ("[dim]○[/]", "[dim]offline[/]")


def detect_skills() -> list[str]:
    """Scan global (~/.sarma) and local (./.sarma) skills directories."""
    found: list[str] = []
    seen: set[str] = set()
    for skills_dir in (paths.global_skills_dir(), paths.local_skills_dir()):
        if not skills_dir.exists():
            continue
        for d in skills_dir.iterdir():
            if d.is_dir() and d.name not in seen:
                seen.add(d.name)
                found.append(d.name)
    return found


def render_status_panel(config: CliConfig, mcp_tool_count: int = 0) -> Panel:
    """Render a status panel showing model, all MCP servers, and skills."""
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("key", style="bold")
    table.add_column("value")

    # Providers
    table.add_row("━ Providers", "")
    for i, p in enumerate(config.providers or []):
        marker = "[bold cyan]▶[/]" if p.default else "  "
        name = p.name or "Provider " + str(i + 1)
        model = p.model_name or "(not set)"
        table.add_row(
            f"{marker} {name}",
            f"[green]{model}[/]" if p.model_name else f"[red]{model}[/]",
        )
        table.add_row("", f"{p.api_mode}  |  {'***' + p.api_key[-4:] if p.api_key else '(no key)'}")

    if not config.providers:
        table.add_row("  No providers configured", "[red]Use /config to add one[/]")

    # MCP servers
    table.add_row("━ MCP", "")
    if config.mcp_servers:
        for srv in config.mcp_servers:
            status = "[green]✓ enabled[/]" if srv.enabled else "[dim]○ disabled[/]"
            transport = srv.url or srv.command or srv.transport
            icon = "HTTP" if srv.url else ("CMD" if srv.command else srv.transport.upper())
            table.add_row(
                f"  {status} {srv.name}",
                f"[dim]{icon}[/] {transport[:60]}",
            )
        if mcp_tool_count:
            table.add_row("  Tools available", str(mcp_tool_count))
    else:
        table.add_row("  None configured", "[dim]Add servers in ~/.sarma/config.toml[/]")

    # Skills
    table.add_row("━ Skills", "")
    skills = detect_skills()
    if skills:
        for s in skills:
            table.add_row(f"  {s}", "[dim]loaded[/]")
    else:
        table.add_row("  None", "[dim]Add skill dirs under ~/.sarma/skills/[/]")

    # Workspace
    table.add_row("━ Workflow", "")
    table.add_row("  Workspace", str(Path.cwd()))

    return Panel(table, title="[bold]Status[/]", border_style="blue", expand=False)
