import { expect, test, describe } from "bun:test";
import { AgentRunner } from "@/engine/agentRunner";
import { AgentFactory } from "@/engine/agentFactory";
import { McpClientPool } from "@/engine/mcpPool";
import { ConversationMessage } from "@/engine/models";
import { ModelProviderDTO } from "@/engine/dto";
import { StreamEventType } from "@/engine/enums";
import { AIMessageChunk } from "@langchain/core/messages";

function fakeProvider(): ModelProviderDTO {
  return new ModelProviderDTO({
    id: null,
    name: "fake",
    modelName: "fake-model",
    apiMode: "openai_compatible",
    apiKey: "x",
    baseUrl: "http://localhost",
    temperature: 0,
    topP: 1,
    maxContextTokens: 128000,
    enabled: true,
  });
}

/** A fake compiled agent whose stream() yields ruflo-style message chunks. */
function fakeAgent(chunks: unknown[]) {
  return {
    async *stream() {
      for (const c of chunks) yield c;
    },
  };
}

/** LangGraph.js stream() returns a Promise of an AsyncIterable. */
function fakePromiseStreamAgent(chunks: unknown[]) {
  return {
    async stream() {
      return (async function* () {
        for (const c of chunks) yield c;
      })();
    },
  };
}

describe("AgentRunner streaming (fake agent)", () => {
  test("accumulates assistant tokens from messages-mode chunks", async () => {
    // 2-tuple-with-ns format: [ns, mode, data] where data = [msg, metadata]
    const chunks = [
      [[], "messages", [new AIMessageChunk({ content: "Hello " }), {}]],
      [[], "messages", [new AIMessageChunk({ content: "world" }), {}]],
    ];
    const factory = {
      build: async () => [fakeAgent(chunks), []],
    } as unknown as AgentFactory;

    const runner = new AgentRunner({
      factory,
      pool: new McpClientPool(),
      provider: fakeProvider(),
      enabledServers: [],
      skill: null,
      history: [new ConversationMessage({ role: "user", content: "hi" })],
      systemPrompt: "sys",
      conversationId: "c1",
      turnId: "t1",
      mode: "ruflo",
    });

    const events = [];
    for await (const evt of runner.run("hi")) events.push(evt);

    expect(runner.assistantContent).toBe("Hello world");
    const tokenEvents = events.filter((e) => e.type === StreamEventType.TOKEN);
    expect(tokenEvents.length).toBe(2);
  });

  test("accumulates reasoning_content from additional_kwargs", async () => {
    const msg = new AIMessageChunk({ content: "answer", additional_kwargs: { reasoning_content: "thinking..." } });
    const chunks = [[[], "messages", [msg, {}]]];
    const factory = { build: async () => [fakeAgent(chunks), []] } as unknown as AgentFactory;

    const runner = new AgentRunner({
      factory,
      pool: new McpClientPool(),
      provider: fakeProvider(),
      enabledServers: [],
      skill: null,
      history: [],
      systemPrompt: "",
      conversationId: "c1",
      turnId: "t1",
      mode: "ruflo",
    });

    for await (const _ of runner.run("q")) void _;
    expect(runner.reasoningContent).toBe("thinking...");
    expect(runner.assistantContent).toBe("answer");
  });

  test("awaits Promise-wrapped LangGraph stream results", async () => {
    const chunks = [[[], "messages", [new AIMessageChunk({ content: "streamed" }), {}]]];
    const factory = { build: async () => [fakePromiseStreamAgent(chunks), []] } as unknown as AgentFactory;

    const runner = new AgentRunner({
      factory,
      pool: new McpClientPool(),
      provider: fakeProvider(),
      enabledServers: [],
      skill: null,
      history: [],
      systemPrompt: "",
      conversationId: "c1",
      turnId: "t1",
      mode: "ruflo",
    });

    const events = [];
    for await (const evt of runner.run("q")) events.push(evt);

    expect(runner.assistantContent).toBe("streamed");
    expect(events.some((e) => e.type === StreamEventType.TOKEN)).toBe(true);
  });

  test("builds audit graph input with audit_task", async () => {
    let captured: Record<string, unknown> | null = null;
    const agent = {
      async *stream(input: Record<string, unknown>) {
        captured = input;
        return;
        yield;
      },
    };
    const factory = { build: async () => [agent, []] } as unknown as AgentFactory;

    const runner = new AgentRunner({
      factory,
      pool: new McpClientPool(),
      provider: fakeProvider(),
      enabledServers: [],
      skill: null,
      history: [],
      systemPrompt: "",
      conversationId: "c1",
      turnId: "t1",
      mode: "audit",
    });

    for await (const _ of runner.run("find bugs")) void _;
    expect(captured).not.toBeNull();
    expect(captured!.audit_task).toBe("find bugs");
    expect(captured!.current_stage).toBe("");
  });

  test("finalContent falls back to assistant tokens for ruflo", async () => {
    const chunks = [[[], "messages", [new AIMessageChunk({ content: "answer" }), {}]]];
    const factory = { build: async () => [fakeAgent(chunks), []] } as unknown as AgentFactory;
    const runner = new AgentRunner({
      factory,
      pool: new McpClientPool(),
      provider: fakeProvider(),
      enabledServers: [],
      skill: null,
      history: [],
      systemPrompt: "",
      conversationId: "c1",
      turnId: "t1",
      mode: "ruflo",
    });
    for await (const _ of runner.run("q")) void _;
    expect(runner.finalContent).toBe("answer");
  });

  test("finalContent returns the report stage for audit, not concatenated stages", async () => {
    // Outer-namespace update chunks carry each node's stage_outputs return.
    const chunks = [
      [[], "updates", { recon: { stage_outputs: { recon: "recon notes" } } }],
      [[], "updates", { hunt: { stage_outputs: { hunt: "hunt notes" } } }],
      [[], "updates", { report: { stage_outputs: { report: "THE FINAL REPORT" } } }],
    ];
    const factory = { build: async () => [fakeAgent(chunks), []] } as unknown as AgentFactory;
    const runner = new AgentRunner({
      factory,
      pool: new McpClientPool(),
      provider: fakeProvider(),
      enabledServers: [],
      skill: null,
      history: [],
      systemPrompt: "",
      conversationId: "c1",
      turnId: "t1",
      mode: "audit",
    });
    for await (const _ of runner.run("find bugs")) void _;
    expect(runner.finalContent).toBe("THE FINAL REPORT");
  });
});
