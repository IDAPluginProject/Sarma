# Sarma Repository Atlas

## Project Responsibility

Sarma is the parent repository for a PySide6 desktop IDE that manages IDA Pro automation resources. The IDE owns user-facing workflows, installation, configuration, gateway lifecycle, workspace/chat state, packaging, and release coordination. Runtime plugins are tracked as submodules under `ide/resources/`.

## Submodule Policy

| Path | Branch | Responsibility |
|------|--------|----------------|
| `ide/resources/ida_mcp` | `main` | Standalone IDA-MCP plugin repository: IDA plugin entry, FastMCP server, gateway/proxy, API docs, and live-IDA tests |
| `ide/resources/diaphora` | `master` | Upstream Diaphora resource used by IDE install/config flows |

IDA-MCP code changes happen inside the `ide/resources/ida_mcp` submodule first, then Sarma updates the submodule gitlink. Diaphora updates follow upstream `master`.

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

| Directory | Responsibility |
|-----------|----------------|
| `ide/` | PySide6 desktop IDE, supervisor control plane, workspace/chat UI, packaging, and IDE tests |
| `ide/app/` | Desktop application layer: UI widgets, presenters, services, i18n, chat orchestration, and workspace preview |
| `ide/app/ui/` | Qt widgets, layout, signal/slot wiring, dialogs, and rendering only |
| `ide/app/presenters/` | Pure Python mapping from snapshots/form state into view models |
| `ide/app/services/` | Application services for supervisor calls, settings, skills, MCP/chat, and file preview routing |
| `ide/supervisor/` | Gateway lifecycle, plugin installation, config storage, platform probing, and health reports |
| `ide/shared/` | Shared paths, runtime roots, database, DTOs, config readers/writers, and portable data locations |
| `ide/resources/ida_mcp/` | IDA-MCP submodule: installable plugin files, API reference, requirements, and live-IDA tests |
| `ide/resources/diaphora/` | Diaphora submodule managed as an installable/configurable IDE resource |
| `ide/tests/` | IDE tests runnable in ordinary Python/pytest |
| `skills/` | Agent skill instructions and references; not part of the IDE or plugin runtime import path |

## Runtime Boundaries

- IDE runtime: ordinary Python 3.12 + PySide6. It can launch `command.py` as a subprocess, copy plugin resources, edit config files, and call gateway/MCP APIs.
- IDA instance runtime: IDA Python + IDA SDK. `ida_mcp.py` loads `ida_mcp/plugin_runtime.py`, starts a per-instance MCP server, and registers with the gateway.
- Gateway runtime: standalone Python process started by `command.py`/`registry.py`. It owns the in-memory instance registry, `/internal/*`, and the MCP proxy at `/mcp`.
- Test runtime: `ide/tests/` covers IDE code in ordinary pytest; `ide/resources/ida_mcp/test/` covers plugin behavior against a live gateway and IDA instance.

The IDE must not import `ida_mcp` modules directly. The two runtimes communicate through HTTP, MCP, subprocesses, and filesystem installation/configuration.

## Control Flow

1. User launches `python ide/launcher.py`.
2. IDE reads/writes portable config and bundled resource paths through `ide/shared/`.
3. Installer copies `ide/resources/ida_mcp/ida_mcp.py` and `ide/resources/ida_mcp/ida_mcp/` into IDA's plugins directory.
4. Gateway starts through `ida_mcp/command.py gateway start`, delegated through `ide/supervisor/`.
5. IDA plugin starts `plugin_runtime.py`, creates a per-instance FastMCP server, and registers through gateway `/internal/register`.
6. MCP clients call gateway `/mcp`; proxy tools forward backend calls through `/internal/call` to the selected IDA instance.
7. Direct instance MCP connections can read `ida://` resources from `api_resources.py`.

## Development Rules

- Put new IDA capabilities in the appropriate `api_*.py` module in the IDA-MCP submodule and register them with `@tool` plus `@idaread` or `@idawrite`.
- Put UI state, chat/workspace persistence, audit workflow state, and settings screens under `ide/`, not under `ida_mcp/`.
- Keep API contract updates in `ide/resources/ida_mcp/API.md`.
- Keep plugin integration tests under `ide/resources/ida_mcp/test/`; keep IDE tests under `ide/tests/`.
- `app/ui/` should not own business decisions, config model mapping, install-result text construction, or `SupervisorSnapshot` transformations; put that in presenters/services/supervisor.
- `SettingsPage` reads/writes widget values and triggers dialogs; form-update mapping belongs in `app/presenters/settings_presenter.py`.
- `MainWindow` owns navigation and rendering; status card/tree row mapping belongs in `app/presenters/main_window_presenter.py`.
- User data belongs under the IDE `data/` root and must survive update/reinstall flows.
- Packaged IDE builds use Nuitka; paths must go through `shared/runtime.py` and `shared/paths.py` and must not assume the source tree exists.

## Roadmap

### Submodule Release Discipline

- Keep `.gitmodules` branch policy stable: IDA-MCP -> `main`, Diaphora -> `master`.
- Commit, validate, and push IDA-MCP changes inside the submodule before updating the Sarma gitlink.
- Record bound IDA-MCP and Diaphora commits in Sarma release notes.

### IDE Resource Management

- Keep the IDA-MCP install file list explicit so development files are not copied into IDA plugins.
- Surface bound IDA-MCP and Diaphora commits in the IDE settings/status experience.
- Preserve strict separation between ordinary IDE Python and IDA Python plugin runtime.

### Chat And Workspace

- Continue hardening the LangGraph/MCP chat runtime, session persistence, tool trace rendering, and provider/skill selection.
- Move long-running chat execution toward subprocess isolation when UI responsiveness or cancellation requires it.
- Keep large tool-output handling and error recovery inside the application service/runtime layer.

### Packaging And Verification

- Stabilize Nuitka packaging with resource submodules included as files, not imported plugin modules.
- Release checks should confirm submodule commits exist on their remotes, IDE tests pass, and IDA-MCP compile smoke checks pass.
- Live IDA-MCP tests remain environment-dependent and require a running gateway plus a registered IDA instance.

## Verification Commands

```bash
pytest ide/tests
python -m compileall -q ide/resources/ida_mcp/ida_mcp.py ide/resources/ida_mcp/ida_mcp ide/resources/ida_mcp/test
python ide/resources/ida_mcp/test/test.py
```
