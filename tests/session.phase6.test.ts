import { expect, test, describe, beforeEach, afterEach } from "bun:test";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { loadConfig } from "@/config";
import { Store } from "@/store";
import { Session } from "@/session";
import { StreamEventType } from "@/engine/enums";

let tmpHome: string;
let tmpCwd: string;
let origHome: string | undefined;
let origCwd: string;
let store: Store;

beforeEach(() => {
  tmpHome = mkdtempSync(join(tmpdir(), "sarma-home-"));
  tmpCwd = mkdtempSync(join(tmpdir(), "sarma-cwd-"));
  origHome = process.env.SARMA_HOME;
  origCwd = process.cwd();
  process.env.SARMA_HOME = tmpHome;
  process.chdir(tmpCwd);
  store = new Store();
});

afterEach(() => {
  store.close();
  process.chdir(origCwd);
  if (origHome === undefined) delete process.env.SARMA_HOME;
  else process.env.SARMA_HOME = origHome;
  rmSync(tmpHome, { recursive: true, force: true });
  rmSync(tmpCwd, { recursive: true, force: true });
});

describe("Session lifecycle", () => {
  test("newConversation creates a conversation and resets state", () => {
    const session = new Session(loadConfig(), store);
    const cid = session.newConversation();
    expect(cid).toBeTruthy();
    expect(session.conversationId).toBe(cid);
    const conv = store.getConversation(cid)!;
    expect(conv.title.toLowerCase()).toContain("session");
  });

  test("default workflow is ruflo", () => {
    const session = new Session(loadConfig(), store);
    expect(session.workflow).toBe("ruflo");
  });

  test("setWorkflow switches mode", () => {
    const session = new Session(loadConfig(), store);
    session.setWorkflow("audit");
    expect(session.workflow).toBe("audit");
  });

  test("setWorkflow rejects unknown modes", () => {
    const session = new Session(loadConfig(), store);
    expect(() => session.setWorkflow("typo")).toThrow("Unknown workflow");
  });

  test("resumeConversation rebuilds history from store", () => {
    const session = new Session(loadConfig(), store);
    const cid = store.createConversation("prior", "m");
    store.saveMessage(cid, "t1", "user", "first question");
    store.saveMessage(cid, "t1", "assistant", "first answer");

    const ok = session.resumeConversation(cid);
    expect(ok).toBe(true);
    expect(session.conversationId).toBe(cid);
  });

  test("resumeConversation returns false for empty conversation", () => {
    const session = new Session(loadConfig(), store);
    const cid = store.createConversation();
    expect(session.resumeConversation(cid)).toBe(false);
  });

  test("graphState returns an independent snapshot", () => {
    const session = new Session(loadConfig(), store);
    const snap1 = session.graphState;
    snap1.completed.add("recon");
    snap1.current_stage = "hunt";
    const snap2 = session.graphState;
    expect(snap2.completed.has("recon")).toBe(false);
    expect(snap2.current_stage).toBe("");
  });

  test("compactContext returns false when nothing to compact", async () => {
    const session = new Session(loadConfig(), store);
    session.newConversation();
    const changed = await session.compactContext({ force: true, workflow: "ruflo" });
    expect(changed).toBe(false);
  });

  test("toolCount is zero with no MCP servers", () => {
    const session = new Session(loadConfig(), store);
    expect(session.toolCount).toBe(0);
  });

  test("runTurn emits lifecycle failure events when provider is unconfigured", async () => {
    const session = new Session(loadConfig(), store);
    const events = [];
    for await (const event of session.runTurn("hello")) events.push(event);
    expect(events[0]!.type).toBe(StreamEventType.RUN_STARTED);
    expect(events.some((e) => e.type === StreamEventType.RUN_FAILED)).toBe(true);
  });
});
