/** Terminal streaming renderer for one-shot and interactive CLI turns. */

import pc from "picocolors";
import { StreamEvent } from "@/engine/models";
import { StreamEventType } from "@/engine/enums";

function truncate(text: string, maxLen: number): string {
  const t = text.replace(/\n/g, " ").trim();
  if (t.length > maxLen) return t.slice(0, maxLen - 3) + "...";
  return t;
}

/** Accumulates streamed tokens and prints tool / subagent transitions inline. */
export class StreamPrinter {
  private toolStart = new Map<string, number>();
  private subagentStart = new Map<string, number>();
  private atLineStart = true;

  feedToken(token: string): void {
    if (!token) return;
    process.stdout.write(token);
    this.atLineStart = token.endsWith("\n");
  }

  feedReasoning(text: string): void {
    if (!text) return;
    process.stdout.write(pc.dim(text));
    this.atLineStart = text.endsWith("\n");
  }

  /** Print an out-of-band status line, ensuring it starts on a fresh line. */
  private statusLine(line: string): void {
    if (!this.atLineStart) {
      process.stdout.write("\n");
      this.atLineStart = true;
    }
    process.stdout.write(line + "\n");
  }

  startTool(name: string): void {
    this.toolStart.set(name, Date.now());
  }

  endTool(name: string): number {
    const start = this.toolStart.get(name);
    this.toolStart.delete(name);
    return start ? (Date.now() - start) / 1000 : 0;
  }

  startSubagent(name: string): void {
    this.subagentStart.set(name, Date.now());
  }

  endSubagent(name: string): number {
    const start = this.subagentStart.get(name);
    this.subagentStart.delete(name);
    return start ? (Date.now() - start) / 1000 : 0;
  }

  toolLine(name: string, args: string): void {
    this.statusLine(`  ${pc.blue(`▶ ${name}`)} ${pc.dim(args)}`);
  }

  toolResultLine(name: string, result: string, elapsed: number): void {
    const t = elapsed > 0.1 ? pc.dim(` (${elapsed.toFixed(1)}s)`) : "";
    this.statusLine(`  ${pc.green(`✓ ${name}`)} ${pc.dim(result)}${t}`);
  }

  toolErrorLine(name: string, error: string, elapsed: number): void {
    const t = elapsed > 0.1 ? pc.dim(` (${elapsed.toFixed(1)}s)`) : "";
    this.statusLine(`  ${pc.red(`✗ ${name}`)} ${pc.red(error)}${t}`);
  }

  subagentStartLine(name: string, description: string): void {
    this.statusLine(`\n${pc.blue(`╭─ ${name.toUpperCase()}`)} ${pc.dim(description)}`);
  }

  subagentCompleteLine(name: string, elapsed: number): void {
    const t = elapsed > 0.1 ? pc.dim(` (${elapsed.toFixed(1)}s)`) : "";
    this.statusLine(`${pc.green(`╰─ ${name} complete`)}${t}\n`);
  }

  stageStartLine(name: string, description: string): void {
    this.statusLine(`\n${pc.blue(`╭─ STAGE ${name.toUpperCase()}`)} ${pc.dim(description)}`);
  }

  stageCompleteLine(name: string, elapsed: number): void {
    const t = elapsed > 0.1 ? pc.dim(` (${elapsed.toFixed(1)}s)`) : "";
    this.statusLine(`${pc.green(`╰─ stage ${name} complete`)}${t}\n`);
  }

  flush(): void {
    if (!this.atLineStart) {
      process.stdout.write("\n");
      this.atLineStart = true;
    }
  }
}

export function printError(message: string): void {
  process.stderr.write(pc.red(`Error: ${message}`) + "\n");
}

export function printInfo(message: string): void {
  process.stdout.write(message + "\n");
}

/** Route a StreamEvent to the appropriate renderer output. */
export function handleEvent(event: StreamEvent, printer: StreamPrinter): void {
  const etype = event.type;
  const payload = event.payload;

  if (etype === StreamEventType.TOKEN) {
    const reasoning = (payload.reasoning_content as string) || "";
    if (reasoning) printer.feedReasoning(reasoning);
    const token = (payload.content as string) || "";
    if (token) printer.feedToken(token);
  } else if (etype === StreamEventType.RUN_STARTED) {
    printer.flush();
    process.stdout.write(pc.dim("─".repeat(40)) + "\n");
  } else if (etype === StreamEventType.TOOL_START) {
    const name = (payload.tool_name as string) || "?";
    printer.startTool(name);
    printer.toolLine(name, truncate((payload.args_json as string) || "", 100));
  } else if (etype === StreamEventType.TOOL_RESULT) {
    const name = (payload.tool_name as string) || "?";
    printer.toolResultLine(name, truncate((payload.result_summary as string) || "", 160), printer.endTool(name));
  } else if (etype === StreamEventType.TOOL_ERROR) {
    const name = (payload.tool_name as string) || "?";
    printer.toolErrorLine(name, truncate((payload.error_text as string) || "", 160), printer.endTool(name));
  } else if (etype === StreamEventType.STAGE_START) {
    const name = (payload.stage as string) || "";
    if (name) {
      printer.startSubagent(`stage:${name}`);
      printer.stageStartLine(name, (payload.description as string) || "");
    }
  } else if (etype === StreamEventType.STAGE_COMPLETE) {
    const name = (payload.stage as string) || "";
    if (name) printer.stageCompleteLine(name, printer.endSubagent(`stage:${name}`));
  } else if (etype === StreamEventType.SUBAGENT_START) {
    const name = (payload.subagent as string) || "";
    if (name) {
      printer.startSubagent(name);
      printer.subagentStartLine(name, (payload.description as string) || "");
    }
  } else if (etype === StreamEventType.SUBAGENT_COMPLETE) {
    const name = (payload.subagent as string) || "";
    if (name) printer.subagentCompleteLine(name, printer.endSubagent(name));
  } else if (etype === StreamEventType.RUN_FAILED) {
    printer.flush();
    printError(`Agent run failed: ${(payload.error as string) || "Unknown error"}`);
  }
}
