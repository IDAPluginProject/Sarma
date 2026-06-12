/**
 * LangGraph event stream → StreamEvent normalization.
 *
 * Bridges LangGraph subgraph streaming output to the internal `StreamEvent`
 * schema consumed by the UI layer.
 *
 * JS subgraph streaming format
 * ============================
 * Each chunk from `graph.stream(..., { subgraphs: true, streamMode: [...] })`
 * is a tuple:
 *   - 3-tuple `[ns, mode, data]` when `subgraphs: true`
 *   - 2-tuple `[mode, data]` when `subgraphs` is off (ns = [])
 *
 * `ns` is the agent hierarchy path (array of segments). `[]` = top-level graph.
 * For the audit pipeline, the first segment is the stage node name (e.g.
 * `["recon"]` or `["recon:<uuid>"]`).
 *   - mode `"messages"` → data is `[messageChunk, metadata]` (LLM tokens)
 *   - mode `"updates"`  → data is a node-name → state-delta object
 *   - mode `"custom"`   → data is whatever `config.writer` emitted
 */

import { StreamEvent } from "@/engine/models";
import { StreamEventType } from "@/engine/enums";
import { AUDIT_SUBAGENT_ORDER } from "@/workflows/auditSubagents";
import { AUDIT_SLIM_SUBAGENT_ORDER } from "@/workflows/auditSlimSubagents";

/** Maximum characters retained from a tool result in streaming events. */
export const MAX_TOOL_RESULT_CHARS = 2000;

/** Conventional name for the top-level coordinator agent. */
export const ORCHESTRATOR = "orchestrator";

const ROUTER_NODES = [
  "validate_check",
  "gapfill_check",
  "feedback_check",
  "verify_check",
] as const;

/** Known fixed workflow node names (from audit pipelines). */
const KNOWN_WORKFLOW_NODES: Set<string> = new Set([
  ...AUDIT_SUBAGENT_ORDER,
  ...AUDIT_SLIM_SUBAGENT_ORDER,
  ...ROUTER_NODES,
]);

function workflowNodeKind(name: string): "stage" | "router" {
  return (ROUTER_NODES as readonly string[]).includes(name) ? "router" : "stage";
}

function nowSeconds(): number {
  return Date.now() / 1000;
}

function stageNameFromNsSegment(segment: unknown): string {
  if (typeof segment !== "string") return "";
  // LangGraph namespace segments are often "node_name:<task_uuid>".
  const nodeName = segment.split(":", 1)[0]!;
  if (KNOWN_WORKFLOW_NODES.has(nodeName)) return nodeName;
  return "";
}

/**
 * Return the stage or dynamic subagent responsible for a namespace tuple.
 *
 * Handles native ns format where the first segment is the node name, and the
 * legacy "tools:<call_id>" segment format.
 */
function resolveSourceFromNs(
  ns: string[],
  toolCallToSubagent: Map<string, string>,
): string {
  if (!ns || ns.length === 0) return ORCHESTRATOR;
  const firstName = stageNameFromNsSegment(ns[0]);
  if (firstName) return firstName;
  for (const seg of ns) {
    if (typeof seg !== "string") continue;
    const segName = stageNameFromNsSegment(seg);
    if (segName) return segName;
    const direct = toolCallToSubagent.get(seg);
    if (direct) return direct;
    if (seg.startsWith("tools:")) {
      const callId = seg.slice("tools:".length);
      const name = toolCallToSubagent.get(callId);
      if (name) return name;
    }
  }
  return ORCHESTRATOR;
}

interface UnpackedChunk {
  eventType: string | null;
  ns: string[];
  data: unknown;
}

/**
 * Return `{ eventType, ns, data }` for any supported chunk shape.
 *
 * Supported shapes:
 *   - 3-tuple `[ns, mode, data]` (subgraphs on)
 *   - 2-tuple `[mode, data]` (subgraphs off) → ns = []
 */
function unpackChunk(chunk: unknown): UnpackedChunk {
  if (Array.isArray(chunk)) {
    if (chunk.length === 3) {
      const [nsValue, mode, data] = chunk as [unknown, unknown, unknown];
      const ns = Array.isArray(nsValue) ? (nsValue as string[]) : [];
      return { eventType: typeof mode === "string" ? mode : null, ns, data };
    }
    if (chunk.length === 2) {
      const [mode, data] = chunk as [unknown, unknown];
      return { eventType: typeof mode === "string" ? mode : null, ns: [], data };
    }
  }
  return { eventType: null, ns: [], data: null };
}

