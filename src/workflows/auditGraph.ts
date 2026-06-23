/**
 * Native LangGraph audit pipeline.
 *
 * Replaces deepagents' createDeepAgent with an explicit StateGraph that
 * orchestrates 8 specialist subagents through a vulnerability discovery
 * pipeline with gapfill and feedback loops.
 *
 * Each subagent node wraps a LangChain `createAgent` graph. The inner graph is
 * streamed so the outer `stream({ subgraphs: true })` can expose native
 * token/tool events with the subagent namespace; `config.writer` is reserved
 * for stage lifecycle events.
 */

import { z } from "zod";
import { createAgent } from "langchain";
import { HumanMessage, type BaseMessage } from "@langchain/core/messages";
import type { StructuredToolInterface } from "@langchain/core/tools";
import type { BaseChatModel } from "@langchain/core/language_models/chat_models";
import {
  StateGraph,
  START,
  END,
  Command,
  Annotation,
  MessagesAnnotation,
  getWriter,
  type LangGraphRunnableConfig,
} from "@langchain/langgraph";
import { AUDIT_SUBAGENTS, AUDIT_SUBAGENT_ORDER, type SubagentSpec } from "@/workflows/auditSubagents";
import type { ResolvedSkill } from "@/engine/models";
import { buildAgentMiddlewareForModel } from "@/runtime/middleware";
import type { TokenEstimator } from "@/context/tokenizer";

export const DEFAULT_MAX_GAPFILL = 3;
export const DEFAULT_MAX_FEEDBACK = 2;
export const DEFAULT_ROUTE_TIMEOUT = 30_000; // ms

export const ROUTE_ROUTER_PROMPT =
  "You are Sarma's audit workflow router. Read the completed stage output " +
  "and choose the next workflow node from the allowed options. Return only " +
  "the structured response requested by the caller. Do not summarize the " +
  "audit and do not invent findings.";

/** Structured routing decision returned by a lightweight router agent. */
export const RouteDecision = z.object({
  next: z.string().describe("Next workflow node name."),
  reason: z.string().default("").describe("Brief reason for the route."),
});
export type RouteDecisionType = z.infer<typeof RouteDecision>;

/** State flowing through the audit pipeline. */
export const AuditState = Annotation.Root({
  ...MessagesAnnotation.spec,
  audit_task: Annotation<string>({ reducer: (_a, b) => b, default: () => "" }),
  stage_outputs: Annotation<Record<string, string>>({
    reducer: (a, b) => ({ ...a, ...b }),
    default: () => ({}),
  }),
  gapfill_count: Annotation<number>({ reducer: (_a, b) => b, default: () => 0 }),
  feedback_count: Annotation<number>({ reducer: (_a, b) => b, default: () => 0 }),
  current_stage: Annotation<string>({ reducer: (_a, b) => b, default: () => "" }),
});
export type AuditStateType = typeof AuditState.State;

const BUILTIN_TOOL_NAMES = new Set([
  "rag_search",
  "web_search",
  "fetch_url",
  "http_exchange",
  "packet_exchange",
]);

function isBuiltinTool(tool: StructuredToolInterface): boolean {
  return BUILTIN_TOOL_NAMES.has(tool.name ?? "");
}

function toolNameMatches(toolName: string, prefix: string): boolean {
  return (
    toolName.startsWith(prefix) ||
    toolName.includes(`_${prefix}`) ||
    toolName.includes(`__${prefix}`) ||
    toolName.includes(`.${prefix}`) ||
    toolName.includes(`:${prefix}`)
  );
}

/** Filter tools whose name starts with any of the given prefixes. */
function filterToolsByPrefix(
  allTools: StructuredToolInterface[],
  prefixes: string[] | undefined,
): StructuredToolInterface[] {
  if (!prefixes || prefixes.length === 0 || allTools.length === 0) {
    return [...allTools];
  }
  return allTools.filter(
    (t) => isBuiltinTool(t) || prefixes.some((p) => toolNameMatches(t.name ?? "", p)),
  );
}

