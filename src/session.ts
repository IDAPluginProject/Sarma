/**
 * Session lifecycle — wraps the agent runtime for CLI use.
 *
 * Workflow-aware: reads the current workflow on each turn to determine
 * execution mode (ruflo vs audit pipeline). Switching the workflow takes
 * effect on the next turn — no session restart needed.
 */

import { randomUUID } from "node:crypto";
import { SystemMessage, HumanMessage } from "@langchain/core/messages";

import { AgentFactory } from "@/engine/agentFactory";
import { AgentRunner } from "@/engine/agentRunner";
import { McpClientPool } from "@/engine/mcpPool";
import { ConversationMessage, StreamEvent } from "@/engine/models";
import { ModelFactory } from "@/engine/modelFactory";
import { ModelProviderDTO } from "@/engine/dto";
import { StreamEventType } from "@/engine/enums";
import {
  makeRunCompletedEvent,
  makeRunFailedEvent,
  makeRunStartedEvent,
} from "@/engine/streaming";
import {
  STRUCTURED_MEMORY_PROMPT,
  ContextCompactor,
  ContextWindowPolicy,
  estimateStaticPromptTokens,
} from "@/context/compaction";
import { createTokenEstimator } from "@/context/tokenizer";
import { type CliConfig, type ProviderConfig } from "@/config";
import { RuntimePolicyResolver } from "@/runtime/resolver";
import { AgentRuntimeServices } from "@/runtime/services";
import { Store } from "@/store";
import { defaultWorkflowName, getWorkflowMeta } from "@/workflows";

export interface GraphState {
  current_stage: string;
  completed: Set<string>;
  failed: string | null;
  gapfill_loops: number;
  feedback_loops: number;
}

function uid(): string {
  return randomUUID().replace(/-/g, "").slice(0, 12);
}

/** Manages a conversation with the LangGraph agent pipeline. */
export class Session {
  private pool: McpClientPool;
  private modelFactory: ModelFactory;
  private runtimeServices: AgentRuntimeServices;
  private factory: AgentFactory;
  private resolver: RuntimePolicyResolver;
  private _conversationId = "";
  private _history: ConversationMessage[] = [];
  private _graphState: GraphState = Session.freshGraphState();
  private readonly compactTriggerRatio = 0.9;
  private readonly compactTargetRatio = 0.55;
  private currentWorkflow: string = defaultWorkflowName();
  private currentRunAbort: AbortController | null = null;

  constructor(
    private readonly config: CliConfig,
    private readonly store: Store,
  ) {
    this.pool = new McpClientPool();
    this.modelFactory = new ModelFactory();
    this.runtimeServices = AgentRuntimeServices.create();
    this.factory = new AgentFactory(this.pool, {
      modelFactory: this.modelFactory,
      runtimeServices: this.runtimeServices,
    });
    this.resolver = new RuntimePolicyResolver(config);
  }

  private static freshGraphState(): GraphState {
    return {
      current_stage: "",
      completed: new Set(),
      failed: null,
      gapfill_loops: 0,
      feedback_loops: 0,
    };
  }

  get graphState(): GraphState {
    return {
      ...this._graphState,
      completed: new Set(this._graphState.completed),
    };
  }

  get conversationId(): string {
    return this._conversationId;
  }

  get poolRef(): McpClientPool {
    return this.pool;
  }

  get toolCount(): number {
    return this.pool.tools.length;
  }

  /** Set the active workflow that the next turn will run. */
  setWorkflow(name: string): void {
    if (!getWorkflowMeta(name)) {
      throw new Error(`Unknown workflow: ${name}`);
    }
    this.currentWorkflow = name;
  }

  get workflow(): string {
    return this.currentWorkflow;
  }

  /** Connect the runtime MCP pool for the given workflow without building an agent. */
  async ensureMcpConnected(workflow: string): Promise<void> {
    const runPlan = this.resolver.resolve(workflow);
    await this.pool.connect(Session.serverConfigsFor(runPlan.enabledServers));
  }

