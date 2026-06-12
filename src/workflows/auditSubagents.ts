/**
 * Vulnerability Discovery Harness — 8-stage subagent pipeline.
 *
 * Stages
 * ------
 * 1. Recon     — Survey binary metadata, segments, imports/exports, strings, entries
 * 2. Hunt      — Pattern-match for dangerous sinks
 * 3. Validate  — Confirm candidates are real bugs (not dead/sanitized)
 * 4. Gapfill   — Identify coverage gaps; route back to Hunt or Validate
 * 5. Dedupe    — Merge duplicates, cluster by root cause
 * 6. Trace     — Data-flow from entries to sinks, build exploitation paths
 * 7. Feedback  — Review quality; send weak findings back to Hunt (long loop)
 * 8. Report    — Synthesize final vulnerability report + PoC + remediation
 *
 * All agents share access to IDA MCP tools (decompile, disasm, xrefs, etc.).
 * There is no dedicated "decompile" agent — it is a tool, not a role.
 */

import type { BaseChatModel } from "@langchain/core/language_models/chat_models";

export interface SubagentSpec {
  name: string;
  description: string;
  systemPrompt: string;
  toolPrefixes: string[];
  /** Optional per-spec model override (rarely set; mostly runtime-provided). */
  model?: BaseChatModel;
}

