# Sarma Project Map

This document describes the current source tree, module boundaries, and runtime
architecture of Sarma.

## Directory Tree

```text
Sarma/
├── README.md
├── README_CN.md
├── LICENSE
├── Sarma.png
├── pyproject.toml
├── pytest.ini
├── uv.lock
├── project.md
├── tests/
│   └── test_runtime_boundaries.py
└── src/
    ├── main.py
    └── sarma_cli/
        ├── __init__.py
        ├── __main__.py
        ├── app.py
        ├── config.py
        ├── paths.py
        ├── renderer.py
        ├── session.py
        ├── status.py
        ├── store.py
        ├── commands/
        │   ├── __init__.py
        │   ├── history.py
        │   ├── models.py
        │   ├── plugins.py
        │   └── workflow.py
        ├── engine/
        │   ├── __init__.py
        │   ├── agent_factory.py
        │   ├── agent_runner.py
        │   ├── audit_graph.py
        │   ├── audit_slim_graph.py
        │   ├── audit_subagents.py
        │   ├── audit_slim_subagents.py
        │   ├── dto.py
        │   ├── enums.py
        │   ├── errors.py
        │   ├── mcp_pool.py
        │   ├── models.py
        │   ├── prompts.py
        │   └── streaming.py
        ├── runtime/
        │   ├── __init__.py
        │   └── resolver.py
        ├── resources/
        │   ├── __init__.py
        │   ├── plugins.py
        │   └── skills.py
        ├── tui/
        │   ├── __init__.py
        │   ├── config_app.py
        │   └── plugin_app.py
        └── workflows/
            ├── __init__.py
            ├── audit.py
            ├── audit_slim.py
            └── ruflo.py
```

## Top-Level Files

- `pyproject.toml`: Python package metadata, runtime dependencies, dev
  dependency group, and the `sarma` console script.
- `uv.lock`: Locked dependency graph managed by `uv`.
- `pytest.ini`: Pytest discovery settings.
- `README.md` / `README_CN.md`: User-facing setup, workflow, configuration,
  and UI-boundary documentation.
- `project.md`: Maintainer-facing project map and architecture notes.
- `tests/test_runtime_boundaries.py`: Boundary tests for runtime policy,
  tool-filter safety, and storage field validation.

## Source Map

### Entrypoints

- `src/main.py`
  - Development launcher.
  - Delegates to the CLI package entrypoint.

- `src/sarma_cli/__main__.py`
  - Click-based command entrypoint.
  - Defines `sarma`, `sarma init`, `sarma workflow`, and `sarma plugin`.
  - Keeps command-line flags minimal: `-c/--message`, `--version`, `--help`.
  - Loads configuration through `config.load_config()` and enters either
    interactive or one-shot mode.

### Application Shell

- `app.py`
  - Owns the interactive REPL loop.
  - Uses `prompt_toolkit` only for the input prompt and input history.
  - Handles slash-command dispatch through `commands.handle_command()`.
  - Runs ruflo/audit turns through `Session`.
  - Sends stream events to `renderer.StreamPrinter`.

- `session.py`
  - Owns conversation lifecycle.
  - Maintains current conversation id, in-memory message history, graph progress,
    MCP pool, and agent factory.
  - Resolves runtime policy through `runtime.RuntimePolicyResolver`.
  - Constructs `AgentRunner` with strong runtime DTOs.
  - Persists user and assistant messages through `Store`.

### Commands

- `commands/__init__.py`
  - Slash-command router.
  - Should remain thin: parse command name, delegate to command modules, return
    control signals such as `exit`, `clear`, `restart`, and `resume:<id>`.

- `commands/models.py`
  - `/models`: Rich table for configured model providers.
  - `/config`: launches the Textual workspace configuration app and saves
    `models.toml`, `agents.toml`, and `mcp.toml`.

- `commands/workflow.py`
  - `/workflow`: list or switch workflow.

- `commands/history.py`
  - `/history`: list persisted conversations.
  - `/resume`: return resume signal to the app loop.

