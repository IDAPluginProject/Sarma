# Sarma Development Guide

This guide is for contributors working on Sarma internals.

## Setup

Requirements:

- Python 3.12+
- `uv`
- optional: `rg` for fast repository search
- optional: Nuitka for release packaging

Install dependencies:

```powershell
uv sync
```

Run the TUI:

```powershell
uv run sarma
```

Run oneshot mode:

```powershell
uv run sarma -c "Audit the loaded target for command injection"
```

Run checks:

```powershell
uv run python -m compileall -q src tests scripts
uv run pytest tests\test_build_nuitka.py tests\test_runtime_boundaries.py -q
uv run sarma --help
```

## Development Workflow

1. Read the local module before editing it.
2. Keep changes inside the layer that owns the behavior.
3. Add or update `tests/test_runtime_boundaries.py` for boundary behavior.
4. Run compileall and the boundary test file.
5. Update `project.md`, README, or this guide when behavior crosses module
   boundaries.

## Module Ownership

### UI

Files:

- `src/sarma_cli/tui/`
- `src/sarma_cli/app.py`
- `src/sarma_cli/status.py`
- `src/sarma_cli/renderer.py`

Rules:

- Textual widgets own presentation only.
- TUI code should not resolve model/MCP/skill policy.
- `/status`, `/models`, `/history`, and `/graph` stay copyable in chat.
- Short operational feedback should use `App.notify`.
- `renderer.py` is for oneshot/non-full-screen output.

### Config And Persistence

Files:

- `src/sarma_cli/config.py`
- `src/sarma_cli/paths.py`
- `src/sarma_cli/store.py`

Rules:

- Config code loads/saves TOML and validates local shape.
- It must not connect MCP servers or build agents.
- Store migrations must be explicit and tested.
- `Store.update_conversation()` must keep its allowlist behavior.

### Runtime Policy

Files:

- `src/sarma_cli/runtime/resolver.py`
- `src/sarma_cli/runtime/middleware.py`
- `src/sarma_cli/runtime/services.py`

Rules:

- Resolve wildcard config here.
- Resolve workflow/subagent model, MCP, and skill policy here.
- Middleware belongs here, not in graph nodes.
- Runtime services are session-owned. Do not create checkpointers or stores in
  random engine functions.

### Engine

Files:

- `src/sarma_cli/engine/`

Rules:

- Engine receives DTOs and resolved policy.
- Engine does not read TOML.
- Engine does not render UI.
- Tool filtering must fail closed.
- Agent graphs must emit stream events that the TUI can attribute to a workflow
  or subagent.

## Agent Runtime

Interactive flow:

```text
MainApp
  -> Session.run_turn()
  -> RuntimePolicyResolver.resolve()
  -> AgentRunner
  -> AgentFactory
  -> MCP tools + model + middleware + workflow graph
  -> EventTranslator
  -> TUI widgets
```

`Session` owns:

- `Store`;
- `McpClientPool`;
- `ModelFactory`;
- `AgentRuntimeServices`;
- `AgentFactory`;
- conversation id and message history.

`AgentRuntimeServices` currently provides LangGraph `InMemorySaver` and
`InMemoryStore`. These are not durable; durable conversation history is Sarma's
SQLite store.

## Adding A Workflow

1. Add workflow metadata in `src/sarma_cli/workflows/<name>.py`.
2. Register it in `src/sarma_cli/workflows/__init__.py`.
3. Add default config entries in `config.py`.
4. Add resolver behavior in `runtime/resolver.py` if the workflow has
   subagents.
5. Add an engine graph under `src/sarma_cli/engine/` if it is not a plain ReAct
   workflow.
6. Add sidebar graph rendering through the workflow metadata object.
7. Add tests for:
   - workflow registration;
   - resolver model/MCP/skill policy;
   - graph routing;
   - sidebar graph state.

## Adding A Model API Mode

1. Add the mode to config validation/options.
2. Implement construction in `engine/model_factory.py`.
3. Keep provider quirks inside `ModelFactory`.
4. Update `/config` UI options if the new mode is user selectable.
5. Add tests for config parsing and model factory dispatch.

Do not put model construction back into `AgentFactory`.

## Adding Middleware

Add middleware in `runtime/middleware.py`.

Checklist:

- Is it safe for all workflows?
- Does it expose tools?
- Does it mutate context?
- Does it need the model instance?
- Does it need current working directory access?
- Does it need tests proving order and configuration?

Current rejected/default-off middleware:

- `ContextEditingMiddleware`: can alter context before model reasoning.
- global tool selection middleware: may hide IDA tools required by audit.
- model/tool call limit middleware: audit may require many legitimate calls.

