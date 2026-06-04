"""Audit-Slim graph — compact 4-stage pipeline.

recon -> hunter <-> verify -> report. Reuses the subagent node machinery from
the full audit graph so streaming and per-stage event attribution behave
identically.
"""

from __future__ import annotations

from typing import Any, Literal

from langgraph.graph import StateGraph, START, END
from langgraph.types import Command

from sarma_cli.engine.audit_graph import AuditState, _make_subagent_node, _write_audit_event
from sarma_cli.engine.audit_slim_subagents import (
    AUDIT_SLIM_SUBAGENTS,
    AUDIT_SLIM_SUBAGENT_ORDER,
)

DEFAULT_MAX_VERIFY_FEEDBACK = 3


def _verify_router(state: AuditState) -> Command[Literal["hunter", "report"]]:
    """Route weak verify results back to Hunter, or confirmed results to Report."""
    output = (state.get("stage_outputs") or {}).get("verify", "")
    lower = output.lower()
    normalized = lower.lstrip()
    count = state.get("feedback_count", 0)
    needs_hunter = normalized.startswith("needs-hunter") or any(marker in lower for marker in (
        "needs-hunter",
        "needs hunter",
        "not reliable",
        "not confirmed",
        "insufficient",
        "unsupported",
        "false positive",
        "weak",
    ))
    confirmed = normalized.startswith("verified") or any(marker in lower for marker in (
        "verified",
        "reliable finding",
        "ready for reporting",
    ))

    if needs_hunter and not normalized.startswith("verified") and count < DEFAULT_MAX_VERIFY_FEEDBACK:
        next_count = count + 1
        _write_audit_event({
            "type": "audit_route",
            "from": "verify",
            "to": "hunter",
            "loop": "feedback",
            "count": next_count,
        })
        return Command(update={"feedback_count": next_count}, goto="hunter")

    _write_audit_event({
        "type": "audit_route",
        "from": "verify",
        "to": "report",
    })
    return Command(goto="report")


def build_audit_slim_graph(
    model: Any,
    tools: list[Any],
    system_prompt: str = "",
    subagent_specs: list[dict[str, Any]] | None = None,
    subagent_models: dict[str, Any] | None = None,
    subagent_mcp_allow: dict[str, list[str] | None] | None = None,
    subagent_skills: dict[str, object] | None = None,
) -> Any:
    """Build and compile the audit-slim StateGraph.

    Args:
        model: Default LLM for subagents.
        tools: All available MCP tools (each subagent filters by prefix).
        system_prompt: Kept for API parity with build_audit_graph (unused).
        subagent_specs: Slim subagent specs (defaults to AUDIT_SLIM_SUBAGENTS).
        subagent_models: Optional per-agent model overrides.

    Returns:
        Compiled LangGraph usable with astream().
    """
    specs = subagent_specs or AUDIT_SLIM_SUBAGENTS
    spec_map = {s["name"]: s for s in specs}

    builder = StateGraph(AuditState)
    for name in AUDIT_SLIM_SUBAGENT_ORDER:
        node_fn = _make_subagent_node(
            name,
            spec_map[name],
            model,
            tools,
            subagent_models,
            (subagent_mcp_allow or {}).get(name),
            (subagent_skills or {}).get(name),
        )
        builder.add_node(name, node_fn)

    builder.add_node("verify_check", _verify_router)

    # Harness: recon -> hunter <-> verify -> report
    builder.add_edge(START, "recon")
    builder.add_edge("recon", "hunter")
    builder.add_edge("hunter", "verify")
    builder.add_edge("verify", "verify_check")
    builder.add_edge("report", END)

    return builder.compile()
