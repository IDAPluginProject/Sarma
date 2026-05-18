# Repository Atlas: IDA-MCP

## Project Responsibility

IDA-MCP is a desktop IDE plus bundled IDA plugin distribution. The IDE owns user-facing workflows, installation, configuration, gateway lifecycle, workspace/chat state, and packaging. The bundled `ida_mcp` plugin owns IDA runtime integration, FastMCP tools/resources, gateway/proxy behavior, and live-IDA integration tests.

## System Entry Points

| Entry | Responsibility |
|-------|----------------|
| `ide/launcher.py` | Starts the PySide6 IDE in development mode |
| `ide/app/main.py` | Initializes the desktop application |
| `ide/supervisor/manager.py` | Aggregates install, config, gateway, and health operations |
| `ide/resources/ida_mcp/ida_mcp.py` | IDA plugin file exposing `PLUGIN_ENTRY()` |
| `ide/resources/ida_mcp/ida_mcp/plugin_runtime.py` | Per-IDA-instance MCP server lifecycle |
| `ide/resources/ida_mcp/ida_mcp/registry_server.py` | Standalone gateway process with `/internal/*` and `/mcp` |
| `ide/resources/ida_mcp/ida_mcp/command.py` | CLI for gateway, IDA lifecycle, tool calls, and resources |
| `ide/resources/ida_mcp/API.md` | Tool, resource, proxy, and internal HTTP contract |

## Directory Map

| Directory | Responsibility Summary | Detailed Map |
|-----------|------------------------|--------------|
| `ide/` | PySide6 desktop IDE, supervisor control plane, workspace/chat UI, packaging, and IDE tests. It must not directly import `ida_mcp`. | `ide/project.md` |
| `ide/app/` | Desktop application layer: UI widgets, presenters, services, i18n, chat orchestration, and workspace preview. | `ide/project.md` |
| `ide/supervisor/` | Backend control plane for gateway lifecycle, plugin installation, config storage, platform probing, and health reports. | `ide/project.md` |
| `ide/shared/` | Shared IDE infrastructure: paths, runtime roots, database, DTOs, config readers/writers, and portable data locations. | `ide/project.md` |
| `ide/resources/ida_mcp/` | Bundled IDA plugin project root: installable plugin files, API reference, requirements, and live-IDA tests. | `project.md` |
| `ide/resources/ida_mcp/ida_mcp/` | Core plugin package: FastMCP instance server, gateway, proxy, tool/resource APIs, CLI/control, and IDA synchronization. | `ide/resources/ida_mcp/ida_mcp/project.md` |
| `ide/resources/ida_mcp/test/` | Plugin integration tests that require a running gateway and registered IDA instance. | `AGENTS.md` |
| `ide/resources/diaphora/` | Bundled Diaphora plugin resources managed by the IDE installer/config flows. | `project.md` |
| `ide/resources/diaphora-cpp/` | Independent C++ rewrite path for Diaphora's diffing core; reads Diaphora SQLite exports and writes compatible result databases. | `ide/resources/diaphora-cpp/project.md` |
| `skills/` | Agent skill instructions and references; not part of the IDE or plugin runtime import path. | `project.md` |

## Runtime Boundaries

- IDE runtime: ordinary Python 3.12 + PySide6. It can launch `command.py` as a subprocess, copy plugin resources, and edit config files, but it must not import IDA-bound `ida_mcp` modules directly.
- IDA instance runtime: IDA Python + IDA SDK. `ida_mcp.py` loads `ida_mcp/plugin_runtime.py`, starts a per-instance MCP server, and registers with the gateway.
- Gateway runtime: standalone Python process started by `command.py`/`registry.py`. It owns the in-memory instance registry, `/internal/*`, and the MCP proxy at `/mcp`.
- Test runtime: `ide/tests/` covers IDE code in ordinary pytest; `ide/resources/ida_mcp/test/` covers plugin behavior against a live gateway and IDA instance.

## Control Flow

1. User launches `python ide/launcher.py`.
2. IDE reads/writes portable config and bundled resource paths through `ide/shared/`.
3. Installer copies `ide/resources/ida_mcp/ida_mcp.py` and `ide/resources/ida_mcp/ida_mcp/` into IDA's plugins directory.
4. Gateway starts through `ida_mcp/command.py gateway start`, which delegates to `control.py` and `registry.py`.
5. IDA plugin starts `plugin_runtime.py`, creates a per-instance FastMCP server, and registers through gateway `/internal/register`.
6. MCP clients call gateway `/mcp`; proxy tools forward backend calls through `/internal/call` to the selected IDA instance.
7. Direct instance MCP connections can read `ida://` resources from `api_resources.py`.

## Development Rules

- Put new IDA capabilities in the appropriate `api_*.py` module and register them with `@tool` plus `@idaread` or `@idawrite`.
- Put UI state, chat/workspace persistence, audit workflow state, and settings screens under `ide/`, not under `ida_mcp/`.
- Keep API contract updates in `ide/resources/ida_mcp/API.md`.
- Keep plugin integration tests under `ide/resources/ida_mcp/test/`; keep IDE tests under `ide/tests/`.
