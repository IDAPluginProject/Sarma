"""LangGraph event stream → StreamEvent normalization.

This module bridges LangGraph subgraph streaming output to the internal
``StreamEvent`` schema consumed by the UI layer.

Subgraph streaming format (LangGraph v1.1+, ``version="v2"``)
==============================================================

Each chunk from ``agent.astream(..., subgraphs=True, version="v2")`` is a
dict:

    {
        "type": "messages" | "updates" | "custom",
        "ns": tuple[str, ...],
        "data": <mode-specific payload>,
    }

* ``ns`` is the agent hierarchy path. ``()`` = top-level graph. For the
  audit pipeline, the first segment is the subagent node name (e.g.
  ``("recon",)`` or ``("recon", "agent")``).
* ``type="messages"`` → ``data`` is ``(message_chunk, metadata)`` —
  individual LLM tokens.
* ``type="updates"`` → ``data`` is a node-name → state-delta dict.
* ``type="custom"`` → ``data`` is whatever ``get_stream_writer`` emitted.

The translator below carries a stateful ``EventTranslator`` that:

1. Resolves ``ns`` tuples to subagent names by matching the first segment
   against known audit pipeline node names.
2. Falls back to tool_call_id mapping for legacy compatibility.
3. Emits :class:`StreamEvent` instances with a stable ``subagent`` field
   on every payload, so the UI can route tokens / tool calls to the
   correct role card without guessing.
"""

from __future__ import annotations

import time
from typing import Any

from sarma_cli.engine.models import StreamEvent
from sarma_cli.engine.enums import StreamEventType

# Maximum characters retained from a tool result in streaming events.
MAX_TOOL_RESULT_CHARS = 2000

# Conventional name for the top-level coordinator agent.
ORCHESTRATOR = "orchestrator"

# Known subagent node names (from audit pipeline).
_KNOWN_SUBAGENTS: set[str] = set()

def _init_known_subagents() -> None:
    """Lazily populate known subagent names from audit_subagents."""
    global _KNOWN_SUBAGENTS
    if not _KNOWN_SUBAGENTS:
        names: set[str] = set()
        try:
            from sarma_cli.engine.audit_subagents import AUDIT_SUBAGENT_ORDER
            names.update(AUDIT_SUBAGENT_ORDER)
        except ImportError:
            pass
        try:
            from sarma_cli.engine.audit_slim_subagents import AUDIT_SLIM_SUBAGENT_ORDER
            names.update(AUDIT_SLIM_SUBAGENT_ORDER)
        except ImportError:
            pass
        _KNOWN_SUBAGENTS = names


def _resolve_subagent_from_ns(
    ns: tuple[str, ...] | None,
    tool_call_to_subagent: dict[str, str],
) -> str:
    """Return the subagent name responsible for a given namespace tuple.

    Handles native LangGraph ns format where the first segment is the
    node name (e.g. ("recon",) or ("recon", "agent")).
    Also handles legacy "tools:<call_id>" format for backwards compat.
    """
    if not ns:
        return ORCHESTRATOR
    _init_known_subagents()
    first = ns[0] if ns else ""
    first_name = _subagent_name_from_ns_segment(first)
    if first_name:
        return first_name
    # Fallback: check tool_call_id mapping (handles "tools:<id>" segments)
    for seg in ns:
        if not isinstance(seg, str):
            continue
        seg_name = _subagent_name_from_ns_segment(seg)
        if seg_name:
            return seg_name
        # Try direct lookup
        name = tool_call_to_subagent.get(seg)
        if name:
            return name
        # Try stripping "tools:" prefix
        if seg.startswith("tools:"):
            call_id = seg[len("tools:"):]
            name = tool_call_to_subagent.get(call_id)
            if name:
                return name
    return ORCHESTRATOR


def _subagent_name_from_ns_segment(segment: Any) -> str:
    if not isinstance(segment, str):
        return ""
    _init_known_subagents()
    # LangGraph v2 namespace segments are often "node_name:<task_uuid>".
    node_name = segment.split(":", 1)[0]
    if node_name in _KNOWN_SUBAGENTS:
        return node_name
    return ""


