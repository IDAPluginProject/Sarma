---
name: vuln-audit-workflow
description: 8-stage vulnerability discovery harness for IDA binary audit. Governs the orchestrator and all subagents. Load this skill when the user asks to "audit", "find vulnerabilities", "security review a binary", or "run the full pipeline". Defines execution order, inter-stage contracts, quality gates, and iteration rules.
---

# Vulnerability Audit Workflow

## Overview

You are operating inside Sarma's 8-stage vulnerability discovery harness.
Each stage is a specialized subagent with a defined input/output contract.
The orchestrator dispatches stages in order and enforces iteration limits.

## Pipeline Stages

```
┌──────────────┐
│ Orchestrator │
└──────┬───────┘
       │
       ▼
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│   1. Recon   │────▶│   2. Hunt    │────▶│  3. Validate │
└──────────────┘     └──────┬───────┘     └──────┬───────┘
                            │                     │
                            ▼                     ▼
                     ┌──────────────┐      (loop back)
                     │  4. Gapfill  │◀─────────────┘
                     └──────┬───────┘
                            │
                            ▼
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  5. Dedupe   │────▶│   6. Trace   │────▶│ 7. Feedback  │
└──────────────┘     └──────────────┘     └──────┬───────┘
                                                  │
                                           (weak findings)
                                                  │
                                                  ▼
                                           ┌──────────────┐
                                           │  8. Report   │
                                           └──────────────┘
```

## Execution Rules

### General Rules

1. Always start with Recon. Always end with Report.
2. Never skip a stage. If a stage has nothing to do, it must confirm "no action needed".
3. Pass structured context from each stage to the next via the task description.
4. Keep orchestrator messages brief. Subagents do the heavy lifting.
5. Each subagent must output structured data, not prose narratives.

### Iteration Rules

- **Gapfill loop**: After Gapfill identifies gaps, re-dispatch Hunt and Validate for the specific gaps. Maximum 3 iterations. Stop early if Gapfill reports "no gaps remaining".
- **Feedback loop**: After Feedback flags weak findings, send them back to Gapfill. Maximum 2 iterations. Stop early if Feedback approves all findings.
- Never enter an infinite loop. Count iterations explicitly.

### Tool Usage Rules

- Use IDA MCP tools (decompile, disasm, xrefs, strings, bytes) as primary information sources.
- There is no "decompile agent" — decompilation is a tool available to all stages.
- Prefer `decompile` for understanding logic, `disasm` for precise instruction-level detail.
- Use `xrefs_to` / `xrefs_from` / `get_callers` / `get_callees` for reachability analysis.
- Use `find_bytes` for pattern matching (magic numbers, opcodes).
- Limit `list_functions` / `list_strings` to the first call; cache results across stages.

### Quality Gates

- A finding is CONFIRMED only when:
  1. The sink is real (decompiled code shows dangerous operation)
  2. The path from entry to sink is reachable (no dead code / guards)
  3. User-controlled data reaches the sink without sanitization
- A finding without all three is SPECULATIVE and must go back to Gapfill.

---

## Stage Contracts

### Stage 1: Recon

**Input**: Target binary loaded in IDA (port provided or auto-selected)

**Actions**:
- `get_metadata` — architecture, bits, endianness
- `list_segments` — memory layout and permissions
- `list_functions` — full function list with sizes
- `list_imports` — external dependencies (libc, custom libs)
- `list_exports` — public interface
- `list_strings` — interesting strings (paths, commands, formats, URLs)
- `get_entry_points` — program entries

**Output format**:
```
## Recon Summary
- Architecture: {arch} {bits}-bit {endian}
- Segments: {count} ({list with permissions})
- Functions: {total_count} ({named_count} named)
- Imports: {dangerous_imports_list}
- Exports: {public_api_list}
- Interesting strings: {categorized_list}
- Entry points: {list}
- Attack surface estimate: {high/medium/low} — {reason}
```

### Stage 2: Hunt

**Input**: Recon summary

**Actions**:
- Search for dangerous sinks: `system`, `popen`, `execve`, `sprintf`, `strcpy`, `memcpy` without bounds, `eval`, format strings
- Trace imports to call sites via `xrefs_to`
- Decompile functions around sinks
- Search for authentication patterns and bypass opportunities
- Check for hardcoded credentials in strings

**Output format** (per candidate):
```
## Candidate #{n}
- Address: 0x{addr}
- Function: {name}
- Pattern class: {command_injection | buffer_overflow | format_string | auth_bypass | path_traversal | info_leak}
- Sink: {function_called}
- Rationale: {1-2 sentences}
- Confidence: {high | medium | low}
```

