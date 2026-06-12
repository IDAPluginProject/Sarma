/**
 * Integration test: the audit-slim StateGraph, streamed with subgraphs:true,
 * must surface each stage's inner tokens under a "<name>:<uuid>" namespace
 * that the EventTranslator resolves back to the stage owner. This is the guard
 * for the regression where makeSubagentNode consumed the inner stream itself
 * (dropping tokens) and never threaded config (severing the namespace).
 */
import { describe, test, expect } from "bun:test";
import { FakeListChatModel } from "@langchain/core/utils/testing";
import { buildAuditSlimGraph } from "@/workflows/auditSlimGraph";
import { EventTranslator } from "@/engine/streaming";
import { StreamEventType } from "@/engine/enums";
import { HumanMessage } from "@langchain/core/messages";

describe("audit-slim graph streaming (integration)", () => {
  test("stage tokens surface with the stage namespace", async () => {
    // One canned response per stage; "verified" steers the verify router to report.
    const model = new FakeListChatModel({
      responses: ["recon output", "hunter output", "verified", "final report body"],
    });
    const graph = buildAuditSlimGraph(model, [], { structuredRouting: false });

    const translator = new EventTranslator("c1", "t1");
    const stagesSeen = new Set<string>();
    let tokenCount = 0;
    let sawReport = false;

    for await (const chunk of await graph.stream(
      {
        messages: [new HumanMessage("audit my app")],
        audit_task: "audit my app",
        stage_outputs: {},
        feedback_count: 0,
        current_stage: "",
      },
      { streamMode: ["messages", "updates", "custom"], subgraphs: true },
    )) {
      for (const evt of translator.translate(chunk)) {
        if (evt.type === StreamEventType.TOKEN) {
          tokenCount += 1;
          stagesSeen.add(String(evt.payload.subagent));
        }
        if (evt.type === StreamEventType.STAGE_START) {
          stagesSeen.add(String(evt.payload.stage));
        }
      }
    }

    // Read the final report straight off the terminal graph state.
    const finalState = await graph.invoke(
      {
        messages: [new HumanMessage("audit my app")],
        audit_task: "audit my app",
        stage_outputs: {},
        feedback_count: 0,
        current_stage: "",
      },
      { recursionLimit: 50 },
    );
    sawReport = Boolean((finalState as { stage_outputs?: Record<string, string> }).stage_outputs?.report);

    // The regression produced ZERO tokens and no stage attribution.
    expect(tokenCount).toBeGreaterThan(0);
    expect(stagesSeen.has("recon")).toBe(true);
    expect(stagesSeen.has("report")).toBe(true);
    expect(sawReport).toBe(true);
  });
});
