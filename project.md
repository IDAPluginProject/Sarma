# Sarma Project Architecture

This document describes the current TypeScript source tree, module boundaries,
agent runtime, and operational safety rules.

## Current Shape

Sarma is an OpenTUI-first terminal agent for vulnerability auditing. The main
interactive experience is a full-screen TUI with:

- center chat transcript;
- bottom input bar with shell-like prompt history;
- right runtime sidebar;
- modal `/config`, `/plugin`, `/rag`, `/workflow`, `/model`, and `/graph`
  panels.

The engine is LangChain.js/LangGraph.js based. Sarma resolves model, MCP, skill,
RAG, and workflow policy before entering the engine layer; the engine receives
concrete DTOs and does not read TOML or render UI.

## Source Tree

```text
Sarma/
|-- README.md
|-- project.md
|-- code.md
|-- package.json
|-- bun.lock
|-- tsconfig.json
|-- bunfig.toml
|-- tests/
`-- src/
    |-- index.ts
    |-- cli/
    |-- context/
    |-- engine/
    |-- resources/
    |-- runtime/
    |-- tui/
    |-- workflows/
    |-- config.ts
    |-- paths.ts
    |-- session.ts
    |-- store.ts
    `-- debug.ts
```

## Layer Boundaries

```text
CLI / TUI
  -> Session
  -> RuntimePolicyResolver
  -> AgentRunner
  -> AgentFactory / workflow graphs
  -> LangChain / LangGraph / MCP
```

- `index.ts`: yargs entrypoint for TUI, one-shot mode, plain REPL, sessions,
  resume, workflow, init, and RAG commands.
- `cli/`: plain REPL, one-shot rendering, and RAG command helpers.
- `tui/`: OpenTUI/Solid components, controller, modal panels, markdown
  rendering, and prompt history. It owns presentation and user interaction.
- `config.ts` / `paths.ts`: TOML parsing, layered global/workspace config, and
  path resolution.
- `store.ts`: durable Bun SQLite store under `./.sarma/db.sqlite`.
- `resources/`: skill discovery, SkillHub access, RAG chunk/search, web search,
  and network exchange tools.
- `runtime/`: converts config/resources into concrete runtime policy and
  session-scoped LangGraph services.
- `engine/`: LangChain/LangGraph execution, model construction, MCP pooling,
  stream translation, and built agent construction.
- `workflows/`: graph implementations and user-visible workflow metadata.

Engine modules must not import TUI modules. Config modules must not build
agents or connect MCP servers.

## Agent Runtime Architecture

### Session

`src/session.ts` owns one live runtime:

- `Store`: durable workspace session database.
- `McpClientPool`: MCP connection lifecycle.
- `ModelFactory`: model client construction.
- `AgentRuntimeServices`: LangGraph in-memory checkpointer/store services.
- `AgentFactory`: compiled agent/graph builder.
- conversation id, message history, and workflow graph progress.

`Session.runTurn()` resolves the current workflow, connects MCP, compacts
context if needed, persists the user message, creates an `AgentRunner`, streams
events, updates graph progress, stores tool executions, and persists the final
assistant response.

### Runtime Policy

`runtime/resolver.ts` is the config-to-run-plan boundary. It resolves:

- active workflow model;
- enabled MCP servers;
- workflow/system prompt;
- workflow skills;
- per-subagent model assignments;
- per-subagent MCP allowlists;
- per-subagent skills;
- RAG settings and enabled knowledge bases.

Wildcard `["*"]` expansion belongs here, not in the engine.

### Runtime Services

`runtime/services.ts` defines `AgentRuntimeServices`.

Current services:

- LangGraph `MemorySaver` checkpointer;
- LangGraph in-memory store;
- optional cache field, intentionally disabled.

Durable sessions remain Sarma-owned through `Store`. Runtime services are
recreated on `/restart`.

### AgentFactory

`engine/agentFactory.ts` builds the executable runtime shape:

1. Validate the resolved model provider.
2. Connect/reuse MCP servers through `McpClientPool`.
3. Apply skill tool allow/deny filters to MCP tools.
4. Append built-in local tools.
5. Reuse the compiled agent/graph when the runtime shape is unchanged. This is
   an in-process construction cache, not model/tool result caching.
6. Initialize the model via `ModelFactory`.
7. Build one of:
   - `ruflo`: primary ReAct agent with `delegate_task`;
   - `audit`: full StateGraph;
   - `audit-slim`: compact StateGraph;
   - fallback/test ReAct agent.

Runtime services are passed into `createAgent(...)` for ReAct agents and into
`StateGraph.compile(...)` for audit graphs.

### ModelFactory

`engine/modelFactory.ts` owns model construction and provider quirks:

- `openai_compatible`;
- `openai_responses`;
- `anthropic`;
- OpenAI-compatible reasoning content preservation where available.

Sampling is config-driven. The generated default uses temperature `0.0` and
top-p `1.0`.

### Middleware

