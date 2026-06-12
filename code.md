# Sarma Development Guide

This guide is for contributors working on the TypeScript/Bun implementation of
Sarma.

## Setup

Requirements:

- Bun
- optional: `rg` for fast repository search
- optional: configured MCP servers such as IDA-MCP for real audits

Install dependencies:

```bash
bun install
```

Run the TUI:

```bash
bun run sarma
```

Run oneshot mode:

```bash
bun run sarma -c "Audit the loaded target for command injection"
```

Run the plain REPL:

```bash
bun run sarma --plain
```

Run checks:

```bash
bun run typecheck
bun test
bun run sarma --help
```

## Development Workflow

1. Read the local module before editing it.
2. Keep changes inside the layer that owns the behavior.
3. Add or update focused tests for boundary behavior.
4. Run `bun run typecheck` and the relevant `bun test` subset.
5. Update `README.md`, `project.md`, or this guide when behavior crosses module
   boundaries.

## Module Ownership

### UI

Files:

- `src/tui/`

Rules:

- OpenTUI/Solid components own presentation only.
- `controller.ts` bridges Session events into reactive UI state.
- TUI code should not resolve model/MCP/skill policy directly.
- `/status`, `/models`, `/sessions`, `/graph status`, and similar reports
  should remain copyable in chat.
- Use modal panels for configuration flows: model/config, plugin, RAG,
  workflow, model picker, and graph view.

### CLI

Files:

- `src/index.ts`
- `src/cli/`

Rules:

- `index.ts` only parses commands and dispatches.
- Plain REPL and one-shot rendering belong in `src/cli/`.
- Keep full-screen TUI imports lazy so non-TUI commands do not load OpenTUI.

### Config And Persistence

Files:

- `src/config.ts`
- `src/paths.ts`
- `src/store.ts`

Rules:

- Config code loads/saves TOML and validates file shape.
- Model providers and workflow agent policy are global.
- MCP servers, skills, and RAG knowledge bases support workspace/local scope.
- Config code must not connect MCP servers or build agents.
- Store migrations must be explicit and tested.
- `Store.updateConversation()` must keep its allowlist behavior.

### Runtime Policy

Files:

- `src/runtime/resolver.ts`
- `src/runtime/middleware.ts`
- `src/runtime/services.ts`

Rules:

- Resolve wildcard config here.
- Resolve workflow/subagent model, MCP, and skill policy here.
- Middleware belongs here, not in graph nodes.
- Runtime services are session-owned. Do not create checkpointers or stores in
  random engine functions.

### Engine

Files:

- `src/engine/`

Rules:

- Engine receives DTOs and resolved policy.
- Engine does not read TOML.
- Engine does not render UI.
- Tool filtering must fail closed.
- Agent graphs must emit stream events that the TUI can attribute to a workflow
  or subagent.

### Workflows

Files:

- `src/workflows/`

Rules:

- Keep graph structure in workflow graph modules.
- Keep stage prompts in subagent spec modules.
- Visible stage output should be normal Markdown.
- Structured routing belongs in router nodes, not in visible chat output.
- TUI graph metadata must match the actual compiled graph shape.

### Resources

Files:

- `src/resources/`

Rules:

- Built-in tools live here and are mounted by `AgentFactory`.
- Built-in tools are not MCP servers.
- RAG logic should preserve the workspace/global config contract.
- SkillHub behavior belongs in `skillshub.ts`; skill discovery/loading belongs
  in `skills.ts`.

## Agent Runtime

Interactive flow:

```text
TUI / CLI
  -> Session.runTurn()
  -> RuntimePolicyResolver.resolve()
  -> AgentRunner
  -> AgentFactory
  -> MCP tools + model + middleware + workflow graph
  -> EventTranslator
  -> TUI or CLI renderer
```

`Session` owns:

- `Store`;
- `McpClientPool`;
- `ModelFactory`;
- `AgentRuntimeServices`;
- `AgentFactory`;
- conversation id and message history;
- workflow graph progress state.

`AgentRuntimeServices` currently provides in-memory LangGraph helpers. Durable
conversation history is Sarma's SQLite store.

## Adding A Workflow

1. Add workflow metadata in `src/workflows/index.ts`.
2. Add graph code under `src/workflows/` if it is not a plain ReAct workflow.
3. Add default config entries in `src/config.ts`.
4. Add resolver behavior in `src/runtime/resolver.ts` if the workflow has
   subagents.
