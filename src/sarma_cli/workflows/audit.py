"""Audit workflow — 8-stage pipeline with progress visualization."""

from __future__ import annotations

from typing import Any

from rich.panel import Panel
from rich.text import Text

from sarma_cli.workflows import Workflow
from sarma_cli.engine.audit_subagents import AUDIT_SUBAGENTS, AUDIT_SUBAGENT_ORDER


class AuditWorkflow(Workflow):
    """8-stage vulnerability audit pipeline."""

    def __init__(self) -> None:
        super().__init__(name="audit", description="Full audit pipeline with 8 stages")
        self._stages = list(AUDIT_SUBAGENT_ORDER)
        self._descriptions = {s["name"]: s["description"] for s in AUDIT_SUBAGENTS}

    def render_graph(self, **kwargs: Any) -> Panel:
        """Render the audit harness — main line plus loop annotations.

        Structure (not a straight line):
          recon → hunt → validate →(gaps?)→ gapfill → hunt/validate
                                  →(ok)→ dedupe → trace → feedback
          feedback →(weak?)→ hunt   (long loop)   →(ok)→ report
        """
        current = kwargs.get("current_stage", "")
        completed = kwargs.get("completed", set())
        failed = kwargs.get("failed", None)
        gapfill_loops = kwargs.get("gapfill_loops", 0)
        feedback_loops = kwargs.get("feedback_loops", 0)

        # Display order puts gapfill as an indented side-branch off validate.
        main_line = ["recon", "hunt", "validate", "dedupe", "trace", "feedback", "report"]

        text = Text()
        for i, stage in enumerate(main_line):
            if stage == failed:
                row_style, icon = "bold red", "✗"
            elif stage == current:
                row_style, icon = "bold cyan", "▶"
            elif stage in completed:
                row_style, icon = "green", "✓"
            else:
                row_style, icon = "dim", "○"

            label = stage.title()
            desc = self._descriptions.get(stage, "")
            if len(desc) > 52:
                desc = desc[:49] + "..."

            text.append(f"  {icon} {i+1}. {label:<10}", style=row_style)
            if desc:
                desc_style = row_style if stage in (current, failed) else "dim"
                text.append(f"  {desc}", style=desc_style)
            text.append("\n")

            # gapfill is a side-branch hanging off validate (validate⇄gapfill)
            if stage == "validate":
                gf_current = current == "gapfill"
                gf_done = "gapfill" in completed
                gf_style = "bold cyan" if gf_current else ("green" if gf_done else "dim")
                gf_icon = "▶" if gf_current else ("✓" if gf_done else "○")
                text.append(f"      └ {gf_icon} gapfill", style=gf_style)
                text.append("  ↕ fills gaps → re-hunt / re-validate", style="dim")
                if gapfill_loops > 0:
                    text.append(f"  ×{gapfill_loops}", style="yellow")
                text.append("\n")

            if stage == "feedback" and feedback_loops > 0:
                text.append(f"           ↺ ×{feedback_loops} weak → back to Hunt\n", style="yellow")

        return Panel(text, title="[bold]Audit Harness[/]", border_style="blue", expand=False)
