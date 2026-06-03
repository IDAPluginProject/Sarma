"""Ruflo workflow — conversational primary agent with subagent delegation."""

from __future__ import annotations

from rich.panel import Panel
from rich.text import Text

from sarma_cli.workflows import Workflow


class RufloWorkflow(Workflow):
    """Ruflo conversation with controlled subagent delegation."""

    def __init__(self) -> None:
        super().__init__(
            name="ruflo",
            description="Ruflo with subagent delegation (default)",
            is_default=True,
        )

    def render_graph(self, **kwargs) -> Panel:
        text = Text("Ruflo mode: primary agent + focused subagents\n", style="bold")
        text.append(
            "Subagents return compact result templates to control context growth.",
            style="dim",
        )
        return Panel(text, title="[bold bright_blue]Ruflo Workflow[/]", border_style="#3fb950")
