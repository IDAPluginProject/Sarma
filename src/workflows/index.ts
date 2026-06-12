/**
 * Workflow metadata registry (data-only).
 *
 * The Python `workflows` package also owns Rich/TUI graph rendering. Here we
 * keep only the data the runtime resolver needs: which subagents each workflow
 * owns and the default workflow. Rendering is a phase-6 concern (CLI/TUI).
 */

import { AUDIT_SUBAGENT_ORDER } from "@/workflows/auditSubagents";
import { AUDIT_SLIM_SUBAGENT_ORDER } from "@/workflows/auditSlimSubagents";

export interface WorkflowMeta {
  name: string;
  description: string;
  isDefault: boolean;
  subagents: readonly string[];
}

const WORKFLOW_METAS: Record<string, WorkflowMeta> = {
  ruflo: {
    name: "ruflo",
    description: "Primary agent with focused delegated subagents",
    isDefault: true,
    subagents: [],
  },
  audit: {
    name: "audit",
    description: "Full audit pipeline with 8 stages",
    isDefault: false,
    subagents: AUDIT_SUBAGENT_ORDER,
  },
  "audit-slim": {
    name: "audit-slim",
    description: "Compact 4-stage audit pipeline",
    isDefault: false,
    subagents: AUDIT_SLIM_SUBAGENT_ORDER,
  },
};

export function getWorkflowMeta(name: string): WorkflowMeta | null {
  return WORKFLOW_METAS[name] ?? null;
}

export function listWorkflowMetas(): WorkflowMeta[] {
  return Object.values(WORKFLOW_METAS);
}

export function defaultWorkflowName(): string {
  return listWorkflowMetas().find((w) => w.isDefault)?.name ?? "ruflo";
}

/** Return subagent names owned by a workflow (empty for single-agent flows). */
export function subagentsForWorkflow(workflow: string): string[] {
  return [...(getWorkflowMeta(workflow)?.subagents ?? [])];
}
