"""Right sidebar showing workflow and runtime status."""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.containers import Vertical
from textual.widgets import Static


class Sidebar(Vertical):
    """Right sidebar with workflow status, model info, and runtime state."""

    def __init__(self) -> None:
        super().__init__(id="sidebar")
        self._workflow_name = "ruflo"
        self._current_agents: list[str] = []
        self._model_name = ""
        self._model_assignments: list[tuple[str, str]] = []
        self._mcp_connected = False
        self._mcp_servers: list[Any] = []
        self._conversation_id = ""
        self._seen_agents: list[str] = []
        self._completed_agents: set[str] = set()
        self._failed_agent = ""
        self._gapfill_loops = 0
        self._feedback_loops = 0

    def compose(self):
        with Static(classes="sidebar-section"):
            yield Static("Workflow", classes="sidebar-title")
            yield Static(self._workflow_name, id="wf-name", classes="sidebar-value sidebar-active")
            yield Static("Agents: idle", id="agent-name", classes="sidebar-value sidebar-inactive")

        with Static(classes="sidebar-section"):
            yield Static("Model", classes="sidebar-title")
            yield Static(self._render_models(), id="model-name", classes="sidebar-value")

        with Static(classes="sidebar-section"):
            yield Static("MCP", classes="sidebar-title")
            yield Static(
                "● connected" if self._mcp_connected else "○ not connected",
                id="mcp-status",
                classes="sidebar-value sidebar-active" if self._mcp_connected else "sidebar-value sidebar-inactive",
            )
            yield Static("", id="mcp-servers", classes="sidebar-value sidebar-mcp-list")

        with Static(classes="sidebar-section"):
            yield Static("Session", classes="sidebar-title")
            yield Static(self._conversation_id or "new", id="session-id", classes="sidebar-value")

        with Static(classes="sidebar-section sidebar-graph-section"):
            yield Static("Graph", classes="sidebar-title")
            yield Static(self._render_workflow_graph(), id="workflow-graph", classes="sidebar-value sidebar-graph")

    def update_workflow(self, name: str, agents: str | list[str] | tuple[str, ...] = "") -> None:
        """Update the active workflow name and current agents."""
        workflow_changed = name != self._workflow_name
        self._workflow_name = name
        if workflow_changed:
            self.reset_run_state()
        if isinstance(agents, str):
            self._current_agents = [agents] if agents else []
        else:
            self._current_agents = [agent for agent in agents if agent]
        wf_name = self.query_one("#wf-name", Static)
        agent_label = self.query_one("#agent-name", Static)
        wf_name.update(name)
        wf_name.classes = "sidebar-value sidebar-active"
        if self._current_agents:
            label = "Agent" if len(self._current_agents) == 1 else "Agents"
            agent_label.update(f"{label}: {', '.join(self._current_agents)}")
            agent_label.classes = "sidebar-value sidebar-active"
        else:
            agent_label.update("Agents: idle")
            agent_label.classes = "sidebar-value sidebar-inactive"
        self._refresh_graph()

    def update_model(self, name: str) -> None:
        """Update the displayed model name."""
        self.update_models([("primary", name)])

    def update_models(self, assignments: list[tuple[str, str]]) -> None:
        """Update displayed model assignments for the active workflow."""
        self._model_assignments = [
            (agent or "agent", model or "not configured")
            for agent, model in assignments
        ]
        name = ", ".join(model for _agent, model in self._model_assignments)
        self._model_name = name
        model_label = self.query_one("#model-name", Static)
        model_label.update(self._render_models())
        if self._model_assignments:
            model_label.classes = "sidebar-value sidebar-active"
        else:
            model_label.classes = "sidebar-value sidebar-inactive"

    def update_mcp(self, connected: bool, servers: list[Any] | None = None) -> None:
        """Update MCP connection status."""
        self._mcp_connected = connected
        self._mcp_servers = list(servers or [])
        status = self.query_one("#mcp-status", Static)
        status.update("● connected" if connected else "○ not connected")
        status.classes = (
            "sidebar-value sidebar-active"
            if connected
            else "sidebar-value sidebar-inactive"
        )
        self.query_one("#mcp-servers", Static).update(
            self._render_mcp_servers()
        )

    def update_session(self, conversation_id: str) -> None:
        """Update the conversation ID display."""
        self._conversation_id = conversation_id
        session_label = self.query_one("#session-id", Static)
        session_label.update(conversation_id or "new")

    def reset_run_state(self) -> None:
        """Reset per-turn workflow graph state."""
        self._current_agents = []
        self._seen_agents = []
        self._completed_agents = set()
        self._failed_agent = ""
        self._gapfill_loops = 0
        self._feedback_loops = 0
        self._refresh_graph()

    def update_run_state(
        self,
        *,
        active: list[str] | None = None,
        seen: list[str] | None = None,
        completed: set[str] | None = None,
        failed: str = "",
        gapfill_loops: int | None = None,
        feedback_loops: int | None = None,
    ) -> None:
        """Update the bottom workflow graph from runtime state."""
        if active is not None:
            self._current_agents = [agent for agent in active if agent]
        if seen is not None:
            self._seen_agents = list(dict.fromkeys(agent for agent in seen if agent))
        if completed is not None:
            self._completed_agents = set(completed)
        self._failed_agent = failed
        if gapfill_loops is not None:
            self._gapfill_loops = gapfill_loops
        if feedback_loops is not None:
            self._feedback_loops = feedback_loops
        self._refresh_graph()

    def _render_mcp_servers(self) -> Text:
        if not self._mcp_servers:
            return Text("none", style="dim")
        text = Text()
        for index, server in enumerate(self._mcp_servers):
            if index:
                text.append("\n")
            name = str(_status_value(server, "name", "mcp"))
            connected = bool(_status_value(server, "connected", False))
            tool_count = int(_status_value(server, "tool_count", 0) or 0)
            text.append(name, style="bold #e6edf3")
            text.append("  ")
            if connected:
                text.append("● connected", style="bold #3fb950")
            else:
                text.append("○ not connected", style="#7d8590")
            text.append(f"  {tool_count}", style="#7d8590")
        return text

    def _render_models(self) -> Text:
        if not self._model_assignments:
            return Text(self._model_name or "not configured", style="dim")
        text = Text()
        for index, (agent, model) in enumerate(self._model_assignments):
            if index:
                text.append("\n")
            text.append(agent, style="bold #e6edf3")
            text.append("  ")
            if model == "not configured":
                text.append(model, style="#7d8590")
            else:
                text.append(model, style="#3fb950")
        return text

    def _refresh_graph(self) -> None:
        try:
            self.query_one("#workflow-graph", Static).update(self._render_workflow_graph())
        except Exception:
            return

    def _render_workflow_graph(self) -> Text:
        if self._workflow_name == "ruflo":
            return self._render_ruflo_graph()
        if self._workflow_name == "audit-slim":
            return self._render_audit_slim_graph()
        if self._workflow_name == "audit":
            return self._render_audit_graph()
        text = Text()
        text.append(self._workflow_name or "unknown", style="bold #e6edf3")
        text.append("\n○ idle", style="dim")
        return text

    def _render_ruflo_graph(self) -> Text:
        text = Text()
        text.append("primary", style="bold #a371f7")
        text.append("  ● ready\n", style="#3fb950")
        text.append(f"agents run  {len(self._seen_agents)}\n", style="#7d8590")
        if self._current_agents:
            text.append("parallel\n" if len(self._current_agents) > 1 else "active\n", style="dim")
            for agent in self._current_agents:
                text.append(f"  ▶ {agent}\n", style="bold #58a6ff")
        elif self._seen_agents:
            text.append("active  idle\n", style="dim")
        else:
            text.append("active  none\n", style="dim")
        completed = [agent for agent in self._seen_agents if agent in self._completed_agents]
        if completed:
            text.append("done\n", style="dim")
            for agent in completed[-4:]:
                text.append(f"  ✓ {agent}\n", style="#3fb950")
        return text

    def _render_stage_graph(self, stages: list[str]) -> Text:
        text = Text()
        for index, stage in enumerate(stages):
            if stage == self._failed_agent:
                icon, style = "✗", "bold #f85149"
            elif stage in self._current_agents:
                icon, style = "▶", "bold #58a6ff"
            elif stage in self._completed_agents:
                icon, style = "✓", "#3fb950"
            else:
                icon, style = "○", "dim"
            text.append(f"{icon} {stage}", style=style)
            if index != len(stages) - 1:
                connector = " ↔ " if stage in {"validate", "gapfill"} else " → "
                text.append(connector, style="dim")
                if (index + 1) % 3 == 0:
                    text.append("\n", style="dim")
        if self._current_agents:
            text.append("\nactive  ", style="dim")
            text.append(", ".join(self._current_agents), style="bold #58a6ff")
        return text

    def _render_audit_slim_graph(self) -> Text:
        text = Text()
        self._append_stage(text, "recon")
        text.append(" → ", style="dim")
        self._append_stage(text, "hunter")
        text.append(" ↔ ", style="dim")
        self._append_stage(text, "verify")
        text.append(" → ", style="dim")
        self._append_stage(text, "report")
        if self._feedback_loops:
            text.append(f"\nfeedback  verify → hunter ×{self._feedback_loops}", style="#d29922")
        if self._current_agents:
            text.append("\nactive  ", style="dim")
            text.append(", ".join(self._current_agents), style="bold #58a6ff")
        return text

    def _render_audit_graph(self) -> Text:
        text = Text()
        main_line = ["recon", "hunt", "validate", "dedupe", "trace", "feedback", "report"]
        for index, stage in enumerate(main_line):
            self._append_stage(text, stage)
            if index != len(main_line) - 1:
                text.append(" → ", style="dim")
                if index in {2, 5}:
                    text.append("\n", style="dim")

            if stage == "validate":
                text.append("\n  ")
                text.append("└ ", style="dim")
                self._append_stage(text, "gapfill")
                text.append(" ⇢ hunt/validate", style="dim")
                if self._gapfill_loops:
                    text.append(f" ×{self._gapfill_loops}", style="#d29922")
                text.append("\n", style="dim")

            if stage == "feedback" and self._feedback_loops:
                text.append("  ↺ hunt", style="#d29922")
                text.append(f" ×{self._feedback_loops}", style="#d29922")

        if self._current_agents:
            text.append("\nactive  ", style="dim")
            text.append(", ".join(self._current_agents), style="bold #58a6ff")
        return text

    def _append_stage(self, text: Text, stage: str) -> None:
        if stage == self._failed_agent:
            icon, style = "✗", "bold #f85149"
        elif stage in self._current_agents:
            icon, style = "▶", "bold #58a6ff"
        elif stage in self._completed_agents:
            icon, style = "✓", "#3fb950"
        else:
            icon, style = "○", "dim"
        text.append(f"{icon} {stage}", style=style)


def _status_value(status: Any, key: str, default: Any = None) -> Any:
    if isinstance(status, dict):
        return status.get(key, default)
    return getattr(status, key, default)
