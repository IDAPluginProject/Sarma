"""Native LangGraph audit pipeline.

Replaces deepagents' create_deep_agent with an explicit StateGraph that
orchestrates 8 specialist subagents through a vulnerability discovery
pipeline with gapfill and feedback loops.

Each subagent node wraps a ``create_react_agent`` and streams its events
via ``get_stream_writer()`` so that the outer ``astream(subgraphs=True)``
can attribute tokens and tool calls to the correct subagent.
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, Literal

from langchain_core.messages import BaseMessage, HumanMessage
from langgraph.config import get_stream_writer
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import create_react_agent
from langgraph.types import Command
from typing_extensions import TypedDict

from sarma_cli.engine.audit_subagents import AUDIT_SUBAGENTS, AUDIT_SUBAGENT_ORDER

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
    """Create an async node function that runs a react agent for one stage.

    Uses ``astream`` instead of ``ainvoke`` so that the inner agent's
    streaming events (tokens, tool calls) propagate through the outer
    graph's ``astream(subgraphs=True)`` with the correct namespace.
    Additionally emits custom events via ``get_stream_writer()`` to signal
    stage lifecycle transitions.
    """
    model = (
        (subagent_models or {}).get(name)
        or spec.get("model")
        or default_model
    )
    tools = _filter_tools_by_prefix(all_tools, spec.get("_tool_prefixes"))
    agent = create_react_agent(model, tools, prompt=spec["system_prompt"])

    async def node(state: AuditState) -> dict[str, Any]:
        writer = get_stream_writer()
        writer({"type": "subagent_start", "name": name})

        context = _build_context(name, state.get("stage_outputs", {}))
        input_messages = [HumanMessage(content=context)]

        # Stream the inner agent so that tokens and tool calls are
        # forwarded to the outer graph via custom events.
        final_messages: list[BaseMessage] = []
        async for mode, data in agent.astream(
            {"messages": input_messages},
            stream_mode=["messages", "updates"],
        ):
            if mode == "messages":
                # data is (message_chunk, metadata)
                msg_chunk, _meta = data
                # Skip ToolMessages (tool results) — not tokens.
                if hasattr(msg_chunk, "tool_call_id") and msg_chunk.tool_call_id:
                    continue
                # Forward token content via custom event.
                content = getattr(msg_chunk, "content", None)
                if content and isinstance(content, str):
                    # Skip if this message also has tool_calls (it's a
                    # function-calling message, not a text response).
                    if not getattr(msg_chunk, "tool_calls", None):
                        writer({
                            "type": "token",
                            "subagent": name,
                            "content": content,
                        })
                # Forward tool call chunks (only complete ones with a name).
                tool_calls = getattr(msg_chunk, "tool_calls", None)
                if tool_calls:
                    for tc in tool_calls:
                        tc_name = tc.get("name", "")
                        if tc_name:
                            writer({
                                "type": "tool_call",
                                "subagent": name,
                                "tool_name": tc_name,
                                "tool_call_id": tc.get("id", ""),
                                "args": tc.get("args", {}),
                            })
            elif mode == "updates":
                # Accumulate final messages from state deltas.
                if isinstance(data, dict):
                    for _node, delta in data.items():
                        msgs = delta.get("messages", []) if isinstance(delta, dict) else []
                        if msgs:
                            final_messages = msgs

        last_msg = final_messages[-1].content if final_messages else ""
        new_outputs = dict(state.get("stage_outputs", {}))
        new_outputs[name] = last_msg

        writer({"type": "subagent_complete", "name": name})
        return {
            "stage_outputs": new_outputs,
            "current_stage": name,
            "messages": final_messages,
        }

    node.__name__ = name
    return node


def _validate_router(state: AuditState) -> Command[Literal["gapfill", "dedupe"]]:
    """After validate: if candidates remain unresolved, branch to gapfill.

    This is the validate⇄gapfill side-branch. ``gapfill_count`` bounds the
    whole cluster so it always terminates onto the main line (dedupe).
    """
    output = (state.get("stage_outputs") or {}).get("validate", "")
    lower = output.lower()
    has_gaps = any(k in lower for k in (
        "needs-more", "needs more", "unresolved", "gap", "incomplete", "uncertain",
    ))
    count = state.get("gapfill_count", 0)

    if has_gaps and count < DEFAULT_MAX_GAPFILL:
        return Command(update={"gapfill_count": count + 1}, goto="gapfill")
    return Command(goto="dedupe")


def _gapfill_router(state: AuditState) -> Command[Literal["hunt", "validate"]]:
    """Gapfill decides where its requests go: re-hunt or re-validate.

    Per the harness design, gapfill emits targeted work for either Hunt
    (find new candidates) or Validate (re-check existing ones).
    """
    output = (state.get("stage_outputs") or {}).get("gapfill", "")
    lower = output.lower()
    wants_hunt = any(k in lower for k in (
        "hunt", "search", "new candidate", "additional sink", "unexplored", "scan",
    ))
    return Command(goto="hunt" if wants_hunt else "validate")


def _feedback_router(state: AuditState) -> Command[Literal["hunt", "report"]]:
    """After feedback: weak findings trigger a fresh hunt round (the long loop).

    Routes back to Hunt (not Gapfill), resetting the gapfill budget so the
    new round gets its own gap-analysis allowance. ``feedback_count`` bounds
    the outer loop.
    """
    output = (state.get("stage_outputs") or {}).get("feedback", "")
    lower = output.lower()
    is_weak = any(k in lower for k in (
        "weak", "insufficient", "needs more", "speculative", "unconfirmed",
    ))
    count = state.get("feedback_count", 0)

    if is_weak and count < DEFAULT_MAX_FEEDBACK:
        return Command(
            update={"feedback_count": count + 1, "gapfill_count": 0},
            goto="hunt",
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

    builder.add_node("validate_check", _validate_router)
    builder.add_node("gapfill_check", _gapfill_router)
    builder.add_node("feedback_check", _feedback_router)

    # Main line: recon → hunt → validate → (validate_check) → dedupe → trace
    #            → feedback → (feedback_check) → report
    # Side-branch (validate⇄gapfill): validate_check → gapfill → gapfill_check
    #            → {hunt | validate}
    # Outer loop: feedback_check → {hunt | report}
    builder.add_edge(START, "recon")
    builder.add_edge("recon", "hunt")
    builder.add_edge("hunt", "validate")
    builder.add_edge("validate", "validate_check")
    # validate_check routes to gapfill (side-branch) or dedupe (main line)
    builder.add_edge("gapfill", "gapfill_check")
    # gapfill_check routes to hunt (re-hunt) or validate (re-check)
    builder.add_edge("dedupe", "trace")
    builder.add_edge("trace", "feedback")
    builder.add_edge("feedback", "feedback_check")
    # feedback_check routes to hunt (long loop) or report (forward)
    builder.add_edge("report", END)

    return builder.compile()
