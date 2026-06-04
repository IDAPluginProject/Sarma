"""Textual configuration app for models and agents."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Input, Label, ListItem, ListView, Select, Static

from sarma_cli.config import (
    API_MODES,
    LEGACY_WORKFLOW_ALIASES,
    WORKFLOWS,
    AgentConfig,
    CliConfig,
    ProviderConfig,
    parse_context_window,
)
from sarma_cli.tui.theme import CONFIG_APP_CSS

SECTION_MODELS = "Models"
SECTION_WORKFLOW = "Workflow"


@dataclass(slots=True)
class ConfigEditResult:
    models: list[ProviderConfig]
    active_model: str
    agents: list[AgentConfig]


@dataclass(slots=True)
class _Field:
    label: str
    key: str
    secret: bool = False


class ConfigViewMixin:
    """Shared full-screen Sarma configuration view."""

    BINDINGS = [
        ("ctrl+s", "save", "Save"),
        ("escape", "cancel", "Close"),
    ]

    CSS = CONFIG_APP_CSS

    _MODEL_FIELDS = [
        _Field("Model name", "name"),
        _Field("Model ID", "model_name"),
        _Field("API mode", "api_mode"),
        _Field("Base URL", "base_url"),
        _Field("API key", "api_key", secret=True),
        _Field("Max context window", "max_context_tokens"),
        _Field("Enabled", "enabled"),
    ]

    def __init__(self, config: CliConfig) -> None:
        super().__init__()
        self.models = deepcopy(config.models) or [ProviderConfig()]
        self.active_model = config.active_model or self.models[0].name
        self.agents = _normalize_workflow_agents(config.agents, self.active_model)
        self.section = SECTION_MODELS
        self.selected = 0
        self.status = "Use the buttons to save, add, delete, or close."

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Horizontal(id="shell"):
            with Vertical(id="sections"):
                yield Static("Config", classes="hint")
                yield ListView(
                    *[ListItem(Label(label)) for label in self._section_labels()],
                    id="section-list",
                )
            with Vertical(id="items"):
                yield Static("Items", classes="hint")
                yield ListView(id="item-list")
            with Vertical(id="form"):
                yield Static("", id="form-title")
                yield VerticalScroll(id="form-fields")
                with Horizontal(id="buttons"):
                    yield Static("", id="button-spacer")
                    yield Button("Save", id="save", variant="success")
                    yield Button("New", id="new")
                    yield Button("Delete", id="delete", variant="error")
                    yield Button("Close", id="close")
        yield Static(self.status, id="status")
        yield Footer()

    async def on_mount(self) -> None:
        self.query_one("#section-list", ListView).index = 0
        await self._refresh_items()
        await self._refresh_form()

    async def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.list_view.id == "section-list":
            self._apply_form()
            self.section = self._section_labels()[event.list_view.index or 0]
            self.selected = 0
            await self._refresh_items()
            await self._refresh_form()
            self._refresh_buttons()
        elif event.list_view.id == "item-list":
            self._apply_form()
            self.selected = event.list_view.index or 0
            await self._refresh_form()

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save":
            self.action_save()
        elif event.button.id == "new":
            await self.action_new_item()
        elif event.button.id == "delete":
            await self.action_delete_item()
        elif event.button.id == "close":
            self.action_cancel()

    def action_save(self) -> None:
        if not self._apply_form():
            return
        self._finish(ConfigEditResult(
            models=deepcopy(self.models),
            active_model=self.active_model,
            agents=deepcopy(self.agents),
        ))

    def action_cancel(self) -> None:
        self._finish(None)

    def _finish(self, result: ConfigEditResult | None) -> None:
        raise NotImplementedError

    async def action_new_item(self) -> None:
        self._apply_form()
        if self.section == SECTION_MODELS:
            self.models.append(ProviderConfig(name=_unique_name([m.name for m in self.models], "new-model")))
            self.selected = len(self.models) - 1
        else:
            self._set_status("Workflow agents are fixed for each workflow.")
            return
        self._set_status("New item created. Fill the form and press Ctrl-S.")
        await self._refresh_items()
        await self._refresh_form()

    async def action_delete_item(self) -> None:
        if self.section == SECTION_MODELS:
            if len(self.models) <= 1:
                self._set_status("At least one model is required.")
                return
            removed = self.models.pop(self.selected)
            if self.active_model == removed.name:
                self.active_model = self.models[0].name
            self._replace_agent_model_refs(removed.name, self.models[0].name)
            self.selected = min(self.selected, len(self.models) - 1)
        else:
            self._set_status("Workflow agents are fixed for each workflow.")
            return
        self._set_status("Deleted. Press Ctrl-S to persist.")
        await self._refresh_items()
        await self._refresh_form()

    async def _refresh_items(self) -> None:
        items = self.query_one("#item-list", ListView)
        await items.clear()
        labels = self._item_labels()
        for label in labels:
            await items.append(ListItem(Label(label)))
        if labels:
            items.index = min(self.selected, len(labels) - 1)

    async def _refresh_form(self) -> None:
        form = self.query_one("#form-fields", VerticalScroll)
        await form.remove_children()
        form.scroll_home(animate=False)
        self.query_one("#form-title", Static).update(f"{self.section} / {self._current_label()}")
        if self.section == SECTION_WORKFLOW:
            await self._mount_workflow_form(form)
            form.focus()
            return
        for field_def in self._fields():
            await form.mount(Label(field_def.label, classes="field-label"))
            value = self._field_value(field_def.key)
            if field_def.key == "api_mode":
                await form.mount(Select(
                    [(mode, mode) for mode in API_MODES],
                    prompt=field_def.label,
                    allow_blank=False,
                    value=value,
                    id=f"field-{field_def.key}",
                ))
            else:
                await form.mount(Input(value=value, id=f"field-{field_def.key}", password=field_def.secret))
        form.focus()

    def _apply_form(self) -> bool:
        if self.section == SECTION_WORKFLOW:
            return self._apply_workflow_form()

        fields = {field_def.key: self._field_input(field_def.key) for field_def in self._fields()}
        try:
            if self.section == SECTION_MODELS:
                old_name = self.models[self.selected].name
                new_name = fields["name"].strip() or "default"
                if new_name != old_name and any(
                    model.name == new_name
                    for index, model in enumerate(self.models)
                    if index != self.selected
                ):
                    raise ValueError(f"Model name already exists: {new_name}")
                self.models[self.selected] = ProviderConfig(
                    name=new_name,
                    model_name=fields["model_name"].strip(),
                    api_key=fields["api_key"],
                    base_url=fields["base_url"].strip(),
                    api_mode=_valid_api_mode(fields["api_mode"]),
                    temperature=0.0,
                    top_p=1.0,
                    max_context_tokens=parse_context_window(fields["max_context_tokens"]),
                    enabled=_parse_bool(fields["enabled"]),
                )
                if new_name != old_name:
                    if self.active_model == old_name:
                        self.active_model = new_name
                    self._replace_agent_model_refs(old_name, new_name)
        except ValueError as exc:
            self._set_status(str(exc))
            return False
        return True

    def _item_labels(self) -> list[str]:
        if self.section == SECTION_MODELS:
            return [
                f"{'*' if model.name == self.active_model else ' '} {self._model_display(model)}"
                for model in self.models
            ]
        if self.section == SECTION_WORKFLOW:
            return list(WORKFLOWS)
        return []

    def _current_label(self) -> str:
        labels = self._item_labels()
        if not labels:
            return "(none)"
        return labels[min(self.selected, len(labels) - 1)].strip()

    def _fields(self) -> list[_Field]:
        if self.section == SECTION_MODELS:
            return self._MODEL_FIELDS
        return []

    def _field_value(self, key: str) -> str:
        if self.section == SECTION_MODELS:
            item = self.models[self.selected]
        else:
            return ""
        value = getattr(item, key)
        if isinstance(value, list):
            return ", ".join(value)
        if isinstance(value, bool):
            return "true" if value else "false"
        return str(value)

    def _field_input(self, key: str) -> str:
        if key == "api_mode":
            return str(self.query_one(f"#field-{key}", Select).value)
        return self.query_one(f"#field-{key}", Input).value

    def _set_status(self, text: str) -> None:
        self.status = text
        self.query_one("#status", Static).update(text)

    def _refresh_buttons(self) -> None:
        model_section = self.section == SECTION_MODELS
        self.query_one("#new", Button).display = model_section
        self.query_one("#delete", Button).display = model_section

    def _section_labels(self) -> list[str]:
        return [SECTION_MODELS, SECTION_WORKFLOW]

    def _agent_workflow(self) -> str | None:
        if self.section != SECTION_WORKFLOW:
            return None
        return WORKFLOWS[min(self.selected, len(WORKFLOWS) - 1)]

    def _agent_indices(self) -> list[int]:
        workflow = self._agent_workflow()
        if workflow is None:
            return []
        prefix = f"{workflow}."
        return [
            index
            for index, agent in enumerate(self.agents)
            if agent.name == workflow or agent.name.startswith(prefix)
        ]

    def _selected_agent_index(self) -> int | None:
        indices = self._agent_indices()
        if not indices:
            return None
        return indices[min(self.selected, len(indices) - 1)]

    def _agent_display_name(self, name: str) -> str:
        workflow = self._agent_workflow()
        if workflow and name == workflow:
            return workflow
        if workflow and name.startswith(f"{workflow}."):
            return name.removeprefix(f"{workflow}.")
        return name

    async def _mount_workflow_form(self, form: VerticalScroll) -> None:
        for agent_index in self._agent_indices():
            agent = self.agents[agent_index]
            await form.mount(Label(self._agent_display_name(agent.name), classes="field-label"))
            await form.mount(Label("Model", classes="field-label"))
            await form.mount(Select(
                self._model_options(agent.model),
                prompt="Model",
                allow_blank=False,
                value=agent.model,
                id=f"field-agent-{agent_index}-model",
            ))
            await form.mount(Label("MCP", classes="field-label"))
            await form.mount(Input(
                value=", ".join(agent.mcp or ["*"]),
                id=f"field-agent-{agent_index}-mcp",
                placeholder='Comma list, "*" for all',
            ))
            await form.mount(Label("Skills", classes="field-label"))
            await form.mount(Input(
                value=", ".join(agent.skills or ["*"]),
                id=f"field-agent-{agent_index}-skills",
                placeholder='Comma list, "*" for all',
            ))

    def _apply_workflow_form(self) -> bool:
        try:
            for agent_index in self._agent_indices():
                agent = self.agents[agent_index]
                model = str(self.query_one(f"#field-agent-{agent_index}-model", Select).value)
                mcp = self.query_one(f"#field-agent-{agent_index}-mcp", Input).value
                skills = self.query_one(f"#field-agent-{agent_index}-skills", Input).value
                self.agents[agent_index] = AgentConfig(
                    name=agent.name,
                    model=model,
                    mcp=_parse_list(mcp, default=["*"]),
                    skills=_parse_list(skills, default=["*"]),
                )
        except ValueError as exc:
            self._set_status(str(exc))
            return False
        return True

    def _model_options(self, current: str) -> list[tuple[str, str]]:
        options = [(self._model_display(model), model.name) for model in self.models]
        if current and current not in {model.name for model in self.models}:
            options.append((current, current))
        return options

    def _model_display(self, model: ProviderConfig) -> str:
        return model.model_name.strip() or model.name

    def _replace_agent_model_refs(self, old_name: str, new_name: str) -> None:
        self.agents = [
            AgentConfig(
                name=agent.name,
                model=new_name if agent.model == old_name else agent.model,
                mcp=list(agent.mcp) or ["*"],
                skills=list(agent.skills),
            )
            for agent in self.agents
        ]


def _unique_name(existing: list[str], base: str) -> str:
    if base not in existing:
        return base
    index = 2
    while f"{base}-{index}" in existing:
        index += 1
    return f"{base}-{index}"


def _normalize_workflow_agents(agents: list[AgentConfig], active_model: str) -> list[AgentConfig]:
    by_name: dict[str, AgentConfig] = {}
    valid_names = set(_workflow_agent_names())
    for agent in deepcopy(agents):
        name = _normalize_agent_name(agent.name)
        if name in valid_names and name not in by_name:
            by_name[name] = AgentConfig(
                name=name,
                model=agent.model or active_model,
                mcp=list(agent.mcp) or ["*"],
                skills=list(agent.skills),
            )
    for name in _workflow_agent_names():
        by_name.setdefault(name, AgentConfig(name=name, model=active_model))
    return [by_name[name] for name in _workflow_agent_names()]


def _normalize_agent_name(name: str) -> str:
    workflow, dot, subagent = name.partition(".")
    workflow = LEGACY_WORKFLOW_ALIASES.get(workflow, workflow)
    return f"{workflow}.{subagent}" if dot else workflow


def _workflow_agent_names() -> list[str]:
    from sarma_cli.engine.audit_subagents import AUDIT_SUBAGENT_ORDER
    from sarma_cli.engine.audit_slim_subagents import AUDIT_SLIM_SUBAGENT_ORDER

    return [
        "ruflo",
        "audit",
        *[f"audit.{name}" for name in AUDIT_SUBAGENT_ORDER],
        "audit-slim",
        *[f"audit-slim.{name}" for name in AUDIT_SLIM_SUBAGENT_ORDER],
    ]


def _valid_api_mode(value: str) -> str:
    mode = value.strip() or API_MODES[0]
    if mode not in API_MODES:
        raise ValueError(f"API mode must be one of: {', '.join(API_MODES)}")
    return mode


def _parse_bool(value: str) -> bool:
    return value.strip().lower() not in ("0", "false", "no", "off", "disabled")


def _parse_list(value: str, *, default: list[str]) -> list[str]:
    parts = [part.strip() for part in value.split(",") if part.strip()]
    return parts or list(default)


class ConfigScreen(ConfigViewMixin, Screen[ConfigEditResult | None]):
    """Embeddable configuration screen for the full-screen MainApp."""

    def _finish(self, result: ConfigEditResult | None) -> None:
        self.dismiss(result)


class ConfigApp(ConfigViewMixin, App[ConfigEditResult | None]):
    """Standalone configuration app."""

    def _finish(self, result: ConfigEditResult | None) -> None:
        self.exit(result)


async def configure_workspace_tui(config: CliConfig) -> ConfigEditResult | None:
    """Run the Textual config app."""
    return await ConfigApp(config).run_async()
