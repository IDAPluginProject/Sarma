from __future__ import annotations

import asyncio
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path

import pytest
from rich.console import Console
from textual.widgets import Button, Input, ListView, Select

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
from sarma_cli.engine.dto import McpServerDTO, ModelProviderDTO
from sarma_cli.engine.models import AgentRunConfig, ConversationMessage
from sarma_cli.engine.mcp_pool import _connect_timeout
from sarma_cli.resources.plugins import (
    create_mcp_server,
    install_skill_from_zip,
    list_mcp_quick_modes,
    validate_mcp_server,
)
from sarma_cli.runtime.resolver import RuntimePolicyResolver
from sarma_cli.store import Store
from sarma_cli.workflows import get_registry, init_workflows
from sarma_cli.engine.ruflo import SUBAGENT_RESULT_TEMPLATE, build_ruflo_prompt
from sarma_cli.session import Session
from sarma_cli.status import render_status_panel
from sarma_cli.context.compaction import ContextCompactor, ContextWindowPolicy
import sarma_cli.tui.plugin_app as plugin_app_module
from sarma_cli.tui.config_app import ConfigApp
from sarma_cli.tui.plugin_app import PluginApp


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


def test_mcp_connect_timeout_is_capped_for_responsiveness() -> None:
    assert _connect_timeout({"local": {"transport": "stdio"}}) == 20.0
    assert _connect_timeout({"local": {"transport": "http", "timeout": 60}}) == 20.0
    assert _connect_timeout({"local": {"transport": "http", "timeout": 5}}) == 5.0


def test_status_panel_shows_mcp_runtime_and_tools() -> None:
    config = CliConfig(
        models=[ProviderConfig(name="default", model_name="gpt-4o")],
        mcp_servers=[McpServerConfig(name="ida-mcp", transport="http", enabled=True)],
    )
    console = Console(record=True, width=120)

    console.print(render_status_panel(config, pool=StatusPool()))
    text = console.export_text()

    assert "ida-mcp (http)" in text
    assert "connected" in text
    assert "ida-mcp_decompile" in text
    assert "ida-mcp_disasm" in text


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
