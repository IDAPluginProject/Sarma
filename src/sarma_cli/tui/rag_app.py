"""Textual RAG knowledge base panel."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import dataclass

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Header, Input, Label, ListItem, ListView, Select, Static

from sarma_cli.config import CliConfig, RagConfig
from sarma_cli.resources.rag import (
    embedding_model_local_path,
    knowledge_base_chroma_path,
    pull_embedding_model,
)
from sarma_cli.tui.theme import RAG_APP_CSS


SECTION_MODEL = "Model"
SECTION_KNOWLEDGE = "Knowledge Bases"


@dataclass(slots=True)
class RagEditResult:
    rag: RagConfig
    changed: bool = False


class RagViewMixin:
    """Shared RAG panel view for standalone and embedded usage."""

    BINDINGS = [
        ("ctrl+s", "save", "Save"),
        ("escape", "cancel", "Close"),
    ]

    CSS = RAG_APP_CSS

    def __init__(self, config: CliConfig) -> None:
        super().__init__()
        self.rag = deepcopy(config.rag)
        self.section = SECTION_MODEL
        self.selected = 0
        self.changed = False
        self.status = "Configure the global RAG embedding model. Manage KBs with `sarma rag`."

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Horizontal(id="shell"):
            with Vertical(id="sections"):
                yield Static("RAG", classes="hint")
                yield ListView(
                    ListItem(Label(SECTION_MODEL)),
                    ListItem(Label(SECTION_KNOWLEDGE)),
                    id="section-list",
                )
            with Vertical(id="items"):
                yield Static("Knowledge bases", classes="hint")
                yield ListView(id="item-list")
            with Vertical(id="detail"):
                yield Static("", id="title")
                yield Static("", id="description")
                yield VerticalScroll(id="fields")
                with Horizontal(id="buttons"):
                    yield Static("", id="button-spacer")
                    yield Button("Apply", id="apply", variant="success")
                    yield Button("Pull Model", id="pull-model", variant="primary")
                    yield Button("Save", id="save")
                    yield Button("Close", id="close")
        yield Static(self.status, id="status")

    async def on_mount(self) -> None:
        self.query_one("#section-list", ListView).index = 0
        await self._refresh_items()
        await self._refresh_fields()
        self._refresh_buttons()

    async def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.list_view.id == "section-list":
            self._apply_fields()
            self.section = [SECTION_MODEL, SECTION_KNOWLEDGE][event.list_view.index or 0]
            self.selected = 0
            await self._refresh_items()
            await self._refresh_fields()
            self._refresh_buttons()
        elif event.list_view.id == "item-list":
            self._apply_fields()
            self.selected = event.list_view.index or 0
            await self._refresh_fields()
            self._refresh_buttons()

    async def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "rag-embedding-backend":
            self.rag.embedding_backend = str(event.value)
            self._refresh_model_field_visibility()
            self._refresh_buttons()

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "apply":
            if self._apply_fields():
                self.changed = True
                self._set_status("RAG model settings applied. Press Save to write global config.")
                await self._refresh_items()
                await self._refresh_fields()
        elif event.button.id == "pull-model":
            await self._pull_model()
        elif event.button.id == "save":
            self.action_save()
        elif event.button.id == "close":
            self.action_cancel()

    def action_save(self) -> None:
        if not self._apply_fields():
            return
        self._finish(RagEditResult(rag=deepcopy(self.rag), changed=self.changed))

    def action_cancel(self) -> None:
        self._finish(None)

    def _finish(self, result: RagEditResult | None) -> None:
        raise NotImplementedError

    async def _pull_model(self) -> None:
        if not self._apply_fields():
            return
        self._set_status("Pulling embedding model...")
        try:
            result = await asyncio.to_thread(pull_embedding_model, self.rag)
        except Exception as exc:
            self._set_status(f"Pull failed: {exc}")
            return
        self.rag.embedding_local_path = str(result.path)
        self.changed = True
        self._set_status(f"Pulled embedding model {result.model}: {result.path}")
        await self._refresh_fields()

    async def _refresh_items(self) -> None:
        items = self.query_one("#item-list", ListView)
        await items.clear()
        labels = self._item_labels()
        for label in labels:
            await items.append(ListItem(Label(label)))
        if labels:
            items.index = min(self.selected, len(labels) - 1)

    async def _refresh_fields(self) -> None:
        fields = self.query_one("#fields", VerticalScroll)
        await fields.remove_children()
        fields.scroll_home(animate=False)
        self.query_one("#title", Static).update(self.section)
        self.query_one("#description", Static).update(self._description())
        if self.section == SECTION_MODEL:
            await self._mount_model_fields(fields)
        else:
            await self._mount_knowledge_base_view(fields)

    async def _mount_model_fields(self, fields: VerticalScroll) -> None:
        backend = self.rag.embedding_backend or "huggingface"
        await fields.mount(Label("Embedding backend", classes="field-label"))
        await fields.mount(Select(
            [("HuggingFace local", "huggingface"), ("API", "api")],
            value=backend,
            allow_blank=False,
            id="rag-embedding-backend",
        ))
        await fields.mount(Label("Embedding model", classes="field-label"))
        await fields.mount(Input(value=self.rag.embedding_model, id="rag-embedding-model"))
        await fields.mount(Label("API base URL", classes="field-label api-field"))
        await fields.mount(
            Input(
                value=self.rag.embedding_api_base,
                id="rag-embedding-api-base",
                classes="api-field",
            )
        )
        await fields.mount(Label("API key", classes="field-label api-field"))
        await fields.mount(
            Input(
                value=self.rag.embedding_api_key,
                id="rag-embedding-api-key",
                classes="api-field",
            )
        )
        await fields.mount(Label("Local model path", classes="field-label hf-field"))
        local_path = self.rag.embedding_local_path
        if not local_path and self.rag.embedding_model.strip():
            local_path = str(embedding_model_local_path(self.rag))
        await fields.mount(
            Input(value=local_path, id="rag-embedding-local-path", classes="hf-field")
        )
        await fields.mount(Label("Chunk size", classes="field-label"))
        await fields.mount(Input(value=str(self.rag.chunk_size), id="rag-chunk-size"))
        await fields.mount(Label("Chunk overlap", classes="field-label"))
        await fields.mount(Input(value=str(self.rag.chunk_overlap), id="rag-chunk-overlap"))
        self._refresh_model_field_visibility()

    async def _mount_knowledge_base_view(self, fields: VerticalScroll) -> None:
        if not self.rag.knowledge_bases:
            await fields.mount(Static("No knowledge base configured. Use `sarma rag --split` or `sarma rag --add`."))
            return
        for kb in self.rag.knowledge_bases:
            state = "enabled" if kb.enabled else "disabled"
            await fields.mount(Label(kb.name or "(unnamed)", classes="field-label"))
            await fields.mount(Static(
                f"{state}\nChroma: {knowledge_base_chroma_path(kb)}"
            ))

    def _apply_fields(self) -> bool:
        try:
            if self.section == SECTION_MODEL:
                self._apply_model_fields()
                return True
            return True
        except Exception as exc:
            self._set_status(str(exc))
            return False

    def _apply_model_fields(self) -> None:
        backend = self._select_value("#rag-embedding-backend", self.rag.embedding_backend)
        self.rag.embedding_backend = backend or "huggingface"
        self.rag.embedding_model = self._input_value(
            "#rag-embedding-model",
            self.rag.embedding_model,
        )
        if self.rag.embedding_backend == "api":
            self.rag.embedding_api_base = self._input_value(
                "#rag-embedding-api-base",
                self.rag.embedding_api_base,
            )
            self.rag.embedding_api_key = self._input_value(
                "#rag-embedding-api-key",
                self.rag.embedding_api_key,
            )
        else:
            self.rag.embedding_local_path = self._input_value(
                "#rag-embedding-local-path",
                self.rag.embedding_local_path,
            )

        chunk_size = int(self._input_value("#rag-chunk-size", str(self.rag.chunk_size)))
        chunk_overlap = int(
            self._input_value("#rag-chunk-overlap", str(self.rag.chunk_overlap))
        )
        if chunk_size <= 0:
            raise ValueError("Chunk size must be greater than 0.")
        if chunk_overlap < 0:
            raise ValueError("Chunk overlap must be 0 or greater.")
        if chunk_overlap >= chunk_size:
            raise ValueError("Chunk overlap must be smaller than chunk size.")
        self.rag.chunk_size = chunk_size
        self.rag.chunk_overlap = chunk_overlap

    def _input_value(self, selector: str, default: str = "") -> str:
        widgets = list(self.query(selector))
        if not widgets or not isinstance(widgets[0], Input):
            return default
        return widgets[0].value.strip()

    def _select_value(self, selector: str, default: str = "") -> str:
        widgets = list(self.query(selector))
        if not widgets or not isinstance(widgets[0], Select):
            return default
        return str(widgets[0].value)

    def _refresh_model_field_visibility(self) -> None:
        is_api = self.rag.embedding_backend == "api"
        for widget in self.query(".api-field"):
            widget.display = is_api
        for widget in self.query(".hf-field"):
            widget.display = not is_api

    def _item_labels(self) -> list[str]:
        if not self.rag.knowledge_bases:
            return ["(none)"]
        return [
            f"{kb.name or '(unnamed)'} [{('enabled' if kb.enabled else 'disabled')}]"
            for kb in self.rag.knowledge_bases
        ]

    def _description(self) -> str:
        if self.section == SECTION_MODEL:
            return "Set the global embedding model and chunking parameters used by RAG indexing."
        return "Knowledge bases are registered by the `sarma rag` CLI. This view is read-only."

    def _refresh_buttons(self) -> None:
        try:
            self.query_one("#apply", Button).display = self.section == SECTION_MODEL
            self.query_one("#pull-model", Button).display = (
                self.section == SECTION_MODEL
                and self.rag.embedding_backend != "api"
            )
        except Exception:
            pass

    def _set_status(self, message: str) -> None:
        self.status = message
        try:
            self.query_one("#status", Static).update(message)
        except Exception:
            pass


class RagScreen(RagViewMixin, Screen[RagEditResult | None]):
    """Embedded RAG panel screen."""

    def _finish(self, result: RagEditResult | None) -> None:
        self.dismiss(result)


class RagApp(RagViewMixin, App[RagEditResult | None]):
    """Standalone RAG panel app for tests and future CLI entrypoints."""

    def _finish(self, result: RagEditResult | None) -> None:
        self.exit(result)
