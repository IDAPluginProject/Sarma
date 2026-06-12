import { expect, test, describe } from "bun:test";
import { buildAuditGraph, buildSubagentPrompt, routeNext } from "@/workflows/auditGraph";
import { AUDIT_SUBAGENTS } from "@/workflows/auditSubagents";
import { buildAuditSlimGraph, DEFAULT_MAX_VERIFY_FEEDBACK } from "@/workflows/auditSlimGraph";
import { AUDIT_SLIM_SUBAGENTS } from "@/workflows/auditSlimSubagents";
import { buildSystemPrompt, RUFLO_SYSTEM_PROMPT, BASE_SYSTEM_PROMPT } from "@/engine/prompts";
import { buildRufloPrompt } from "@/workflows/ruflo";
import { ResolvedSkill } from "@/engine/models";
import { EventTranslator, ORCHESTRATOR } from "@/engine/streaming";
import { StreamEventType } from "@/engine/enums";
import { FakeListChatModel } from "@langchain/core/utils/testing";
import { HumanMessage } from "@langchain/core/messages";

describe("routeNext", () => {
  test("parses route_json line", () => {
    expect(routeNext('route_json: {"next": "gapfill"}', new Set(["gapfill", "dedupe"]))).toBe("gapfill");
  });
  test("parses bare json object", () => {
    expect(routeNext('{"decision": "dedupe"}', new Set(["gapfill", "dedupe"]))).toBe("dedupe");
  });
  test("parses key: value line", () => {
    expect(routeNext("next: hunt", new Set(["hunt", "report"]))).toBe("hunt");
  });
  test("ignores disallowed values", () => {
    expect(routeNext("next: nowhere", new Set(["hunt", "report"]))).toBe("");
  });
  test("returns empty when nothing matches", () => {
    expect(routeNext("just some prose here", new Set(["hunt"]))).toBe("");
  });
});

describe("audit workflow graph", () => {
  test("runs the main audit path without gapfill when validate is ready", async () => {
    const model = new FakeListChatModel({
      responses: ["router fallback unused"],
    });
    const graph = buildAuditGraph(model, [], {
      structuredRouting: false,
      subagentModels: {
        recon: new FakeListChatModel({ responses: ["recon summary"] }),
        hunt: new FakeListChatModel({ responses: ["hunt candidates"] }),
        validate: new FakeListChatModel({ responses: ["confirmed findings ready for dedupe"] }),
        dedupe: new FakeListChatModel({ responses: ["deduped findings"] }),
        trace: new FakeListChatModel({ responses: ["trace evidence"] }),
        feedback: new FakeListChatModel({ responses: ["solid findings ready for reporting"] }),
        report: new FakeListChatModel({ responses: ["final report"] }),
      },
    });
    const finalState = await graph.invoke(
      {
        messages: [new HumanMessage("audit target")],
        audit_task: "audit target",
        stage_outputs: {},
        gapfill_count: 0,
        feedback_count: 0,
        current_stage: "",
      },
      { recursionLimit: 80 },
    );
    const outputs = (finalState as { stage_outputs?: Record<string, string> }).stage_outputs ?? {};
    expect(outputs.recon).toBe("recon summary");
    expect(outputs.gapfill).toBeUndefined();
    expect(outputs.report).toBe("final report");
  });

  test("bounds the validate gapfill branch before converging to report", async () => {
    const model = new FakeListChatModel({
      responses: ["router fallback unused"],
    });
    const graph = buildAuditGraph(model, [], {
      structuredRouting: false,
      subagentModels: {
        recon: new FakeListChatModel({ responses: ["recon summary"] }),
        hunt: new FakeListChatModel({ responses: ["first hunt candidates", "second hunt candidates"] }),
        validate: new FakeListChatModel({
          responses: ["needs-more-analysis: coverage gap remains", "confirmed findings ready for dedupe"],
        }),
        gapfill: new FakeListChatModel({ responses: ["recommended next focus: Hunt new candidate classes"] }),
        dedupe: new FakeListChatModel({ responses: ["deduped findings"] }),
        trace: new FakeListChatModel({ responses: ["trace evidence"] }),
        feedback: new FakeListChatModel({ responses: ["solid findings ready for reporting"] }),
        report: new FakeListChatModel({ responses: ["final report"] }),
      },
    });
    const finalState = await graph.invoke(
      {
        messages: [new HumanMessage("audit target")],
        audit_task: "audit target",
        stage_outputs: {},
        gapfill_count: 0,
        feedback_count: 0,
        current_stage: "",
      },
      { recursionLimit: 100 },
    );
    const state = finalState as { stage_outputs?: Record<string, string>; gapfill_count?: number };
    const outputs = state.stage_outputs ?? {};
    expect(state.gapfill_count).toBe(3);
    expect(outputs.gapfill).toContain("Hunt");
    expect(outputs.report).toBe("final report");
  });

  test("streams audit router nodes as workflow lifecycle events", async () => {
    const model = new FakeListChatModel({
      responses: [
        "recon summary",
        "hunt candidates",
        "confirmed findings ready for dedupe",
        "deduped findings",
        "trace evidence",
        "solid findings ready for reporting",
        "final report",
      ],
    });
    const graph = buildAuditGraph(model, [], { structuredRouting: false });
    const translator = new EventTranslator("c1", "t1");
    const started = new Set<string>();
    const completed = new Set<string>();

    for await (const chunk of await graph.stream(
      {
        messages: [new HumanMessage("audit target")],
        audit_task: "audit target",
        stage_outputs: {},
        gapfill_count: 0,
        feedback_count: 0,
        current_stage: "",
      },
      { streamMode: ["messages", "updates", "custom"], subgraphs: true, recursionLimit: 80 },
    )) {
      for (const event of translator.translate(chunk)) {
        if (event.type === StreamEventType.STAGE_START) started.add(String(event.payload.stage));
        if (event.type === StreamEventType.STAGE_COMPLETE) completed.add(String(event.payload.stage));
      }
    }

    expect(started.has("validate_check")).toBe(true);
    expect(started.has("feedback_check")).toBe(true);
    expect(completed.has("validate_check")).toBe(true);
    expect(completed.has("feedback_check")).toBe(true);
  });
});

