import { expect, test, describe } from "bun:test";
import { AIMessage } from "@langchain/core/messages";
import { buildAgentMiddleware, buildAgentMiddlewareForModel, sarmaModelRetryMiddleware } from "@/runtime/middleware";
import { AgentRuntimeServices } from "@/runtime/services";
import { ModelFactory } from "@/engine/modelFactory";
import { ModelProviderDTO } from "@/engine/dto";

function model() {
  return new ModelFactory().initModel(
    new ModelProviderDTO({
      id: 1,
      name: "d",
      modelName: "gpt-4o-mini",
      apiMode: "openai_compatible",
      apiKey: "sk-x",
      baseUrl: "",
      temperature: 0,
      topP: 1,
      maxContextTokens: 128000,
      enabled: true,
    }),
  );
}

describe("middleware", () => {
  test("no-model build includes filesystem + retries, no summarization", () => {
    const mw = buildAgentMiddleware();
    const names = mw.map((m) => (m as { name: string }).name);
    expect(names).toContain("FilesystemMiddleware");
    expect(names).toContain("modelRetryMiddleware");
    expect(names).toContain("toolRetryMiddleware");
    expect(names).not.toContain("SummarizationMiddleware");
  });

  test("with-model build adds summarization", () => {
    const mw = buildAgentMiddlewareForModel(model());
    const names = mw.map((m) => (m as { name: string }).name);
    expect(names).toContain("SummarizationMiddleware");
    expect(mw.length).toBe(5);
  });

  test("model retry middleware normalizes internal message objects", async () => {
    const mw = sarmaModelRetryMiddleware();
    const result = await (mw as {
      wrapModelCall: (request: object, handler: (request: object) => Promise<object>) => Promise<unknown>;
    }).wrapModelCall({}, async () => ({ messages: [new AIMessage({ content: "ok" })] }));
    expect(AIMessage.isInstance(result)).toBe(true);
    expect((result as AIMessage).content).toBe("ok");
  });

  test("model retry middleware throws after retries instead of returning an error message", async () => {
    const mw = sarmaModelRetryMiddleware({ maxRetries: 1 });
    let calls = 0;
    const run = (mw as {
      wrapModelCall: (request: object, handler: (request: object) => Promise<object>) => Promise<unknown>;
    }).wrapModelCall({}, async () => {
      calls += 1;
      throw new Error("rate limited");
    });
    await expect(run).rejects.toThrow("Model call failed after 2 attempts: Error: rate limited");
    expect(calls).toBe(2);
  });

  test("model retry middleware rejects unknown response envelopes", async () => {
    const mw = sarmaModelRetryMiddleware({ maxRetries: 0 });
    const run = (mw as {
      wrapModelCall: (request: object, handler: (request: object) => Promise<object>) => Promise<unknown>;
    }).wrapModelCall({}, async () => ({ unexpected: true }));
    await expect(run).rejects.toThrow("Unsupported model response envelope");
  });

  test("model retry middleware never returns structured response envelopes", async () => {
    const mw = sarmaModelRetryMiddleware({ maxRetries: 0 });
    const run = (mw as {
      wrapModelCall: (request: object, handler: (request: object) => Promise<object>) => Promise<unknown>;
    }).wrapModelCall({}, async () => ({ structuredResponse: { next: "report" }, messages: [] }));
    await expect(run).rejects.toThrow("Unsupported model response envelope");
  });

  test("model retry middleware includes nested causes in failure text", async () => {
    const mw = sarmaModelRetryMiddleware({ maxRetries: 0 });
    const inner = new Error("expected AIMessage or Command, got object");
    const outer = new Error("Invalid response from wrapModelCall", { cause: inner });
    const run = (mw as {
      wrapModelCall: (request: object, handler: (request: object) => Promise<object>) => Promise<unknown>;
    }).wrapModelCall({}, async () => {
      throw outer;
    });
    await expect(run).rejects.toThrow(
      "Model call failed after 1 attempts: Error: Invalid response from wrapModelCall <- Error: expected AIMessage or Command, got object",
    );
  });
});

describe("AgentRuntimeServices", () => {
  test("create yields checkpointer + store", () => {
    const svc = AgentRuntimeServices.create();
    expect(svc.checkpointer).toBeDefined();
    expect(svc.store).toBeDefined();
    expect(svc.cache).toBeNull();
  });

  test("compileKwargs omits cache when null", () => {
    const svc = AgentRuntimeServices.create();
    const kwargs = svc.compileKwargs();
    expect(Object.keys(kwargs).sort()).toEqual(["checkpointer", "store"]);
  });
});