/** Reduce a LangChain message `content` field to a plain string. */
function flattenContent(content: unknown): string {
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
  return "";
}

function stableStringify(value: unknown): string {
  return JSON.stringify(value, (_key, val) => {
    if (val && typeof val === "object" && !Array.isArray(val)) {
      const sorted: Record<string, unknown> = {};
      for (const k of Object.keys(val as object).sort()) {
        sorted[k] = (val as Record<string, unknown>)[k];
      }
      return sorted;
    }
    return val;
  });
}

/**
 * Detect if a tool call is reading a SKILL.md file.
 * Returns the skill name if detected, else null.
 */
function detectSkillFromTool(toolName: string, toolArgs: Record<string, unknown>): string | null {
  if (["read_file", "cat", "read"].includes(toolName)) {
    const path = String(toolArgs.path ?? toolArgs.file_path ?? "");
    if (path.includes("SKILL.md")) {
      const parts = path.replace(/\\/g, "/").split("/");
      const idx = parts.indexOf("SKILL.md");
      if (idx > 0) return parts[idx - 1]!;
    }
  }
  return null;
}

interface MessageLike {
  content?: unknown;
  reasoning_content?: unknown;
  additional_kwargs?: Record<string, unknown>;
  tool_call_id?: string;
  tool_calls?: { name?: string; args?: Record<string, unknown>; id?: string }[];
  tool_call_chunks?: unknown[];
  name?: string;
  status?: string;
}

/**
 * Stateful translator from LangGraph subgraph events → StreamEvents.
 *
 * One instance per agent turn. Holds the `tool_call_id → subagent_name`
 * mapping populated as `task` calls are observed, and tracks the active
 * fixed stage via namespace transitions so STAGE_START / STAGE_COMPLETE
 * events are emitted for native StateGraph pipelines.
 */
export class EventTranslator {
  private readonly conv: string;
  private readonly turn: string;
  private readonly toolCallToSubagent = new Map<string, string>();
  private activeStage: string | null = null;

  constructor(conversationId: string, turnId: string) {
    this.conv = conversationId;
    this.turn = turnId;
  }

  /** Normalize one subgraph-stream chunk into StreamEvents. */
  translate(chunk: unknown): StreamEvent[] {
    const { eventType, ns, data } = unpackChunk(chunk);
    if (eventType === null) return [];

    const lifecycleEvents = eventType === "custom" ? [] : this.checkStageTransition(ns);

    if (eventType === "messages") {
      const evt = this.onMessage(data, ns);
      if (evt !== null) lifecycleEvents.push(evt);
      return lifecycleEvents;
    }
    if (eventType === "updates") {
      const payloadEvents = this.onUpdates(data, ns);
      if (ns.length === 0) {
        payloadEvents.push(...this.detectNodeCompletion(data));
      }
      return [...lifecycleEvents, ...payloadEvents];
    }
    if (eventType === "custom") {
      return [...lifecycleEvents, ...this.onCustom(data, ns)];
    }
    return lifecycleEvents;
  }

  // -- fixed workflow stage lifecycle --

  private checkStageTransition(ns: string[]): StreamEvent[] {
    if (!ns || ns.length === 0) return [];
    const first = stageNameFromNsSegment(ns[0]);
    if (!KNOWN_WORKFLOW_NODES.has(first)) return [];
    if (first === this.activeStage) return [];

    const events: StreamEvent[] = [];
    if (this.activeStage !== null) {
      events.push(
        new StreamEvent({
          type: StreamEventType.STAGE_COMPLETE,
          conversationId: this.conv,
          turnId: this.turn,
          payload: { stage: this.activeStage, node_kind: workflowNodeKind(this.activeStage), result: "" },
          timestamp: nowSeconds(),
        }),
      );
    }
    this.activeStage = first;
    events.push(
      new StreamEvent({
        type: StreamEventType.STAGE_START,
        conversationId: this.conv,
        turnId: this.turn,
        payload: { stage: first, node_kind: workflowNodeKind(first), description: `Running ${first} ${workflowNodeKind(first)}` },
        timestamp: nowSeconds(),
      }),
    );
    return events;
  }