describe("audit-slim workflow graph", () => {
  test("runs recon -> hunter -> verify -> report when verify confirms findings", async () => {
    const model = new FakeListChatModel({
      responses: ["router fallback unused"],
    });
    const graph = buildAuditSlimGraph(model, [], {
      structuredRouting: false,
      subagentModels: {
        recon: new FakeListChatModel({ responses: ["weak areas mapped"] }),
        hunter: new FakeListChatModel({ responses: ["candidate finding"] }),
        verify: new FakeListChatModel({ responses: ["verified: reliable finding ready for reporting"] }),
        report: new FakeListChatModel({ responses: ["verified-only final report"] }),
      },
    });

    const finalState = await graph.invoke(
      {
        messages: [new HumanMessage("audit target")],
        audit_task: "audit target",
        stage_outputs: {},
        feedback_count: 0,
        current_stage: "",
      },
      { recursionLimit: 50 },
    );
    const state = finalState as { stage_outputs?: Record<string, string>; feedback_count?: number };
    const outputs = state.stage_outputs ?? {};
    expect(outputs.recon).toBe("weak areas mapped");
    expect(outputs.hunter).toBe("candidate finding");
    expect(outputs.verify).toContain("verified");
    expect(outputs.report).toBe("verified-only final report");
    expect(state.feedback_count ?? 0).toBe(0);
  });

  test("sends weak verify results back to hunter and caps the feedback loop", async () => {
    const model = new FakeListChatModel({
      responses: ["router fallback unused"],
    });
    const graph = buildAuditSlimGraph(model, [], {
      structuredRouting: false,
      subagentModels: {
        recon: new FakeListChatModel({ responses: ["weak areas mapped"] }),
        hunter: new FakeListChatModel({
          responses: ["candidate v1", "candidate v2", "candidate v3", "candidate v4"],
        }),
        verify: new FakeListChatModel({
          responses: [
            "needs-hunter: reachability is weak",
            "needs-hunter: sink evidence is weak",
            "needs-hunter: sanitizer not ruled out",
            "needs-hunter: still unsupported",
          ],
        }),
        report: new FakeListChatModel({ responses: ["no verified findings survived"] }),
      },
    });

    const finalState = await graph.invoke(
      {
        messages: [new HumanMessage("audit target")],
        audit_task: "audit target",
        stage_outputs: {},
        feedback_count: 0,
        current_stage: "",
      },
      { recursionLimit: 80 },
    );
    const state = finalState as { stage_outputs?: Record<string, string>; feedback_count?: number };
    expect(state.feedback_count).toBe(DEFAULT_MAX_VERIFY_FEEDBACK);
    expect(state.stage_outputs?.verify).toContain("needs-hunter");
    expect(state.stage_outputs?.report).toBe("no verified findings survived");
  });
});

