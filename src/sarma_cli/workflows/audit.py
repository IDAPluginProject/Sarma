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

    @property
    def subagents(self) -> tuple[str, ...]:
        return tuple(self._stages)

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

            text.append(f"  {icon} {i+1}. {label:<10}", style=row_style)
            if desc:
                desc_style = row_style if stage in (current, failed) else "dim"
                text.append(f"  {desc}", style=desc_style)
            text.append("\n")

            # gapfill is a side-branch hanging off validate (validate⇄gapfill)
            if stage == "validate":
                gf_current = current == "gapfill"
                gf_done = "gapfill" in completed
                gf_style = "bold #58a6ff" if gf_current else ("#3fb950" if gf_done else "dim")
                gf_icon = "▶" if gf_current else ("✓" if gf_done else "○")
                text.append(f"      └ {gf_icon} gapfill", style=gf_style)
                text.append("  ↕ fills gaps → re-hunt / re-validate", style="dim")
                if gapfill_loops > 0:
                    text.append(f"  ×{gapfill_loops}", style="#d29922")
                text.append("\n")

            if stage == "feedback" and feedback_loops > 0:
                text.append(f"           ↺ ×{feedback_loops} weak → back to Hunt\n", style="#d29922")

        return Panel(text, title="[bold bright_blue]Audit Harness[/]", border_style="#58a6ff", expand=False)

    def render_sidebar_graph(self, **kwargs: Any) -> Text:
        current_agents = list(kwargs.get("active", []) or [])
        completed = set(kwargs.get("completed", set()) or set())
        failed = str(kwargs.get("failed") or "")
        gapfill_loops = int(kwargs.get("gapfill_loops") or 0)
        feedback_loops = int(kwargs.get("feedback_loops") or 0)

        text = Text()
        main_line = ["recon", "hunt", "validate", "dedupe", "trace", "feedback", "report"]
        for index, stage in enumerate(main_line):
            _append_sidebar_stage(text, stage, current_agents, completed, failed)
            if index != len(main_line) - 1:
                text.append(" → ", style="dim")
                if index in {2, 5}:
                    text.append("\n", style="dim")

            if stage == "validate":
                text.append("\n  ")
                text.append("└ ", style="dim")
                _append_sidebar_stage(text, "gapfill", current_agents, completed, failed)
                text.append(" ⇢ hunt/validate", style="dim")
                if gapfill_loops:
                    text.append(f" ×{gapfill_loops}", style="#d29922")
                text.append("\n", style="dim")

            if stage == "feedback" and feedback_loops:
                text.append("  ↺ hunt", style="#d29922")
                text.append(f" ×{feedback_loops}", style="#d29922")

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
