from __future__ import annotations

import asyncio
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path

import pytest
from rich.console import Console
from textual.app import App, ComposeResult
from textual.widgets import Button, Input, ListView, Select, Static

from sarma_cli.config import (
    AgentConfig,
    CliConfig,
    McpServerConfig,
    ProviderConfig,
    _parse_agents,
    _parse_models,
    parse_context_window,
    save_models,
)
from sarma_cli.engine.audit_graph import _filter_tools_by_mcp, _filter_tools_by_prefix
from sarma_cli.engine.agent_factory import AgentFactory
from sarma_cli.engine.agent_runner import AgentRunner
from sarma_cli.engine.dto import McpServerDTO, ModelProviderDTO
from sarma_cli.engine.enums import StreamEventType
from sarma_cli.engine.models import AgentRunConfig, ConversationMessage, StreamEvent
from sarma_cli.engine.mcp_pool import _connect_timeout
from sarma_cli.engine.streaming import EventTranslator
from sarma_cli.resources.plugins import (
    create_mcp_server,
    install_skill_from_zip,
    list_mcp_quick_modes,
    validate_mcp_server,
)
from sarma_cli.runtime.resolver import RuntimePolicyResolver
from sarma_cli.runtime.middleware import (
    build_agent_middleware,
    build_agent_middleware_for_model,
)
from sarma_cli.store import Store
from sarma_cli.workflows import get_registry, init_workflows
from sarma_cli.engine.ruflo import SUBAGENT_RESULT_TEMPLATE, build_ruflo_prompt
from sarma_cli.session import Session
from sarma_cli.status import render_status_panel
from sarma_cli.context.compaction import ContextCompactor, ContextWindowPolicy
import sarma_cli.tui.plugin_app as plugin_app_module
from sarma_cli.tui.chat_area import AssistantMessage, ChatArea, ToolCallWidget
from sarma_cli.tui.config_app import ConfigApp
from sarma_cli.tui.input_bar import HistoryInput, InputBar
from sarma_cli.tui.input_history import append_input_history, load_input_history
from sarma_cli.tui.main_app import MainApp, StreamEventMessage
from sarma_cli.tui.plugin_app import PluginApp
from sarma_cli.tui.sidebar import Sidebar


@dataclass
class Tool:
    name: str


class FakeMcpPool:
    def __init__(self) -> None:
        self.connect_calls = 0
        self.tools = [Tool("demo_tool")]

    async def connect(self, _server_configs: dict[str, dict[str, object]]) -> list[Tool]:
        self.connect_calls += 1
        return self.tools

    def filter_tools(
        self,
        tools: list[Tool],
        allowlist: set[str] | None = None,
        denylist: set[str] | None = None,
    ) -> list[Tool]:
        result = list(tools)
        if allowlist is not None:
            result = [tool for tool in result if tool.name in allowlist]
        if denylist is not None:
            result = [tool for tool in result if tool.name not in denylist]
        return result


class StatusPool:
    is_connected = True

    @property
    def tools(self) -> list[Tool]:
        return [Tool("ida-mcp_decompile"), Tool("ida-mcp_disasm")]

    @property
    def server_statuses(self) -> list[dict[str, object]]:
        return [{
            "name": "ida-mcp",
            "connected": True,
            "tool_count": 2,
        }]


class CountingAgentFactory(AgentFactory):
    def __init__(self, pool: FakeMcpPool) -> None:
        super().__init__(pool)  # type: ignore[arg-type]
        self.model_builds = 0
        self.agent_builds = 0

    def _init_model(self, provider: object, skill: object | None) -> object:
        self.model_builds += 1
        return object()

    def _create_agent(
        self,
        config: AgentRunConfig,
        model: object,
        tools: list[object],
    ) -> object:
        self.agent_builds += 1
        return object()


def _agent_run_config(message: str, *, system_prompt: str = "base") -> AgentRunConfig:
    return AgentRunConfig(
        conversation_id="c1",
        provider=ModelProviderDTO(
            id=None,
            name="default",
            model_name="gpt-4o",
            api_mode="openai_compatible",
            api_key="test",
            base_url="",
            temperature=0.0,
            top_p=1.0,
            max_context_tokens=128_000,
            enabled=True,
        ),
        skill=None,
        enabled_servers=[],
        message_history=[],
        user_message=message,
        system_prompt=system_prompt,
        mode="test",
    )


@pytest.mark.anyio
async def test_agent_factory_reuses_agent_for_same_runtime_shape() -> None:
    pool = FakeMcpPool()
    factory = CountingAgentFactory(pool)

    first_agent, _first_tools = await factory.build(_agent_run_config("first"))
    second_agent, _second_tools = await factory.build(_agent_run_config("second"))

    assert second_agent is first_agent
    assert factory.model_builds == 1
    assert factory.agent_builds == 1
    assert pool.connect_calls == 2

    changed_agent, _changed_tools = await factory.build(
        _agent_run_config("third", system_prompt="changed")
    )

    assert changed_agent is not first_agent
    assert factory.model_builds == 2
    assert factory.agent_builds == 2


def test_subagent_tool_prefix_filter_fails_closed() -> None:
    tools = [Tool("ida_mcp_decompile"), Tool("ida_mcp_disasm")]

    assert _filter_tools_by_prefix(tools, ["missing_tool"]) == []


def test_event_translator_resolves_langgraph_v2_subagent_namespace() -> None:
    from langchain_core.messages import AIMessageChunk

    events = EventTranslator("c1", "t1").translate({
        "type": "messages",
        "ns": ("recon:9302c9ff-eb94",),
        "data": (AIMessageChunk(content="x"), {}),
    })

    tokens = [event for event in events if event.type == StreamEventType.TOKEN]
    assert len(tokens) == 1
    assert tokens[0].payload["subagent"] == "recon"


def test_audit_graph_input_carries_user_task_separately() -> None:
    graph_input = AgentRunner._build_graph_input(
        messages=[],
        user_message="audit FortiOS init binary",
        mode="audit",
    )

    assert graph_input["audit_task"] == "audit FortiOS init binary"
    assert graph_input["stage_outputs"] == {}
    assert graph_input["gapfill_count"] == 0
    assert graph_input["feedback_count"] == 0


