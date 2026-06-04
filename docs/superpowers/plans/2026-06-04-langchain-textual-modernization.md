# LangChain/Textual Modernization Completion

**Goal:** Use the newer LangChain, LangGraph, DeepAgents, and Textual APIs where
they improve Sarma's reliability, audit structure, and TUI ergonomics without
weakening tool access needed for binary auditing.

## Completed

- `ModelRetryMiddleware`: retry transient model failures twice.
- `ToolRetryMiddleware`: retry transient tool failures twice.
- `FilesystemFileSearchMiddleware`: expose `glob_search` and `grep_search`
  rooted at the current working directory.
- Same-model structured router calls: audit branch decisions now use
  `create_agent(..., response_format=RouteDecision)` through lightweight router
  agents. Subagents still stream normal Markdown output.
- Runtime services: `Session` owns LangGraph `InMemorySaver` and `InMemoryStore`
  instances and injects them into `AgentFactory`. ReAct agents receive
  `checkpointer` and `store`; audit StateGraphs receive the same services via
  `StateGraph.compile(...)`.
- Thread identity: agent runs pass the Sarma conversation id as the LangGraph
  `thread_id`.
- Textual notifications: transient status messages use `App.notify` instead of
  writing short operational feedback into the chat transcript.

No tool or model call limit middleware is enabled. Audit workflows often need a
large number of IDA/MCP calls, so hard call caps belong in a future policy layer,
not the default runtime.

## Structured Output

Structured routing is implemented for:

- audit routing: `validate -> gapfill|dedupe`
- gapfill routing: `gapfill -> hunt|validate`
- feedback routing: `feedback -> hunt|report`
- audit-slim verification routing: `verify -> hunter|report`

The route model lives next to the audit graph as `RouteDecision`. Visible
subagent prompts no longer require `ROUTE_JSON`, so chat/report output is not
polluted by routing protocol text. `_route_next(...)` remains as a legacy
fallback for provider failures or old transcripts.

## Agent State APIs

`AgentRuntimeServices` centralizes runtime-owned LangGraph services:

- `Session`: owns the services and recreates them on runtime restart.
- `AgentFactory`: accepts the services object and passes supported kwargs into
  `create_agent`.
- Audit graph builders accept `compile_kwargs` and pass them to
  `StateGraph.compile`.
- `Store`: remains Sarma's durable metadata/history database. The installed
  LangGraph package only provides in-memory checkpoint/store backends, so these
  runtime services are not durable.
- `cache`: intentionally disabled. Do not cache IDA/MCP-sensitive work until
  target binary identity and mutable IDA state are part of cache keys.
- `transformers`: wired as an empty runtime-services field, but not enabled
  until a concrete transformer replaces existing event/state adapter code.

## Filesystem Search

`FilesystemFileSearchMiddleware` is safe to enable globally because it is
read-only and rooted at `Path.cwd()`. It complements the existing writable
DeepAgents filesystem tools and shell middleware:

- use file search for fast discovery;
- use filesystem tools for direct reads/writes;
- use shell for commands that need the project toolchain.

## Textual 8 UI Work

Adopted now:

- `App.notify` handles transient operational feedback such as config/plugin
  saves, runtime restart, context compaction, duplicate turn submission, and
  interrupt hints.
- User-requested command outputs such as `/status`, `/models`, `/history`, and
  `/graph` remain in chat so they can be copied.

Deferred UI API use:

- `Tree`/`DataTable`: useful for workflow graphs and MCP summaries, but should
  be introduced with a focused sidebar/status redesign.
- Command palette: useful for slash-command discoverability, but should wait
  until command latency and chat scrolling behavior are stable.

## Explicitly Deferred

- `ContextEditingMiddleware`: not enabled because it can alter context before
  the model reasons over it.
- Global tool selection middleware: defer until workflow-specific allowlists are
  mature enough to avoid hiding needed IDA tools.