### Stage 3: Validate

**Input**: Hunt candidates list

**Actions** (per candidate):
- Decompile the full function
- Check reachability from entry points (callers chain)
- Verify no sanitization guards the path
- Confirm the code is not dead (conditionals, feature flags)

**Output format** (per candidate):
```
## Validation #{n} — {CONFIRMED | REJECTED | NEEDS_MORE}
- Original candidate: #{ref}
- Reachability: {entry → ... → sink} or UNREACHABLE
- Guards: {none | list_of_sanitization}
- Dead code: {no | yes — reason}
- Verdict: {CONFIRMED | REJECTED | NEEDS_MORE}
- Reason: {1 sentence}
```

### Stage 4: Gapfill

**Input**: Validated findings + Recon summary

**Actions**:
- Compare covered functions vs total attack surface
- Identify unchecked dangerous imports
- Look for unexplored code regions with high complexity
- Check if all entry points have been traced

**Output format**:
```
## Coverage Analysis
- Functions analyzed: {n}/{total}
- Dangerous imports with unchecked xrefs: {list}
- Unexplored high-value regions: {list with addresses}
- Specific requests for Hunt: {targeted_queries}
- Specific requests for Validate: {recheck_items}
- Gaps remaining: {yes/no}
```

### Stage 5: Dedupe

**Input**: All CONFIRMED findings

**Actions**:
- Group findings by root cause (same vulnerable pattern, same wrapper)
- Identify duplicate call sites (same bug, different callers)
- Assign cluster IDs

**Output format**:
```
## Deduplicated Findings
### Cluster {id}: {root_cause_description}
- Primary finding: #{ref} at 0x{addr}
- Duplicates: [#{refs}]
- Affected call sites: {count}
- Root cause: {1 sentence}
```

### Stage 6: Trace

**Input**: Deduplicated findings

**Actions** (per cluster):
- Trace data flow from nearest external input to the sink
- Document each hop (function → function) with transforms
- Identify constraints on the input
- Assess exploitability

**Output format** (per finding):
```
## Trace #{n}
- Entry: {source_function} (0x{addr})
- Path: {func1} → {func2} → ... → {sink}
- Input type: {network | file | IPC | argv}
- Transforms: {list of operations on data}
- Constraints: {length limits, character filters, etc.}
- Exploitability: {trivial | moderate | complex | theoretical}
```

### Stage 7: Feedback

**Input**: Traced findings

**Criteria for PASS**:
- Complete data-flow path (no gaps)
- Realistic constraints (attacker can satisfy them)
- Justified severity
- Clear root cause

**Criteria for FAIL (send back)**:
- Incomplete trace (missing hops)
- Unrealistic constraints without explanation
- Severity not justified by evidence
- Speculative without decompilation proof

**Output format**:
```
## Feedback
### APPROVED: {list of finding refs}
### NEEDS REWORK: 
- Finding #{ref}: {specific_question_to_resolve}
- Finding #{ref}: {what_evidence_is_missing}
### Overall quality: {PASS | ITERATE}
```

### Stage 8: Report

**Input**: All approved findings with traces

**Output format**:
```
# Vulnerability Report: {binary_name}

## Executive Summary
- Target: {binary} ({arch}, {size})
- Findings: {count} confirmed vulnerabilities
- Critical: {n} | High: {n} | Medium: {n} | Low: {n}
- Most severe: {title} — {one_line}

## Finding #{n}: {title}
- Severity: {Critical | High | Medium | Low}
- CVSS estimate: {score}
- Location: {function} at 0x{addr}
- Type: {CWE-id} {name}
- Data flow: {entry} → ... → {sink}
- Impact: {what can attacker achieve}
- Proof of Concept:
  ```
  {minimal PoC sketch or trigger conditions}
  ```
- Remediation: {specific fix recommendation}

## Appendix
- Functions analyzed: {n}/{total}
- Coverage: {percentage}%
- Tools used: {list}
- Iteration count: Gapfill×{n}, Feedback×{n}
```

---

## Orchestrator Behavior

The orchestrator must:
1. Track which stage is active and report it
2. Pass the FULL output of each stage to the next (do not summarize between stages)
3. Count gapfill and feedback iterations
4. Break loops when limits are reached, even if gaps remain
5. Never call Report until Feedback returns PASS or iteration limit is hit
6. On error in any stage, log the error and continue with available data

The orchestrator must NOT:
1. Perform analysis itself (delegate to subagents)
2. Skip stages to "save time"
3. Invent findings not produced by Hunt/Validate
4. Override Feedback quality judgments