describe("prompt assembly", () => {
  test("audit mode uses base prompt", () => {
    const p = buildSystemPrompt(null, null, "audit");
    expect(p).toBe(BASE_SYSTEM_PROMPT);
  });
  test("ruflo mode uses ruflo prompt", () => {
    const p = buildSystemPrompt(null, null, "ruflo");
    expect(p.startsWith(RUFLO_SYSTEM_PROMPT)).toBe(true);
  });
  test("override + skill appended in order", () => {
    const skill = new ResolvedSkill({ name: "x", systemPromptSuffix: "SKILL-SUFFIX" });
    const p = buildSystemPrompt(skill, "OVERRIDE", "audit");
    const idxOverride = p.indexOf("OVERRIDE");
    const idxSkill = p.indexOf("SKILL-SUFFIX");
    expect(idxOverride).toBeGreaterThan(0);
    expect(idxSkill).toBeGreaterThan(idxOverride);
  });
  test("buildRufloPrompt joins base and ruflo prompt", () => {
    const p = buildRufloPrompt("BASE");
    expect(p).toContain("BASE");
    expect(p).toContain("Ruflo mode");
    expect(p).toContain("---");
  });
  test("audit subagent prompt matches Python: stage prompt plus stage skill only", () => {
    const skill = new ResolvedSkill({ name: "stage", systemPromptSuffix: "STAGE-SKILL" });
    const p = buildSubagentPrompt("STAGE-PROMPT", skill);
    expect(p).toContain("STAGE-PROMPT");
    expect(p).toContain("STAGE-SKILL");
    expect(p).not.toContain("WORKFLOW-PROMPT");
  });
  test("audit stage prompts keep routing out of visible JSON output", () => {
    for (const stage of AUDIT_SUBAGENTS) {
      expect(stage.systemPrompt).not.toContain("route_json");
    }
    expect(AUDIT_SUBAGENTS.find((s) => s.name === "validate")!.systemPrompt).toContain("separate structured router");
    expect(AUDIT_SUBAGENTS.find((s) => s.name === "feedback")!.systemPrompt).toContain("separate structured router");
  });
  test("audit-slim stage prompts keep routing out of visible JSON output", () => {
    for (const stage of AUDIT_SLIM_SUBAGENTS) {
      expect(stage.systemPrompt).not.toContain("route_json");
      expect(stage.systemPrompt).toContain("normal Markdown");
    }
    expect(AUDIT_SLIM_SUBAGENTS.find((s) => s.name === "verify")!.systemPrompt).toContain("separate structured router");
    expect(AUDIT_SLIM_SUBAGENTS.find((s) => s.name === "report")!.systemPrompt).toContain("Do not revive rejected or unverified candidates");
  });
});

