/** LangGraph agent factory. */

import { createAgent } from "langchain";
import type { BaseChatModel } from "@langchain/core/language_models/chat_models";
import type { StructuredToolInterface } from "@langchain/core/tools";

import { AgentBuildError, ProviderNotConfiguredError } from "@/engine/errors";
import { McpClientPool } from "@/engine/mcpPool";
import { type AgentRunConfig, ResolvedSkill } from "@/engine/models";
import { ModelFactory } from "@/engine/modelFactory";
import type { ModelProviderDTO } from "@/engine/dto";
import { buildAgentMiddlewareForModel } from "@/runtime/middleware";
import { AgentRuntimeServices } from "@/runtime/services";
import { buildHttpExchangeTool, buildPacketExchangeTool } from "@/resources/networkTools";
import { buildWebSearchTool } from "@/resources/webTools";
import { buildRagSearchTool } from "@/resources/rag";
import { buildAuditGraph } from "@/workflows/auditGraph";
import { AUDIT_SUBAGENTS } from "@/workflows/auditSubagents";
import { buildAuditSlimGraph } from "@/workflows/auditSlimGraph";
import { AUDIT_SLIM_SUBAGENTS } from "@/workflows/auditSlimSubagents";
import { buildDelegateTool } from "@/workflows/ruflo";
import { createTokenEstimator } from "@/context/tokenizer";

type CompiledAgent = { stream: (...args: unknown[]) => AsyncIterable<unknown> } & Record<string, unknown>;
type BuildResult = [CompiledAgent, StructuredToolInterface[]];

function providerKey(provider: ModelProviderDTO): Record<string, unknown> {
  return {
    name: provider.name,
    model_name: provider.modelName,
    api_mode: provider.apiMode,
    api_key: provider.apiKey,
    base_url: provider.baseUrl,
    temperature: provider.temperature,
    top_p: provider.topP,
  };
}

function skillKey(skill: ResolvedSkill | null): Record<string, unknown> | null {
  if (skill === null) return null;
  return {
    id: skill.id,
    name: skill.name,
    system_prompt_suffix: skill.systemPromptSuffix,
    tool_allowlist: skill.toolAllowlist === null ? null : [...skill.toolAllowlist].sort(),
    tool_denylist: skill.toolDenylist === null ? null : [...skill.toolDenylist].sort(),
    preferred_model_name: skill.preferredModelName,
    temperature_override: skill.temperatureOverride,
  };
}

function ragKey(rag: AgentRunConfig["rag"]): Record<string, unknown> {
  return {
    embedding_backend: rag.embeddingBackend,
    embedding_model: rag.embeddingModel,
    embedding_api_base: rag.embeddingApiBase,
    embedding_api_key: rag.embeddingApiKey,
    embedding_local_path: rag.embeddingLocalPath,
    chunk_size: rag.chunkSize,
    chunk_overlap: rag.chunkOverlap,
    knowledge_bases: rag.knowledgeBases.map((kb) => ({
      name: kb.name,
      backend: kb.backend,
      docs_path: kb.docsPath,
      chroma_path: kb.chromaPath,
      chroma_url: kb.chromaUrl,
      collection_name: kb.collectionName,
      tenant: kb.tenant,
      database: kb.database,
      headers: kb.headers,
      enabled: kb.enabled,
    })),
  };
}

/** Builds a LangGraph agent from runtime configuration. */
export class AgentFactory {
  private readonly modelFactory: ModelFactory;
  private readonly runtimeServices: AgentRuntimeServices | null;
  private readonly agentCache = new Map<string, BuildResult>();
  private readonly agentCacheLimit = 8;

  constructor(
    private readonly pool: McpClientPool,
    options: {
      workspacePath?: string;
      modelFactory?: ModelFactory;
      runtimeServices?: AgentRuntimeServices | null;
    } = {},
  ) {
    this.modelFactory = options.modelFactory ?? new ModelFactory();
    this.runtimeServices = options.runtimeServices ?? null;
  }

  /** Build and return [compiledGraph, tools]. */
  async build(config: AgentRunConfig): Promise<BuildResult> {
    const provider = config.provider;
    if (!provider.modelName) {
      throw new ProviderNotConfiguredError("Model name is required for the selected provider.");
    }

    // 1. Build MCP server configs from enabled servers.
    const serverConfigs: Record<string, Record<string, unknown>> = {};
    for (const server of config.enabledServers) {
      serverConfigs[server.name] = server.toLangchainConfig();
    }

    // 2. Connect / reuse MCP client pool and get tools.
    const allTools = await this.pool.connect(serverConfigs);

    // 3. Match Python Sarma: skill allow/deny filters MCP tools, then
    // built-in local tools are appended and remain available.
    const tools = [
      ...this.applySkillFilter(allTools, config.skill),
      ...this.buildBuiltinTools(config),
    ];

    const cacheKey = this.agentCacheKey(config, serverConfigs, tools);
    const cached = this.agentCache.get(cacheKey);
    if (cached !== undefined) return cached;

    // 4. Initialize LLM.
    let model: BaseChatModel;
    try {
      model = this.modelFactory.initModel(provider, config.skill);
    } catch (exc) {
      throw new AgentBuildError(`Failed to initialize model: ${exc instanceof Error ? exc.message : exc}`);
    }

    // 5. Build agent (audit pipelines vs ruflo primary + delegation).
    let agent: CompiledAgent;
    try {
      agent = this.createAgentForMode(config, model, tools);
    } catch (exc) {
      throw new AgentBuildError(`Failed to create agent: ${exc instanceof Error ? exc.message : exc}`);
    }

    const result: BuildResult = [agent, tools];
    this.agentCache.set(cacheKey, result);
    if (this.agentCache.size > this.agentCacheLimit) {
      const firstKey = this.agentCache.keys().next().value;
      if (firstKey !== undefined) this.agentCache.delete(firstKey);
    }
    return result;
  }