## Structured Routing

Audit branch routing uses same-model structured router calls.

When adding a routed branch:

1. Keep the visible subagent output human-readable.
2. Define or reuse a Pydantic route model near the graph.
3. Call a lightweight router agent with `response_format`.
4. Keep a local deterministic fallback where possible.
5. Test the route helper and graph behavior separately.

Do not force visible subagent answers to start with routing JSON unless this is
explicitly a fallback compatibility path.

## Cache Policy

Cache is currently disabled by design.

Do not enable LangChain/LangGraph cache globally until Sarma has target-aware
cache keys. Vulnerability auditing depends on mutable external state:

- loaded binary;
- IDA database state;
- MCP server connection;
- renamed functions and comments;
- patched bytes;
- current tool results;
- workflow and prompt versions.

Incorrect cache hits can hide changed evidence or skip necessary tool calls.
Retries are safe; stale cache is not.

Acceptable future cache work:

- cache pure text summarization with explicit conversation/message hashes;
- cache static file reads with file path + mtime + size;
- cache IDA metadata only with IDB/binary fingerprint and mutation marker.

## TUI Development

Textual files:

- `main_app.py`: app lifecycle and event routing.
- `main_commands.py`: slash command routing for the TUI.
- `chat_area.py`: chat messages, assistant markdown, tool widgets.
- `sidebar.py`: runtime status and workflow graph.
- `config_app.py`: model/workflow config screen.
- `plugin_app.py`: MCP/skill management screen.
- `theme/`: shared CSS/theme fragments.

Rules:

- Keep chat content copyable.
- Keep tool widgets collapsed by default when output is long.
- Do not put large tool lists in the sidebar.
- Use `App.notify` for transient status.
- Keep command output in chat when the user explicitly requested it.
- Add tests with `app.run_test()` for UI behavior.

## MCP And Skills

MCP config belongs in `mcp.toml` and plugin helpers. Runtime connection belongs
to `McpClientPool`.

Skill discovery belongs in `resources/skills.py`; skill policy belongs in
`RuntimePolicyResolver`; skill tool filtering belongs in the engine/MCP pool
boundary.

Do not let skill or MCP UI code directly mutate live engine objects. Save config
first, then restart or refresh runtime through `Session`.

## Release And Packaging

Common checks before publishing:

```powershell
uv lock --check
uv run python -m compileall -q src tests scripts
uv run pytest tests\test_build_nuitka.py tests\test_runtime_boundaries.py -q
uv run sarma --help
```

Local native release scripts:

- `scripts/build_native_release.py`
- `scripts/build_native_windows.ps1`
- `scripts/build_native_linux.sh`
- `scripts/build_native_macos.sh`

Run them on the matching host OS. Nuitka is not a cross-compilation pipeline.

Windows x86_64:

```powershell
scripts\install_windows_packaging_tools.ps1
scripts\build_native_windows.ps1 -Arch x86_64 -Formats msi -Jobs 4
```

macOS arm64:

```bash
sh scripts/build_native_macos.sh --arch arm64 --formats pkg --jobs 4
```

Linux x86_64:

```bash
sh scripts/build_native_linux.sh --arch x86_64 --formats deb,pkg --jobs 4
```

Linux arm64:

```bash
sh scripts/build_native_linux.sh --arch arm64 --formats deb,pkg --jobs 4
```

The wrapper scripts run the full local release pipeline:

1. `compileall`;
2. focused pytest suite;
3. Nuitka build;
4. `sarma --help` smoke test;
5. native package creation.

Pass `--skip-tests`, `--skip-build`, `--skip-smoke`, or `--skip-package` to
`build_native_release.py` through the wrapper when you need a partial local
run.

Lower-level build scripts:

- `scripts/build_nuitka.py`
- `scripts/package_native.py`
- `scripts/build_nuitka.ps1`
- `scripts/build_nuitka.sh`
- `scripts/install.ps1`
- `scripts/install.sh`

Native release CI:

- `.github/workflows/release-native.yml`
- CI calls the same local wrapper scripts instead of duplicating build steps in
  YAML.
- Windows x86_64: MSI.
- macOS arm64: pkg.
- Linux x86_64: deb and Arch-style pkg.tar.zst.
- Linux arm64: deb and Arch-style pkg.tar.zst.

Nuitka builds are native per OS/architecture. Do not treat this as a
cross-compilation pipeline. Python 3.13 cannot use Nuitka `--mingw64`; Windows
CI uses MSVC and includes Windows runtime DLLs through
`--include-windows-runtime-dlls=yes`.

PyPI publishing should be done through the configured CI workflow or a local
trusted environment with a scoped PyPI token. Never commit tokens.
