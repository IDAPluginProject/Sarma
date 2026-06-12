/**
 * Transcript model — the structured, reactive-friendly representation of a
 * conversation turn that the TUI renders. The CLI's StreamPrinter renders the
 * same StreamEvents to a scrolling log; this builds an in-memory tree instead.
 */

export type ChatRole = "user" | "assistant";

export interface ToolEntry {
  id: string;
  toolCallId: string;
  name: string;
  subagent?: string;
  args: string;
  status: "running" | "ok" | "error";
  summary: string;
  result: string;
  error: string;
  elapsed: number; // seconds
}

export interface SubagentEntry {
  id: string;
  name: string;
  description: string;
  status: "running" | "complete" | "error";
  elapsed: number;
  toolCallId: string;
  output: string;
  reasoning: string;
  result: string;
  error: string;
}

export interface StageEntry {
  id: string;
  name: string;
  nodeKind: "stage" | "router";
  description: string;
  status: "running" | "complete" | "error";
  elapsed: number;
  error: string;
}

export type TranscriptItem =
  | { kind: "message"; id: string; role: ChatRole; content: string; reasoning: string }
  | { kind: "tool"; id: string; tool: ToolEntry }
  | { kind: "subagent"; id: string; subagent: SubagentEntry }
  | { kind: "stage"; id: string; stage: StageEntry }
  | { kind: "note"; id: string; text: string }
  | { kind: "error"; id: string; text: string }
  | { kind: "divider"; id: string };

let counter = 0;
export function nextId(prefix = "i"): string {
  counter += 1;
  return `${prefix}${counter}`;
}
