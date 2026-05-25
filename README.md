# Sarma

**English** | **[中文](README_CN.md)**

<p align="center">
  <img src="Sarma.png" width="75%" alt="Sarma">
</p>

Sarma is a desktop IDE for IDA Pro automation. It provides a PySide6 workbench for installing and configuring reverse-engineering resources, managing the IDA-MCP gateway, and running assistant-driven analysis workflows without coupling the IDE runtime to IDA Python internals.

The repository is the parent project for the IDE. Runtime plugins are tracked as submodules under `ide/resources/`:

| Path | Remote | Branch | Role |
|------|--------|--------|------|
| `ide/resources/ida_mcp` | `git@github.com:Captain-AI-Hub/IDA-MCP.git` | `main` | IDA-MCP plugin, gateway, MCP tools/resources, and live-IDA tests |
| `ide/resources/soff/` | `https://github.com/Captain-AI-Hub/soff` | release | Soff binary diff engine plugin binaries |

## Repository Layout

```text
Sarma/
├── ide/                         # PySide6 desktop IDE and supervisor
│   ├── launcher.py              # Development entry point
│   ├── app/                     # UI, presenters, chat/workspace services
│   ├── supervisor/              # Installer, gateway lifecycle, health checks
│   ├── shared/                  # Paths, database, DTOs, config helpers
│   ├── resources/
│   │   ├── ida_mcp/             # Git submodule: standalone IDA-MCP plugin repo
│   │   ├── soff/                # Soff binary diff plugin binaries
│   │   ├── i18n/                # IDE localization resources
│   │   └── icons/               # IDE icons
│   ├── tests/                   # IDE pytest suite
│   └── resources/
│       └── skills/              # Agent skill materials used by local workflows
├── codemap.md                   # Architecture atlas and entry-point index
└── project.md                   # Repository project map
```

## Getting the Source

Clone with submodules so the IDE has the plugin resources it installs:

```bash
git clone --recurse-submodules git@github.com:Captain-AI-Hub/Sarma.git
cd Sarma
```

If the repository was cloned without submodules:

```bash
git submodule update --init --recursive
```

To update resource submodules to their configured tracking branches:

```bash
git submodule update --remote ide/resources/ida_mcp
```

## Launching the IDE

```bash
python ide/launcher.py
```

The IDE project targets Python 3.12 and uses the dependencies declared under `ide/`. For development, install IDE dependencies from `ide/requirements.txt` or use the Poetry project in `ide/pyproject.toml`.

## IDA-MCP Boundary

`ide/resources/ida_mcp` is a standalone Git submodule. It contains:

- `ida_mcp.py`, the IDA plugin entry file exposing `PLUGIN_ENTRY()`.
- `ida_mcp/`, the plugin package with FastMCP instance server, gateway, proxy, CLI, and API modules.
- `API.md`, the tool/resource/internal HTTP contract reference.
- `test/`, the live-IDA pytest suite.

The IDE may copy these files, launch `ida_mcp/command.py` as a subprocess, and edit plugin configuration. It must not import `ida_mcp` modules directly because they depend on the IDA Python runtime.

## Development Commands

```bash
# IDE tests
pytest ide/tests

# Plugin smoke compile from the submodule
python -m compileall -q ide/resources/ida_mcp/ida_mcp.py ide/resources/ida_mcp/ida_mcp ide/resources/ida_mcp/test

# Plugin live tests require a running gateway and registered IDA instance
python ide/resources/ida_mcp/test/test.py
```

## Documentation

- `codemap.md` - repository architecture, entry points, and runtime boundaries.
- `project.md` - Sarma parent-repository project map.
- Roadmap and IDE rules are merged into `codemap.md` and `project.md`.
- `ide/resources/ida_mcp/API.md` - IDA-MCP API contract.
