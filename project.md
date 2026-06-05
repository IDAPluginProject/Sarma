# Sarma Project Architecture

This document describes the current Sarma source tree, module boundaries, agent
runtime, and operational safety rules.

## Current Shape

Sarma is a Textual-first terminal agent for vulnerability auditing. The main
interactive experience is a full-screen TUI with:

- center chat area;
- bottom input bar;
- right runtime/workflow sidebar;
- modal `/config` and `/plugin` screens.

The engine is LangChain/LangGraph based. Sarma resolves model, MCP, skill, and
workflow policy before entering the engine layer; the engine receives concrete
DTOs and does not read TOML or render UI.

## Source Tree

```text
Sarma/
├── README.md / README_CN.md
├── project.md
├── pyproject.toml
├── uv.lock
├── docs/
│   ├── development.md
│   └── superpowers/plans/
├── scripts/
│   ├── build_nuitka.py
│   ├── build_nuitka.ps1
│   ├── build_nuitka.sh
│   ├── install.ps1
│   └── install.sh
├── tests/
│   └── test_runtime_boundaries.py
└── src/
    ├── main.py
    └── sarma_cli/
        ├── __main__.py
        ├── app.py
        ├── config.py
        ├── paths.py
        ├── renderer.py
        ├── session.py
        ├── status.py
        ├── store.py
        ├── context/
        ├── commands/
        ├── engine/
        ├── resources/
        ├── runtime/
        ├── tui/
        └── workflows/
```

## Layer Boundaries

```text
CLI / TUI
  -> Session
  -> RuntimePolicyResolver
  -> AgentRunner
  -> AgentFactory / audit graphs
  -> LangChain / LangGraph / MCP
```

- `__main__.py`: Click entrypoint for `sarma`, `init`, `workflow`, and
  `plugin`.
- `app.py`: launches `MainApp` for interactive mode and keeps a oneshot path
  for `sarma -c`.
- `tui/`: Textual widgets and screens. It owns presentation and user
  interaction only.
- `config.py` / `paths.py`: layered global/workspace config and filesystem
  paths.
- `store.py`: Sarma's durable SQLite store under `./.sarma/db.sqlite`.
- `resources/`: skill discovery and plugin/MCP helper logic.
- `runtime/`: converts config/resources into concrete runtime policy and
  session-scoped LangGraph services.
- `engine/`: LangChain/LangGraph execution, model construction, MCP pooling,
  audit graphs, and stream translation.
- `workflows/`: user-visible workflow metadata and sidebar graph rendering.

Engine modules must not import TUI modules. Config modules must not build
agents or connect MCP servers.

## Agent Runtime Architecture

### Session

`src/sarma_cli/session.py` owns one live runtime:

- `Store`: durable Sarma conversation/history database.
- `McpClientPool`: MCP connection lifecycle.
- `ModelFactory`: model client construction.
- `AgentRuntimeServices`: LangGraph in-memory checkpointer/store services.
- `AgentFactory`: compiled agent/graph builder.
- conversation id, message history, and workflow graph progress.

`Session.run_turn()` resolves the current workflow, compacts context if needed,
persists the user message, creates an `AgentRunner`, streams events, and stores
the assistant response.

### Runtime Policy

`runtime/resolver.py` is the config-to-run-plan boundary. It resolves:

- active workflow model;
- enabled MCP servers;
- workflow/system prompt;
- workflow skills;
- per-subagent model assignments;
- per-subagent MCP allowlists;
- per-subagent skills.

Wildcard `["*"]` expansion belongs here, not in the engine.

### Runtime Services

`runtime/services.py` defines `AgentRuntimeServices`.

Current services:

- `InMemorySaver` checkpointer;
- `InMemoryStore`;
- optional cache field, currently disabled;
- optional transformers tuple, currently empty.

The installed LangGraph package only provides in-memory checkpoint/store
backends. Durable conversation history remains Sarma-owned through `Store`.

`AgentRunner` passes the Sarma conversation id as LangGraph
`configurable.thread_id` so the checkpointer has a stable session namespace.

### AgentFactory

`engine/agent_factory.py` builds the executable runtime shape:

1. Validate the resolved model provider.
2. Connect/reuse MCP servers through `McpClientPool`.
3. Apply skill tool allow/deny filters.
4. Reuse the compiled agent/graph when the runtime shape is unchanged. This is
   an in-process construction cache, not LangChain model/tool result caching.
5. Initialize the model via `ModelFactory`.
6. Build one of:
   - `ruflo`: primary ReAct agent with `delegate_task`;
   - `audit`: full StateGraph;
   - `audit-slim`: compact StateGraph;
   - fallback/test ReAct agent.

Runtime services are passed into `create_agent(...)` for ReAct agents and into
`StateGraph.compile(...)` for audit graphs.

### ModelFactory

`engine/model_factory.py` owns model construction and provider quirks:

- `openai_compatible`;
- `openai_responses`;
- `anthropic`;
- OpenAI-compatible `reasoning_content` preservation.

Sampling is intentionally fixed by config policy: temperature is `0`, top-p is
not user-configured.

### Middleware

`runtime/middleware.py` builds the default agent middleware stack:

