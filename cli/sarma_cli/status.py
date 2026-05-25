"""Status detection for MCP servers, models, skills, and gateway."""

from __future__ import annotations

import urllib.request
import urllib.error
from pathlib import Path
from typing import Any

from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from sarma_cli.config import CliConfig, SARMA_DIR


def check_gateway(url: str = "http://127.0.0.1:11338/health") -> bool:
    """Check if IDA-MCP gateway is reachable."""
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=3) as resp:
            return resp.status == 200
    except Exception:
        return False


def detect_skills() -> list[str]:
    """Scan .sarma/skills/ for available skill directories."""
    skills_dir = SARMA_DIR / "skills"
    if not skills_dir.exists():
        return []
    return [d.name for d in skills_dir.iterdir() if d.is_dir()]


def render_status_panel(config: CliConfig, mcp_tool_count: int = 0) -> Panel:
    """Render a status panel showing model, MCP, gateway, and skills info."""
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("key", style="bold")
    table.add_column("value")

    # Model
    model = config.provider.model_name or "(not configured)"
    table.add_row("Model", f"[green]{model}[/]" if config.provider.model_name else f"[red]{model}[/]")
    table.add_row("API Mode", config.provider.api_mode)
    table.add_row("API Key", "***" + config.provider.api_key[-4:] if config.provider.api_key else "[red](missing)[/]")

    # MCP
    server_names = [s.name for s in config.mcp_servers if s.enabled]
    if server_names:
        table.add_row("MCP Servers", ", ".join(server_names))
        table.add_row("MCP Tools", str(mcp_tool_count) if mcp_tool_count else "[dim]not connected[/]")
    else:
        table.add_row("MCP Servers", "[dim]none configured[/]")

    # Gateway
    gw_ok = check_gateway()
    table.add_row("IDA Gateway", "[green]online[/]" if gw_ok else "[dim]offline[/]")

    # Skills
    skills = detect_skills()
    table.add_row("Skills", ", ".join(skills) if skills else "[dim]none[/]")

    # Workspace
    table.add_row("Workspace", str(Path.cwd()))

    return Panel(table, title="[bold]Status[/]", border_style="blue", expand=False)