  /** Rebuild runtime resources while preserving conversation history. */
  async restartRuntime(): Promise<void> {
    this.cancelCurrentRun();
    await this.pool.disconnect();
    this.pool = new McpClientPool();
    this.modelFactory = new ModelFactory();
    this.runtimeServices = AgentRuntimeServices.create();
    this.factory = new AgentFactory(this.pool, {
      modelFactory: this.modelFactory,
      runtimeServices: this.runtimeServices,
    });
    this.resolver = new RuntimePolicyResolver(this.config);
    this.resetGraphState();
  }

  cancelCurrentRun(): boolean {
    const controller = this.currentRunAbort;
    if (!controller || controller.signal.aborted) return false;
    controller.abort();
    return true;
  }

  newConversation(title = ""): string {
    const mode = this.currentWorkflow;
    const provider = this.resolver.providerFor(mode || "ruflo");
    const titledMode = mode.charAt(0).toUpperCase() + mode.slice(1);
    this._conversationId = this.store.createConversation(
      title || `${titledMode} session`,
      provider.modelName,
    );
    this._history = [];
    this.resetGraphState();
    return this._conversationId;
  }

  resumeConversation(cid: string): boolean {
    const messages = this.store.loadMessages(cid);
    if (messages.length === 0) return false;
    this._conversationId = cid;
    this._history = messages.map(
      (m) =>
        new ConversationMessage({
          id: m.id,
          conversationId: cid,
          turnId: m.turn_id,
          role: m.role,
          content: m.content,
          reasoningContent: m.reasoning ?? null,
        }),
    );
    return true;
  }

  /** Compact history into structured memory near the context limit. */
  async compactContext(
    options: { force?: boolean; workflow?: string; upcomingText?: string; systemPrompt?: string } = {},
  ): Promise<boolean> {
    const workflow = options.workflow ?? "ruflo";
    const compactor = this.compactorForWorkflow(workflow, options.systemPrompt ?? "");
    const [changed, newHistory, memory] = await compactor.compact(
      this._history,
      (messages) => this.summarizeMessages(messages, workflow),
      {
        conversationId: this._conversationId,
        upcomingText: options.upcomingText ?? "",
        force: options.force ?? true,
      },
    );
    if (!changed) return false;

    const sourceCount = this._history.length - (newHistory.length - 1);
    this._history = newHistory;
    if (this._conversationId) {
      this.store.saveMemoryArtifact(this._conversationId, memory, "structured_context", Math.max(sourceCount, 0));
      this.store.replaceMessages(
        this._conversationId,
        this._history.map((m) => ({
          id: m.id ?? undefined,
          turn_id: m.turnId,
          role: m.role,
          content: m.content,
          reasoning_content: m.reasoningContent ?? null,
          created_at: m.createdAt ?? undefined,
        })),
      );
    }
    return true;
  }