  private detectNodeCompletion(data: unknown): StreamEvent[] {
    if (!data || typeof data !== "object") return [];
    const events: StreamEvent[] = [];
    for (const nodeName of Object.keys(data as Record<string, unknown>)) {
      if (KNOWN_WORKFLOW_NODES.has(nodeName) && this.activeStage === nodeName) {
        this.activeStage = null;
        events.push(
          new StreamEvent({
            type: StreamEventType.STAGE_COMPLETE,
            conversationId: this.conv,
            turnId: this.turn,
            payload: { stage: nodeName, node_kind: workflowNodeKind(nodeName), result: "" },
            timestamp: nowSeconds(),
          }),
        );
      }
    }
    return events;
  }

  // -- mode = "messages" --

  private onMessage(data: unknown, ns: string[]): StreamEvent | null {
    if (!Array.isArray(data) || data.length < 2) return null;
    const msg = data[0] as MessageLike;

    // ToolMessage (a tool result) — suppress; the "updates" mode delivers a
    // richer event with the tool name attached.
    if (msg.tool_call_id) return null;

    // AIMessage carrying tool-call chunks — suppress; tool starts come from
    // the "updates" path.
    if ((msg.tool_calls && msg.tool_calls.length) || (msg.tool_call_chunks && msg.tool_call_chunks.length)) {
      return null;
    }

    const content = flattenContent(msg.content);
    const reasoning =
      typeof msg.reasoning_content === "string"
        ? msg.reasoning_content
        : typeof msg.additional_kwargs?.reasoning_content === "string"
          ? msg.additional_kwargs.reasoning_content
          : "";
    if (!content && !reasoning) return null;

    return new StreamEvent({
      type: StreamEventType.TOKEN,
      conversationId: this.conv,
      turnId: this.turn,
      payload: {
        content,
        reasoning_content: reasoning,
        subagent: resolveSourceFromNs(ns, this.toolCallToSubagent),
      },
      timestamp: nowSeconds(),
    });
  }

  // -- mode = "updates" --

  private onUpdates(data: unknown, ns: string[]): StreamEvent[] {
    if (!data || typeof data !== "object") return [];
    const events: StreamEvent[] = [];
    const source = resolveSourceFromNs(ns, this.toolCallToSubagent);

    for (const [nodeName, stateDelta] of Object.entries(data as Record<string, unknown>)) {
      if (!stateDelta || typeof stateDelta !== "object") continue;
      const messages = (stateDelta as { messages?: MessageLike[] }).messages;
      if (!messages || messages.length === 0) continue;

      if (nodeName === "agent" || nodeName === "model" || nodeName === "model_request") {
        events.push(...this.emitToolStarts(messages, source));
      } else if (nodeName === "tools") {
        events.push(...this.emitToolResults(messages, source));
      }
    }
    return events;
  }

  private emitToolStarts(messages: MessageLike[], source: string): StreamEvent[] {
    const events: StreamEvent[] = [];
    for (const msg of messages) {
      const toolCalls = msg.tool_calls;
      if (!toolCalls || toolCalls.length === 0) continue;
      for (const tc of toolCalls) {
        const toolName = tc.name ?? "";
        const toolArgs = tc.args ?? {};
        const toolCallId = tc.id ?? "";

        events.push(
          new StreamEvent({
            type: StreamEventType.TOOL_START,
            conversationId: this.conv,
            turnId: this.turn,
            payload: {
              tool_name: toolName,
              tool_call_id: toolCallId,
              args_json: stableStringify(toolArgs),
              args: toolArgs,
              subagent: source,
            },
            timestamp: nowSeconds(),
          }),
        );

        const skillName = detectSkillFromTool(toolName, toolArgs);
        if (skillName) {
          events.push(
            new StreamEvent({
              type: StreamEventType.SKILL_TRIGGERED,
              conversationId: this.conv,
              turnId: this.turn,
              payload: { skill_name: skillName, event: "skill_read", subagent: source, detail: "" },
              timestamp: nowSeconds(),
            }),
          );
        }

        if ((toolName === "task" || toolName === "delegate_task") && toolArgs && typeof toolArgs === "object") {
          const subagentType =
            toolName === "delegate_task"
              ? (toolArgs as Record<string, unknown>).subagent_name as string | undefined
              : (toolArgs as Record<string, unknown>).subagent_type as string | undefined;
          if (subagentType && toolCallId) {
            this.toolCallToSubagent.set(toolCallId, subagentType);
          }
          if (subagentType) {
            const description =
              toolName === "delegate_task"
                ? String((toolArgs as Record<string, unknown>).task ?? "")
                : String((toolArgs as Record<string, unknown>).description ?? "");
            events.push(
              new StreamEvent({
                type: StreamEventType.SUBAGENT_START,
                conversationId: this.conv,
                turnId: this.turn,
                payload: {
                  subagent: subagentType,
                  description,
                  tool_call_id: toolCallId,
                },
                timestamp: nowSeconds(),
              }),
            );
          }
        }
      }
    }
    return events;
  }

