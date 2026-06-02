"""Audit-Slim Harness — minimal 3-stage subagent pipeline.

A lightweight alternative to the full 8-stage audit, for quick passes:

1. Recon  — Does the audit: survey the binary AND hunt for vulnerabilities,
            producing a candidate findings list in one pass.
2. Verify — Ensures the findings are real and reliable: confirm reachability,
            rule out dead/sanitized paths, discard false positives.
3. Report — Validates the verified results once more and produces clear,
            actionable user-facing feedback.

Linear flow: recon -> verify -> report (no loops). All agents share the
IDA MCP tool set.
"""

from __future__ import annotations

from typing import Any


AUDIT_SLIM_SUBAGENTS: list[dict[str, Any]] = [
    {
        "name": "recon",
        "description": (
            "Audit the binary in one pass: survey its structure and hunt for "
            "vulnerabilities, producing a candidate findings list."
        ),
        "system_prompt": (
            "You are the Recon agent of a lightweight audit.  You perform the "
            "whole discovery pass yourself: first survey the binary "
            "(metadata, segments, imports/exports, functions, strings, entry "
            "points), then hunt for vulnerabilities — command injection, "
            "memory unsafety, auth bypass, path traversal, and similar "
            "classes.  Use IDA MCP tools (decompile, disasm, xrefs, byte "
            "search) as needed.  Output a structured candidate findings list: "
            "for each, record address, function, vulnerability class, and a "
            "brief rationale with supporting evidence."
        ),
        "_tool_prefixes": [
            "get_metadata", "list_segments", "list_functions",
            "list_imports", "list_exports", "list_strings",
            "get_entry_points", "get_bytes", "decompile", "disasm",
            "find_bytes", "get_callees", "get_callers",
            "xrefs_to", "xrefs_from", "linear_disasm",
        ],
    },
    {
        "name": "verify",
        "description": (
            "Ensure the audit results are real and reliable: confirm each "
            "candidate is reachable and exploitable, discard false positives."
        ),
        "system_prompt": (
            "You are the Verify agent.  For each candidate the Recon agent "
            "reported, establish whether it is a genuine, reliable finding. "
            "Confirm reachability from an external entry point, rule out dead "
            "or unreachable code, and check the dangerous sink is not already "
            "sanitized or guarded.  Re-examine the evidence with IDA MCP "
            "tools rather than trusting Recon's claims.  Output the findings "
            "marked confirmed or rejected, each with the concrete evidence "
            "that supports the verdict."
        ),
        "_tool_prefixes": [
            "decompile", "disasm", "get_basic_blocks",
            "get_callees", "get_callers", "xrefs_to", "xrefs_from",
            "get_bytes", "read_scalar",
        ],
    },
    {
        "name": "report",
        "description": (
            "Validate the verified results and produce clear, actionable "
            "user-facing feedback."
        ),
        "system_prompt": (
            "You are the Report agent.  Take the confirmed findings from "
            "Verify and do a final validation pass: sanity-check each verdict "
            "and drop anything unsupported.  Then synthesize clear, "
            "actionable feedback for the user.  For each finding include: "
            "title, severity, affected function/address, a concise "
            "explanation of the issue and its impact, and a remediation "
            "recommendation.  If no findings survived, say so plainly and "
            "summarize what was examined.  End with a short executive summary."
        ),
        "_tool_prefixes": [
            "decompile", "disasm",
        ],
    },
]

AUDIT_SLIM_SUBAGENT_ORDER: tuple[str, ...] = tuple(
    s["name"] for s in AUDIT_SLIM_SUBAGENTS
)