  /** Execute one turn, yielding StreamEvents. */
  async *runTurn(userMessage: string): AsyncIterableIterator<StreamEvent> {
    const mode = this.currentWorkflow || "ruflo";
    if (!getWorkflowMeta(mode)) {
      throw new Error(`Unknown workflow: ${mode}`);
    }
    if (!this._conversationId) {
      this.newConversation(userMessage.slice(0, 60));
    }

    const turnId = uid();
    const runPlan = this.resolver.resolve(mode);
    const toolExecutionIds = new Map<string, string>();
    const abortController = new AbortController();
    this.currentRunAbort = abortController;

    yield makeRunStartedEvent(this._conversationId, turnId);

    try {
      if (abortController.signal.aborted) throw new Error("Run cancelled.");
      await this.pool.connect(Session.serverConfigsFor(runPlan.enabledServers));
      if (abortController.signal.aborted) throw new Error("Run cancelled.");

      await this.compactContext({
        force: false,
        workflow: mode,
        upcomingText: userMessage,
        systemPrompt: runPlan.systemPrompt,
      });

      const runnerHistory = [...this._history];

      // Persist user message.
      this.store.saveMessage(this._conversationId, turnId, "user", userMessage);
      this._history.push(
        new ConversationMessage({
          role: "user",
          content: userMessage,
          conversationId: this._conversationId,
          turnId,
        }),
      );

      const runner = new AgentRunner({
        factory: this.factory,
        pool: this.pool,
        provider: runPlan.provider,
        enabledServers: runPlan.enabledServers,
        skill: runPlan.skill,
        history: runnerHistory,
        systemPrompt: runPlan.systemPrompt,
        conversationId: this._conversationId,
        turnId,
        mode,
        subagentProviders: runPlan.subagentProviders,
        subagentMcpAllow: runPlan.subagentMcpAllow,
        subagentSkills: runPlan.subagentSkills,
        rag: runPlan.rag,
        abortSignal: abortController.signal,
      });

      for await (const event of runner.run(userMessage)) {
        if (abortController.signal.aborted) throw new Error("Run cancelled.");
        this.persistToolEvent(event, toolExecutionIds);
        if (mode === "audit" || mode === "audit-slim") {
          this.trackGraphProgress(event);
        }
        yield event;
      }

      // Persist assistant response. For audit modes finalContent is the report
      // stage; for Ruflo it is the accumulated assistant tokens.
      const finalContent = runner.finalContent;
      if (finalContent) {
        this.store.saveMessage(
          this._conversationId,
          turnId,
          "assistant",
          finalContent,
          null,
          runner.reasoningContent || null,
        );
        this._history.push(
          new ConversationMessage({
            role: "assistant",
            content: finalContent,
            conversationId: this._conversationId,
            turnId,
            reasoningContent: runner.reasoningContent || null,
          }),
        );
        const updateFields: Record<string, string> = { status: "idle" };
        const existing = this.store.getConversation(this._conversationId);
        if (existing && !(existing.title || "").trim()) {
          updateFields.title = userMessage.slice(0, 60) || "Untitled session";
        }
        this.store.updateConversation(this._conversationId, updateFields);
      }
      yield makeRunCompletedEvent(this._conversationId, turnId, finalContent);
    } catch (exc) {
      const message = abortController.signal.aborted ? "Run cancelled." : exc instanceof Error ? exc.message : String(exc);
      yield makeRunFailedEvent(this._conversationId, turnId, message);
    } finally {
      if (this.currentRunAbort === abortController) this.currentRunAbort = null;
    }
  }

  private resetGraphState(): void {
    this._graphState = Session.freshGraphState();
  }

  private contextBudget(workflow: string): number {
    const provider = this.resolver.providerFor(workflow);
    return Math.max(Math.trunc(provider.maxContextTokens || 128_000), 1);
  }

  private compactorForWorkflow(workflow: string, systemPrompt = ""): ContextCompactor {
    const provider = this.resolver.providerFor(workflow);
    const estimateText = createTokenEstimator(provider);
    return new ContextCompactor(
      new ContextWindowPolicy({
        maxContextTokens: Math.max(Math.trunc(provider.maxContextTokens || 128_000), 1),
        triggerRatio: this.compactTriggerRatio,
        rawTailRatio: this.compactTargetRatio,
        staticPromptTokens: estimateStaticPromptTokens(
          systemPrompt,
          this.toolCount + Session.builtinAndMiddlewareToolCount(this.resolver.resolve(workflow).rag),
          estimateText,
        ),
        tokenEstimator: estimateText,
      }),
    );
  }

  private async summarizeMessages(
    messages: ConversationMessage[],
    workflow = "ruflo",
  ): Promise<string> {
    const provider: ProviderConfig = this.resolver.providerFor(workflow);
    const model = this.modelFactory.initModel(providerToDto(provider), null);
    const transcript = messages
      .filter((m) => m.content)
      .map((m) => `${m.role.toUpperCase()}: ${m.content}`)
      .join("\n\n");
    const result = await model.invoke([
      new SystemMessage({ content: STRUCTURED_MEMORY_PROMPT }),
      new HumanMessage({ content: transcript }),
    ]);
    const content = (result as { content?: unknown }).content;
    return typeof content === "string" ? content : String(content ?? "");
  }

