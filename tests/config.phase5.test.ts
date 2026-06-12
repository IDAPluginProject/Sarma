import { expect, test, describe, beforeEach, afterEach } from "bun:test";
import { existsSync, mkdtempSync, rmSync, writeFileSync, mkdirSync, statSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import {
  parseContextWindow,
  loadConfig,
  saveModels,
  saveAgents,
  saveMcpServers,
  initConfig,
  saveRagKnowledgeBases,
  ProviderConfig,
  McpServerConfig,
  KnowledgeBaseConfig,
  AgentConfig,
  CliConfig,
  WILDCARD,
} from "@/config";
import { loadSkill, loadSkills, listAvailableSkills } from "@/resources/skills";
import { Store } from "@/store";
import * as paths from "@/paths";

let tmpHome: string;
let tmpCwd: string;
let origHome: string | undefined;
let origCwd: string;

beforeEach(() => {
  tmpHome = mkdtempSync(join(tmpdir(), "sarma-home-"));
  tmpCwd = mkdtempSync(join(tmpdir(), "sarma-cwd-"));
  origHome = process.env.SARMA_HOME;
  origCwd = process.cwd();
  process.env.SARMA_HOME = tmpHome;
  process.chdir(tmpCwd);
});

afterEach(() => {
  process.chdir(origCwd);
  if (origHome === undefined) delete process.env.SARMA_HOME;
  else process.env.SARMA_HOME = origHome;
  rmSync(tmpHome, { recursive: true, force: true });
  rmSync(tmpCwd, { recursive: true, force: true });
});

describe("parseContextWindow", () => {
  test("plain integer", () => {
    expect(parseContextWindow(200000)).toBe(200000);
  });
  test("decimal suffixes with separators and spaces", () => {
    expect(parseContextWindow("200K")).toBe(200000);
    expect(parseContextWindow("200 K")).toBe(200000);
    expect(parseContextWindow("200kb")).toBe(200000);
    expect(parseContextWindow("0.2M")).toBe(200000);
    expect(parseContextWindow("1M")).toBe(1000000);
    expect(parseContextWindow("1 M")).toBe(1000000);
    expect(parseContextWindow("1.5M tokens")).toBe(1500000);
    expect(parseContextWindow("1_000_000")).toBe(1000000);
    expect(parseContextWindow("1,000,000")).toBe(1000000);
    expect(parseContextWindow("2GB")).toBe(2000000000);
  });
  test("default on null", () => {
    expect(parseContextWindow(null, 99)).toBe(99);
  });
  test("throws on non-positive and malformed values", () => {
    expect(() => parseContextWindow(0)).toThrow();
    expect(() => parseContextWindow("12x3")).toThrow();
    expect(() => parseContextWindow("1P")).toThrow();
    expect(() => parseContextWindow("1 MiB")).toThrow();
  });
});

describe("config load/save roundtrip", () => {
  test("loadConfig produces defaults", () => {
    const cfg = loadConfig();
    expect(cfg.activeModel).toBe("default");
    expect(cfg.models.length).toBeGreaterThan(0);
    expect(cfg.agents.some((a) => a.name === "ruflo")).toBe(true);
    expect(cfg.agents.some((a) => a.name === "audit.recon")).toBe(true);
  });

  test("initConfig local only creates workspace dirs without touching global config", () => {
    const result = initConfig(true);
    expect(result.workspace).toBe(paths.localDir());
    expect(existsSync(paths.localDir())).toBe(true);
    expect(existsSync(paths.localSkillsDir())).toBe(true);
    expect(existsSync(paths.globalModelsFile())).toBe(false);
    expect(existsSync(paths.globalMcpFile())).toBe(false);
  });

  test("saveModels then loadConfig roundtrips a custom model", () => {
    const cfg = loadConfig();
    cfg.upsertModel(
      new ProviderConfig({
        name: "gpt",
        modelName: "gpt-4o",
        apiKey: "sk-z",
        temperature: 0.3,
        topP: 0.8,
        maxContextTokens: 200000,
      }),
    );
    cfg.activeModel = "gpt";
    saveModels(cfg);
    const reloaded = loadConfig();
    expect(reloaded.activeModel).toBe("gpt");
    const m = reloaded.getModel("gpt");
    expect(m.modelName).toBe("gpt-4o");
    expect(m.temperature).toBe(0.3);
    expect(m.topP).toBe(0.8);
    expect(m.maxContextTokens).toBe(200000);
  });

  test("saveMcpServers local merges into loadConfig", () => {
    saveMcpServers(
      [new McpServerConfig({ name: "ida", transport: "http", url: "http://x", enabled: true })],
      "local",
    );
    const cfg = loadConfig();
    expect(cfg.mcpServers.some((s) => s.name === "ida")).toBe(true);
  });

  test("api_key with newline and quote round-trips (no silent config loss)", () => {
    // The old hand-rolled serializer left raw newlines in the output, making
    // the whole file unparseable — and readToml's {} fallback then wiped every
    // setting. smol-toml escapes these, so the value survives a round-trip.
    const cfg = loadConfig();
    const tricky = 'sk-line1\nline2\ttab"quote\\back';
    cfg.upsertModel(new ProviderConfig({ name: "weird", modelName: "m", apiKey: tricky }));
    cfg.activeModel = "weird";
    saveModels(cfg);
    const reloaded = loadConfig();
    // If serialization corrupted the file, activeModel would fall back to a
    // default and the model would be missing entirely.
    expect(reloaded.activeModel).toBe("weird");
    expect(reloaded.getModel("weird").apiKey).toBe(tricky);
  });

  test("saved config files are mode 0600 (secrets not world-readable)", () => {
    const cfg = loadConfig();
    cfg.upsertModel(new ProviderConfig({ name: "gpt", modelName: "m", apiKey: "sk-secret" }));
    const target = saveModels(cfg);
    // Windows does not implement POSIX permission bits; skip there.
    if (process.platform !== "win32") {
      const mode = statSync(target).mode & 0o777;
      expect(mode).toBe(0o600);
    }
  });

  test("saveAgents persists agent routing", () => {
    const cfg = loadConfig();
    const recon0 = cfg.agents.find((a) => a.name === "audit.recon")!;
    recon0.model = "gpt";
    recon0.mcp = ["ida"];
    recon0.skills = ["x"];
    saveAgents(cfg);
    const reloaded = loadConfig();
    const recon = reloaded.agents.find((a) => a.name === "audit.recon")!;
    expect(recon.model).toBe("gpt");
    expect(recon.mcp).toEqual(["ida"]);
  });

  test("local mcp overrides global by name", () => {
    saveMcpServers([new McpServerConfig({ name: "dup", url: "global" })], "global");
    saveMcpServers([new McpServerConfig({ name: "dup", url: "local" })], "local");
    const cfg = loadConfig();
    const dup = cfg.mcpServers.filter((s) => s.name === "dup");
    expect(dup.length).toBe(1);
    expect(dup[0]!.url).toBe("local");
  });

  test("RAG Chroma HTTP knowledge base fields roundtrip", () => {
    saveRagKnowledgeBases([
      new KnowledgeBaseConfig({
        name: "remote",
        backend: "chroma_http",
        chromaUrl: "http://127.0.0.1:8000",
        collectionName: "audit-docs",
        tenant: "t",
        database: "d",
        headers: '{"x":"y"}',
      }),
    ]);
    const cfg = loadConfig();
    const kb = cfg.rag.knowledgeBases.find((x) => x.name === "remote")!;
    expect(kb.backend).toBe("chroma_http");
    expect(kb.chromaUrl).toBe("http://127.0.0.1:8000");
    expect(kb.collectionName).toBe("audit-docs");
    expect(kb.tenant).toBe("t");
    expect(kb.database).toBe("d");
    expect(kb.headers).toBe('{"x":"y"}');
  });
});

describe("CliConfig helpers", () => {
  test("getModel falls back to first enabled", () => {
    const cfg = new CliConfig({
      activeModel: "missing",
      models: [new ProviderConfig({ name: "a", enabled: true })],
    });
    expect(cfg.getModel().name).toBe("a");
  });
  test("AgentConfig wildcard checks", () => {
    const a = new AgentConfig({ mcp: [WILDCARD], skills: ["x"] });
    expect(a.allowsAllMcp()).toBe(true);
    expect(a.allowsAllSkills()).toBe(false);
  });
});

describe("skills", () => {
  function writeSkill(name: string, frontmatter: string, body: string) {
    const dir = join(tmpHome, "skills", name);
    mkdirSync(dir, { recursive: true });
    writeFileSync(join(dir, "SKILL.md"), `---\n${frontmatter}\n---\n${body}`, "utf-8");
  }

  test("loadSkill parses frontmatter and body", () => {
    writeSkill("idapython", 'tools_allow: ["decompile", "disasm"]\nmodel: gpt', "Use IDA carefully.");
    const skill = loadSkill("idapython");
    expect(skill).not.toBeNull();
    expect(skill!.system_prompt_template).toBe("Use IDA carefully.");
    expect(JSON.parse(skill!.tool_allowlist_json!)).toEqual(["decompile", "disasm"]);
    expect(skill!.model_override).toBe("gpt");
  });

  test("listAvailableSkills finds skill dirs", () => {
    writeSkill("a", "", "A");
    writeSkill("b", "", "B");
    expect(listAvailableSkills().sort()).toEqual(["a", "b"]);
  });

  test("loadSkills merges multiple", () => {
    writeSkill("s1", 'tools_allow: ["x"]', "P1");
    writeSkill("s2", 'tools_allow: ["y"]', "P2");
    const merged = loadSkills(["s1", "s2"]);
    expect(merged!.name).toBe("s1+s2");
    expect(merged!.system_prompt_template).toContain("P1");
    expect(merged!.system_prompt_template).toContain("P2");
    expect(JSON.parse(merged!.tool_allowlist_json!).sort()).toEqual(["x", "y"]);
  });

  test("missing skill returns null", () => {
    expect(loadSkill("nope")).toBeNull();
    expect(loadSkills(["nope"])).toBeNull();
  });
});

describe("Store", () => {
  test("conversation + message lifecycle", () => {
    const store = new Store();
    const cid = store.createConversation("t", "gpt");
    expect(store.getConversation(cid)!.title).toBe("t");
    store.saveMessage(cid, "turn1", "user", "hello");
    store.saveMessage(cid, "turn1", "assistant", "hi");
    const msgs = store.loadMessages(cid);
    expect(msgs.length).toBe(2);
    expect(msgs[0]!.content).toBe("hello");
    store.updateConversation(cid, { status: "done" });
    expect(store.getConversation(cid)!.status).toBe("done");
    store.close();
  });

  test("replaceMessages swaps history", () => {
    const store = new Store();
    const cid = store.createConversation();
    store.saveMessage(cid, "t", "user", "old");
    store.replaceMessages(cid, [{ role: "user", content: "new", turn_id: "t2" }]);
    const msgs = store.loadMessages(cid);
    expect(msgs.length).toBe(1);
    expect(msgs[0]!.content).toBe("new");
    store.close();
  });

  test("tool execution lifecycle", () => {
    const store = new Store();
    const cid = store.createConversation();
    const tid = store.saveToolExecution(cid, "t", "decompile", "{}", "ida");
    store.finishToolExecution(tid, "succeeded", "ok");
    store.close();
    expect(tid).toBeTruthy();
  });

  test("invalid update field throws", () => {
    const store = new Store();
    const cid = store.createConversation();
    expect(() => store.updateConversation(cid, { bogus: "x" })).toThrow();
    store.close();
  });
});
