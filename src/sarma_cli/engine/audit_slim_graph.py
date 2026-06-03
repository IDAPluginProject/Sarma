"""Audit-Slim graph — minimal linear 3-stage pipeline.

recon -> verify -> report, with no gapfill/feedback loops. Reuses the
subagent node machinery from the full audit graph so streaming and
per-stage event attribution behave identically.
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import StateGraph, START, END

from sarma_cli.engine.audit_graph import AuditState, _make_subagent_node
from sarma_cli.engine.audit_slim_subagents import (
    AUDIT_SLIM_SUBAGENTS,
    AUDIT_SLIM_SUBAGENT_ORDER,
)


def build_audit_slim_graph(
    model: Any,
    tools: list[Any],
    system_prompt: str = "",
    subagent_specs: list[dict[str, Any]] | None = None,
    subagent_models: dict[str, Any] | None = None,
    subagent_mcp_allow: dict[str, list[str] | None] | None = None,
    subagent_skills: dict[str, object] | None = None,
) -> Any:
    """Build and compile the linear audit-slim StateGraph.

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

    # Linear: recon -> verify -> report
    builder.add_edge(START, "recon")
    builder.add_edge("recon", "verify")
    builder.add_edge("verify", "report")
    builder.add_edge("report", END)

    return builder.compile()