def test_audit_slim_uses_four_stage_feedback_harness() -> None:
    from sarma_cli.engine.audit_slim_subagents import AUDIT_SLIM_SUBAGENT_ORDER

    assert AUDIT_SLIM_SUBAGENT_ORDER == ("recon", "hunter", "verify", "report")


def test_audit_stage_context_uses_task_and_prior_outputs_only() -> None:
    from sarma_cli.engine.audit_graph import _build_context

    context = _build_context(
        "validate",
        "audit FortiOS init binary",
        {
            "recon": "binary metadata",
            "hunt": "candidate at 0x401000",
        },
    )

    assert "audit FortiOS init binary" in context
    assert "### recon" in context
    assert "binary metadata" in context
    assert "### hunt" in context
    assert "candidate at 0x401000" in context
    assert "hidden tool traces" in context


def test_audit_route_events_update_graph_loop_counts(monkeypatch) -> None:
    workspace = Path("build/test-audit-route-state").resolve()
    shutil.rmtree(workspace, ignore_errors=True)
    workspace.mkdir(parents=True)
    monkeypatch.chdir(workspace)

    config = CliConfig(models=[ProviderConfig(name="default", model_name="gpt-4o")])
    store = Store()
    session = Session(config, store)

    event = StreamEvent(
        type=StreamEventType.CUSTOM_PROGRESS,
        payload={
            "data": {
                "type": "audit_route",
                "from": "validate",
                "to": "gapfill",
                "loop": "gapfill",
                "count": 2,
            }
        },
    )

    session._track_graph_progress(event)

    assert session.graph_state["gapfill_loops"] == 2
    store.close()
    shutil.rmtree(workspace, ignore_errors=True)


@pytest.mark.anyio
async def test_audit_graph_streams_subagent_tokens_once() -> None:
    from langchain_core.language_models.fake_chat_models import FakeListChatModel
    from sarma_cli.engine.audit_slim_graph import build_audit_slim_graph

    class ToolBindingFakeModel(FakeListChatModel):
        def bind_tools(self, *args: object, **kwargs: object) -> object:
            return self

    graph = build_audit_slim_graph(
        ToolBindingFakeModel(responses=[
            "hello from recon",
            "hello from hunter",
            "verified\nhello from verify",
            "hello from report",
        ]),
        [],
    )
    translator = EventTranslator("c1", "t1")
    tokens_by_subagent: dict[str, list[str]] = {}

    async for chunk in graph.astream(
        {"messages": []},
        stream_mode=["messages", "updates", "custom"],
        subgraphs=True,
        version="v2",
    ):
        for event in translator.translate(chunk):
            if event.type == StreamEventType.TOKEN:
                subagent = str(event.payload.get("subagent") or "")
                tokens_by_subagent.setdefault(subagent, []).append(
                    str(event.payload.get("content") or "")
                )

    rendered = {
        subagent: "".join(tokens)
        for subagent, tokens in tokens_by_subagent.items()
    }
    assert rendered["recon"] == "hello from recon"
    assert rendered["hunter"] == "hello from hunter"
    assert rendered["verify"] == "verified\nhello from verify"
    assert rendered["report"] == "hello from report"
    assert "orchestrator" not in rendered


def test_mcp_connect_timeout_is_capped_for_responsiveness() -> None:
    assert _connect_timeout({"local": {"transport": "stdio"}}) == 20.0
    assert _connect_timeout({"local": {"transport": "http", "timeout": 60}}) == 20.0
    assert _connect_timeout({"local": {"transport": "http", "timeout": 5}}) == 5.0


def test_status_panel_summarizes_mcp_runtime() -> None:
    config = CliConfig(
        models=[ProviderConfig(name="default", model_name="gpt-4o")],
        mcp_servers=[McpServerConfig(name="ida-mcp", transport="http", enabled=True)],
    )
    console = Console(record=True, width=120)

    console.print(render_status_panel(config, pool=StatusPool()))
    text = console.export_text()

    assert "connected" in text
    assert "1 enabled" in text
    assert "2 tools" in text
    assert "ida-mcp" in text
    assert "ida-mcp_decompile" not in text
    assert "ida-mcp_disasm" not in text


@pytest.mark.anyio
async def test_sidebar_mcp_lists_server_names_without_tool_details() -> None:
    app = MainApp(CliConfig(models=[ProviderConfig(name="default", model_name="gpt-4o")]))

    async with app.run_test():
        sidebar = app.query_one(Sidebar)
        sidebar.update_mcp(True, servers=[
            {"name": "ida-mcp", "connected": True, "tool_count": 64},
            {"name": "other-mcp", "connected": False, "tool_count": 0},
        ])

        text = sidebar._render_mcp_servers().plain

        assert "ida-mcp" in text
        assert "connected" in text
        assert "other-mcp" in text
        assert "IDA-MCP_decompile" not in text


@pytest.mark.anyio
async def test_sidebar_renders_ruflo_runtime_graph() -> None:
    app = MainApp(CliConfig(models=[ProviderConfig(name="default", model_name="gpt-4o")]))

    async with app.run_test():
        sidebar = app.query_one(Sidebar)
        sidebar.update_workflow("ruflo")
        sidebar.update_run_state(
            active=["recon", "verifier"],
            seen=["recon", "verifier"],
            completed={"recon"},
        )

        text = sidebar.query_one("#workflow-graph", Static).content.plain

        assert "agents run  2" in text
        assert "parallel" in text
        assert "▶ verifier" in text
        assert "✓ recon" in text


@pytest.mark.anyio
async def test_sidebar_renders_per_agent_models() -> None:
    app = MainApp(CliConfig(models=[ProviderConfig(name="default", model_name="gpt-4o")]))

    async with app.run_test():
        sidebar = app.query_one(Sidebar)
        sidebar.update_models([
            ("recon", "gpt-4o"),
            ("hunter", "claude-sonnet"),
            ("verify", "gpt-4o"),
        ])

        text = sidebar.query_one("#model-name", Static).content.plain

        assert "recon  gpt-4o" in text
        assert "hunter  claude-sonnet" in text
        assert "verify  gpt-4o" in text