- `commands/plugins.py`
  - `/plugin`: launches the Textual plugin manager.
  - Creates stdio, http, or sse MCP entries and saves them to workspace
    `mcp.toml`.
  - Installs skills from local directories, zip files, remote zip URLs, or
    Skillshub search results.
  - Requests runtime restart after plugin changes.

### Configuration

- `config.py`
  - Defines configuration dataclasses:
    - `ProviderConfig`
    - `McpServerConfig`
    - `AgentConfig`
    - `CliConfig`
  - Creates default global config files under `~/.sarma`.
  - Copies missing config files into workspace `./.sarma`.
  - Reads and writes:
    - `models.toml`
    - `agents.toml`
    - `mcp.toml`
  - Does not resolve runtime policy. That belongs in `runtime/resolver.py`.

- `paths.py`
  - Central path resolution.
  - Defines global and local config paths, skills paths, and workspace DB path.

- `resources/skills.py`
  - Discovers skill directories in local and global skill roots.
  - Loads `SKILL.md` frontmatter and prompt body.
  - Produces skill dictionaries consumed by runtime resolution.

- `resources/plugins.py`
  - Provides non-UI helpers for MCP creation/validation, skill zip/path/URL
    installation, and Skillshub search.

### Layer Boundaries

Sarma is organized by responsibility, not by file type.

- Interface layer: `__main__.py`, `app.py`, `commands/`, `tui/`, `renderer.py`,
  and `status.py`.
  - Owns CLI/TUI interaction and presentation.
  - Delegates policy and execution work downward.

- Configuration and persistence layer: `config.py`, `paths.py`, and `store.py`.
  - Owns TOML loading/saving, workspace/global paths, and SQLite persistence.
  - Does not connect to MCP servers or build agents.

- Resource layer: `resources/`.
  - Owns plugin creation helpers, validation, Skillshub search, and installed
    skill discovery/loading.
  - Does not render UI, resolve agent policy, connect MCP, or call LangGraph.

- Runtime policy layer: `runtime/`.
  - Converts `CliConfig` plus installed resources into a concrete `RunPlan`.
  - Expands `["*"]`, selects models, selects MCP servers, and resolves skills.
  - Does not perform terminal UI work or own MCP network lifecycle.

- Engine layer: `engine/`.
  - Owns LangChain/LangGraph execution, MCP client pooling, prompts, audit graphs,
    and stream-event translation.
  - Receives already-resolved DTOs and does not read TOML or scan skill folders.

- Workflow layer: `workflows/`.
  - Owns user-visible workflow metadata and graph display.
  - Does not implement model/MCP/skill policy or agent execution.

### Runtime Policy

- `runtime/resolver.py`
  - Converts `CliConfig` into a concrete `RunPlan`.
  - Resolves the active workflow's:
    - model provider
    - enabled MCP servers
    - configured skills
    - system prompt
    - subagent model assignments
    - subagent MCP allowlists
    - subagent skills
  - Expands `["*"]` for MCP and skills.
  - Converts config dataclasses into engine DTOs.

The runtime resolver is the boundary between configuration files and engine
execution. New policy rules should be added here, not in `Session` or
`AgentFactory`.

### Engine

- `engine/dto.py`
  - DTOs crossing into the engine layer:
    - `ModelProviderDTO`
    - `McpServerDTO`

- `engine/models.py`
  - Core runtime models:
    - `ConversationMessage`
    - `StreamEvent`
    - `ResolvedSkill`
    - `AgentRunConfig`
  - Converts persisted conversation messages to LangChain message objects.

- `engine/agent_runner.py`
  - Builds `AgentRunConfig` from already-resolved strong types.
  - Runs compiled LangGraph agents with streaming.
  - Accumulates assistant content, reasoning content, and tool starts.
  - Translates LangGraph chunks into `StreamEvent` objects through
    `EventTranslator`.

- `engine/agent_factory.py`
  - Builds model clients for supported API modes:
    - `openai_compatible`
    - `openai_responses`
    - `anthropic`
  - Connects MCP tools through `McpClientPool`.
  - Applies skill tool allow/deny filters.
  - Builds either a single ReAct agent or an audit graph.
  - Preserves OpenAI-compatible `reasoning_content` through a LangChain mixin.

