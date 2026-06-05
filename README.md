# Sarma

**English** | **[中文](README_CN.md)**

<p align="center">
  <img src="Sarma.png" width="75%" alt="Sarma">
</p>

Sarma is a full-screen terminal agent for vulnerability auditing. It combines a
Textual chat interface, LangGraph workflows, LangChain agents, MCP tools, and
layered global/workspace configuration for reverse-engineering and security
review.

Sarma is designed for tool-heavy audits such as IDA-MCP based binary analysis,
but the runtime can use any configured MCP server.

## Features

- Full-screen Textual TUI with chat, input bar, runtime sidebar, and workflow
  graph.
- `ruflo`: conversational primary agent with focused subagent delegation.
- `audit`: full multi-stage vulnerability discovery workflow.
- `audit-slim`: compact recon/hunter/verify/report workflow.
- Per-workflow and per-agent model, MCP, and skill configuration.
- MCP management and skill installation through `/plugin`.
- RAG support through `/rag` for global embedding model settings and
  `sarma rag` for local Chroma knowledge base registration/chunking.
- Built-in `web_search`, `http_exchange`, and `packet_exchange` tools for
  public research and HTTP/HTTPS or raw port testing.
- Context compaction based on each model's configured context window.
- Native release packaging: Windows MSI, macOS pkg, Linux deb, and Linux
  Arch-style pkg.tar.zst.

## Install From Source

Requires Python 3.12+ and `uv`.

```bash
git clone https://github.com/Captain-AI-Hub/Sarma.git
cd Sarma
uv sync
uv run sarma
```

One-shot mode is available after a model is configured:

```bash
uv run sarma -c "Audit the currently loaded target for command injection"
```

## First Run

Start Sarma:

```bash
uv run sarma
```

Then use the TUI input bar:

```text
/config
```

Configure at least one model. In config:

- Model name: Sarma's local alias, referenced by workflow agents.
- Model ID: provider model id, for example `gpt-4o`, `claude-sonnet-4-5`, or an
  OpenAI-compatible model id.
- API mode: `openai_compatible`, `openai_responses`, or `anthropic`.
- Max context window: accepts values such as `128000`, `200K`, or `1M`.

Use `/plugin` to configure MCP servers and install skills.

## Workflows

| Workflow | Purpose |
|----------|---------|
| `ruflo` | Default conversational workflow with optional focused subagent delegation |
| `audit` | Full vulnerability discovery harness |
| `audit-slim` | Smaller four-stage audit harness |

Switch workflows with:

```text
/workflow audit
/workflow audit-slim
/workflow ruflo
```

Workflow changes apply on the next user turn.

### Ruflo

`ruflo` runs a primary ReAct agent. It can call `delegate_task` to spin up
focused subagents, then summarizes compact subagent results into the final
answer.

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
|---------|-------------|
| `/help` | List commands |
| `/status` | Show model and MCP status |
| `/graph` | Show the current workflow graph |
| `/workflow [name]` | List or switch workflows |
| `/models` | Show configured models |
| `/history` | List past conversations |
| `/resume <id>` | Resume a previous conversation |
| `/config` | Open model and workflow configuration |
| `/plugin` | Manage MCP servers and skills |
| `/rag` | Configure the global RAG embedding model and inspect knowledge bases |
| `/restart` | Restart runtime resources |
| `/compact` | Compact older context into structured memory |
| `/clear` | Clear the current conversation |
| `/exit` | Quit |

## Configuration Files

Sarma creates global defaults under `~/.sarma`. Workspace files under
`./.sarma` are additive overlays for local resources; they are not copies of
global config.

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
  rag/
    docs/
    chroma/
  skills/
  db.sqlite
```

Runtime merging rules:

- `models.toml` and `agents.toml` are global and are edited by `/config`.
- MCP servers are `global + workspace`; a workspace server with the same name
  overrides the global entry, but other global MCP servers remain available.
- Skills are directory resources under `skills/<name>/SKILL.md`; workspace
  skills take precedence over global skills with the same name.
- RAG embedding model settings are global and are edited by `/rag` or
  `sarma rag --model ...`.
- RAG knowledge bases are `global + workspace`, defaulting to workspace-local
  Chroma databases under `./.sarma/rag/chroma/<knowledge-base>/`.

`/plugin` lets MCP servers and skill installs choose `workspace` or `global`
scope. `sarma rag --global` registers a knowledge base in global `rag.toml`;
without `--global`, it registers only in the current workspace.

`models.toml`:

```toml
active = "default"

[[models]]
name = "default"
model_name = "gpt-4o"
api_key = ""
base_url = ""
api_mode = "openai_compatible"
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
embedding_backend = "huggingface" # huggingface | api
embedding_model = "text-embedding-3-large"
embedding_api_base = ""
embedding_api_key = ""
embedding_local_path = ""
chunk_size = 1200
chunk_overlap = 150

