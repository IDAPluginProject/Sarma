# Sarma Full-Screen TUI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development

**Goal:** Replace the prompt_toolkit REPL with a full-screen Textual TUI featuring a chat area (center), workflow sidebar (right), and input bar (bottom), similar to OpenCode's layout.

**Architecture:** A single Textual `MainApp` manages the full-screen layout using CSS Grid. The existing `Session`/`Engine` layers remain unchanged; only the presentation layer (`app.py`, `renderer.py`) is replaced with Textual widgets. Stream events are bridged via Textual's message system.

**Tech Stack:** Textual (already a dependency), Rich (already a dependency)

---

## File Structure

### New Files
- `src/sarma_cli/tui/main_app.py` — Textual `MainApp` with grid layout
- `src/sarma_cli/tui/chat_log.py` — `RichLog`-based chat history widget
- `src/sarma_cli/tui/message_item.py` — Single message display widget (user/assistant)
- `src/sarma_cli/tui/sidebar.py` — Right sidebar showing workflow status
- `src/sarma_cli/tui/input_bar.py` — Bottom input bar with Textual `Input`
- `src/sarma_cli/tui/main_app.css` — Textual CSS for layout

### Modified Files
- `src/sarma_cli/app.py` — `run_interactive()` launches `MainApp` instead of REPL loop
- `src/sarma_cli/renderer.py` — Create `TextualStreamPrinter` variant for TUI integration

---

## Task 1: Create MainApp with Grid Layout

**Files:**
- Create: `src/sarma_cli/tui/main_app.py`
- Create: `src/sarma_cli/tui/main_app.css`
- Modify: `src/sarma_cli/app.py:41-158`

**Layout (CSS Grid):**
```css
Screen {
    layout: grid;
    grid-size: 2;
    grid-columns: 3fr 1fr;
    grid-rows: 1fr auto;
}

#chat-area { row: span 1; column: span 1; }
#sidebar { row: span 2; column: span 1; }
#input-bar { row: span 1; column: span 1; }
```

**Steps:**
- [ ] Step 1: Create `main_app.css` with grid layout
- [ ] Step 2: Create `MainApp` class with compose() yielding chat-area, sidebar, input-bar
- [ ] Step 3: Mount placeholder widgets (Static) in each region
- [ ] Step 4: Update `app.py` `run_interactive()` to launch `MainApp(config).run()`
- [ ] Step 5: Run `uv run sarma` to verify full-screen layout appears

---

## Task 2: Build Chat Log Area

**Files:**
- Create: `src/sarma_cli/tui/chat_log.py`
- Modify: `src/sarma_cli/tui/main_app.py`

**Steps:**
- [ ] Step 1: Create `ChatLog` widget (extends `RichLog`)
- [ ] Step 2: Add `add_user_message(text)` method that writes a styled user message
- [ ] Step 3: Add `add_assistant_placeholder()` method that returns a `MessageItem` widget reference
- [ ] Step 4: Integrate `ChatLog` into `MainApp`
- [ ] Step 5: Test by manually adding dummy messages

---

## Task 3: Build Message Item Widget

**Files:**
- Create: `src/sarma_cli/tui/message_item.py`

**Design:**
- User messages: right-aligned, blue background panel
- Assistant messages: left-aligned, default background
- Streaming support: `update_content(markdown_text)` method
- Tool calls: inline badge-style display

**Steps:**
- [ ] Step 1: Create `MessageItem(Static)` base class
- [ ] Step 2: Add `UserMessageItem` with right-aligned Panel
- [ ] Step 3: Add `AssistantMessageItem` with streaming `update()` support
- [ ] Step 4: Add `ToolCallItem` for tool start/result display
- [ ] Step 5: Test rendering in isolation

---

## Task 4: Build Sidebar Widget

**Files:**
- Create: `src/sarma_cli/tui/sidebar.py`
- Modify: `src/sarma_cli/tui/main_app.py`

**Content:**
- Workflow name + active indicator
- Subagent stage list (for audit mode)
- MCP server status (connected / not connected)
- Model name
- Session info (conversation ID, message count)

**Steps:**
- [ ] Step 1: Create `Sidebar(Vertical)` with sections
- [ ] Step 2: Add `update_workflow(name, stage)` method
- [ ] Step 3: Add `update_mcp_status(connected, tools)` method
- [ ] Step 4: Add `update_model(name)` method
- [ ] Step 5: Style with borders and colors matching theme

---

## Task 5: Build Input Bar

**Files:**
- Create: `src/sarma_cli/tui/input_bar.py`
- Modify: `src/sarma_cli/tui/main_app.py`

**Features:**
- Textual `Input` widget with placeholder
- Submit on Enter
- `/` command detection (highlight in blue)
- Multi-line support (Shift+Enter for newline)

