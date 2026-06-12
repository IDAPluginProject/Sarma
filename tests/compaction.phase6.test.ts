import { expect, test, describe } from "bun:test";
import {
  ContextCompactor,
  ContextWindowPolicy,
  estimateStaticPromptTokens,
  buildMemoryContextMessage,
} from "@/context/compaction";
import { createTokenEstimator } from "@/context/tokenizer";
import { ConversationMessage } from "@/engine/models";

function msg(role: string, content: string): ConversationMessage {
  return new ConversationMessage({ role, content });
}

describe("ContextWindowPolicy", () => {
  test("derived budgets", () => {
    const p = new ContextWindowPolicy({ maxContextTokens: 100_000, triggerRatio: 0.9, rawTailRatio: 0.5 });
    expect(p.budget).toBe(100_000);
    expect(p.triggerTokens).toBe(90_000);
    expect(p.rawTailTokens).toBe(50_000);
    expect(p.outputReserveTokens).toBe(12_000);
  });

  test("output reserve respects minimum", () => {
    const p = new ContextWindowPolicy({ maxContextTokens: 1_000 });
    expect(p.outputReserveTokens).toBe(2_048);
  });
});

describe("ContextCompactor.plan", () => {
  test("does not compact small history", () => {
    const c = new ContextCompactor(new ContextWindowPolicy({ maxContextTokens: 100_000 }));
    const plan = c.plan([msg("user", "hi"), msg("assistant", "hello")]);
    expect(plan.shouldCompact).toBe(false);
  });

  test("force compacts when older messages exist", () => {
    const c = new ContextCompactor(
      new ContextWindowPolicy({ maxContextTokens: 1_000, rawTailRatio: 0.01 }),
    );
    const history = Array.from({ length: 10 }, (_, i) => msg("user", "x".repeat(400) + i));
    const plan = c.plan(history, { force: true });
    expect(plan.shouldCompact).toBe(true);
    expect(plan.older.length).toBeGreaterThan(0);
    expect(plan.keepTail.length).toBeGreaterThan(0);
  });

  test("auto-triggers when estimate exceeds trigger", () => {
    const c = new ContextCompactor(
      new ContextWindowPolicy({ maxContextTokens: 2_000, triggerRatio: 0.5, rawTailRatio: 0.1 }),
    );
    const history = Array.from({ length: 20 }, () => msg("user", "x".repeat(400)));
    const plan = c.plan(history);
    expect(plan.shouldCompact).toBe(true);
  });
});

describe("ContextCompactor.compact", () => {
  test("returns memory message + tail", async () => {
    const c = new ContextCompactor(
      new ContextWindowPolicy({ maxContextTokens: 1_000, rawTailRatio: 0.05 }),
    );
    const history = Array.from({ length: 8 }, (_, i) => msg("user", "y".repeat(300) + i));
    const [changed, newHistory, memory] = await c.compact(
      history,
      async () => "STRUCTURED MEMORY SUMMARY",
      { conversationId: "c1", force: true },
    );
    expect(changed).toBe(true);
    expect(memory).toBe("STRUCTURED MEMORY SUMMARY");
    expect(newHistory[0]!.role).toBe("system");
    expect(newHistory[0]!.content).toContain("STRUCTURED MEMORY SUMMARY");
    expect(newHistory.length).toBeLessThan(history.length);
  });

  test("no change when summarizer returns empty", async () => {
    const c = new ContextCompactor(
      new ContextWindowPolicy({ maxContextTokens: 1_000, rawTailRatio: 0.05 }),
    );
    const history = Array.from({ length: 8 }, (_, i) => msg("user", "z".repeat(300) + i));
    const [changed] = await c.compact(history, async () => "   ", { force: true });
    expect(changed).toBe(false);
  });

  test("no change when nothing to compact", async () => {
    const c = new ContextCompactor(new ContextWindowPolicy({ maxContextTokens: 100_000 }));
    const [changed, hist] = await c.compact([msg("user", "hi")], async () => "x");
    expect(changed).toBe(false);
    expect(hist.length).toBe(1);
  });
});

describe("token estimation", () => {
  test("estimateTextTokens approximates len/4", () => {
    expect(ContextCompactor.estimateTextTokens("abcd")).toBe(1);
    expect(ContextCompactor.estimateTextTokens("a".repeat(40))).toBe(10);
    expect(ContextCompactor.estimateTextTokens("")).toBe(0);
  });

  test("estimateStaticPromptTokens adds per-tool budget", () => {
    expect(estimateStaticPromptTokens("", 0)).toBe(0);
    expect(estimateStaticPromptTokens("", 2)).toBe(256);
  });

  test("provider tokenizer estimator counts text", () => {
    const estimate = createTokenEstimator({
      name: "p",
      modelName: "gpt-4o-mini",
      apiMode: "openai_compatible",
      apiKey: "",
      baseUrl: "",
      temperature: 0,
      topP: 1,
      maxContextTokens: 128_000,
      enabled: true,
    });
    expect(estimate("hello world")).toBeGreaterThan(0);
  });
});

describe("buildMemoryContextMessage", () => {
  test("wraps memory with durable-context framing", () => {
    const out = buildMemoryContextMessage("  facts  ");
    expect(out).toContain("Structured memory compacted");
    expect(out).toContain("facts");
    expect(out).not.toContain("  facts  ");
  });
});
