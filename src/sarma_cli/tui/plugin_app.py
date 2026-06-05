"""Textual plugin manager for MCP servers and skills."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
import asyncio
from collections.abc import Awaitable, Callable

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Header, Input, Label, ListItem, ListView, Select, Static

from sarma_cli.config import (
    CliConfig,
    McpServerConfig,
    load_global_mcp_servers,
    load_local_mcp_servers,
)
from sarma_cli.engine.dto import McpServerDTO
from sarma_cli.engine.mcp_pool import McpClientPool
from sarma_cli.resources.plugins import (
    DEFAULT_SKILLSHUB_URL,
    SkillSearchResult,
    create_mcp_server,
    install_skill_from_path,
    install_skill_from_url,
    list_mcp_quick_modes,
    search_skillshub,
    upsert_mcp_server,
)
from sarma_cli.resources.skills import list_available_skills
from sarma_cli.tui.theme import PLUGIN_APP_CSS

SECTION_MCP = "MCP"
SECTION_SKILLS = "Skills"
MCP_BASE_FIELDS = ("mcp-name",)
MCP_STDIO_FIELDS = ("mcp-command", "mcp-args", "mcp-env")
MCP_REMOTE_FIELDS = ("mcp-url", "mcp-headers")


@dataclass(slots=True)
class PluginEditResult:
    mcp_servers: list[McpServerConfig]
    local_mcp_servers: list[McpServerConfig]
    global_mcp_servers: list[McpServerConfig]
    changed: bool = False
    restart_requested: bool = False


class PluginViewMixin:
    """Shared plugin manager view for standalone and embedded TUI usage."""

    BINDINGS = [
        ("ctrl+s", "save", "Save"),
        ("escape", "cancel", "Close"),
    ]

    CSS = PLUGIN_APP_CSS

    def __init__(self, config: CliConfig) -> None:
        super().__init__()
        self.global_mcp_servers = load_global_mcp_servers()
        self.local_mcp_servers = load_local_mcp_servers()
        if not self.global_mcp_servers and not self.local_mcp_servers and config.mcp_servers:
            self.local_mcp_servers = deepcopy(config.mcp_servers)
        self.mcp_servers = _merge_mcp_servers(
            self.global_mcp_servers,
            self.local_mcp_servers,
        )
        self.section = SECTION_MCP
        self.selected = 0
        self.changed = False
        self.restart_requested = False
        self.search_results: list[SkillSearchResult] = []
        self.status = "Use the buttons to manage MCP servers and skills."
        self._check_task: asyncio.Task[None] | None = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Horizontal(id="shell"):
            with Vertical(id="sections"):
                yield Static("Plugins", classes="hint")
                yield ListView(
                    ListItem(Label(SECTION_MCP)),
                    ListItem(Label(SECTION_SKILLS)),
                    id="section-list",
                )
            with Vertical(id="items"):
                yield Static("Configured MCP / Installed skills", classes="hint")
                yield ListView(id="item-list")
            with Vertical(id="detail"):
                yield Static("", id="title")
                yield Static("", id="description")

                with VerticalScroll(id="detail-fields"):
                    yield Label("MCP name", id="label-mcp-name", classes="field-label")
                    yield Input(id="mcp-name", placeholder="my-mcp")
                    yield Label("MCP transport", id="label-mcp-transport", classes="field-label")
                    yield Select(
                        [(mode, mode) for mode in list_mcp_quick_modes()],
                        value="stdio",
                        allow_blank=False,
                        id="mcp-transport",
                    )
                    yield Label("Enabled", id="label-mcp-enabled", classes="field-label")
                    yield Select(
                        [("true", "true"), ("false", "false")],
                        value="true",
                        allow_blank=False,
                        id="mcp-enabled",
                    )
                    yield Label("MCP scope", id="label-mcp-scope", classes="field-label")
                    yield Select(
                        [("workspace", "workspace"), ("global", "global")],
                        value="workspace",
                        allow_blank=False,
                        id="mcp-scope",
                    )
                    yield Label("URL (http/sse)", id="label-mcp-url", classes="field-label")
                    yield Input(id="mcp-url", placeholder="http://127.0.0.1:8000/mcp")
                    yield Label("Command (stdio)", id="label-mcp-command", classes="field-label")
                    yield Input(id="mcp-command", placeholder="uvx my-mcp-server")
                    yield Label("Args JSON (stdio)", id="label-mcp-args", classes="field-label")
                    yield Input(id="mcp-args", placeholder='["--flag"]')
                    yield Label("Env JSON (stdio)", id="label-mcp-env", classes="field-label")
                    yield Input(id="mcp-env", placeholder='{"TOKEN":"..."}')
                    yield Label("Headers JSON (http/sse)", id="label-mcp-headers", classes="field-label")
                    yield Input(id="mcp-headers", placeholder='{"Authorization":"Bearer ..."}')

                    yield Label("Skill source", id="label-skill-source", classes="field-label")
                    yield Input(id="skill-source", placeholder="Directory, skills.zip, or https://.../skill.zip")
                    yield Label("Skill scope", id="label-skill-scope", classes="field-label")
                    yield Select(
                        [("workspace", "workspace"), ("global", "global")],
                        value="workspace",
                        allow_blank=False,
                        id="skill-scope",
                    )
                    yield Label("Skillshub registry", id="label-skillshub-url", classes="field-label")
                    yield Input(id="skillshub-url", value=DEFAULT_SKILLSHUB_URL)
                    yield Label("Skillshub query", id="label-skillshub-query", classes="field-label")
                    yield Input(id="skillshub-query", placeholder="Search skills")
                    yield Label("Skillshub results", id="label-skill-results", classes="field-label")
                    yield Vertical(id="skill-results")

                with Horizontal(id="buttons"):
                    yield Static("", id="button-spacer")
                    yield Button("Apply", id="apply-mcp", variant="success")
                    yield Button("Check", id="check-mcp")
                    yield Button("Install Skill", id="install-skill", variant="success")
                    yield Button("Search Skillshub", id="search-skillshub")
                    yield Button("Save", id="save")
                    yield Button("Close", id="close")
        yield Static(self.status, id="status")

    async def on_mount(self) -> None:
        self.query_one("#section-list", ListView).index = 0
        await self._refresh_items()
        self._refresh_detail()
        self._refresh_buttons()

    async def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.list_view.id == "section-list":
            self.section = [SECTION_MCP, SECTION_SKILLS][event.list_view.index or 0]
            self.selected = 0
            await self._refresh_items()
            self._refresh_detail()
            if self.section == SECTION_SKILLS:
                await self._refresh_skill_results()
            self._refresh_buttons()
        elif event.list_view.id == "item-list":
            self.selected = event.list_view.index or 0
            self._refresh_detail()

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "apply-mcp":
            await self._apply_mcp()
        elif event.button.id == "check-mcp":
            await self._check_mcp()
        elif event.button.id == "install-skill":
            await self._install_skill()
        elif event.button.id == "search-skillshub":
            await self._search_skillshub()
        elif event.button.id and event.button.id.startswith("install-skill-result-"):
            await self._install_skill_result(event.button.id)
        elif event.button.id == "save":
            self.action_save()
        elif event.button.id == "close":
            self.action_cancel()

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "mcp-transport" and self.section == SECTION_MCP:
            self._show_mcp_transport_fields(str(event.value))

    def action_save(self) -> None:
        self._finish(PluginEditResult(
            mcp_servers=deepcopy(self.mcp_servers),
            local_mcp_servers=deepcopy(self.local_mcp_servers),
            global_mcp_servers=deepcopy(self.global_mcp_servers),
            changed=self.changed,
            restart_requested=self.restart_requested or self.changed,
        ))

    def action_cancel(self) -> None:
        self._finish(None)

    def _finish(self, result: PluginEditResult | None) -> None:
        raise NotImplementedError

    async def _apply_mcp(self) -> None:
        try:
            server = self._current_mcp_server()
        except Exception as exc:
            self._set_status(str(exc))
            return
        scope = self._input("mcp-scope")
        if scope == "global":
            upsert_mcp_server(self.global_mcp_servers, server)
        else:
            upsert_mcp_server(self.local_mcp_servers, server)
        self.mcp_servers = _merge_mcp_servers(
            self.global_mcp_servers,
            self.local_mcp_servers,
        )
        self.changed = True
        self.restart_requested = True
        self._set_status(
            f"MCP {server.name} applied to {scope}. Press Save to write config."
        )
        await self._refresh_items()

    async def _check_mcp(self) -> None:
        if self._check_task and not self._check_task.done():
            return
        self._check_task = asyncio.create_task(self._run_mcp_check())

    async def _run_mcp_check(self) -> None:
        stop_loading: Callable[[], Awaitable[None]] | None = None
        check_button = self.query_one("#check-mcp", Button)
        try:
            stop_loading = await self._start_check_loading()
            server = self._current_mcp_server()
            tools = await asyncio.wait_for(_check_mcp_server(server), timeout=20)
        except Exception as exc:
            self._set_status(f"MCP check failed: {exc}")
        else:
            self._set_status(f"MCP {server.name} OK: {len(tools)} tool(s) available.")
        finally:
            if stop_loading:
                await stop_loading()
            check_button.disabled = False
            check_button.label = "Check"

    async def _start_check_loading(self) -> Callable[[], Awaitable[None]]:
        check_button = self.query_one("#check-mcp", Button)
        check_button.disabled = True
        self._set_status("Checking MCP connection...")
        stop_event = asyncio.Event()

        async def animate() -> None:
            frames = ("Check .", "Check ..", "Check ...")
            index = 0
            while not stop_event.is_set():
                check_button.label = frames[index % len(frames)]
                index += 1
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=0.35)
                except TimeoutError:
                    pass

        task = asyncio.create_task(animate())

        async def stop() -> None:
            stop_event.set()
            await task

        return stop

    async def _install_skill(self) -> None:
        source = self._input("skill-source")
        if not source:
            self._set_status("Skill source is required.")
            return
        await self._install_skill_source(source)

    async def _install_skill_result(self, button_id: str) -> None:
        try:
            index = int(button_id.rsplit("-", 1)[1])
            result = self.search_results[index]
        except (IndexError, ValueError):
            self._set_status("Skillshub result is no longer available.")
            return
        if not result.url:
            self._set_status(f"Skill {result.name} has no download URL.")
            return
        await self._install_skill_source(result.url)

    async def _install_skill_source(self, source: str) -> None:
        scope = _valid_scope(self._input("skill-scope"))
        try:
            if _is_url(source):
                target = install_skill_from_url(source, scope=scope)
            else:
                target = install_skill_from_path(Path(source), scope=scope)
        except Exception as exc:
            self._set_status(str(exc))
            return
        self.changed = True
        self.restart_requested = True
        self._set_status(f"Skill installed and validated: {target}")
        await self._refresh_items()

    async def _search_skillshub(self) -> None:
        query = self._input("skillshub-query")
        registry = self._input("skillshub-url") or DEFAULT_SKILLSHUB_URL
        try:
            self.search_results = search_skillshub(query, registry_url=registry)
        except Exception as exc:
            self._set_status(str(exc))
            return
        self.section = SECTION_SKILLS
        self.selected = 0
        self.query_one("#section-list", ListView).index = 1
        await self._refresh_items()
        self._refresh_detail()
        await self._refresh_skill_results()
        self._refresh_buttons()
        self._set_status(f"Skillshub results: {len(self.search_results)}")

    async def _refresh_items(self) -> None:
        items = self.query_one("#item-list", ListView)
        await items.clear()
        labels = self._item_labels()
        for label in labels:
            await items.append(ListItem(Label(label)))
        if labels:
            items.index = min(self.selected, len(labels) - 1)

    async def _refresh_skill_results(self) -> None:
        results = self.query_one("#skill-results", Vertical)
        await results.remove_children()
        if not self.search_results:
            await results.mount(Static("No Skillshub results.", classes="hint"))
            return
        for index, result in enumerate(self.search_results):
            row = Horizontal(classes="skill-result")
            await results.mount(row)
            await row.mount(
                Static(
                    f"{result.name}\n{result.description or result.url or 'No description'}",
                    classes="skill-result-info",
                ),
                Button("Install", id=f"install-skill-result-{index}", variant="success"),
            )

    def _refresh_detail(self) -> None:
        self.query_one("#title", Static).update(f"{self.section} Plugins")
        self.query_one("#detail-fields", VerticalScroll).scroll_home(animate=False)
        if self.section == SECTION_MCP:
            server = self._selected_mcp_server()
            mode = server.transport if server else "stdio"
            self.query_one("#description", Static).update(
                f"{'Editing configured' if server else 'Create'} MCP server: {mode}."
            )
            self._fill_mcp_fields(server, mode)
            self._show_mcp_fields(True)
            self._show_skill_fields(False)
            return

        installed = ", ".join(list_available_skills()) or "none"
        self.query_one("#description", Static).update(
            f"Installed skills: {installed}. Provide a directory, zip, URL, or search Skillshub."
        )
        self._show_mcp_fields(False)
        self._show_skill_fields(True)

    def _item_labels(self) -> list[str]:
        if self.section == SECTION_MCP:
            names = sorted({server.name for server in self.mcp_servers})
            return [
                f"{name} [{self._mcp_scope_for(name)}, {self._mcp_enabled_for(name)}]"
                for name in names
            ] or ["No MCP configured"]
        installed = list_available_skills()
        return [f"{name} [installed]" for name in installed] or ["No skills installed"]

    def _selected_mcp_server(self) -> McpServerConfig | None:
        if self.section != SECTION_MCP:
            return None
        names = sorted({server.name for server in self.mcp_servers})
        if not names or self.selected >= len(names):
            return None
        target = names[self.selected]
        for server in self.mcp_servers:
            if server.name == target:
                return server
        return None

    def _current_mcp_server(self) -> McpServerConfig:
        transport = self._input("mcp-transport")
        return create_mcp_server(
            name=self._input("mcp-name"),
            transport=transport,
            url=self._input("mcp-url") if transport in {"http", "sse"} else "",
            command=self._input("mcp-command") if transport == "stdio" else "",
            args=self._input("mcp-args") if transport == "stdio" else "",
            env=self._input("mcp-env") if transport == "stdio" else "",
            headers=self._input("mcp-headers") if transport in {"http", "sse"} else "",
            enabled=self._input("mcp-enabled") != "false",
        )

    def _fill_mcp_fields(self, server: McpServerConfig | None, mode: str) -> None:
        self.query_one("#mcp-name", Input).value = server.name if server else ""
        self.query_one("#mcp-transport", Select).value = mode
        self.query_one("#mcp-enabled", Select).value = (
            "true" if server is None or server.enabled else "false"
        )
        self.query_one("#mcp-scope", Select).value = (
            self._mcp_scope_for(server.name) if server else "workspace"
        )
        self.query_one("#mcp-url", Input).value = server.url if server else ""
        self.query_one("#mcp-command", Input).value = server.command if server else ""
        self.query_one("#mcp-args", Input).value = server.args if server else ""
        self.query_one("#mcp-env", Input).value = server.env if server else ""
        self.query_one("#mcp-headers", Input).value = server.headers if server else ""

    def _show_mcp_fields(self, show: bool) -> None:
        for widget_id in MCP_BASE_FIELDS:
            self._show_input_field(widget_id, show)
        self.query_one("#mcp-transport", Select).display = show
        self.query_one("#label-mcp-transport", Label).display = show
        self.query_one("#mcp-enabled", Select).display = show
        self.query_one("#label-mcp-enabled", Label).display = show
        self.query_one("#mcp-scope", Select).display = show
        self.query_one("#label-mcp-scope", Label).display = show
        if show:
            self._show_mcp_transport_fields(self._input("mcp-transport"))
        else:
            for widget_id in (*MCP_STDIO_FIELDS, *MCP_REMOTE_FIELDS):
                self._show_input_field(widget_id, False)

    def _show_mcp_transport_fields(self, transport: str) -> None:
        is_stdio = transport == "stdio"
        for widget_id in MCP_STDIO_FIELDS:
            self._show_input_field(widget_id, is_stdio)
        for widget_id in MCP_REMOTE_FIELDS:
            self._show_input_field(widget_id, transport in {"http", "sse"})

    def _show_input_field(self, widget_id: str, show: bool) -> None:
        self.query_one(f"#{widget_id}", Input).display = show
        self.query_one(f"#label-{widget_id}", Label).display = show

    def _show_skill_fields(self, show: bool) -> None:
        for widget_id in (
            "skill-source", "skill-scope",
            "skillshub-url", "skillshub-query",
        ):
            self.query_one(f"#label-{widget_id}", Label).display = show
            if widget_id == "skill-scope":
                self.query_one(f"#{widget_id}", Select).display = show
            else:
                self.query_one(f"#{widget_id}", Input).display = show
        self.query_one("#label-skill-results", Label).display = show
        self.query_one("#skill-results", Vertical).display = show

    def _input(self, widget_id: str) -> str:
        if widget_id in {"mcp-transport", "mcp-enabled", "mcp-scope", "skill-scope"}:
            return str(self.query_one(f"#{widget_id}", Select).value).strip()
        return self.query_one(f"#{widget_id}", Input).value.strip()

    def _mcp_scope_for(self, name: str) -> str:
        if any(server.name == name for server in self.local_mcp_servers):
            return "workspace"
        if any(server.name == name for server in self.global_mcp_servers):
            return "global"
        return "workspace"

    def _mcp_enabled_for(self, name: str) -> str:
        for server in self.mcp_servers:
            if server.name == name:
                return "enabled" if server.enabled else "disabled"
        return "disabled"

    def _set_status(self, text: str) -> None:
        self.status = text
        self.query_one("#status", Static).update(text)

    def _refresh_buttons(self) -> None:
        is_mcp = self.section == SECTION_MCP
        self.query_one("#apply-mcp", Button).display = is_mcp
        self.query_one("#check-mcp", Button).display = is_mcp
        self.query_one("#install-skill", Button).display = not is_mcp
        self.query_one("#search-skillshub", Button).display = not is_mcp


def _valid_scope(value: str) -> str:
    scope = value.strip().lower() or "workspace"
    if scope not in {"workspace", "global"}:
        raise ValueError("Skill scope must be workspace or global.")
    return scope


def _merge_mcp_servers(
    global_servers: list[McpServerConfig],
    local_servers: list[McpServerConfig],
) -> list[McpServerConfig]:
    by_name: dict[str, McpServerConfig] = {}
    order: list[str] = []
    for server in [*global_servers, *local_servers]:
        if not server.name:
            continue
        if server.name not in by_name:
            order.append(server.name)
        by_name[server.name] = server
    return [deepcopy(by_name[name]) for name in order]


def _is_url(value: str) -> bool:
    return value.startswith("http://") or value.startswith("https://")


async def _check_mcp_server(server: McpServerConfig) -> list[object]:
    dto = McpServerDTO(
        id=None,
        name=server.name,
        transport=server.transport,
        enabled=server.enabled,
        command=server.command,
        args=server.args,
        env=server.env,
        cwd=server.cwd,
        encoding=server.encoding,
        url=server.url,
        headers=server.headers,
        timeout=server.timeout,
        sse_read_timeout=server.sse_read_timeout,
    )
    pool = McpClientPool()
    try:
        return await pool.connect({server.name: dto.to_langchain_config()})
    finally:
        await pool.disconnect()


class PluginScreen(PluginViewMixin, Screen[PluginEditResult | None]):
    """Embeddable plugin manager for the full-screen MainApp."""

    def _finish(self, result: PluginEditResult | None) -> None:
        self.dismiss(result)


class PluginApp(PluginViewMixin, App[PluginEditResult | None]):
    """Standalone plugin manager."""

    def _finish(self, result: PluginEditResult | None) -> None:
        self.exit(result)


async def manage_plugins_tui(config: CliConfig) -> PluginEditResult | None:
    """Run the Textual plugin manager."""
    return await PluginApp(config).run_async()