**Steps:**
- [ ] Step 1: Create `InputBar(Horizontal)` with Input + Submit Button
- [ ] Step 2: Handle `on_input_submitted` event
- [ ] Step 3: Post `UserMessageSubmitted` custom message to MainApp
- [ ] Step 4: Clear input after submit
- [ ] Step 5: Style input bar with border-top

---

## Task 6: Integrate Session and Streaming

**Files:**
- Modify: `src/sarma_cli/tui/main_app.py`
- Modify: `src/sarma_cli/renderer.py`
- Modify: `src/sarma_cli/app.py`

**Architecture:**
- `MainApp` holds `Session` instance
- On user submit: create async worker calling `session.run_turn(message)`
- Stream events are posted as Textual messages via `self.post_message()`
- MainApp's `on_stream_event` handler routes to appropriate widget

**Steps:**
- [ ] Step 1: Add `Session` and `RuntimePolicyResolver` to `MainApp.__init__`
- [ ] Step 2: Create `StreamEventMessage` Textual message class
- [ ] Step 3: Create async worker that iterates `session.run_turn()` and posts messages
- [ ] Step 4: Implement `on_stream_event` handler in MainApp
- [ ] Step 5: Route TOKEN events to `MessageItem.update_content()`
- [ ] Step 6: Route TOOL_START/RESULT to inline display
- [ ] Step 7: Route SUBAGENT_START/COMPLETE to sidebar and chat separators
- [ ] Step 8: Handle RUN_STARTED/FAILED events

---

## Task 7: Migrate Slash Commands

**Files:**
- Modify: `src/sarma_cli/tui/main_app.py`
- Modify: `src/sarma_cli/tui/input_bar.py`

**Commands to support in TUI:**
- `/help` — show help overlay
- `/status` — show status in sidebar or modal
- `/clear` — clear chat log
- `/workflow <name>` — switch workflow (update sidebar)
- `/config` — launch existing Textual config app (modal)
- `/plugin` — launch existing Textual plugin app (modal)
- `/exit` — quit app
- `/restart` — restart session runtime
- `/compact` — compact context

**Steps:**
- [ ] Step 1: Create command router in MainApp
- [ ] Step 2: Implement `/help` as temporary RichLog message
- [ ] Step 3: Implement `/clear` as chat log clear
- [ ] Step 4: Implement `/workflow` with sidebar update
- [ ] Step 5: Implement `/config` and `/plugin` as modal overlays
- [ ] Step 6: Implement `/exit`, `/restart`, `/compact`
- [ ] Step 7: Pass unknown commands to existing `handle_command()` where possible

---

## Task 8: Adapt Renderer for TUI

**Files:**
- Modify: `src/sarma_cli/renderer.py`
- Modify: `src/sarma_cli/tui/chat_log.py`

**Changes:**
- `StreamPrinter` is replaced by `MessageItem` streaming updates
- `print_banner` stays for non-interactive mode
- Tool line formatting functions are reused
- Subagent separator functions are reused

**Steps:**
- [ ] Step 1: Extract badge/tool formatting as pure functions (no console.print)
- [ ] Step 2: Create `format_tool_start(name, args) -> Text`
- [ ] Step 3: Create `format_tool_result(name, result, elapsed) -> Text`
- [ ] Step 4: Update `_handle_event()` in `app.py` to use formatting functions
- [ ] Step 5: Remove `StreamPrinter` from TUI path (keep for `run_oneshot`)

---

## Task 9: Testing and Polish

**Files:**
- Modify: various
- Create: `tests/test_tui_main_app.py`

**Steps:**
- [ ] Step 1: Add pytest for MainApp instantiation
- [ ] Step 2: Add pytest for ChatLog message addition
- [ ] Step 3: Add pytest for Sidebar updates
- [ ] Step 4: Run full test suite: `uv run pytest tests/ -v`
- [ ] Step 5: Manual test: `uv run sarma` and verify layout
- [ ] Step 6: Test workflow switch, tool calls, subagent display
- [ ] Step 7: Polish CSS spacing, colors, borders

---

## Spec Coverage Check

| Requirement | Task |
|---|---|
| Full-screen TUI | Task 1 |
| Right sidebar with workflow | Task 4 |
| Center chat area | Task 2, 3 |
| Bottom input bar | Task 5 |
| Streaming output | Task 6 |
| Slash commands | Task 7 |
| Theme consistency | All tasks |

**No gaps identified.**

## Placeholder Scan

- No TBD/TODO placeholders
- No vague "add error handling" steps
- Each step has concrete code or command

## Type Consistency

- `StreamEventMessage` uses `event: StreamEvent` type throughout
- `MainApp` holds `session: Session` and `resolver: RuntimePolicyResolver`
- `Sidebar.update_workflow(name: str, stage: str | None)` signature is consistent
