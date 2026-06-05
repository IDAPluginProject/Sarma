"""Slash command handling for the main Textual app."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sarma_cli.commands import COMMANDS
from sarma_cli.workflows import get_registry

if TYPE_CHECKING:
    from sarma_cli.tui.main_app import MainApp


class MainCommandController:
    """Route slash commands away from the UI widget class."""

    def __init__(self, app: "MainApp") -> None:
        self._app = app

    async def handle(self, cmd: str) -> None:
        chat = self._app.query_one_chat()
        cmd_lower = cmd.strip().lower()

        if cmd_lower in ("/exit", "/quit", "/q"):
            self._app.exit()
            return

        if cmd_lower == "/clear":
            chat.clear_chat()
            if self._app.session:
                self._app.session.new_conversation()
            return

        if cmd_lower == "/help":
            help_text = "Commands:\n"
            for command, desc in COMMANDS.items():
                help_text += f"  {command:<12} {desc}\n"
            chat.add_system_message(help_text)
            return

        if cmd_lower.startswith("/workflow"):
            self._app.handle_workflow_command(cmd)
            return

        if cmd_lower == "/status":
            await self._app.handle_status_command()
            return

        if cmd_lower == "/graph":
            self._app.handle_graph_command()
            return

        if cmd_lower == "/models":
            self._app.handle_models_command()
            return

        if cmd_lower == "/history":
            self._app.handle_history_command()
            return

        if cmd_lower == "/config":
            await self._app.handle_config_command()
            return

        if cmd_lower == "/plugin":
            await self._app.handle_plugin_command()
            return

        if cmd_lower == "/rag":
            await self._app.handle_rag_command()
            return

        if cmd_lower == "/restart":
            if self._app.session:
                await self._app.session.restart_runtime()
                self._app.refresh_resolver()
            self._app.notify_status("Workflow runtime restarted.")
            return

        if cmd_lower == "/compact":
            if self._app.session:
                try:
                    compacted = await self._app.session.compact_context(
                        force=True,
                        workflow=get_registry().current_name() or "ruflo",
                    )
                except Exception as exc:
                    self._app.notify_status(
                        f"Context compaction failed: {exc}",
                        severity="error",
                    )
                else:
                    msg = (
                        "Context compacted."
                        if compacted
                        else "Context is already within model budget."
                    )
                    self._app.notify_status(msg)
            return

        if cmd_lower.startswith("/resume"):
            _, _, cid = cmd.partition(" ")
            cid = cid.strip()
            if self._app.session and cid and self._app.session.resume_conversation(cid):
                self._app.notify_status(f"Resumed conversation {cid}")
                self._app.query_one_sidebar().update_session(cid)
            else:
                self._app.notify_status(
                    f"Conversation {cid or '(missing)'} not found.",
                    severity="warning",
                )
            return

        chat.add_system_message(f"Unknown command: {cmd}")