@pytest.mark.anyio
async def test_sidebar_renders_audit_harness_side_branch() -> None:
    app = MainApp(CliConfig(models=[ProviderConfig(name="default", model_name="gpt-4o")]))

    async with app.run_test():
        sidebar = app.query_one(Sidebar)
        sidebar.update_workflow("audit")
        sidebar.update_run_state(
            active=["gapfill"],
            seen=["recon", "hunt", "validate", "gapfill"],
            completed={"recon", "hunt", "validate"},
            gapfill_loops=1,
            feedback_loops=0,
        )

        text = sidebar.query_one("#workflow-graph", Static).content.plain

        assert "recon" in text
        assert "hunt" in text
        assert "validate" in text
        assert "└ ▶ gapfill ⇢ hunt/validate ×1" in text
        assert "feedback" in text
        assert "report" in text


@pytest.mark.anyio
async def test_sidebar_renders_audit_slim_feedback_loop() -> None:
    app = MainApp(CliConfig(models=[ProviderConfig(name="default", model_name="gpt-4o")]))

    async with app.run_test():
        sidebar = app.query_one(Sidebar)
        sidebar.update_workflow("audit-slim")
        sidebar.update_run_state(
            active=["verify"],
            seen=["recon", "hunter", "verify"],
            completed={"recon", "hunter"},
            feedback_loops=1,
        )

        text = sidebar.query_one("#workflow-graph", Static).content.plain

        assert "recon" in text
        assert "hunter ↔ ▶ verify" in text
        assert "feedback  verify → hunter ×1" in text
        assert "report" in text


def test_mcp_filter_allows_only_named_server_tools() -> None:
    tools = [
        Tool("ida-mcp_decompile"),
        Tool("ida-mcp_disasm"),
        Tool("other-mcp_decompile"),
    ]

    allowed = _filter_tools_by_mcp(tools, ["ida-mcp"])

    assert [tool.name for tool in allowed] == ["ida-mcp_decompile", "ida-mcp_disasm"]


def test_runtime_resolver_expands_workflow_mcp_without_config_runtime_imports() -> None:
    config = CliConfig(
        active_model="default",
        models=[ProviderConfig(name="default", model_name="gpt-4o")],
        mcp_servers=[
            McpServerConfig(name="ida-mcp", enabled=True),
            McpServerConfig(name="other-mcp", enabled=True),
        ],
        agents=[
            AgentConfig(name="audit", model="default", mcp=[]),
            AgentConfig(name="audit.recon", model="default", mcp=["ida-mcp"]),
            AgentConfig(name="audit.hunt", model="default", mcp=["other-mcp"]),
        ],
    )

    plan = RuntimePolicyResolver(config).resolve("audit")

    assert {server.name for server in plan.enabled_servers} == {"ida-mcp", "other-mcp"}
    assert plan.subagent_mcp_allow["recon"] == ["ida-mcp"]
    assert plan.subagent_mcp_allow["hunt"] == ["other-mcp"]


def test_runtime_resolver_reports_per_agent_model_assignments() -> None:
    config = CliConfig(
        active_model="default",
        models=[
            ProviderConfig(name="default", model_name="gpt-4o"),
            ProviderConfig(name="backup", model_name="claude-sonnet"),
        ],
        agents=[
            AgentConfig(name="audit-slim", model="default"),
            AgentConfig(name="audit-slim.hunter", model="backup"),
        ],
    )

    assignments = dict(RuntimePolicyResolver(config).model_assignments_for("audit-slim"))

    assert assignments == {
        "recon": "gpt-4o",
        "hunter": "claude-sonnet",
        "verify": "gpt-4o",
        "report": "gpt-4o",
    }


def test_store_rejects_unknown_conversation_update_field(monkeypatch) -> None:
    workspace = Path("build/test-store-boundaries").resolve()
    shutil.rmtree(workspace, ignore_errors=True)
    workspace.mkdir(parents=True)
    monkeypatch.chdir(workspace)

    store = Store()
    cid = store.create_conversation()

    with pytest.raises(ValueError):
        store.update_conversation(cid, unknown_column="value")

    store.close()
    shutil.rmtree(workspace, ignore_errors=True)


def test_plugin_mcp_quick_modes_are_generic() -> None:
    assert list_mcp_quick_modes() == ["stdio", "http", "sse"]


def test_mcp_plugin_validation_requires_mode_specific_fields() -> None:
    assert validate_mcp_server(McpServerConfig(name="x", transport="http")) == [
        "http MCP requires a URL"
    ]

    server = create_mcp_server(
        name="local-tools",
        transport="stdio",
        command="python",
        args='["-m", "server"]',
        env='{"TOKEN":"x"}',
    )

    assert server.transport == "stdio"
    assert server.command == "python"


def test_model_sampling_settings_are_fixed_and_not_saved(monkeypatch) -> None:
    workspace = Path("build/test-model-config").resolve()
    shutil.rmtree(workspace, ignore_errors=True)
    workspace.mkdir(parents=True)
    monkeypatch.chdir(workspace)

    active, models = _parse_models({
        "active": "default",
        "models": [{
            "name": "default",
            "model_name": "gpt-4o",
            "temperature": 0.7,
            "top_p": 0.5,
            "max_context_tokens": 4096,
        }],
    })
    path = save_models(CliConfig(active_model=active, models=models))
    text = path.read_text(encoding="utf-8")

    assert models[0].temperature == 0.0
    assert models[0].top_p == 1.0
    assert "temperature" not in text
    assert "top_p" not in text
    assert "max_context_tokens = 4096" in text

    shutil.rmtree(workspace, ignore_errors=True)