- `TodoListMiddleware`;
- `FilesystemFileSearchMiddleware` rooted at `Path.cwd()`;
- DeepAgents `FilesystemMiddleware` rooted at `Path.cwd()`;
- `ShellToolMiddleware` rooted at `Path.cwd()`;
- `ModelRetryMiddleware(max_retries=2)`;
- `ToolRetryMiddleware(max_retries=2)`;
- model-dependent summarization helpers;
- `RubricMiddleware`.

No model/tool call limit middleware is enabled. Audit workflows can require many
IDA/MCP calls, and hard caps belong in a future policy layer.

## Workflows

### Ruflo

`ruflo` is the default conversational workflow:

```text
user
  -> primary ReAct agent
      -> optional delegate_task focused subagent(s)
  -> synthesized answer
```

Delegated subagents return compact result templates. Their full hidden traces
are not replayed into the shared context.

### Audit

Full audit graph:

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
  -> feedback_check
       -> hunt
       -> report
  -> END
```

Stages:

- `recon`: architecture, metadata, entry points, trust boundaries.
- `hunt`: vulnerability candidates.
- `validate`: end-to-end candidate validation.
- `gapfill`: coverage gaps.
- `dedupe`: duplicate/root-cause consolidation.
- `trace`: data/control-flow evidence.
- `feedback`: evidence-quality review.
- `report`: final report.

### Audit-Slim

Compact graph:

```text
START -> recon -> hunter -> verify -> report -> END
                       ^       |
                       └───────┘
```

`verify` sends weak or unsupported findings back to `hunter`; verified findings
advance to `report`.

## Structured Routing

Audit branch decisions use same-model structured router calls.

The visible subagent output stays normal Markdown. Router nodes call a small
router agent with:

```python
create_agent(model, [], response_format=RouteDecision)
```

Routes covered:

- `validate -> gapfill | dedupe`;
- `gapfill -> hunt | validate`;
- `feedback -> hunt | report`;
- `verify -> hunter | report`.

`ROUTE_JSON` is no longer required in visible subagent prompts. `_route_next()`
remains as a legacy fallback if structured output fails.

## Why Cache Is Disabled

Sarma deliberately wires a cache field but does not enable it yet.

Reasons:

- IDA/MCP state is mutable. The same prompt can produce different correct
  results after the user loads a new binary, renames functions, patches bytes,
  changes comments, or reconnects a server.
- Tool results depend on external process state, not just prompt text.
- Audit routing must see fresh stage outputs and current MCP observations.
- A generic LangGraph/LangChain cache key does not currently include target
  binary identity, IDB hash, loaded segment state, MCP server state, or tool
  side effects.
- Incorrect cache hits in vulnerability auditing are worse than slower runs:
  they can hide changed evidence or skip necessary tool calls.

Cache can be enabled later only after Sarma defines a target-aware cache policy,
for example:

- target binary hash / IDB metadata;
- MCP server identity and connection mode;
- relevant tool arguments;
- IDA database mutation/version marker;
- workflow and agent name;
- model id and prompt version.

Until then, retries improve reliability without risking stale audit evidence.

## Streaming and UI

`AgentRunner` streams LangGraph chunks with:

- `stream_mode=["messages", "updates", "custom"]`;
- `subgraphs=True`;
- `version="v2"`;
- `thread_id = conversation_id`.

`engine/streaming.py` translates LangGraph chunks into `StreamEvent`s. The TUI
uses these events to update:

- chat Markdown;
- collapsed tool call widgets;
- skill trigger lines;
- sidebar MCP status;
- active workflow graph;
- active/completed subagents.

Transient UI status uses Textual `App.notify`; user-requested command output
such as `/status`, `/models`, `/history`, and `/graph` remains in chat so it can
be copied.

## Persistence

Sarma persistence is explicit:

- `models.toml`, `agents.toml`, `mcp.toml`: workspace runtime config.
- `skills/`: installed workspace/global skills.
- `db.sqlite`: conversations, messages, memory artifacts, tool records.

LangGraph in-memory services are runtime helpers only. They are recreated on
`/restart` and are not treated as durable memory.

## Test Map

Current tests live in `tests/test_runtime_boundaries.py`.

They cover:

- agent cache reuse;
- audit routing and graph structure;
- structured router helper behavior;
- MCP filtering and status summaries;
- middleware stack and no call-limit middleware;
- runtime services;
- context compaction;
- config/plugin TUI behavior;
- main TUI command/event behavior;
- sidebar workflow graph rendering;
- store migration and update boundaries.

Run:

```powershell
uv run python -m compileall -q src tests scripts
uv run pytest tests\test_runtime_boundaries.py -q
uv run sarma --help
```

## Extension Rules

- Add config policy in `runtime/resolver.py`, not in `Session` or
  `AgentFactory`.
- Add model construction in `engine/model_factory.py`.
- Add agent execution in `engine/`.
- Add workflow metadata and sidebar graph rendering in `workflows/`.
- Add presentation-only logic in `tui/`.
- Keep `renderer.py` for oneshot/non-full-screen output.
- Never make tool filtering fail open.
- Do not enable cache until target-aware cache keys exist.