function filterToolsByMcp(
  allTools: StructuredToolInterface[],
  allowedServers: string[] | null | undefined,
): StructuredToolInterface[] {
  if (allowedServers === null || allowedServers === undefined) {
    return [...allTools];
  }
  const builtins = allTools.filter(isBuiltinTool);
  if (allowedServers.length === 0) {
    return builtins;
  }
  const result: StructuredToolInterface[] = [];
  for (const tool of allTools) {
    if (isBuiltinTool(tool)) {
      result.push(tool);
      continue;
    }
    const name = tool.name ?? "";
    const matches = allowedServers.some(
      (server) =>
        name === server ||
        name.startsWith(`${server}_`) ||
        name.startsWith(`${server}__`) ||
        name.startsWith(`${server}.`) ||
        name.startsWith(`${server}:`),
    );
    if (matches) result.push(tool);
  }
  return result;
}

function filterToolsBySkill(
  allTools: StructuredToolInterface[],
  skill: ResolvedSkill | null | undefined,
): StructuredToolInterface[] {
  if (!skill) return [...allTools];
  let result = [...allTools];
  if (skill.toolAllowlist !== null) {
    result = result.filter((t) => isBuiltinTool(t) || skill.toolAllowlist!.has(t.name ?? ""));
  }
  if (skill.toolDenylist !== null) {
    result = result.filter((t) => isBuiltinTool(t) || !skill.toolDenylist!.has(t.name ?? ""));
  }
  return result;
}

function combinePromptParts(...parts: (string | null | undefined)[]): string {
  return parts.map((p) => (p ?? "").trim()).filter(Boolean).join("\n\n---\n\n");
}

export function buildSubagentPrompt(
  stagePrompt: string,
  skill: ResolvedSkill | null | undefined,
): string {
  return combinePromptParts(stagePrompt, skill?.systemPromptSuffix);
}

/** Build context message for a subagent from prior stage outputs. */
function buildContext(
  stageName: string,
  auditTask: string,
  stageOutputs: Record<string, string>,
  options: { maxPriorStageTokens?: number; estimateText?: TokenEstimator } = {},
): string {
  const parts = [
    "## Audit target / user request\n",
    auditTask.trim() || "Audit the currently loaded target.",
    "\n",
  ];
  const entries = Object.entries(stageOutputs);
  if (entries.length === 0) {
    parts.push("## Prior stage outputs\nNone yet.\n");
  } else {
    parts.push("## Prior stage outputs\n");
    for (const [name, output] of packStageOutputs(entries, options)) {
      parts.push(`### ${name}\n${output}\n`);
    }
  }
  parts.push(
    `\n## Your task\nYou are the **${stageName}** agent. ` +
      "Proceed with your role based on the user request and " +
      "the prior stage outputs above. Do not rely on hidden " +
      "tool traces from previous agents; only treat the prior " +
      "stage outputs as shared evidence.",
  );
  return parts.join("\n");
}

function packStageOutputs(
  entries: [string, string][],
  options: { maxPriorStageTokens?: number; estimateText?: TokenEstimator },
): [string, string][] {
  const estimateText = options.estimateText ?? ((text: string) => Math.ceil(text.length / 4));
  const maxTokens = Math.max(Math.trunc(options.maxPriorStageTokens ?? 16_000), 1);
  if (entries.length === 0) return [];
  const perStageFloor = 1_200;
  const perStageBudget = Math.max(perStageFloor, Math.floor(maxTokens / entries.length));
  let remaining = maxTokens;
  const packed: [string, string][] = [];

  for (let i = 0; i < entries.length; i++) {
    const [name, output] = entries[i]!;
    const stagesLeft = entries.length - i;
    const budget = Math.max(perStageFloor, Math.min(perStageBudget, remaining - perStageFloor * (stagesLeft - 1)));
    const text = fitTextToTokenBudget(output, budget, estimateText);
    packed.push([name, text]);
    remaining -= Math.max(1, estimateText(text));
  }
  return packed;
}

function fitTextToTokenBudget(text: string, budget: number, estimateText: TokenEstimator): string {
  const clean = text.trim();
  if (!clean) return "";
  if (estimateText(clean) <= budget) return clean;
  const marker = "\n\n[... truncated to fit prior-stage context budget ...]";
  let lo = 0;
  let hi = clean.length;
  let best = "";
  while (lo <= hi) {
    const mid = Math.floor((lo + hi) / 2);
    const candidate = clean.slice(0, mid).trimEnd() + marker;
    if (estimateText(candidate) <= budget) {
      best = candidate;
      lo = mid + 1;
    } else {
      hi = mid - 1;
    }
  }
  return best || marker.trim();
}

