"""Main application loop for Sarma CLI TUI."""

from __future__ import annotations

from typing import Any

from prompt_toolkit import PromptSession
from prompt_toolkit.history import InMemoryHistory

from shared.enums import StreamEventType

from sarma_cli.commands import handle_command
from sarma_cli.config import CliConfig
from sarma_cli.graph_view import render_graph
from sarma_cli.renderer import (
    StreamPrinter,
    console,
    print_banner,
    print_error,
    print_info,
    print_markdown,
    print_subagent_done,
    print_subagent_start,
    print_tool_error,
    print_tool_result,
    print_tool_start,
)
from sarma_cli.session import AuditSession
from sarma_cli.store import Store


async def run_interactive(config: CliConfig) -> None:
    """Main interactive REPL with audit workflow."""
    if not config.provider.model_name:
        print_error(
            "No model configured.\n"
            "  Run: sarma init   (creates .sarma/config.toml)\n"
            "  Or:  sarma -m <model> --api-key <key>"
        )
        return

    store = Store()
    session = AuditSession(config, store)

    print_banner(
        model=config.provider.model_name,
        mcp_count=len([s for s in config.mcp_servers if s.enabled]),
    )

    prompt_session: PromptSession = PromptSession(history=InMemoryHistory())

    try:
        while True:
            try:
                user_input = await prompt_session.prompt_async("sarma> ")
            except EOFError:
                break

            user_input = user_input.strip()
            if not user_input:
                continue

            # Slash commands
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

            # Run audit turn
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
    """Run a single audit message and exit."""
    if not config.provider.model_name:
        print_error("No model configured. Use --model or run 'sarma init'.")
        return

    store = Store()
    session = AuditSession(config, store)

    try:
        await _run_turn_interactive(session, message)
    except Exception as exc:
        print_error(str(exc))
    finally:
        await session.close()
        store.close()


async def _run_turn_interactive(session: AuditSession, message: str) -> None:
    """Execute one turn with streaming output to terminal."""
    printer = StreamPrinter()

    async for event in session.run_turn(message):
        _handle_event(event, printer)

    content = printer.flush()

    # Show final graph state after turn
    gs = session.graph_state
    if gs.get("current_stage") or gs.get("completed"):
        console.print(render_graph(**gs))


def _handle_event(event: Any, printer: StreamPrinter) -> None:
    """Route a StreamEvent to the appropriate renderer."""
    from app.chat.models import StreamEvent

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
        printer.flush()
        name = payload.get("tool_name", "?")
        args = payload.get("args_json", "")
        print_tool_start(name, args)

    elif etype == StreamEventType.TOOL_RESULT:
        name = payload.get("tool_name", "?")
        result = payload.get("result_summary", "")
        print_tool_result(name, result)

    elif etype == StreamEventType.TOOL_ERROR:
        name = payload.get("tool_name", "?")
        error = payload.get("error_text", "")
        print_tool_error(name, error)

    elif etype == StreamEventType.SUBAGENT_START:
        printer.flush()
        name = payload.get("subagent", "")
        if name:
            print_subagent_start(name)

    elif etype == StreamEventType.SUBAGENT_COMPLETE:
        printer.flush()
        name = payload.get("subagent", "")
        if name:
            print_subagent_done(name)

    elif etype == StreamEventType.RUN_FAILED:
        printer.flush()
        error = payload.get("error", "Unknown error")
        print_error(f"Agent run failed: {error}")
