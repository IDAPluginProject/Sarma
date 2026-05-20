"""LangGraph event stream → StreamEvent normalization.

This module bridges deepagents v0.6+ subgraph streaming output to the
internal ``StreamEvent`` schema consumed by the UI layer.

Subgraph streaming format (deepagents v0.6, ``version="v2"``)
=============================================================

Each chunk from ``agent.astream(..., subgraphs=True, version="v2")`` is a
dict:

    {
        "type": "messages" | "updates" | "custom",
        "ns": tuple[str, ...],
        "data": <mode-specific payload>,
    }

* ``ns`` is the agent hierarchy path. ``()`` = main agent. A segment of
  the form ``"tools:<tool_call_id>"`` denotes a subagent dispatched
  through the built-in ``task`` tool with that tool_call_id.
* ``type="messages"`` → ``data`` is ``(message_chunk, metadata)`` —
  individual LLM tokens.
* ``type="updates"`` → ``data`` is a node-name → state-delta dict.
* ``type="custom"`` → ``data`` is whatever ``get_stream_writer`` emitted.

The translator below carries a stateful ``EventTranslator`` that:

1. Remembers ``tool_call_id → subagent_name`` for every ``task`` call
   that originates from the main agent.
2. Resolves any ``ns`` containing ``"tools:<id>"`` to the matching
   subagent name (defaulting to ``"orchestrator"`` for the empty ``ns``).
3. Emits :class:`StreamEvent` instances with a stable ``subagent`` field
   on every payload, so the UI can route tokens / tool calls to the
   correct role card without guessing.
"""

from __future__ import annotations

import time
from typing import Any

from app.chat.models import StreamEvent

# Maximum characters retained from a tool result in streaming events.
MAX_TOOL_RESULT_CHARS = 2000

# Conventional name for the top-level coordinator agent.
ORCHESTRATOR = "orchestrator"

# Namespace segment prefix that deepagents uses for delegated subagents.
_SUBAGENT_NS_PREFIX = "tools:"


def _resolve_subagent_from_ns(
    ns: tuple[str, ...] | None,
    tool_call_to_subagent: dict[str, str],
) -> str:
    """Return the subagent name responsible for a given namespace tuple.

    Falls back to ``ORCHESTRATOR`` for empty namespaces or unknown call
    IDs (which can happen for the first chunk before the corresponding
    ``task`` tool_start event has been observed — rare, but defensive).
    """
    if not ns:
        return ORCHESTRATOR
    for seg in ns:
        if not isinstance(seg, str) or not seg.startswith(_SUBAGENT_NS_PREFIX):
            continue
        call_id = seg[len(_SUBAGENT_NS_PREFIX):]
        name = tool_call_to_subagent.get(call_id)
        if name:
            return name
        # Namespace identifies *some* subagent but we don't know which
        # one yet; surface the raw segment so the UI can still group
        # related events together.
        return seg
    return ORCHESTRATOR


class EventTranslator:
    """Stateful translator from deepagents subgraph events → StreamEvents.

    One instance per agent turn. Holds the ``tool_call_id → subagent_name``
    mapping that is populated as ``task`` calls are observed.
    """

    def __init__(self, conversation_id: str, turn_id: str) -> None:
        self._conv = conversation_id
        self._turn = turn_id
        self._tool_call_to_subagent: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def translate(self, chunk: Any) -> list[StreamEvent]:
        """Normalize one subgraph-stream chunk into StreamEvents.

        Accepts both the v0.6 wrapped-dict format and the legacy
        ``(mode, data)`` / ``(ns, mode, data)`` tuple shapes for
        defensive compatibility while the deepagents API stabilises.
        """
        event_type, ns, data = _unpack_chunk(chunk)
        if event_type is None:
            return []
        if event_type == "messages":
            evt = self._on_message(data, ns)
            return [evt] if evt is not None else []
        if event_type == "updates":
            return self._on_updates(data, ns)
        if event_type == "custom":
            return self._on_custom(data, ns)
        return []

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
            type="token",
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
                    type="tool_start",
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
                        type="skill_triggered",
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
                            type="subagent_start",
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
                type="tool_error" if is_error else "tool_result",
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
                        "subagent_error" if is_error else "subagent_complete"
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

        deepagents SkillsMiddleware emits custom events when skills are
        matched/loaded.  Expected shapes:
          {"type": "skill_matched", "skill": "<name>", ...}
          {"type": "skill_loaded", "skill": "<name>", ...}
          {"skill": "<name>", "status": "loaded"|"matched", ...}
        """
        if not isinstance(data, dict):
            return []

        source = _resolve_subagent_from_ns(ns, self._tool_call_to_subagent)

        # Shape 1: {"type": "skill_matched"|"skill_loaded", "skill": "..."}
        event_subtype = data.get("type", "")
        skill_name = data.get("skill") or data.get("name") or ""

        if event_subtype in ("skill_matched", "skill_loaded") and skill_name:
            return [StreamEvent(
                type="skill_triggered",
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

        # Shape 2: {"skill": "...", "status": "loaded"|"matched"}
        if skill_name and data.get("status") in ("loaded", "matched"):
            return [StreamEvent(
                type="skill_triggered",
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

        # Shape 3: generic progress/status from get_stream_writer()
        if "progress" in data or "status" in data:
            return [StreamEvent(
                type="custom_progress",
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
      * dict (deepagents v0.6+): ``{"type": ..., "ns": (...), "data": ...}``
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
        type="run_started",
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
        type="run_completed",
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
        type="run_failed",
        conversation_id=conversation_id,
        turn_id=turn_id,
        payload={"error": error, "partial_message": partial_content},
        timestamp=time.time(),
    )
