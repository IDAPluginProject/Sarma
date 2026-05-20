"""Native LangGraph audit pipeline.

Replaces deepagents' create_deep_agent with an explicit StateGraph that
orchestrates 8 specialist subagents through a vulnerability discovery
pipeline with gapfill and feedback loops.
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, Literal

from langchain_core.messages import BaseMessage, HumanMessage
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import create_react_agent
from langgraph.types import Command
from typing_extensions import TypedDict

from app.chat.audit_subagents import AUDIT_SUBAGENTS, AUDIT_SUBAGENT_ORDER

DEFAULT_MAX_GAPFILL = 3
DEFAULT_MAX_FEEDBACK = 2


class AuditState(TypedDict):
    """State flowing through the audit pipeline."""

    messages: Annotated[list[BaseMessage], add_messages]
    stage_outputs: dict[str, str]
    gapfill_count: int
    feedback_count: int
    current_stage: str


def _filter_tools_by_prefix(
    all_tools: list[Any], prefixes: list[str] | None
) -> list[Any]:
    """Filter tools whose name starts with any of the given prefixes."""
    if not prefixes or not all_tools:
        return list(all_tools)
    matched = [t for t in all_tools if any(t.name.startswith(p) for p in prefixes)]
    return matched if matched else list(all_tools)


def _build_context(stage_name: str, stage_outputs: dict[str, str]) -> str:
    """Build context message for a subagent from prior stage outputs."""
    if not stage_outputs:
        return "Begin the audit. No prior stage outputs yet."
    parts = [f"## Prior stage outputs\n"]
    for name, output in stage_outputs.items():
        parts.append(f"### {name}\n{output[:4000]}\n")
    parts.append(f"\n## Your task\nYou are the **{stage_name}** agent. "
                 "Proceed with your role based on the context above.")
    return "\n".join(parts)


def _make_subagent_node(
    name: str,
    spec: dict[str, Any],
    default_model: Any,
    all_tools: list[Any],
    subagent_models: dict[str, Any] | None = None,
):
    """Create an async node function that runs a react agent for one stage."""
    model = (
        (subagent_models or {}).get(name)
        or spec.get("model")
        or default_model
    )
    tools = _filter_tools_by_prefix(all_tools, spec.get("_tool_prefixes"))
    agent = create_react_agent(model, tools, prompt=spec["system_prompt"])

    async def node(state: AuditState) -> dict[str, Any]:
        context = _build_context(name, state.get("stage_outputs", {}))
        result = await agent.ainvoke({"messages": [HumanMessage(content=context)]})
        last_msg = result["messages"][-1].content if result["messages"] else ""
        new_outputs = dict(state.get("stage_outputs", {}))
        new_outputs[name] = last_msg
        return {
            "stage_outputs": new_outputs,
            "current_stage": name,
            "messages": result["messages"],
        }

    node.__name__ = name
    return node


def _gapfill_router(state: AuditState) -> Command[Literal["hunt", "dedupe"]]:
    """Route: if gapfill found gaps and budget remains, loop back to hunt."""
    output = (state.get("stage_outputs") or {}).get("gapfill", "")
    lower = output.lower()
    no_gaps = "no gaps" in lower or "no action" in lower or "no additional" in lower
    count = state.get("gapfill_count", 0)

    if not no_gaps and count < DEFAULT_MAX_GAPFILL:
        return Command(
            update={"gapfill_count": count + 1},
            goto="hunt",
        )
    return Command(goto="dedupe")


def _feedback_router(state: AuditState) -> Command[Literal["gapfill", "report"]]:
    """Route: if feedback flags weak findings, loop back to gapfill."""
    output = (state.get("stage_outputs") or {}).get("feedback", "")
    lower = output.lower()
    is_weak = "weak" in lower or "insufficient" in lower or "needs more" in lower
    count = state.get("feedback_count", 0)

    if is_weak and count < DEFAULT_MAX_FEEDBACK:
        return Command(
            update={"feedback_count": count + 1},
            goto="gapfill",
        )
    return Command(goto="report")


def build_audit_graph(
    model: Any,
    tools: list[Any],
    system_prompt: str = "",
    subagent_specs: list[dict[str, Any]] | None = None,
    subagent_models: dict[str, Any] | None = None,
) -> Any:
    """Build and compile the audit pipeline StateGraph.

    Args:
        model: Default LLM for subagents.
        tools: All available MCP tools (each subagent filters by prefix).
        system_prompt: Unused here (orchestrator prompt is implicit in graph
                       structure). Kept for API compatibility.
        subagent_specs: List of subagent spec dicts from AUDIT_SUBAGENTS.
        subagent_models: Optional per-agent model overrides.

    Returns:
        Compiled LangGraph that can be used with astream().
    """
    specs = subagent_specs or AUDIT_SUBAGENTS
    spec_map = {s["name"]: s for s in specs}

    builder = StateGraph(AuditState)

    for name in AUDIT_SUBAGENT_ORDER:
        spec = spec_map[name]
        node_fn = _make_subagent_node(
            name, spec, model, tools, subagent_models
        )
        builder.add_node(name, node_fn)

    builder.add_node("gapfill_check", _gapfill_router)
    builder.add_node("feedback_check", _feedback_router)

    # Linear pipeline: recon → hunt → validate → gapfill → gapfill_check
    builder.add_edge(START, "recon")
    builder.add_edge("recon", "hunt")
    builder.add_edge("hunt", "validate")
    builder.add_edge("validate", "gapfill")
    builder.add_edge("gapfill", "gapfill_check")
    # gapfill_check routes to hunt (loop) or dedupe (forward)
    builder.add_edge("dedupe", "trace")
    builder.add_edge("trace", "feedback")
    builder.add_edge("feedback", "feedback_check")
    # feedback_check routes to gapfill (loop) or report (forward)
    builder.add_edge("report", END)

    return builder.compile()