/** Emit audit progress when running under LangGraph streaming. */
function writeAuditEvent(data: Record<string, unknown>): void {
  let writer: ((chunk: unknown) => void) | undefined;
  try {
    writer = getWriter();
  } catch {
    return;
  }
  writer?.(data);
}

const ROUTE_KEYS = ["next", "route", "target", "decision"];

/** Extract a structured route decision from a stage output (heuristic fallback). */
export function routeNext(output: string, allowed: Set<string>): string {
  const lines = output.split(/\r?\n/).slice(0, 12);
  for (const line of lines) {
    let text = line.trim();
    if (!text) continue;
    if (text.toLowerCase().startsWith("route_json:")) {
      text = text.split(/:(.+)/)[1]?.trim() ?? "";
    }
    if (text.startsWith("{")) {
      try {
        const data = JSON.parse(text) as Record<string, unknown>;
        const value =
          (data.next as string) ||
          (data.route as string) ||
          (data.target as string) ||
          (data.decision as string);
        if (typeof value === "string" && allowed.has(value.trim().toLowerCase())) {
          return value.trim().toLowerCase();
        }
      } catch {
        continue;
      }
    }
    if (text.includes(":")) {
      const idx = text.indexOf(":");
      const key = text.slice(0, idx).trim().toLowerCase();
      let value = text.slice(idx + 1).trim().toLowerCase();
      if (ROUTE_KEYS.includes(key) && allowed.has(value)) {
        return value;
      }
    }
  }
  return "";
}

/** Normalize a structured route response into a valid next-node name. */
function routeValueFromStructuredResponse(response: unknown, allowed: Set<string>): string {
  let value: unknown;
  if (response && typeof response === "object") {
    const obj = response as Record<string, unknown>;
    value = obj.next ?? obj.route ?? obj.target ?? obj.decision;
  }
  if (typeof value === "string" && allowed.has(value.trim().toLowerCase())) {
    return value.trim().toLowerCase();
  }
  return "";
}

/**
 * Race `fn(signal)` against a timeout, aborting the underlying work on timeout.
 *
 * The factory receives an AbortSignal that is passed to the model invoke so a
 * timed-out router call is actually cancelled rather than left running in the
 * background (consuming the connection/tokens past the deadline).
 */
function withTimeout<T>(fn: (signal: AbortSignal) => Promise<T>, ms: number): Promise<T> {
  const controller = new AbortController();
  let timer: ReturnType<typeof setTimeout> | undefined;
  const timeout = new Promise<never>((_resolve, reject) => {
    timer = setTimeout(() => {
      controller.abort();
      reject(new Error(`route timed out after ${ms}ms`));
    }, ms);
  });
  return Promise.race([fn(controller.signal), timeout]).finally(() => {
    if (timer) clearTimeout(timer);
  }) as Promise<T>;
}

/**
 * Ask the same-model structured router for the next workflow node.
 *
 * Keeps audit subagent output human-readable while moving branch decisions
 * off prompt-parsed markdown. Callers fall back to local parsing on failure.
 */
export async function routeNextStructured(
  routeAgent: ReturnType<typeof createAgent>,
  stage: string,
  output: string,
  allowed: Set<string>,
): Promise<string> {
  if (!output.trim()) return "";
  const prompt =
    `Stage: ${stage}\n` +
    `Allowed next nodes: ${[...allowed].sort().join(", ")}\n\n` +
    "Completed stage output:\n" +
    output.slice(0, 8000);

  const result = (await withTimeout(
    (signal) =>
      routeAgent.invoke(
        { messages: [new HumanMessage(prompt)] },
        { recursionLimit: 4, signal },
      ),
    DEFAULT_ROUTE_TIMEOUT,
  )) as { structuredResponse?: unknown };

  const decision = routeValueFromStructuredResponse(result.structuredResponse, allowed);
  if (decision) return decision;
  return routeValueFromStructuredResponse(result, allowed);
}

/** Create a same-model structured router agent for workflow branching. */
export function makeRouteAgent(model: BaseChatModel, name: string): ReturnType<typeof createAgent> {
  return createAgent({
    model,
    tools: [],
    systemPrompt: ROUTE_ROUTER_PROMPT,
    responseFormat: RouteDecision,
    name,
  });
}