[[knowledge_bases]]
name = "project-docs"
docs_path = ""
chroma_path = ""
enabled = true
```

Use `/rag` to configure the global embedding backend/model, pull HuggingFace
models into the global model cache, and inspect registered knowledge bases.
Use the `sarma rag` CLI to register, split, and import knowledge bases.

Embedding backends:

- `huggingface`: uses `langchain-huggingface` and can pull/cache the model under
  `~/.sarma/rag/models/<model>/` or `embedding_local_path`.
- `api`: uses an OpenAI-compatible embeddings API through `embedding_api_base`
  and `embedding_api_key`.

If `docs_path` or `chroma_path` is empty, Sarma uses:

- source documents: `./.sarma/rag/docs/<knowledge-base>/`;
- Chroma database: `./.sarma/rag/chroma/<knowledge-base>/`.

The RAG embedding model is independent from chat models in `models.toml`; the
primary agent model is not used for document chunking or future vectorization.

The same behavior is available from the CLI:

```bash
sarma rag --backend huggingface --model BAAI/bge-small-en-v1.5 --pull
sarma rag --backend api --model text-embedding-3-large --api-base https://api.example/v1
sarma rag --name project-docs --split ./docs
sarma rag --name project-docs --split ./docs --chroma-path ./.sarma/rag/chroma/project-docs
sarma rag --name imported-kb --add ./.sarma/rag/chroma/imported-kb
sarma rag --global --name shared-kb --add /absolute/path/to/chroma
```

`--add` registers an existing Chroma persistent directory only. The directory
must contain Chroma's `chroma.sqlite3` file, for example:

```text
./.sarma/rag/chroma/project-docs/
  chroma.sqlite3
  <Chroma segment/index files>
```

When at least one knowledge base is enabled, Sarma attaches a built-in
`rag_search` tool to the existing workflow agents. RAG is not a separate agent;
agents call `rag_search` when they need private knowledge.

## Built-In Agent Tools

Sarma mounts local built-in tools on the existing workflow agents:

| Tool | Purpose |
|------|---------|
| `rag_search` | Search enabled local RAG knowledge bases |
| `web_search` | Search the public web for compact titles, URLs, and snippets |
| `http_exchange` | Send HTTP/HTTPS requests to a target host, port, path, and method |
| `packet_exchange` | Send raw TCP, UDP, or TLS payloads and capture the response |

`http_exchange` is the preferred tool for HTTP/HTTPS service checks. Use
`packet_exchange` when the agent needs a lower-level payload, a non-HTTP
protocol, or a deliberately malformed request.

## Context And State

Sarma compacts conversation context when the estimated tokens approach the
configured model window. Older context becomes structured memory; recent context
stays raw where possible. `/compact` triggers the same process manually.

Runtime checkpointer/store services are in-memory LangGraph helpers. Durable
conversation history and memory artifacts are stored in `./.sarma/db.sqlite`.

Cache is intentionally disabled. Audits depend on mutable external state such as
the loaded binary, IDA database changes, MCP connection state, and tool results.
Incorrect cache hits could hide changed evidence.

## Native Packages

Native packages are built on the matching host OS/architecture. Sarma does not
cross-compile Nuitka artifacts.

| Target | Package |
|--------|---------|
| Windows x86_64 | `.msi` |
| macOS arm64 | `.pkg` |
| Linux x86_64 | `.deb`, `.pkg.tar.zst` |
| Linux arm64 | `.deb`, `.pkg.tar.zst` |

Build requirements:

- all platforms: `uv` and Python 3.12+;
- Windows: MSVC Build Tools, .NET SDK, and WiX Toolset;
- macOS: Apple command line tools with `pkgbuild`;
- Linux: `dpkg-deb` and `zstd`;
- Linux arm64: `clang` and `lld` are used for the Nuitka C backend/linker.

Install Windows packaging tools:

```powershell
scripts\install_windows_packaging_tools.ps1
```

Equivalent manual commands:

```powershell
winget install --id Microsoft.DotNet.SDK.8 --exact --source winget
dotnet tool install --global wix
```

Windows uses MSVC with `--include-windows-runtime-dlls=yes`. Nuitka does not
support `--mingw64` with Python 3.13+.

Local native builds use the same scripts as CI:

```bash
# Windows PowerShell
scripts\build_native_windows.ps1 -Arch x86_64 -Formats msi -Jobs 4

# macOS
sh scripts/build_native_macos.sh --arch arm64 --formats pkg --jobs 4

# Linux
sh scripts/build_native_linux.sh --arch x86_64 --formats deb,pkg --jobs 4
sh scripts/build_native_linux.sh --arch arm64 --formats deb,pkg --jobs 4
```

Each wrapper runs the full release pipeline:

1. compile `src`, `tests`, and `scripts`;
2. run the focused pytest suite;
3. build the Nuitka executable;
4. run `sarma --help` against the built executable;
5. package the executable into the requested native installer formats.

Outputs are written to:

- `dist/nuitka/<platform>-<machine>/` for Nuitka build output;
- `dist/packages/` for final installers.

For partial local runs, pass these flags through the wrapper:

```bash
--skip-tests
--skip-build
--skip-smoke
--skip-package
```

The GitHub native release workflow only selects a target matrix and invokes the
same local wrapper scripts. Manual workflow dispatch can build `all`,
`windows-x86_64`, `macos-arm64`, `linux-x86_64`, or `linux-arm64`.

Linux artifacts may be much larger than macOS artifacts because the Linux job
currently uploads both `.deb` and `.pkg.tar.zst`, and each package contains the
same Nuitka onefile executable payload. Use `--formats deb` or `--formats pkg`
locally if you want to compare one Linux package at a time.

## Development

- Architecture map: [project.md](project.md)
- Development guide: [docs/development.md](docs/development.md)

Useful checks:

```bash
uv run python -m compileall -q src tests scripts
uv run pytest tests/test_build_nuitka.py tests/test_runtime_boundaries.py -q
uv run sarma --help
```

## License

MIT. See [LICENSE](LICENSE).
