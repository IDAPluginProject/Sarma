"""Vulnerability Discovery Harness — 8-stage subagent pipeline.

Stages
------
1. Recon     — Survey binary metadata, segments, imports/exports, strings, entries
2. Hunt      — Pattern-match for dangerous sinks
3. Validate  — Confirm candidates are real bugs (not dead/sanitized)
4. Gapfill   — Identify coverage gaps, loop back to Hunt/Validate
5. Dedupe    — Merge duplicates, cluster by root cause
6. Trace     — Data-flow from entries to sinks, build exploitation paths
7. Feedback  — Review quality, send weak findings back to Gapfill
8. Report    — Synthesize final vulnerability report + PoC + remediation

All agents share access to IDA MCP tools (decompile, disasm, xrefs, etc.).
There is no dedicated "decompile" agent — it is a tool, not a role.
"""

from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# Subagent specifications
# ---------------------------------------------------------------------------

AUDIT_SUBAGENTS: list[dict[str, Any]] = [
    {
        "name": "recon",
        "description": (
            "Survey the target binary: collect metadata, segment layout, "
            "imports/exports, function list, interesting strings, and entry "
            "points.  Produce a structured reconnaissance summary."
        ),
        "system_prompt": (
            "You are the Recon agent.  Your job is to gather a comprehensive "
            "overview of the binary under analysis.  Use IDA MCP tools to "
            "enumerate segments, imports, exports, functions, strings, and "
            "entry points.  Output a structured summary that downstream "
            "agents can consume without re-reading the binary."
        ),
        "_tool_prefixes": [
            "get_metadata", "list_segments", "list_functions",
            "list_imports", "list_exports", "list_strings",
            "get_entry_points", "get_bytes",
        ],
    },
    {
        "name": "hunt",
        "description": (
            "Search for dangerous code patterns: command injection, memory "
            "unsafety, authentication bypass, path traversal, and other "
            "common vulnerability classes."
        ),
        "system_prompt": (
            "You are the Hunt agent.  Systematically search the binary for "
            "dangerous sinks and vulnerability patterns.  Use decompilation, "
            "disassembly, byte pattern search, and string references to "
            "locate candidates.  For each candidate, record the address, "
            "function, pattern class, and a brief rationale."
        ),
        "_tool_prefixes": [
            "decompile", "disasm", "find_bytes", "list_strings",
            "get_callees", "get_callers", "xrefs_to", "xrefs_from",
            "linear_disasm",
        ],
    },
    {
        "name": "validate",
        "description": (
            "Confirm each vulnerability candidate is a real, exploitable "
            "bug — not dead code, unreachable, or already sanitized."
        ),
        "system_prompt": (
            "You are the Validate agent.  For each candidate from Hunt, "
            "verify reachability from an external entry point, confirm the "
            "dangerous sink is not guarded by sanitization, and check that "
            "the code path is not dead.  Mark each candidate as confirmed, "
            "rejected, or needs-more-analysis."
        ),
        "_tool_prefixes": [
            "decompile", "disasm", "get_basic_blocks",
            "get_callees", "get_callers", "xrefs_to", "xrefs_from",
        ],
    },
    {
        "name": "gapfill",
        "description": (
            "Identify coverage gaps in the analysis and request additional "
            "work from Hunt or Validate to fill them."
        ),
        "system_prompt": (
            "You are the Gapfill agent.  Review the current findings and "
            "the recon summary.  Identify functions, code regions, or "
            "vulnerability classes that have not been adequately covered.  "
            "Produce targeted requests for the Hunt and Validate agents "
            "to investigate specific gaps."
        ),
        "_tool_prefixes": [
            "list_functions", "decompile", "disasm",
            "get_callees", "xrefs_to",
        ],
    },
    {
        "name": "dedupe",
        "description": (
            "Merge duplicate findings and cluster related vulnerabilities "
            "by root cause."
        ),
        "system_prompt": (
            "You are the Dedupe agent.  Take all confirmed findings and "
            "identify duplicates (same root cause at different call sites) "
            "and clusters (related issues from a single design flaw).  "
            "Produce a deduplicated finding list with cluster annotations."
        ),
        "_tool_prefixes": [
            "decompile", "xrefs_to", "xrefs_from",
            "get_callers", "get_callees",
        ],
    },
    {
        "name": "trace",
        "description": (
            "Trace data flow from external entry points to dangerous sinks "
            "and construct exploitation paths."
        ),
        "system_prompt": (
            "You are the Trace agent.  For each deduplicated finding, "
            "trace the complete data-flow path from the nearest external "
            "input (network, file, IPC) to the vulnerable sink.  Document "
            "each hop, any transformations, and constraints.  This forms "
            "the basis for a proof-of-concept."
        ),
        "_tool_prefixes": [
            "decompile", "disasm", "get_basic_blocks",
            "get_callees", "get_callers", "xrefs_to", "xrefs_from",
            "get_bytes", "read_scalar",
        ],
    },
    {
        "name": "feedback",
        "description": (
            "Review findings quality and send weak or under-evidenced "
            "findings back to Gapfill for deeper analysis."
        ),
        "system_prompt": (
            "You are the Feedback agent.  Critically review each traced "
            "finding for evidence quality: is the data-flow path complete? "
            "Are constraints realistic?  Is the severity justified?  "
            "Findings that are weak or speculative should be flagged and "
            "sent back to Gapfill with specific questions to resolve."
        ),
        "_tool_prefixes": [
            "decompile", "disasm", "xrefs_to", "xrefs_from",
        ],
    },
    {
        "name": "report",
        "description": (
            "Synthesize the final vulnerability report with severity "
            "ratings, proof-of-concept sketches, and remediation advice."
        ),
        "system_prompt": (
            "You are the Report agent.  Compile all confirmed and traced "
            "findings into a professional vulnerability report.  For each "
            "finding include: title, severity (CVSS-like), affected "
            "function/address, data-flow summary, proof-of-concept sketch, "
            "and remediation recommendation.  End with an executive summary."
        ),
        "_tool_prefixes": [
            "decompile", "disasm",
        ],
    },
]

