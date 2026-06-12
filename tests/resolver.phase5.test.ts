import { expect, test, describe, beforeEach, afterEach } from "bun:test";
import { mkdtempSync, rmSync, writeFileSync, mkdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { loadConfig, saveModels, saveAgents, saveMcpServers, ProviderConfig, McpServerConfig } from "@/config";
import { RuntimePolicyResolver } from "@/runtime/resolver";

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

function writeSkill(name: string, frontmatter: string, body: string) {
  const dir = join(tmpHome, "skills", name);
  mkdirSync(dir, { recursive: true });
  writeFileSync(join(dir, "SKILL.md"), `---\n${frontmatter}\n---\n${body}`, "utf-8");
}

describe("RuntimePolicyResolver", () => {
  test("resolve(ruflo) has no subagents", () => {
    const plan = new RuntimePolicyResolver(loadConfig()).resolve("ruflo");
    expect(plan.workflow).toBe("ruflo");
    expect(Object.keys(plan.subagentProviders)).toEqual([]);
    expect(plan.systemPrompt.length).toBeGreaterThan(0);
  });

  test("resolve(audit) wires all 8 subagents", () => {
    const plan = new RuntimePolicyResolver(loadConfig()).resolve("audit");
    const names = Object.keys(plan.subagentProviders).sort();
    expect(names).toContain("recon");
    expect(names).toContain("hunt");
    expect(names).toContain("report");
    expect(names.length).toBe(8);
    expect(plan.subagentMcpAllow.recon).toBeNull(); // wildcard mcp by default
  });

  test("resolve(audit-slim) wires 4 subagents", () => {
    const plan = new RuntimePolicyResolver(loadConfig()).resolve("audit-slim");
    expect(Object.keys(plan.subagentProviders).sort()).toEqual(["hunter", "recon", "report", "verify"]);
  });

  test("provider resolution honors per-agent model override", () => {
    let cfg = loadConfig();
    cfg.upsertModel(new ProviderConfig({ name: "fast", modelName: "haiku", enabled: true }));
    saveModels(cfg);
    cfg = loadConfig();
    const recon = cfg.agents.find((a) => a.name === "audit.recon")!;
    recon.model = "fast";
    saveAgents(cfg);

    const plan = new RuntimePolicyResolver(loadConfig()).resolve("audit");
    expect(plan.subagentProviders.recon!.modelName).toBe("haiku");
  });

  test("default agent model follows the active model", () => {
    let cfg = loadConfig();
    cfg.upsertModel(new ProviderConfig({ name: "primary", modelName: "gpt-4o-mini", enabled: true }));
    cfg.activeModel = "primary";
    saveModels(cfg);

    const plan = new RuntimePolicyResolver(loadConfig()).resolve("ruflo");
    expect(plan.provider.modelName).toBe("gpt-4o-mini");
  });

  test("modelAssignmentsFor returns primary for ruflo", () => {
    const resolver = new RuntimePolicyResolver(loadConfig());
    const assignments = resolver.modelAssignmentsFor("ruflo");
    expect(assignments.length).toBe(1);
    expect(assignments[0]![0]).toBe("primary");
  });

  test("mcp allowlist restricts to named servers", () => {
    saveMcpServers([new McpServerConfig({ name: "ida", url: "http://x", enabled: true })], "local");
    let cfg = loadConfig();
    const recon = cfg.agents.find((a) => a.name === "audit.recon")!;
    recon.mcp = ["ida"];
    saveAgents(cfg);

    const plan = new RuntimePolicyResolver(loadConfig()).resolve("audit");
    expect(plan.subagentMcpAllow.recon).toEqual(["ida"]);
  });

  test("audit workflow merges vuln-audit skill into resolved skill", () => {
    const plan = new RuntimePolicyResolver(loadConfig()).resolve("audit");
    // AUDIT_SKILL_DICT always merges; resolved skill name includes the workflow skill.
    expect(plan.skill).not.toBeNull();
  });

  test("wildcard skills load all available skills into prompt", () => {
    writeSkill("rev", "", "Reverse engineering guidance.");
    let cfg = loadConfig();
    const ruflo = cfg.agents.find((a) => a.name === "ruflo")!;
    ruflo.skills = ["*"];
    saveAgents(cfg);

    const plan = new RuntimePolicyResolver(loadConfig()).resolve("ruflo");
    expect(plan.skill).not.toBeNull();
    expect(plan.systemPrompt).toContain("Reverse engineering guidance.");
  });
});
