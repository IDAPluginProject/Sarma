/**
 * TUI controller — owns the Session and projects its StreamEvents into a
 * SolidJS store the components render reactively.
 *
 * Mirrors the routing in cli/renderer.ts handleEvent, but instead of printing
 * lines it mutates a structured transcript + live status signals.
 */

import { createSignal } from "solid-js";
import { createStore, produce } from "solid-js/store";
import { HumanMessage } from "@langchain/core/messages";
import { existsSync, mkdirSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { join, resolve } from "node:path";

import {
  AgentConfig,
  type CliConfig,
  KnowledgeBaseConfig,
  loadGlobalMcpServers,
  loadGlobalRagConfig,
  loadLocalMcpServers,
  loadLocalRagConfig,
  McpServerConfig,
  ProviderConfig,
  saveAgents,
  saveMcpServers,
  saveModels,
  saveRagKnowledgeBases,
  saveRagModel,
  tryParseContextWindow,
} from "@/config";
import { Session } from "@/session";
import { Store } from "@/store";
import { StreamEventType } from "@/engine/enums";
import { ORCHESTRATOR } from "@/engine/streaming";
import type { ModelProviderDTO } from "@/engine/dto";
import { AUDIT_SUBAGENT_ORDER } from "@/workflows/auditSubagents";
import { AUDIT_SLIM_SUBAGENT_ORDER } from "@/workflows/auditSlimSubagents";
import { RuntimePolicyResolver } from "@/runtime/resolver";
import { listAvailableSkills } from "@/resources/skills";
import { type TranscriptItem, type ToolEntry, type SubagentEntry, nextId } from "@/tui/transcript";
import { debugEnabled, debugLog, debugLogFile, setDebugEnabled } from "@/debug";
import * as paths from "@/paths";
import { getWorkflowMeta } from "@/workflows";

export interface GraphStageView {
  name: string;
  status: "pending" | "running" | "complete" | "error";
}

export interface McpStatusView {
  name: string;
  connected: boolean;
}

export interface TodoView {
  content: string;
  status: "pending" | "in_progress" | "completed";
}

/** Editable view of a model provider for the config form. */
export interface ModelDraft {
  name: string;
  modelName: string;
  apiMode: string;
  baseUrl: string;
  apiKey: string;
  maxContextTokens: string;
  enabled: string;
}

export interface AgentDraft {
  name: string;
  model: string;
  mcp: string;
  skills: string;
}

export interface ConfigModelRow {
  name: string;
  modelName: string;
  apiMode: string;
  enabled: boolean;
  active: boolean;
}

export interface ConfigAgentRow {
  name: string;
  model: string;
  mcp: string;
  skills: string;
}

export interface ConfigWorkflowRow {
  name: string;
  agentCount: number;
  current: boolean;
}

export interface WorkflowPickerRow {
  name: string;
  description: string;
  agentCount: number;
  current: boolean;
  isDefault: boolean;
}

export interface WorkflowGraphNode {
  name: string;
  label: string;
  kind: "workflow" | "primary" | "stage" | "router" | "terminal" | "tools" | "parallel" | "delegate";
  level: number;
  status: GraphStageView["status"] | "idle";
  detail: string;
}

export interface WorkflowGraphView {
  workflow: string;
  description: string;
  currentStage: string;
  failedStage: string;
  gapfillLoops: number;
  feedbackLoops: number;
  nodes: WorkflowGraphNode[];
}

export interface PluginMcpRow {
  name: string;
  transport: string;
  target: string;
  enabled: boolean;
}

export interface PluginSkillRow {
  name: string;
  enabled: boolean;
}

export interface PluginSkillSearchRow {
  name: string;
  description: string;
  installed: boolean;
  enabled: boolean;
}

export interface PluginMcpDraft {
  name: string;
  transport: string;
  url: string;
  headers: string;
  command: string;
  args: string;
  env: string;
  enabled: string;
  scope: string;
}

export interface PluginSkillDraft {
  name: string;
  prompt: string;
  enabled: string;
  scope: string;
}

export interface RagModelDraft {
  embeddingBackend: string;
  embeddingModel: string;
  embeddingApiBase: string;
  embeddingApiKey: string;
  embeddingLocalPath: string;
  chunkSize: string;
  chunkOverlap: string;
}

export interface RagKnowledgeBaseRow {
  name: string;
  backend: string;
  target: string;
  docsPath: string;
  enabled: boolean;
}

export interface RagKnowledgeBaseDraft {
  name: string;
  backend: string;
  docsPath: string;
  chromaPath: string;
  chromaUrl: string;
  collectionName: string;
  headers: string;
  enabled: string;
  scope: string;
}

export interface RagSearchDraft {
  query: string;
  knowledgeBase: string;
  topK: string;
}

/** Human-friendly labels for each API interface type. */
export const API_MODES = ["openai_compatible", "openai_responses", "anthropic"];
export const API_MODE_LABELS: Record<string, string> = {
  openai_compatible: "OpenAI Compatible API",
  openai_responses: "OpenAI Responses API",
  anthropic: "Anthropic Messages API",
};

/** Which pane of the config dialog is showing. */
export type ConfigSection = "models" | "workflow";
export type ConfigStep = "browse" | "model-fields" | "agent-fields";
export type ConfigWorkflowPane = "workflows" | "agents";
export type PluginSection = "mcp" | "skills";
export type PluginStep = "browse" | "mcp-fields" | "skill-fields";
export type RagSection = "model" | "knowledge" | "search";
export type RagStep = "browse" | "model-fields" | "kb-fields" | "search-fields";

export function parseContextSize(raw: string): number | null {
  return tryParseContextWindow(raw);
}

function truncateStatus(value: string, max: number): string {
  const compact = value.replace(/\s+/g, " ").trim();
  return compact.length > max ? `${compact.slice(0, Math.max(0, max - 1))}...` : compact;
}

function messageContentText(content: unknown): string {
  if (typeof content === "string") return content;
  if (Array.isArray(content)) {
    return content.map((part) => {
      if (typeof part === "string") return part;
      if (part && typeof part === "object" && "text" in part) {
        return String((part as { text?: unknown }).text ?? "");
      }
      return "";
    }).join("");
  }
  return content === null || content === undefined ? "" : String(content);
}

function safePathName(name: string): string {
  const safe = name.trim().replace(/[^A-Za-z0-9_.-]+/g, "-").replace(/^-+|-+$/g, "");
  return safe || "knowledge-base";
}

function expandUserPath(path: string): string {
  if (path === "~" || path.startsWith("~/") || path.startsWith("~\\")) {
    return resolve(join(homedir(), path.slice(1)));
  }
  return resolve(path);
}

function knowledgeBaseChromaPath(kb: KnowledgeBaseConfig): string {
  if (kb.chromaPath.trim()) return expandUserPath(kb.chromaPath);
  return join(paths.ragChromaDir(), safePathName(kb.name));
}

function upsertKnowledgeBase(
  knowledgeBases: KnowledgeBaseConfig[],
  knowledgeBase: KnowledgeBaseConfig,
): void {
  const index = knowledgeBases.findIndex((kb) => kb.name === knowledgeBase.name);
  if (index >= 0) knowledgeBases[index] = knowledgeBase;
  else knowledgeBases.push(knowledgeBase);
}

// Stage panels are derived from the real subagent node names so the side panel
// matches what the graph actually runs. Hardcoding a guessed list (e.g.
// "hunter"/"confirm") leaves stages perpetually pending because their events
// never match a row.
const AUDIT_STAGES = [...AUDIT_SUBAGENT_ORDER];
const AUDIT_SLIM_STAGES = [...AUDIT_SLIM_SUBAGENT_ORDER];

export interface Controller {
  /** Reactive transcript items (newest last). */
  items: TranscriptItem[];
  /** Live assistant text being streamed (not yet committed to items). */
  draft: () => string;
  draftReasoning: () => string;
  busy: () => boolean;
  status: () => string;
  workflow: () => string;
  modelName: () => string;
  toolCount: () => number;
  mcpStatuses: () => McpStatusView[];
  refreshMcpStatus: () => Promise<void>;
  todoItems: () => TodoView[];
  stages: () => GraphStageView[];
  workflows: () => string[];
  sessionId: () => string;
  /** Submit a user message; resolves when the turn finishes. */
  submit: (text: string) => Promise<void>;
  cancelCurrentRun: () => boolean;
  setWorkflow: (name: string) => void;
  workflowPickerOpen: () => boolean;
  workflowPickerSelectedIndex: () => number;
  workflowRows: () => WorkflowPickerRow[];
  openWorkflowPicker: () => void;
  closeWorkflowPicker: () => void;
  moveWorkflowPickerSelection: (delta: number) => void;
  activateWorkflowPickerSelection: () => string | null;
  graphOpen: () => boolean;
  workflowGraph: () => WorkflowGraphView;
  openGraph: () => void;
  closeGraph: () => void;
  newConversation: () => void;
  /** Append a system note line to the transcript. */
  note: (text: string) => void;
  statusReport: () => Promise<string>;
  graphReport: () => string;
  modelReport: () => string;
  selectModel: (name: string) => Promise<string>;
  modelsReport: () => string;
  mcpReport: () => Promise<string>;
  skillsReport: () => string;
  sessionsReport: (limit?: number) => string;
  resumeSession: (sessionId: string) => boolean;
  restartRuntime: () => Promise<string>;
  compactContext: () => Promise<string>;
  pluginReport: () => string;
  pluginCommand: (args: string) => Promise<string>;
  // --- plugin configuration overlay ---
  pluginOpen: () => boolean;
  pluginSection: () => PluginSection;
  pluginStep: () => PluginStep;
  pluginSelectedIndex: () => number;
  openPlugin: () => void;
  closePlugin: () => void;
  setPluginSection: (section: PluginSection) => void;
  movePluginSelection: (delta: number) => void;
  pluginMcpRows: () => PluginMcpRow[];
  pluginSkillRows: () => PluginSkillRow[];
  pluginSkillSearchQuery: () => string;
  setPluginSkillSearchQuery: (value: string) => void;
  pluginSkillSearchRows: () => PluginSkillSearchRow[];
  searchPluginSkills: () => Promise<string | null>;
  installPluginSkill: (name: string) => Promise<string | null>;
  newPluginMcp: () => void;
  editPluginMcp: () => void;
  toggleSelectedPlugin: () => Promise<string | null>;
  pluginMcpDraft: PluginMcpDraft;
  setPluginMcpField: (key: keyof PluginMcpDraft, value: string) => void;
  /** Probe the current MCP draft by connecting and loading tools. */
  testPluginMcp: () => Promise<string>;
  savePluginMcp: () => Promise<string | null>;
  newPluginSkill: () => void;
  pluginSkillDraft: PluginSkillDraft;
  setPluginSkillField: (key: keyof PluginSkillDraft, value: string) => void;
  savePluginSkill: () => Promise<string | null>;
  backToPluginBrowse: () => void;
  ragReport: () => string;
  // --- RAG overlay ---
  ragOpen: () => boolean;
  ragSection: () => RagSection;
  ragStep: () => RagStep;
  ragSelectedIndex: () => number;
  openRag: () => void;
  closeRag: () => void;
  setRagSection: (section: RagSection) => void;
  moveRagSelection: (delta: number) => void;
  ragKnowledgeBaseRows: () => RagKnowledgeBaseRow[];
  editRagModelSettings: () => void;
  editRagSearch: () => void;
  newRagKnowledgeBase: () => void;
  editRagKnowledgeBase: () => void;
  toggleSelectedRagKnowledgeBase: () => Promise<string | null>;
  deleteSelectedRagKnowledgeBase: () => Promise<string | null>;
  chunkSelectedRagKnowledgeBase: () => Promise<string | null>;
  ragModelDraft: RagModelDraft;
  ragKnowledgeBaseDraft: RagKnowledgeBaseDraft;
  ragSearchDraft: RagSearchDraft;
  setRagModelField: (key: keyof RagModelDraft, value: string) => void;
  setRagKnowledgeBaseField: (key: keyof RagKnowledgeBaseDraft, value: string) => void;
  setRagSearchField: (key: keyof RagSearchDraft, value: string) => void;
  saveRagModelSettings: () => Promise<string | null>;
  saveRagKnowledgeBase: () => Promise<string | null>;
  runRagSearch: () => Promise<string | null>;
  backToRagBrowse: () => void;
  debugReport: (arg?: string) => string;
  /** True when an enabled model with a model id is configured. */
  hasModel: () => boolean;
  // --- active model picker overlay ---
  modelPickerOpen: () => boolean;
  modelPickerSelectedIndex: () => number;
  openModelPicker: () => void;
  closeModelPicker: () => void;
  moveModelPickerSelection: (delta: number) => void;
  activateModelPickerSelection: () => Promise<string | null>;
  // --- model configuration overlay ---
  configOpen: () => boolean;
  configSection: () => ConfigSection;
  configStep: () => ConfigStep;
  openConfig: () => void;
  closeConfig: () => void;
  setConfigSection: (section: ConfigSection) => void;
  configSelectedIndex: () => number;
  configWorkflowSelectedIndex: () => number;
  configAgentSelectedIndex: () => number;
  configWorkflowPane: () => ConfigWorkflowPane;
  configModelRows: () => ConfigModelRow[];
  configWorkflowRows: () => ConfigWorkflowRow[];
  configAgentRows: () => ConfigAgentRow[];
  selectConfigItem: (index: number) => void;
  moveConfigSelection: (delta: number) => void;
  moveConfigWorkflowSelection: (delta: number) => void;
  moveConfigAgentSelection: (delta: number) => void;
  setConfigWorkflowPane: (pane: ConfigWorkflowPane) => void;
  newConfigModel: () => void;
  editConfigModel: () => void;
  editConfigAgent: () => void;
  deleteConfigModel: () => Promise<string | null>;
  activateConfigModel: () => Promise<string | null>;
  /** Choose an interface type and advance to the fields step. */
  chooseInterface: (apiMode: string) => void;
  /** Go back to the interface-selection step. */
  backToInterface: () => void;
  modelDraft: ModelDraft;
  setModelField: (key: keyof ModelDraft, value: string) => void;
  agentDraft: AgentDraft;
  setAgentField: (key: keyof AgentDraft, value: string) => void;
  /** Probe the current model draft with a minimal request. */
  testModel: () => Promise<string>;
  /** Persist the draft to models.toml and rebuild the runtime. Returns an error message or null. */
  saveModel: () => Promise<string | null>;
  saveAgent: () => Promise<string | null>;
  close: () => Promise<void>;
}

export function createController(config: CliConfig, workflowNames: string[]): Controller {
  const store = new Store();
  const session = new Session(config, store);
  let resolver = new RuntimePolicyResolver(config);
  let closed = false;

  const [items, setItems] = createStore<TranscriptItem[]>([]);
  const [draft, setDraft] = createSignal("");
  const [draftReasoning, setDraftReasoning] = createSignal("");
  const [busy, setBusy] = createSignal(false);
  const [status, setStatus] = createSignal("ready");
  const [workflow, setWorkflowSig] = createSignal(session.workflow);
  const [toolCount, setToolCount] = createSignal(session.toolCount);
  const [mcpStatusVersion, setMcpStatusVersion] = createSignal(0);
  const [stages, setStages] = createStore<GraphStageView[]>([]);
  const [todoItems, setTodoItems] = createStore<TodoView[]>([]);
  const [workflowPickerOpen, setWorkflowPickerOpen] = createSignal(false);
  const [workflowPickerSelectedIndex, setWorkflowPickerSelectedIndex] = createSignal(0);
  const [graphOpen, setGraphOpen] = createSignal(false);
  const [activeWorkflowNode, setActiveWorkflowNode] = createSignal("");
  // Bumped whenever config changes so model-derived getters re-run.
  const [configVersion, setConfigVersion] = createSignal(0);
  let pendingDraftText = "";
  let pendingDraftReasoning = "";
  let draftFlushTimer: ReturnType<typeof setTimeout> | undefined;

  function clearDraftFlushTimer(): void {
    if (draftFlushTimer) clearTimeout(draftFlushTimer);
    draftFlushTimer = undefined;
  }

  function flushDraftBuffers(): void {
    clearDraftFlushTimer();
    const text = pendingDraftText;
    const reasoning = pendingDraftReasoning;
    pendingDraftText = "";
    pendingDraftReasoning = "";
    if (reasoning) setDraftReasoning((prev) => prev + reasoning);
    if (text) setDraft((prev) => prev + text);
  }

  function scheduleDraftFlush(): void {
    if (draftFlushTimer) return;
    draftFlushTimer = setTimeout(() => flushDraftBuffers(), 32);
  }

  function appendDraftText(content: string, reasoning: string): void {
    if (!content && !reasoning) return;
    pendingDraftText += content;
    pendingDraftReasoning += reasoning;
    if (pendingDraftText.length + pendingDraftReasoning.length >= 2048) {
      flushDraftBuffers();
    } else {
      scheduleDraftFlush();
    }
  }

  const modelName = () => {
    configVersion();
    return resolver.providerFor(workflow() || "ruflo").modelName || "(unset)";
  };
  const hasModel = () => {
    configVersion();
    return Boolean(resolver.providerFor("ruflo").modelName);
  };
  const mcpStatuses = () => {
    configVersion();
    mcpStatusVersion();
    const byName = new Map(session.poolRef.serverStatuses.map((s) => [s.name, s]));
    return config.mcpServers.map((server) => ({
      name: server.name,
      connected: Boolean(server.enabled && byName.get(server.name)?.connected),
    }));
  };

  async function refreshMcpStatus(): Promise<void> {
    if (busy()) return;
    try {
      await session.ensureMcpConnected(workflow());
      setToolCount(session.toolCount);
    } catch (exc) {
      debugLog("TUI MCP status refresh failed", exc);
    } finally {
      setMcpStatusVersion((v) => v + 1);
    }
  }

  // --- model configuration overlay state ---
  const [modelPickerOpen, setModelPickerOpen] = createSignal(false);
  const [modelPickerSelectedIndex, setModelPickerSelectedIndex] = createSignal(0);
  const [configOpen, setConfigOpen] = createSignal(false);
  const [configSection, setConfigSectionSig] = createSignal<ConfigSection>("models");
  const [configStep, setConfigStep] = createSignal<ConfigStep>("browse");
  const [configSelectedIndex, setConfigSelectedIndex] = createSignal(0);
  const [configWorkflowSelectedIndex, setConfigWorkflowSelectedIndex] = createSignal(0);
  const [configAgentSelectedIndex, setConfigAgentSelectedIndex] = createSignal(0);
  const [configWorkflowPane, setConfigWorkflowPane] = createSignal<ConfigWorkflowPane>("workflows");
  const [editingModelName, setEditingModelName] = createSignal("");
  const rawActive = () => config.models.find((model) => model.name === config.activeModel) ?? config.models[0] ?? new ProviderConfig();
  const existing = rawActive();
  const [modelDraft, setModelDraft] = createStore<ModelDraft>({
    name: existing.name || "default",
    modelName: existing.modelName || "",
    apiMode: existing.apiMode || "openai_compatible",
    baseUrl: existing.baseUrl || "",
    apiKey: existing.apiKey || "",
    maxContextTokens: String(existing.maxContextTokens || 128_000),
    enabled: existing.enabled ? "true" : "false",
  });
  const [agentDraft, setAgentDraft] = createStore<AgentDraft>({
    name: "ruflo",
    model: "default",
    mcp: "*",
    skills: "",
  });
  const [pluginOpen, setPluginOpen] = createSignal(false);
  const [pluginSection, setPluginSectionSig] = createSignal<PluginSection>("mcp");
  const [pluginStep, setPluginStep] = createSignal<PluginStep>("browse");
  const [pluginSelectedIndex, setPluginSelectedIndex] = createSignal(0);
  const [pluginSkillSearchQuery, setPluginSkillSearchQuerySig] = createSignal("");
  const [pluginSkillSearchRows, setPluginSkillSearchRows] = createSignal<PluginSkillSearchRow[]>([]);
  const [editingMcpName, setEditingMcpName] = createSignal("");
  const [pluginMcpDraft, setPluginMcpDraft] = createStore<PluginMcpDraft>({
    name: "",
    transport: "http",
    url: "",
    headers: "",
    command: "",
    args: "",
    env: "",
    enabled: "true",
    scope: "local",
  });
  const [pluginSkillDraft, setPluginSkillDraft] = createStore<PluginSkillDraft>({
    name: "",
    prompt: "",
    enabled: "true",
    scope: "local",
  });
  const [ragOpen, setRagOpen] = createSignal(false);
  const [ragSection, setRagSectionSig] = createSignal<RagSection>("knowledge");
  const [ragStep, setRagStep] = createSignal<RagStep>("browse");
  const [ragSelectedIndex, setRagSelectedIndex] = createSignal(0);
  const [ragVersion, setRagVersion] = createSignal(0);
  const [editingRagKnowledgeBaseName, setEditingRagKnowledgeBaseName] = createSignal("");
  const [ragModelDraft, setRagModelDraft] = createStore<RagModelDraft>({
    embeddingBackend: config.rag.embeddingBackend || "huggingface",
    embeddingModel: config.rag.embeddingModel || "",
    embeddingApiBase: config.rag.embeddingApiBase || "",
    embeddingApiKey: config.rag.embeddingApiKey || "",
    embeddingLocalPath: config.rag.embeddingLocalPath || "",
    chunkSize: String(config.rag.chunkSize || 1200),
    chunkOverlap: String(config.rag.chunkOverlap || 150),
  });
  const [ragKnowledgeBaseDraft, setRagKnowledgeBaseDraft] = createStore<RagKnowledgeBaseDraft>({
    name: "",
    backend: "sarma_native",
    docsPath: "",
    chromaPath: "",
    chromaUrl: "",
    collectionName: "",
    headers: "",
    enabled: "true",
    scope: "local",
  });
  const [ragSearchDraft, setRagSearchDraft] = createStore<RagSearchDraft>({
    query: "",
    knowledgeBase: "",
    topK: "5",
  });

  function push(item: TranscriptItem): void {
    setItems(produce((list) => list.push(item)));
  }

  function stageTemplate(wf: string): GraphStageView[] {
    const names = wf === "audit" ? AUDIT_STAGES : wf === "audit-slim" ? AUDIT_SLIM_STAGES : [];
    return names.map((name) => ({ name, status: "pending" as const }));
  }

  function setStageStatus(name: string, st: GraphStageView["status"]): void {
    setStages(
      (s) => s.name === name,
      produce((s) => {
        s.status = st;
      }),
    );
  }

  function isCurrentWorkflowStage(name: string): boolean {
    if (!name) return false;
    const wf = workflow();
    return (wf === "audit" && AUDIT_STAGES.includes(name)) || (wf === "audit-slim" && AUDIT_SLIM_STAGES.includes(name));
  }

  function isCurrentWorkflowNode(name: string): boolean {
    if (isCurrentWorkflowStage(name)) return true;
    const wf = workflow();
    const auditRouters = ["validate_check", "gapfill_check", "feedback_check"];
    const auditSlimRouters = ["verify_check"];
    return (wf === "audit" && auditRouters.includes(name)) || (wf === "audit-slim" && auditSlimRouters.includes(name));
  }

  function findTool(id: string): number {
    return items.findIndex((it) => it.kind === "tool" && it.tool.id === id);
  }
  function findSubagent(name: string, callId = ""): number {
    if (callId) {
      const idx = items.findIndex(
        (it) => it.kind === "subagent" && it.subagent.toolCallId === callId && it.subagent.status === "running",
      );
      if (idx >= 0) return idx;
    }
    for (let idx = items.length - 1; idx >= 0; idx -= 1) {
      const item = items[idx];
      if (item?.kind === "subagent" && item.subagent.name === name && item.subagent.status === "running") return idx;
    }
    return -1;
  }

  function findRunningStage(name: string): number {
    for (let idx = items.length - 1; idx >= 0; idx -= 1) {
      const item = items[idx];
      if (item?.kind === "stage" && item.stage.name === name && item.stage.status === "running") return idx;
    }
    return -1;
  }

  function currentRunningStage(): string {
    return activeWorkflowNode() || stages.find((stage) => stage.status === "running")?.name || "";
  }

  const toolStart = new Map<string, number>();
  const stageStart = new Map<string, number>();
  const subagentStart = new Map<string, number>();
  const toolPending: { id: string; name: string; callId: string; subagent: string }[] = [];

  function subagentKey(name: string, callId = ""): string {
    return callId || name;
  }

  function parseTodos(value: unknown): TodoView[] {
    if (!value) return [];
    if (typeof value === "string") {
      const text = value.trim();
      if (!text) return [];
      try {
        return parseTodos(JSON.parse(text));
      } catch {
        const match = /Updated todo list to\s+(\[.*\])$/s.exec(text);
        if (match) return parseTodos(match[1]);
        return [];
      }
    }
    if (Array.isArray(value)) return normalizeTodos(value);
    if (typeof value === "object") {
      const record = value as Record<string, unknown>;
      if (Array.isArray(record.todos)) return normalizeTodos(record.todos);
    }
    return [];
  }

  function normalizeTodos(values: unknown[]): TodoView[] {
    const result: TodoView[] = [];
    for (const item of values) {
      if (!item || typeof item !== "object") continue;
      const record = item as Record<string, unknown>;
      const content = String(record.content ?? record.text ?? record.task ?? "").trim();
      const rawStatus = String(record.status ?? "pending").trim();
      const status: TodoView["status"] =
        rawStatus === "in_progress" || rawStatus === "completed" ? rawStatus : "pending";
      if (content) result.push({ content, status });
    }
    return result;
  }

  function replaceTodos(todos: TodoView[]): void {
    setTodoItems(
      produce((list) => {
        list.splice(0, list.length, ...todos);
      }),
    );
  }

  function maybeUpdateTodos(toolName: string, value: unknown): void {
    if (toolName !== "write_todos") return;
    const todos = parseTodos(value);
    if (todos.length > 0 || Array.isArray(value)) replaceTodos(todos);
  }

  function stringifyPayload(value: unknown): string {
    if (typeof value === "string") return value;
    if (value === undefined || value === null) return "";
    try {
      return JSON.stringify(value, null, 2);
    } catch {
      return String(value);
    }
  }

  function appendSubagentStream(name: string, callId: string, content: string, reasoning: string): void {
    let idx = findSubagent(name, callId);
    if (idx < 0) {
      const id = nextId("s");
      subagentStart.set(subagentKey(name, callId), Date.now());
      push({
        kind: "subagent",
        id,
        subagent: {
          id,
          name,
          description: "",
          status: "running",
          elapsed: 0,
          toolCallId: callId,
          output: "",
          reasoning: "",
          result: "",
          error: "",
        },
      });
      idx = items.length - 1;
    }
    setItems(
      idx,
      produce((it) => {
        if (it.kind !== "subagent") return;
        it.subagent.output += content;
        it.subagent.reasoning += reasoning;
      }),
    );
  }

  function implicitSubagentForToken(): SubagentEntry | null {
    const delegateCallIds = new Set(
      toolPending
        .filter((tool) => tool.name === "delegate_task" || tool.name === "task")
        .map((tool) => tool.callId)
        .filter((callId) => callId),
    );
    const running = items.flatMap((item) =>
      item.kind === "subagent" &&
      item.subagent.status === "running" &&
      item.subagent.toolCallId &&
      delegateCallIds.has(item.subagent.toolCallId)
        ? [item.subagent]
        : [],
    );
    return running.length === 1 ? running[0]! : null;
  }

  function commitDraft(): void {
    flushDraftBuffers();
    const text = draft();
    const reasoning = draftReasoning();
    if (text || reasoning) {
      push({ kind: "message", id: nextId("a"), role: "assistant", content: text, reasoning });
    }
    setDraft("");
    setDraftReasoning("");
  }

  function handleEvent(event: { type: string; payload: Record<string, unknown> }): void {
    const p = event.payload;
    switch (event.type) {
      case StreamEventType.TOKEN: {
        const r = (p.reasoning_content as string) || "";
        const t = (p.content as string) || "";
        const source = String(p.subagent ?? ORCHESTRATOR);
        const callId = (p.tool_call_id as string) || "";
        if (source && source !== ORCHESTRATOR && !isCurrentWorkflowNode(source)) {
          appendSubagentStream(source, callId, t, r);
        } else {
          const implicit = implicitSubagentForToken();
          if (implicit) {
            appendSubagentStream(implicit.name, implicit.toolCallId, t, r);
          } else {
            appendDraftText(t, r);
          }
        }
        break;
      }
      case StreamEventType.TOOL_START: {
        commitDraft();
        const name = (p.tool_name as string) || "?";
        const callId = (p.tool_call_id as string) || "";
        const source = String(p.subagent ?? ORCHESTRATOR);
        const toolSubagent = source && source !== ORCHESTRATOR ? source : "";
        maybeUpdateTodos(name, p.args ?? p.args_json);
        setToolCount(session.toolCount);
        setMcpStatusVersion((v) => v + 1);
        const id = nextId("t");
        toolStart.set(id, Date.now());
        // Track the tool_call_id so the matching result correlates exactly,
        // even when several tools with the same name run concurrently.
        toolPending.push({ id, name, callId, subagent: toolSubagent });
        push({
          kind: "tool",
          id,
          tool: {
            id,
            toolCallId: callId,
            name,
            subagent: toolSubagent,
            args: stringifyPayload(p.args_json || p.args),
            status: "running",
            summary: "",
            result: "",
            error: "",
            elapsed: 0,
          },
        });
        setStatus(`running ${name}`);
        break;
      }
      case StreamEventType.TOOL_RESULT:
      case StreamEventType.TOOL_ERROR: {
        const name = (p.tool_name as string) || "?";
        const callId = (p.tool_call_id as string) || "";
        maybeUpdateTodos(name, p.result ?? p.result_summary ?? p.error_text);
        // Prefer an exact tool_call_id match; fall back to name for events
        // that carry no id (so older/synthetic events still correlate).
        let pending =
          callId !== "" ? toolPending.find((x) => x.callId === callId) : undefined;
        if (!pending) pending = toolPending.find((x) => x.name === name);
        if (!pending) break;
        toolPending.splice(toolPending.indexOf(pending), 1);
        const idx = findTool(pending.id);
        const elapsed = toolStart.has(pending.id) ? (Date.now() - toolStart.get(pending.id)!) / 1000 : 0;
        toolStart.delete(pending.id);
        const isError = event.type === StreamEventType.TOOL_ERROR;
        if (idx >= 0) {
          setItems(
            idx,
            produce((it) => {
              if (it.kind !== "tool") return;
              it.tool.status = isError ? "error" : "ok";
              it.tool.summary = isError ? (p.error_text as string) || "" : (p.result_summary as string) || "";
              it.tool.result = stringifyPayload(p.result ?? p.result_summary);
              it.tool.error = stringifyPayload(p.error_text ?? p.error);
              it.tool.elapsed = elapsed;
            }),
          );
        }
        setStatus(currentRunningStage() ? `${currentRunningStage()} working` : "thinking");
        break;
      }
      case StreamEventType.STAGE_START: {
        commitDraft();
        const name = (p.stage as string) || (p.subagent as string) || "";
        if (!name) break;
        const nodeKind = p.node_kind === "router" ? "router" : "stage";
        const description = (p.description as string) || "";
        stageStart.set(name, Date.now());
        setActiveWorkflowNode(name);
        const idx = findRunningStage(name);
        if (idx >= 0) {
          setItems(
            idx,
            produce((it) => {
              if (it.kind !== "stage") return;
              if (description) it.stage.description = description;
            }),
          );
        } else {
          const id = nextId("g");
          push({
            kind: "stage",
            id,
            stage: {
              id,
              name,
              nodeKind,
              description,
              status: "running",
              elapsed: 0,
              error: "",
            },
          });
        }
        if (isCurrentWorkflowStage(name)) setStageStatus(name, "running");
        setStatus(`${name} working`);
        break;
      }
      case StreamEventType.STAGE_COMPLETE: {
        const name = (p.stage as string) || (p.subagent as string) || "";
        if (name) {
          const idx = findRunningStage(name);
          const elapsed = stageStart.has(name) ? (Date.now() - stageStart.get(name)!) / 1000 : 0;
          stageStart.delete(name);
          if (idx >= 0) {
            setItems(
              idx,
              produce((it) => {
                if (it.kind !== "stage") return;
                it.stage.status = "complete";
                it.stage.elapsed = elapsed;
              }),
            );
          }
          if (isCurrentWorkflowStage(name)) setStageStatus(name, "complete");
          if (activeWorkflowNode() === name) setActiveWorkflowNode("");
          setStatus(currentRunningStage() ? `${currentRunningStage()} working` : "thinking");
        }
        break;
      }
      case StreamEventType.STAGE_ERROR: {
        const name = (p.stage as string) || (p.subagent as string) || "";
        if (name) {
          const idx = findRunningStage(name);
          const elapsed = stageStart.has(name) ? (Date.now() - stageStart.get(name)!) / 1000 : 0;
          stageStart.delete(name);
          if (idx >= 0) {
            setItems(
              idx,
              produce((it) => {
                if (it.kind !== "stage") return;
                it.stage.status = "error";
                it.stage.elapsed = elapsed;
                it.stage.error = String(p.error_text ?? p.error ?? "");
              }),
            );
          }
          if (isCurrentWorkflowStage(name)) setStageStatus(name, "error");
          if (activeWorkflowNode() === name) setActiveWorkflowNode("");
          setStatus(`${name} failed`);
        }
        break;
      }
      case StreamEventType.SUBAGENT_START: {
        commitDraft();
        const name = (p.subagent as string) || "";
        if (!name) break;
        const callId = (p.tool_call_id as string) || "";
        const id = nextId("s");
        subagentStart.set(subagentKey(name, callId), Date.now());
        push({
          kind: "subagent",
          id,
          subagent: {
            id,
            name,
            description: (p.description as string) || "",
            status: "running",
            elapsed: 0,
            toolCallId: callId,
            output: "",
            reasoning: "",
            result: "",
            error: "",
          },
        });
        setStatus(`${name} working`);
        break;
      }
      case StreamEventType.SUBAGENT_COMPLETE: {
        const name = (p.subagent as string) || "";
        if (!name) break;
        const callId = (p.tool_call_id as string) || "";
        const key = subagentKey(name, callId);
        const idx = findSubagent(name, callId);
        const elapsed = subagentStart.has(key) ? (Date.now() - subagentStart.get(key)!) / 1000 : 0;
        subagentStart.delete(key);
        if (idx >= 0) {
          setItems(
            idx,
            produce((it) => {
              if (it.kind !== "subagent") return;
              it.subagent.status = "complete";
              it.subagent.elapsed = elapsed;
              it.subagent.result = String(p.result_summary ?? p.result ?? "");
            }),
          );
        }
        break;
      }
      case StreamEventType.SUBAGENT_ERROR: {
        const name = (p.subagent as string) || "";
        const callId = (p.tool_call_id as string) || "";
        const key = subagentKey(name, callId);
        const idx = name ? findSubagent(name, callId) : -1;
        const elapsed = subagentStart.has(key) ? (Date.now() - subagentStart.get(key)!) / 1000 : 0;
        subagentStart.delete(key);
        if (idx >= 0) {
          setItems(
            idx,
            produce((it) => {
              if (it.kind !== "subagent") return;
              it.subagent.status = "error";
              it.subagent.elapsed = elapsed;
              it.subagent.error = String(p.error_text ?? p.error ?? p.result_summary ?? p.result ?? "");
            }),
          );
        }
        break;
      }
      case StreamEventType.RUN_FAILED: {
        commitDraft();
        push({ kind: "error", id: nextId("e"), text: (p.error as string) || "Unknown error" });
        break;
      }
      default:
        break;
    }
  }

  async function submit(text: string): Promise<void> {
    const trimmed = text.trim();
    if (!trimmed || busy()) return;
    let failureMessage = "";
    push({ kind: "message", id: nextId("u"), role: "user", content: trimmed, reasoning: "" });
    setBusy(true);
    setStatus("thinking");
    try {
      for await (const event of session.runTurn(trimmed)) {
        if (event.type === StreamEventType.RUN_FAILED) {
          failureMessage = String(event.payload.error ?? "Unknown error");
        }
        handleEvent(event as unknown as { type: string; payload: Record<string, unknown> });
      }
      commitDraft();
      setToolCount(session.toolCount);
      setMcpStatusVersion((v) => v + 1);
    } catch (exc) {
      debugLog("TUI submit failed", exc);
      failureMessage = exc instanceof Error ? exc.message : String(exc);
      commitDraft();
      push({ kind: "error", id: nextId("e"), text: failureMessage });
    } finally {
      setMcpStatusVersion((v) => v + 1);
      setBusy(false);
      setStatus(failureMessage ? `error: ${failureMessage}` : "ready");
    }
  }

  function markRunningItemsCancelled(): void {
    const now = Date.now();
    commitDraft();
    setItems(
      produce((list) => {
        for (const item of list) {
          if (item.kind === "tool" && item.tool.status === "running") {
            item.tool.status = "error";
            item.tool.summary ||= "Cancelled.";
            item.tool.error ||= "Cancelled.";
            item.tool.elapsed = toolStart.has(item.tool.id) ? (now - toolStart.get(item.tool.id)!) / 1000 : item.tool.elapsed;
          } else if (item.kind === "subagent" && item.subagent.status === "running") {
            const key = subagentKey(item.subagent.name, item.subagent.toolCallId);
            item.subagent.status = "error";
            item.subagent.error ||= "Cancelled.";
            item.subagent.elapsed = subagentStart.has(key) ? (now - subagentStart.get(key)!) / 1000 : item.subagent.elapsed;
          } else if (item.kind === "stage" && item.stage.status === "running") {
            item.stage.status = "error";
            item.stage.error ||= "Cancelled.";
            item.stage.elapsed = stageStart.has(item.stage.name) ? (now - stageStart.get(item.stage.name)!) / 1000 : item.stage.elapsed;
          }
        }
      }),
    );
    setStages(
      produce((list) => {
        for (const stage of list) {
          if (stage.status === "running") stage.status = "error";
        }
      }),
    );
    toolStart.clear();
    stageStart.clear();
    subagentStart.clear();
    toolPending.splice(0, toolPending.length);
    setActiveWorkflowNode("");
  }

  function cancelCurrentRun(): boolean {
    if (!busy()) return false;
    const cancelled = session.cancelCurrentRun();
    if (cancelled) {
      markRunningItemsCancelled();
      setStatus("cancelling");
      note("Stopping current workflow...");
    }
    return cancelled;
  }

  function resetLiveTurnState(): void {
    clearDraftFlushTimer();
    pendingDraftText = "";
    pendingDraftReasoning = "";
    setDraft("");
    setDraftReasoning("");
    toolStart.clear();
    stageStart.clear();
    subagentStart.clear();
    toolPending.splice(0, toolPending.length);
    setActiveWorkflowNode("");
    setStages(stageTemplate(workflow()));
    replaceTodos([]);
  }

  function setWorkflow(name: string): void {
    session.setWorkflow(name);
    setWorkflowSig(name);
    setActiveWorkflowNode("");
    setStages(stageTemplate(name));
  }

  function workflowRows(): WorkflowPickerRow[] {
    return configWorkflowNames().map((name) => {
      const meta = getWorkflowMeta(name);
      return {
        name,
        description: meta?.description ?? "",
        agentCount: agentNamesForWorkflow(name).length,
        current: name === workflow(),
        isDefault: Boolean(meta?.isDefault),
      };
    });
  }

  function openWorkflowPicker(): void {
    const idx = workflowRows().findIndex((row) => row.current);
    setWorkflowPickerSelectedIndex(Math.max(0, idx));
    setConfigOpen(false);
    setPluginOpen(false);
    setRagOpen(false);
    setModelPickerOpen(false);
    setGraphOpen(false);
    setWorkflowPickerOpen(true);
  }

  function closeWorkflowPicker(): void {
    setWorkflowPickerOpen(false);
  }

  function moveWorkflowPickerSelection(delta: number): void {
    const rows = workflowRows();
    if (rows.length === 0) {
      setWorkflowPickerSelectedIndex(0);
      return;
    }
    setWorkflowPickerSelectedIndex((idx) => (idx + delta + rows.length) % rows.length);
  }

  function activateWorkflowPickerSelection(): string | null {
    if (busy()) return "Cannot switch workflow while a turn is running.";
    const rows = workflowRows();
    const row = rows[Math.max(0, Math.min(workflowPickerSelectedIndex(), rows.length - 1))];
    if (!row) return "No workflow selected.";
    setWorkflow(row.name);
    setWorkflowPickerOpen(false);
    return null;
  }

  function workflowGraph(): WorkflowGraphView {
    configVersion();
    const wf = workflow();
    const meta = getWorkflowMeta(wf);
    const gs = session.graphState;
    const agent = config.agents.find((item) => item.name === wf);
    const enabledMcp = agent?.mcp?.length ? agent.mcp.join(", ") : "*";
    const enabledSkills = agent?.skills?.length ? agent.skills.join(", ") : "(none)";
    const nodeStatus = (name: string): WorkflowGraphNode["status"] =>
      gs.failed === name ? "error" : gs.current_stage === name ? "running" : gs.completed.has(name) ? "complete" : "idle";
    const nodes: WorkflowGraphNode[] = [
      {
        name: wf,
        label: wf,
        kind: "workflow",
        level: 0,
        status: gs.failed ? "error" : gs.current_stage ? "running" : "idle",
        detail: meta?.description ?? "Workflow",
      },
    ];
    if (stages.length === 0) {
      nodes.push({
        name: `${wf}:primary`,
        label: `${wf} primary agent`,
        kind: "primary",
        level: 1,
        status: gs.current_stage ? "running" : "idle",
        detail: `model=${resolver.providerFor(wf).modelName || "(unset)"}, mcp=${enabledMcp}, skills=${enabledSkills}`,
      });
      nodes.push({
        name: `${wf}:tools`,
        label: "model/tools loop",
        kind: "tools",
        level: 2,
        status: session.poolRef.isConnected ? "running" : "idle",
        detail: "LangChain createAgent ReAct loop; MCP and built-ins run through the tools node",
      });
      nodes.push({
        name: `${wf}:parallel-delegation`,
        label: "parallel delegate_task fan-out",
        kind: "parallel",
        level: 2,
        status: "idle",
        detail: "0..N delegate_task calls may run concurrently from the same model tool step",
      });
      nodes.push({
        name: `${wf}:delegate_task`,
        label: "delegate_task[*] -> focused subagent",
        kind: "delegate",
        level: 3,
        status: "idle",
        detail: "each branch creates a temporary subagent graph and returns a compact result",
      });
    } else {
      nodes.push({
        name: "START",
        label: "START",
        kind: "terminal",
        level: 1,
        status: "idle",
        detail: "entry into the compiled audit StateGraph",
      });
      for (const [idx, stage] of stages.entries()) {
        const agentName = `${wf}.${stage.name}`;
        const stageAgent = config.agents.find((item) => item.name === agentName);
        nodes.push({
          name: stage.name,
          label: `${String(idx + 1).padStart(2, "0")} ${stage.name}`,
          kind: "stage",
          level: 2,
          status: stage.status,
          detail: `agent=${agentName}, model=${stageAgent?.model || "default"}`,
        });
        if (wf === "audit" && stage.name === "validate") {
          nodes.push({
            name: "validate_check",
            label: "validate_check",
            kind: "router",
            level: 3,
            status: nodeStatus("validate_check"),
            detail: "same-model structured router: gapfill | dedupe",
          });
          nodes.push({
            name: "gapfill_check",
            label: "gapfill_check",
            kind: "router",
            level: 3,
            status: nodeStatus("gapfill_check"),
            detail: "after gapfill: hunt | validate",
          });
        }
        if (wf === "audit" && stage.name === "feedback") {
          nodes.push({
            name: "feedback_check",
            label: "feedback_check",
            kind: "router",
            level: 3,
            status: nodeStatus("feedback_check"),
            detail: "same-model structured router: hunt | report",
          });
        }
        if (wf === "audit-slim" && stage.name === "verify") {
          nodes.push({
            name: "verify_check",
            label: "verify_check",
            kind: "router",
            level: 3,
            status: nodeStatus("verify_check"),
            detail: "same-model structured router: hunter | report",
          });
        }
      }
      nodes.push({
        name: "END",
        label: "END",
        kind: "terminal",
        level: 1,
        status: "idle",
        detail: "final report stage output becomes the user-facing answer",
      });
    }
    return {
      workflow: wf,
      description: meta?.description ?? "",
      currentStage: gs.current_stage || "(idle)",
      failedStage: gs.failed || "(none)",
      gapfillLoops: gs.gapfill_loops,
      feedbackLoops: gs.feedback_loops,
      nodes,
    };
  }

  function openGraph(): void {
    setConfigOpen(false);
    setPluginOpen(false);
    setRagOpen(false);
    setModelPickerOpen(false);
    setWorkflowPickerOpen(false);
    setGraphOpen(true);
  }

  function closeGraph(): void {
    setGraphOpen(false);
  }

  function newConversation(): void {
    session.newConversation();
    setItems([]);
    resetLiveTurnState();
    push({ kind: "divider", id: nextId("d") });
  }

  async function close(): Promise<void> {
    // Idempotent: signal handlers and the normal exit path may both call this.
    if (closed) return;
    closed = true;
    clearDraftFlushTimer();
    await session.close();
    store.close();
  }

  function note(text: string): void {
    push({ kind: "note", id: nextId("n"), text });
  }

  function boolStatus(value: boolean): string {
    return value ? "enabled" : "disabled";
  }

  function formatList(values: string[]): string {
    return values.length > 0 ? values.join(", ") : "(none)";
  }

  function mcpTarget(server: McpServerConfig): string {
    if (server.transport === "stdio") return [server.command, server.args].filter(Boolean).join(" ");
    return server.url;
  }

  function parseList(value: string, dflt: string[] = []): string[] {
    const parts = value.split(",").map((part) => part.trim()).filter(Boolean);
    return parts.length > 0 ? parts : [...dflt];
  }

  function parseBool(value: string): boolean {
    return !["0", "false", "no", "off", "disabled"].includes(value.trim().toLowerCase());
  }

  function workflowAgentNames(): string[] {
    return configWorkflowNames().flatMap(agentNamesForWorkflow);
  }

  function configWorkflowNames(): string[] {
    const preferred = workflowNames.length > 0 ? workflowNames : ["ruflo", "audit", "audit-slim"];
    return [...new Set(preferred)];
  }

  function agentNamesForWorkflow(wf: string): string[] {
    if (wf === "audit") return [wf, ...AUDIT_STAGES.map((name) => `${wf}.${name}`)];
    if (wf === "audit-slim") return [wf, ...AUDIT_SLIM_STAGES.map((name) => `${wf}.${name}`)];
    return [wf];
  }

  function ensureWorkflowAgents(): void {
    const byName = new Map(config.agents.map((agent) => [agent.name, agent]));
    for (const name of workflowAgentNames()) {
      if (!byName.has(name)) {
        config.agents.push(new AgentConfig({ name, model: "default" }));
      }
    }
  }

  function replaceAgentModelRefs(oldName: string, newName: string): void {
    for (const agent of config.agents) {
      if (agent.model === oldName) agent.model = newName;
    }
  }

  function retargetAgentsFollowingActive(previousActive: string): boolean {
    let changed = false;
    for (const agent of config.agents) {
      if (!agent.model || agent.model === "default" || agent.model === previousActive) {
        if (agent.model !== "default") {
          agent.model = "default";
          changed = true;
        }
      }
    }
    return changed;
  }

  function uniqueModelName(base = "new-model"): string {
    const names = new Set(config.models.map((model) => model.name));
    if (!names.has(base)) return base;
    let idx = 2;
    while (names.has(`${base}-${idx}`)) idx += 1;
    return `${base}-${idx}`;
  }

  function modelAtSelection(): ProviderConfig | undefined {
    return config.models[configSelectedIndex()];
  }

  function modelAtPickerSelection(): ConfigModelRow | undefined {
    return configModelRows()[modelPickerSelectedIndex()];
  }

  function agentAtSelection(): AgentConfig | undefined {
    ensureWorkflowAgents();
    return config.agents.find((agent) => agent.name === configAgentRows()[configAgentSelectedIndex()]?.name);
  }

  function loadModelDraft(model: ProviderConfig): void {
    setModelDraft({
      name: model.name || "default",
      modelName: model.modelName || "",
      apiMode: model.apiMode || "openai_compatible",
      baseUrl: model.baseUrl || "",
      apiKey: model.apiKey || "",
      maxContextTokens: String(model.maxContextTokens || 128_000),
      enabled: model.enabled ? "true" : "false",
    });
  }

  function loadAgentDraft(agent: AgentConfig): void {
    setAgentDraft({
      name: agent.name,
      model: agent.model || "default",
      mcp: (agent.mcp.length > 0 ? agent.mcp : ["*"]).join(", "),
      skills: agent.skills.join(", "),
    });
  }

  function configModelRows(): ConfigModelRow[] {
    configVersion();
    return config.models.map((model) => ({
      name: model.name,
      modelName: model.modelName,
      apiMode: model.apiMode,
      enabled: model.enabled,
      active: model.name === config.activeModel,
    }));
  }

  function configWorkflowRows(): ConfigWorkflowRow[] {
    configVersion();
    return configWorkflowNames().map((name) => ({
      name,
      agentCount: agentNamesForWorkflow(name).length,
      current: name === workflow(),
    }));
  }

  function selectedConfigWorkflow(): string {
    const rows = configWorkflowRows();
    return rows[Math.max(0, Math.min(configWorkflowSelectedIndex(), rows.length - 1))]?.name ?? workflow() ?? "ruflo";
  }

  function configAgentRows(): ConfigAgentRow[] {
    configVersion();
    ensureWorkflowAgents();
    return agentNamesForWorkflow(selectedConfigWorkflow()).map((name) => {
      const agent = config.agents.find((item) => item.name === name) ?? new AgentConfig({ name });
      return {
        name: agent.name,
        model: agent.model || "default",
        mcp: (agent.mcp.length > 0 ? agent.mcp : ["*"]).join(", "),
        skills: agent.skills.join(", ") || "(none)",
      };
    });
  }

  function formatDate(value: string): string {
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) return value || "(unknown)";
    return d.toLocaleString();
  }

  async function statusReport(): Promise<string> {
    const wf = workflow();
    let mcpError = "";
    try {
      await session.ensureMcpConnected(wf);
      setToolCount(session.toolCount);
      setMcpStatusVersion((v) => v + 1);
    } catch (exc) {
      mcpError = exc instanceof Error ? exc.message : String(exc);
      setMcpStatusVersion((v) => v + 1);
    }

    const provider = resolver.providerFor(wf);
    const enabledServers = config.mcpServers.filter((server) => server.enabled);
    const statuses = session.poolRef.serverStatuses;
    const byName = new Map(statuses.map((s) => [s.name, s]));
    const skills = listAvailableSkills();
    const lines = [
      "status:",
      `  workflow: ${wf}`,
      `  model: ${provider.modelName || "(unset)"} via ${provider.name || "(unnamed)"}`,
      `  api mode: ${provider.apiMode}`,
      `  context: ${provider.maxContextTokens.toLocaleString()} tokens`,
      `  mcp: ${session.poolRef.isConnected && !mcpError ? "connected" : "not connected"}`,
      `  tools: ${session.toolCount}`,
      `  skills: ${formatList(skills)}`,
    ];

    if (enabledServers.length === 0) {
      lines.push("  servers: (none)");
    } else {
      lines.push("  servers:");
      for (const server of enabledServers) {
        const st = byName.get(server.name);
        const state = st?.connected ? "connected" : st?.error || mcpError ? "error" : "not connected";
        const detail = st?.error || (state === "error" ? mcpError : "");
        lines.push(
          `    - ${server.name}: ${state}, ${st?.toolCount ?? 0} tool(s)` +
            (detail ? ` (${detail})` : ""),
        );
      }
    }
    return lines.join("\n");
  }

  function graphReport(): string {
    const gs = session.graphState;
    const stageNames = stages.map((s) => s.name);
    const lines = [
      "graph:",
      `  workflow: ${workflow()}`,
      `  current: ${gs.current_stage || "(idle)"}`,
      `  completed: ${formatList([...gs.completed])}`,
      `  failed: ${gs.failed || "(none)"}`,
      `  gapfill loops: ${gs.gapfill_loops}`,
      `  feedback loops: ${gs.feedback_loops}`,
    ];
    if (stageNames.length > 0) {
      lines.push("  stages:");
      for (const stage of stages) lines.push(`    - ${stage.name}: ${stage.status}`);
    } else {
      lines.push("  stages: single-agent workflow");
    }
    return lines.join("\n");
  }

  function modelsReport(): string {
    const lines = ["models:"];
    for (const model of config.models) {
      const active = model.name === config.activeModel ? "*" : "-";
      lines.push(
        `  ${active} ${model.name}: ${model.modelName || "(unset)"} ` +
          `[${model.apiMode}, ${boolStatus(model.enabled)}, ${model.maxContextTokens.toLocaleString()} ctx]`,
      );
    }
    lines.push(`assignments for ${workflow()}:`);
    for (const [agent, model] of resolver.modelAssignmentsFor(workflow())) {
      lines.push(`  - ${agent}: ${model}`);
    }
    return lines.join("\n");
  }

  function modelReport(): string {
    return [
      modelsReport(),
      "",
      "usage:",
      "  /model <name>   select the active model",
      "  /config         add or edit model providers",
    ].join("\n");
  }

  async function selectModel(name: string): Promise<string> {
    if (busy()) return "Cannot switch model while a turn is running.";
    const target = name.trim();
    if (!target) return modelReport();
    const provider = config.models.find((model) => model.name === target);
    if (!provider) {
      return `unknown model: ${target}\n${modelReport()}`;
    }
    if (!provider.enabled) {
      return `model is disabled: ${target}`;
    }
    if (!provider.modelName.trim()) {
      return `model "${target}" has no Model ID. Use /config to edit it.`;
    }
    const previousActive = config.activeModel;
    config.activeModel = target;
    let savedPath: string;
    let agentsPath = "";
    try {
      const agentsChanged = retargetAgentsFollowingActive(previousActive);
      savedPath = saveModels(config);
      if (agentsChanged) agentsPath = saveAgents(config);
    } catch (exc) {
      return exc instanceof Error ? exc.message : String(exc);
    }
    resolver = new RuntimePolicyResolver(config);
    await session.restartRuntime();
    resetLiveTurnState();
    setToolCount(session.toolCount);
    setMcpStatusVersion((v) => v + 1);
    setConfigVersion((v) => v + 1);
    return `selected model: ${target} (${provider.modelName})\nsaved: ${savedPath}${agentsPath ? `\nsaved: ${agentsPath}` : ""}`;
  }

  async function mcpReport(): Promise<string> {
    const wf = workflow();
    let mcpError = "";
    try {
      await session.ensureMcpConnected(wf);
      setToolCount(session.toolCount);
      setMcpStatusVersion((v) => v + 1);
    } catch (exc) {
      mcpError = exc instanceof Error ? exc.message : String(exc);
      setMcpStatusVersion((v) => v + 1);
    }
    const statuses = session.poolRef.serverStatuses;
    const byName = new Map(statuses.map((s) => [s.name, s]));
    const lines = [
      "mcp:",
      `  workflow: ${wf}`,
      `  connected: ${session.poolRef.isConnected && !mcpError ? "yes" : "no"}`,
      `  tools: ${session.toolCount}`,
      `  local: ${paths.localMcpFile()}`,
      `  global: ${paths.globalMcpFile()}`,
      "  servers:",
    ];
    if (config.mcpServers.length === 0) {
      lines.push("    (none)");
    } else {
      for (const server of config.mcpServers) {
        const st = byName.get(server.name);
        const state = !server.enabled
          ? "disabled"
          : st?.connected
            ? "connected"
            : st?.error || mcpError
              ? "error"
              : "not connected";
        const detail = st?.error || (state === "error" ? mcpError : "");
        lines.push(
          `    - ${server.name}: ${server.transport}, ${state}, ${st?.toolCount ?? 0} tool(s)` +
            (detail ? ` (${detail})` : ""),
        );
      }
    }
    return lines.join("\n");
  }

  function agentSkillRows(): string[] {
    const wf = workflow();
    const rows: string[] = [];
    for (const agent of config.agents) {
      if (agent.name === wf || agent.name.startsWith(`${wf}.`)) {
        rows.push(`    - ${agent.name}: ${formatList(agent.skills)}`);
      }
    }
    if (rows.length === 0) rows.push(`    - ${wf}: (none)`);
    return rows;
  }

  function skillsReport(): string {
    return [
      "skills:",
      `  installed: ${formatList(listAvailableSkills())}`,
      `  local: ${paths.localSkillsDir()}`,
      `  global: ${paths.globalSkillsDir()}`,
      `  workflow assignments (${workflow()}):`,
      ...agentSkillRows(),
    ].join("\n");
  }

  function sessionsReport(limit = 20): string {
    const rows = store.listConversations(limit);
    if (rows.length === 0) return "sessions:\n  (no sessions yet)";
    const lines = ["sessions:"];
    for (const row of rows) {
      const title = row.title || "Untitled session";
      const model = row.model_name || "(unset)";
      lines.push(`  ${row.id}  ${title}  [${model}, ${row.status}, ${formatDate(row.updated_at)}]`);
    }
    return lines.join("\n");
  }

  function resumeSession(sessionId: string): boolean {
    const id = sessionId.trim();
    if (!id || !session.resumeConversation(id)) return false;
    const messages = store.loadMessages(id);
    setItems([]);
    for (const msg of messages) {
      if (msg.role !== "user" && msg.role !== "assistant") continue;
      push({
        kind: "message",
        id: msg.id || nextId("m"),
        role: msg.role,
        content: msg.content,
        reasoning: msg.reasoning ?? "",
      });
    }
    resetLiveTurnState();
    note(`Resumed session ${id}`);
    return true;
  }

  async function restartRuntime(): Promise<string> {
    if (busy()) return "Cannot restart while a turn is running.";
    await session.restartRuntime();
    resolver = new RuntimePolicyResolver(config);
    resetLiveTurnState();
    setToolCount(session.toolCount);
    setMcpStatusVersion((v) => v + 1);
    setConfigVersion((v) => v + 1);
    return "Workflow runtime restarted.";
  }

  async function compactContext(): Promise<string> {
    if (busy()) return "Cannot compact while a turn is running.";
    try {
      const changed = await session.compactContext({ force: true, workflow: workflow() });
      return changed ? "Context compacted." : "Context is already within model budget.";
    } catch (exc) {
      return `Context compaction failed: ${exc instanceof Error ? exc.message : String(exc)}`;
    }
  }

  function pluginMcpRows(): PluginMcpRow[] {
    configVersion();
    return config.mcpServers.map((server) => ({
      name: server.name,
      transport: server.transport,
      target: mcpTarget(server),
      enabled: server.enabled,
    }));
  }

  function currentWorkflowAgent(): AgentConfig | null {
    const wf = workflow();
    return config.agents.find((item) => item.name === wf) ?? null;
  }

  function pluginSkillRows(): PluginSkillRow[] {
    configVersion();
    const agent = currentWorkflowAgent();
    const enabled = new Set(agent?.skills ?? []);
    const wildcard = enabled.has("*");
    return listAvailableSkills().map((name) => ({
      name,
      enabled: wildcard || enabled.has(name),
    }));
  }

  function setPluginSkillSearchQuery(value: string): void {
    setPluginSkillSearchQuerySig(value);
  }

  function hydrateSkillSearchRows(rows: { name: string; description: string }[]): PluginSkillSearchRow[] {
    configVersion();
    const installed = new Set(listAvailableSkills());
    const agent = currentWorkflowAgent();
    const enabled = new Set(agent?.skills ?? []);
    const wildcard = enabled.has("*");
    return rows.map((row) => ({
      name: row.name,
      description: row.description,
      installed: installed.has(row.name),
      enabled: wildcard || enabled.has(row.name),
    }));
  }

  function selectedPluginRows(): Array<PluginMcpRow | PluginSkillRow> {
    return pluginSection() === "mcp" ? pluginMcpRows() : pluginSkillRows();
  }

  function openPlugin(): void {
    setConfigOpen(false);
    setModelPickerOpen(false);
    setRagOpen(false);
    setWorkflowPickerOpen(false);
    setGraphOpen(false);
    setPluginSectionSig("mcp");
    setPluginStep("browse");
    setPluginSelectedIndex(0);
    setPluginOpen(true);
  }

  function closePlugin(): void {
    setPluginOpen(false);
  }

  function setPluginSection(section: PluginSection): void {
    setPluginSectionSig(section);
    setPluginStep("browse");
    setPluginSelectedIndex(0);
  }

  function movePluginSelection(delta: number): void {
    const rows = selectedPluginRows();
    if (rows.length === 0) {
      setPluginSelectedIndex(0);
      return;
    }
    setPluginSelectedIndex((idx) => (idx + delta + rows.length) % rows.length);
  }

  function newPluginMcp(): void {
    setEditingMcpName("");
    setPluginMcpDraft({
      name: uniqueMcpName(),
      transport: "http",
      url: "",
      headers: "",
      command: "",
      args: "",
      env: "",
      enabled: "true",
      scope: "local",
    });
    setPluginSectionSig("mcp");
    setPluginStep("mcp-fields");
  }

  function editPluginMcp(): void {
    const row = pluginMcpRows()[pluginSelectedIndex()];
    const server = row ? config.mcpServers.find((item) => item.name === row.name) : undefined;
    if (!server) return newPluginMcp();
    setEditingMcpName(server.name);
    setPluginMcpDraft({
      name: server.name,
      transport: normalizeMcpTransport(server.transport),
      url: server.url,
      headers: server.headers,
      command: server.command,
      args: server.args,
      env: server.env,
      enabled: server.enabled ? "true" : "false",
      scope: mcpServerScope(server.name),
    });
    setPluginSectionSig("mcp");
    setPluginStep("mcp-fields");
  }

  function setPluginMcpField(key: keyof PluginMcpDraft, value: string): void {
    setPluginMcpDraft(key, value);
  }

  function backToPluginBrowse(): void {
    setPluginStep("browse");
  }

  function uniqueMcpName(base = "new-mcp"): string {
    const names = new Set(config.mcpServers.map((server) => server.name));
    if (!names.has(base)) return base;
    let idx = 2;
    while (names.has(`${base}-${idx}`)) idx += 1;
    return `${base}-${idx}`;
  }

  function normalizeMcpTransport(value: string): "http" | "sse" | "stdio" {
    if (value === "streamable_http") return "http";
    return value === "http" || value === "sse" || value === "stdio" ? value : "stdio";
  }

  function normalizePluginScope(value: string): "local" | "global" {
    const scope = value.trim().toLowerCase();
    return scope === "global" ? "global" : "local";
  }

  function cloneMcpServer(server: McpServerConfig): McpServerConfig {
    return new McpServerConfig({ ...server });
  }

  function mergedMcpServers(): McpServerConfig[] {
    const byName = new Map<string, McpServerConfig>();
    const order: string[] = [];
    for (const server of [...loadGlobalMcpServers(), ...loadLocalMcpServers()]) {
      const name = server.name.trim();
      if (!name) continue;
      if (!byName.has(name)) order.push(name);
      byName.set(name, server);
    }
    return order.map((name) => byName.get(name)!);
  }

  function refreshMergedMcpServers(): void {
    config.mcpServers = mergedMcpServers();
  }

  function mcpServerScope(name: string): "local" | "global" {
    if (loadLocalMcpServers().some((server) => server.name === name)) return "local";
    if (loadGlobalMcpServers().some((server) => server.name === name)) return "global";
    return "local";
  }

  function saveMcpServerToScope(server: McpServerConfig, scope: "local" | "global", oldName = server.name): string {
    const current = scope === "global" ? loadGlobalMcpServers() : loadLocalMcpServers();
    const next = current.filter((item) => item.name !== oldName && item.name !== server.name);
    next.push(cloneMcpServer(server));
    const savedPath = saveMcpServers(next, scope);
    refreshMergedMcpServers();
    return savedPath;
  }

  function removeMcpServerFromScope(name: string, scope: "local" | "global"): void {
    const current = scope === "global" ? loadGlobalMcpServers() : loadLocalMcpServers();
    if (!current.some((server) => server.name === name)) return;
    saveMcpServers(current.filter((server) => server.name !== name), scope);
  }

  function skillsDirForScope(scope: string): string {
    return normalizePluginScope(scope) === "global" ? paths.globalSkillsDir() : paths.localSkillsDir();
  }

  function skillFileForScope(scope: string, name: string): string {
    return join(skillsDirForScope(scope), name, "SKILL.md");
  }

  function jsonFieldError(value: string, field: string, kind: "array" | "object"): string | null {
    const trimmed = value.trim();
    if (!trimmed) return null;
    try {
      const parsed = JSON.parse(trimmed);
      if (kind === "array" && !Array.isArray(parsed)) return `${field} must be a JSON array.`;
      if (
        kind === "object" &&
        (parsed === null || typeof parsed !== "object" || Array.isArray(parsed))
      ) {
        return `${field} must be a JSON object.`;
      }
      return null;
    } catch {
      return `${field} must be valid JSON.`;
    }
  }

  function applyPluginMcpDraft(server: McpServerConfig): string | null {
    const name = pluginMcpDraft.name.trim();
    const transport = normalizeMcpTransport(pluginMcpDraft.transport);
    const url = pluginMcpDraft.url.trim();
    const command = pluginMcpDraft.command.trim();
    if (!name) return "MCP name is required.";
    if ((transport === "http" || transport === "sse") && !url) return "MCP URL is required.";
    if (transport === "stdio" && !command) return "MCP command is required.";
    const jsonError =
      transport === "stdio"
        ? jsonFieldError(pluginMcpDraft.args, "MCP args", "array") ??
          jsonFieldError(pluginMcpDraft.env, "MCP env", "object")
        : jsonFieldError(pluginMcpDraft.headers, "MCP headers", "object");
    if (jsonError) return jsonError;

    server.name = name;
    server.enabled = parseBool(pluginMcpDraft.enabled);
    server.transport = transport;
    if (transport === "stdio") {
      server.command = command;
      server.args = pluginMcpDraft.args.trim();
      server.env = pluginMcpDraft.env.trim();
      server.url = "";
      server.headers = "";
    } else {
      server.url = url;
      server.headers = pluginMcpDraft.headers.trim();
      server.command = "";
      server.args = "";
      server.env = "";
    }
    return null;
  }

  async function testPluginMcp(): Promise<string> {
    if (busy()) return "Cannot test MCP while a turn is running.";
    const server = new McpServerConfig();
    const error = applyPluginMcpDraft(server);
    if (error) return error;
    const { McpClientPool } = await import("@/engine/mcpPool");
    const { McpServerDTO } = await import("@/engine/dto");
    const pool = new McpClientPool();
    try {
      const dto = new McpServerDTO({
        id: null,
        name: server.name,
        transport: server.transport,
        enabled: server.enabled,
        command: server.command,
        args: server.args,
        env: server.env,
        cwd: server.cwd,
        encoding: server.encoding,
        url: server.url,
        headers: server.headers,
        timeout: server.timeout,
        sseReadTimeout: server.sseReadTimeout,
      });
      const tools = await pool.connect({ [server.name]: dto.toLangchainConfig() });
      return `MCP test OK: ${tools.length} tool${tools.length === 1 ? "" : "s"}`;
    } catch (exc) {
      debugLog("TUI MCP test failed", exc);
      return "MCP test failed";
    } finally {
      await pool.disconnect();
    }
  }

  async function savePluginMcp(): Promise<string | null> {
    if (busy()) return "Cannot change plugins while a turn is running.";
    const draftServer = new McpServerConfig();
    const draftError = applyPluginMcpDraft(draftServer);
    if (draftError) return draftError;
    const name = draftServer.name;
    const oldName = editingMcpName() || name;
    if (name !== oldName && config.mcpServers.some((server) => server.name === name)) {
      return `MCP server already exists: ${name}`;
    }
    const server = cloneMcpServer(config.mcpServers.find((item) => item.name === oldName) ?? new McpServerConfig({ name }));
    const error = applyPluginMcpDraft(server);
    if (error) return error;
    let savedPath: string;
    try {
      const targetScope = normalizePluginScope(pluginMcpDraft.scope);
      const previousScope = editingMcpName() ? mcpServerScope(oldName) : targetScope;
      if (previousScope !== targetScope) removeMcpServerFromScope(oldName, previousScope);
      savedPath = saveMcpServerToScope(server, targetScope, oldName);
    } catch (exc) {
      return exc instanceof Error ? exc.message : String(exc);
    }
    await restartRuntime();
    setConfigVersion((v) => v + 1);
    setPluginStep("browse");
    const idx = pluginMcpRows().findIndex((row) => row.name === name);
    if (idx >= 0) setPluginSelectedIndex(idx);
    note(`Saved MCP "${name}" -> ${savedPath}`);
    return null;
  }

  function newPluginSkill(): void {
    setPluginSkillSearchQuerySig("");
    setPluginSkillSearchRows([]);
    setPluginSkillDraft({
      name: "",
      prompt: "",
      enabled: "true",
      scope: "local",
    });
    setPluginSectionSig("skills");
    setPluginStep("skill-fields");
  }

  function setPluginSkillField(key: keyof PluginSkillDraft, value: string): void {
    setPluginSkillDraft(key, value);
  }

  function validPluginName(name: string): boolean {
    return /^[A-Za-z0-9_.-]+$/.test(name);
  }

  async function savePluginSkill(): Promise<string | null> {
    if (busy()) return "Cannot change plugins while a turn is running.";
    const name = pluginSkillDraft.name.trim();
    const prompt = pluginSkillDraft.prompt.trim();
    if (!name) return "Skill name is required.";
    if (!validPluginName(name)) return "Skill name may only contain letters, numbers, dot, dash, and underscore.";
    if (!prompt) return "Skill prompt is required.";
    const dir = join(skillsDirForScope(pluginSkillDraft.scope), name);
    if (existsSync(dir)) return `Skill directory already exists: ${dir}`;
    try {
      mkdirSync(dir, { recursive: true });
      writeFileSync(join(dir, "SKILL.md"), `${prompt}\n`, "utf-8");
      if (parseBool(pluginSkillDraft.enabled)) {
        const agent = agentForCurrentWorkflow();
        if (!agent.skills.includes(name)) agent.skills.push(name);
        saveAgents(config);
      }
    } catch (exc) {
      return exc instanceof Error ? exc.message : String(exc);
    }
    await restartRuntime();
    setConfigVersion((v) => v + 1);
    setPluginStep("browse");
    const idx = pluginSkillRows().findIndex((row) => row.name === name);
    if (idx >= 0) setPluginSelectedIndex(idx);
    note(`Saved skill "${name}" -> ${join(dir, "SKILL.md")}`);
    return null;
  }

  async function searchPluginSkills(): Promise<string | null> {
    const query = pluginSkillSearchQuery().trim();
    if (!query) return "Enter a SkillHub search query.";
    try {
      const { searchSkillHub } = await import("@/resources/skillshub");
      const results = await searchSkillHub(query);
      setPluginSkillSearchRows(hydrateSkillSearchRows(results));
      setPluginSelectedIndex(0);
      return results.length === 0 ? "No SkillHub skills found." : null;
    } catch (exc) {
      debugLog("SkillHub search failed", exc);
      return `SkillHub search failed: ${exc instanceof Error ? exc.message : String(exc)}`;
    }
  }

  async function installPluginSkill(name: string): Promise<string | null> {
    if (busy()) return "Cannot change plugins while a turn is running.";
    const skillName = name.trim();
    if (!skillName) return "No SkillHub skill selected.";
    if (!validPluginName(skillName)) return "Skill name may only contain letters, numbers, dot, dash, and underscore.";
    const scope = normalizePluginScope(pluginSkillDraft.scope);
    const skillPath = skillFileForScope(scope, skillName);
    try {
      const { installSkillFromHub } = await import("@/resources/skillshub");
      const installed = existsSync(skillPath)
        ? { name: skillName, path: skillPath, installed: false }
        : await installSkillFromHub(skillName, { targetDir: skillsDirForScope(scope) });
      if (parseBool(pluginSkillDraft.enabled)) {
        const agent = agentForCurrentWorkflow();
        if (!agent.skills.includes(skillName)) agent.skills.push(skillName);
        saveAgents(config);
      }
      await restartRuntime();
      setConfigVersion((v) => v + 1);
      setPluginStep("browse");
      setPluginSectionSig("skills");
      const idx = pluginSkillRows().findIndex((row) => row.name === skillName);
      if (idx >= 0) setPluginSelectedIndex(idx);
      note(`${installed.installed ? "Installed" : "Enabled"} SkillHub skill "${skillName}" -> ${installed.path}`);
      return null;
    } catch (exc) {
      debugLog("SkillHub install failed", exc);
      return `SkillHub install failed: ${exc instanceof Error ? exc.message : String(exc)}`;
    }
  }

  async function toggleSelectedPlugin(): Promise<string | null> {
    if (busy()) return "Cannot change plugins while a turn is running.";
    if (pluginSection() === "mcp") {
      const row = pluginMcpRows()[pluginSelectedIndex()];
      const server = row ? cloneMcpServer(config.mcpServers.find((item) => item.name === row.name) ?? new McpServerConfig()) : undefined;
      if (!server) return "No MCP server selected.";
      server.enabled = !server.enabled;
      let savedPath: string;
      try {
        savedPath = saveMcpServerToScope(server, mcpServerScope(server.name));
      } catch (exc) {
        return exc instanceof Error ? exc.message : String(exc);
      }
      await restartRuntime();
      setConfigVersion((v) => v + 1);
      note(`MCP "${server.name}" ${server.enabled ? "enabled" : "disabled"} -> ${savedPath}`);
      return null;
    }

    const row = pluginSkillRows()[pluginSelectedIndex()];
    if (!row) return "No skill selected.";
    if (!listAvailableSkills().includes(row.name)) return `Unknown skill: ${row.name}`;
    const agent = agentForCurrentWorkflow();
    const available = listAvailableSkills();
    if (agent.skills.includes("*")) {
      agent.skills = available.filter((name) => name !== row.name);
    } else if (agent.skills.includes(row.name)) {
      agent.skills = agent.skills.filter((name) => name !== row.name);
    } else {
      agent.skills.push(row.name);
    }
    let savedPath: string;
    try {
      savedPath = saveAgents(config);
    } catch (exc) {
      return exc instanceof Error ? exc.message : String(exc);
    }
    await restartRuntime();
    setConfigVersion((v) => v + 1);
    note(`skill "${row.name}" ${pluginSkillRows()[pluginSelectedIndex()]?.enabled ? "enabled" : "disabled"} for ${workflow()} -> ${savedPath}`);
    return null;
  }

  function pluginReport(): string {
    const lines = [
      "plugins:",
      "  usage:",
      "    /plugin add mcp <name> <url-or-command> [--global]",
      "    /plugin add skill <name> [--global]",
      "    /plugin enable mcp <name>",
      "    /plugin disable mcp <name>",
      "    /plugin enable skill <name>",
      "    /plugin disable skill <name>",
      `  local mcp: ${paths.localMcpFile()}`,
      `  global mcp: ${paths.globalMcpFile()}`,
      `  local skills: ${paths.localSkillsDir()}`,
      `  global skills: ${paths.globalSkillsDir()}`,
      "  mcp servers:",
    ];
    if (config.mcpServers.length === 0) {
      lines.push("    (none)");
    } else {
      for (const server of config.mcpServers) {
        const target =
          server.transport === "stdio" ? [server.command, server.args].filter(Boolean).join(" ") : server.url;
        lines.push(
          `    - ${server.name}: ${server.transport}, ${boolStatus(server.enabled)}` +
            (target ? `, ${target}` : ""),
        );
      }
    }
    lines.push(`  skills: ${formatList(listAvailableSkills())}`);
    return lines.join("\n");
  }

  function agentForCurrentWorkflow(): AgentConfig {
    const wf = workflow();
    let agent = config.agents.find((item) => item.name === wf);
    if (!agent) {
      agent = new AgentConfig({ name: wf, model: "default" });
      config.agents.push(agent);
    }
    return agent;
  }

  async function pluginCommand(args: string): Promise<string> {
    const parts = args.trim().split(/\s+/).filter(Boolean);
    if (parts.length === 0) return pluginReport();
    const [action, kind, name, ...rest] = parts;
    const normalizedAction = (action ?? "").toLowerCase();
    const normalizedKind = (kind ?? "").toLowerCase();
    const pluginName = (name ?? "").trim();
    if (!["add", "enable", "disable"].includes(normalizedAction) || !["mcp", "skill"].includes(normalizedKind) || !pluginName) {
      return pluginReport();
    }
    const scopeFlag = rest.includes("--global") ? "global" : "local";
    const targetParts = rest.filter((part) => part !== "--global" && part !== "--local");

    if (normalizedKind === "mcp") {
      const existing = config.mcpServers.find((server) => server.name === pluginName);
      if (normalizedAction === "add") {
        const target = targetParts.join(" ").trim();
        if (!target) return "usage: /plugin add mcp <name> <url-or-command> [--global]";
        const server = cloneMcpServer(existing ?? new McpServerConfig({ name: pluginName }));
        server.enabled = true;
        if (/^https?:\/\//i.test(target)) {
          server.transport = "http";
          server.url = target;
          server.command = "";
          server.args = "";
        } else {
          server.transport = "stdio";
          server.command = target;
          server.url = "";
        }
        const targetScope = normalizePluginScope(scopeFlag);
        const previousScope = existing ? mcpServerScope(pluginName) : targetScope;
        if (previousScope !== targetScope) removeMcpServerFromScope(pluginName, previousScope);
        const savedPath = saveMcpServerToScope(server, targetScope);
        await restartRuntime();
        return `MCP ${pluginName} enabled.\nsaved: ${savedPath}`;
      } else {
        if (!existing) return `unknown MCP server: ${pluginName}`;
        const server = cloneMcpServer(existing);
        server.enabled = normalizedAction === "enable";
        const savedPath = saveMcpServerToScope(server, mcpServerScope(pluginName));
        await restartRuntime();
        return `MCP ${pluginName} ${normalizedAction === "disable" ? "disabled" : "enabled"}.\nsaved: ${savedPath}`;
      }
    }

    const availableSkills = listAvailableSkills();
    if (normalizedAction === "add") {
      const previousEnabled = pluginSkillDraft.enabled;
      const previousScope = pluginSkillDraft.scope;
      setPluginSkillDraft("enabled", "true");
      setPluginSkillDraft("scope", scopeFlag);
      try {
        const result = await installPluginSkill(pluginName);
        return result ?? `SkillHub skill ${pluginName} installed and enabled for ${workflow()}.`;
      } finally {
        setPluginSkillDraft("enabled", previousEnabled);
        setPluginSkillDraft("scope", previousScope);
      }
    }
    if (!availableSkills.includes(pluginName)) {
      return `unknown skill: ${pluginName}\ninstalled: ${formatList(availableSkills)}`;
    }
    const agent = agentForCurrentWorkflow();
    if (normalizedAction === "disable") {
      agent.skills = agent.skills.filter((skill) => skill !== pluginName);
    } else {
      if (!agent.skills.includes(pluginName)) agent.skills.push(pluginName);
    }
    const savedPath = saveAgents(config);
    await restartRuntime();
    return `skill ${pluginName} ${normalizedAction === "disable" ? "disabled" : "enabled"} for ${workflow()}.\nsaved: ${savedPath}`;
  }

  function ragKnowledgeBaseRows(): RagKnowledgeBaseRow[] {
    ragVersion();
    return config.rag.knowledgeBases.map((kb) => ({
      name: kb.name,
      backend: kb.backend,
      target:
        kb.backend === "chroma_http"
          ? `${kb.chromaUrl || "(unset)"} collection=${kb.collectionName || kb.name || "(unset)"}`
          : knowledgeBaseChromaPath(kb),
      docsPath: kb.docsPath || "(default)",
      enabled: kb.enabled,
    }));
  }

  function openRag(): void {
    setConfigOpen(false);
    setModelPickerOpen(false);
    setPluginOpen(false);
    setWorkflowPickerOpen(false);
    setGraphOpen(false);
    refreshRagModelDraft();
    setRagSectionSig("knowledge");
    setRagStep("browse");
    setRagSelectedIndex(0);
    setRagOpen(true);
  }

  function closeRag(): void {
    setRagOpen(false);
  }

  function setRagSection(section: RagSection): void {
    setRagSectionSig(section);
    setRagStep("browse");
    setRagSelectedIndex(0);
  }

  function moveRagSelection(delta: number): void {
    const rows = ragKnowledgeBaseRows();
    if (rows.length === 0) {
      setRagSelectedIndex(0);
      return;
    }
    setRagSelectedIndex((idx) => (idx + delta + rows.length) % rows.length);
  }

  function setRagModelField(key: keyof RagModelDraft, value: string): void {
    setRagModelDraft(key, value);
  }

  function setRagKnowledgeBaseField(key: keyof RagKnowledgeBaseDraft, value: string): void {
    setRagKnowledgeBaseDraft(key, value);
  }

  function setRagSearchField(key: keyof RagSearchDraft, value: string): void {
    setRagSearchDraft(key, value);
  }

  function backToRagBrowse(): void {
    setRagStep("browse");
  }

  function refreshRagModelDraft(): void {
    setRagModelDraft({
      embeddingBackend: config.rag.embeddingBackend || "huggingface",
      embeddingModel: config.rag.embeddingModel || "",
      embeddingApiBase: config.rag.embeddingApiBase || "",
      embeddingApiKey: config.rag.embeddingApiKey || "",
      embeddingLocalPath: config.rag.embeddingLocalPath || "",
      chunkSize: String(config.rag.chunkSize || 1200),
      chunkOverlap: String(config.rag.chunkOverlap || 150),
    });
  }

  function editRagModelSettings(): void {
    refreshRagModelDraft();
    setRagSectionSig("model");
    setRagStep("model-fields");
  }

  function editRagSearch(): void {
    setRagSectionSig("search");
    setRagStep("search-fields");
  }

  function newRagKnowledgeBase(): void {
    setEditingRagKnowledgeBaseName("");
    setRagKnowledgeBaseDraft({
      name: "",
      backend: "sarma_native",
      docsPath: "",
      chromaPath: "",
      chromaUrl: "",
      collectionName: "",
      headers: "",
      enabled: "true",
      scope: "local",
    });
    setRagSectionSig("knowledge");
    setRagStep("kb-fields");
  }

  function editRagKnowledgeBase(): void {
    const row = ragKnowledgeBaseRows()[ragSelectedIndex()];
    const kb = row ? config.rag.knowledgeBases.find((item) => item.name === row.name) : undefined;
    if (!kb) return newRagKnowledgeBase();
    setEditingRagKnowledgeBaseName(kb.name);
    setRagKnowledgeBaseDraft({
      name: kb.name,
      backend: kb.backend || "sarma_native",
      docsPath: kb.docsPath,
      chromaPath: kb.chromaPath,
      chromaUrl: kb.chromaUrl,
      collectionName: kb.collectionName,
      headers: kb.headers,
      enabled: kb.enabled ? "true" : "false",
      scope: "local",
    });
    setRagSectionSig("knowledge");
    setRagStep("kb-fields");
  }

  function selectedRagKnowledgeBase(): KnowledgeBaseConfig | null {
    const row = ragKnowledgeBaseRows()[ragSelectedIndex()];
    return row ? config.rag.knowledgeBases.find((kb) => kb.name === row.name) ?? null : null;
  }

  function scopedRagForKnowledgeBase(name: string, preferredScope = "local"): { rag: import("@/config").RagConfig; scope: "local" | "global" } {
    const local = loadLocalRagConfig();
    if (local.knowledgeBases.some((kb) => kb.name === name)) return { rag: local, scope: "local" };
    const global = loadGlobalRagConfig();
    if (global.knowledgeBases.some((kb) => kb.name === name)) return { rag: global, scope: "global" };
    const scope = normalizePluginScope(preferredScope);
    return { rag: scope === "global" ? global : local, scope };
  }

  function applyRagKnowledgeBaseDraft(): { kb: KnowledgeBaseConfig | null; error: string | null; scope: "local" | "global" } {
    const name = ragKnowledgeBaseDraft.name.trim();
    const backend = ragKnowledgeBaseDraft.backend.trim() === "chroma_http" ? "chroma_http" : "sarma_native";
    const scope = normalizePluginScope(ragKnowledgeBaseDraft.scope);
    if (!name) return { kb: null, error: "Knowledge base name is required.", scope };
    if (!validPluginName(name)) return { kb: null, error: "Knowledge base name may only contain letters, numbers, dot, dash, and underscore.", scope };
    if (backend === "chroma_http" && !ragKnowledgeBaseDraft.chromaUrl.trim()) {
      return { kb: null, error: "Chroma URL is required for Chroma HTTP.", scope };
    }
    if (backend === "chroma_http" && !ragKnowledgeBaseDraft.collectionName.trim()) {
      return { kb: null, error: "Collection is required for Chroma HTTP.", scope };
    }
    const headersError = jsonFieldError(ragKnowledgeBaseDraft.headers, "RAG headers", "object");
    if (headersError) return { kb: null, error: headersError, scope };
    const docsPath = ragKnowledgeBaseDraft.docsPath.trim();
    const chromaPath = ragKnowledgeBaseDraft.chromaPath.trim();
    return {
      scope,
      error: null,
      kb: new KnowledgeBaseConfig({
        name,
        backend,
        docsPath: docsPath ? resolve(docsPath) : "",
        chromaPath: chromaPath ? resolve(chromaPath) : "",
        chromaUrl: ragKnowledgeBaseDraft.chromaUrl.trim(),
        collectionName: ragKnowledgeBaseDraft.collectionName.trim(),
        headers: ragKnowledgeBaseDraft.headers.trim(),
        enabled: parseBool(ragKnowledgeBaseDraft.enabled),
      }),
    };
  }

  async function saveRagModelSettings(): Promise<string | null> {
    if (busy()) return "Cannot change RAG settings while a turn is running.";
    const chunkSize = parseContextSize(ragModelDraft.chunkSize);
    const chunkOverlap = parseContextSize(ragModelDraft.chunkOverlap);
    if (chunkSize === null) return "Chunk size must be a positive number.";
    if (chunkOverlap === null || chunkOverlap >= chunkSize) return "Chunk overlap must be positive and smaller than chunk size.";
    const backend = ragModelDraft.embeddingBackend.trim().toLowerCase();
    config.rag.embeddingBackend = backend === "api" ? "api" : "huggingface";
    config.rag.embeddingModel = ragModelDraft.embeddingModel.trim();
    config.rag.embeddingApiBase = ragModelDraft.embeddingApiBase.trim();
    config.rag.embeddingApiKey = ragModelDraft.embeddingApiKey.trim();
    config.rag.embeddingLocalPath = ragModelDraft.embeddingLocalPath.trim();
    config.rag.chunkSize = chunkSize;
    config.rag.chunkOverlap = chunkOverlap;
    let savedPath: string;
    try {
      savedPath = saveRagModel(config);
    } catch (exc) {
      return exc instanceof Error ? exc.message : String(exc);
    }
    await restartRuntime();
    setRagVersion((v) => v + 1);
    setRagStep("browse");
    note(`Saved RAG model settings -> ${savedPath}`);
    return null;
  }

  async function saveRagKnowledgeBase(): Promise<string | null> {
    if (busy()) return "Cannot change RAG knowledge bases while a turn is running.";
    const draft = applyRagKnowledgeBaseDraft();
    if (draft.error || !draft.kb) return draft.error ?? "Invalid knowledge base.";
    const oldName = editingRagKnowledgeBaseName() || draft.kb.name;
    const scoped = scopedRagForKnowledgeBase(oldName, draft.scope);
    if (draft.kb.name !== oldName) {
      scoped.rag.knowledgeBases = scoped.rag.knowledgeBases.filter((kb) => kb.name !== oldName);
      config.rag.knowledgeBases = config.rag.knowledgeBases.filter((kb) => kb.name !== oldName);
    }
    upsertKnowledgeBase(scoped.rag.knowledgeBases, draft.kb);
    upsertKnowledgeBase(config.rag.knowledgeBases, draft.kb);
    let savedPath: string;
    try {
      savedPath = saveRagKnowledgeBases(scoped.rag.knowledgeBases, scoped.scope);
    } catch (exc) {
      return exc instanceof Error ? exc.message : String(exc);
    }
    await restartRuntime();
    setRagVersion((v) => v + 1);
    setRagStep("browse");
    const idx = ragKnowledgeBaseRows().findIndex((row) => row.name === draft.kb!.name);
    if (idx >= 0) setRagSelectedIndex(idx);
    note(`Saved RAG knowledge base "${draft.kb.name}" -> ${savedPath}`);
    return null;
  }

  async function toggleSelectedRagKnowledgeBase(): Promise<string | null> {
    if (busy()) return "Cannot change RAG knowledge bases while a turn is running.";
    const kb = selectedRagKnowledgeBase();
    if (!kb) return "No RAG knowledge base selected.";
    const scoped = scopedRagForKnowledgeBase(kb.name);
    const target = scoped.rag.knowledgeBases.find((item) => item.name === kb.name);
    if (!target) return "No RAG knowledge base selected.";
    target.enabled = !target.enabled;
    kb.enabled = target.enabled;
    let savedPath: string;
    try {
      savedPath = saveRagKnowledgeBases(scoped.rag.knowledgeBases, scoped.scope);
    } catch (exc) {
      return exc instanceof Error ? exc.message : String(exc);
    }
    await restartRuntime();
    setRagVersion((v) => v + 1);
    note(`RAG knowledge base "${kb.name}" ${kb.enabled ? "enabled" : "disabled"} -> ${savedPath}`);
    return null;
  }

  async function deleteSelectedRagKnowledgeBase(): Promise<string | null> {
    if (busy()) return "Cannot change RAG knowledge bases while a turn is running.";
    const kb = selectedRagKnowledgeBase();
    if (!kb) return "No RAG knowledge base selected.";
    const scoped = scopedRagForKnowledgeBase(kb.name);
    scoped.rag.knowledgeBases = scoped.rag.knowledgeBases.filter((item) => item.name !== kb.name);
    config.rag.knowledgeBases = config.rag.knowledgeBases.filter((item) => item.name !== kb.name);
    let savedPath: string;
    try {
      savedPath = saveRagKnowledgeBases(scoped.rag.knowledgeBases, scoped.scope);
    } catch (exc) {
      return exc instanceof Error ? exc.message : String(exc);
    }
    await restartRuntime();
    setRagVersion((v) => v + 1);
    setRagSelectedIndex(0);
    note(`Deleted RAG knowledge base "${kb.name}" -> ${savedPath}`);
    return null;
  }

  async function chunkSelectedRagKnowledgeBase(): Promise<string | null> {
    if (busy()) return "Cannot chunk RAG knowledge bases while a turn is running.";
    const kb = selectedRagKnowledgeBase();
    if (!kb) return "No RAG knowledge base selected.";
    if (kb.backend === "chroma_http") return "Chroma HTTP knowledge bases are searched remotely and cannot be chunked locally.";
    try {
      const { chunkKnowledgeBase } = await import("@/resources/rag");
      const result = await chunkKnowledgeBase(kb, config.rag);
      note(`Chunked RAG "${kb.name}": ${result.files} file(s), ${result.chunks} chunk(s) -> ${result.outputPath}`);
      return null;
    } catch (exc) {
      return exc instanceof Error ? exc.message : String(exc);
    }
  }

  async function runRagSearch(): Promise<string | null> {
    const query = ragSearchDraft.query.trim();
    if (!query) return "Search query is required.";
    const topK = parseContextSize(ragSearchDraft.topK) ?? 5;
    try {
      const { searchKnowledgeBases } = await import("@/resources/rag");
      const result = await searchKnowledgeBases(config.rag, {
        query,
        knowledgeBase: ragSearchDraft.knowledgeBase.trim(),
        topK,
      });
      note(result);
      return null;
    } catch (exc) {
      return exc instanceof Error ? exc.message : String(exc);
    }
  }

  function ragReport(): string {
    const rag = config.rag;
    const lines = [
      "rag:",
      `  embedding_backend: ${rag.embeddingBackend}`,
      `  embedding_model: ${rag.embeddingModel || "(unset)"}`,
      `  embedding_api_base: ${rag.embeddingApiBase || "(unset)"}`,
      `  embedding_local_path: ${rag.embeddingLocalPath || "(default)"}`,
      `  chunk_size: ${rag.chunkSize}`,
      `  chunk_overlap: ${rag.chunkOverlap}`,
      "  knowledge_bases:",
    ];
    if (rag.knowledgeBases.length === 0) {
      lines.push("    (none)");
    } else {
      for (const kb of rag.knowledgeBases) {
        const target =
          kb.backend === "chroma_http"
            ? `${kb.chromaUrl || "(unset)"} collection=${kb.collectionName || kb.name || "(unset)"}`
            : knowledgeBaseChromaPath(kb);
        lines.push(
          `    - ${kb.name || "(unnamed)"}: ${boolStatus(kb.enabled)}, backend=${kb.backend}, ` +
            `docs=${kb.docsPath || "(default)"}, chroma=${target}`,
        );
      }
    }
    lines.push("  cli: sarma rag --help");
    return lines.join("\n");
  }

  function debugReport(arg = ""): string {
    const action = arg.trim().toLowerCase();
    if (["on", "enable", "enabled", "1", "true"].includes(action)) setDebugEnabled(true);
    if (["off", "disable", "disabled", "0", "false"].includes(action)) setDebugEnabled(false);
    debugLog("debug command invoked", { action: action || "status" });
    return [
      "debug:",
      `  enabled: ${debugEnabled() ? "yes" : "no"}`,
      `  log: ${debugLogFile()}`,
      "  usage: /debug on | /debug off | /debug",
      "  env: SARMA_DEBUG=1 SARMA_DEBUG_LOG=<path>",
    ].join("\n");
  }

  function setConfigSection(section: ConfigSection): void {
    setConfigSectionSig(section);
    setConfigStep("browse");
    setConfigSelectedIndex(0);
    setConfigWorkflowPane("workflows");
    setConfigWorkflowSelectedIndex(0);
    setConfigAgentSelectedIndex(0);
  }

  function selectConfigItem(index: number): void {
    const rows = configSection() === "models" ? configModelRows() : configWorkflowRows();
    if (rows.length === 0) {
      setConfigSelectedIndex(0);
      return;
    }
    const next = Math.max(0, Math.min(index, rows.length - 1));
    if (configSection() === "models") setConfigSelectedIndex(next);
    else {
      setConfigWorkflowSelectedIndex(next);
      setConfigAgentSelectedIndex(0);
    }
  }

  function moveConfigSelection(delta: number): void {
    if (configSection() === "workflow") {
      if (configWorkflowPane() === "agents") moveConfigAgentSelection(delta);
      else moveConfigWorkflowSelection(delta);
      return;
    }
    const rows = configModelRows();
    if (rows.length === 0) return;
    setConfigSelectedIndex((idx) => (idx + delta + rows.length) % rows.length);
  }

  function moveConfigWorkflowSelection(delta: number): void {
    const rows = configWorkflowRows();
    if (rows.length === 0) return;
    setConfigWorkflowSelectedIndex((idx) => (idx + delta + rows.length) % rows.length);
    setConfigAgentSelectedIndex(0);
  }

  function moveConfigAgentSelection(delta: number): void {
    const rows = configAgentRows();
    if (rows.length === 0) return;
    setConfigAgentSelectedIndex((idx) => (idx + delta + rows.length) % rows.length);
  }

  function newConfigModel(): void {
    setEditingModelName("");
    setModelDraft({
      name: uniqueModelName(),
      modelName: "",
      apiMode: "openai_compatible",
      baseUrl: "",
      apiKey: "",
      maxContextTokens: "128000",
      enabled: "true",
    });
    setConfigSectionSig("models");
    setConfigStep("model-fields");
  }

  function editConfigModel(): void {
    const model = modelAtSelection();
    if (!model) return newConfigModel();
    setEditingModelName(model.name);
    loadModelDraft(model);
    setConfigSectionSig("models");
    setConfigStep("model-fields");
  }

  function editConfigAgent(): void {
    const agent = agentAtSelection();
    if (!agent) return;
    loadAgentDraft(agent);
    setConfigSectionSig("workflow");
    setConfigStep("agent-fields");
  }

  async function deleteConfigModel(): Promise<string | null> {
    if (busy()) return "Cannot change models while a turn is running.";
    if (config.models.length <= 1) return "At least one model profile is required.";
    const model = modelAtSelection();
    if (!model) return "No model selected.";
    const idx = config.models.indexOf(model);
    config.models.splice(idx, 1);
    const replacement = config.models[Math.max(0, Math.min(idx, config.models.length - 1))]!;
    if (config.activeModel === model.name) config.activeModel = replacement.name;
    replaceAgentModelRefs(model.name, replacement.name);
    let savedPath: string;
    try {
      savedPath = saveModels(config);
      saveAgents(config);
    } catch (exc) {
      return exc instanceof Error ? exc.message : String(exc);
    }
    resolver = new RuntimePolicyResolver(config);
    await session.restartRuntime();
    setConfigVersion((v) => v + 1);
    selectConfigItem(Math.min(idx, config.models.length - 1));
    return `Deleted model "${model.name}". Saved: ${savedPath}`;
  }

  async function activateConfigModel(): Promise<string | null> {
    const model = modelAtSelection();
    if (!model) return "No model selected.";
    return selectModel(model.name);
  }

  function openModelPicker(): void {
    const rows = configModelRows();
    const activeIdx = rows.findIndex((row) => row.active);
    setModelPickerSelectedIndex(Math.max(0, activeIdx));
    setConfigOpen(false);
    setPluginOpen(false);
    setRagOpen(false);
    setWorkflowPickerOpen(false);
    setGraphOpen(false);
    setModelPickerOpen(true);
  }

  function closeModelPicker(): void {
    setModelPickerOpen(false);
  }

  function moveModelPickerSelection(delta: number): void {
    const rows = configModelRows();
    if (rows.length === 0) {
      setModelPickerSelectedIndex(0);
      return;
    }
    setModelPickerSelectedIndex((idx) => (idx + delta + rows.length) % rows.length);
  }

  async function activateModelPickerSelection(): Promise<string | null> {
    const row = modelAtPickerSelection();
    if (!row) return "No model profiles configured. Use /config to add one.";
    const result = await selectModel(row.name);
    if (result.startsWith("selected model:")) {
      setModelPickerOpen(false);
      return null;
    }
    return result;
  }

  function openConfig(): void {
    ensureWorkflowAgents();
    const activeIdx = Math.max(0, config.models.findIndex((model) => model.name === config.activeModel));
    const wfIdx = Math.max(0, configWorkflowNames().indexOf(workflow()));
    setConfigSectionSig("models");
    setConfigSelectedIndex(activeIdx);
    setConfigWorkflowSelectedIndex(wfIdx);
    setConfigAgentSelectedIndex(0);
    setConfigWorkflowPane("workflows");
    setConfigStep("browse");
    setModelPickerOpen(false);
    setPluginOpen(false);
    setRagOpen(false);
    setWorkflowPickerOpen(false);
    setGraphOpen(false);
    setConfigOpen(true);
  }

  function closeConfig(): void {
    setConfigOpen(false);
  }

  function chooseInterface(apiMode: string): void {
    if (API_MODES.includes(apiMode)) setModelDraft("apiMode", apiMode);
    setConfigStep("model-fields");
  }

  function backToInterface(): void {
    setConfigStep("browse");
  }

  function setModelField(key: keyof ModelDraft, value: string): void {
    setModelDraft(key, value);
  }

  function setAgentField(key: keyof AgentDraft, value: string): void {
    setAgentDraft(key, value);
  }

  function providerFromModelDraft(): { provider: ProviderConfig | null; error: string | null; name: string; modelId: string; ctx: number } {
    const name = modelDraft.name.trim() || "default";
    const modelId = modelDraft.modelName.trim();
    if (!modelId) return { provider: null, error: "Model ID is required.", name, modelId, ctx: 0 };
    const ctx = parseContextSize(modelDraft.maxContextTokens);
    if (ctx === null) {
      return {
        provider: null,
        error: "Context size must be a positive number (e.g. 128000, 200K, 1M).",
        name,
        modelId,
        ctx: 0,
      };
    }
    const oldName = editingModelName() || modelDraft.name.trim();
    const existingProvider = config.models.find((model) => model.name === oldName) ?? new ProviderConfig({ name });
    return {
      provider: new ProviderConfig({
        name,
        modelName: modelId,
        apiMode: API_MODES.includes(modelDraft.apiMode) ? modelDraft.apiMode : "openai_compatible",
        baseUrl: modelDraft.baseUrl.trim(),
        apiKey: modelDraft.apiKey,
        temperature: existingProvider.temperature,
        topP: existingProvider.topP,
        maxContextTokens: ctx,
        enabled: parseBool(modelDraft.enabled),
      }),
      error: null,
      name,
      modelId,
      ctx,
    };
  }

  async function testModel(): Promise<string> {
    if (busy()) return "Cannot test the model while a turn is running.";
    const draft = providerFromModelDraft();
    if (draft.error || !draft.provider) return draft.error ?? "Invalid model configuration.";
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 15_000);
    try {
      const { ModelFactory } = await import("@/engine/modelFactory");
      const model = new ModelFactory().initModel(providerToDto(draft.provider), null);
      const result = await model.invoke(
        [new HumanMessage({ content: "Reply with exactly: OK" })],
        { signal: controller.signal },
      );
      const text = messageContentText((result as { content?: unknown }).content).trim();
      return `Model test OK: ${draft.name} (${draft.modelId})${text ? ` -> ${truncateStatus(text, 120)}` : ""}`;
    } catch (exc) {
      debugLog("TUI model test failed", exc);
      return `Model test failed: ${exc instanceof Error ? exc.message : String(exc)}`;
    } finally {
      clearTimeout(timeout);
    }
  }

  async function saveModel(): Promise<string | null> {
    // Changing the model rebuilds the runtime (restartRuntime disconnects the
    // MCP pool and resets graph state). Doing that mid-turn would pull the rug
    // out from under the in-flight run, so refuse while busy.
    if (busy()) return "Cannot change the model while a turn is running.";
    const draft = providerFromModelDraft();
    if (draft.error || !draft.provider) return draft.error ?? "Invalid model configuration.";
    const { name, modelId, ctx, provider } = draft;
    const oldName = editingModelName() || modelDraft.name.trim();
    if (name !== oldName && config.models.some((model) => model.name === name)) {
      return `Model name already exists: ${name}`;
    }
    // Mutate the shared config object in place (Session holds the same ref).
    const editIdx = config.models.findIndex((model) => model.name === oldName);
    if (editIdx >= 0) config.models[editIdx] = provider;
    else config.upsertModel(provider);
    if (!config.models.some((model) => model.name === config.activeModel)) config.activeModel = name;
    if (oldName !== name) {
      if (config.activeModel === oldName) config.activeModel = name;
      replaceAgentModelRefs(oldName, name);
    }
    let savedPath: string;
    try {
      savedPath = saveModels(config);
      saveAgents(config);
    } catch (exc) {
      return exc instanceof Error ? exc.message : String(exc);
    }
    // Rebuild the runtime so the new model takes effect immediately.
    resolver = new RuntimePolicyResolver(config);
    await session.restartRuntime();
    setToolCount(session.toolCount);
    setMcpStatusVersion((v) => v + 1);
    setConfigVersion((v) => v + 1);
    setConfigStep("browse");
    const idx = config.models.findIndex((model) => model.name === name);
    if (idx >= 0) setConfigSelectedIndex(idx);
    note(`Saved model "${name}" (${modelId}, ${ctx.toLocaleString()} ctx) -> ${savedPath}`);
    return null;
  }

  async function saveAgent(): Promise<string | null> {
    if (busy()) return "Cannot change workflow config while a turn is running.";
    ensureWorkflowAgents();
    const agent = config.agents.find((item) => item.name === agentDraft.name);
    if (!agent) return `Unknown workflow agent: ${agentDraft.name}`;
    const modelName = agentDraft.model.trim() || "default";
    if (modelName !== "default" && !config.models.some((model) => model.name === modelName)) {
      return `Unknown model profile: ${modelName}`;
    }
    agent.model = modelName;
    agent.mcp = parseList(agentDraft.mcp, ["*"]);
    agent.skills = parseList(agentDraft.skills, []);
    let savedPath: string;
    try {
      savedPath = saveAgents(config);
    } catch (exc) {
      return exc instanceof Error ? exc.message : String(exc);
    }
    resolver = new RuntimePolicyResolver(config);
    await session.restartRuntime();
    setToolCount(session.toolCount);
    setMcpStatusVersion((v) => v + 1);
    setConfigVersion((v) => v + 1);
    setConfigStep("browse");
    note(`Saved workflow agent "${agent.name}" -> ${savedPath}`);
    return null;
  }

  // Initialize stages for the starting workflow.
  setStages(stageTemplate(workflow()));

  return {
    items,
    draft,
    draftReasoning,
    busy,
    status,
    workflow,
    modelName,
    toolCount,
    mcpStatuses,
    refreshMcpStatus,
    todoItems: () => todoItems,
    stages: () => stages,
    workflows: () => workflowNames,
    sessionId: () => session.conversationId,
    submit,
    cancelCurrentRun,
    setWorkflow,
    workflowPickerOpen,
    workflowPickerSelectedIndex,
    workflowRows,
    openWorkflowPicker,
    closeWorkflowPicker,
    moveWorkflowPickerSelection,
    activateWorkflowPickerSelection,
    graphOpen,
    workflowGraph,
    openGraph,
    closeGraph,
    newConversation,
    note,
    statusReport,
    graphReport,
    modelReport,
    selectModel,
    modelsReport,
    mcpReport,
    skillsReport,
    sessionsReport,
    resumeSession,
    restartRuntime,
    compactContext,
    pluginReport,
    pluginCommand,
    pluginOpen,
    pluginSection,
    pluginStep,
    pluginSelectedIndex,
    openPlugin,
    closePlugin,
    setPluginSection,
    movePluginSelection,
    pluginMcpRows,
    pluginSkillRows,
    pluginSkillSearchQuery,
    setPluginSkillSearchQuery,
    pluginSkillSearchRows,
    searchPluginSkills,
    installPluginSkill,
    newPluginMcp,
    editPluginMcp,
    toggleSelectedPlugin,
    pluginMcpDraft,
    setPluginMcpField,
    testPluginMcp,
    savePluginMcp,
    newPluginSkill,
    pluginSkillDraft,
    setPluginSkillField,
    savePluginSkill,
    backToPluginBrowse,
    ragReport,
    ragOpen,
    ragSection,
    ragStep,
    ragSelectedIndex,
    openRag,
    closeRag,
    setRagSection,
    moveRagSelection,
    ragKnowledgeBaseRows,
    editRagModelSettings,
    editRagSearch,
    newRagKnowledgeBase,
    editRagKnowledgeBase,
    toggleSelectedRagKnowledgeBase,
    deleteSelectedRagKnowledgeBase,
    chunkSelectedRagKnowledgeBase,
    ragModelDraft,
    ragKnowledgeBaseDraft,
    ragSearchDraft,
    setRagModelField,
    setRagKnowledgeBaseField,
    setRagSearchField,
    saveRagModelSettings,
    saveRagKnowledgeBase,
    runRagSearch,
    backToRagBrowse,
    debugReport,
    hasModel,
    modelPickerOpen,
    modelPickerSelectedIndex,
    openModelPicker,
    closeModelPicker,
    moveModelPickerSelection,
    activateModelPickerSelection,
    configOpen,
    configSection,
    configStep,
    openConfig,
    closeConfig,
    setConfigSection,
    configSelectedIndex,
    configWorkflowSelectedIndex,
    configAgentSelectedIndex,
    configWorkflowPane,
    configModelRows,
    configWorkflowRows,
    configAgentRows,
    selectConfigItem,
    moveConfigSelection,
    moveConfigWorkflowSelection,
    moveConfigAgentSelection,
    setConfigWorkflowPane,
    newConfigModel,
    editConfigModel,
    editConfigAgent,
    deleteConfigModel,
    activateConfigModel,
    chooseInterface,
    backToInterface,
    modelDraft,
    setModelField,
    agentDraft,
    setAgentField,
    testModel,
    saveModel,
    saveAgent,
    close,
  };
}

function providerToDto(provider: ProviderConfig): ModelProviderDTO {
  return {
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
    toDict() {
      return {
        id: null,
        name: provider.name,
        model_name: provider.modelName,
        api_mode: provider.apiMode,
        api_key: provider.apiKey,
        base_url: provider.baseUrl,
        temperature: provider.temperature,
        top_p: provider.topP,
        max_context_tokens: provider.maxContextTokens,
        enabled: provider.enabled,
      };
    },
  };
}
