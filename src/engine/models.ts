/** Runtime conversation data models. */

import {
  AIMessage,
  HumanMessage,
  SystemMessage,
  type BaseMessage,
} from "@langchain/core/messages";
import { RagConfigDTO } from "@/engine/dto";
import type { ModelProviderDTO, McpServerDTO } from "@/engine/dto";

function uid(): string {
  return crypto.randomUUID().replace(/-/g, "").slice(0, 12);
}

function nowIso(): string {
  return new Date().toISOString();
}

// ---------------------------------------------------------------------------
// ConversationMessage
// ---------------------------------------------------------------------------

export interface ConversationMessageInit {
  id?: string;
  conversationId?: string;
  turnId?: string;
  role?: string; // system | user | assistant | tool
  content?: string;
  toolName?: string | null;
  toolCallId?: string | null;
  metadataJson?: string | null;
  reasoningContent?: string | null;
  createdAt?: string;
}

export class ConversationMessage {
  id: string;
  conversationId: string;
  turnId: string;
  role: string;
  content: string;
  toolName: string | null;
  toolCallId: string | null;
  metadataJson: string | null;
  reasoningContent: string | null;
  createdAt: string;

  constructor(init: ConversationMessageInit = {}) {
    this.id = init.id ?? uid();
    this.conversationId = init.conversationId ?? "";
    this.turnId = init.turnId ?? "";
    this.role = init.role ?? "";
    this.content = init.content ?? "";
    this.toolName = init.toolName ?? null;
    this.toolCallId = init.toolCallId ?? null;
    this.metadataJson = init.metadataJson ?? null;
    this.reasoningContent = init.reasoningContent ?? null;
    this.createdAt = init.createdAt ?? nowIso();
  }

  toDict(): Record<string, unknown> {
    return {
      id: this.id,
      conversation_id: this.conversationId,
      turn_id: this.turnId,
      role: this.role,
      content: this.content,
      tool_name: this.toolName,
      tool_call_id: this.toolCallId,
      metadata_json: this.metadataJson,
      reasoning_content: this.reasoningContent,
      created_at: this.createdAt,
    };
  }

  /** Build from a snake_case persistence row (or null). */
  static fromDict(data: Record<string, unknown> | null | undefined): ConversationMessage {
    if (!data) return new ConversationMessage();
    return new ConversationMessage({
      id: data.id as string | undefined,
      conversationId: data.conversation_id as string | undefined,
      turnId: data.turn_id as string | undefined,
      role: data.role as string | undefined,
      content: data.content as string | undefined,
      toolName: (data.tool_name as string | null | undefined) ?? null,
      toolCallId: (data.tool_call_id as string | null | undefined) ?? null,
      metadataJson: (data.metadata_json as string | null | undefined) ?? null,
      reasoningContent: (data.reasoning_content as string | null | undefined) ?? null,
      createdAt: data.created_at as string | undefined,
    });
  }

  /** Convert to a LangChain BaseMessage so extra fields survive. */
  toLangchainMessage(): BaseMessage {
    if (this.role === "tool") {
      // Always degrade to text to avoid orphan ToolMessage issues. The
      // preceding AIMessage in history may lack tool_calls (e.g. after
      // compaction or summarization), which breaks providers that require
      // tool_calls before every ToolMessage.
      return new AIMessage({ content: this.toolHistoryFallbackText() });
    }

    // Thinking-mode LLMs (DeepSeek-R1 etc.) require reasoning_content to be
    // passed back verbatim on subsequent calls.
    const additionalKwargs: Record<string, unknown> = {};
    if (this.reasoningContent) {
      additionalKwargs.reasoning_content = this.reasoningContent;
    }

    if (this.role === "assistant") {
      return new AIMessage({ content: this.content, additional_kwargs: additionalKwargs });
    }
    if (this.role === "user") {
      return new HumanMessage(this.content);
    }
    if (this.role === "system") {
      return new SystemMessage(this.content);
    }

    // Fallback for unknown roles.
    return new HumanMessage({ content: this.content, additional_kwargs: additionalKwargs });
  }

  /**
   * Serialize persisted tool history without tool_call_id as plain text.
   *
   * Older rows and partial tool traces may not have a valid tool_call_id.
   * Those cannot be reconstructed as protocol-correct ToolMessage objects, so
   * we degrade them into assistant text instead of crashing replay.
   */
  private toolHistoryFallbackText(): string {
    const toolLabel = this.toolName || "tool";
    const content = this.content || "";

    let data: unknown = null;
    try {
      data = JSON.parse(content);
    } catch {
      data = null;
    }

    if (data && typeof data === "object" && !Array.isArray(data)) {
      const obj = data as Record<string, unknown>;
      const args = obj.args;
      const result = obj.result;
      const parts = [`Previous tool call: ${toolLabel}`];
      const argsEmpty =
        args === null ||
        args === undefined ||
        args === "" ||
        (Array.isArray(args) && args.length === 0) ||
        (typeof args === "object" && Object.keys(args as object).length === 0);
      if (!argsEmpty) {
        parts.push(`Args: ${stableStringify(args)}`);
      }
      if (result !== null && result !== undefined && result !== "") {
        parts.push(`Result: ${result}`);
      }
      return parts.join("\n");
    }

    if (content) {
      return `Previous tool call: ${toolLabel}\nResult: ${content}`;
    }
    return `Previous tool call: ${toolLabel}`;
  }
}