  private emitToolResults(messages: MessageLike[], source: string): StreamEvent[] {
    const events: StreamEvent[] = [];
    for (const msg of messages) {
      if (msg.name === undefined || msg.tool_call_id === undefined) continue;
      const toolName = msg.name ?? "";
      const toolCallId = msg.tool_call_id ?? "";
      const content = typeof msg.content === "string" ? msg.content : String(msg.content);
      const isError = msg.status === "error";

      events.push(
        new StreamEvent({
          type: isError ? StreamEventType.TOOL_ERROR : StreamEventType.TOOL_RESULT,
          conversationId: this.conv,
          turnId: this.turn,
          payload: {
            tool_name: toolName,
            tool_call_id: toolCallId,
            result_summary: content.slice(0, MAX_TOOL_RESULT_CHARS),
            result: content.slice(0, MAX_TOOL_RESULT_CHARS),
            subagent: source,
            ...(isError ? { error_text: content, error: content } : {}),
          },
          timestamp: nowSeconds(),
        }),
      );

      if (toolName === "task" || toolName === "delegate_task") {
        const finished = this.toolCallToSubagent.get(toolCallId) ?? "";
        this.toolCallToSubagent.delete(toolCallId);
        events.push(
          new StreamEvent({
            type: isError ? StreamEventType.SUBAGENT_ERROR : StreamEventType.SUBAGENT_COMPLETE,
            conversationId: this.conv,
            turnId: this.turn,
            payload: {
              subagent: finished,
              tool_call_id: toolCallId,
              result_summary: content.slice(0, MAX_TOOL_RESULT_CHARS),
              result: content.slice(0, MAX_TOOL_RESULT_CHARS),
              ...(isError ? { error_text: content, error: content } : {}),
            },
            timestamp: nowSeconds(),
          }),
        );
      }
    }
    return events;
  }

  // -- mode = "custom" — skill events + user-defined signals --