class EventTranslator:
    """Stateful translator from LangGraph subgraph events → StreamEvents.

    One instance per agent turn. Holds the ``tool_call_id → subagent_name``
    mapping that is populated as ``task`` calls are observed.

    Also tracks the currently active subagent via namespace transitions so
    that SUBAGENT_START / SUBAGENT_COMPLETE events are emitted for native
    StateGraph pipelines (where there is no "task" tool).
    """

    def __init__(self, conversation_id: str, turn_id: str) -> None:
        self._conv = conversation_id
        self._turn = turn_id
        self._tool_call_to_subagent: dict[str, str] = {}
        # Namespace-based lifecycle tracking for native audit graph.
        self._active_subagent: str | None = None

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def translate(self, chunk: Any) -> list[StreamEvent]:
        """Normalize one subgraph-stream chunk into StreamEvents.

        Accepts both the v0.6 wrapped-dict format and the legacy
        ``(mode, data)`` / ``(ns, mode, data)`` tuple shapes for
        defensive compatibility while the LangGraph streaming API evolves.
        """
        event_type, ns, data = _unpack_chunk(chunk)
        if event_type is None:
            return []

        # --- Namespace-based subagent lifecycle detection ---
        lifecycle_events = self._check_subagent_transition(ns)

        if event_type == "messages":
            evt = self._on_message(data, ns)
            if evt is not None:
                lifecycle_events.append(evt)
            return lifecycle_events
        if event_type == "updates":
            payload_events = self._on_updates(data, ns)
            # Also detect subagent completion from top-level updates.
            if not ns:
                payload_events.extend(
                    self._detect_node_completion(data)
                )
            return lifecycle_events + payload_events
        if event_type == "custom":
            return lifecycle_events + self._on_custom(data, ns)
        return lifecycle_events

    # ------------------------------------------------------------------
    # Namespace-based subagent lifecycle
    # ------------------------------------------------------------------

    def _check_subagent_transition(
        self, ns: tuple[str, ...]
    ) -> list[StreamEvent]:
        """Emit SUBAGENT_START when ns enters a new known subagent.

        This handles native StateGraph pipelines where subagents are graph
        nodes (not "task" tool calls). The first segment of ns is the node
        name — if it matches a known subagent and differs from the current
        active one, we emit a transition.
        """
        _init_known_subagents()
        if not ns:
            return []
        first = _subagent_name_from_ns_segment(ns[0])
        if first not in _KNOWN_SUBAGENTS:
            return []
        if first == self._active_subagent:
            return []

        events: list[StreamEvent] = []

        # Complete the previous subagent if one was active.
        if self._active_subagent is not None:
            events.append(StreamEvent(
                type=StreamEventType.SUBAGENT_COMPLETE,
                conversation_id=self._conv,
                turn_id=self._turn,
                payload={
                    "subagent": self._active_subagent,
                    "tool_call_id": "",
                    "result": "",
                },
                timestamp=time.time(),
            ))

        # Start the new subagent.
        self._active_subagent = first
        events.append(StreamEvent(
            type=StreamEventType.SUBAGENT_START,
            conversation_id=self._conv,
            turn_id=self._turn,
            payload={
                "subagent": first,
                "description": f"Running {first} stage",
                "tool_call_id": "",
            },
            timestamp=time.time(),
        ))
        return events

    def _detect_node_completion(
        self, data: Any
    ) -> list[StreamEvent]:
        """Detect subagent completion from top-level updates (ns=()).

        When the top-level graph emits an update for a known subagent node,
        it means that node has finished executing. Emit SUBAGENT_COMPLETE
        if we haven't already transitioned away.
        """
        if not isinstance(data, dict):
            return []
        _init_known_subagents()
        events: list[StreamEvent] = []
        for node_name in data:
            if node_name in _KNOWN_SUBAGENTS:
                if self._active_subagent == node_name:
                    self._active_subagent = None
                    events.append(StreamEvent(
                        type=StreamEventType.SUBAGENT_COMPLETE,
                        conversation_id=self._conv,
                        turn_id=self._turn,
                        payload={
                            "subagent": node_name,
                            "tool_call_id": "",
                            "result": "",
                        },
                        timestamp=time.time(),
                    ))
        return events

    # ------------------------------------------------------------------
    # mode = "messages"
    # ------------------------------------------------------------------

    def _on_message(
        self, data: Any, ns: tuple[str, ...]
    ) -> StreamEvent | None:
        if not isinstance(data, tuple) or len(data) < 2:
            return None
        msg, _metadata = data[0], data[1]

        # ToolMessage (a tool result) — suppress; the "updates" mode of
        # the same chunk batch will deliver a richer event with the
        # tool name attached.
        if hasattr(msg, "tool_call_id") and msg.tool_call_id:
            return None

        # AIMessage carrying tool-call chunks — suppress; tool starts are
        # emitted from the "updates" path on completion of the message.
        has_tool_calls = hasattr(msg, "tool_calls") and msg.tool_calls
        has_tool_call_chunks = (
            hasattr(msg, "tool_call_chunks") and msg.tool_call_chunks
        )
        if has_tool_calls or has_tool_call_chunks:
            return None

        if not (hasattr(msg, "content") and msg.content):
            return None

        content = _flatten_content(msg.content)
        if not content:
            return None

        return StreamEvent(
            type=StreamEventType.TOKEN,
            conversation_id=self._conv,
            turn_id=self._turn,
            payload={
                "content": content,
                "subagent": _resolve_subagent_from_ns(
                    ns, self._tool_call_to_subagent
                ),
            },
            timestamp=time.time(),
        )

    # ------------------------------------------------------------------
    # mode = "updates"
    # ------------------------------------------------------------------

    def _on_updates(
        self, data: Any, ns: tuple[str, ...]
    ) -> list[StreamEvent]:
        if not isinstance(data, dict):
            return []

        events: list[StreamEvent] = []
        source = _resolve_subagent_from_ns(ns, self._tool_call_to_subagent)

        for node_name, state_delta in data.items():
            if not isinstance(state_delta, dict):
                continue
            messages = state_delta.get("messages", [])
            if not messages:
                continue

            if node_name in ("agent", "model", "model_request"):
                events.extend(
                    self._emit_tool_starts(messages, source)
                )
            elif node_name == "tools":
                events.extend(
                    self._emit_tool_results(messages, source)
                )

        return events

    def _emit_tool_starts(
        self, messages: list[Any], source: str
    ) -> list[StreamEvent]:
        events: list[StreamEvent] = []
        for msg in messages:
            tool_calls = getattr(msg, "tool_calls", None)
            if not tool_calls:
                continue
            for tc in tool_calls:
                tool_name = tc.get("name", "")
                tool_args = tc.get("args", {}) or {}
                tool_call_id = tc.get("id", "")

                events.append(StreamEvent(
                    type=StreamEventType.TOOL_START,
                    conversation_id=self._conv,
                    turn_id=self._turn,
                    payload={
                        "tool_name": tool_name,
                        "tool_call_id": tool_call_id,
                        "args": tool_args,
                        "subagent": source,
                    },
                    timestamp=time.time(),
                ))

                # Detect skill file reads as skill triggers.
                skill_name = _detect_skill_from_tool(tool_name, tool_args)
                if skill_name:
                    events.append(StreamEvent(
                        type=StreamEventType.SKILL_TRIGGERED,
                        conversation_id=self._conv,
                        turn_id=self._turn,
                        payload={
                            "skill_name": skill_name,
                            "event": "skill_read",
                            "subagent": source,
                            "detail": "",
                        },
                        timestamp=time.time(),
                    ))

                # Track task → subagent for namespace resolution.
                if tool_name == "task" and isinstance(tool_args, dict):
                    subagent_type = tool_args.get("subagent_type")
                    if subagent_type and tool_call_id:
                        self._tool_call_to_subagent[tool_call_id] = (
                            subagent_type
                        )
                    if subagent_type:
                        events.append(StreamEvent(
                            type=StreamEventType.SUBAGENT_START,
                            conversation_id=self._conv,
                            turn_id=self._turn,
                            payload={
                                "subagent": subagent_type,
                                "description": tool_args.get(
                                    "description", ""
                                ),
                                "tool_call_id": tool_call_id,
                            },
                            timestamp=time.time(),
                        ))
        return events

    def _emit_tool_results(
        self, messages: list[Any], source: str
    ) -> list[StreamEvent]:
        events: list[StreamEvent] = []
        for msg in messages:
            if not (hasattr(msg, "name") and hasattr(msg, "tool_call_id")):
                continue
            tool_name = getattr(msg, "name", "")
            tool_call_id = getattr(msg, "tool_call_id", "")
            content = (
                msg.content
                if isinstance(msg.content, str)
                else str(msg.content)
            )
            is_error = (
                hasattr(msg, "status") and msg.status == "error"
            )

            # Tool result is *received* by the agent that owns this
            # update; for a task-tool completion, that's the orchestrator
            # — not the subagent that just finished.
            events.append(StreamEvent(
                type=StreamEventType.TOOL_ERROR if is_error else StreamEventType.TOOL_RESULT,
                conversation_id=self._conv,
                turn_id=self._turn,
                payload={
                    "tool_name": tool_name,
                    "tool_call_id": tool_call_id,
                    "result": content[:MAX_TOOL_RESULT_CHARS],
                    "subagent": source,
                    **({"error": content} if is_error else {}),
                },
                timestamp=time.time(),
            ))

            if tool_name == "task":
                finished = self._tool_call_to_subagent.pop(
                    tool_call_id, None
                )
                events.append(StreamEvent(
                    type=(
                        StreamEventType.SUBAGENT_ERROR if is_error else StreamEventType.SUBAGENT_COMPLETE
                    ),
                    conversation_id=self._conv,
                    turn_id=self._turn,
                    payload={
                        "subagent": finished or "",
                        "tool_call_id": tool_call_id,
                        "result": content[:MAX_TOOL_RESULT_CHARS],
                        **({"error": content} if is_error else {}),
                    },
                    timestamp=time.time(),
                ))
        return events

    # ------------------------------------------------------------------
    # mode = "custom" — skill events + user-defined signals
    # ------------------------------------------------------------------

    def _on_custom(
        self, data: Any, ns: tuple[str, ...]
    ) -> list[StreamEvent]:
        """Handle custom stream events.

        LangGraph custom events can signal:
          - Audit pipeline stage transitions (subagent_start/subagent_complete)
          - Skill triggers (skill_matched/skill_loaded)
          - Generic progress updates
        """
        if not isinstance(data, dict):
            return []

        source = _resolve_subagent_from_ns(ns, self._tool_call_to_subagent)
        event_subtype = data.get("type", "")

        # --- Audit pipeline stage lifecycle (from get_stream_writer) ---
        if event_subtype == "subagent_start":
            subagent_name = data.get("name", "")
            if subagent_name:
                # Complete previous subagent if transitioning.
                events: list[StreamEvent] = []
                if (
                    self._active_subagent is not None
                    and self._active_subagent != subagent_name
                ):
                    events.append(StreamEvent(
                        type=StreamEventType.SUBAGENT_COMPLETE,
                        conversation_id=self._conv,
                        turn_id=self._turn,
                        payload={
                            "subagent": self._active_subagent,
                            "tool_call_id": "",
                            "result": "",
                        },
                        timestamp=time.time(),
                    ))
                self._active_subagent = subagent_name
                events.append(StreamEvent(
                    type=StreamEventType.SUBAGENT_START,
                    conversation_id=self._conv,
                    turn_id=self._turn,
                    payload={
                        "subagent": subagent_name,
                        "description": f"Running {subagent_name} stage",
                        "tool_call_id": "",
                    },
                    timestamp=time.time(),
                ))
                return events

        if event_subtype == "subagent_complete":
            subagent_name = data.get("name", "")
            if subagent_name:
                if self._active_subagent == subagent_name:
                    self._active_subagent = None
                return [StreamEvent(
                    type=StreamEventType.SUBAGENT_COMPLETE,
                    conversation_id=self._conv,
                    turn_id=self._turn,
                    payload={
                        "subagent": subagent_name,
                        "tool_call_id": "",
                        "result": "",
                    },
                    timestamp=time.time(),
                )]

        # --- Audit graph route decisions ---
        if event_subtype == "audit_route":
            return [StreamEvent(
                type=StreamEventType.CUSTOM_PROGRESS,
                conversation_id=self._conv,
                turn_id=self._turn,
                payload={
                    "data": data,
                    "subagent": source,
                },
                timestamp=time.time(),
            )]

        # --- Forwarded token from inner subagent astream ---
        if event_subtype == "token":
            content = data.get("content", "")
            subagent = data.get("subagent", source)
            if content:
                return [StreamEvent(
                    type=StreamEventType.TOKEN,
                    conversation_id=self._conv,
                    turn_id=self._turn,
                    payload={
                        "content": content,
                        "subagent": subagent,
                    },
                    timestamp=time.time(),
                )]
            return []

        # --- Forwarded tool call from inner subagent astream ---
        if event_subtype == "tool_call":
            return [StreamEvent(
                type=StreamEventType.TOOL_START,
                conversation_id=self._conv,
                turn_id=self._turn,
                payload={
                    "tool_name": data.get("tool_name", ""),
                    "tool_call_id": data.get("tool_call_id", ""),
                    "args": data.get("args", {}),
                    "subagent": data.get("subagent", source),
                },
                timestamp=time.time(),
            )]

        # --- Skill triggers ---
        skill_name = data.get("skill") or data.get("name") or ""

        if event_subtype in ("skill_matched", "skill_loaded") and skill_name:
            return [StreamEvent(
                type=StreamEventType.SKILL_TRIGGERED,
                conversation_id=self._conv,
                turn_id=self._turn,
                payload={
                    "skill_name": skill_name,
                    "event": event_subtype,
                    "subagent": source,
                    "detail": data.get("description", ""),
                },
                timestamp=time.time(),
            )]

        if skill_name and data.get("status") in ("loaded", "matched"):
            return [StreamEvent(
                type=StreamEventType.SKILL_TRIGGERED,
                conversation_id=self._conv,
                turn_id=self._turn,
                payload={
                    "skill_name": skill_name,
                    "event": f"skill_{data['status']}",
                    "subagent": source,
                    "detail": data.get("description", ""),
                },
                timestamp=time.time(),
            )]

        # --- Generic progress/status ---
        if "progress" in data or "status" in data:
            return [StreamEvent(
                type=StreamEventType.CUSTOM_PROGRESS,
                conversation_id=self._conv,
                turn_id=self._turn,
                payload={
                    "data": data,
                    "subagent": source,
                },
                timestamp=time.time(),
            )]

        return []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _detect_skill_from_tool(tool_name: str, tool_args: dict) -> str | None:
    """Detect if a tool call is reading a SKILL.md file.

    Returns the skill name if detected, else None.
    """
    # Backend file reads that reference SKILL.md
    if tool_name in ("read_file", "cat", "read"):
        path = tool_args.get("path", "") or tool_args.get("file_path", "")
        if "SKILL.md" in path:
            # Extract skill name from path like "/skills/idapython/SKILL.md"
            parts = path.replace("\\", "/").split("/")
            try:
                idx = parts.index("SKILL.md")
                if idx > 0:
                    return parts[idx - 1]
            except ValueError:
                pass
    return None