def test_parse_context_window_accepts_k_and_m_suffixes() -> None:
    assert parse_context_window("200K") == 200_000
    assert parse_context_window("1M") == 1_000_000
    assert parse_context_window("128,000") == 128_000


def test_legacy_chat_agent_is_migrated_to_ruflo() -> None:
    agents = _parse_agents({
        "agents": [{
            "name": "chat",
            "model": "local-model",
            "skills": ["reverse"],
        }],
    })

    assert agents == [AgentConfig(name="ruflo", model="local-model", skills=["reverse"])]


def test_skill_zip_install_requires_skill_md(monkeypatch) -> None:
    workspace = Path("build/test-skill-install").resolve()
    shutil.rmtree(workspace, ignore_errors=True)
    workspace.mkdir(parents=True)
    monkeypatch.chdir(workspace)

    archive = workspace / "demo-skill.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("demo-skill/SKILL.md", "# Demo skill\n")

    target = install_skill_from_zip(archive, scope="workspace")

    assert target.name == "demo-skill"
    assert (target / "SKILL.md").is_file()
    shutil.rmtree(workspace, ignore_errors=True)


def test_http_mcp_transport_maps_to_langchain_streamable_http() -> None:
    config = McpServerDTO(
        id=None,
        name="local-http-tools",
        transport="http",
        enabled=True,
        command="",
        args="",
        env="",
        cwd="",
        encoding="utf-8",
        url="http://127.0.0.1:8000/mcp",
        headers="",
        timeout=60,
        sse_read_timeout=300,
    )

    assert config.to_langchain_config()["transport"] == "streamable_http"


def test_default_workflow_is_ruflo() -> None:
    init_workflows()

    assert get_registry().current_name() == "ruflo"


def test_ruflo_prompt_requires_compact_subagent_results() -> None:
    prompt = build_ruflo_prompt("Base prompt")

    assert "delegate_task" in prompt
    assert "compact results" in prompt
    assert "hidden chain-of-thought" in SUBAGENT_RESULT_TEMPLATE


def test_default_agent_middleware_uses_current_workspace_filesystem(
    monkeypatch,
) -> None:
    from deepagents.backends import FilesystemBackend
    from deepagents.middleware import FilesystemMiddleware
    from langchain.agents.middleware import TodoListMiddleware
    from langchain.agents.middleware.shell_tool import ShellToolMiddleware

    workspace = Path("build/test-default-agent-middleware").resolve()
    shutil.rmtree(workspace, ignore_errors=True)
    workspace.mkdir(parents=True)
    monkeypatch.chdir(workspace)
    try:
        middleware = build_agent_middleware()

        assert len(middleware) == 3
        assert isinstance(middleware[0], TodoListMiddleware)
        assert isinstance(middleware[1], FilesystemMiddleware)
        assert isinstance(middleware[1].backend, FilesystemBackend)
        assert middleware[1].backend.cwd == workspace
        assert middleware[1].backend.virtual_mode is True
        assert isinstance(middleware[2], ShellToolMiddleware)
        assert middleware[2]._workspace_root == workspace
    finally:
        monkeypatch.chdir(Path(__file__).resolve().parents[1])
        shutil.rmtree(workspace, ignore_errors=True)


def test_model_agent_middleware_adds_context_and_quality_helpers(
    monkeypatch,
) -> None:
    from deepagents.backends import FilesystemBackend
    from deepagents.middleware import (
        FilesystemMiddleware,
        RubricMiddleware,
        SummarizationMiddleware,
        SummarizationToolMiddleware,
    )
    from langchain.agents.middleware import TodoListMiddleware
    from langchain.agents.middleware.shell_tool import ShellToolMiddleware
    from langchain_core.language_models.fake_chat_models import FakeListChatModel

    workspace = Path("build/test-model-agent-middleware").resolve()
    shutil.rmtree(workspace, ignore_errors=True)
    workspace.mkdir(parents=True)
    monkeypatch.chdir(workspace)
    try:
        middleware = build_agent_middleware_for_model(
            FakeListChatModel(responses=["summary"])
        )

        assert len(middleware) == 6
        assert isinstance(middleware[0], TodoListMiddleware)
        assert isinstance(middleware[1], FilesystemMiddleware)
        assert isinstance(middleware[1].backend, FilesystemBackend)
        assert middleware[1].backend.cwd == workspace
        assert middleware[1].backend.virtual_mode is True
        assert isinstance(middleware[2], ShellToolMiddleware)
        assert middleware[2]._workspace_root == workspace
        assert isinstance(middleware[3], SummarizationMiddleware)
        assert isinstance(middleware[4], SummarizationToolMiddleware)
        assert isinstance(middleware[5], RubricMiddleware)
    finally:
        monkeypatch.chdir(Path(__file__).resolve().parents[1])
        shutil.rmtree(workspace, ignore_errors=True)


def test_compaction_trigger_uses_model_context_budget(monkeypatch) -> None:
    config = CliConfig(
        active_model="default",
        models=[ProviderConfig(
            name="default",
            model_name="gpt-4o",
            max_context_tokens=1_000,
        )],
        agents=[AgentConfig(name="ruflo", model="default")],
    )
    workspace = Path("build/test-compact-budget").resolve()
    shutil.rmtree(workspace, ignore_errors=True)
    workspace.mkdir(parents=True)

    monkeypatch.chdir(workspace)
    store = Store()
    session = Session(config, store)
    session._history = [
        ConversationMessage(role="user", content="x" * 4_000)
    ]

    assert session._should_compact(session._context_budget("ruflo"))
    keep_tail, older = session._split_for_compaction(session._context_budget("ruflo"))
    assert keep_tail == []
    assert len(older) == 1

    store.close()
    shutil.rmtree(workspace, ignore_errors=True)


def test_context_compaction_counts_fixed_overhead_and_upcoming_input() -> None:
    compactor = ContextCompactor(ContextWindowPolicy(
        max_context_tokens=10_000,
        trigger_ratio=0.90,
        raw_tail_ratio=0.55,
        minimum_output_reserve_tokens=1_000,
        static_prompt_tokens=1_000,
    ))
    history = [ConversationMessage(role="assistant", content="x" * 24_000)]

    plan = compactor.plan(history, upcoming_text="y" * 8_000)

    assert plan.should_compact
    assert plan.estimated_input_tokens >= 8_000
    assert plan.trigger_tokens == 9_000


