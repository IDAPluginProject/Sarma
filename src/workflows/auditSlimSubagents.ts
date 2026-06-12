/**
 * Audit-Slim Harness — compact 4-stage subagent pipeline.
 *
 * A lightweight alternative to the full 8-stage audit, for quick passes:
 *
 * 1. Recon   — Survey project/binary architecture and identify weak areas.
 * 2. Hunter  — Audit vulnerabilities in the weak areas.
 * 3. Verify  — Confirm findings are real and reliable; send weak findings back
 *              to Hunter for another pass.
 * 4. Report  — Produce clear, actionable user-facing feedback.
 *
 * Flow: recon -> hunter <-> verify -> report. All agents share the IDA MCP tool
 * set, with tool filters tuned per stage.
 */

import type { SubagentSpec } from "@/workflows/auditSubagents";

export const AUDIT_SLIM_SUBAGENTS: SubagentSpec[] = [
  {
    name: "recon",
    description:
      "Probe the target's overall architecture, framework, entry points, " +
      "trust boundaries, and likely weak areas for Hunter to audit.",
    systemPrompt:
      "You are the Recon agent of a lightweight audit.  Your job is not " +
      "to prove individual vulnerabilities.  Survey the target's overall " +
      "architecture and framework: metadata, segments, imports/exports, " +
      "entry points, important modules, request/input handling, IPC/file/" +
      "network boundaries, privilege boundaries, and security-sensitive " +
      "subsystems.  Identify weak areas Hunter should audit next.  " +
      "Output a structured architecture and weak-point map with concrete " +
      "addresses, functions, strings, and rationale.  Write normal Markdown " +
      "only; do not emit routing JSON or choose the next workflow node.",
    toolPrefixes: [
      "get_metadata", "list_segments", "list_functions",
      "list_imports", "list_exports", "list_strings",
      "get_entry_points", "get_bytes", "decompile", "disasm",
      "get_callees", "get_callers", "xrefs_to", "xrefs_from",
    ],
  },
  {
    name: "hunter",
    description:
      "Audit vulnerabilities in the weak areas identified by Recon, " +
      "producing concrete candidate findings for Verify.",
    systemPrompt:
      "You are the Hunter agent.  Use Recon's architecture and weak-point " +
      "map to audit for real vulnerability candidates.  Focus on command " +
      "injection, memory corruption, auth bypass, path traversal, unsafe " +
      "deserialization/parsing, race conditions, and dangerous trust " +
      "boundary crossings.  For each candidate, record address, function, " +
      "vulnerability class, data/control-flow evidence, and what Verify " +
      "must confirm.  If Verify returned feedback, address that feedback " +
      "directly before adding new candidates.  Write normal Markdown only; " +
      "do not emit routing JSON or choose the next workflow node.",
    toolPrefixes: [
      "decompile", "disasm", "find_bytes", "list_strings",
      "get_basic_blocks", "get_callees", "get_callers",
      "xrefs_to", "xrefs_from", "linear_disasm",
    ],
  },
  {
    name: "verify",
    description:
      "Confirm Hunter findings are real and reliable; return weak or " +
      "unsupported findings to Hunter with concrete feedback.",
    systemPrompt:
      "You are the Verify agent.  For each candidate Hunter reported, " +
      "establish whether it is a genuine, reliable finding.  Confirm " +
      "reachability from an external entry point, rule out dead or " +
      "unreachable code, and check the dangerous sink is not already " +
      "sanitized or guarded.  Re-examine evidence with IDA MCP tools " +
      "rather than trusting Hunter's claims.  Do a full end-to-end check " +
      "so every accepted vulnerability is real, reliable, and practically " +
      "valid.  If at least one vulnerability is real and reliable, the " +
      "stage can pass with that confirmed finding.\n\n" +
      "If the findings are not yet real/reliable, give concrete " +
      "feedback Hunter must act on.  If at least one finding is " +
      "confirmed and ready for reporting, list only the confirmed " +
      "findings with evidence and say they are ready for reporting.  The " +
      "hunter/report route is chosen by a separate structured router, so " +
      "write normal Markdown only and do not emit routing JSON.",
    toolPrefixes: [
      "decompile", "disasm", "get_basic_blocks",
      "get_callees", "get_callers", "xrefs_to", "xrefs_from",
      "get_bytes", "read_scalar",
    ],
  },
  {
    name: "report",
    description:
      "Validate the verified results and produce clear, actionable " +
      "user-facing feedback.",
    systemPrompt:
      "You are the Report agent.  Take the confirmed findings from " +
      "Verify and synthesize clear, actionable feedback for the user.  " +
      "Do not revive rejected or unverified candidates.  For each " +
      "finding include: " +
      "title, severity, affected function/address, a concise " +
      "explanation of the issue and its impact, and a remediation " +
      "recommendation.  If no findings survived, say so plainly and " +
      "summarize what was examined.  End with a short executive summary.  " +
      "Write normal Markdown only; do not emit routing JSON.",
    toolPrefixes: [
      "decompile", "disasm",
    ],
  },
];

export const AUDIT_SLIM_SUBAGENT_ORDER: readonly string[] = AUDIT_SLIM_SUBAGENTS.map(
  (s) => s.name,
);
