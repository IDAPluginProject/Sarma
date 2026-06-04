"""Main application loop for Sarma CLI.

Ties together the workflow registry, session, and REPL loop.
"""

from __future__ import annotations

from typing import Any

from sarma_cli.engine.enums import StreamEventType

from sarma_cli.config import CliConfig
from sarma_cli.renderer import (
    StreamPrinter,
    console,
    print_error,
)
from sarma_cli.tui.main_app import MainApp
from sarma_cli.runtime.resolver import RuntimePolicyResolver
from sarma_cli.session import Session
from sarma_cli.store import Store
from sarma_cli.workflows import get_registry


def _truncate(text: str, max_len: int) -> str:
    """Truncate text to max_len, replacing newlines with spaces."""
    text = text.replace("\n", " ").strip()
    if len(text) > max_len:
        return text[: max_len - 3] + "..."
    return text


async def run_interactive(config: CliConfig) -> None:
    """Launch the full-screen Textual TUI."""
    app = MainApp(config)
    await app.run_async()


async def run_oneshot(config: CliConfig, message: str) -> None:
    """Run a single audit message and exit.

    Used for non-interactive mode (e.g., piped input).
    """
    resolver = RuntimePolicyResolver(config)
    if not resolver.provider_for("ruflo").model_name:
        print_error("No model configured. Start [bold]sarma[/] and run /config.")
        return

    store = Store()
    session = Session(config, store)

    try:
        await _run_turn_interactive(session, message)
    except Exception as exc:
        print_error(str(exc))
    finally:
        await session.close()
        store.close()


async def _run_turn_interactive(session: Session, message: str) -> None:
    """Execute one turn with streaming output to terminal.

    Orchestrates:
      1. Stream events via session.run_turn
      2. Render final graph after turn (audit mode)
    """
    printer = StreamPrinter()
    async for event in session.run_turn(message):
        _handle_event(event, printer)

    printer.flush()

    # Show graph after turn if in audit mode
    current_wf = get_registry().current()
    if current_wf and current_wf.name == "audit":
        gs = session.graph_state
        if gs.get("current_stage") or gs.get("completed"):
            console.print(current_wf.render_graph(**gs))

def _handle_event(event: Any, printer: StreamPrinter) -> None:
    """Route a StreamEvent to the appropriate renderer.

    Handles:
      - TOKEN: live markdown rendering
      - TOOL_START/RESULT/ERROR: tool execution feedback
      - SUBAGENT_START/COMPLETE: workflow stage transitions
      - RUN_FAILED: error reporting
    """
    from sarma_cli.engine.models import StreamEvent

    etype = event.type
    payload = event.payload



    if etype == StreamEventType.TOKEN:
        reasoning = payload.get("reasoning_content", "")
        if reasoning:
            printer.feed_reasoning(reasoning)
        token = payload.get("content", "")
        if token:
            printer.feed_token(token)

    elif etype == StreamEventType.RUN_STARTED:
        console.print(f"[dim]─" * 40 + "[/]")

    elif etype == StreamEventType.TOOL_START:
        # Pause live markdown, print tool line, resume on next token
        name = payload.get("tool_name", "?")
        args = _truncate(payload.get("args_json", ""), 100)
        printer.start_tool(name)
        printer.interrupt_for_tool(f"  [bold #58a6ff]▶ {name}[/] [dim]{args}[/]")

    elif etype == StreamEventType.TOOL_RESULT:
        name = payload.get("tool_name", "?")
        result = _truncate(payload.get("result_summary", ""), 160)
        elapsed = printer.end_tool(name)
        time_str = f" [dim]({elapsed:.1f}s)[/]" if elapsed > 0.1 else ""
        printer.interrupt_for_tool(f"  [bold #3fb950]✓ {name}[/] [dim]{result}[/]{time_str}")

    elif etype == StreamEventType.TOOL_ERROR:
        name = payload.get("tool_name", "?")
        error = _truncate(payload.get("error_text", ""), 160)
        elapsed = printer.end_tool(name)
        time_str = f" [dim]({elapsed:.1f}s)[/]" if elapsed > 0.1 else ""
        printer.interrupt_for_tool(f"  [bold red]✗ {name}[/] [red]{error}[/]{time_str}")

    elif etype == StreamEventType.SUBAGENT_START:
        name = payload.get("subagent", "")
        if name:
            description = payload.get("description", "")
            printer.start_subagent(name)
            printer.interrupt_for_tool(
                f"\n[bold #58a6ff]╭─ {name.upper()}[/] [dim]{description}[/]"
            )

    elif etype == StreamEventType.SUBAGENT_COMPLETE:
        name = payload.get("subagent", "")
        if name:
            elapsed = printer.end_subagent(name)
            time_str = f" [dim]({elapsed:.1f}s)[/]" if elapsed > 0.1 else ""
            printer.interrupt_for_tool(
                f"[bold #3fb950]╰─ {name} complete[/]{time_str}\n"
            )

    elif etype == StreamEventType.RUN_FAILED:
        printer.flush()
        error = payload.get("error", "Unknown error")
        print_error(f"Agent run failed: {error}")
