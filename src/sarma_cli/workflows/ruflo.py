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

    def render_sidebar_graph(self, **kwargs) -> Text:
        current_agents = list(kwargs.get("active", []) or [])
        seen_agents = list(kwargs.get("seen", []) or [])
        completed = set(kwargs.get("completed", set()) or set())

        text = Text()
        text.append("primary", style="bold #a371f7")
        text.append("  ● ready\n", style="#3fb950")
        text.append(f"agents run  {len(seen_agents)}\n", style="#7d8590")
        if current_agents:
            text.append("parallel\n" if len(current_agents) > 1 else "active\n", style="dim")
            for agent in current_agents:
                text.append(f"  ▶ {agent}\n", style="bold #58a6ff")
        elif seen_agents:
            text.append("active  idle\n", style="dim")
        else:
            text.append("active  none\n", style="dim")
        done = [agent for agent in seen_agents if agent in completed]
        if done:
            text.append("done\n", style="dim")
            for agent in done[-4:]:
                text.append(f"  ✓ {agent}\n", style="#3fb950")
        return text
