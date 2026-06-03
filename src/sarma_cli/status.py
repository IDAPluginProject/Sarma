"""Status panel for models, MCP servers, and skills."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from rich.columns import Columns
from rich.console import Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from sarma_cli.config import CliConfig
from sarma_cli.resources.skills import list_available_skills


_BADGE_STYLES = (
    "black on cyan",
    "black on green",
    "black on magenta",
    "black on yellow",
    "white on blue",
)


def _section(title: str) -> Text:
    return Text(title.upper(), style="bold dim")


def _badge(label: str, style: str) -> Text:
    return Text(f" {label} ", style=style)


def _badge_list(labels: Iterable[str], *, styles: tuple[str, ...]) -> Text:
    badges = Text()
    has_badges = False
    for index, label in enumerate(labels):
        has_badges = True
        if index:
            badges.append(" ")
        badges.append_text(_badge(label, styles[index % len(styles)]))
    return badges if has_badges else Text("none", style="dim")


def _subtle_tags(labels: Iterable[str]) -> Text:
    tags = Text()
    has_tags = False
    for index, label in enumerate(labels):
        has_tags = True
        if index:
            tags.append(" ")
        tags.append_text(_badge(label, "dim white on grey23"))
    return tags if has_tags else Text("none", style="dim")


def _masked_api_key(api_key: str) -> Text:
    if not api_key:
        return Text("⚠ missing", style="bold red")
    suffix = api_key[-4:] if len(api_key) > 4 else "••••"
    return Text(f"•••• •••• {suffix}", style="bold green")


def _runtime_status(pool: Any | None, mcp_error: str) -> Text:
    if mcp_error:
        status = Text("● error", style="bold red")
        status.append(f"  {mcp_error}", style="red")
        return status
    if pool is None:
        return Text("● not checked", style="dim")
    if pool.is_connected:
        return Text("● connected", style="bold green")
    return Text("● not connected", style="yellow")


def _workspace_path(path: Path) -> Text:
    home = Path.home()
    try:
        relative_path = path.relative_to(home)
        display_path = Path("~") / relative_path
    except ValueError:
        display_path = str(path)

    workspace = Text("📁 ", style="blue")
    display = Path(display_path)
    parent = str(display.parent)
    name = display.name or str(display_path)
    if parent and parent != ".":
        separator = "\\" if "\\" in str(display) else "/"
        workspace.append(parent, style="dim")
        if not parent.endswith(("\\", "/")):
            workspace.append(separator, style="dim")
    workspace.append(name, style="bold bright_blue")
    return workspace


def _card(title: str, rows: Iterable[tuple[str, Any]]) -> Panel:
    table = Table.grid(padding=(0, 1))
    table.add_column(justify="right", style="dim", no_wrap=True)
    table.add_column(ratio=1)
    table.add_row(_section(title), "")
    for label, value in rows:
        table.add_row(label, value)
    return Panel(table, border_style="bright_black", padding=(1, 2), expand=True)


def render_status_panel(
    config: CliConfig,
    *,
    pool: Any | None = None,
    mcp_error: str = "",
) -> Panel:
    """Render a status panel showing configured runtime resources."""
    provider = config.provider
    model_name = provider.model_name or "not configured"
    model = Text(model_name, style="bold bright_blue" if provider.model_name else "bold red")
    if provider.name:
        model.append(f"  via {provider.name}", style="dim")

    enabled_servers = [server for server in config.mcp_servers if server.enabled]
    server_labels = [f"{server.name} ({server.transport})" for server in enabled_servers]
    tool_names = [getattr(tool, "name", str(tool)) for tool in (pool.tools if pool else [])]
    skills = list_available_skills()

    provider_card = _card(
        "Provider",
        (
            ("model", model),
            ("mode", Text(provider.api_mode, style="cyan")),
            ("api key", _masked_api_key(provider.api_key)),
        ),
    )
    runtime_card = _card(
        "Runtime",
        (
            ("mcp", _runtime_status(pool, mcp_error)),
            ("servers", _badge_list(server_labels, styles=_BADGE_STYLES)),
            ("tools", _subtle_tags(tool_names) if tool_names else Text("none loaded", style="dim")),
        ),
    )
    workspace_card = _card(
        "Workspace",
        (
            ("path", _workspace_path(Path.cwd())),
            ("skills", _subtle_tags(skills)),
        ),
    )

    layout = Group(
        Columns((provider_card, runtime_card), equal=True, expand=True),
        workspace_card,
    )
    return Panel(layout, title="[bold]Status[/]", border_style="blue", expand=False)
