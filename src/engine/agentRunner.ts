/**
 * Agent construction and streaming execution for Ruflo and audit turns.
 *
 * For audit-mode runs, uses LangGraph subgraph streaming (`subgraphs: true`)
 * so that every token / tool call / result is attributable to either the
 * orchestrator or a named subagent. The EventTranslator resolves namespace
 * tuples into subagent names and emits StreamEvents with a `subagent` field.
 *
 * For Ruflo, uses a primary LangGraph ReAct agent with controlled delegation.
 */

import { HumanMessage } from "@langchain/core/messages";
import type { BaseMessage } from "@langchain/core/messages";

import { AgentFactory } from "@/engine/agentFactory";
import type { McpServerDTO, ModelProviderDTO } from "@/engine/dto";
import { AgentRunError } from "@/engine/errors";
import { McpClientPool } from "@/engine/mcpPool";
import {
  type AgentRunConfig,
  ConversationMessage,
  makeAgentRunConfig,
  ResolvedSkill,
  StreamEvent,
} from "@/engine/models";
import { RagConfig } from "@/config";
import { EventTranslator } from "@/engine/streaming";
import { StreamEventType } from "@/engine/enums";

type MaybePromise<T> = T | Promise<T>;
type StreamableAgent = {
  stream?: (...args: unknown[]) => MaybePromise<AsyncIterable<unknown>>;
};

export interface AgentRunnerOptions {
  factory: AgentFactory;
  pool: McpClientPool;
  provider: ModelProviderDTO;
  enabledServers: McpServerDTO[];
  skill: ResolvedSkill | null;
  history: ConversationMessage[];
  systemPrompt: string;
  conversationId: string;
  turnId: string;
  mode?: string;
  subagentProviders?: Record<string, ModelProviderDTO>;
  subagentMcpAllow?: Record<string, string[] | null>;
  subagentSkills?: Record<string, ResolvedSkill | null>;
  rag?: RagConfig | null;
}

/** Build a LangGraph agent, run it with streaming, and yield events. */
export class AgentRunner {
  assistantContent = "";
  reasoningContent = "";
  toolCalls: StreamEvent[] = [];
  runConfig: AgentRunConfig | null = null;
  /** Latest `stage_outputs` seen on the outer graph stream (audit modes). */
  private stageOutputs: Record<string, string> = {};

  /**
   * The content to persist/display for this turn.
   *
   * For audit / audit-slim the orchestrator emits no tokens of its own; each
   * stage's text lands in `stage_outputs`. The user-facing answer is the
   * `report` stage (falling back to the last stage that produced output), not
   * the concatenation of every stage's streamed tokens. For Ruflo there are no
   * stage outputs, so this is just the accumulated assistant tokens.
   */
  get finalContent(): string {
    const report = this.stageOutputs.report;
    if (typeof report === "string" && report.trim()) return report;
    const stages = Object.values(this.stageOutputs).filter((v) => v && v.trim());
    if (stages.length) return stages[stages.length - 1]!;
    return this.assistantContent;
  }

  private readonly opts: Required<
    Omit<AgentRunnerOptions, "rag">
  > & { rag: RagConfig };

  constructor(options: AgentRunnerOptions) {
    this.opts = {
      factory: options.factory,
      pool: options.pool,
      provider: options.provider,
      enabledServers: options.enabledServers,
      skill: options.skill,
      history: options.history,
      systemPrompt: options.systemPrompt,
      conversationId: options.conversationId,
      turnId: options.turnId,
      mode: options.mode ?? "audit",
      subagentProviders: options.subagentProviders ?? {},
      subagentMcpAllow: options.subagentMcpAllow ?? {},
      subagentSkills: options.subagentSkills ?? {},
      rag: options.rag ?? new RagConfig(),
    };
  }

