# Sarma

**English** | **[中文](README_CN.md)**

<p align="center">
  <img src="Sarma.png" width="75%" alt="Sarma">
</p>

Sarma is a full-screen terminal agent for vulnerability auditing. It combines a
Textual chat interface, LangGraph workflows, LangChain agents, MCP tools, and
workspace-scoped configuration for reverse-engineering and security review.

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
| `/restart` | Restart runtime resources |
| `/compact` | Compact older context into structured memory |
| `/clear` | Clear the current conversation |
| `/exit` | Quit |

## Configuration Files

Sarma creates global defaults under `~/.sarma` and copies missing files into the
workspace `./.sarma`. The workspace files are the effective runtime config.

```text
./.sarma/
  models.toml
  agents.toml
  mcp.toml
  skills/
  db.sqlite
```

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
