# Sarma Agent Instructions

## Project Layout

- `ide/` — PySide6 desktop IDE (Poetry project, Python 3.12). It **must not** import `ida_mcp` modules directly because they depend on the IDA Python runtime.
- `ide/resources/ida_mcp/` — IDA-MCP submodule source and its pytest suite. The plugin source is copied to IDA’s `plugins/` directory during install.
- `ide/resources/ida_mcp/ida_mcp/` — The actual plugin package (FastMCP server, API modules, gateway).
- `ide/resources/ida_mcp/test/` — pytest suite that exercises a live IDA instance through the gateway.

## Running Tests

Tests require a **running gateway and a registered IDA instance**.

```bash
# Default: run all tests except debug; test both stdio and HTTP transports
python ide/resources/ida_mcp/test/test.py

# Run specific modules
python ide/resources/ida_mcp/test/test.py --core --analysis
python ide/resources/ida_mcp/test/test.py --transport=http --analysis

# Direct pytest equivalents
pytest -m "core or analysis"
pytest -m "not debug"
pytest --transport=http
```

- `ide/resources/ida_mcp/test/test.py` probes `127.0.0.1:11338/internal` and prompts if the gateway or instances are missing.
- The `debug` marker is excluded by default (requires an active debugger).
- API call logs are written to `ide/resources/ida_mcp/.artifacts/api_logs/`.
- `ide/resources/ida_mcp/test/conftest.py` adds `ide/resources/ida_mcp/` to `sys.path` so the `ida_mcp` package is importable without installation.

## Launching the IDE

```bash
python ide/launcher.py
```

## Gateway / CLI

```bash
# Start the standalone gateway
python ide/resources/ida_mcp/ida_mcp/command.py gateway start --json

# Status, stop, open IDA, call a tool directly
python ide/resources/ida_mcp/ida_mcp/command.py gateway status
python ide/resources/ida_mcp/ida_mcp/command.py gateway stop
python ide/resources/ida_mcp/ida_mcp/command.py ida open ./target.exe
python ide/resources/ida_mcp/ida_mcp/command.py tool call get_metadata --port 10000
```

## Architecture Rules

- **Entry point:** `ida_mcp.py` is the IDA plugin file; IDA looks for `PLUGIN_ENTRY()`. It loads `ida_mcp/plugin_runtime.py` to start a per-instance FastMCP HTTP server.
- **Gateway:** `registry_server.py` runs on `127.0.0.1:11338`. It exposes `/internal/*` (registration, health, forwarding) and `/mcp` (MCP proxy). It is a separate process, not part of IDA.
- **Instance registration:** Each IDA instance picks a free port starting from `ida_default_port` (default 10000), serves MCP at `/mcp/`, and registers with the gateway at `/internal/register`.
- **Tool registration:** `rpc.py` provides `@tool`, `@resource`, and `@unsafe`. `server_factory.py` imports all `api_*.py` modules to populate the registry.
- **Thread safety:** All IDA SDK work must be wrapped with `@idaread` (read-only) or `@idawrite` (mutating) from `sync.py`. These use `ida_kernwin.execute_sync()`.
- **Unsafe tools:** `py_eval` and all `dbg_*` tools are gated by `enable_unsafe` in `config.conf`. Treat them as privileged.

## Coding Conventions

- 4-space indentation, type hints where practical.
- `snake_case` for functions/modules, `UPPER_CASE` for constants.
- `Test*` classes and `test_*` functions for tests.
- Match surrounding style; no enforced formatter.
- When editing `command.py`, note that it strips its own directory from `sys.path` to prevent shadowing the stdlib `http` package.

## Config Notes

- `ida_mcp/config.conf` lives next to `config.py` in the installed plugin directory.
- Defaults: `enable_http=true`, `enable_stdio=false`, `enable_unsafe=true`.
- `open_in_ida_autonomous=true` means new IDA processes launch with `-A` (batch/autonomous mode).
- `wsl_path_bridge=true` converts WSL paths to Windows paths before launching IDA.

## Adding Tools

1. Define the function in the appropriate `api_*.py` module.
2. Decorate with `@tool` and `@idaread` or `@idawrite`.
3. Import the module in `rpc.py`’s `ensure_api_modules_loaded()` if it is a new file.
4. No proxy-side changes are needed for most tools; the gateway forwards dynamically.

## References

- `ide/resources/ida_mcp/API.md` — Full tool/request/response contract reference.
- `README.md` / `README_CN.md` — User-facing documentation.
- `project.md` — Sarma project map, IDE structure, boundaries, and development rules.
- `codemap.md` — Repository architecture, entry points, rules, and roadmap.

## Repository Map

A repository map is available at `codemap.md` in the project root.

Before working on any task, read `codemap.md` to understand:
- Project architecture and entry points
- Directory responsibilities and design boundaries
- Integration points between the IDE, bundled plugin, gateway, and tests