  private createAgentForMode(
    config: AgentRunConfig,
    model: BaseChatModel,
    tools: StructuredToolInterface[],
  ): CompiledAgent {
    if (config.mode === "audit" || config.mode === "audit-slim") {
      const subagentModels = this.loadSubagentModels(config.subagentProviders);
      delete subagentModels.orchestrator;
      const compileKwargs = this.runtimeServices?.compileKwargs() ?? {};
      const maxPriorStageTokens = Math.max(
        12_000,
        Math.min(120_000, Math.trunc((config.provider.maxContextTokens || 128_000) * 0.35)),
      );
      const estimateText = createTokenEstimator(config.provider);

      if (config.mode === "audit-slim") {
        return buildAuditSlimGraph(model, tools, {
          systemPrompt: config.systemPrompt || "",
          subagentSpecs: AUDIT_SLIM_SUBAGENTS,
          subagentModels: Object.keys(subagentModels).length ? subagentModels : null,
          subagentMcpAllow: config.subagentMcpAllow,
          subagentSkills: config.subagentSkills,
          maxPriorStageTokens,
          estimateText,
          compileKwargs,
        }) as unknown as CompiledAgent;
      }

      return buildAuditGraph(model, tools, {
        systemPrompt: config.systemPrompt || "",
        subagentSpecs: AUDIT_SUBAGENTS,
        subagentModels: Object.keys(subagentModels).length ? subagentModels : null,
        subagentMcpAllow: config.subagentMcpAllow,
        subagentSkills: config.subagentSkills,
        maxPriorStageTokens,
        estimateText,
        compileKwargs,
      }) as unknown as CompiledAgent;
    }

    if (config.mode === "ruflo") {
      const rufloTools = [...tools, buildDelegateTool(model, tools)];
      const agentKwargs = this.runtimeServices?.createAgentKwargs() ?? {};
      return createAgent({
        model,
        tools: rufloTools,
        systemPrompt: config.systemPrompt || "",
        middleware: buildAgentMiddlewareForModel(model),
        ...agentKwargs,
      }) as unknown as CompiledAgent;
    }

    const agentKwargs = this.runtimeServices?.createAgentKwargs() ?? {};
    return createAgent({
      model,
      tools,
      systemPrompt: config.systemPrompt || "",
      middleware: buildAgentMiddlewareForModel(model),
      ...agentKwargs,
    }) as unknown as CompiledAgent;
  }

  private agentCacheKey(
    config: AgentRunConfig,
    serverConfigs: Record<string, Record<string, unknown>>,
    tools: StructuredToolInterface[],
  ): string {
    const sortedEntries = <T>(obj: Record<string, T>): [string, T][] =>
      Object.entries(obj).sort(([a], [b]) => a.localeCompare(b));

    const data = {
      mode: config.mode,
      provider: providerKey(config.provider),
      skill: skillKey(config.skill),
      servers: serverConfigs,
      tools: tools.map((t) => t.name ?? String(t)),
      system_prompt: config.systemPrompt || "",
      subagent_providers: Object.fromEntries(
        sortedEntries(config.subagentProviders).map(([name, p]) => [name, providerKey(p)]),
      ),
      subagent_mcp_allow: Object.fromEntries(
        sortedEntries(config.subagentMcpAllow).map(([name, allow]) => [
          name,
          allow === null ? null : [...allow].sort(),
        ]),
      ),
      subagent_skills: Object.fromEntries(
        sortedEntries(config.subagentSkills).map(([name, skill]) => [name, skillKey(skill)]),
      ),
      rag: ragKey(config.rag),
    };
    return stableStringify(data);
  }

  private applySkillFilter(
    tools: StructuredToolInterface[],
    skill: ResolvedSkill | null,
  ): StructuredToolInterface[] {
    if (skill === null) return [...tools];
    return [...this.pool.filterTools(tools, skill.toolAllowlist, skill.toolDenylist)];
  }

  private loadSubagentModels(
    providers: Record<string, ModelProviderDTO>,
  ): Record<string, BaseChatModel> {
    const models: Record<string, BaseChatModel> = {};
    for (const [name, provider] of Object.entries(providers)) {
      models[name] = this.modelFactory.initModel(provider, null);
    }
    return models;
  }

  private buildBuiltinTools(config: AgentRunConfig): StructuredToolInterface[] {
    const tools: StructuredToolInterface[] = [
      buildWebSearchTool(),
      buildHttpExchangeTool(),
      buildPacketExchangeTool(),
    ];
    if (config.rag.knowledgeBases.some((kb) => kb.enabled && kb.name)) {
      tools.push(buildRagSearchTool(config.rag));
    }
    return tools;
  }
}

/** Deterministic JSON stringify with sorted object keys (matches Python sort_keys). */
function stableStringify(value: unknown): string {
  return JSON.stringify(sortKeys(value));
}

function sortKeys(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(sortKeys);
  if (value && typeof value === "object") {
    const out: Record<string, unknown> = {};
    for (const key of Object.keys(value as Record<string, unknown>).sort()) {
      out[key] = sortKeys((value as Record<string, unknown>)[key]);
    }
    return out;
  }
  return value;
}