`runtime/middleware.ts` builds the default agent middleware stack. The
TypeScript port provides local equivalents for the pieces Sarma needs:

- todo/list style agent helpers where supported;
- file search and filesystem-oriented tools rooted at `process.cwd()`;
- shell/network/retry/rubric behavior where locally implemented;
- model-dependent context and compaction helpers.

Do not add hard model/tool call caps to audit workflows without an explicit
policy layer. Audit may require many legitimate MCP calls.

## Workflows

### Ruflo

`ruflo` is the default conversational workflow:

```text
user
  -> primary ReAct agent
      -> optional delegate_task focused subagent(s)
  -> synthesized answer
```

`delegate_task` creates temporary focused subagents and returns compact results.
Several delegate calls emitted in one tool step may execute in parallel.

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
                       +-------+
```

`verify` sends weak or unsupported findings back to `hunter`; verified findings
advance to `report`. The feedback loop is bounded.

## Stage Message Passing

Audit stage message passing is explicit LangGraph state, not hidden chat trace
replay and not JSON.

Each stage:

1. receives a `HumanMessage` built from the user task and prior
   `stage_outputs`;
2. runs a stage-specific `createAgent`;
3. stores the final assistant message as `stage_outputs[stageName]`;
4. returns the merged state to the graph.

The next stage receives prior outputs as Markdown sections. The TypeScript port
packs those outputs by token budget rather than a fixed character limit.

## Structured Routing

Audit branch decisions use same-model structured router calls.

The visible subagent output stays normal Markdown. Router nodes call a small
router agent with:

```ts
createAgent({
  model,
  tools: [],
  responseFormat: RouteDecision,
})
```

Routes covered:

- `validate -> gapfill | dedupe`;
- `gapfill -> hunt | validate`;
- `feedback -> hunt | report`;
- `verify -> hunter | report`.

`route_json` is not required in visible subagent prompts. `routeNext()` remains
as a fallback if structured output fails.

## Streaming And UI

`AgentRunner` streams LangGraph chunks with:

- `streamMode: ["messages", "updates", "custom"]`;
- `subgraphs: true`;
- stable `threadId = conversationId`.

`engine/streaming.ts` translates LangGraph chunks into Sarma `StreamEvent`s.
The TUI controller uses these events to update:

- chat Markdown;
- collapsed tool call rows;
- subagent lifecycle rows;
- MCP connection status;
- workflow stage status;
- workflow graph state.

For audit subagents in LangGraph.js, `makeSubagentNode()` invokes the inner
agent with the outer node `config`. That is what preserves nested subgraph
namespaces so streaming tokens and tool calls can be attributed to the correct
stage.

## Persistence

Sarma persistence is explicit:

- `~/.sarma/models.toml`: global model provider config.
- `~/.sarma/agents.toml`: global workflow/subagent policy.
- `mcp.toml`: additive global/workspace MCP definitions.
- `rag.toml`: global RAG settings plus additive knowledge base registrations.
- `skills/`: installed workspace/global skills.
- `./.sarma/.history`: prompt input history for the full-screen TUI.
- `./.sarma/db.sqlite`: sessions, messages, memory artifacts, and tool records.

The DB schema currently stores:

- `conversations`;
- `messages`;
- `tool_executions`;
- `memory_artifacts`.

## RAG

The TypeScript port preserves the user-facing RAG contract but uses a Bun
SQLite-backed local chunk database. Local HuggingFace model pulling is not
supported here. API embeddings are supported through an OpenAI-compatible
embedding endpoint; otherwise search falls back to lexical scoring.

RAG is mounted as a built-in `rag_search` tool on existing agents. It is not a
separate workflow agent.

## Why Result Cache Is Disabled

Sarma deliberately does not enable model/tool result caching.

Reasons:

- IDA/MCP state is mutable.
- Tool results depend on external process state.
- Audit routing must see fresh stage outputs.
- Generic cache keys do not include target binary identity, IDB state, MCP
  server state, or tool side effects.
- Incorrect cache hits in vulnerability auditing can hide changed evidence.

The in-process agent construction cache is separate and only avoids rebuilding
identical runtime shapes.

## Test Map

Tests live under `tests/`.

They cover:

- CLI and TUI command behavior;
- model/config parsing;
- MCP pooling and runtime policy;
- audit graph routing and prompt constraints;
- streaming translation and subagent attribution;
- Ruflo delegate lifecycle;
- context compaction;
- RAG chunk/search behavior;
- plugin and SkillHub behavior;
- session persistence and resume.

Run:

```bash
bun run typecheck
bun test
```

## Extension Rules

- Add config policy in `runtime/resolver.ts`, not in `Session` or
  `AgentFactory`.
- Add model construction in `engine/modelFactory.ts`.
- Add agent execution behavior in `engine/`.
- Add workflow graph logic in `workflows/`.
- Add presentation-only logic in `tui/`.
- Keep one-shot/plain output in `cli/`.
- Never make tool filtering fail open.
- Do not enable result cache until target-aware cache keys exist.