  async *run(message: string): AsyncIterableIterator<StreamEvent> {
    const o = this.opts;
    this.runConfig = makeAgentRunConfig({
      conversationId: o.conversationId,
      provider: o.provider,
      skill: o.skill,
      enabledServers: o.enabledServers,
      messageHistory: o.history,
      userMessage: message,
      systemPrompt: o.systemPrompt,
      mode: o.mode,
      subagentProviders: o.subagentProviders,
      subagentMcpAllow: o.subagentMcpAllow,
      subagentSkills: o.subagentSkills,
      rag: o.rag,
    });

    const [agent] = await o.factory.build(this.runConfig);
    const inputMessages = AgentRunner.buildInputMessages(o.history, message);
    const graphInput = AgentRunner.buildGraphInput(inputMessages, message, o.mode);

    const translator = new EventTranslator(o.conversationId, o.turnId);

    const streamFn = (agent as StreamableAgent).stream;
    if (typeof streamFn !== "function") {
      throw new AgentRunError("Compiled agent does not expose a stream() method.", true);
    }

    let stream: AsyncIterable<unknown>;
    try {
      stream = await streamFn.call(agent, graphInput, {
        streamMode: ["messages", "updates", "custom"],
        subgraphs: true,
        recursionLimit: this.runConfig.maxSteps,
        configurable: { thread_id: o.conversationId },
      });
      if (!stream || typeof stream[Symbol.asyncIterator] !== "function") {
        throw new Error("Compiled agent stream() did not return an AsyncIterable.");
      }
    } catch (exc) {
      throw new AgentRunError(String(exc instanceof Error ? exc.message : exc), true);
    }

    try {
      for await (const chunk of stream) {
        this.accumulateReasoning(chunk);
        this.captureStageOutputs(chunk);
        for (const streamEvent of translator.translate(chunk)) {
          this.accumulateEvent(streamEvent);
          yield streamEvent;
        }
      }
    } catch (exc) {
      if (exc instanceof AgentRunError) throw exc;
      throw new AgentRunError(String(exc instanceof Error ? exc.message : exc), true);
    }
  }

  /**
   * Capture `stage_outputs` from outer-namespace update chunks (audit modes).
   * The outer stream emits `[[], "updates", { <node>: { stage_outputs } }]` as
   * each subagent node returns; we keep the latest merged view.
   */
  private captureStageOutputs(chunk: unknown): void {
    if (!Array.isArray(chunk)) return;
    const ns = chunk.length === 3 ? chunk[0] : [];
    const mode = chunk.length === 3 ? chunk[1] : chunk.length === 2 ? chunk[0] : null;
    const data = chunk.length === 3 ? chunk[2] : chunk.length === 2 ? chunk[1] : null;
    // Only outer-namespace updates carry the merged node return values.
    if (mode !== "updates" || (Array.isArray(ns) && ns.length !== 0)) return;
    if (!data || typeof data !== "object") return;
    for (const delta of Object.values(data as Record<string, unknown>)) {
      const so =
        delta && typeof delta === "object"
          ? (delta as { stage_outputs?: unknown }).stage_outputs
          : undefined;
      if (so && typeof so === "object") {
        for (const [k, v] of Object.entries(so as Record<string, unknown>)) {
          if (typeof v === "string") this.stageOutputs[k] = v;
        }
      }
    }
  }

  private accumulateReasoning(chunk: unknown): void {
    if (!Array.isArray(chunk)) return;
    // [ns, mode, data] (subgraphs on) or [mode, data].
    const mode = chunk.length === 3 ? chunk[1] : chunk.length === 2 ? chunk[0] : null;
    const data = chunk.length === 3 ? chunk[2] : chunk.length === 2 ? chunk[1] : null;
    if (mode !== "messages") return;
    if (!Array.isArray(data) || data.length < 2) return;
    const msg = data[0] as
      | { reasoning_content?: unknown; additional_kwargs?: Record<string, unknown> }
      | null
      | undefined;
    if (!msg) return;
    let reasoning = msg.reasoning_content;
    if (!reasoning && msg.additional_kwargs) {
      reasoning = msg.additional_kwargs.reasoning_content;
    }
    if (typeof reasoning === "string" && reasoning) {
      this.reasoningContent += reasoning;
    }
  }

  private accumulateEvent(streamEvent: StreamEvent): void {
    if (streamEvent.type === StreamEventType.TOKEN) {
      let chunk = streamEvent.payload.content as unknown;
      if (Array.isArray(chunk)) {
        const parts: string[] = [];
        for (const block of chunk) {
          if (typeof block === "string") parts.push(block);
          else if (block && typeof block === "object" && (block as { type?: string }).type === "text") {
            parts.push(String((block as { text?: string }).text ?? ""));
          }
        }
        chunk = parts.join("");
      }
      if (typeof chunk === "string" && chunk) this.assistantContent += chunk;
    } else if (streamEvent.type === StreamEventType.TOOL_START) {
      this.toolCalls.push(streamEvent);
    }
  }

  private static buildInputMessages(
    history: ConversationMessage[],
    userMessage: string,
  ): BaseMessage[] {
    const messages: BaseMessage[] = history.map((m) => m.toLangchainMessage());
    messages.push(new HumanMessage({ content: userMessage }));
    return messages;
  }

  private static buildGraphInput(
    messages: BaseMessage[],
    userMessage: string,
    mode: string,
  ): Record<string, unknown> {
    const graphInput: Record<string, unknown> = { messages };
    if (mode === "audit" || mode === "audit-slim") {
      graphInput.audit_task = userMessage;
      graphInput.stage_outputs = {};
      graphInput.gapfill_count = 0;
      graphInput.feedback_count = 0;
      graphInput.current_stage = "";
    }
    return graphInput;
  }
}