5. Add graph/TUI rendering support in `src/tui/controller.ts` and graph panel
   tests.
6. Add tests for:
   - workflow registration;
   - resolver model/MCP/skill policy;
   - graph routing;
   - streaming attribution;
   - TUI graph state.

## Adding A Model API Mode

1. Add the mode to config validation/options.
2. Implement construction in `src/engine/modelFactory.ts`.
3. Keep provider quirks inside `ModelFactory`.
4. Update `/config` UI options if the mode is user selectable.
5. Add tests for config parsing and model factory dispatch.

Do not put model construction back into `AgentFactory`.

## Adding Middleware

Add middleware in `src/runtime/middleware.ts`.

Checklist:

- Is it safe for all workflows?
- Does it expose tools?
- Does it mutate context?
- Does it need the model instance?
- Does it need current working directory access?
- Does it need tests proving order and configuration?

Avoid default hard call limits for audit workflows. Vulnerability audits often
need many legitimate MCP calls.

## Structured Routing

Audit branch routing uses same-model structured router calls.

When adding a routed branch:

1. Keep visible subagent output human-readable.
2. Define or reuse a Zod route schema near the graph.
3. Call a lightweight router agent with `responseFormat`.
4. Keep a deterministic fallback where possible.
5. Test the route helper and graph behavior separately.

Do not force visible subagent answers to start with routing JSON unless this is
explicitly a fallback compatibility path.

## Stage Message Passing

Audit stage message passing is explicit:

```text
stage final Markdown -> AuditState.stage_outputs -> next stage HumanMessage
```

Do not rely on hidden prior tool traces. If a downstream stage needs evidence,
the upstream stage prompt must ask for that evidence in its visible Markdown
output.

The TypeScript graph packs prior stage outputs by token budget. When changing
that logic, update tests that cover context packing and graph behavior.

## Built-In Tools

Built-in tools are local LangChain tools added by `AgentFactory`; they are not
MCP servers and not separate workflow agents.

Checklist:

- Put resource logic under `src/resources/`.
- Add a `build<Name>Tool()` function that returns a LangChain tool.
- Attach it in `AgentFactory.buildBuiltinTools()`.
- If audit subagents must keep access after MCP filtering, add the tool name to
  the built-in allow set in `src/workflows/auditGraph.ts`.
- Add tests for default mounting and audit filter preservation.
- Document user-visible behavior in `README.md`.

## Config Scope Rules

- Models: global.
- Agents/workflow policy: global.
- MCP servers: global plus workspace; workspace same-name entries override.
- Skills: global plus workspace directories; workspace same-name skills take
  precedence.
- RAG embedding settings: global.
- RAG knowledge bases: global plus workspace.
- Sessions and prompt history: workspace.

Do not silently write global files when the user selected local scope, and do
not silently write local files when the user selected global scope.

## RAG Rules

- RAG is a built-in tool on existing agents, not a workflow.
- Local chunk storage is Bun SQLite-backed.
- `chroma_http` knowledge bases are searched remotely and cannot be chunked
  locally.
- Local HuggingFace model pulling is not implemented in the TypeScript port.
- With no usable embedding model, local search falls back to lexical scoring.

## Cache Policy

Do not enable model/tool result caching by default.

Audits depend on mutable external state such as:

- loaded binary and IDB metadata;
- renamed functions and comments;
- patched bytes;
- MCP server state;
- network service state;
- tool side effects.

The agent construction cache in `AgentFactory` is allowed because it only
deduplicates identical runtime shapes inside the same process. It must include
model, tools, workflow, subagent policy, skill, and RAG shape in its key.

## Testing

Use focused test runs while editing:

```bash
bun test tests/engine.phase3.test.ts
bun test tests/tui.controller.test.ts
bun test tests/tui.app.test.tsx
```

Run the full suite before handing off broad changes:

```bash
bun run typecheck
bun test
```

OpenTUI tests may print EventTarget listener warnings; treat failures, not those
warnings, as the signal.

## Documentation Rules

- Update `README.md` for user-visible behavior.
- Update `project.md` for architecture or module-boundary changes.
- Update `code.md` for development rules or workflow changes.
- Keep examples runnable with Bun commands.
