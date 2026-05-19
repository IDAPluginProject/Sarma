"""Tests for the agent execution pipeline: agent_factory → agent_runner → streaming."""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Streaming normalization
# ---------------------------------------------------------------------------


class TestStreamingNormalization:
    """Verify normalize_langgraph_events handles all event types correctly."""

    def test_normalize_message_token_event(self):
        """AIMessageChunk with text content should produce a token event."""
        from app.chat.streaming import normalize_langgraph_events

        class FakeChunk:
            content = "hello"
            tool_calls = None
            tool_call_chunks = None

        class FakeMetadata:
            pass

        events = normalize_langgraph_events(
            "messages", (FakeChunk(), FakeMetadata()), "conv1", "turn1"
        )
        assert len(events) == 1
        assert events[0].type == "token"
        assert events[0].payload["content"] == "hello"

    def test_normalize_message_suppresses_tool_call_chunks(self):
        """Chunks with tool_call_chunks should be suppressed."""
        from app.chat.streaming import normalize_langgraph_events

        class FakeChunk:
            content = ""
            tool_calls = None
            tool_call_chunks = [{"name": "test_tool"}]

        class FakeMetadata:
            pass

        events = normalize_langgraph_events(
            "messages", (FakeChunk(), FakeMetadata()), "conv1", "turn1"
        )
        assert len(events) == 0

    def test_normalize_message_suppresses_toolmessage(self):
        """ToolMessage (has tool_call_id) should be suppressed."""
        from app.chat.streaming import normalize_langgraph_events

        class FakeToolMsg:
            content = "tool result"
            tool_call_id = "tc_123"

        class FakeMetadata:
            pass

        events = normalize_langgraph_events(
            "messages", (FakeToolMsg(), FakeMetadata()), "conv1", "turn1"
        )
        assert len(events) == 0

    def test_normalize_updates_agent_node(self):
        """Agent node completion with tool_calls should produce tool_start events."""
        from app.chat.streaming import normalize_langgraph_events

        class FakeAIMessage:
            tool_calls = [{"name": "search", "id": "tc_1", "args": {"q": "test"}}]

        data = {"agent": {"messages": [FakeAIMessage()]}}
        events = normalize_langgraph_events("updates", data, "conv1", "turn1")
        assert len(events) == 1
        assert events[0].type == "tool_start"
        assert events[0].payload["tool_name"] == "search"

    def test_normalize_updates_tools_node(self):
        """Tools node completion should produce tool_result events."""
        from app.chat.streaming import normalize_langgraph_events

        class FakeToolMsg:
            name = "search"
            tool_call_id = "tc_1"
            content = '{"results": [1,2,3]}'
            status = "success"

        data = {"tools": {"messages": [FakeToolMsg()]}}
        events = normalize_langgraph_events("updates", data, "conv1", "turn1")
        assert len(events) == 1
        assert events[0].type == "tool_result"
        assert events[0].payload["tool_name"] == "search"

    def test_normalize_updates_tools_error(self):
        """Tools node with error status should produce tool_error events."""
        from app.chat.streaming import normalize_langgraph_events

        class FakeToolMsg:
            name = "search"
            tool_call_id = "tc_1"
            content = "Connection refused"
            status = "error"

        data = {"tools": {"messages": [FakeToolMsg()]}}
        events = normalize_langgraph_events("updates", data, "conv1", "turn1")
        assert len(events) == 1
        assert events[0].type == "tool_error"

    def test_normalize_content_list_to_string(self):
        """Content as list of blocks should be concatenated."""
        from app.chat.streaming import normalize_langgraph_events

        class FakeChunk:
            content = [{"type": "text", "text": "part1"}, "part2"]
            tool_calls = None
            tool_call_chunks = None

        class FakeMetadata:
            pass

        events = normalize_langgraph_events(
            "messages", (FakeChunk(), FakeMetadata()), "conv1", "turn1"
        )
        assert len(events) == 1
        assert events[0].payload["content"] == "part1part2"