- `engine/mcp_pool.py`
  - Owns `MultiServerMCPClient` lifecycle.
  - Reuses MCP connections when the config fingerprint is unchanged.
  - Provides tool filtering helpers.

- `engine/audit_graph.py`
  - Full audit StateGraph.
  - Stages:
    - recon
    - hunt
    - validate
    - gapfill
    - dedupe
    - trace
    - feedback
    - report
  - Creates one ReAct subagent node per stage.
  - Filters tools per MCP allowlist, stage tool prefix, and skill filter.
  - Fails closed when a stage tool prefix has no matches.

- `engine/audit_slim_graph.py`
  - Lightweight linear audit graph:
    - recon
    - verify
    - report
  - Reuses the subagent node machinery from `audit_graph.py`.

- `engine/audit_subagents.py`
  - Full audit subagent specifications.
  - Contains each stage's description, system prompt, and tool-prefix policy.

- `engine/audit_slim_subagents.py`
  - Slim audit subagent specifications.

- `engine/prompts.py`
  - Builds system prompts for ruflo and audit modes.

- `engine/streaming.py`
  - Translates LangGraph streaming chunks into UI-facing stream events.

- `engine/enums.py`
  - Stream event type constants.

- `engine/errors.py`
  - Runtime error types.

### Workflows

- `workflows/__init__.py`
  - Workflow registry.
  - Registers available workflows and tracks the active workflow.

- `workflows/ruflo.py`
  - Default Ruflo workflow metadata and graph display.
  - Ruflo uses a primary agent that can delegate focused subtasks to subagents.

- `workflows/audit.py`
  - Full audit workflow metadata and graph rendering.

- `workflows/audit_slim.py`
  - Slim audit workflow metadata and graph rendering.

Workflow modules describe user-visible modes. Execution policy still flows
through `runtime/resolver.py` and `engine/`.

### Terminal UI

Sarma deliberately uses three terminal UI libraries with separate boundaries.

- `prompt_toolkit`
  - Used only by `app.py` for the REPL input prompt and input history.
  - Do not use it for full-screen config screens.

- `Rich`
  - Used for non-full-screen terminal output:
    - tables
    - panels
    - status
    - command feedback
    - streaming render
  - Lives mainly in `renderer.py`, `status.py`, and command modules.

- `Textual`
  - Used for full-screen configuration applications.
  - Current implementation:
    - `tui/config_app.py`
    - `tui/plugin_app.py`
  - `/config` manages:
    - models
    - workflow agents
    - MCP servers
  - `/plugin` manages:
    - MCP plugin installation/configuration
    - skill plugin installation

### Persistence

- `store.py`
  - SQLite persistence under `./.sarma/db.sqlite`.
  - Stores:
    - conversations
    - messages
    - tool executions
  - `update_conversation()` has an explicit update-field allowlist.

## Runtime Architecture

### Interactive Startup

```text
sarma
  -> __main__.py
  -> config.load_config()
  -> app.run_interactive()
  -> init_workflows()
  -> Store()
  -> Session(config, store)
  -> PromptSession loop
```

### Slash Command Flow

```text
User input starts with "/"
  -> app.run_interactive()
  -> commands.handle_command()
  -> command module
  -> result signal or terminal output
```

Examples:

```text
/config
  -> commands.models.cmd_config()
  -> tui.config_app.configure_workspace_tui()
  -> save_models() + save_agents() + save_mcp()

/plugin
  -> commands.plugins.cmd_plugin()
  -> tui.plugin_app.manage_plugins_tui()
  -> save_mcp()
  -> app.run_interactive() restart signal

/restart
  -> commands.handle_command()
  -> app.run_interactive()
  -> Session.restart_runtime()

/compact
  -> commands.handle_command()
  -> app.run_interactive()
  -> Session.compact_context()
  -> structured memory + recent raw context

/workflow audit
  -> commands.workflow.cmd_workflow()
  -> workflows registry switch
```

### Ruflo/Audit Turn Flow

