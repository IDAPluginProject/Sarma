# Sarma

<p align="center">
  <img src="Sarma.png" width="75%" alt="Sarma">
</p>

Sarma is a terminal agent for vulnerability auditing. This repository is the
TypeScript/Bun implementation of Sarma, built on LangChain.js, LangGraph.js,
OpenTUI/Solid, MCP tools, and layered global/workspace configuration.

Sarma is designed for tool-heavy security work such as IDA-MCP based binary
analysis, source review, and network probing, but it can use any configured MCP
server.

## Features

- Full-screen OpenTUI interface with chat, input history, runtime sidebar,
  MCP connection status, workflow stages, and modal panels.
- `ruflo`: conversational primary ReAct agent with optional parallel
  `delegate_task` focused subagents.
- `audit`: full multi-stage vulnerability discovery workflow.
- `audit-slim`: compact recon/hunter/verify/report workflow.
- Per-workflow and per-subagent model, MCP, and skill configuration.
- `/config` model/workflow configuration TUI.
- `/plugin` MCP and skill configuration TUI, with local/global install scope.
- SkillHub search/install support from `https://www.skillhub.club` by default.
- `/rag` RAG configuration TUI and `sarma rag` CLI for local knowledge bases.
- Built-in `rag_search`, `web_search`, `http_exchange`, and `packet_exchange`
  tools mounted on existing agents.
- Context compaction based on each model profile's configured context window.
- Workspace session database with `sarma sessions` and `sarma resume <id>`.

## Install

Sarma is published as the Bun CLI package `sarma-seek`. The installed command is
`sarma`.

Install with Bun:

```bash
bun add -g sarma-seek
sarma
```

Or install with npm:

```bash
npm install -g sarma-seek
sarma
```

The npm-installed command still runs on Bun because Sarma's executable uses
`#!/usr/bin/env bun`. Make sure `bun` is available in `PATH`.

## Install From Source

Requires Bun.

```bash
git clone https://github.com/Captain-AI-Hub/Sarma.git
cd Sarma
bun install
bun run sarma
```

One-shot mode is available after a model is configured:

```bash
bun run sarma -c "Audit the currently loaded target for command injection"
```

Use a specific workflow:

```bash
bun run sarma -c "Audit this target" --workflow audit-slim
```

Use the plain line-based REPL instead of the full-screen TUI:

```bash
bun run sarma --plain
```

## First Run

Initialize config files:

```bash
bun run sarma init
```

Start the TUI:

```bash
bun run sarma
```

Then open model configuration:

```text
/config
```

Configure at least one model profile:

- Model name: Sarma's local alias, referenced by workflow agents.
- Model ID: provider model id, for example `gpt-4o`, `claude-sonnet-4-5`, or an
  OpenAI-compatible model id.
- API mode: `openai_compatible`, `openai_responses`, or `anthropic`.
- Max context window: accepts values such as `128000`, `200K`, or `1M`.

Use `/plugin` to configure MCP servers and install skills. Use `/rag` to
configure RAG model settings and knowledge bases.

## Workflows

| Workflow | Purpose |
| --- | --- |
| `ruflo` | Default conversational workflow with optional focused subagent delegation |
| `audit` | Full vulnerability discovery harness |
| `audit-slim` | Smaller four-stage audit harness |

Switch workflows with:

```text
/workflow
/workflow audit
/workflow audit-slim
/workflow ruflo
```

`/workflow` with no argument opens the workflow picker. Workflow changes apply
on the next user turn.

### Ruflo

`ruflo` runs a primary ReAct agent. It can call `delegate_task` to spin up
focused subagents, then summarizes compact subagent results into the final
answer. Multiple `delegate_task` calls from the same tool step can run in
parallel.

```text
user
  -> primary agent
      -> optional delegate_task -> focused subagent
      -> optional delegate_task -> focused subagent
  -> final answer
```

### Audit

`audit` is the full workflow:

```text
START
  -> recon
  -> hunt
  -> validate
  -> validate_check
       -> gapfill -> gapfill_check -> hunt | validate
       -> dedupe
  -> trace
  -> feedback
  -> feedback_check -> hunt | report
  -> END
```

Stages:

- `recon`: target architecture, metadata, entry points, imports/exports,
  strings, functions, and trust boundaries.
- `hunt`: vulnerability candidates and dangerous sinks.
- `validate`: end-to-end validation of candidates.
- `gapfill`: coverage gaps and targeted follow-up work.
- `dedupe`: duplicate and root-cause consolidation.
- `trace`: data/control-flow evidence.
- `feedback`: evidence quality review.
- `report`: final vulnerability report.

Branch decisions are made by same-model structured router calls. Visible
subagent output remains normal Markdown; agents do not need to emit routing JSON
in chat.

### Audit-Slim

`audit-slim` is the compact workflow:

```text
START -> recon -> hunter <-> verify -> report -> END
```

- `recon`: maps architecture and weak areas.
- `hunter`: audits vulnerability candidates in those areas.
- `verify`: checks whether findings are real and reliable, and sends weak
  findings back to `hunter`.
- `report`: reports verified findings only.

## Slash Commands

