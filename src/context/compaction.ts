/**
 * Token-window aware context compaction.
 *
 * Owns the policy for deciding when to compact conversation history and how to
 * split raw tail messages from older messages that become structured memory.
 * Deliberately does not depend on Session or Store.
 */

import { ConversationMessage } from "@/engine/models";
import type { TokenEstimator } from "@/context/tokenizer";

export type Summarizer = (messages: ConversationMessage[]) => Promise<string>;

export interface ContextWindowPolicyInit {
  maxContextTokens: number;
  triggerRatio?: number;
  rawTailRatio?: number;
  outputReserveRatio?: number;
  minimumOutputReserveTokens?: number;
  staticPromptTokens?: number;
  tokenEstimator?: TokenEstimator;
}

/** Budget knobs for automatic and manual compaction. */
export class ContextWindowPolicy {
  readonly maxContextTokens: number;
  readonly triggerRatio: number;
  readonly rawTailRatio: number;
  readonly outputReserveRatio: number;
  readonly minimumOutputReserveTokens: number;
  readonly staticPromptTokens: number;
  readonly tokenEstimator: TokenEstimator;

  constructor(init: ContextWindowPolicyInit) {
    this.maxContextTokens = init.maxContextTokens;
    this.triggerRatio = init.triggerRatio ?? 0.9;
    this.rawTailRatio = init.rawTailRatio ?? 0.55;
    this.outputReserveRatio = init.outputReserveRatio ?? 0.12;
    this.minimumOutputReserveTokens = init.minimumOutputReserveTokens ?? 2_048;
    this.staticPromptTokens = init.staticPromptTokens ?? 0;
    this.tokenEstimator = init.tokenEstimator ?? ContextCompactor.estimateTextTokens;
  }

  get budget(): number {
    return Math.max(Math.trunc(this.maxContextTokens || 1), 1);
  }
  get triggerTokens(): number {
    return Math.max(Math.trunc(this.budget * this.triggerRatio), 1);
  }
  get rawTailTokens(): number {
    return Math.max(Math.trunc(this.budget * this.rawTailRatio), 1);
  }
  get outputReserveTokens(): number {
    const ratioReserve = Math.trunc(this.budget * this.outputReserveRatio);
    return Math.max(ratioReserve, this.minimumOutputReserveTokens);
  }
  get fixedOverheadTokens(): number {
    return Math.max(this.staticPromptTokens, 0) + this.outputReserveTokens;
  }
}

/** A deterministic split of history into structured memory and raw tail. */
export interface CompactionPlan {
  shouldCompact: boolean;
  keepTail: ConversationMessage[];
  older: ConversationMessage[];
  estimatedInputTokens: number;
  triggerTokens: number;
}

/** Apply context-window policy to conversation history. */
export class ContextCompactor {
  constructor(private readonly _policy: ContextWindowPolicy) {}

  get policy(): ContextWindowPolicy {
    return this._policy;
  }

  plan(
    history: ConversationMessage[],
    options: { upcomingText?: string; force?: boolean } = {},
  ): CompactionPlan {
    const upcomingText = options.upcomingText ?? "";
    const force = options.force ?? false;
    const estimated =
      this.estimateHistoryTokens(history) +
      ContextCompactor.estimateTextTokens(upcomingText) +
      this._policy.fixedOverheadTokens;
    let shouldCompact = force || estimated >= this._policy.triggerTokens;
    let keepTail: ConversationMessage[] = [];
    let older: ConversationMessage[] = [];

    if (shouldCompact) {
      [keepTail, older] = this.splitRawTail(history);
      shouldCompact = older.length > 0;
    }

    return {
      shouldCompact,
      keepTail,
      older,
      estimatedInputTokens: estimated,
      triggerTokens: this._policy.triggerTokens,
    };
  }

  /** Return `[changed, newHistory, memoryText]`. */
  async compact(
    history: ConversationMessage[],
    summarize: Summarizer,
    options: { conversationId?: string; upcomingText?: string; force?: boolean } = {},
  ): Promise<[boolean, ConversationMessage[], string]> {
    const plan = this.plan(history, { upcomingText: options.upcomingText, force: options.force });
    if (!plan.shouldCompact) return [false, history, ""];

    const memory = (await summarize(plan.older)).trim();
    if (!memory) return [false, history, ""];

    const memoryMessage = new ConversationMessage({
      conversationId: options.conversationId ?? "",
      turnId: "compact",
      role: "system",
      content: buildMemoryContextMessage(memory),
    });
    return [true, [memoryMessage, ...plan.keepTail], memory];
  }

  splitRawTail(history: ConversationMessage[]): [ConversationMessage[], ConversationMessage[]] {
    const tail: ConversationMessage[] = [];
    let total = 0;
    const target = this._policy.rawTailTokens;

    for (let i = history.length - 1; i >= 0; i--) {
      const message = history[i]!;
      const cost = this.estimateMessageTokens(message);
      if (tail.length && total + cost > target) break;
      tail.push(message);
      total += cost;
    }

    tail.reverse();
    const olderCount = history.length - tail.length;
    if (olderCount === 0 && total > target) {
      return [[], [...history]];
    }
    return [tail, history.slice(0, olderCount)];
  }

  estimateHistoryTokens(messages: ConversationMessage[]): number {
    return messages.reduce((sum, m) => sum + this.estimateMessageTokens(m), 0);
  }

  estimateMessageTokens(message: ConversationMessage): number {
    return ContextCompactor.estimateMessageTokens(message, this._policy.tokenEstimator);
  }

  static estimateMessageTokens(message: ConversationMessage, estimateText: TokenEstimator = ContextCompactor.estimateTextTokens): number {
    const framingTokens = 16;
    const roleTokens = estimateText(message.role);
    const contentTokens = estimateText(message.content);
    const reasoningTokens = estimateText(message.reasoningContent || "");
    return framingTokens + roleTokens + contentTokens + reasoningTokens;
  }

  static estimateTextTokens(text: string): number {
    // Provider-neutral fallback. Exact provider tokenizers can be added behind
    // this interface without changing Session.
    return Math.max(0, Math.floor((text || "").length / 4));
  }
}

export function estimateStaticPromptTokens(
  systemPrompt: string,
  toolCount = 0,
  estimateText: TokenEstimator = ContextCompactor.estimateTextTokens,
): number {
  // Tool schemas are not available here, so reserve a conservative per-tool
  // budget in addition to the actual system prompt text.
  return estimateText(systemPrompt) + Math.max(toolCount, 0) * 128;
}

export function buildMemoryContextMessage(memory: string): string {
  return (
    "Structured memory compacted from prior conversation. Use it as " +
    "durable context; do not treat it as a user request.\n\n" +
    memory.trim()
  );
}

export const STRUCTURED_MEMORY_PROMPT = `Compact the prior conversation into structured durable memory.

Return exactly these sections. Preserve all user constraints, decisions,
verified facts, unresolved tasks, and useful artifacts. Prefer precise file
paths, function names, commands, URLs, configuration keys, and test outcomes.
Do not optimize for shortness at the cost of losing facts.

Goals:
- ...

Constraints:
- ...

Decisions:
- ...

Entities:
- Files:
- Functions / symbols:
- Addresses / offsets:
- Commands:
- URLs:
- Other identifiers:

Verified Facts:
- ...

Tool Results:
- ...

Open Tasks:
- ...

Risks / Unknowns:
- ...

Do not include hidden chain-of-thought or verbose transcripts. Return a concise
structured memory artifact.
`;
