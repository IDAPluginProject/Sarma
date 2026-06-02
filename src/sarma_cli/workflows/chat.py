"""Chat workflow — direct single-agent conversation."""

from __future__ import annotations

from rich.panel import Panel
from rich.text import Text

from sarma_cli.workflows import Workflow


class ChatWorkflow(Workflow):
    """Direct conversation with the agent, no pipeline stages."""

    def __init__(self) -> None:
        super().__init__(name="chat", description="Chat with agent (default)", is_default=True)

    def render_graph(self, **kwargs) -> Panel:
        text = Text("Chat mode: Direct conversation with agent\n")
        text.append("No pipeline stages — just chat history.", style="dim")
        return Panel(text, title="[bold]Chat Workflow[/]", border_style="green")
