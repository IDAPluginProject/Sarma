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
pip install -e .
```

This installs the `sarma` command. For development you can also run it without
installing:

```bash
python src/main.py
```

## Quick start

```bash
# 1. Just start the shell
sarma

# 2. Inside the shell, configure your model interactively (saved to ~/.sarma)
sarma [chat]> /config

# One-shot, non-interactive (requires a model already configured)
sarma -c "Audit the firmware in ./target.bin for command injection"
```

`/config` prompts for model name, API mode, base URL, and API key, then saves
them to `~/.sarma/config.toml`. The change applies to the running session on the
next turn. (CLI flags `-m/--api-key/--base-url/--api-mode` still work as optional
overrides, handy for scripting `-c`.)

## Workflows

Sarma runs in one of several workflows; switch at any time, effective on the next turn.

| Workflow | How to enter | What it does |
|----------|--------------|--------------|
| `chat` (default) | `sarma` / `/workflow chat` | Direct ReAct conversation with the agent and its tools |
| `audit` | `sarma workflow audit` / `/workflow audit` | Full harness: recon → hunt → validate (⇄ gapfill) → dedupe → trace → feedback (↺ hunt) → report |
| `audit-slim` | `/workflow audit-slim` | Lightweight 3-stage pass: recon (audits) → verify (confirms reliability) → report (validates + user feedback) |

The REPL prompt shows the active workflow: `sarma [chat]>`, `sarma [audit]>`, or `sarma [audit-slim]>`.

## Slash commands

| Command | Description |
|---------|-------------|
| `/help` | List commands |
| `/status` | Model, MCP tool count, and skills status |
| `/graph` | Render the current workflow's execution graph |
| `/workflow [name]` | List workflows, or switch to one |
| `/models` | Show the configured model |
| `/history` | List past conversations |
| `/resume <id>` | Resume a previous conversation |
| `/config` | Show current configuration |
| `/clear` | Clear the current session |
| `/exit` | Quit |

## Configuration

Config is layered TOML. `sarma init` writes the **global** file at `~/.sarma/config.toml`
(on Windows, `C:\Users\<you>\.sarma\config.toml`). Optionally, `sarma init --local`
writes a per-workspace `./.sarma/config.toml` that overrides individual fields.

Resolution order (highest wins):

```
CLI flags  >  env vars  >  ./.sarma/config.toml (local)  >  ~/.sarma/config.toml (global)
```

The local file is merged onto the global one field-by-field — set just `model_name`
locally and everything else (API key, MCP servers) is inherited. MCP servers merge
**by name**: a same-named local server overrides the global one, new names are added.

```toml
[provider]
model_name = "gpt-4o"
api_key = ""
base_url = ""
api_mode = "openai_compatible"   # openai_compatible | openai_responses | anthropic
temperature = 0.7

# Repeat [[mcp_servers]] for each server
[[mcp_servers]]
name = "ida-mcp"
transport = "streamable_http"
url = "http://127.0.0.1:11338/mcp"
enabled = true
```

Environment overrides: `SARMA_MODEL`, `SARMA_API_KEY`, `SARMA_BASE_URL`, `SARMA_API_MODE`.
Set `SARMA_HOME` to relocate the global config directory (it then *is* the sarma dir).

Conversation history is per-workspace, stored in `./.sarma/db.sqlite`.

## Project layout

```text
Sarma/
├── pyproject.toml          # Package + `sarma` entry point
├── pytest.ini              # Test config
├── README.md / README_CN.md
└── src/
    ├── main.py             # Dev launcher (python src/main.py)
    └── sarma_cli/
        ├── __main__.py     # CLI entry: init / workflow / install + REPL
        ├── app.py          # Interactive REPL loop
        ├── session.py      # Conversation lifecycle (workflow-aware)
        ├── config.py       # Layered global+local config loading
        ├── paths.py        # Cross-platform path resolution
        ├── store.py        # SQLite persistence
        ├── renderer.py     # Live streaming output
        ├── status.py       # Status panel
        ├── engine/         # Agent runtime (LangGraph, MCP pool, audit graph, prompts)
        ├── workflows/      # chat + audit workflow definitions
        └── commands/       # Slash-command handlers
```

## License

MIT — see [LICENSE](LICENSE).