interface SubagentNodeOptions {
  maxPriorStageTokens?: number;
  estimateText?: TokenEstimator;
  subagentModels?: Record<string, BaseChatModel> | null;
  allowedMcpServers?: string[] | null;
  skill?: ResolvedSkill | null;
  conversationId?: string;
}

type NodeFn = (
  state: AuditStateType,
  config: LangGraphRunnableConfig,
) => Promise<Partial<AuditStateType>>;

/**
 * Create an async node function that runs a react agent for one stage.
 *
 * Invokes the inner agent with the node's own `config` propagated, so the
 * inner run is nested under this node's namespace ("<name>:<uuid>"). That makes
 * the inner agent's streaming events (tokens, tool calls) propagate through the
 * outer graph's `stream({ subgraphs: true })` with the correct namespace, which
 * the EventTranslator resolves back to this subagent. Also emits custom events
 * via `config.writer` to signal stage lifecycle transitions.
 *
 * NOTE: we pass `config` straight to `invoke` rather than manually iterating an
 * inner `.stream()`. In LangGraph.js the streaming context rides on `config`
 * (there is no Python-style contextvar), so threading it is what surfaces the
 * nested events; a manual inner loop that drops `config` surfaces nothing.
 */
export function makeSubagentNode(
  name: string,
  spec: SubagentSpec,
  defaultModel: BaseChatModel,
  allTools: StructuredToolInterface[],
  options: SubagentNodeOptions = {},
): NodeFn {
  const model = options.subagentModels?.[name] ?? spec.model ?? defaultModel;
  let tools = filterToolsByMcp(allTools, options.allowedMcpServers);
  tools = filterToolsByPrefix(tools, spec.toolPrefixes);
  tools = filterToolsBySkill(tools, options.skill);

  const prompt = buildSubagentPrompt(spec.systemPrompt, options.skill);

  const agent = createAgent({
    model,
    tools,
    systemPrompt: prompt,
    middleware: buildAgentMiddlewareForModel(model, { conversationId: options.conversationId }),
  });

  const node: NodeFn = async (state, config) => {
    const writer = config.writer ?? getWriter();
    writer?.({ type: "subagent_start", name });

    const auditTask = state.audit_task ?? "";
    const context = buildContext(name, auditTask, state.stage_outputs ?? {}, {
      maxPriorStageTokens: options.maxPriorStageTokens,
      estimateText: options.estimateText,
    });
    const inputMessages = [new HumanMessage(context)];

    // Invoke the inner agent WITH this node's config so the run is nested under
    // the "<name>:<uuid>" namespace and its tokens/tool-calls surface on the
    // outer stream({subgraphs:true}). See the function docstring.
    let lastMsg = "";
    try {
      const result = (await agent.invoke({ messages: inputMessages }, config)) as {
        messages?: BaseMessage[];
      };
      const msgs = result.messages ?? [];
      lastMsg = msgs.length ? stringifyContent(msgs[msgs.length - 1]!.content) : "";
    } catch (exc) {
      // Surface a completion so the UI does not hang on a perpetually-"running"
      // stage, and record the failure as this stage's output so downstream
      // stages and the final report can see what went wrong.
      writer?.({ type: "subagent_complete", name });
      const msg = exc instanceof Error ? exc.message : String(exc);
      const newOutputs = { ...(state.stage_outputs ?? {}) };
      newOutputs[name] = `[stage ${name} failed: ${msg}]`;
      return { audit_task: auditTask, stage_outputs: newOutputs, current_stage: name };
    }

    const newOutputs = { ...(state.stage_outputs ?? {}) };
    newOutputs[name] = lastMsg;

    writer?.({ type: "subagent_complete", name });
    return {
      audit_task: auditTask,
      stage_outputs: newOutputs,
      current_stage: name,
    };
  };

  return node;
}

function stringifyContent(content: unknown): string {
  if (typeof content === "string") return content;
  if (Array.isArray(content)) {
    const parts: string[] = [];
    for (const block of content) {
      if (typeof block === "string") parts.push(block);
      else if (block && typeof block === "object" && (block as { type?: string }).type === "text") {
        parts.push(String((block as { text?: string }).text ?? ""));
      }
    }
    return parts.join("");
  }
  return String(content ?? "");
}