describe("EventTranslator", () => {
  test("top-level token chunk → TOKEN with orchestrator subagent", () => {
    const tr = new EventTranslator("c1", "t1");
    const chunk = [[], "messages", [{ content: "hello" }, {}]];
    const events = tr.translate(chunk);
    expect(events.length).toBe(1);
    expect(events[0]!.type).toBe(StreamEventType.TOKEN);
    expect(events[0]!.payload.content).toBe("hello");
    expect(events[0]!.payload.subagent).toBe(ORCHESTRATOR);
  });

  test("message chunks preserve reasoning_content in TOKEN events", () => {
    const tr = new EventTranslator("c1", "t1");
    const chunk = [
      ["recon"],
      "messages",
      [{ content: "scanning", additional_kwargs: { reasoning_content: "checking routes" } }, {}],
    ];
    const events = tr.translate(chunk);
    const token = events.find((e) => e.type === StreamEventType.TOKEN)!;
    expect(token.payload.content).toBe("scanning");
    expect(token.payload.reasoning_content).toBe("checking routes");
    expect(token.payload.subagent).toBe("recon");
  });

  test("ToolMessage token is suppressed", () => {
    const tr = new EventTranslator("c1", "t1");
    const chunk = [[], "messages", [{ content: "result", tool_call_id: "abc" }, {}]];
    expect(tr.translate(chunk)).toEqual([]);
  });

  test("AIMessage with tool_calls token is suppressed", () => {
    const tr = new EventTranslator("c1", "t1");
    const chunk = [[], "messages", [{ content: "", tool_calls: [{ name: "x", id: "1" }] }, {}]];
    expect(tr.translate(chunk)).toEqual([]);
  });

  test("ns entering known workflow stage emits STAGE_START", () => {
    const tr = new EventTranslator("c1", "t1");
    const chunk = [["recon"], "messages", [{ content: "scanning" }, {}]];
    const events = tr.translate(chunk);
    const types = events.map((e) => e.type);
    expect(types).toContain(StreamEventType.STAGE_START);
    expect(types).toContain(StreamEventType.TOKEN);
    const stageEvt = events.find((e) => e.type === StreamEventType.STAGE_START)!;
    expect(stageEvt.payload.stage).toBe("recon");
    const tokenEvt = events.find((e) => e.type === StreamEventType.TOKEN)!;
    expect(tokenEvt.payload.subagent).toBe("recon");
  });

  test("transition between workflow stages completes the previous", () => {
    const tr = new EventTranslator("c1", "t1");
    tr.translate([["recon"], "messages", [{ content: "a" }, {}]]);
    const events = tr.translate([["hunt"], "messages", [{ content: "b" }, {}]]);
    const types = events.map((e) => e.type);
    expect(types).toContain(StreamEventType.STAGE_COMPLETE);
    expect(types).toContain(StreamEventType.STAGE_START);
  });

  test("updates tool start from agent node", () => {
    const tr = new EventTranslator("c1", "t1");
    const chunk = [
      [],
      "updates",
      { agent: { messages: [{ tool_calls: [{ name: "ida__decompile", args: { addr: "0x1" }, id: "tc1" }] }] } },
    ];
    const events = tr.translate(chunk);
    const start = events.find((e) => e.type === StreamEventType.TOOL_START);
    expect(start).toBeDefined();
    expect(start!.payload.tool_name).toBe("ida__decompile");
    expect(start!.payload.tool_call_id).toBe("tc1");
    expect(start!.payload.args_json).toBe('{"addr":"0x1"}');
  });

  test("updates tool result from tools node", () => {
    const tr = new EventTranslator("c1", "t1");
    const chunk = [
      [],
      "updates",
      { tools: { messages: [{ name: "ida__decompile", tool_call_id: "tc1", content: "int main(){}" }] } },
    ];
    const events = tr.translate(chunk);
    const res = events.find((e) => e.type === StreamEventType.TOOL_RESULT);
    expect(res).toBeDefined();
    expect(res!.payload.result).toBe("int main(){}");
    expect(res!.payload.result_summary).toBe("int main(){}");
  });

  test("error tool result emits TOOL_ERROR", () => {
    const tr = new EventTranslator("c1", "t1");
    const chunk = [
      [],
      "updates",
      { tools: { messages: [{ name: "x", tool_call_id: "tc2", content: "boom", status: "error" }] } },
    ];
    const events = tr.translate(chunk);
    const err = events.find((e) => e.type === StreamEventType.TOOL_ERROR);
    expect(err).toBeDefined();
    expect(err!.payload.error).toBe("boom");
    expect(err!.payload.error_text).toBe("boom");
  });

  test("custom audit lifecycle emits stage events", () => {
    const tr = new EventTranslator("c1", "t1");
    const startEvents = tr.translate([["recon"], "custom", { type: "subagent_start", name: "recon" }]);
    expect(startEvents.some((e) => e.type === StreamEventType.STAGE_START)).toBe(true);
    const doneEvents = tr.translate([["recon"], "custom", { type: "subagent_complete", name: "recon" }]);
    expect(doneEvents.some((e) => e.type === StreamEventType.STAGE_COMPLETE)).toBe(true);
  });

  test("custom audit_route → CUSTOM_PROGRESS", () => {
    const tr = new EventTranslator("c1", "t1");
    const events = tr.translate([[], "custom", { type: "audit_route", from: "validate", to: "dedupe" }]);
    expect(events[0]!.type).toBe(StreamEventType.CUSTOM_PROGRESS);
  });

  test("task tool call tracks subagent and emits SUBAGENT_START", () => {
    const tr = new EventTranslator("c1", "t1");
    const chunk = [
      [],
      "updates",
      { agent: { messages: [{ tool_calls: [{ name: "task", args: { subagent_type: "code-reviewer", description: "review" }, id: "task1" }] }] } },
    ];
    const events = tr.translate(chunk);
    const sa = events.find((e) => e.type === StreamEventType.SUBAGENT_START);
    expect(sa).toBeDefined();
    expect(sa!.payload.subagent).toBe("code-reviewer");
  });

  test("ruflo delegate_task tracks dynamic subagent lifecycle", () => {
    const tr = new EventTranslator("c1", "t1");
    const startChunk = [
      [],
      "updates",
      {
        agent: {
          messages: [
            {
              tool_calls: [
                {
                  name: "delegate_task",
                  args: { subagent_name: "verifier", task: "check the patch" },
                  id: "delegate1",
                },
              ],
            },
          ],
        },
      },
    ];
    const startEvents = tr.translate(startChunk);
    const start = startEvents.find((e) => e.type === StreamEventType.SUBAGENT_START);
    expect(start).toBeDefined();
    expect(start!.payload.subagent).toBe("verifier");
    expect(start!.payload.description).toBe("check the patch");

    const doneEvents = tr.translate([
      [],
      "updates",
      { tools: { messages: [{ name: "delegate_task", tool_call_id: "delegate1", content: "Result: ok" }] } },
    ]);
    const done = doneEvents.find((e) => e.type === StreamEventType.SUBAGENT_COMPLETE);
    expect(done).toBeDefined();
    expect(done!.payload.subagent).toBe("verifier");
  });

  test("ruflo delegate_task tracks multiple parallel subagent calls independently", () => {
    const tr = new EventTranslator("c1", "t1");
    const startEvents = tr.translate([
      [],
      "updates",
      {
        agent: {
          messages: [
            {
              tool_calls: [
                {
                  name: "delegate_task",
                  args: { subagent_name: "recon", task: "map files" },
                  id: "delegate-recon",
                },
                {
                  name: "delegate_task",
                  args: { subagent_name: "reviewer", task: "review risky code" },
                  id: "delegate-reviewer",
                },
              ],
            },
          ],
        },
      },
    ]);
    const starts = startEvents.filter((e) => e.type === StreamEventType.SUBAGENT_START);
    expect(starts.map((e) => e.payload.subagent).sort()).toEqual(["recon", "reviewer"]);

    const doneEvents = tr.translate([
      [],
      "updates",
      {
        tools: {
          messages: [
            { name: "delegate_task", tool_call_id: "delegate-reviewer", content: "Result: review done" },
            { name: "delegate_task", tool_call_id: "delegate-recon", content: "Result: recon done" },
          ],
        },
      },
    ]);
    const completes = doneEvents.filter((e) => e.type === StreamEventType.SUBAGENT_COMPLETE);
    expect(completes.map((e) => e.payload.subagent).sort()).toEqual(["recon", "reviewer"]);
  });
});