| Command | Description |
| --- | --- |
| `/help` | Show command help |
| `/status` | Show combined runtime status |
| `/model [name]` | List or select active model |
| `/config` | Configure model providers and workflow agents |
| `/mcp` | Show MCP status |
| `/skills` | Show skill status |
| `/graph` | Open current workflow graph view |
| `/graph status` | Print a copyable workflow graph report |
| `/workflow [name]` | Open picker or switch workflow |
| `/models` | Show configured models and assignments |
| `/sessions` | List saved sessions |
| `/resume <id>` | Resume a saved session |
| `/plugin` | Configure MCP servers and skills |
| `/rag` | Configure RAG settings and knowledge bases |
| `/debug [on|off]` | Enable debug console/file logging |
| `/restart` | Restart workflow runtime resources |
| `/compact` | Compact conversation context |
| `/clear` | Clear current session history |
| `/exit` | Leave the TUI |

The full-screen TUI stores prompt history in `./.sarma/.history`; Up/Down browse
previous prompts like a shell history file.

## Sessions

Sarma stores workspace sessions in `./.sarma/db.sqlite`.

List sessions:

```bash
bun run sarma sessions
```

Resume a session:

```bash
bun run sarma resume <session-id>
```

On exit, the plain REPL prints the current session id and resume command. The
full-screen TUI also uses the same workspace store.

## Configuration Files

Sarma creates global defaults under `~/.sarma`. Workspace files under
`./.sarma` are additive overlays for local resources.

Global config:

```text
~/.sarma/
  models.toml
  agents.toml
  mcp.toml
  rag.toml
  rag/
    models/
  skills/
```

Workspace config and data:

```text
./.sarma/
  mcp.toml
  rag.toml
  .history
  db.sqlite
  rag/
    docs/
    chroma/
  skills/
```

Runtime merging rules:

- `models.toml` and `agents.toml` are global model/workflow policy files.
- MCP servers are `global + workspace`; a workspace server with the same name
  overrides the global entry.
- Skills are directory resources under `skills/<name>/SKILL.md`; workspace
  skills take precedence over global skills with the same name.
- RAG embedding model settings are global; knowledge bases are `global +
  workspace`.

`models.toml`:

```toml
active = "default"

[[models]]
name = "default"
model_name = "gpt-4o"
api_key = ""
base_url = ""
api_mode = "openai_compatible"
temperature = 0.0
top_p = 1.0
max_context_tokens = 128000
enabled = true
```

`agents.toml`:

```toml
[[agents]]
name = "ruflo"
model = "default"
mcp = ["*"]
skills = []

[[agents]]
name = "audit.recon"
model = "default"
mcp = ["ida-mcp"]
skills = ["*"]
```

`mcp.toml`:

```toml
[[mcp_servers]]
name = "ida-mcp"
transport = "http" # stdio | http | sse
url = "http://127.0.0.1:8000/mcp"
enabled = true
```

`rag.toml`:

```toml
embedding_backend = "api" # huggingface | api
embedding_model = "text-embedding-3-large"
embedding_api_base = ""
embedding_api_key = ""
embedding_local_path = ""
chunk_size = 1200
chunk_overlap = 150

[[knowledge_bases]]
name = "project-docs"
backend = "sarma_native" # sarma_native | chroma_http
docs_path = ""
chroma_path = ""
enabled = true
```

## Plugins And Skills

Use `/plugin` to manage both MCP servers and skills. New MCP and skill entries
can be saved to workspace scope or global scope.

Skills can be added manually by placing a `SKILL.md` file under:

```text
./.sarma/skills/<name>/SKILL.md
~/.sarma/skills/<name>/SKILL.md
```

They are discovered by name and can be enabled per workflow agent through
`agents.toml` or the plugin/config TUI.

SkillHub search and install uses `https://www.skillhub.club` by default. Override
with:

```bash
SARMA_SKILLSHUB_URL=https://example.com bun run sarma
```

## RAG

The TypeScript port stores local chunks in a Bun SQLite-backed database inside a
Chroma-style directory containing `chroma.sqlite3`. API embeddings are supported
through an OpenAI-compatible embedding endpoint. Local HuggingFace model pulling
is not supported in this TypeScript port; with no embedding model configured,
search falls back to lexical scoring.

CLI examples:

```bash
bun run sarma rag --backend api --model text-embedding-3-large --api-base https://api.example/v1
bun run sarma rag --name project-docs --split ./docs
bun run sarma rag --name imported-kb --add ./.sarma/rag/chroma/imported-kb
bun run sarma rag --global --name shared-kb --add /absolute/path/to/chroma
```

When at least one knowledge base is enabled, Sarma attaches a built-in
`rag_search` tool to the existing workflow agents. RAG is not a separate agent.

## Built-In Agent Tools

| Tool | Purpose |
| --- | --- |
| `rag_search` | Search enabled RAG knowledge bases |
| `web_search` | Search the public web for compact titles, URLs, and snippets |
| `http_exchange` | Send HTTP/HTTPS requests to a target host, port, path, and method |
| `packet_exchange` | Send raw TCP, UDP, or TLS payloads and capture the response |

`http_exchange` is the preferred tool for HTTP/HTTPS checks. Use
`packet_exchange` for lower-level or non-HTTP protocol probes.

## Context And State

Sarma compacts conversation context when the estimated token count approaches
the configured model window. Older context becomes structured memory; recent
context stays raw where possible. `/compact` triggers the same process manually.

LangGraph checkpointer/store services are in-memory runtime helpers. Durable
sessions, messages, memory artifacts, and tool records are stored in
`./.sarma/db.sqlite`.

Result caching is intentionally not enabled for model/tool outputs. Audits
depend on mutable external state such as a loaded binary, IDA database changes,
MCP connection state, and tool results.

## Development

Useful checks:

```bash
bun run typecheck
bun test
bun run sarma --help
```

More detail:

- Architecture map: [project.md](project.md)
- Development guide: [code.md](code.md)

## License

MIT, as declared in `package.json`.