// ---------------------------------------------------------------------------
// Routers
// ---------------------------------------------------------------------------

/**
 * After validate: if candidates remain unresolved, branch to gapfill.
 * This is the validate⇄gapfill side-branch. `gapfill_count` bounds the whole
 * cluster so it always terminates onto the main line (dedupe).
 */
function validateRouterFromDecision(state: AuditStateType, decision: string): Command {
  const output = (state.stage_outputs ?? {}).validate ?? "";
  const lower = output.toLowerCase();
  const hasGaps = ["needs-more", "needs more", "unresolved", "gap", "incomplete", "uncertain"].some(
    (k) => lower.includes(k),
  );
  const count = state.gapfill_count ?? 0;

  if ((decision === "gapfill" || (!decision && hasGaps)) && count < DEFAULT_MAX_GAPFILL) {
    const nextCount = count + 1;
    writeAuditEvent({
      type: "audit_route",
      from: "validate",
      to: "gapfill",
      loop: "gapfill",
      count: nextCount,
    });
    return new Command({ update: { gapfill_count: nextCount }, goto: "gapfill" });
  }
  writeAuditEvent({ type: "audit_route", from: "validate", to: "dedupe" });
  return new Command({ goto: "dedupe" });
}

/** Gapfill decides where its requests go: re-hunt or re-validate. */
function gapfillRouterFromDecision(state: AuditStateType, decision: string): Command {
  const output = (state.stage_outputs ?? {}).gapfill ?? "";
  const lower = output.toLowerCase();
  const wantsHunt = ["hunt", "search", "new candidate", "additional sink", "unexplored", "scan"].some(
    (k) => lower.includes(k),
  );
  const target = decision || (wantsHunt ? "hunt" : "validate");
  writeAuditEvent({ type: "audit_route", from: "gapfill", to: target });
  return new Command({ goto: target });
}

/**
 * After feedback: weak findings trigger a fresh hunt round (the long loop).
 * Routes back to Hunt (not Gapfill), resetting the gapfill budget. The
 * `feedback_count` bounds the outer loop.
 */
function feedbackRouterFromDecision(state: AuditStateType, decision: string): Command {
  const output = (state.stage_outputs ?? {}).feedback ?? "";
  const lower = output.toLowerCase();
  const isWeak = ["weak", "insufficient", "needs more", "speculative", "unconfirmed"].some((k) =>
    lower.includes(k),
  );
  const count = state.feedback_count ?? 0;

  if ((decision === "hunt" || (!decision && isWeak)) && count < DEFAULT_MAX_FEEDBACK) {
    const nextCount = count + 1;
    writeAuditEvent({
      type: "audit_route",
      from: "feedback",
      to: "hunt",
      loop: "feedback",
      count: nextCount,
    });
    return new Command({ update: { feedback_count: nextCount, gapfill_count: 0 }, goto: "hunt" });
  }
  writeAuditEvent({ type: "audit_route", from: "feedback", to: "report" });
  return new Command({ goto: "report" });
}

async function routeOrFallback(
  routeAgent: ReturnType<typeof createAgent> | null,
  stage: string,
  output: string,
  allowed: Set<string>,
): Promise<string> {
  if (routeAgent === null) {
    return routeNext(output, allowed);
  }
  try {
    return await routeNextStructured(routeAgent, stage, output, allowed);
  } catch {
    return routeNext(output, allowed);
  }
}

export interface BuildAuditGraphOptions {
  systemPrompt?: string;
  subagentSpecs?: SubagentSpec[];
  subagentModels?: Record<string, BaseChatModel> | null;
  subagentMcpAllow?: Record<string, string[] | null> | null;
  subagentSkills?: Record<string, ResolvedSkill | null> | null;
  structuredRouting?: boolean;
  maxPriorStageTokens?: number;
  estimateText?: TokenEstimator;
  compileKwargs?: Record<string, unknown>;
  conversationId?: string;
}

