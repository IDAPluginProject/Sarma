import { expect, test, describe } from "bun:test";
import { AIMessage, HumanMessage, SystemMessage } from "@langchain/core/messages";
import { McpServerDTO, ModelProviderDTO } from "@/engine/dto";
import { ConversationMessage, resolveSkill, StreamEvent } from "@/engine/models";

describe("McpServerDTO.toLangchainConfig", () => {
  test("stdio server parses args/env JSON", () => {
    const dto = new McpServerDTO({
      id: 1,
      name: "ida",
      transport: "stdio",
      enabled: true,
      command: "ida-mcp",
      args: '["--port", "7000"]',
      env: '{"KEY": "val"}',
      cwd: "/work",
      encoding: "utf-8",
      url: "",
      headers: "",
      timeout: 60,
      sseReadTimeout: 300,
    });
    const cfg = dto.toLangchainConfig();
    expect(cfg.transport).toBe("stdio");
    expect(cfg.command).toBe("ida-mcp");
    expect(cfg.args).toEqual(["--port", "7000"]);
    expect(cfg.env).toEqual({ KEY: "val" });
    expect(cfg.cwd).toBe("/work");
    expect(cfg.stderr).toBe("ignore");
    // utf-8 default is omitted
    expect(cfg.encoding).toBeUndefined();
  });

  test("http transport stays 'http' (JS adapter) with url/headers", () => {
    const dto = new McpServerDTO({
      id: 2,
      name: "remote",
      transport: "http",
      enabled: true,
      command: "",
      args: "",
      env: "",
      cwd: "",
      encoding: "utf-8",
      url: "https://example/mcp",
      headers: '{"Authorization": "Bearer x"}',
      timeout: 30,
      sseReadTimeout: 0,
    });
    const cfg = dto.toLangchainConfig();
    // JS @langchain/mcp-adapters uses literal "http" (NOT Python's
    // "streamable_http"); SSE fallback is handled internally.
    expect(cfg.transport).toBe("http");
    expect(cfg.url).toBe("https://example/mcp");
    expect(cfg.headers).toEqual({ Authorization: "Bearer x" });
    // timeout is a pool-level hint (seconds), stripped by the adapter.
    expect(cfg.timeout).toBe(30);
    // The JS streamable-HTTP schema has no sseReadTimeout field.
    expect(cfg).not.toHaveProperty("sseReadTimeout");
  });
});

describe("ConversationMessage.toLangchainMessage", () => {
  test("roles map to LangChain message classes", () => {
    expect(new ConversationMessage({ role: "user", content: "hi" }).toLangchainMessage()).toBeInstanceOf(HumanMessage);
    expect(new ConversationMessage({ role: "assistant", content: "yo" }).toLangchainMessage()).toBeInstanceOf(AIMessage);
    expect(new ConversationMessage({ role: "system", content: "s" }).toLangchainMessage()).toBeInstanceOf(SystemMessage);
  });

  test("reasoning_content survives on assistant messages", () => {
    const msg = new ConversationMessage({ role: "assistant", content: "x", reasoningContent: "because" });
    const lc = msg.toLangchainMessage() as AIMessage;
    expect(lc.additional_kwargs.reasoning_content).toBe("because");
  });

  test("tool role degrades to AIMessage text with args+result", () => {
    const msg = new ConversationMessage({
      role: "tool",
      toolName: "decompile",
      content: JSON.stringify({ args: { addr: "0x1000" }, result: "int main() {}" }),
    });
    const lc = msg.toLangchainMessage();
    expect(lc).toBeInstanceOf(AIMessage);
    const text = lc.content as string;
    expect(text).toContain("Previous tool call: decompile");
    expect(text).toContain('Args: {"addr":"0x1000"}');
    expect(text).toContain("Result: int main() {}");
  });

  test("tool role with plain content", () => {
    const msg = new ConversationMessage({ role: "tool", toolName: "x", content: "raw" });
    const text = (msg.toLangchainMessage().content as string);
    expect(text).toBe("Previous tool call: x\nResult: raw");
  });
});

describe("resolveSkill", () => {
  test("parses allow/deny json and overrides", () => {
    const skill = resolveSkill({
      id: 5,
      name: "idapython",
      system_prompt_template: "Use IDA.",
      tool_allowlist_json: '["decompile", "disasm"]',
      tool_denylist_json: '["patch_bytes"]',
      model_override: "gpt-x",
      temperature_override: 0.2,
    });
    expect(skill).not.toBeNull();
    expect(skill!.name).toBe("idapython");
    expect(skill!.toolAllowlist).toEqual(new Set(["decompile", "disasm"]));
    expect(skill!.toolDenylist).toEqual(new Set(["patch_bytes"]));
    expect(skill!.preferredModelName).toBe("gpt-x");
    expect(skill!.temperatureOverride).toBe(0.2);
  });

  test("null data returns null", () => {
    expect(resolveSkill(null)).toBeNull();
  });
});

describe("ModelProviderDTO + StreamEvent", () => {
  test("provider toDict uses snake_case", () => {
    const p = new ModelProviderDTO({
      id: 1, name: "default", modelName: "m", apiMode: "anthropic", apiKey: "k",
      baseUrl: "", temperature: 0, topP: 1, maxContextTokens: 200000, enabled: true,
    });
    expect(p.toDict().model_name).toBe("m");
    expect(p.toDict().max_context_tokens).toBe(200000);
  });

  test("stream event defaults", () => {
    const ev = new StreamEvent({ type: "token", payload: { content: "x" } });
    expect(ev.type).toBe("token");
    expect(ev.payload.content).toBe("x");
    expect(typeof ev.timestamp).toBe("number");
  });
});