export const AUDIT_SUBAGENTS: SubagentSpec[] = [
  {
    name: "recon",
    description:
      "Survey the target binary: collect metadata, segment layout, " +
      "imports/exports, function list, interesting strings, and entry " +
      "points.  Produce a structured reconnaissance summary.",
    systemPrompt:
      "You are the Recon agent.  Your job is to gather a comprehensive " +
      "overview of the binary under analysis.  Use IDA MCP tools to " +
      "enumerate segments, imports, exports, functions, strings, and " +
      "entry points.  Identify target architecture, metadata, attack " +
      "surface, and trust boundaries.  Output normal Markdown with a " +
      "structured summary that downstream agents can consume without " +
      "re-reading the binary.  Do not emit routing JSON.",
    toolPrefixes: [
      "get_metadata", "list_segments", "list_functions",
      "list_imports", "list_exports", "list_strings",
      "get_entry_points", "get_bytes",
    ],
  },
  {
    name: "hunt",
    description:
      "Search for dangerous code patterns: command injection, memory " +
      "unsafety, authentication bypass, path traversal, and other " +
      "common vulnerability classes.",
    systemPrompt:
      "You are the Hunt agent.  Systematically search the binary for " +
      "dangerous sinks and vulnerability patterns.  Use decompilation, " +
      "disassembly, byte pattern search, and string references to " +
      "locate candidates.  For each candidate, record the address, " +
      "function, pattern class, and a brief rationale.  Output normal " +
      "Markdown candidate findings; do not validate beyond recording " +
      "why each candidate is suspicious, and do not emit routing JSON.",
    toolPrefixes: [
      "decompile", "disasm", "find_bytes", "list_strings",
      "get_callees", "get_callers", "xrefs_to", "xrefs_from",
      "linear_disasm",
    ],
  },
  {
    name: "validate",
    description:
      "Confirm each vulnerability candidate is a real, exploitable " +
      "bug — not dead code, unreachable, or already sanitized.",
    systemPrompt:
      "You are the Validate agent.  For each candidate from Hunt, " +
      "verify reachability from an external entry point, confirm the " +
      "dangerous sink is not guarded by sanitization, and check that " +
      "the code path is not dead.  Do a full end-to-end check so every " +
      "accepted vulnerability is real, reliable, and practically valid.  " +
      "Mark each candidate as confirmed, rejected, or " +
      "needs-more-analysis.  Do not advance weak, partial, speculative, " +
      "or single-hop evidence.  Clearly state whether the current " +
      "evidence is ready for deduplication or whether more gap-filling " +
      "work is required.  Output normal Markdown only; branch decisions " +
      "are made by a separate structured router.",
    toolPrefixes: [
      "decompile", "disasm", "get_basic_blocks",
      "get_callees", "get_callers", "xrefs_to", "xrefs_from",
    ],
  },
  {
    name: "gapfill",
    description:
      "Identify coverage gaps in the analysis and request additional " +
      "work from Hunt or Validate to fill them.",
    systemPrompt:
      "You are the Gapfill agent.  Review the current findings and " +
      "the recon summary.  Identify functions, code regions, or " +
      "vulnerability classes that have not been adequately covered.  " +
      "If new candidates or unexplored code need discovery, recommend " +
      "**Hunt** as the next focus; if existing candidates only need " +
      "re-checking, recommend **Validate**.  State the recommended " +
      "next focus clearly in normal Markdown.  Do not emit routing JSON.",
    toolPrefixes: [
      "list_functions", "decompile", "disasm",
      "get_callees", "xrefs_to",
    ],
  },
  {
    name: "dedupe",
    description:
      "Merge duplicate findings and cluster related vulnerabilities " +
      "by root cause.",
    systemPrompt:
      "You are the Dedupe agent.  Take all confirmed findings and " +
      "identify duplicates (same root cause at different call sites) " +
      "and clusters (related issues from a single design flaw).  " +
      "Produce a deduplicated finding list with cluster annotations, " +
      "canonical finding ids, and merged evidence.  Output normal " +
      "Markdown and do not emit routing JSON.",
    toolPrefixes: [
      "decompile", "xrefs_to", "xrefs_from",
      "get_callers", "get_callees",
    ],
  },
  {
    name: "trace",
    description:
      "Trace data flow from external entry points to dangerous sinks " +
      "and construct exploitation paths.",
    systemPrompt:
      "You are the Trace agent.  For each deduplicated finding, " +
      "trace the complete data-flow path from the nearest external " +
      "input (network, file, IPC) to the vulnerable sink.  Document " +
      "each hop, any transformations, and constraints.  This forms " +
      "the basis for a proof-of-concept.  Output normal Markdown with " +
      "evidence paths that downstream review can verify.",
    toolPrefixes: [
      "decompile", "disasm", "get_basic_blocks",
      "get_callees", "get_callers", "xrefs_to", "xrefs_from",
      "get_bytes", "read_scalar",
    ],
  },
  {
    name: "feedback",
    description:
      "Review findings quality and send weak or under-evidenced " +
      "findings back to Hunt for another discovery round.",
    systemPrompt:
      "You are the Feedback agent.  Critically review each traced " +
      "finding for evidence quality: is the data-flow path complete? " +
      "Are constraints realistic?  Is the severity justified?  " +
      "If findings are weak, insufficient, or speculative, say so " +
      "explicitly and recommend another Hunt round.  Otherwise, " +
      "confirm the findings are solid and ready for reporting.  Output " +
      "normal Markdown only; branch decisions are made by a separate " +
      "structured router.",
    toolPrefixes: [
      "decompile", "disasm", "xrefs_to", "xrefs_from",
    ],
  },
  {
    name: "report",
    description:
      "Synthesize the final vulnerability report with severity " +
      "ratings, proof-of-concept sketches, and remediation advice.",
    systemPrompt:
      "You are the Report agent.  Compile all confirmed and traced " +
      "findings into a professional vulnerability report.  For each " +
      "finding include: title, severity (CVSS-like), affected " +
      "function/address, data-flow summary, proof-of-concept sketch, " +
      "and remediation recommendation.  Include confidence and evidence " +
      "quality, and do not include rejected candidates as findings.  " +
      "End with an executive summary.",
    toolPrefixes: [
      "decompile", "disasm",
    ],
  },
];

export const AUDIT_SUBAGENT_ORDER: readonly string[] = AUDIT_SUBAGENTS.map((s) => s.name);
