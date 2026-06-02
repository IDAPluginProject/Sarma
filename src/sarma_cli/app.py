"""Main application loop for Sarma CLI.

Ties together the workflow registry, session, and REPL loop.
"""

from __future__ import annotations

from typing import Any

from prompt_toolkit import PromptSession
from prompt_toolkit.history import InMemoryHistory

from sarma_cli.engine.enums import StreamEventType

from sarma_cli.commands import handle_command
from sarma_cli.config import CliConfig
from sarma_cli.renderer import (
    StreamPrinter,
    console,
    print_banner,
    print_error,
    print_info,
)
from sarma_cli.session import Session
from sarma_cli.store import Store
from sarma_cli.workflows import get_registry, init_workflows


def _truncate(text: str, max_len: int) -> str:
    """Truncate text to max_len, replacing newlines with spaces."""
    text = text.replace("\n", " ").strip()
    if len(text) > max_len:
        return text[: max_len - 3] + "..."
    return text


async def run_interactive(config: CliConfig) -> None:
    """Main interactive REPL with workflow support.

    Orchestrates:
      1. Initialize workflow registry (chat, audit, etc.)
      2. Create Session
      3. Main REPL loop:
         - Read user input
         - Handle /commands
         - Run turn with agent
         - Stream output
         - Update graph state
      5. Support workflow switching

    Supports multiple workflows: chat (default), audit, etc.
    """
    # 1. Initialize workflow registry
    init_workflows()
    registry = get_registry()

    # 2. Create session
    store = Store()
    session = Session(config, store)

    print_banner(
        model=config.provider.model_name,
        mcp_count=len([s for s in config.mcp_servers if s.enabled]),
    )

    if not config.provider.model_name:
        print_info("No model configured yet — run /config to set one up.")

    # 4. Main REPL loop
    prompt_session: PromptSession = PromptSession(history=InMemoryHistory())

    try:
        while True:
            try:
                # Show current workflow in prompt
                workflow_name = registry.current_name()
                user_input = await prompt_session.prompt_async(
                    f"sarma [{workflow_name}]> "
                )
            except EOFError:
                break

            user_input = user_input.strip()
            if not user_input:
                continue

            # Handle /commands
            if user_input.startswith("/"):
                result = handle_command(
                    user_input,
                    config=config,
                    store=store,
                    graph_state=session.graph_state,
                    mcp_tool_count=session.tool_count,
                )
                if result == "exit":
                    break
                elif result == "clear":
                    session.new_conversation()
                    print_info("Session cleared.")
                    continue
                elif isinstance(result, str) and result.startswith("resume:"):
                    cid = result.split(":", 1)[1]
                    if session.resume_conversation(cid):
                        print_info(f"Resumed conversation {cid}")
                    else:
                        print_error(f"Conversation {cid} not found.")
                    continue
                elif result:
                    continue

            # Run turn with agent
            if not config.provider.model_name:
                print_info("No model configured — run /config to set one up.")
                continue
            try:
                await _run_turn_interactive(session, user_input)
            except KeyboardInterrupt:
                console.print("\n[dim]Interrupted.[/]")
            except Exception as exc:
                print_error(str(exc))

    except KeyboardInterrupt:
        pass
    finally:
        await session.close()
        store.close()
        console.print("\n[dim]Goodbye.[/]")


async def run_oneshot(config: CliConfig, message: str) -> None:
    """Run a single audit message and exit.

    Used for non-interactive mode (e.g., piped input).
    """
    if not config.provider.model_name:
        print_error("No model configured. Start `sarma` and run /config, or pass -m/--api-key.")
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
        token = payload.get("content", "")
        if token:
            printer.feed_token(token)
        reasoning = payload.get("reasoning_content", "")
        if reasoning:
            printer.feed_reasoning(reasoning)

    elif etype == StreamEventType.TOOL_START:
        # Pause live markdown, print tool line, resume on next token
        name = payload.get("tool_name", "?")
        args = _truncate(payload.get("args_json", ""), 100)
        printer.interrupt_for_tool(f"  [cyan]▶ {name}[/] [dim]{args}[/]")

    elif etype == StreamEventType.TOOL_RESULT:
        name = payload.get("tool_name", "?")
        result = _truncate(payload.get("result_summary", ""), 160)
        printer.interrupt_for_tool(f"  [green]✓ {name}[/] [dim]{result}[/]")

    elif etype == StreamEventType.TOOL_ERROR:
        name = payload.get("tool_name", "?")
        error = _truncate(payload.get("error_text", ""), 160)
        printer.interrupt_for_tool(f"  [red]✗ {name}[/] {error}")

    elif etype == StreamEventType.SUBAGENT_START:
        name = payload.get("subagent", "")
        if name:
            printer.interrupt_for_tool(
                f"\n[bold cyan]┌─ {name.upper()} ─────────────────────────[/]"
            )

    elif etype == StreamEventType.SUBAGENT_COMPLETE:
        name = payload.get("subagent", "")
        if name:
            printer.interrupt_for_tool(
                f"[green]└─ {name} complete ─────────────────[/]\n"
            )

    elif etype == StreamEventType.RUN_FAILED:
        printer.flush()
        error = payload.get("error", "Unknown error")
        print_error(f"Agent run failed: {error}")