def _unpack_chunk(
    chunk: Any,
) -> tuple[str | None, tuple[str, ...], Any]:
    """Return ``(event_type, ns, data)`` for any supported chunk shape.

    Supported shapes:
      * dict (LangGraph v2): ``{"type": ..., "ns": (...), "data": ...}``
      * 3-tuple (raw LangGraph w/ subgraphs): ``(ns, mode, data)``
      * 2-tuple (raw LangGraph w/o subgraphs): ``(mode, data)``  → ns=()
    """
    if isinstance(chunk, dict):
        ns_value = chunk.get("ns") or ()
        ns = tuple(ns_value) if not isinstance(ns_value, tuple) else ns_value
        return chunk.get("type"), ns, chunk.get("data")

    if isinstance(chunk, tuple):
        if len(chunk) == 3:
            ns_value, mode, data = chunk
            ns = tuple(ns_value) if not isinstance(ns_value, tuple) else ns_value
            return mode if isinstance(mode, str) else None, ns, data
        if len(chunk) == 2:
            mode, data = chunk
            return mode if isinstance(mode, str) else None, (), data

    return None, (), None


def _flatten_content(content: Any) -> str:
    """Reduce a LangChain message ``content`` field to a plain string."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
        return "".join(parts)
    return ""


# ---------------------------------------------------------------------------
# Run-lifecycle helpers (unchanged)
# ---------------------------------------------------------------------------

def make_run_started_event(
    conversation_id: str, turn_id: str
) -> StreamEvent:
    return StreamEvent(
        type=StreamEventType.RUN_STARTED,
        conversation_id=conversation_id,
        turn_id=turn_id,
        payload={},
        timestamp=time.time(),
    )


def make_run_completed_event(
    conversation_id: str,
    turn_id: str,
    assistant_content: str = "",
) -> StreamEvent:
    return StreamEvent(
        type=StreamEventType.RUN_COMPLETED,
        conversation_id=conversation_id,
        turn_id=turn_id,
        payload={"assistant_message": assistant_content},
        timestamp=time.time(),
    )


def make_run_failed_event(
    conversation_id: str,
    turn_id: str,
    error: str,
    partial_content: str = "",
) -> StreamEvent:
    return StreamEvent(
        type=StreamEventType.RUN_FAILED,
        conversation_id=conversation_id,
        turn_id=turn_id,
        payload={"error": error, "partial_message": partial_content},
        timestamp=time.time(),
    )
