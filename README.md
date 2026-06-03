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
| `audit-slim` | `/workflow audit-slim` | Lightweight 3-stage pass: recon (audits) → verify (confirms reliability) → report (validates + user feedback) |

The REPL prompt shows the active workflow: `sarma [ruflo]>`, `sarma [audit]>`, or `sarma [audit-slim]>`.

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
