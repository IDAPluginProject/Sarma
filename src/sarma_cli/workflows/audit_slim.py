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
