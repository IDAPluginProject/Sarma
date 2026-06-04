"""Audit-Slim workflow — compact 4-stage feedback pipeline."""

from __future__ import annotations

from typing import Any

from rich.panel import Panel
from rich.text import Text

from sarma_cli.workflows import Workflow
from sarma_cli.engine.audit_slim_subagents import (
    AUDIT_SLIM_SUBAGENTS,
    AUDIT_SLIM_SUBAGENT_ORDER,
)


class AuditSlimWorkflow(Workflow):
    """Lightweight audit: recon -> hunter <-> verify -> report."""

    def __init__(self) -> None:
        super().__init__(
            name="audit-slim",
            description="Lightweight audit (recon -> hunter <-> verify -> report)",
        )
        self._stages = list(AUDIT_SLIM_SUBAGENT_ORDER)
        self._descriptions = {s["name"]: s["description"] for s in AUDIT_SLIM_SUBAGENTS}

    @property
    def subagents(self) -> tuple[str, ...]:
        return tuple(self._stages)

    def render_graph(self, **kwargs: Any) -> Panel:
        current = kwargs.get("current_stage", "")
        completed = kwargs.get("completed", set())
        failed = kwargs.get("failed", None)
        feedback_loops = kwargs.get("feedback_loops", 0)

        text = Text()
        for i, stage in enumerate(self._stages):
            if stage == failed:
                row_style, icon = "bold #f85149", "✗"
            elif stage == current:
                row_style, icon = "bold #58a6ff", "▶"
            elif stage in completed:
                row_style, icon = "#3fb950", "✓"
            else:
                row_style, icon = "dim", "○"

            label = stage.title()
            desc = self._descriptions.get(stage, "")
            if len(desc) > 52:
                desc = desc[:49] + "..."

            text.append(f"  {icon} {i+1}. {label:<8}", style=row_style)
            if desc:
                desc_style = row_style if stage in (current, failed) else "dim"
                text.append(f"  {desc}", style=desc_style)
            text.append("\n")
            if stage != self._stages[-1]:
                if stage == "hunter":
                    text.append("       ↕ feedback with verify\n", style="dim")
                    if feedback_loops:
                        text.append(f"       ↺ verify → hunter ×{feedback_loops}\n", style="#d29922")
                else:
                    text.append("       │\n", style="dim")

        return Panel(text, title="[bold bright_blue]Audit-Slim[/]", border_style="#a371f7", expand=False)

    def render_sidebar_graph(self, **kwargs: Any) -> Text:
        current_agents = list(kwargs.get("active", []) or [])
        completed = set(kwargs.get("completed", set()) or set())
        failed = str(kwargs.get("failed") or "")
        feedback_loops = int(kwargs.get("feedback_loops") or 0)

        text = Text()
        _append_sidebar_stage(text, "recon", current_agents, completed, failed)
        text.append(" → ", style="dim")
        _append_sidebar_stage(text, "hunter", current_agents, completed, failed)
        text.append(" ↔ ", style="dim")
        _append_sidebar_stage(text, "verify", current_agents, completed, failed)
        text.append(" → ", style="dim")
        _append_sidebar_stage(text, "report", current_agents, completed, failed)
        if feedback_loops:
            text.append(f"\nfeedback  verify → hunter ×{feedback_loops}", style="#d29922")
        if current_agents:
            text.append("\nactive  ", style="dim")
            text.append(", ".join(current_agents), style="bold #58a6ff")
        return text


def _append_sidebar_stage(
    text: Text,
    stage: str,
    active: list[str],
    completed: set[str],
    failed: str,
) -> None:
    if stage == failed:
        icon, style = "✗", "bold #f85149"
    elif stage in active:
        icon, style = "▶", "bold #58a6ff"
    elif stage in completed:
        icon, style = "✓", "#3fb950"
    else:
        icon, style = "○", "dim"
    text.append(f"{icon} {stage}", style=style)