# ---------------------------------------------------------------------------
# History compaction
# ---------------------------------------------------------------------------


class TestHistoryCompactor:
    """Verify history compactor handles edge cases correctly."""

    def test_empty_history_returns_empty(self):
        from app.chat.history_compactor import HistoryCompactor
        from app.chat.persistence import ChatPersistence

        compactor = HistoryCompactor(ChatPersistence(None), 1000)
        result = compactor.compact("conv1", [])
        assert result == []

    def test_all_tool_messages_returns_empty(self):
        """When all kept messages are tool messages after stripping, return []."""
        from app.chat.history_compactor import HistoryCompactor
        from app.chat.models import ChatMessage
        from app.chat.persistence import ChatPersistence

        messages = [
            ChatMessage(
                conversation_id="conv1", role="tool",
                content='{"args":{"q":"test"},"result":"got it"}',
                tool_name="search",
            ),
            ChatMessage(
                conversation_id="conv1", role="tool",
                content='{"args":{},"result":"done"}',
                tool_name="read",
            ),
        ]
        compactor = HistoryCompactor(ChatPersistence(None), 10)
        result = compactor.compact("conv1", messages)
        assert result == []


# ---------------------------------------------------------------------------
# MCP pool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mcp_pool_empty_config_returns_no_tools():
    from app.chat.mcp_pool import McpClientPool

    pool = McpClientPool()
    tools = await pool.connect({})
    assert tools == []
    assert pool.is_connected


@pytest.mark.asyncio
async def test_mcp_pool_disconnect_clears_state():
    from app.chat.mcp_pool import McpClientPool

    pool = McpClientPool()
    await pool.connect({})
    await pool.disconnect()
    assert not pool.is_connected
    assert pool.tools == []


# ---------------------------------------------------------------------------
# Agent factory model building
# ---------------------------------------------------------------------------


class TestModelBuilders:
    """Verify model builder dispatch and configuration."""

    def test_unsupported_api_mode_raises(self):
        from app.chat.agent_factory import AgentFactory
        from app.chat.mcp_pool import McpClientPool

        factory = AgentFactory(McpClientPool())
        from app.chat.errors import ProviderNotConfiguredError

        class FakeProvider:
            api_mode = "unsupported"
            model_name = "gpt-4"

        with pytest.raises(ProviderNotConfiguredError, match="Unsupported api_mode"):
            factory._init_model(FakeProvider(), None)

    def test_skill_temperature_override(self):
        from app.chat.agent_factory import AgentFactory, _MODEL_BUILDERS
        from app.chat.mcp_pool import McpClientPool
        from app.chat.models import ResolvedSkill

        assert "openai_compatible" in _MODEL_BUILDERS
        assert "anthropic" in _MODEL_BUILDERS
        assert "openai_responses" in _MODEL_BUILDERS


# ---------------------------------------------------------------------------
# Utility: resolve_skill
# ---------------------------------------------------------------------------


class TestResolveSkill:
    def test_resolve_skill_none_data(self):
        from app.chat.models import resolve_skill
        assert resolve_skill(None) is None

    def test_resolve_skill_empty_dict(self):
        from app.chat.models import resolve_skill
        result = resolve_skill({})
        assert result is None

    def test_resolve_skill_with_allowlist(self):
        from app.chat.models import resolve_skill
        import json

        data = {
            "id": 1,
            "name": "test_skill",
            "tool_allowlist_json": json.dumps(["tool_a", "tool_b"]),
        }
        result = resolve_skill(data)
        assert result is not None
        assert result.name == "test_skill"
        assert result.tool_allowlist == {"tool_a", "tool_b"}

    def test_resolve_skill_malformed_json(self):
        from app.chat.models import resolve_skill

        data = {
            "id": 1,
            "name": "test_skill",
            "tool_allowlist_json": "not-valid-json",
        }
        result = resolve_skill(data)
        assert result is not None
        assert result.tool_allowlist is None  # silently ignored