def test_store_replace_messages_after_compaction(monkeypatch) -> None:
    workspace = Path("build/test-compact-store").resolve()
    shutil.rmtree(workspace, ignore_errors=True)
    workspace.mkdir(parents=True)
    monkeypatch.chdir(workspace)

    store = Store()
    cid = store.create_conversation()
    old = ConversationMessage(
        conversation_id=cid,
        turn_id="old",
        role="user",
        content="old large history",
    )
    memory = ConversationMessage(
        conversation_id=cid,
        turn_id="compact",
        role="system",
        content="Structured memory",
    )

    store.save_message(cid, old.turn_id, old.role, old.content)
    store.replace_messages(cid, [memory])
    store.save_memory_artifact(cid, "Goals:\n- keep useful facts", source_count=1)

    rows = store.load_messages(cid)
    artifacts = store.load_memory_artifacts(cid)

    assert [row["content"] for row in rows] == ["Structured memory"]
    assert artifacts[0]["source_count"] == 1

    store.close()
    shutil.rmtree(workspace, ignore_errors=True)


def test_input_history_file_keeps_recent_unique_entries() -> None:
    workspace = Path("build/test-input-history").resolve()
    shutil.rmtree(workspace, ignore_errors=True)
    workspace.mkdir(parents=True)
    history_file = workspace / ".history"

    append_input_history("first", history_file)
    append_input_history("second", history_file)
    append_input_history("first", history_file)

    assert load_input_history(history_file) == ["second", "first"]

    shutil.rmtree(workspace, ignore_errors=True)


@pytest.mark.anyio
async def test_history_input_navigation_and_completion() -> None:
    workspace = Path("build/test-history-input-widget").resolve()
    shutil.rmtree(workspace, ignore_errors=True)
    workspace.mkdir(parents=True)
    history_file = workspace / ".history"
    append_input_history("audit fortios init", history_file)
    append_input_history("list functions", history_file)

    class HistoryInputApp(App[None]):
        def compose(self) -> ComposeResult:
            yield HistoryInput(history_path=history_file)

    app = HistoryInputApp()

    async with app.run_test():
        input_widget = app.query_one(HistoryInput)

        input_widget._previous_history()
        assert input_widget.value == "list functions"

        input_widget._previous_history()
        assert input_widget.value == "audit fortios init"

        input_widget._next_history()
        assert input_widget.value == "list functions"

        input_widget.value = "/wor"
        input_widget._complete()
        assert input_widget.value == "/workflow "

        input_widget.value = "/workflow au"
        input_widget._complete()
        assert input_widget.value == "/workflow audit"

        input_widget.value = "audit"
        input_widget._complete()
        assert input_widget.value == "audit fortios init"

    shutil.rmtree(workspace, ignore_errors=True)


@pytest.mark.anyio
async def test_plugin_app_switches_mcp_and_skill_panes() -> None:
    app = PluginApp(CliConfig())

    async with app.run_test():
        assert app.query_one("#apply-mcp", Button).display is True
        assert app.query_one("#check-mcp", Button).display is True
        assert app.query_one("#install-skill", Button).display is False
        assert app._item_labels() == ["No MCP configured"]
        assert "new stdio" not in app._item_labels()
        assert "new http" not in app._item_labels()
        assert "new sse" not in app._item_labels()
        assert app.query_one("#mcp-transport", Select).value == "stdio"
        assert app.query_one("#mcp-command", Input).display is True
        assert app.query_one("#mcp-url", Input).display is False
        assert app.query_one("#mcp-headers", Input).display is False

        app.query_one("#mcp-transport", Select).value = "http"
        app._show_mcp_transport_fields("http")

        assert app.query_one("#mcp-command", Input).display is False
        assert app.query_one("#mcp-args", Input).display is False
        assert app.query_one("#mcp-env", Input).display is False
        assert app.query_one("#mcp-url", Input).display is True
        assert app.query_one("#mcp-headers", Input).display is True

        app.section = "Skills"
        app._refresh_detail()
        app._refresh_buttons()

        assert app.query_one("#apply-mcp", Button).display is False
        assert app.query_one("#check-mcp", Button).display is False
        assert app.query_one("#install-skill", Button).display is True
        assert app.query_one("#skill-scope", Select).value == "workspace"


@pytest.mark.anyio
async def test_plugin_app_populates_configured_mcp_for_editing() -> None:
    app = PluginApp(CliConfig(mcp_servers=[
        McpServerConfig(
            name="ida-mcp",
            transport="http",
            url="http://127.0.0.1:11338/mcp",
        )
    ]))

    async with app.run_test():
        app.selected = 0
        app._refresh_detail()

        assert app.query_one("#mcp-name", Input).value == "ida-mcp"
        assert app.query_one("#mcp-transport", Select).value == "http"
        assert app.query_one("#mcp-url", Input).value == "http://127.0.0.1:11338/mcp"
        assert app.query_one("#mcp-url", Input).display is True
        assert app.query_one("#mcp-headers", Input).display is True
        assert app.query_one("#mcp-command", Input).display is False


@pytest.mark.anyio
async def test_plugin_app_current_mcp_ignores_hidden_transport_fields() -> None:
    app = PluginApp(CliConfig())

    async with app.run_test():
        app.query_one("#mcp-name", Input).value = "local-tools"
        app.query_one("#mcp-transport", Select).value = "stdio"
        app.query_one("#mcp-command", Input).value = "python"
        app.query_one("#mcp-url", Input).value = "http://old.example/mcp"
        app.query_one("#mcp-headers", Input).value = '{"Authorization":"old"}'

        stdio = app._current_mcp_server()

        assert stdio.transport == "stdio"
        assert stdio.command == "python"
        assert stdio.url == ""
        assert stdio.headers == ""

        app.query_one("#mcp-transport", Select).value = "http"
        app.query_one("#mcp-url", Input).value = "http://127.0.0.1:8000/mcp"
        app.query_one("#mcp-command", Input).value = "old-command"

        http = app._current_mcp_server()

        assert http.transport == "http"
        assert http.url == "http://127.0.0.1:8000/mcp"
        assert http.command == ""


