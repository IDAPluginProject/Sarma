"""ASCII DAG visualization for the 8-stage audit pipeline."""

from __future__ import annotations

from rich.panel import Panel
from rich.text import Text

STAGES = ("recon", "hunt", "validate", "gapfill", "dedupe", "trace", "feedback", "report")

_STAGE_LABELS = {
    "recon": "Recon",
    "hunt": "Hunt",
    "validate": "Validate",
    "gapfill": "Gapfill",
    "dedupe": "Dedupe",
    "trace": "Trace",
    "feedback": "Feedback",
    "report": "Report",
}


def render_graph(
    current_stage: str = "",
    completed: set[str] | None = None,
    failed: str | None = None,
    gapfill_loops: int = 0,
    feedback_loops: int = 0,
) -> Panel:
    """Render the audit DAG as a Rich Panel with colored stage indicators."""
    done = completed or set()
    text = Text()

    for i, stage in enumerate(STAGES):
        # Determine style
        if stage == failed:
            style = "bold red"
            icon = "✗"
        elif stage == current_stage:
            style = "bold cyan"
            icon = "▶"
        elif stage in done:
            style = "green"
            icon = "✓"
        else:
            style = "dim"
            icon = "○"

        label = _STAGE_LABELS[stage]
        text.append(f" {icon} {label}", style=style)

        # Show loop counts
        if stage == "gapfill" and gapfill_loops > 0:
            text.append(f" ×{gapfill_loops}", style="yellow")
        if stage == "feedback" and feedback_loops > 0:
            text.append(f" ×{feedback_loops}", style="yellow")

        # Arrow between stages
        if i < len(STAGES) - 1:
            next_stage = STAGES[i + 1]
            # Show loop arrows for gapfill→hunt and feedback→gapfill
            if stage == "gapfill" and current_stage == "hunt" and gapfill_loops > 0:
                text.append(" ↺ ", style="yellow")
            elif stage == "feedback" and current_stage == "gapfill" and feedback_loops > 0:
                text.append(" ↺ ", style="yellow")
            else:
                text.append(" → ", style="dim")

    return Panel(text, title="[bold]Audit Pipeline[/]", border_style="blue", expand=False)
