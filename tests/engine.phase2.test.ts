import { expect, test, describe } from "bun:test";
import { ChatAnthropic } from "@langchain/anthropic";
import { ChatOpenAI } from "@langchain/openai";
import { McpClientPool } from "@/engine/mcpPool";
import { ModelFactory } from "@/engine/modelFactory";
import { ProviderNotConfiguredError } from "@/engine/errors";
import { KnowledgeBaseDTO, McpServerDTO, ModelProviderDTO, RagConfigDTO } from "@/engine/dto";
import { MultiServerMCPClient } from "@langchain/mcp-adapters";
import {
  startHttpMcpServer,
  startSseMcpServer,
  stdioServerScriptPath,
} from "./fixtures/mockMcpServers";
import { ResolvedSkill } from "@/engine/models";
import { AgentFactory } from "@/engine/agentFactory";
import { makeAgentRunConfig } from "@/engine/models";

function provider(overrides: Partial<ConstructorParameters<typeof ModelProviderDTO>[0]> = {}) {
  return new ModelProviderDTO({
    id: 1,
    name: "default",
    modelName: "gpt-4o-mini",
    apiMode: "openai_compatible",
    apiKey: "sk-test",
    baseUrl: "",
    temperature: 0,
    topP: 1,
    maxContextTokens: 128000,
    enabled: true,
    ...overrides,
  });
}

describe("ModelFactory", () => {
  const factory = new ModelFactory();

  test("openai_compatible builds ChatOpenAI", () => {
    const m = factory.initModel(provider());
    expect(m).toBeInstanceOf(ChatOpenAI);
  });

  test("openai_responses sets useResponsesApi", () => {
    const m = factory.initModel(provider({ apiMode: "openai_responses" })) as ChatOpenAI;
    expect(m).toBeInstanceOf(ChatOpenAI);
    expect(m.useResponsesApi).toBe(true);
  });

  test("anthropic builds ChatAnthropic", () => {
    const m = factory.initModel(provider({ apiMode: "anthropic", modelName: "claude-x" }));
    expect(m).toBeInstanceOf(ChatAnthropic);
  });

  test("unknown api_mode throws", () => {
    expect(() => factory.initModel(provider({ apiMode: "bogus" }))).toThrow(ProviderNotConfiguredError);
  });

  test("skill preferred model + temperature override applied", () => {
    const skill = new ResolvedSkill({
      name: "s",
      preferredModelName: "deepseek-reasoner",
      temperatureOverride: 0.5,
    });
    const m = factory.initModel(provider(), skill) as ChatOpenAI;
    expect(m.model).toBe("deepseek-reasoner");
    expect(m.temperature).toBe(0.5);
  });
});

describe("McpClientPool", () => {
  test("empty config connects with no tools", async () => {
    const pool = new McpClientPool();
    const tools = await pool.connect({});
    expect(tools).toEqual([]);
    expect(pool.isConnected).toBe(true);
  });

  test("filterTools applies allow then deny", () => {
    const pool = new McpClientPool();
    const fakeTools = [
      { name: "ida__decompile" },
      { name: "ida__disasm" },
      { name: "ida__patch_bytes" },
    ] as never[];
    const allowed = pool.filterTools(
      fakeTools,
      new Set(["ida__decompile", "ida__disasm", "ida__patch_bytes"]),
      new Set(["ida__patch_bytes"]),
    );
    expect(allowed.map((t) => (t as { name: string }).name)).toEqual([
      "ida__decompile",
      "ida__disasm",
    ]);
  });

  test("null allowlist allows all", () => {
    const pool = new McpClientPool();
    const fakeTools = [{ name: "a" }, { name: "b" }] as never[];
    expect(pool.filterTools(fakeTools).length).toBe(2);
  });
});

function mcpServer(overrides: Partial<ConstructorParameters<typeof McpServerDTO>[0]> = {}) {
  return new McpServerDTO({
    id: null,
    name: "mock",
    transport: "http",
    enabled: true,
    command: "",
    args: "",
    env: "",
    cwd: "",
    encoding: "utf-8",
    url: "http://127.0.0.1:65535/mcp",
    headers: "",
    timeout: 60,
    sseReadTimeout: 300,
    ...overrides,
  });
}