@pytest.mark.anyio
async def test_plugin_app_check_mcp_shows_loading_state(monkeypatch) -> None:
    started = asyncio.Event()
    release = asyncio.Event()

    async def fake_check(_server: McpServerConfig) -> list[object]:
        started.set()
        await release.wait()
        return [object()]

    monkeypatch.setattr(plugin_app_module, "_check_mcp_server", fake_check)
    app = PluginApp(CliConfig())

    async with app.run_test():
        app.query_one("#mcp-name", Input).value = "local-tools"
        app.query_one("#mcp-command", Input).value = "python"

        await app._check_mcp()
        await asyncio.wait_for(started.wait(), timeout=1)
        await asyncio.sleep(0.4)

        button = app.query_one("#check-mcp", Button)
        assert button.disabled is True
        assert button.label.plain.startswith("Check ")

        release.set()
        assert app._check_task is not None
        await app._check_task

        assert button.disabled is False
        assert button.label.plain == "Check"
        assert "OK: 1 tool(s)" in app.status


@pytest.mark.anyio
async def test_plugin_app_skillhub_results_install_from_right_pane(monkeypatch) -> None:
    installed: list[tuple[str, str]] = []

    def fake_search(_query: str, *, registry_url: str) -> list[plugin_app_module.SkillSearchResult]:
        assert registry_url
        return [plugin_app_module.SkillSearchResult(
            name="demo-skill",
            description="Demo skill",
            url="https://example.test/demo-skill.zip",
        )]

    def fake_install(url: str, *, scope: str) -> Path:
        installed.append((url, scope))
        return Path("build/test-skillhub-result/demo-skill")

    monkeypatch.setattr(plugin_app_module, "search_skillshub", fake_search)
    monkeypatch.setattr(plugin_app_module, "install_skill_from_url", fake_install)
    app = PluginApp(CliConfig())

    async with app.run_test():
        app.section = "Skills"
        app._refresh_detail()
        await app._refresh_skill_results()

        assert len(app.query("#skill-name")) == 0

        app.query_one("#skillshub-query", Input).value = "demo"
        await app._search_skillshub()

        install_buttons = list(app.query("#skill-results Button"))
        assert len(install_buttons) == 1
        assert install_buttons[0].id == "install-skill-result-0"

        await app._install_skill_result("install-skill-result-0")

        assert installed == [("https://example.test/demo-skill.zip", "workspace")]
        assert "Skill installed and validated" in app.status


@pytest.mark.anyio
async def test_main_app_handles_core_commands_inside_textual() -> None:
    app = MainApp(CliConfig(models=[ProviderConfig(name="default", model_name="gpt-4o")]))

    async with app.run_test() as pilot:
        bar = app.query_one(InputBar)
        input_widget = bar.query_one("#user-input", Input)

        input_widget.value = "/workflow"
        bar._submit_input()
        await pilot.pause()

        input_widget.value = "/status"
        bar._submit_input()
        await pilot.pause()

        input_widget.value = "/models"
        bar._submit_input()
        await pilot.pause()

        input_widget.value = "/history"
        bar._submit_input()
        await pilot.pause()

        input_widget.value = "/graph"
        bar._submit_input()
        await pilot.pause()

        await app._handle_config_command()
        await pilot.pause()
        assert type(app.screen).__name__ == "ConfigScreen"

        app.screen.dismiss(None)
        await pilot.pause()

        input_widget.value = "/plugin"
        bar._submit_input()
        await pilot.pause()
        assert type(app.screen).__name__ == "PluginScreen"

        app.screen.dismiss(None)
        await pilot.pause()


@pytest.mark.anyio
async def test_main_app_suppresses_parallel_subagent_detail() -> None:
    app = MainApp(CliConfig(models=[ProviderConfig(name="default", model_name="gpt-4o")]))

    async with app.run_test():
        await app.on_stream_event_message(StreamEventMessage(StreamEvent(
            type=StreamEventType.SUBAGENT_START,
            payload={"subagent": "recon"},
        )))
        await app.on_stream_event_message(StreamEventMessage(StreamEvent(
            type=StreamEventType.SUBAGENT_START,
            payload={"subagent": "hunt"},
        )))
        await app.on_stream_event_message(StreamEventMessage(StreamEvent(
            type=StreamEventType.TOKEN,
            payload={"subagent": "recon", "content": "hidden detail"},
        )))

        assert app._active_agents == ["recon", "hunt"]
        assert app.query_one(Sidebar)._current_agents == ["recon", "hunt"]
        assert app.query_one(ChatArea).get_current_assistant() is None


@pytest.mark.anyio
async def test_main_app_ignores_orphan_whitespace_tokens() -> None:
    app = MainApp(CliConfig(models=[ProviderConfig(name="default", model_name="gpt-4o")]))

    async with app.run_test():
        await app.on_stream_event_message(StreamEventMessage(StreamEvent(
            type=StreamEventType.TOKEN,
            payload={"subagent": "orchestrator", "content": "\n"},
        )))
        await app.on_stream_event_message(StreamEventMessage(StreamEvent(
            type=StreamEventType.TOKEN,
            payload={"subagent": "recon", "content": "I'll start"},
        )))

        assistants = [
            child
            for child in app.query_one(ChatArea).children
            if isinstance(child, AssistantMessage)
        ]

        assert len(assistants) == 1
        assert assistants[0].speaker == "recon"