/** JSON stringify with sorted object keys (mirrors Python sort_keys=True). */
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

// ---------------------------------------------------------------------------
// Stream events (runtime → UI)
// ---------------------------------------------------------------------------

export interface StreamEventInit {
  type: string;
  conversationId?: string;
  turnId?: string;
  payload?: Record<string, unknown>;
  timestamp?: number;
}

export class StreamEvent {
  type: string;
  conversationId: string;
  turnId: string;
  payload: Record<string, unknown>;
  timestamp: number;

  constructor(init: StreamEventInit) {
    this.type = init.type;
    this.conversationId = init.conversationId ?? "";
    this.turnId = init.turnId ?? "";
    this.payload = init.payload ?? {};
    this.timestamp = init.timestamp ?? Date.now() / 1000;
  }

  toDict(): Record<string, unknown> {
    return {
      type: this.type,
      conversation_id: this.conversationId,
      turn_id: this.turnId,
      payload: this.payload,
      timestamp: this.timestamp,
    };
  }
}

// ---------------------------------------------------------------------------
// Resolved Skill (runtime)
// ---------------------------------------------------------------------------

/** Runtime-resolved Skill configuration (prompt overlay + tool filter). */
export class ResolvedSkill {
  id: number | null;
  name: string;
  systemPromptSuffix: string;
  toolAllowlist: Set<string> | null; // null = allow all
  toolDenylist: Set<string> | null; // null = deny none
  preferredModelName: string | null;
  temperatureOverride: number | null;

  constructor(init: Partial<{
    id: number | null;
    name: string;
    systemPromptSuffix: string;
    toolAllowlist: Set<string> | null;
    toolDenylist: Set<string> | null;
    preferredModelName: string | null;
    temperatureOverride: number | null;
  }> = {}) {
    this.id = init.id ?? null;
    this.name = init.name ?? "";
    this.systemPromptSuffix = init.systemPromptSuffix ?? "";
    this.toolAllowlist = init.toolAllowlist ?? null;
    this.toolDenylist = init.toolDenylist ?? null;
    this.preferredModelName = init.preferredModelName ?? null;
    this.temperatureOverride = init.temperatureOverride ?? null;
  }
}

/** Parse a skill config dict into a ResolvedSkill. */
export function resolveSkill(
  data: Record<string, unknown> | null | undefined,
): ResolvedSkill | null {
  if (!data) return null;

  let allowlist: Set<string> | null = null;
  let denylist: Set<string> | null = null;

  const allowJson = data.tool_allowlist_json as string | undefined;
  if (allowJson) {
    try {
      allowlist = new Set(JSON.parse(allowJson) as string[]);
    } catch {
      /* ignore */
    }
  }
  const denyJson = data.tool_denylist_json as string | undefined;
  if (denyJson) {
    try {
      denylist = new Set(JSON.parse(denyJson) as string[]);
    } catch {
      /* ignore */
    }
  }

  return new ResolvedSkill({
    id: (data.id as number | null | undefined) ?? null,
    name: (data.name as string | undefined) ?? "",
    systemPromptSuffix: (data.system_prompt_template as string | undefined) ?? "",
    toolAllowlist: allowlist,
    toolDenylist: denylist,
    preferredModelName: (data.model_override as string | undefined) || null,
    temperatureOverride: (data.temperature_override as number | null | undefined) ?? null,
  });
}

// ---------------------------------------------------------------------------
// Agent run config (single turn)
// ---------------------------------------------------------------------------

/** Complete configuration for a single agent run. */
export interface AgentRunConfig {
  conversationId: string;
  provider: ModelProviderDTO;
  skill: ResolvedSkill | null;
  enabledServers: McpServerDTO[];
  messageHistory: ConversationMessage[];
  userMessage: string;
  systemPrompt: string;
  mode: string; // ruflo | audit | audit-slim
  maxSteps: number;
  subagentProviders: Record<string, ModelProviderDTO>;
  subagentMcpAllow: Record<string, string[] | null>;
  subagentSkills: Record<string, ResolvedSkill | null>;
  rag: RagConfigDTO;
}

export function makeAgentRunConfig(
  init: Partial<AgentRunConfig> &
    Pick<AgentRunConfig, "conversationId" | "provider" | "userMessage">,
): AgentRunConfig {
  return {
    conversationId: init.conversationId,
    provider: init.provider,
    skill: init.skill ?? null,
    enabledServers: init.enabledServers ?? [],
    messageHistory: init.messageHistory ?? [],
    userMessage: init.userMessage,
    systemPrompt: init.systemPrompt ?? "",
    mode: init.mode ?? "ruflo",
    maxSteps: init.maxSteps ?? 100_000,
    subagentProviders: init.subagentProviders ?? {},
    subagentMcpAllow: init.subagentMcpAllow ?? {},
    subagentSkills: init.subagentSkills ?? {},
    rag: init.rag ?? new RagConfigDTO(),
  };
}