/** Build and compile the audit pipeline StateGraph. */
export function buildAuditGraph(
  model: BaseChatModel,
  tools: StructuredToolInterface[],
  options: BuildAuditGraphOptions = {},
) {
  const specs = options.subagentSpecs ?? AUDIT_SUBAGENTS;
  const specMap = new Map(specs.map((s) => [s.name, s]));
  const structuredRouting = options.structuredRouting ?? true;

  const validateRouteAgent = structuredRouting ? makeRouteAgent(model, "audit_validate_router") : null;
  const gapfillRouteAgent = structuredRouting ? makeRouteAgent(model, "audit_gapfill_router") : null;
  const feedbackRouteAgent = structuredRouting ? makeRouteAgent(model, "audit_feedback_router") : null;

  const builder = new StateGraph(AuditState);
  // Nodes are registered dynamically (loop + checks), so the compile-time
  // node-name union cannot be inferred. Wire through a string-typed view,
  // mirroring the Python builder's plain-string node references.
  const g = builder as unknown as {
    addNode: (
      name: string,
      fn: NodeFn,
      opts?: { ends?: string[] },
    ) => void;
    addEdge: (from: string, to: string) => void;
    compile: (opts?: Record<string, unknown>) => ReturnType<StateGraph<typeof AuditState.spec>["compile"]>;
  };

  for (const name of AUDIT_SUBAGENT_ORDER) {
    const spec = specMap.get(name)!;
    const nodeFn = makeSubagentNode(name, spec, model, tools, {
      subagentModels: options.subagentModels,
      allowedMcpServers: (options.subagentMcpAllow ?? {})[name],
      skill: (options.subagentSkills ?? {})[name],
      maxPriorStageTokens: options.maxPriorStageTokens,
      estimateText: options.estimateText,
      conversationId: options.conversationId,
    });
    g.addNode(name, nodeFn);
  }

  const validateCheck: NodeFn = async (state) => {
    writeAuditEvent({
      type: "subagent_start",
      name: "validate_check",
      description: "same-model structured router: gapfill | dedupe",
    });
    const output = (state.stage_outputs ?? {}).validate ?? "";
    const decision = await routeOrFallback(
      validateRouteAgent,
      "validate",
      output,
      new Set(["gapfill", "dedupe"]),
    );
    const next = validateRouterFromDecision(state, decision) as unknown as Partial<AuditStateType>;
    writeAuditEvent({ type: "subagent_complete", name: "validate_check" });
    return next;
  };

  const gapfillCheck: NodeFn = async (state) => {
    writeAuditEvent({
      type: "subagent_start",
      name: "gapfill_check",
      description: "same-model structured router: hunt | validate",
    });
    const output = (state.stage_outputs ?? {}).gapfill ?? "";
    const decision = await routeOrFallback(
      gapfillRouteAgent,
      "gapfill",
      output,
      new Set(["hunt", "validate"]),
    );
    const next = gapfillRouterFromDecision(state, decision) as unknown as Partial<AuditStateType>;
    writeAuditEvent({ type: "subagent_complete", name: "gapfill_check" });
    return next;
  };

  const feedbackCheck: NodeFn = async (state) => {
    writeAuditEvent({
      type: "subagent_start",
      name: "feedback_check",
      description: "same-model structured router: hunt | report",
    });
    const output = (state.stage_outputs ?? {}).feedback ?? "";
    const decision = await routeOrFallback(
      feedbackRouteAgent,
      "feedback",
      output,
      new Set(["hunt", "report"]),
    );
    const next = feedbackRouterFromDecision(state, decision) as unknown as Partial<AuditStateType>;
    writeAuditEvent({ type: "subagent_complete", name: "feedback_check" });
    return next;
  };

  g.addNode("validate_check", validateCheck, { ends: ["gapfill", "dedupe"] });
  g.addNode("gapfill_check", gapfillCheck, { ends: ["hunt", "validate"] });
  g.addNode("feedback_check", feedbackCheck, { ends: ["hunt", "report"] });

  // Main line: recon → hunt → validate → (validate_check) → dedupe → trace
  //            → feedback → (feedback_check) → report
  // Side-branch (validate⇄gapfill): validate_check → gapfill → gapfill_check
  //            → {hunt | validate}
  // Outer loop: feedback_check → {hunt | report}
  g.addEdge(START, "recon");
  g.addEdge("recon", "hunt");
  g.addEdge("hunt", "validate");
  g.addEdge("validate", "validate_check");
  g.addEdge("gapfill", "gapfill_check");
  g.addEdge("dedupe", "trace");
  g.addEdge("trace", "feedback");
  g.addEdge("feedback", "feedback_check");
  g.addEdge("report", END);

  return g.compile(options.compileKwargs);
}
