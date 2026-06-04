"""Main full-screen Textual application for Sarma."""

from __future__ import annotations

import asyncio
import io
import json
import time
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.worker import get_current_worker

from sarma_cli.config import CliConfig, save_agents, save_mcp, save_models
from sarma_cli.engine.enums import StreamEventType
from sarma_cli.engine.models import StreamEvent
from sarma_cli.runtime.resolver import RuntimePolicyResolver
from sarma_cli.session import Session
from sarma_cli.status import render_status_panel
from sarma_cli.store import Store
from sarma_cli.tui.chat_area import ChatArea
from sarma_cli.tui.config_app import ConfigScreen
from sarma_cli.tui.input_bar import InputBar, UserInputSubmitted
from sarma_cli.tui.main_commands import MainCommandController
from sarma_cli.tui.plugin_app import PluginScreen
from sarma_cli.tui.sidebar import Sidebar
from sarma_cli.workflows import get_registry, init_workflows


class StreamEventMessage(Message):
    """Internal message for routing engine events to UI."""

    def __init__(self, event: StreamEvent) -> None:
        super().__init__()
        self.event = event


class MainApp(App[None]):
    """Full-screen Sarma TUI with chat area, sidebar, and input bar."""

    CSS_PATH = Path(__file__).with_suffix(".css")
    BINDINGS = [
        ("ctrl+c", "interrupt", "Stop"),
        ("escape", "interrupt", "Stop"),
        ("ctrl+l", "clear", "Clear"),
    ]

    def __init__(self, config: CliConfig) -> None:
        super().__init__()
        self.config = config
        self.store: Store | None = None
        self.session: Session | None = None
        self.resolver: RuntimePolicyResolver | None = None
        self._running_turn = False
        self._turn_failed = False
        self._active_agents: list[str] = []
        self._seen_agents: list[str] = []
        self._completed_agents: set[str] = set()
        self._failed_agent = ""
        self._delegate_call_agents: dict[str, str] = {}
        self._last_parallel_status = ""
        self._turn_worker: Any | None = None
        self._turn_cancelled = False
        self._last_interrupt_at = 0.0
        self._commands = MainCommandController(self)

    def query_one_chat(self) -> ChatArea:
        return self.query_one(ChatArea)

    def query_one_sidebar(self) -> Sidebar:
        return self.query_one(Sidebar)

    def notify_status(
        self,
        message: str,
        *,
        severity: str = "information",
    ) -> None:
        """Show transient UI status without adding it to chat history."""
        try:
            self.notify(message, severity=severity, timeout=4)
        except Exception:
            self.query_one(ChatArea).add_system_message(message)

    def refresh_resolver(self) -> None:
        self.resolver = RuntimePolicyResolver(self.config)

    def compose(self) -> ComposeResult:
        with Horizontal(id="main-container"):
            with Vertical(id="main-content"):
                yield ChatArea()
                yield InputBar()
            yield Sidebar()

    async def on_mount(self) -> None:
        """Initialize session and display banner."""
        init_workflows()
        self.store = Store()
        self.session = Session(self.config, self.store)
        self.resolver = RuntimePolicyResolver(self.config)

        # Show welcome message in chat area. Avoid printing to stdout inside Textual.
        chat = self.query_one(ChatArea)
        chat.add_system_message(
            "Sarma ready. Type a message or use /help for commands."
        )

        sidebar = self.query_one(Sidebar)
        workflow = get_registry().current_name() or "ruflo"
        sidebar.update_workflow(workflow)
        self._sync_model_sidebar(sidebar, workflow)
        sidebar.update_mcp(connected=False, servers=self._configured_mcp_statuses(workflow))
        sidebar.update_session("")
        self.run_worker(self._check_mcp_on_startup(), thread=False)

        self.query_one(InputBar).focus_input()

    async def _check_mcp_on_startup(self) -> None:
        """Connect MCP once on startup and reflect only connectivity in the sidebar."""
        if self.session is None:
            return
        workflow = get_registry().current_name() or "ruflo"
        connected = False
        try:
            await self.session.ensure_mcp_connected(workflow)
            connected = self.session.pool.is_connected
        except Exception:
            connected = False
        self.query_one(Sidebar).update_mcp(
            connected,
            servers=self._mcp_statuses(workflow),
        )

    async def on_user_input_submitted(self, event: UserInputSubmitted) -> None:
        """Handle user message submission."""
        content = event.content
        if not content:
            return

        chat = self.query_one(ChatArea)

        # Display user message
        chat.add_user_message(content)

        # Handle slash commands
        if content.startswith("/"):
            await self._handle_slash_command(content)
            return

        # Check model config
        registry = get_registry()
        workflow = registry.current_name() or "ruflo"
        if not self.resolver or not self.resolver.provider_for(workflow).model_name:
            self.notify_status(
                "No model configured. Run /config to set one up.",
                severity="warning",
            )
            return

        if self._running_turn:
            self.notify_status("A turn is already in progress.", severity="warning")
            return

        self._running_turn = True
        self._turn_failed = False
        self._reset_runtime_graph()

        self._turn_worker = self.run_worker(
            self._run_turn_worker(content),
            thread=False,
        )

    async def _run_turn_worker(self, message: str) -> None:
        """Background worker that runs the agent turn and posts events."""
        if self.session is None:
            return

        cancelled = False
        try:
            async for event in self.session.run_turn(message):
                if get_current_worker().is_cancelled:
                    cancelled = True
                    break
                self.post_message(StreamEventMessage(event))
        except asyncio.CancelledError:
            cancelled = True
        except Exception as exc:
            self.post_message(
                StreamEventMessage(
                    StreamEvent(
                        type=StreamEventType.RUN_FAILED,
                        payload={"error": str(exc)},
                    )
                )
            )
        finally:
            if cancelled or get_current_worker().is_cancelled:
                self.post_message(
                    StreamEventMessage(
                        StreamEvent(
                            type=StreamEventType.RUN_FAILED,
                            payload={"error": "Run cancelled."},
                        )
                    )
                )
            else:
                self.post_message(StreamEventMessage(
                    StreamEvent(type=StreamEventType.RUN_COMPLETED)
                ))
            self._running_turn = False
            self._turn_worker = None

    async def on_stream_event_message(self, event_msg: StreamEventMessage) -> None:
        """Handle stream events from the background worker."""
        event = event_msg.event
        etype = event.type
        payload = event.payload
        chat = self.query_one(ChatArea)
        sidebar = self.query_one(Sidebar)

        if etype == StreamEventType.TOKEN:
            token = payload.get("content", "")
            reasoning = payload.get("reasoning_content", "")
            if self._suppress_subagent_detail(payload):
                return
            speaker = self._speaker_from_payload(payload)
            follow = chat.should_follow()
            token_text = self._stream_text(token)
            if not token_text.strip() and not reasoning:
                assistant = chat.get_current_assistant(speaker)
                if assistant is not None and assistant.has_visible_content():
                    assistant.feed_token(token_text)
                    chat.follow_if(follow)
                return
            assistant = chat.ensure_assistant_message(speaker)
            if reasoning:
                assistant.feed_reasoning(reasoning)
            if token_text:
                assistant.feed_token(token_text)
            chat.follow_if(follow)

        elif etype == StreamEventType.TOOL_START:
            if self._suppress_subagent_detail(payload):
                return
            name = payload.get("tool_name", "?")
            args = self._tool_args_summary(payload)
            speaker = self._speaker_from_payload(payload)
            self._maybe_start_delegate_agent(str(name), payload, chat, sidebar)
            chat.add_tool_call(
                call_id=str(payload.get("tool_call_id") or ""),
                name=str(name),
                speaker=speaker,
                args=payload.get("args"),
                summary=args,
            )

        elif etype == StreamEventType.TOOL_RESULT:
            if self._suppress_subagent_detail(payload):
                return
            name = payload.get("tool_name", "?")
            result = self._truncate(str(payload.get("result_summary") or payload.get("result") or ""), 240)
            speaker = self._speaker_from_payload(payload)
            chat.update_tool_call(
                str(payload.get("tool_call_id") or ""),
                name=str(name),
                speaker=speaker,
                result=result,
            )
            self._maybe_complete_delegate_agent(str(name), payload, chat, sidebar)

        elif etype == StreamEventType.TOOL_ERROR:
            if self._suppress_subagent_detail(payload):
                return
            name = payload.get("tool_name", "?")
            error = self._truncate(str(payload.get("error_text") or payload.get("error") or payload.get("result") or ""), 240)
            speaker = self._speaker_from_payload(payload)
            chat.update_tool_call(
                str(payload.get("tool_call_id") or ""),
                name=str(name),
                speaker=speaker,
                error=error,
            )
            self._maybe_complete_delegate_agent(str(name), payload, chat, sidebar, failed=True)

        elif etype == StreamEventType.SKILL_TRIGGERED:
            if self._suppress_subagent_detail(payload):
                return
            skill_name = str(payload.get("skill_name") or payload.get("name") or "skill")
            speaker = self._speaker_from_payload(payload)
            chat.add_skill_trigger(skill_name, speaker=speaker)

        elif etype == StreamEventType.SUBAGENT_START:
            name = payload.get("subagent", "")
            if name:
                chat.end_assistant_message()
                self._add_active_agent(name)
                self._sync_active_agents(chat, sidebar)

        elif etype == StreamEventType.SUBAGENT_COMPLETE:
            name = payload.get("subagent", "")
            if name:
                chat.end_assistant_message()
                self._remove_active_agent(name)
                self._sync_active_agents(chat, sidebar)

        elif etype == StreamEventType.SUBAGENT_ERROR:
            name = payload.get("subagent", "")
            chat.end_assistant_message()
            self._remove_active_agent(name)
            self._sync_active_agents(chat, sidebar)
            error = payload.get("error") or payload.get("result") or "Subagent failed."
            chat.add_system_message(f"{name or 'Subagent'} failed: {error}")

        elif etype == StreamEventType.CUSTOM_PROGRESS:
            self._sync_runtime_graph(sidebar)

        elif etype == StreamEventType.RUN_COMPLETED:
            chat.end_assistant_message()
            self._active_agents.clear()
            self._last_parallel_status = ""
            sidebar.update_workflow(sidebar._workflow_name, "")
            self._sync_runtime_graph(sidebar)
            if not self._turn_failed:
                workflow_name = get_registry().current_name() or "ruflo"
                chat.add_system_message(f"{workflow_name} workflow finished.")

        elif etype == StreamEventType.RUN_FAILED:
            chat.end_assistant_message()
            self._turn_failed = True
            self._active_agents.clear()
            self._last_parallel_status = ""
            sidebar.update_workflow(sidebar._workflow_name, "")
            self._sync_runtime_graph(sidebar)
            error = payload.get("error", "Unknown error")
            chat.add_system_message(f"Error: {error}")

    async def _handle_slash_command(self, cmd: str) -> None:
        """Handle slash commands in the TUI."""
        await self._commands.handle(cmd)

    def handle_workflow_command(self, cmd: str) -> None:
        self._handle_workflow_command(cmd)

    async def handle_status_command(self) -> None:
        await self._handle_status_command()

    def handle_graph_command(self) -> None:
        self._handle_graph_command()

    def handle_models_command(self) -> None:
        self._handle_models_command()

    def handle_history_command(self) -> None:
        self._handle_history_command()

    async def handle_config_command(self) -> None:
        await self._handle_config_command()

    async def handle_plugin_command(self) -> None:
        await self._handle_plugin_command()

    def _handle_workflow_command(self, cmd: str) -> None:
        chat = self.query_one(ChatArea)
        sidebar = self.query_one(Sidebar)
        _, _, arg = cmd.partition(" ")
        registry = get_registry()
        workflow_name = arg.strip()
        if not workflow_name:
            lines = ["Available workflows:"]
            for workflow in registry.list_workflows():
                marker = "*" if workflow.name == registry.current_name() else " "
                lines.append(f"  {marker} {workflow.name:<10} {workflow.description}")
            chat.add_system_message("\n".join(lines))
            return
        if registry.switch(workflow_name):
            sidebar.update_workflow(workflow_name)
            self._reset_runtime_graph()
            if self.resolver:
                self._sync_model_sidebar(sidebar, workflow_name)
            chat.add_system_message(f"Switched to {workflow_name} workflow.")
            return
        chat.add_system_message(f"Unknown workflow: {workflow_name}")

    async def _handle_status_command(self) -> None:
        chat = self.query_one(ChatArea)
        sidebar = self.query_one(Sidebar)
        workflow = get_registry().current_name() or "ruflo"
        if self.session:
            sidebar.update_mcp(
                self.session.pool.is_connected,
                servers=self._mcp_statuses(workflow),
            )

        chat.add_system_message(render_status_panel(
            self.config,
            pool=self.session.pool if self.session else None,
            mcp_error="",
        ))
        if (
            self.session
            and not self.session.pool.is_connected
            and self._configured_mcp_statuses(workflow)
        ):
            self.notify_status("Checking MCP status in background...")
            self.run_worker(
                self._refresh_status_worker(workflow),
                thread=False,
                exclusive=True,
                group="mcp-status",
            )

    async def _refresh_status_worker(self, workflow: str) -> None:
        chat = self.query_one(ChatArea)
        sidebar = self.query_one(Sidebar)
        mcp_error = ""
        if self.session is None:
            return
        try:
            await self.session.ensure_mcp_connected(workflow)
        except Exception as exc:
            mcp_error = str(exc)
        sidebar.update_mcp(
            self.session.pool.is_connected,
            servers=self._mcp_statuses(workflow),
        )
        chat.add_system_message(render_status_panel(
            self.config,
            pool=self.session.pool,
            mcp_error=mcp_error,
        ))

    def _handle_graph_command(self) -> None:
        chat = self.query_one(ChatArea)
        registry = get_registry()
        current = registry.current()
        if current is None:
            chat.add_system_message("No workflow active.")
            return
        buffer = io.StringIO()
        console = Console(
            file=buffer,
            force_terminal=False,
            width=110,
            color_system=None,
        )
        graph_state = self.session.graph_state if self.session else {}
        console.print(current.render_graph(**graph_state))
        chat.add_system_message(buffer.getvalue().rstrip())

    def _handle_models_command(self) -> None:
        chat = self.query_one(ChatArea)
        if not self.config.models:
            chat.add_system_message("No models configured. Run /config to add one.")
            return
        lines = ["Configured models:"]
        for model in self.config.models:
            marker = "*" if model.name == self.config.active_model else " "
            model_id = model.model_name or "(not set)"
            base_url = model.base_url or "(provider default)"
            enabled = "enabled" if model.enabled else "disabled"
            lines.append(
                f"  {marker} {model.name} -> {model_id} "
                f"[{model.api_mode}, {enabled}, {base_url}]"
            )
        chat.add_system_message("\n".join(lines))

    def _handle_history_command(self) -> None:
        chat = self.query_one(ChatArea)
        if self.store is None:
            chat.add_system_message("History store is not available.")
            return
        conversations = self.store.list_conversations()
        if not conversations:
            chat.add_system_message("No conversations yet.")
            return
        lines = ["Conversation history:"]
        for conversation in conversations:
            conv_id = str(conversation.get("id", "unknown"))
            title = str(conversation.get("title") or "Untitled")[:50]
            model = str(conversation.get("model_name") or "unknown")
            updated = str(conversation.get("updated_at") or "unknown")[:16]
            lines.append(f"  {conv_id:<14} {updated:<16} {model:<20} {title}")
        chat.add_system_message("\n".join(lines))

    async def _handle_config_command(self) -> None:
        self.push_screen(ConfigScreen(self.config), self._on_config_result)

    def _on_config_result(self, result: Any) -> None:
        self.run_worker(self._apply_config_result(result), thread=False)

    async def _apply_config_result(self, result: Any) -> None:
        chat = self.query_one(ChatArea)
        if result is None:
            self.notify_status("Config closed without saving.")
            self.query_one(InputBar).focus_input()
            return
        self.config.models = result.models
        self.config.active_model = result.active_model
        self.config.agents = result.agents
        try:
            models_path = save_models(self.config)
            agents_path = save_agents(self.config)
        except Exception as exc:
            chat.add_system_message(f"Could not save config: {exc}")
            self.query_one(InputBar).focus_input()
            return
        if self.session:
            await self.session.restart_runtime()
        self.resolver = RuntimePolicyResolver(self.config)
        workflow = get_registry().current_name() or "ruflo"
        sidebar = self.query_one(Sidebar)
        self._sync_model_sidebar(sidebar, workflow)
        self.notify_status(f"Config saved to {models_path} and {agents_path}.")
        self.query_one(InputBar).focus_input()

    async def _handle_plugin_command(self) -> None:
        self.push_screen(PluginScreen(self.config), self._on_plugin_result)

    def _on_plugin_result(self, result: Any) -> None:
        self.run_worker(self._apply_plugin_result(result), thread=False)

    async def _apply_plugin_result(self, result: Any) -> None:
        chat = self.query_one(ChatArea)
        if result is None:
            self.notify_status("Plugin manager closed without saving.")
            self.query_one(InputBar).focus_input()
            return
        self.config.mcp_servers = result.mcp_servers
        try:
            mcp_path = save_mcp(self.config)
        except Exception as exc:
            chat.add_system_message(f"Could not save plugin config: {exc}")
            self.query_one(InputBar).focus_input()
            return
        if result.restart_requested and self.session:
            await self.session.restart_runtime()
            self.resolver = RuntimePolicyResolver(self.config)
        if self.session:
            workflow = get_registry().current_name() or "ruflo"
            self.query_one(Sidebar).update_mcp(
                self.session.pool.is_connected,
                servers=self._mcp_statuses(workflow),
            )
        self.notify_status(f"Plugin config saved to {mcp_path}.")
        self.query_one(InputBar).focus_input()

    def action_clear(self) -> None:
        """Ctrl+L handler."""
        chat = self.query_one(ChatArea)
        chat.clear_chat()
        if self.session:
            self.session.new_conversation()

    def action_interrupt(self) -> None:
        """Stop the current turn, or double-press to quit when idle."""
        now = time.monotonic()
        if self._running_turn and self._turn_worker is not None:
            self._turn_cancelled = True
            self._turn_worker.cancel()
            self.notify_status("Stopping current workflow...")
            self._last_interrupt_at = now
            return
        if now - self._last_interrupt_at <= 1.2:
            self.exit()
            return
        self._last_interrupt_at = now
        self.notify_status("Press Ctrl+C again quickly to exit.")

    async def on_unmount(self) -> None:
        """Cleanup session on exit."""
        if self.session:
            await self.session.close()
        if self.store:
            self.store.close()

    @staticmethod
    def _truncate(text: str, max_len: int) -> str:
        text = text.replace("\n", " ").strip()
        if len(text) > max_len:
            return text[: max_len - 3] + "..."
        return text

    @staticmethod
    def _stream_text(content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for block in content:
                if isinstance(block, str):
                    parts.append(block)
                elif isinstance(block, dict) and block.get("type") == "text":
                    parts.append(str(block.get("text", "")))
            return "".join(parts)
        return str(content) if content is not None else ""

    def _add_active_agent(self, name: str) -> None:
        agent = name.strip()
        if agent and agent not in self._active_agents:
            self._active_agents.append(agent)
        if agent and agent not in self._seen_agents:
            self._seen_agents.append(agent)

    def _remove_active_agent(self, name: str) -> None:
        agent = name.strip()
        if agent in self._active_agents:
            self._active_agents.remove(agent)
        if agent:
            self._completed_agents.add(agent)

    def _sync_active_agents(self, chat: ChatArea, sidebar: Sidebar) -> None:
        sidebar.update_workflow(sidebar._workflow_name, self._active_agents)
        self._sync_runtime_graph(sidebar)
        if len(self._active_agents) <= 1:
            self._last_parallel_status = ""
            return
        status = f"Agents running: {', '.join(self._active_agents)}"
        if status != self._last_parallel_status:
            chat.add_system_message(status)
            self._last_parallel_status = status

    def _reset_runtime_graph(self) -> None:
        self._active_agents.clear()
        self._seen_agents.clear()
        self._completed_agents.clear()
        self._failed_agent = ""
        self._delegate_call_agents.clear()
        self._last_parallel_status = ""
        try:
            self.query_one(Sidebar).reset_run_state()
        except Exception:
            return

    def _sync_runtime_graph(self, sidebar: Sidebar) -> None:
        graph_state = self.session.graph_state if self.session else {}
        sidebar.update_run_state(
            active=self._active_agents,
            seen=self._seen_agents,
            completed=self._completed_agents,
            failed=self._failed_agent,
            gapfill_loops=int(graph_state.get("gapfill_loops") or 0),
            feedback_loops=int(graph_state.get("feedback_loops") or 0),
        )

    def _sync_model_sidebar(self, sidebar: Sidebar, workflow: str) -> None:
        if self.resolver is None:
            sidebar.update_model("")
            return
        sidebar.update_models(self.resolver.model_assignments_for(workflow))

    def _maybe_start_delegate_agent(
        self,
        tool_name: str,
        payload: dict[str, Any],
        chat: ChatArea,
        sidebar: Sidebar,
    ) -> None:
        if tool_name != "delegate_task":
            return
        args = payload.get("args")
        if not isinstance(args, dict):
            return
        agent = str(args.get("subagent_name") or args.get("subagent_type") or "subagent").strip()
        if not agent:
            return
        call_id = str(payload.get("tool_call_id") or "")
        if call_id:
            self._delegate_call_agents[call_id] = agent
        self._add_active_agent(agent)
        self._sync_active_agents(chat, sidebar)

    def _maybe_complete_delegate_agent(
        self,
        tool_name: str,
        payload: dict[str, Any],
        chat: ChatArea,
        sidebar: Sidebar,
        *,
        failed: bool = False,
    ) -> None:
        if tool_name != "delegate_task":
            return
        call_id = str(payload.get("tool_call_id") or "")
        agent = self._delegate_call_agents.pop(call_id, "") if call_id else ""
        if not agent:
            args = payload.get("args")
            if isinstance(args, dict):
                agent = str(args.get("subagent_name") or args.get("subagent_type") or "").strip()
        if not agent:
            return
        if failed:
            self._failed_agent = agent
        self._remove_active_agent(agent)
        self._sync_active_agents(chat, sidebar)

    def _speaker_from_payload(self, payload: dict[str, Any]) -> str:
        subagent = str(payload.get("subagent") or "").strip()
        if subagent == "orchestrator":
            return "Sarma"
        if subagent:
            return subagent
        if len(self._active_agents) == 1:
            return self._active_agents[0]
        return "Sarma"

    def _suppress_subagent_detail(self, payload: dict[str, Any]) -> bool:
        if len(self._active_agents) <= 1:
            return False
        subagent = str(payload.get("subagent") or "").strip()
        return bool(subagent and subagent in self._active_agents)

    def _tool_args_summary(self, payload: dict[str, Any]) -> str:
        args = payload.get("args")
        if args is None:
            args = payload.get("args_json", "")
        tool_name = str(payload.get("tool_name") or "")
        if tool_name == "delegate_task" and isinstance(args, dict):
            subagent = str(args.get("subagent_name") or args.get("subagent_type") or "subagent")
            task = self._truncate(str(args.get("task") or ""), 180)
            expected = self._truncate(str(args.get("expected_output") or ""), 120)
            parts = [f"to {subagent}"]
            if task:
                parts.append(f"task: {task}")
            if expected:
                parts.append(f"expected: {expected}")
            return " | ".join(parts)
        if isinstance(args, str):
            return self._truncate(args, 220)
        try:
            text = json.dumps(args, ensure_ascii=False, separators=(",", ":"))
        except TypeError:
            text = str(args)
        return self._truncate(text, 220)

    def _mcp_statuses(self, workflow: str) -> list[Any]:
        if self.session and self.session.pool.server_statuses:
            return self.session.pool.server_statuses
        return self._configured_mcp_statuses(workflow)

    def _configured_mcp_statuses(self, workflow: str) -> list[dict[str, Any]]:
        if self.resolver is None:
            return []
        try:
            run_plan = self.resolver.resolve(workflow)
        except Exception:
            return []
        return [
            {
                "name": server.name,
                "connected": False,
                "tool_count": 0,
            }
            for server in run_plan.enabled_servers
        ]
