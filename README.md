# Sarma

**English** | **[中文](README_CN.md)**

<p align="center">
  <img src="Sarma.png" width="75%" alt="Sarma">
</p>

Sarma is a lightweight terminal agent for vulnerability auditing. It drives a
LangGraph ReAct agent over any MCP toolset (for example [IDA-MCP](https://github.com/Captain-AI-Hub/IDA-MCP)),
streams reasoning and tool calls live in your terminal, and ships an opt-in
8-stage audit pipeline for structured reverse-engineering workflows.

## Install

Requires Python 3.12+.

```bash
git clone https://github.com/Captain-AI-Hub/Sarma.git
cd Sarma
uv sync
```

This creates a local `.venv` and installs the `sarma` command. Run it with:

```bash
uv run sarma
```

For development you can also run the launcher directly:

```bash
uv run python src/main.py
```

## Quick start

```bash
# 1. Just start the shell
uv run sarma

# 2. Inside the shell, configure your model interactively (saved to ~/.sarma)
sarma [ruflo]> /config

# One-shot, non-interactive (requires a model already configured)
uv run sarma -c "Audit the firmware in ./target.bin for command injection"
```

`/config` opens a full-screen Textual TUI for managing models and workflow
agents. It saves `./.sarma/models.toml` and `./.sarma/agents.toml`. The change
applies to the running session on the next turn. MCP server definitions are
managed through `/plugin`.

## Workflows

Sarma runs in one of several workflows; switch at any time, effective on the next turn.

| Workflow | How to enter | What it does |
|----------|--------------|--------------|
| `ruflo` (default) | `uv run sarma` / `/workflow ruflo` | Conversational primary agent with focused subagent delegation |
| `audit` | `uv run sarma workflow audit` / `/workflow audit` | Full harness: recon → hunt → validate (⇄ gapfill) → dedupe → trace → feedback (↺ hunt) → report |
| `audit-slim` | `/workflow audit-slim` | Compact harness: recon → hunter ⇄ verify → report |

The REPL prompt shows the active workflow: `sarma [ruflo]>`, `sarma [audit]>`, or `sarma [audit-slim]>`.

### Ruflo

`ruflo` is the default conversational workflow. It runs a primary ReAct agent
that can delegate focused tasks to subagents when useful, then synthesizes the
compact subagent results into the user-facing answer.

```text
user
  ↓
primary agent
  ├─ optional delegate_task → focused subagent
  ├─ optional delegate_task → focused subagent
  └─ synthesize compact results → answer
```

Subagents in `ruflo` return compact result templates rather than full hidden
reasoning traces, so delegation does not flood the shared context.

### Audit

`audit` is the full vulnerability discovery harness. It uses eight specialist
agents plus three router nodes:

| Agent | Role |
|-------|------|
| `recon` | Survey binary/project architecture, metadata, entry points, imports/exports, strings, functions, and trust boundaries |
| `hunt` | Search for dangerous sinks and vulnerability candidates |
| `validate` | Confirm candidates are reachable, real, and not already sanitized |
| `gapfill` | Identify coverage gaps and request more hunt or validation work |
| `dedupe` | Merge duplicate findings and cluster related root causes |
| `trace` | Build data/control-flow paths from external inputs to vulnerable sinks |
| `feedback` | Review evidence quality and send weak findings back for another hunt pass |
| `report` | Produce the final vulnerability report |

The graph is not a simple line. `gapfill` is a bounded side branch off
`validate`, and `feedback` can send weak findings back to `hunt`:

```text
START
  ↓
recon
  ↓
hunt
  ↓
validate
  ↓
validate_check
  ├─ gaps / unresolved → gapfill → gapfill_check
  │                         ├─ needs new candidates → hunt
  │                         └─ needs re-check      → validate
  └─ ok → dedupe
          ↓
        trace
          ↓
        feedback
          ↓
        feedback_check
          ├─ weak / insufficient → hunt
          └─ ok → report
                    ↓
                   END
```

Loop limits keep the harness finite: `validate`/`gapfill` can loop up to 3
times, and `feedback` can return to `hunt` up to 2 times.

Each audit agent receives the original user audit task plus prior
`stage_outputs`. Agents do not receive the full token/tool trace from previous
agents; they share structured stage results to keep context bounded.

### Audit-Slim

`audit-slim` is a compact four-stage harness for faster passes:

| Agent | Role |
|-------|------|
| `recon` | Probe the overall architecture/framework and identify weak areas |
| `hunter` | Audit vulnerabilities in the weak areas from recon |
| `verify` | Confirm whether hunter's findings are real and reliable |
| `report` | Report only findings verified as reliable |

```text
START
  ↓
recon
  ↓
hunter
  ↓
verify
  ├─ needs-hunter / weak / unsupported → hunter
  └─ verified → report
                  ↓
                 END
```

`hunter` and `verify` form the feedback loop. `verify` starts its output with
`needs-hunter` when findings are not reliable enough and gives concrete
feedback for `hunter`; it starts with `verified` when findings are ready for
`report`. The verify-to-hunter loop is capped at 3 iterations.

## Slash commands

| Command | Description |
|---------|-------------|
| `/help` | List commands |
| `/status` | Model, MCP servers, and skills status |
| `/graph` | Render the current workflow's execution graph |
| `/workflow [name]` | List workflows, or switch to one |
| `/plugin` | Manage MCP and skill plugins |
| `/restart` | Restart the current workflow runtime |
| `/models` | Show the configured model |
| `/history` | List past conversations |
| `/resume <id>` | Resume a previous conversation |
| `/config` | Open the full-screen workspace configuration TUI |
| `/clear` | Clear the current session |
| `/compact` | Compact older context into structured memory |
| `/exit` | Quit |

## Configuration

Config is split across workspace TOML files. On first run in a workspace, Sarma
creates global defaults under `~/.sarma` and copies them into `./.sarma` so each
project can be tuned independently.

```toml
active = "default"

[[models]]
name = "default"
model_name = "gpt-4o"
api_key = ""
base_url = ""
api_mode = "openai_compatible"   # openai_compatible | openai_responses | anthropic
max_context_tokens = 128000
```

`./.sarma/agents.toml` assigns models, MCP servers, and skills per workflow agent:

```toml
[[agents]]
name = "ruflo"
model = "default"
mcp = ["*"]
skills = []

[[agents]]
name = "audit.recon"
model = "default"
mcp = ["local-http-tools"]
skills = ["*"]
```

Use `["*"]` to allow all configured MCP servers or all installed skills.
`./.sarma/mcp.toml` stores MCP server definitions:

```toml
[[mcp_servers]]
name = "local-http-tools"
transport = "http"   # stdio | http | sse
url = "http://127.0.0.1:8000/mcp"
enabled = true
```

Set `SARMA_HOME` to relocate the global config directory (it then *is* the
sarma dir).

Conversation history is per-workspace, stored in `./.sarma/db.sqlite`.

## Context Compaction

Sarma compacts context only when the estimated conversation tokens approach the
configured model window (`max_context_tokens`). It preserves as much recent raw
context as fits the budget, then converts older context into structured memory:
goals, constraints, decisions, entities, verified facts, tool results, open
tasks, and risks. `/compact` triggers the same process manually.
In `/config`, the max context window accepts shorthand such as `200K` and `1M`;
saved config stores the expanded integer token count.

## Plugins

`/plugin` opens a full-screen Textual plugin manager for MCP servers and skill
templates. The MCP section creates stdio, http, or sse MCP entries in
`./.sarma/mcp.toml`; the Skills section installs a local skill directory,
`skills.zip`, remote zip URL, or a Skillshub search result.

Skills are directories containing `SKILL.md`. Workspace skills live in
`./.sarma/skills/<name>` and global skills live in `~/.sarma/skills/<name>`.
Plugin changes are validated before install/save. Use `/restart` after manual
config edits; changes made through `/plugin` request a runtime restart
automatically. Assign installed skills to workflows or agents through `/config`.

## Terminal UI boundaries

Sarma uses three terminal UI libraries with strict boundaries:

- `prompt_toolkit`: the lightweight REPL input line (`sarma [ruflo]>`) and input
  history only.
- `Rich`: non-full-screen output such as tables, status panels, markdown-style
  streaming render, and command feedback.
- `Textual`: full-screen configuration apps. `/config` manages models and
  agents through `src/sarma_cli/tui/`; `/plugin` manages MCP servers and skills.

## Project layout

```text
Sarma/
├── pyproject.toml          # Package + `sarma` entry point
├── pytest.ini              # Test config
├── README.md / README_CN.md
└── src/
    ├── main.py             # Dev launcher (python src/main.py)
    └── sarma_cli/
        ├── __main__.py     # CLI entry: init / workflow / plugin + REPL
        ├── app.py          # Interactive REPL loop
        ├── session.py      # Conversation lifecycle (workflow-aware)
        ├── config.py       # Layered global+local config loading
        ├── paths.py        # Cross-platform path resolution
        ├── store.py        # SQLite persistence
        ├── renderer.py     # Live streaming output
        ├── status.py       # Status panel
        ├── resources/      # Plugin catalogs and skill resource loading
        ├── engine/         # Agent runtime (LangGraph, MCP pool, audit graph, prompts)
        ├── runtime/        # Config-to-run-plan policy resolution
        ├── tui/            # Textual full-screen apps
        ├── workflows/      # ruflo + audit workflow definitions
        └── commands/       # Slash-command handlers
```

## License

MIT — see [LICENSE](LICENSE).
