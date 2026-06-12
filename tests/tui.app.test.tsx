/** @jsxImportSource @opentui/solid */
import { expect, test, describe } from "bun:test";
import { testRender } from "@opentui/solid";
import { createSignal } from "solid-js";
import { createStore } from "solid-js/store";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { App, isCtrlCKey, tuiHelpText } from "@/tui/app";
import type { Controller } from "@/tui/controller";
import type { TranscriptItem } from "@/tui/transcript";
import type { GraphStageView } from "@/tui/controller";

function mockController(over: Partial<Controller> = {}): Controller {
  const [items] = createStore<TranscriptItem[]>(
    (over.items as TranscriptItem[]) ?? [
      { kind: "message", id: "u1", role: "user", content: "find auth bugs", reasoning: "" },
      {
        kind: "subagent",
        id: "s1",
        subagent: {
          id: "s1",
          name: "recon",
          description: "mapping",
          status: "complete",
          elapsed: 2.1,
          toolCallId: "delegate-1",
          output: "streamed recon details",
          reasoning: "thinking through entry points",
          result: "mapped entry points",
          error: "",
        },
      },
      {
        kind: "tool",
        id: "t1",
        tool: {
          id: "t1",
          toolCallId: "http-1",
          name: "http_exchange",
          args: "GET /login",
          status: "ok",
          summary: "200 OK",
          result: "HTTP/1.1 200 OK",
          error: "",
          elapsed: 0.4,
        },
      },
      { kind: "message", id: "a1", role: "assistant", content: "Found a reflected XSS.", reasoning: "" },
    ],
  );
  const [stages] = createStore<GraphStageView[]>([
    { name: "recon", status: "complete" },
    { name: "hunter", status: "running" },
    { name: "confirm", status: "pending" },
    { name: "report", status: "pending" },
  ]);
  return {
    items,
    draft: () => "",
    draftReasoning: () => "",
    busy: () => true,
    status: () => "hunter working",
    workflow: () => "audit",
    modelName: () => "gpt-4o-mini",
    toolCount: () => 4,
    mcpStatuses: () => [
      { name: "ida", connected: true },
      { name: "gh", connected: false },
    ],
    refreshMcpStatus: async () => {},
    todoItems: () => [
      { content: "Map attack surface", status: "completed" },
      { content: "Validate SSLVPN paths", status: "in_progress" },
    ],
    stages: () => stages,
    workflows: () => ["ruflo", "audit", "audit-slim"],
    sessionId: () => "",
    submit: async () => {},
    setWorkflow: () => {},
    workflowPickerOpen: () => false,
    workflowPickerSelectedIndex: () => 0,
    workflowRows: () => [
      {
        name: "ruflo",
        description: "Primary agent with focused delegated subagents",
        agentCount: 1,
        current: true,
        isDefault: true,
      },
      {
        name: "audit",
        description: "Full audit pipeline with 8 stages",
        agentCount: 9,
        current: false,
        isDefault: false,
      },
    ],
    openWorkflowPicker: () => {},
    closeWorkflowPicker: () => {},
    moveWorkflowPickerSelection: () => {},
    activateWorkflowPickerSelection: () => null,
    graphOpen: () => false,
    workflowGraph: () => ({
      workflow: "audit",
      description: "Full audit pipeline with 8 stages",
      currentStage: "hunt",
      failedStage: "(none)",
      gapfillLoops: 0,
      feedbackLoops: 0,
      nodes: [
        {
          name: "audit",
          label: "audit",
          kind: "workflow",
          level: 0,
          status: "running",
          detail: "Full audit pipeline with 8 stages",
        },
        {
          name: "START",
          label: "START",
          kind: "terminal",
          level: 1,
          status: "idle",
          detail: "entry into the compiled audit StateGraph",
        },
        {
          name: "hunt",
          label: "02 hunt",
          kind: "stage",
          level: 2,
          status: "running",
          detail: "agent=audit.hunt, model=default",
        },
        {
          name: "validate_check",
          label: "validate_check",
          kind: "router",
          level: 3,
          status: "idle",
          detail: "same-model structured router: gapfill | dedupe",
        },
      ],
    }),
    openGraph: () => {},
    closeGraph: () => {},
    newConversation: () => {},
    note: () => {},
    statusReport: async () => "status:",
    graphReport: () => "graph:",
    modelReport: () => "models:",
    selectModel: async () => "selected model",
    modelsReport: () => "models:",
    mcpReport: async () => "mcp:",
    skillsReport: () => "skills:",
    sessionsReport: () => "sessions:",
    resumeSession: () => true,
    restartRuntime: async () => "Workflow runtime restarted.",
    compactContext: async () => "Context compacted.",
    pluginReport: () => "plugins:",
    pluginCommand: async () => "plugins:",
    pluginOpen: () => false,
    pluginSection: () => "mcp",
    pluginStep: () => "browse",
    pluginSelectedIndex: () => 0,
    openPlugin: () => {},
    closePlugin: () => {},
    setPluginSection: () => {},
    movePluginSelection: () => {},
    pluginMcpRows: () => [],
    pluginSkillRows: () => [],
    pluginSkillSearchQuery: () => "",
    setPluginSkillSearchQuery: () => {},
    pluginSkillSearchRows: () => [],
    searchPluginSkills: async () => null,
    installPluginSkill: async () => null,
    newPluginMcp: () => {},
    editPluginMcp: () => {},
    toggleSelectedPlugin: async () => null,
    pluginMcpDraft: {
      name: "ida",
      transport: "http",
      url: "http://127.0.0.1:5000/mcp",
      headers: "",
      command: "",
      args: "",
      env: "",
      enabled: "true",
      scope: "local",
    },
    setPluginMcpField: () => {},
    testPluginMcp: async () => "MCP test OK: 3 tools",
    savePluginMcp: async () => null,
    newPluginSkill: () => {},
    pluginSkillDraft: {
      name: "idapython",
      prompt: "Use IDA carefully.",
      enabled: "true",
      scope: "local",
    },
    setPluginSkillField: () => {},
    savePluginSkill: async () => null,
    backToPluginBrowse: () => {},
    ragReport: () => "rag:",
    ragOpen: () => false,
    ragSection: () => "knowledge",
    ragStep: () => "browse",
    ragSelectedIndex: () => 0,
    openRag: () => {},
    closeRag: () => {},
    setRagSection: () => {},
    moveRagSelection: () => {},
    ragKnowledgeBaseRows: () => [],
    editRagModelSettings: () => {},
    editRagSearch: () => {},
    newRagKnowledgeBase: () => {},
    editRagKnowledgeBase: () => {},
    toggleSelectedRagKnowledgeBase: async () => null,
    deleteSelectedRagKnowledgeBase: async () => null,
    chunkSelectedRagKnowledgeBase: async () => null,
    ragModelDraft: {
      embeddingBackend: "huggingface",
      embeddingModel: "",
      embeddingApiBase: "",
      embeddingApiKey: "",
      embeddingLocalPath: "",
      chunkSize: "1200",
      chunkOverlap: "150",
    },
    ragKnowledgeBaseDraft: {
      name: "",
      backend: "sarma_native",
      docsPath: "",
      chromaPath: "",
      chromaUrl: "",
      collectionName: "",
      headers: "",
      enabled: "true",
      scope: "local",
    },
    ragSearchDraft: {
      query: "",
      knowledgeBase: "",
      topK: "5",
    },
    setRagModelField: () => {},
    setRagKnowledgeBaseField: () => {},
    setRagSearchField: () => {},
    saveRagModelSettings: async () => null,
    saveRagKnowledgeBase: async () => null,
    runRagSearch: async () => null,
    backToRagBrowse: () => {},
    debugReport: () => "debug:",
    hasModel: () => true,
    modelPickerOpen: () => false,
    modelPickerSelectedIndex: () => 0,
    openModelPicker: () => {},
    closeModelPicker: () => {},
    moveModelPickerSelection: () => {},
    activateModelPickerSelection: async () => null,
    configOpen: () => false,
    configSection: () => "models",
    configStep: () => "browse",
    openConfig: () => {},
    closeConfig: () => {},
    setConfigSection: () => {},
    configSelectedIndex: () => 0,
    configWorkflowSelectedIndex: () => 0,
    configAgentSelectedIndex: () => 0,
    configWorkflowPane: () => "workflows",
    configModelRows: () => [],
    configWorkflowRows: () => [],
    configAgentRows: () => [],
    selectConfigItem: () => {},
    moveConfigSelection: () => {},
    moveConfigWorkflowSelection: () => {},
    moveConfigAgentSelection: () => {},
    setConfigWorkflowPane: () => {},
    newConfigModel: () => {},
    editConfigModel: () => {},
    editConfigAgent: () => {},
    deleteConfigModel: async () => null,
    activateConfigModel: async () => null,
    chooseInterface: () => {},
    backToInterface: () => {},
    modelDraft: {
      name: "default",
      modelName: "gpt-4o-mini",
      apiMode: "openai_compatible",
      baseUrl: "",
      apiKey: "",
      maxContextTokens: "128000",
      enabled: "true",
    },
    setModelField: () => {},
    agentDraft: {
      name: "ruflo",
      model: "default",
      mcp: "*",
      skills: "",
    },
    setAgentField: () => {},
    testModel: async () => "Model test OK: default (gpt-4o-mini) -> OK",
    saveModel: async () => null,
    saveAgent: async () => null,
    close: async () => {},
    ...over,
  };
}

