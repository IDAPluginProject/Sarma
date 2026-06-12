/**
 * Audit-Slim graph — compact 4-stage pipeline.
 *
 * recon -> hunter <-> verify -> report. Reuses the subagent node machinery
 * from the full audit graph so streaming and per-stage event attribution
 * behave identically.
 */

import { createAgent } from "langchain";
import type { StructuredToolInterface } from "@langchain/core/tools";
import type { BaseChatModel } from "@langchain/core/language_models/chat_models";
import { StateGraph, START, END, Command } from "@langchain/langgraph";
import {
  AuditState,
  type AuditStateType,
  makeSubagentNode,
  makeRouteAgent,
  routeNext,
  routeNextStructured,
} from "@/workflows/auditGraph";
import {
  AUDIT_SLIM_SUBAGENTS,
  AUDIT_SLIM_SUBAGENT_ORDER,
} from "@/workflows/auditSlimSubagents";
import type { SubagentSpec } from "@/workflows/auditSubagents";
import type { ResolvedSkill } from "@/engine/models";
import { getWriter } from "@langchain/langgraph";
import type { TokenEstimator } from "@/context/tokenizer";

export const DEFAULT_MAX_VERIFY_FEEDBACK = 3;

function writeAuditEvent(data: Record<string, unknown>): void {
  let writer: ((chunk: unknown) => void) | undefined;
  try {
    writer = getWriter();
  } catch {
    return;
  }
  writer?.(data);
}

/** Route weak verify results back to Hunter, or confirmed results to Report. */
function verifyRouterFromDecision(state: AuditStateType, decision: string): Command {
  const output = (state.stage_outputs ?? {}).verify ?? "";
  const lower = output.toLowerCase();
  const normalized = lower.replace(/^\s+/, "");
  const count = state.feedback_count ?? 0;
  const needsHunter =
    normalized.startsWith("needs-hunter") ||
    [
      "needs-hunter",
      "needs hunter",
      "not reliable",
      "not confirmed",
      "insufficient",
      "unsupported",
      "false positive",
      "weak",
    ].some((marker) => lower.includes(marker));

  if (
    (decision === "hunter" ||
      (!decision && needsHunter && !normalized.startsWith("verified"))) &&
    count < DEFAULT_MAX_VERIFY_FEEDBACK
  ) {
    const nextCount = count + 1;
    writeAuditEvent({
      type: "audit_route",
      from: "verify",
      to: "hunter",
      loop: "feedback",
      count: nextCount,
    });
    return new Command({ update: { feedback_count: nextCount }, goto: "hunter" });
  }

  writeAuditEvent({ type: "audit_route", from: "verify", to: "report" });
  return new Command({ goto: "report" });
}

export interface BuildAuditSlimGraphOptions {
  systemPrompt?: string;
  subagentSpecs?: SubagentSpec[];
  subagentModels?: Record<string, BaseChatModel> | null;
  subagentMcpAllow?: Record<string, string[] | null> | null;
  subagentSkills?: Record<string, ResolvedSkill | null> | null;
  structuredRouting?: boolean;
  maxPriorStageTokens?: number;
  estimateText?: TokenEstimator;
  compileKwargs?: Record<string, unknown>;
}

/** Build and compile the audit-slim StateGraph. */
export function buildAuditSlimGraph(
  model: BaseChatModel,
  tools: StructuredToolInterface[],
  options: BuildAuditSlimGraphOptions = {},
) {
  const specs = options.subagentSpecs ?? AUDIT_SLIM_SUBAGENTS;
  const specMap = new Map(specs.map((s) => [s.name, s]));
  const structuredRouting = options.structuredRouting ?? true;

  const verifyRouteAgent = structuredRouting
    ? makeRouteAgent(model, "audit_slim_verify_router")
    : null;

  type NodeFn = (state: AuditStateType, config: never) => Promise<Partial<AuditStateType>>;
  const builder = new StateGraph(AuditState);
  const g = builder as unknown as {
    addNode: (name: string, fn: NodeFn, opts?: { ends?: string[] }) => void;
    addEdge: (from: string, to: string) => void;
    compile: (opts?: Record<string, unknown>) => ReturnType<StateGraph<typeof AuditState.spec>["compile"]>;
  };

  for (const name of AUDIT_SLIM_SUBAGENT_ORDER) {
    const nodeFn = makeSubagentNode(name, specMap.get(name)!, model, tools, {
      subagentModels: options.subagentModels,
      allowedMcpServers: (options.subagentMcpAllow ?? {})[name],
      skill: (options.subagentSkills ?? {})[name],
      maxPriorStageTokens: options.maxPriorStageTokens,
      estimateText: options.estimateText,
    }) as unknown as NodeFn;
    g.addNode(name, nodeFn);
  }

  const verifyCheck: NodeFn = async (state) => {
    writeAuditEvent({
      type: "subagent_start",
      name: "verify_check",
      description: "same-model structured router: hunter | report",
    });
    const output = (state.stage_outputs ?? {}).verify ?? "";
    let decision: string;
    if (verifyRouteAgent === null) {
      decision = routeNext(output, new Set(["hunter", "report"]));
    } else {
      try {
        decision = await routeNextStructured(
          verifyRouteAgent,
          "verify",
          output,
          new Set(["hunter", "report"]),
        );
      } catch {
        decision = routeNext(output, new Set(["hunter", "report"]));
      }
    }
    const next = verifyRouterFromDecision(state, decision) as unknown as Partial<AuditStateType>;
    writeAuditEvent({ type: "subagent_complete", name: "verify_check" });
    return next;
  };

  g.addNode("verify_check", verifyCheck, { ends: ["hunter", "report"] });

  // Harness: recon -> hunter <-> verify -> report
  g.addEdge(START, "recon");
  g.addEdge("recon", "hunter");
  g.addEdge("hunter", "verify");
  g.addEdge("verify", "verify_check");
  g.addEdge("report", END);

  return g.compile(options.compileKwargs);
}
