"""LangGraph event stream → StreamEvent normalization."""

from __future__ import annotations

import time
from typing import Any

from app.chat.models import StreamEvent

# Maximum characters retained from a tool result in streaming events.
MAX_TOOL_RESULT_CHARS = 2000


def normalize_langgraph_events(
    event_type: str,
    event_data: Any,
    conversation_id: str,
    turn_id: str,
) -> list[StreamEvent]:
    """Convert a raw LangGraph stream event into a list of StreamEvents.

    LangGraph stream_mode="messages" yields (AIMessageChunk, metadata) tuples.
    stream_mode="updates" yields node-name → state-delta dicts.

    A single raw event can produce multiple StreamEvents (e.g. the "agent"
    node completing with several tool_calls, or the "tools" node returning
    multiple tool results).

    Args:
        event_type: The stream mode that produced this event ("messages", "updates", etc.)
        event_data: The raw event data from LangGraph.
        conversation_id: Active conversation ID.
        turn_id: Active turn ID.

    Returns:
        A list of StreamEvents (may be empty).
    """
    if event_type == "messages":
        evt = _normalize_message_event(event_data, conversation_id, turn_id)
        return [evt] if evt is not None else []
    elif event_type == "updates":
        return _normalize_update_events(event_data, conversation_id, turn_id)
    return []


def _normalize_message_event(
    data: Any,
    conversation_id: str,
    turn_id: str,
) -> StreamEvent | None:
    """Handle stream_mode="messages" events.

    data is a tuple of (message_chunk, metadata).

    Priority order:
      1. ToolMessage (tool_call_id set) — suppress entirely.
         Tool results are emitted via the "updates" stream mode
         (_normalize_update_events / "tools" node) which includes
         the tool_name; the "messages" mode ToolMessage lacks it.
      2. AIMessageChunk with tool calls in progress — suppress.
         The content contains tool call arguments / JSON that should
         not appear in the user-facing response.
      3. Regular text token — emit as "token" event.
    """
    if not isinstance(data, tuple) or len(data) < 2:
        return None

    msg, _metadata = data[0], data[1]

    # --- 1. ToolMessage (tool result) — suppress, handled by "updates" ---
    if hasattr(msg, "tool_call_id") and msg.tool_call_id:
        return None

    # --- 2. LLM generating tool calls — suppress ---
    has_tool_calls = hasattr(msg, "tool_calls") and msg.tool_calls
    has_tool_call_chunks = (
        hasattr(msg, "tool_call_chunks") and msg.tool_call_chunks
    )
    if has_tool_calls or has_tool_call_chunks:
        return None

    # --- 3. Regular text token ---
    if hasattr(msg, "content") and msg.content:
        # Normalize content to string.
        # msg.content can be a list of content blocks (e.g.
        # [{"type": "text", "text": "..."}]) when the LLM returns
        # structured content alongside tool calls.
        content = msg.content
        if isinstance(content, list):
            parts: list[str] = []
            for block in content:
                if isinstance(block, str):
                    parts.append(block)
                elif isinstance(block, dict) and block.get("type") == "text":
                    parts.append(block.get("text", ""))
            content = "".join(parts)

        return StreamEvent(
            type="token",
            conversation_id=conversation_id,
            turn_id=turn_id,
            payload={"content": content},
            timestamp=time.time(),
        )

    return None


def _normalize_update_events(
    data: Any,
    conversation_id: str,
    turn_id: str,
) -> list[StreamEvent]:
    """Handle stream_mode="updates" events.

    data is a dict mapping node name → state delta.

    LangGraph node structure:
      - "agent" node completes with AIMessage (may contain tool_calls)
      - "tools"  node completes with ToolMessage(s) (tool results)

    Returns a list so that multiple tool calls in a single node
    completion are not lost.
    """
    if not isinstance(data, dict):
        return []

    events: list[StreamEvent] = []

    for node_name, state_delta in data.items():
        if not isinstance(state_delta, dict):
            continue
        messages = state_delta.get("messages", [])
        if not messages:
            continue

        if node_name in ("agent", "model"):
            # Agent / model node finished — look for tool call requests on the
            # AIMessage.  Deepagents uses node name "model" instead of "agent".
            for msg in messages:
                if hasattr(msg, "tool_calls") and msg.tool_calls:
                    for tc in msg.tool_calls:
                        events.append(StreamEvent(
                            type="tool_start",
                            conversation_id=conversation_id,
                            turn_id=turn_id,
                            payload={
                                "tool_name": tc.get("name", ""),
                                "tool_call_id": tc.get("id", ""),
                                "args": tc.get("args", {}),
                            },
                            timestamp=time.time(),
                        ))

        elif node_name == "tools":
            # Tools node finished — extract ToolMessage results.
            for msg in messages:
                if hasattr(msg, "name") and hasattr(msg, "tool_call_id"):
                    content = (
                        msg.content
                        if isinstance(msg.content, str)
                        else str(msg.content)
                    )
                    is_error = (
                        hasattr(msg, "status") and msg.status == "error"
                    )
                    events.append(StreamEvent(
                        type="tool_error" if is_error else "tool_result",
                        conversation_id=conversation_id,
                        turn_id=turn_id,
                        payload={
                            "tool_name": getattr(msg, "name", ""),
                            "tool_call_id": getattr(msg, "tool_call_id", ""),
                            "result": content[:MAX_TOOL_RESULT_CHARS],
                            **({"error": content} if is_error else {}),
                        },
                        timestamp=time.time(),
                    ))

    return events


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