@pytest.mark.anyio
async def test_main_app_interleaves_markdown_and_collapsed_tool_events() -> None:
    app = MainApp(CliConfig(models=[ProviderConfig(name="default", model_name="gpt-4o")]))

    async with app.run_test():
        await app.on_stream_event_message(StreamEventMessage(StreamEvent(
            type=StreamEventType.TOKEN,
            payload={"subagent": "orchestrator", "content": "Before tool.\n"},
        )))
        await app.on_stream_event_message(StreamEventMessage(StreamEvent(
            type=StreamEventType.TOOL_START,
            payload={
                "subagent": "orchestrator",
                "tool_name": "IDA-MCP_decompile",
                "tool_call_id": "call-1",
                "args": {"address": "0x401000"},
            },
        )))
        await app.on_stream_event_message(StreamEventMessage(StreamEvent(
            type=StreamEventType.TOOL_RESULT,
            payload={
                "subagent": "orchestrator",
                "tool_name": "IDA-MCP_decompile",
                "tool_call_id": "call-1",
                "result": "decompiled main",
            },
        )))
        await app.on_stream_event_message(StreamEventMessage(StreamEvent(
            type=StreamEventType.SKILL_TRIGGERED,
            payload={
                "subagent": "orchestrator",
                "skill_name": "idapython",
                "event": "skill_loaded",
                "detail": "loaded SKILL.md",
            },
        )))
        await app.on_stream_event_message(StreamEventMessage(StreamEvent(
            type=StreamEventType.TOKEN,
            payload={"subagent": "orchestrator", "content": "After tool."},
        )))

        chat = app.query_one(ChatArea)
        flow = [
            child
            for child in chat.children
            if isinstance(child, (AssistantMessage, ToolCallWidget))
            or (isinstance(child, Static) and "tool-line" in child.classes)
        ]

        assert [type(child) for child in flow] == [
            AssistantMessage,
            ToolCallWidget,
            Static,
            AssistantMessage,
        ]
        tool_blocks = [child for child in flow if isinstance(child, ToolCallWidget)]
        assert len(tool_blocks) == 1
        assert tool_blocks[0].tool_name == "IDA-MCP_decompile"
        assert tool_blocks[0].status == "done"
        assert tool_blocks[0].collapsed is True
        skill_lines = [
            child for child in flow
            if isinstance(child, Static) and "tool-line" in child.classes
        ]
        assert len(skill_lines) == 1
        assert "idapython" in skill_lines[0].content.plain


@pytest.mark.anyio
async def test_chat_area_follow_stays_sticky_until_user_scrolls(monkeypatch) -> None:
    class ChatScrollApp(App[None]):
        def compose(self) -> ComposeResult:
            yield ChatArea()

    app = ChatScrollApp()

    async with app.run_test():
        chat = app.query_one(ChatArea)

        monkeypatch.setattr(ChatArea, "_is_near_vertical_end", lambda self: False)
        assert chat.should_follow() is True

        chat.watch_scroll_y(10, 5)
        assert chat.should_follow() is False

        monkeypatch.setattr(ChatArea, "_is_near_vertical_end", lambda self: True)
        assert chat.should_follow() is True


def test_chat_area_follow_scrolls_after_layout_refresh(monkeypatch) -> None:
    chat = ChatArea()
    scroll_calls = 0
    scheduled: list[object] = []

    def fake_scroll_end(self, **kwargs) -> None:
        nonlocal scroll_calls
        assert kwargs["animate"] is False
        assert kwargs["immediate"] is True
        scroll_calls += 1

    def fake_schedule(self, callback) -> None:
        scheduled.append(callback)

    monkeypatch.setattr(ChatArea, "scroll_end", fake_scroll_end)
    monkeypatch.setattr(ChatArea, "call_after_refresh", fake_schedule)
    monkeypatch.setattr(ChatArea, "call_later", fake_schedule)

    chat.follow_if(True)

    assert scroll_calls == 1
    assert len(scheduled) == 2

    for callback in scheduled:
        callback()

    assert scroll_calls == 3


@pytest.mark.anyio
async def test_main_app_updates_ruflo_graph_for_delegate_task() -> None:
    app = MainApp(CliConfig(models=[ProviderConfig(name="default", model_name="gpt-4o")]))

    async with app.run_test():
        await app.on_stream_event_message(StreamEventMessage(StreamEvent(
            type=StreamEventType.TOOL_START,
            payload={
                "subagent": "orchestrator",
                "tool_name": "delegate_task",
                "tool_call_id": "call-1",
                "args": {
                    "subagent_name": "recon",
                    "task": "collect context",
                },
            },
        )))

        sidebar = app.query_one(Sidebar)
        active_text = sidebar.query_one("#workflow-graph", Static).content.plain
        assert "agents run  1" in active_text
        assert "▶ recon" in active_text

        await app.on_stream_event_message(StreamEventMessage(StreamEvent(
            type=StreamEventType.TOOL_RESULT,
            payload={
                "subagent": "orchestrator",
                "tool_name": "delegate_task",
                "tool_call_id": "call-1",
                "result": "done",
            },
        )))

        done_text = sidebar.query_one("#workflow-graph", Static).content.plain
        assert "active  idle" in done_text
        assert "✓ recon" in done_text


@pytest.mark.anyio
async def test_config_app_refresh_form_replaces_existing_field_widgets() -> None:
    config = CliConfig(
        active_model="default",
        models=[
            ProviderConfig(name="default", model_name="gpt-4o"),
            ProviderConfig(name="backup", model_name="gpt-4o-mini"),
        ],
    )
    app = ConfigApp(config)

    async with app.run_test():
        app.selected = 1
        await app._refresh_form()
        app.selected = 0
        await app._refresh_form()

        assert app.query_one("#field-name", Input).value == "default"
        assert app.query_one("#field-api_mode", Select).value == "openai_compatible"
        assert len(app.query("#form-fields Input")) == len(ConfigApp._MODEL_FIELDS) - 1


@pytest.mark.anyio
async def test_config_app_does_not_show_mcp_section() -> None:
    app = ConfigApp(CliConfig(models=[ProviderConfig(name="default")]))

    async with app.run_test():
        sections = app.query_one("#section-list", ListView)

        assert len(sections.children) == 2
        assert app._section_labels() == ["Models", "Workflow"]