  private trackGraphProgress(event: StreamEvent): void {
    const etype = event.type;
    const payload = event.payload;

    if (etype === StreamEventType.STAGE_START) {
      const name = (payload.stage as string) || (payload.subagent as string) || "";
      if (name) this._graphState.current_stage = name;
    } else if (etype === StreamEventType.STAGE_COMPLETE) {
      const name = (payload.stage as string) || (payload.subagent as string) || "";
      if (name) {
        this._graphState.completed.add(name);
        if (name === this._graphState.current_stage) this._graphState.current_stage = "";
      }
    } else if (etype === StreamEventType.STAGE_ERROR) {
      const name = (payload.stage as string) || (payload.subagent as string) || "";
      if (name) this._graphState.failed = name;
    } else if (etype === StreamEventType.CUSTOM_PROGRESS) {
      const data = payload.data;
      if (data && typeof data === "object" && (data as { type?: string }).type === "audit_route") {
        const loop = (data as { loop?: string }).loop ?? "";
        const count = (data as { count?: number }).count;
        if (loop === "gapfill" && count !== undefined && count !== null) {
          this._graphState.gapfill_loops = Math.trunc(count);
        } else if (loop === "feedback" && count !== undefined && count !== null) {
          this._graphState.feedback_loops = Math.trunc(count);
        }
      }
    }
  }

  private persistToolEvent(event: StreamEvent, toolExecutionIds: Map<string, string>): void {
    if (!this._conversationId) return;
    const payload = event.payload;
    if (event.type === StreamEventType.TOOL_START) {
      const toolName = String(payload.tool_name ?? "");
      const callId = String(payload.tool_call_id ?? "");
      const argsJson = String(payload.args_json ?? JSON.stringify(payload.args ?? {}));
      const serverName = toolName.includes("__") ? toolName.split("__", 1)[0]! : "";
      const id = this.store.saveToolExecution(this._conversationId, event.turnId, toolName, argsJson, serverName);
      if (callId) toolExecutionIds.set(callId, id);
      return;
    }
    if (event.type === StreamEventType.TOOL_RESULT || event.type === StreamEventType.TOOL_ERROR) {
      const callId = String(payload.tool_call_id ?? "");
      const id = callId ? toolExecutionIds.get(callId) : undefined;
      if (!id) return;
      const isError = event.type === StreamEventType.TOOL_ERROR;
      this.store.finishToolExecution(
        id,
        isError ? "error" : "succeeded",
        isError ? null : String(payload.result_summary ?? payload.result ?? ""),
        isError ? String(payload.error_text ?? payload.error ?? "") : null,
      );
      toolExecutionIds.delete(callId);
    }
  }

  private static serverConfigsFor(servers: { name: string; toLangchainConfig(): Record<string, unknown> }[]): Record<string, Record<string, unknown>> {
    const configs: Record<string, Record<string, unknown>> = {};
    for (const server of servers) configs[server.name] = server.toLangchainConfig();
    return configs;
  }

  private static builtinAndMiddlewareToolCount(rag: { knowledgeBases: { enabled: boolean; name: string }[] }): number {
    const builtin = 3 + (rag.knowledgeBases.some((kb) => kb.enabled && kb.name) ? 1 : 0);
    const middleware = 8;
    return builtin + middleware;
  }

  async close(): Promise<void> {
    this.cancelCurrentRun();
    await this.pool.disconnect();
  }
}

function providerToDto(provider: ProviderConfig): ModelProviderDTO {
  return new ModelProviderDTO({
    id: null,
    name: provider.name,
    modelName: provider.modelName,
    apiMode: provider.apiMode,
    apiKey: provider.apiKey,
    baseUrl: provider.baseUrl,
    temperature: provider.temperature,
    topP: provider.topP,
    maxContextTokens: provider.maxContextTokens,
    enabled: provider.enabled,
  });
}