AUDIT_SUBAGENT_ORDER: tuple[str, ...] = tuple(s["name"] for s in AUDIT_SUBAGENTS)


def build_subagent_specs(
    mcp_tools: list[Any] | None = None,
) -> list[dict[str, Any]]:
    """Build deepagents-compatible SubAgent dicts from the spec above.

    Each subagent receives all IDA MCP tools (decompilation is just a
    tool, not a dedicated agent).  The ``_tool_prefixes`` field is used
    for optional tool filtering when the caller wants to restrict scope.
    """
    specs: list[dict[str, Any]] = []
    for agent_spec in AUDIT_SUBAGENTS:
        spec: dict[str, Any] = {
            "name": agent_spec["name"],
            "description": agent_spec["description"],
            "system_prompt": agent_spec["system_prompt"],
        }
        if mcp_tools:
            prefixes = agent_spec.get("_tool_prefixes", [])
            if prefixes:
                filtered = [
                    t for t in mcp_tools
                    if any(
                        getattr(t, "name", "").startswith(p) for p in prefixes
                    )
                ]
                spec["tools"] = filtered if filtered else mcp_tools
            else:
                spec["tools"] = mcp_tools
        specs.append(spec)
    return specs


# Alias expected by agent_factory.py
build_runtime_subagents = build_subagent_specs


# ---------------------------------------------------------------------------
# Orchestrator system prompt
# ---------------------------------------------------------------------------

ORCHESTRATOR_SYSTEM_PROMPT = """\
You are the Orchestrator of a vulnerability discovery harness.  You coordinate
a pipeline of specialized subagents to find, validate, and report security
vulnerabilities in a binary loaded in IDA Pro.

## Pipeline stages (execute in order)

1. **recon** — Gather binary metadata, segments, imports, exports, strings,
   entry points.  Always run first.
2. **hunt** — Search for dangerous patterns and vulnerability candidates.
3. **validate** — Confirm each candidate is real (reachable, not sanitized).
4. **gapfill** — Review coverage.  If gaps exist, send targeted requests back
   to hunt and validate.  Iterate up to {max_gapfill_iterations} times.
5. **dedupe** — Merge duplicates, cluster by root cause.
6. **trace** — Build data-flow paths from entry points to sinks.
7. **feedback** — Quality gate.  If findings are weak or under-evidenced, send
   them back to gapfill for deeper analysis.  Iterate up to
   {max_feedback_iterations} times.
8. **report** — Produce the final vulnerability report.

## Rules

- Always start with recon, always end with report.
- Use the `task` tool to delegate to each subagent by name.
- Pass relevant context from previous stages in the task description.
- For gapfill loops: after gapfill responds, call hunt/validate again with
  the specific gaps identified, then re-run gapfill.  Stop after
  {max_gapfill_iterations} iterations or when gapfill reports no gaps.
- For feedback loops: after feedback responds, if it flags weak findings,
  call gapfill with those findings, then re-run the pipeline from gapfill.
  Stop after {max_feedback_iterations} iterations or when feedback approves.
- Never skip stages.  If a stage has nothing to do, still call it and let it
  confirm "no action needed".
- Keep your own responses brief — the subagents do the heavy lifting.
"""

# Default iteration limits (can be overridden via config)
DEFAULT_MAX_GAPFILL_ITERATIONS = 3
DEFAULT_MAX_FEEDBACK_ITERATIONS = 2


def get_orchestrator_prompt(
    max_gapfill_iterations: int = DEFAULT_MAX_GAPFILL_ITERATIONS,
    max_feedback_iterations: int = DEFAULT_MAX_FEEDBACK_ITERATIONS,
) -> str:
    """Return the orchestrator system prompt with iteration limits filled in."""
    return ORCHESTRATOR_SYSTEM_PROMPT.format(
        max_gapfill_iterations=max_gapfill_iterations,
        max_feedback_iterations=max_feedback_iterations,
    )