@pytest.mark.anyio
async def test_config_app_hides_new_delete_buttons_in_workflow_section() -> None:
    app = ConfigApp(CliConfig(models=[ProviderConfig(name="default")]))

    async with app.run_test():
        app.section = "Workflow"
        app._refresh_buttons()

        assert app.query_one("#new", Button).display is False
        assert app.query_one("#delete", Button).display is False

        app.section = "Models"
        app._refresh_buttons()
        assert app.query_one("#new", Button).display is True
        assert app.query_one("#delete", Button).display is True


@pytest.mark.anyio
async def test_config_app_api_mode_is_selected_from_fixed_options() -> None:
    app = ConfigApp(CliConfig(models=[ProviderConfig(name="default")]))

    async with app.run_test():
        select = app.query_one("#field-api_mode", Select)
        select.value = "anthropic"

        assert select.value == "anthropic"
        assert app._apply_form()
        assert app.models[0].api_mode == "anthropic"


@pytest.mark.anyio
async def test_config_app_groups_agents_by_workflow() -> None:
    app = ConfigApp(CliConfig(
        models=[
            ProviderConfig(name="default", model_name="gpt-4o"),
            ProviderConfig(name="backup", model_name="claude-sonnet"),
        ],
        agents=[
            AgentConfig(name="ruflo"),
            AgentConfig(name="audit.recon"),
            AgentConfig(name="audit.hunt"),
            AgentConfig(name="audit-slim.verify"),
        ],
    ))

    async with app.run_test():
        app.section = "Workflow"
        app.selected = 1
        await app._refresh_items()
        await app._refresh_form()
        recon_index = next(index for index, agent in enumerate(app.agents) if agent.name == "audit.recon")
        recon_model = app.query_one(f"#field-agent-{recon_index}-model", Select)

        assert app._item_labels() == ["ruflo", "audit", "audit-slim"]
        assert recon_model.value == "default"
        recon_model.value = "backup"
        assert app._apply_form()
        assert app.agents[recon_index].model == "backup"


@pytest.mark.anyio
async def test_config_app_model_display_uses_model_id_over_default_alias() -> None:
    app = ConfigApp(CliConfig(
        active_model="default",
        models=[ProviderConfig(name="default", model_name="gpt-4o")],
    ))

    async with app.run_test():
        assert app._item_labels() == ["* gpt-4o"]
        assert app._model_options("default") == [("gpt-4o", "default")]


@pytest.mark.anyio
async def test_config_app_model_rename_updates_workflow_agent_refs() -> None:
    app = ConfigApp(CliConfig(
        active_model="default",
        models=[ProviderConfig(name="default", model_name="gpt-4o")],
        agents=[
            AgentConfig(name="ruflo", model="default"),
            AgentConfig(name="audit.recon", model="default"),
        ],
    ))

    async with app.run_test():
        app.query_one("#field-name", Input).value = "main-model"

        assert app._apply_form()
        assert app.active_model == "main-model"
        assert {agent.model for agent in app.agents} == {"main-model"}

        app.section = "Workflow"
        app.selected = 0
        await app._refresh_form()
        ruflo_index = next(index for index, agent in enumerate(app.agents) if agent.name == "ruflo")
        assert app.query_one(f"#field-agent-{ruflo_index}-model", Select).value == "main-model"


@pytest.mark.anyio
async def test_config_app_accepts_context_window_suffixes() -> None:
    app = ConfigApp(CliConfig(models=[ProviderConfig(name="default")]))

    async with app.run_test():
        app.query_one("#field-max_context_tokens", Input).value = "1M"

        assert app._apply_form()
        assert app.models[0].max_context_tokens == 1_000_000


@pytest.mark.anyio
async def test_config_app_edits_agent_mcp_and_skills_with_wildcard_defaults() -> None:
    app = ConfigApp(CliConfig(
        models=[ProviderConfig(name="default")],
        agents=[AgentConfig(name="ruflo", mcp=["ida-mcp"], skills=[])],
    ))

    async with app.run_test():
        app.section = "Workflow"
        app.selected = 0
        await app._refresh_form()
        ruflo_index = next(index for index, agent in enumerate(app.agents) if agent.name == "ruflo")
        app.query_one(f"#field-agent-{ruflo_index}-mcp", Input).value = ""
        app.query_one(f"#field-agent-{ruflo_index}-skills", Input).value = ""

        assert app._apply_form()
        assert app.agents[ruflo_index].mcp == ["*"]
        assert app.agents[ruflo_index].skills == ["*"]


@pytest.mark.anyio
async def test_session_compact_context_persists_replay_history(monkeypatch) -> None:
    config = CliConfig(
        active_model="default",
        models=[ProviderConfig(
            name="default",
            model_name="gpt-4o",
            max_context_tokens=1_000,
        )],
        agents=[AgentConfig(name="ruflo", model="default")],
    )
    workspace = Path("build/test-session-compact-store").resolve()
    shutil.rmtree(workspace, ignore_errors=True)
    workspace.mkdir(parents=True)
    monkeypatch.chdir(workspace)

    store = Store()
    session = Session(config, store)
    cid = session.new_conversation()
    message = ConversationMessage(
        conversation_id=cid,
        turn_id="t1",
        role="user",
        content="x" * 4_000,
    )
    session._history = [message]
    store.save_message(cid, message.turn_id, message.role, message.content)

    async def fake_summary(messages: list[ConversationMessage], *, workflow: str = "ruflo") -> str:
        return "Goals:\n- preserve compacted facts"

    monkeypatch.setattr(session, "_summarize_messages", fake_summary)

    changed = await session.compact_context(force=True, workflow="ruflo")
    rows = store.load_messages(cid)
    artifacts = store.load_memory_artifacts(cid)

    assert changed
    assert len(rows) == 1
    assert rows[0]["role"] == "system"
    assert "Structured memory compacted" in rows[0]["content"]
    assert artifacts[0]["content"] == "Goals:\n- preserve compacted facts"

    store.close()
    shutil.rmtree(workspace, ignore_errors=True)