```text
User message
  -> Session.run_turn()
  -> RuntimePolicyResolver.resolve(workflow)
  -> AgentRunner(...)
  -> AgentFactory.build(AgentRunConfig)
  -> McpClientPool.connect()
  -> LangGraph ReAct agent or audit StateGraph
  -> EventTranslator
  -> StreamPrinter / Store
```

### Configuration Flow

```text
~/.sarma/
  models.toml
  agents.toml
  mcp.toml
  skills/

first workspace run
  -> copy missing files into ./.sarma/

./.sarma/
  models.toml
  agents.toml
  mcp.toml
  skills/
  db.sqlite
```

Workspace files are the effective runtime config. The global config is a seed
and shared template source.

## Configuration Files

### `models.toml`

Defines named model providers.

```toml
active = "default"

[[models]]
name = "default"
model_name = "gpt-4o"
api_key = ""
base_url = ""
api_mode = "openai_compatible"
temperature = 0.7
top_p = 1.0
max_context_tokens = 128000
enabled = true
```

### `agents.toml`

Assigns runtime policy per workflow or subagent.

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

`["*"]` means all configured MCP servers or all installed skills.

### `mcp.toml`

Defines MCP server connection settings.

```toml
[[mcp_servers]]
name = "local-http-tools"
transport = "http"
url = "http://127.0.0.1:8000/mcp"
enabled = true
```

## Module Dependency Direction

Preferred dependency direction:

```text
__main__
  -> app
  -> commands / session
  -> runtime
  -> config / skills / engine DTOs
  -> engine
  -> external libraries
```

Important constraints:

- `config.py` should not know engine execution details.
- `Session` should not expand model/MCP/skill policy directly.
- `AgentRunner` should receive strong runtime objects, not raw TOML dicts.
- `commands` should route and save, not implement engine logic.
- `tui` should return edit results; command/application layers decide how to
  persist them.
- `engine` should not import UI modules.

## Safety Rules

- Tool filtering must fail closed.
  - If a subagent has a tool-prefix policy and no tool matches, it receives no
    tools for that prefix set.
  - It must not fall back to all tools.

- MCP permissions are resolved before engine execution.
  - `RuntimePolicyResolver` decides which MCP servers are connected for a run.
  - `audit_graph.py` applies per-subagent MCP allowlists to the connected tools.

- Store updates must use allowlisted fields.
  - `Store.update_conversation()` rejects unknown field names.

## Testing Map

Current tests live in `tests/test_runtime_boundaries.py`.

They cover:

- audit subagent tool-prefix filtering fails closed
- MCP server tool filtering only allows selected server tools
- runtime resolver expands workflow MCP policy correctly
- store conversation updates reject unknown fields

Recommended future tests:

- Textual config app save result for Models, Agents, and MCP
- `RuntimePolicyResolver` behavior for `skills = ["*"]`
- `audit-slim` subagent policy resolution
- one-shot command behavior with missing model config
- MCP config serialization roundtrip
- token-budget context compaction split behavior

## Extension Guide

### Add A New Workflow

1. Add `workflows/<name>.py`.
2. Register it in `workflows/__init__.py`.
3. Add default agent entries to `_DEFAULT_AGENTS_TOML` in `config.py`.
4. If it has subagents, update `runtime/resolver.py` with subagent names.
5. Add graph implementation under `engine/` if needed.

### Add A New Model API Mode

1. Add the API mode to `API_MODES` in `config.py`.
2. Add a model builder in `engine/agent_factory.py`.
3. Register it in `_MODEL_BUILDERS`.
4. Update the Textual config UI if the mode needs extra fields.

### Add A New Full-Screen Config Surface

1. Add it under `src/sarma_cli/tui/`.
2. Keep persistence in the command/application layer.
3. Keep Rich output outside Textual.
4. Keep prompt_toolkit limited to the REPL input line.

### Add A New Slash Command

1. Add the command description to `commands.COMMANDS`.
2. Implement behavior in a dedicated `commands/<feature>.py` module.
3. Delegate from `commands.handle_command()`.
4. Keep command modules out of engine internals.