async function withTempWorkspace(fn: (workspace: string) => Promise<void>) {
  const prevCwd = process.cwd();
  const workspace = mkdtempSync(join(tmpdir(), "sarma-tui-history-"));
  process.chdir(workspace);
  try {
    await fn(workspace);
  } finally {
    process.chdir(prevCwd);
    rmSync(workspace, { recursive: true, force: true });
  }
}

describe("TUI App", () => {
  test("recognizes Ctrl+C key event variants", () => {
    expect(isCtrlCKey({ ctrl: true, name: "c" })).toBe(true);
    expect(isCtrlCKey({ ctrl: true, name: "C" })).toBe(true);
    expect(isCtrlCKey({ sequence: "\u0003" })).toBe(true);
    expect(isCtrlCKey({ raw: "\u0003" })).toBe(true);
    expect(isCtrlCKey({ name: "c" })).toBe(false);
  });

  test("help text uses /exit without advertising Ctrl+C", () => {
    const help = tuiHelpText();
    expect(help).toContain("/help");
    expect(help).toContain("/model [name]");
    expect(help).toContain("/config");
    expect(help).toContain("/mcp");
    expect(help).toContain("/skills");
    expect(help).toContain("/sessions");
    expect(help).toContain("/clear");
    expect(help).not.toContain("/history");
    expect(help).not.toContain("/new");
    expect(help).toContain("/exit");
    expect(help).not.toContain("/quit");
    expect(help).not.toContain("^C");
  });

  test("exits only after two Ctrl+C presses", async () => {
    let exits = 0;
    const t = await testRender(() => App({ controller: mockController(), onExit: () => exits++ }), {
      width: 84,
      height: 22,
    });
    await t.renderOnce();

    t.mockInput.pressCtrlC();
    await t.renderOnce();
    expect(exits).toBe(0);

    t.mockInput.pressCtrlC();
    await t.renderOnce();
    expect(exits).toBe(1);
  });

  test("renders chat, input and status sidebar", async () => {
    const t = await testRender(() => App({ controller: mockController(), onExit: () => {} }), {
      width: 100,
      height: 30,
    });
    await t.renderOnce();
    const frame = t.captureCharFrame();

    // Removed chrome: the TUI is just chat, input and a right status panel.
    expect(frame).not.toContain("SARMA");
    expect(frame).not.toContain("vulnerability audit agent");
    // Transcript content
    expect(frame).toContain("find auth bugs");
    expect(frame).toContain("RECON");
    expect(frame).toContain("http_exchange");
    expect(frame).toContain("reflected XSS");
    // Status sidebar
    expect(frame).toContain("SESSION");
    expect(frame).toContain("STATUS");
    expect(frame).toContain("workflow");
    expect(frame).toContain("audit");
    expect(frame).toContain("gpt-4o-mini");
    expect(frame).toContain("MCP");
    expect(frame).toContain("ida");
    expect(frame).toContain("yes");
    expect(frame).toContain("gh");
    expect(frame).toContain("no");
    expect(frame).toContain("hunter working");
    expect(frame).toContain("TODO");
    expect(frame).toContain("[X] Map attack surface");
    expect(frame).toContain("[*] Validate SSLVPN");
    expect(frame).toContain("Map attack surface");
    expect(frame).toContain("Validate SSLVPN");
    expect(frame).toContain("SUBAGENTS");
    expect(frame).toContain("[X] recon");
    expect(frame).not.toContain("^C ^C exit");
    expect(frame).toContain("STAGES");
    expect(frame).toContain("current hunter");
    // Stage glyphs
    expect(frame).toContain("✓ recon");
    expect(frame).toContain("◐ hunter");
    expect(frame).toContain("· confirm");
    // Bottom input stays in the left column.
    expect(frame).toContain("❯");
    expect(frame).toContain("Ask Sarma to audit...");
  });

  test("renders workflow stage cards in the transcript", async () => {
    const t = await testRender(
      () =>
        App({
          controller: mockController({
            items: [
              { kind: "message", id: "u1", role: "user", content: "audit target", reasoning: "" },
              {
                kind: "stage",
                id: "g1",
                stage: {
                  id: "g1",
                  name: "hunter",
                  nodeKind: "stage",
                  description: "Audit vulnerability candidates",
                  status: "running",
                  elapsed: 0,
                  error: "",
                },
              },
            ],
          }),
          onExit: () => {},
        }),
      { width: 100, height: 30 },
    );
    await t.renderOnce();
    const frame = t.captureCharFrame();
    expect(frame).toContain("STAGE HUNTER");
    expect(frame).toContain("Audit vulnerability candidates");
    expect(frame).toContain("current hunter");
  });

  test("renders workflow router cards in the transcript", async () => {
    const t = await testRender(
      () =>
        App({
          controller: mockController({
            items: [
              { kind: "message", id: "u1", role: "user", content: "audit target", reasoning: "" },
              {
                kind: "stage",
                id: "g1",
                stage: {
                  id: "g1",
                  name: "validate_check",
                  nodeKind: "router",
                  description: "same-model structured router: gapfill | dedupe",
                  status: "running",
                  elapsed: 0,
                  error: "",
                },
              },
            ],
          }),
          onExit: () => {},
        }),
      { width: 100, height: 30 },
    );
    await t.renderOnce();
    const frame = t.captureCharFrame();
    expect(frame).toContain("ROUTER");
    expect(frame).toContain("VALIDATE_CHECK");
    expect(frame).toContain("gapfill |");
    expect(frame).toContain("dedupe");
  });

  test("renders delegate_task dispatch and opens subagent details fullscreen", async () => {
    const t = await testRender(
      () =>
        App({
          controller: mockController({
            busy: () => true,
            items: [
              { kind: "message", id: "u1", role: "user", content: "audit target", reasoning: "" },
              {
                kind: "tool",
                id: "t-delegate",
                tool: {
                  id: "t-delegate",
                  toolCallId: "delegate-recon",
                  name: "delegate_task",
                  args: JSON.stringify({ subagent_name: "recon", task: "Map auth attack surface" }),
                  status: "ok",
                  summary: "done",
                  result: "Compact recon result",
                  error: "",
                  elapsed: 0.5,
                },
              },
              {
                kind: "subagent",
                id: "s-recon",
                subagent: {
                  id: "s-recon",
                  name: "recon",
                  description: "Map auth attack surface",
                  status: "complete",
                  elapsed: 0.5,
                  toolCallId: "delegate-recon",
                  output: "Streamed recon output",
                  reasoning: "Reasoning through handlers",
                  result: "Compact recon result",
                  error: "",
                },
              },
            ],
          }),
          onExit: () => {},
        }),
      { width: 120, height: 34, useMouse: true, autoFocus: true },
    );
    await t.renderOnce();
    let frame = t.captureCharFrame();
    expect(frame).toContain("delegate_task -> recon");
    expect(frame).toContain("Map auth attack surface");
    expect(frame).toContain("SUBAGENT RECON");
    expect(frame).toContain("OUTPUT");
    expect(frame).toContain("Streamed recon output");
    expect(frame).toContain("click to open full subagent output");
    expect(frame).not.toContain("RETURNED RESULT");

    await t.mockMouse.click(5, 13);
    await t.renderOnce();
    frame = t.captureCharFrame();
    expect(frame).toContain("SUBAGENT RECON");
    expect(frame).toContain("TASK");
    expect(frame).toContain("Map auth attack surface");
    expect(frame).toContain("THINKING");
    expect(frame).toContain("Reasoning through handlers");
    expect(frame).toContain("RETURNED RESULT");
    expect(frame).toContain("Compact recon result");
  });

  test("renders delegate subagent reasoning in the merged card preview", async () => {
    const t = await testRender(
      () =>
        App({
          controller: mockController({
            busy: () => true,
            items: [
              {
                kind: "tool",
                id: "t-delegate",
                tool: {
                  id: "t-delegate",
                  toolCallId: "delegate-tester",
                  name: "delegate_task",
                  args: JSON.stringify({ subagent_name: "tester", task: "Answer simple questions" }),
                  status: "running",
                  summary: "",
                  result: "",
                  error: "",
                  elapsed: 0,
                },
              },
              {
                kind: "subagent",
                id: "s-tester",
                subagent: {
                  id: "s-tester",
                  name: "tester",
                  description: "Answer simple questions",
                  status: "running",
                  elapsed: 0,
                  toolCallId: "delegate-tester",
                  output: "",
                  reasoning: "The user is asking simple questions.",
                  result: "",
                  error: "",
                },
              },
            ],
          }),
          onExit: () => {},
        }),
      { width: 120, height: 26 },
    );
    await t.renderOnce();
    const frame = t.captureCharFrame();
    expect(frame).toContain("delegate_task -> tester");
    expect(frame).toContain("SUBAGENT TESTER");
    expect(frame).toContain("THINKING");
    expect(frame).toContain("simple questions");
  });

  test("renders subagent-owned tools inside subagent details", async () => {
    const t = await testRender(
      () =>
        App({
          controller: mockController({
            busy: () => false,
            items: [
              {
                kind: "subagent",
                id: "s-recon",
                subagent: {
                  id: "s-recon",
                  name: "recon",
                  description: "Map attack surface",
                  status: "complete",
                  elapsed: 0.4,
                  toolCallId: "",
                  output: "Recon output",
                  reasoning: "",
                  result: "Recon done",
                  error: "",
                },
              },
              {
                kind: "tool",
                id: "t-grep",
                tool: {
                  id: "t-grep",
                  toolCallId: "grep-1",
                  name: "grep",
                  subagent: "recon",
                  args: JSON.stringify({ pattern: "auth" }),
                  status: "ok",
                  summary: "src/auth.ts: token check",
                  result: "src/auth.ts: token check",
                  error: "",
                  elapsed: 0.2,
                },
              },
            ],
          }),
          onExit: () => {},
        }),
      { width: 120, height: 32, useMouse: true, autoFocus: true },
    );
    await t.renderOnce();

    await t.mockMouse.click(5, 2);
    await t.renderOnce();
    const frame = t.captureCharFrame();
    expect(frame).toContain("SUBAGENT RECON");
    expect(frame).toContain("TOOLS");
    expect(frame).toContain("grep");
    expect(frame).toContain("token check");
  });

  test("refreshes MCP status when the TUI mounts", async () => {
    let refreshes = 0;
    const t = await testRender(
      () =>
        App({
          controller: mockController({ refreshMcpStatus: async () => { refreshes += 1; } }),
          onExit: () => {},
        }),
      { width: 84, height: 18 },
    );
    await t.renderOnce();
    expect(refreshes).toBe(1);
  });

  test("renders idle status when not busy", async () => {
    const t = await testRender(
      () => App({ controller: mockController({ busy: () => false, items: [] }), onExit: () => {} }),
      { width: 84, height: 16 },
    );
    await t.renderOnce();
    const frame = t.captureCharFrame();
    expect(frame).toContain("ready");
  });

  test("renders chat messages through markdown instead of raw markdown text", async () => {
    const t = await testRender(
      () =>
        App({
          controller: mockController({
            busy: () => false,
            items: [
              {
                kind: "message",
                id: "a-md",
                role: "assistant",
                content: "**Finding**\n\n- `token` leak\n\n```ts\nconst ok = true\n```",
                reasoning: "",
              },
            ],
          }),
          onExit: () => {},
        }),
      { width: 84, height: 18 },
    );
    await t.renderOnce();
    const frame = t.captureCharFrame();

    expect(frame).toContain("Finding");
    expect(frame).toContain("token");
    expect(frame).toContain("const ok = true");
    expect(frame).not.toContain("**Finding**");
    expect(frame).not.toContain("```ts");
  });

  test("clicking the terminal keeps typing routed to the input", async () => {
    let submitted = "";
    const t = await testRender(
      () =>
        App({
          controller: mockController({
            busy: () => false,
            items: [],
            submit: async (text) => {
              submitted = text;
            },
          }),
          onExit: () => {},
        }),
      { width: 84, height: 18, useMouse: true, autoFocus: true },
    );
    await t.renderOnce();

    await t.mockMouse.click(10, 4);
    await t.mockInput.typeText("audit target");
    await t.renderOnce();
    t.mockInput.pressEnter();
    await t.renderOnce();

    expect(submitted).toBe("audit target");
  });

  test("stores submitted user prompts in workspace input history", async () => {
    await withTempWorkspace(async (workspace) => {
      let submitted = "";
      const notes: string[] = [];
      const t = await testRender(
        () =>
          App({
            controller: mockController({
              busy: () => false,
              items: [],
              submit: async (text) => {
                submitted = text;
              },
              note: (text) => notes.push(text),
            }),
            onExit: () => {},
          }),
        { width: 84, height: 18, useMouse: true, autoFocus: true },
      );
      await t.renderOnce();

      await t.mockInput.typeText("audit target");
      t.mockInput.pressEnter();
      await t.renderOnce();
      await t.mockInput.typeText("/help");
      t.mockInput.pressEnter();
      await t.renderOnce();

      const historyFile = join(workspace, ".sarma", ".history");
      expect(submitted).toBe("audit target");
      expect(notes.at(-1)).toContain("/exit");
      expect(readFileSync(historyFile, "utf8")).toBe("audit target\n");
    });
  });

  test("up and down browse input history and restore the current draft", async () => {
    await withTempWorkspace(async (workspace) => {
      const sarmaDir = join(workspace, ".sarma");
      mkdirSync(sarmaDir, { recursive: true });
      writeFileSync(join(sarmaDir, ".history"), "first prompt\nsecond prompt\n", "utf8");

      const submitted: string[] = [];
      const t = await testRender(
        () =>
          App({
            controller: mockController({
              busy: () => false,
              items: [],
              submit: async (text) => {
                submitted.push(text);
              },
            }),
            onExit: () => {},
          }),
        { width: 84, height: 18, useMouse: true, autoFocus: true },
      );
      await t.renderOnce();

      await t.mockInput.typeText("draft prompt");
      t.mockInput.pressArrow("up");
      await t.renderOnce();
      t.mockInput.pressArrow("up");
      await t.renderOnce();
      t.mockInput.pressArrow("down");
      await t.renderOnce();
      t.mockInput.pressEnter();
      await t.renderOnce();

      expect(submitted).toEqual(["second prompt"]);

      await t.mockInput.typeText("new draft");
      t.mockInput.pressArrow("up");
      await t.renderOnce();
      t.mockInput.pressArrow("down");
      await t.renderOnce();
      t.mockInput.pressEnter();
      await t.renderOnce();

      expect(submitted).toEqual(["second prompt", "new draft"]);
      expect(existsSync(join(sarmaDir, ".history"))).toBe(true);
    });
  });

  test("routes model, MCP, skills, and sessions slash commands", async () => {
    const notes: string[] = [];
    const t = await testRender(
      () =>
        App({
          controller: mockController({
            busy: () => false,
            items: [],
            note: (text) => notes.push(text),
            selectModel: async (name) => `selected ${name}`,
            mcpReport: async () => "mcp report",
            skillsReport: () => "skills report",
            sessionsReport: () => "sessions report",
          }),
          onExit: () => {},
        }),
      { width: 84, height: 18, useMouse: true, autoFocus: true },
    );
    await t.renderOnce();

    await t.mockInput.typeText("/model primary");
    t.mockInput.pressEnter();
    await t.renderOnce();
    await t.mockInput.typeText("/MCP");
    t.mockInput.pressEnter();
    await t.renderOnce();
    await t.mockInput.typeText("/Skills");
    t.mockInput.pressEnter();
    await t.renderOnce();
    await t.mockInput.typeText("/sessions");
    t.mockInput.pressEnter();
    await t.renderOnce();

    expect(notes).toContain("selected primary");
    expect(notes).toContain("mcp report");
    expect(notes).toContain("skills report");
    expect(notes).toContain("sessions report");
  });

  test("/model without an argument opens the model picker", async () => {
    let opened = false;
    const notes: string[] = [];
    const t = await testRender(
      () =>
        App({
          controller: mockController({
            busy: () => false,
            items: [],
            note: (text) => notes.push(text),
            openModelPicker: () => {
              opened = true;
            },
          }),
          onExit: () => {},
        }),
      { width: 84, height: 18, useMouse: true, autoFocus: true },
    );
    await t.renderOnce();

    await t.mockInput.typeText("/model");
    t.mockInput.pressEnter();
    await t.renderOnce();

    expect(opened).toBe(true);
    expect(notes).toEqual([]);
  });

  test("/workflow without an argument opens the workflow picker", async () => {
    let opened = false;
    const notes: string[] = [];
    const t = await testRender(
      () =>
        App({
          controller: mockController({
            busy: () => false,
            items: [],
            note: (text) => notes.push(text),
            openWorkflowPicker: () => {
              opened = true;
            },
          }),
          onExit: () => {},
        }),
      { width: 84, height: 18, useMouse: true, autoFocus: true },
    );
    await t.renderOnce();

    await t.mockInput.typeText("/workflow");
    t.mockInput.pressEnter();
    await t.renderOnce();

    expect(opened).toBe(true);
    expect(notes).toEqual([]);
  });

  test("/graph without an argument opens the graph panel", async () => {
    let opened = false;
    const notes: string[] = [];
    const t = await testRender(
      () =>
        App({
          controller: mockController({
            busy: () => false,
            items: [],
            note: (text) => notes.push(text),
            openGraph: () => {
              opened = true;
            },
          }),
          onExit: () => {},
        }),
      { width: 84, height: 18, useMouse: true, autoFocus: true },
    );
    await t.renderOnce();

    await t.mockInput.typeText("/graph");
    t.mockInput.pressEnter();
    await t.renderOnce();

    expect(opened).toBe(true);
    expect(notes).toEqual([]);
  });

  test("/plugin without arguments opens the plugin panel", async () => {
    let opened = false;
    const notes: string[] = [];
    const t = await testRender(
      () =>
        App({
          controller: mockController({
            busy: () => false,
            items: [],
            note: (text) => notes.push(text),
            openPlugin: () => {
              opened = true;
            },
          }),
          onExit: () => {},
        }),
      { width: 84, height: 18, useMouse: true, autoFocus: true },
    );
    await t.renderOnce();

    await t.mockInput.typeText("/plugin");
    t.mockInput.pressEnter();
    await t.renderOnce();

    expect(opened).toBe(true);
    expect(notes).toEqual([]);
  });

  test("/rag without arguments opens the RAG panel", async () => {
    let opened = false;
    const notes: string[] = [];
    const t = await testRender(
      () =>
        App({
          controller: mockController({
            busy: () => false,
            items: [],
            note: (text) => notes.push(text),
            openRag: () => {
              opened = true;
            },
          }),
          onExit: () => {},
        }),
      { width: 84, height: 18, useMouse: true, autoFocus: true },
    );
    await t.renderOnce();

    await t.mockInput.typeText("/rag");
    t.mockInput.pressEnter();
    await t.renderOnce();

    expect(opened).toBe(true);
    expect(notes).toEqual([]);
  });

  test("renders RAG panel with knowledge bases", async () => {
    const t = await testRender(
      () =>
        App({
          controller: mockController({
            busy: () => false,
            items: [],
            ragOpen: () => true,
            ragKnowledgeBaseRows: () => [
              {
                name: "docs",
                backend: "sarma_native",
                target: ".sarma/rag/chroma/docs",
                docsPath: "docs",
                enabled: true,
              },
            ],
          }),
          onExit: () => {},
        }),
      { width: 100, height: 20 },
    );
    await t.renderOnce();
    const frame = t.captureCharFrame();

    expect(frame).toContain("RAG");
    expect(frame).toContain("Knowledge Bases");
    expect(frame).toContain("docs");
    expect(frame).toContain("sarma_native");
    expect(frame).toContain(".sarma/rag/chroma/docs");
  });

  test("renders workflow picker with workflow rows", async () => {
    const t = await testRender(
      () =>
        App({
          controller: mockController({
            busy: () => false,
            items: [],
            workflowPickerOpen: () => true,
          }),
          onExit: () => {},
        }),
      { width: 100, height: 18 },
    );
    await t.renderOnce();
    const frame = t.captureCharFrame();

    expect(frame).toContain("WORKFLOW");
    expect(frame).toContain("ruflo");
    expect(frame).toContain("audit");
    expect(frame).toContain("Primary agent");
    expect(frame).toContain("Enter select");
  });

  test("renders graph panel with workflow hierarchy", async () => {
    const t = await testRender(
      () =>
        App({
          controller: mockController({
            busy: () => false,
            items: [],
            graphOpen: () => true,
          }),
          onExit: () => {},
        }),
      { width: 120, height: 24 },
    );
    await t.renderOnce();
    const frame = t.captureCharFrame();

    expect(frame).toContain("GRAPH");
    expect(frame).toContain("Workflow Graph");
    expect(frame).toContain("START");
    expect(frame).toContain("02 hunt");
    expect(frame).toContain("validate_check");
    expect(frame).toContain("parallel: Ruflo fan-out");
    expect(frame).toContain("router: branch decision");
    expect(frame).toContain("stage: ordered work");
  });

  test("renders plugin panel for MCP and skills", async () => {
    const t = await testRender(
      () =>
        App({
          controller: mockController({
            busy: () => false,
            items: [],
            pluginOpen: () => true,
            pluginSection: () => "mcp",
            pluginMcpRows: () => [
              {
                name: "ida",
                transport: "http",
                target: "http://127.0.0.1:5000/mcp",
                enabled: true,
              },
            ],
            pluginSkillRows: () => [
              {
                name: "idapython",
                enabled: false,
              },
            ],
          }),
          onExit: () => {},
        }),
      { width: 100, height: 18 },
    );
    await t.renderOnce();
    const frame = t.captureCharFrame();

    expect(frame).toContain("PLUGIN");
    expect(frame).toContain("MCP Servers");
    expect(frame).toContain("ida");
    expect(frame).toContain("http://127.0.0.1:5000/mcp");
    expect(frame).toContain("Space toggle");
  });

  test("plugin MCP transport changes with left/right while up/down moves focus", async () => {
    const [pluginMcpDraft, setPluginMcpDraft] = createStore({
      name: "ida",
      transport: "http",
      url: "http://127.0.0.1:5000/mcp",
      headers: "",
      command: "",
      args: "",
      env: "",
      enabled: "true",
      scope: "local",
    });
    const transportChanges: string[] = [];
    const t = await testRender(
      () =>
        App({
          controller: mockController({
            busy: () => false,
            items: [],
            pluginOpen: () => true,
            pluginStep: () => "mcp-fields",
            pluginMcpDraft,
            setPluginMcpField: (key, value) => {
              if (key === "transport") transportChanges.push(value);
              setPluginMcpDraft(key, value);
            },
          }),
          onExit: () => {},
        }),
      { width: 120, height: 24 },
    );
    await t.renderOnce();

    expect(t.captureCharFrame()).toContain("> Name");
    expect(t.captureCharFrame()).toContain("[http]");

    t.mockInput.pressArrow("down");
    await t.renderOnce();
    expect(t.captureCharFrame()).toContain("> Transport");

    t.mockInput.pressArrow("right");
    await t.renderOnce();
    t.mockInput.pressArrow("right");
    await t.renderOnce();
    expect(transportChanges).toEqual(["sse", "stdio"]);
    expect(pluginMcpDraft.transport).toBe("stdio");
    expect(t.captureCharFrame()).toContain("[stdio]");
    expect(t.captureCharFrame()).toContain("stdio executable");

    t.mockInput.pressArrow("down");
    await t.renderOnce();
    expect(transportChanges).toEqual(["sse", "stdio"]);
    expect(t.captureCharFrame()).toContain("> python");
  });

  test("plugin edit shortcut does not type e into MCP name", async () => {
    const [pluginStep, setPluginStep] = createSignal<"browse" | "mcp-fields">("browse");
    const [pluginMcpDraft, setPluginMcpDraft] = createStore({
      name: "ida",
      transport: "http",
      url: "http://127.0.0.1:5000/mcp",
      headers: "",
      command: "",
      args: "",
      env: "",
      enabled: "true",
      scope: "local",
    });
    const t = await testRender(
      () =>
        App({
          controller: mockController({
            busy: () => false,
            items: [],
            pluginOpen: () => true,
            pluginStep,
            pluginSection: () => "mcp",
            pluginMcpRows: () => [
              {
                name: "ida",
                transport: "http",
                target: "http://127.0.0.1:5000/mcp",
                enabled: true,
              },
            ],
            editPluginMcp: () => setPluginStep("mcp-fields"),
            pluginMcpDraft,
            setPluginMcpField: (key, value) => setPluginMcpDraft(key, value),
          }),
          onExit: () => {},
        }),
      { width: 120, height: 24 },
    );
    await t.renderOnce();
    expect(t.captureCharFrame()).toContain("MCP Servers");

    t.mockInput.pressKey("e");
    await t.renderOnce();

    expect(t.captureCharFrame()).toContain("MCP Server");
    expect(pluginMcpDraft.name).toBe("ida");
  });

  test("plugin MCP form exposes a Ctrl-T MCP test action", async () => {
    let tested = false;
    const t = await testRender(
      () =>
        App({
          controller: mockController({
            busy: () => false,
            items: [],
            pluginOpen: () => true,
            pluginStep: () => "mcp-fields",
            testPluginMcp: async () => {
              tested = true;
              return "MCP test OK: 3 tools";
            },
          }),
          onExit: () => {},
        }),
      { width: 120, height: 24 },
    );
    await t.renderOnce();
    expect(t.captureCharFrame()).toContain("Ctrl-T Test");

    t.mockInput.pressKey("t", { ctrl: true });
    await t.renderOnce();
    expect(tested).toBe(true);
    expect(t.captureCharFrame()).toContain("MCP test OK");
    expect(t.captureCharFrame()).toContain("3 tools");
    expect(t.captureCharFrame()).not.toContain("ida (3 tools)");
  });

  test("renders model picker as a TUI selection window", async () => {
    const t = await testRender(
      () =>
        App({
          controller: mockController({
            busy: () => false,
            items: [],
            modelPickerOpen: () => true,
            configModelRows: () => [
              {
                name: "primary",
                modelName: "gpt-4o-mini",
                apiMode: "openai_compatible",
                enabled: true,
                active: true,
              },
              {
                name: "backup",
                modelName: "claude-sonnet-4-6",
                apiMode: "anthropic",
                enabled: true,
                active: false,
              },
            ],
          }),
          onExit: () => {},
        }),
      { width: 84, height: 18 },
    );
    await t.renderOnce();
    const frame = t.captureCharFrame();

    expect(frame).toContain("MODEL");
    expect(frame).toContain("Select active provider profile");
    expect(frame).toContain("* primary");
    expect(frame).toContain("gpt-4o-mini");
    expect(frame).toContain("backup");
    expect(frame).toContain("claude-sonnet-4-6");
    expect(frame).toContain("Enter select");
  });

  test("config model API mode changes with left/right while up/down moves focus", async () => {
    const [modelDraft, setModelDraft] = createStore({
      name: "default",
      modelName: "gpt-4o-mini",
      apiMode: "openai_compatible",
      baseUrl: "",
      apiKey: "",
      maxContextTokens: "128000",
      enabled: "true",
    });
    const apiModeChanges: string[] = [];
    const t = await testRender(
      () =>
        App({
          controller: mockController({
            busy: () => false,
            items: [],
            configOpen: () => true,
            configStep: () => "model-fields",
            modelDraft,
            setModelField: (key, value) => {
              if (key === "apiMode") apiModeChanges.push(value);
              setModelDraft(key, value);
            },
          }),
          onExit: () => {},
        }),
      { width: 120, height: 24 },
    );
    await t.renderOnce();

    t.mockInput.pressArrow("down");
    await t.renderOnce();
    t.mockInput.pressArrow("down");
    await t.renderOnce();

    t.mockInput.pressArrow("down");
    await t.renderOnce();
    expect(apiModeChanges).toEqual([]);
    expect(modelDraft.apiMode).toBe("openai_compatible");

    t.mockInput.pressArrow("up");
    await t.renderOnce();
    t.mockInput.pressArrow("right");
    await t.renderOnce();
    expect(apiModeChanges).toEqual(["openai_responses"]);
    expect(modelDraft.apiMode).toBe("openai_responses");
  });

  test("config workflow agent model changes with left/right while up/down moves focus", async () => {
    const [agentDraft, setAgentDraft] = createStore({
      name: "audit.recon",
      model: "default",
      mcp: "*",
      skills: "",
    });
    const modelChanges: string[] = [];
    const t = await testRender(
      () =>
        App({
          controller: mockController({
            busy: () => false,
            items: [],
            configOpen: () => true,
            configSection: () => "workflow",
            configStep: () => "agent-fields",
            configModelRows: () => [
              {
                name: "primary",
                modelName: "gpt-4o-mini",
                apiMode: "openai_compatible",
                enabled: true,
                active: true,
              },
              {
                name: "backup",
                modelName: "claude-sonnet-4-6",
                apiMode: "anthropic",
                enabled: true,
                active: false,
              },
            ],
            agentDraft,
            setAgentField: (key, value) => {
              if (key === "model") modelChanges.push(value);
              setAgentDraft(key, value);
            },
          }),
          onExit: () => {},
        }),
      { width: 120, height: 20 },
    );
    await t.renderOnce();

    expect(t.captureCharFrame()).toContain("> Model");
    expect(t.captureCharFrame()).toContain("[default]");

    t.mockInput.pressArrow("down");
    await t.renderOnce();
    expect(modelChanges).toEqual([]);
    expect(agentDraft.model).toBe("default");
    expect(t.captureCharFrame()).toContain("> MCP");

    t.mockInput.pressArrow("up");
    await t.renderOnce();
    t.mockInput.pressArrow("right");
    await t.renderOnce();
    expect(modelChanges).toEqual(["primary"]);
    expect(agentDraft.model).toBe("primary");
    expect(t.captureCharFrame()).toContain("[primary]");
  });

  test("config model form exposes a Ctrl-T model test action", async () => {
    let tested = false;
    const t = await testRender(
      () =>
        App({
          controller: mockController({
            busy: () => false,
            items: [],
            configOpen: () => true,
            configStep: () => "model-fields",
            testModel: async () => {
              tested = true;
              return "Model test OK: default (gpt-4o-mini) -> OK";
            },
          }),
          onExit: () => {},
        }),
      { width: 120, height: 24 },
    );
    await t.renderOnce();
    expect(t.captureCharFrame()).toContain("Ctrl-T Test");

    t.mockInput.pressKey("t", { ctrl: true });
    await t.renderOnce();
    await t.renderOnce();

    expect(tested).toBe(true);
    expect(t.captureCharFrame()).toContain("Model test OK");
  });

  test("drag-selecting transcript text copies it through OSC52", async () => {
    let copied = "";
    const t = await testRender(
      () =>
        App({
          controller: mockController({
            busy: () => false,
            items: [{ kind: "message", id: "u1", role: "user", content: "find auth bugs", reasoning: "" }],
          }),
          onExit: () => {},
        }),
      {
        width: 84,
        height: 18,
        useMouse: true,
        autoFocus: true,
      },
    );
    t.renderer.copyToClipboardOSC52 = (text: string) => {
      copied = text;
      return true;
    };
    await t.renderOnce();

    await t.mockMouse.drag(3, 1, 17, 1);
    await t.renderOnce();

    expect(copied).toBe("find auth bugs");
  });
});