  private onCustom(data: unknown, ns: string[]): StreamEvent[] {
    if (!data || typeof data !== "object") return [];
    const obj = data as Record<string, unknown>;
    const source = resolveSourceFromNs(ns, this.toolCallToSubagent);
    const eventSubtype = String(obj.type ?? "");

    if (eventSubtype === "subagent_start") {
      const stageName = String(obj.name ?? "");
      if (stageName && KNOWN_WORKFLOW_NODES.has(stageName)) {
        const events: StreamEvent[] = [];
        if (this.activeStage !== null && this.activeStage !== stageName) {
          events.push(
            new StreamEvent({
              type: StreamEventType.STAGE_COMPLETE,
              conversationId: this.conv,
              turnId: this.turn,
              payload: { stage: this.activeStage, node_kind: workflowNodeKind(this.activeStage), result: "" },
              timestamp: nowSeconds(),
            }),
          );
        }
        this.activeStage = stageName;
        events.push(
          new StreamEvent({
            type: StreamEventType.STAGE_START,
            conversationId: this.conv,
            turnId: this.turn,
            payload: {
              stage: stageName,
              node_kind: workflowNodeKind(stageName),
              description: String(obj.description ?? `Running ${stageName} ${workflowNodeKind(stageName)}`),
            },
            timestamp: nowSeconds(),
          }),
        );
        return events;
      }
      if (stageName) {
        return [
          new StreamEvent({
            type: StreamEventType.SUBAGENT_START,
            conversationId: this.conv,
            turnId: this.turn,
            payload: {
              subagent: stageName,
              description: String(obj.description ?? ""),
              tool_call_id: String(obj.tool_call_id ?? ""),
            },
            timestamp: nowSeconds(),
          }),
        ];
      }
    }

    if (eventSubtype === "subagent_complete") {
      const stageName = String(obj.name ?? "");
      if (stageName && KNOWN_WORKFLOW_NODES.has(stageName)) {
        if (this.activeStage === stageName) this.activeStage = null;
        return [
          new StreamEvent({
            type: StreamEventType.STAGE_COMPLETE,
            conversationId: this.conv,
            turnId: this.turn,
            payload: { stage: stageName, node_kind: workflowNodeKind(stageName), result: "" },
            timestamp: nowSeconds(),
          }),
        ];
      }
      if (stageName) {
        return [
          new StreamEvent({
            type: StreamEventType.SUBAGENT_COMPLETE,
            conversationId: this.conv,
            turnId: this.turn,
            payload: {
              subagent: stageName,
              tool_call_id: String(obj.tool_call_id ?? ""),
              result: String(obj.result ?? ""),
              result_summary: String(obj.result_summary ?? obj.result ?? ""),
            },
            timestamp: nowSeconds(),
          }),
        ];
      }
    }

    if (eventSubtype === "audit_route") {
      return [
        new StreamEvent({
          type: StreamEventType.CUSTOM_PROGRESS,
          conversationId: this.conv,
          turnId: this.turn,
          payload: { data: obj, subagent: source },
          timestamp: nowSeconds(),
        }),
      ];
    }

    if (eventSubtype === "token") {
      const content = String(obj.content ?? "");
      const subagent = (obj.subagent as string) ?? source;
      if (content) {
        return [
          new StreamEvent({
            type: StreamEventType.TOKEN,
            conversationId: this.conv,
            turnId: this.turn,
            payload: { content, subagent },
            timestamp: nowSeconds(),
          }),
        ];
      }
      return [];
    }

    if (eventSubtype === "tool_call") {
      return [
        new StreamEvent({
          type: StreamEventType.TOOL_START,
          conversationId: this.conv,
          turnId: this.turn,
          payload: {
            tool_name: String(obj.tool_name ?? ""),
            tool_call_id: String(obj.tool_call_id ?? ""),
            args_json: stableStringify(obj.args ?? {}),
            args: obj.args ?? {},
            subagent: (obj.subagent as string) ?? source,
          },
          timestamp: nowSeconds(),
        }),
      ];
    }

    const skillName = String(obj.skill ?? obj.name ?? "");

    if ((eventSubtype === "skill_matched" || eventSubtype === "skill_loaded") && skillName) {
      return [
        new StreamEvent({
          type: StreamEventType.SKILL_TRIGGERED,
          conversationId: this.conv,
          turnId: this.turn,
          payload: { skill_name: skillName, event: eventSubtype, subagent: source, detail: String(obj.description ?? "") },
          timestamp: nowSeconds(),
        }),
      ];
    }

    const status = obj.status;
    if (skillName && (status === "loaded" || status === "matched")) {
      return [
        new StreamEvent({
          type: StreamEventType.SKILL_TRIGGERED,
          conversationId: this.conv,
          turnId: this.turn,
          payload: { skill_name: skillName, event: `skill_${status}`, subagent: source, detail: String(obj.description ?? "") },
          timestamp: nowSeconds(),
        }),
      ];
    }

    if ("progress" in obj || "status" in obj) {
      return [
        new StreamEvent({
          type: StreamEventType.CUSTOM_PROGRESS,
          conversationId: this.conv,
          turnId: this.turn,
          payload: { data: obj, subagent: source },
          timestamp: nowSeconds(),
        }),
      ];
    }

    return [];
  }
}

// ---------------------------------------------------------------------------
// Run-lifecycle helpers
// ---------------------------------------------------------------------------

export function makeRunStartedEvent(conversationId: string, turnId: string): StreamEvent {
  return new StreamEvent({
    type: StreamEventType.RUN_STARTED,
    conversationId,
    turnId,
    payload: {},
    timestamp: nowSeconds(),
  });
}

export function makeRunCompletedEvent(
  conversationId: string,
  turnId: string,
  assistantContent = "",
): StreamEvent {
  return new StreamEvent({
    type: StreamEventType.RUN_COMPLETED,
    conversationId,
    turnId,
    payload: { assistant_message: assistantContent },
    timestamp: nowSeconds(),
  });
}

export function makeRunFailedEvent(
  conversationId: string,
  turnId: string,
  error: string,
  partialContent = "",
): StreamEvent {
  return new StreamEvent({
    type: StreamEventType.RUN_FAILED,
    conversationId,
    turnId,
    payload: { error, partial_message: partialContent },
    timestamp: nowSeconds(),
  });
}