// These guard the Python→JS adapter contract mismatch: the JS connection
// schema only accepts transport "http"/"sse"/"stdio" (NOT "streamable_http"),
// requires stdio `args` to be an array, and has no sseReadTimeout field.
describe("McpServerDTO.toLangchainConfig() — JS adapter contract", () => {
  test("http transport stays 'http' (not Python's streamable_http)", () => {
    const cfg = mcpServer({ transport: "http", url: "http://127.0.0.1:65535/mcp" }).toLangchainConfig();
    expect(cfg.transport).toBe("http");
    expect(cfg.url).toBe("http://127.0.0.1:65535/mcp");
    expect(cfg).not.toHaveProperty("sseReadTimeout");
  });

  test("legacy 'streamable_http' is normalized to 'http'", () => {
    const cfg = mcpServer({ transport: "streamable_http" }).toLangchainConfig();
    expect(cfg.transport).toBe("http");
  });

  test("stdio always emits an args array even when unconfigured", () => {
    const cfg = mcpServer({ transport: "stdio", command: "node", args: "" }).toLangchainConfig();
    expect(cfg.transport).toBe("stdio");
    expect(cfg.command).toBe("node");
    expect(cfg.args).toEqual([]);
  });

  // Constructing MultiServerMCPClient runs the adapter's zod validation, so an
  // accepted config proves the contract holds without needing a live server.
  test("http config is accepted by MultiServerMCPClient", () => {
    const cfg = mcpServer({ transport: "http" }).toLangchainConfig();
    expect(
      () =>
        new MultiServerMCPClient({
          mcpServers: { mock: cfg } as never,
          prefixToolNameWithServerName: true,
          additionalToolNamePrefix: "",
          throwOnLoadError: true,
        }),
    ).not.toThrow();
  });

  test("stdio config is accepted by MultiServerMCPClient", () => {
    const cfg = mcpServer({ transport: "stdio", command: "node", args: "" }).toLangchainConfig();
    expect(
      () =>
        new MultiServerMCPClient({
          mcpServers: { mock: cfg } as never,
          throwOnLoadError: true,
        }),
    ).not.toThrow();
  });
});

// Live end-to-end tests, one per transport. Each spins up a self-contained MCP
// server (official @modelcontextprotocol/sdk) exposing a `ping` tool, then
// drives it through the real DTO → McpClientPool.connect() → tools path. All
// servers bind to an OS-assigned ephemeral port (or a spawned child for stdio),
// so no externally installed/running MCP server (e.g. IDA-MCP) is required.
describe("McpClientPool.connect() — live servers (all transports)", () => {
  test("http transport returns prefixed tools", async () => {
    const srv = await startHttpMcpServer();
    const pool = new McpClientPool();
    try {
      const dto = mcpServer({ name: "svc", transport: "http", url: srv.url });
      const tools = await pool.connect({ svc: dto.toLangchainConfig() });
      expect(tools.map((t) => t.name)).toEqual(["svc__ping"]);
      expect(pool.isConnected).toBe(true);
      const status = pool.serverStatuses.find((s) => s.name === "svc");
      expect(status?.connected).toBe(true);
      expect(status?.toolCount).toBe(1);
    } finally {
      await pool.disconnect();
      await srv.close();
    }
  });

  test("sse transport returns prefixed tools", async () => {
    const srv = await startSseMcpServer();
    const pool = new McpClientPool();
    try {
      const dto = mcpServer({ name: "svc", transport: "sse", url: srv.url });
      const tools = await pool.connect({ svc: dto.toLangchainConfig() });
      expect(tools.map((t) => t.name)).toEqual(["svc__ping"]);
      expect(pool.isConnected).toBe(true);
    } finally {
      await pool.disconnect();
      await srv.close();
    }
  });

  test("stdio transport returns prefixed tools", async () => {
    const pool = new McpClientPool();
    try {
      const dto = mcpServer({
        name: "svc",
        transport: "stdio",
        command: process.execPath, // bun
        args: JSON.stringify([stdioServerScriptPath()]),
      });
      const tools = await pool.connect({ svc: dto.toLangchainConfig() });
      expect(tools.map((t) => t.name)).toEqual(["svc__ping"]);
      expect(pool.isConnected).toBe(true);
    } finally {
      await pool.disconnect();
    }
  });
});

describe("AgentFactory tool policy", () => {
  test("skill allowlist filters MCP tools before built-ins are appended", async () => {
    const factory = new AgentFactory(new McpClientPool(), { runtimeServices: null });
    const skill = new ResolvedSkill({
      name: "web-only",
      toolAllowlist: new Set(["web_search"]),
    });
    const [, tools] = await factory.build(
      makeAgentRunConfig({
        conversationId: "c",
        provider: provider(),
        userMessage: "q",
        mode: "ruflo",
        skill,
      }),
    );
    expect(tools.map((t) => t.name)).toEqual(["web_search", "fetch_url", "http_exchange", "packet_exchange"]);
  });

  test("RAG path changes invalidate cached agents", async () => {
    const factory = new AgentFactory(new McpClientPool(), { runtimeServices: null });
    const runConfig = (chromaPath: string) =>
      makeAgentRunConfig({
        conversationId: "c",
        provider: provider(),
        userMessage: "q",
        mode: "ruflo",
        rag: new RagConfigDTO({
          knowledgeBases: [
            new KnowledgeBaseDTO({
              name: "docs",
              docsPath: "",
              backend: "sarma_native",
              chromaPath,
              chromaUrl: "",
              collectionName: "",
              tenant: "",
              database: "",
              headers: "",
              enabled: true,
            }),
          ],
        }),
      });

    const [firstAgent] = await factory.build(runConfig("/tmp/a"));
    const [secondAgent] = await factory.build(runConfig("/tmp/b"));

    expect(secondAgent).not.toBe(firstAgent);
  });
});
