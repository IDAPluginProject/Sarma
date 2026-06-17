/** Persistent terminal tools for long-lived interactive CLI processes. */

import { spawn } from "node:child_process";
import type { ChildProcessWithoutNullStreams } from "node:child_process";
import { appendFileSync, mkdirSync } from "node:fs";
import * as path from "node:path";
import { createMiddleware } from "langchain";
import { tool } from "@langchain/core/tools";
import { z } from "zod";
import type { StructuredToolInterface } from "@langchain/core/tools";
import type { AnyAgentMiddleware } from "langchain";
import * as paths from "@/paths";

const DEFAULT_WAIT_MS = 200;
const DEFAULT_MAX_OUTPUT_BYTES = 12000;
const MAX_OUTPUT_BYTES = 128000;
const MAX_HISTORY_BYTES = 1024 * 1024;
const MAX_SESSIONS = 8;
const allManagers = new Set<PersistentTerminalManager>();

type ExitState = { code: number | null; signal: NodeJS.Signals | null } | null;

interface TerminalSession {
  id: string;
  command: string;
  args: string[];
  cwd: string;
  startedAt: Date;
  proc: ChildProcessWithoutNullStreams;
  chunks: Buffer[];
  historyBytes: number;
  readOffset: number;
  exitState: ExitState;
  logFile: string | null;
}

export interface PersistentTerminalManagerOptions {
  conversationId?: string;
  logRoot?: string;
}

export interface TerminalStartArgs {
  terminalId?: string;
  command: string;
  args?: string[];
  cwd?: string;
  envJson?: string;
  useShell?: boolean;
  waitMs?: number;
  maxOutputBytes?: number;
}

export interface TerminalWriteArgs {
  terminalId: string;
  input: string;
  appendNewline?: boolean;
  waitMs?: number;
  maxOutputBytes?: number;
}

export interface TerminalReadArgs {
  terminalId: string;
  waitMs?: number;
  maxOutputBytes?: number;
}

export interface TerminalStopArgs {
  terminalId: string;
  signal?: NodeJS.Signals;
  waitMs?: number;
  maxOutputBytes?: number;
}

export class PersistentTerminalManager {
  private readonly sessions = new Map<string, TerminalSession>();
  private readonly conversationId: string;
  private readonly logRoot: string | null;

  constructor(
    private readonly workspaceRoot = process.cwd(),
    options: PersistentTerminalManagerOptions = {},
  ) {
    this.conversationId = sanitizePathPart(options.conversationId ?? "");
    this.logRoot = options.logRoot ?? (this.conversationId ? path.join(paths.localDir(), this.conversationId, "terminals") : null);
    allManagers.add(this);
  }

  async start(args: TerminalStartArgs): Promise<string> {
    const command = args.command.trim();
    if (!command) return "terminal_start requires a command.";
    if (this.sessions.size >= MAX_SESSIONS) return `terminal_start reached the session limit (${MAX_SESSIONS}).`;

    const id = this.normalizeId(args.terminalId || this.nextId(command));
    if (this.sessions.has(id)) return `terminal_start terminal_id already exists: ${id}`;

    let cwd: string;
    let env: NodeJS.ProcessEnv;
    try {
      cwd = this.resolveCwd(args.cwd || ".");
      env = this.parseEnv(args.envJson || "");
    } catch (exc) {
      return `terminal_start invalid input: ${exc instanceof Error ? exc.message : String(exc)}`;
    }

    const proc = spawn(command, args.args ?? [], {
      cwd,
      env,
      shell: args.useShell ?? false,
      windowsHide: true,
      stdio: "pipe",
    });

    const session: TerminalSession = {
      id,
      command,
      args: args.args ?? [],
      cwd,
      startedAt: new Date(),
      proc,
      chunks: [],
      historyBytes: 0,
      readOffset: 0,
      exitState: null,
      logFile: this.logFileFor(id),
    };
    this.sessions.set(id, session);
    this.writeLog(
      session,
      [
        `# Sarma terminal transcript`,
        `session_id=${this.conversationId || "(none)"}`,
        `terminal_id=${id}`,
        `started_at=${session.startedAt.toISOString()}`,
        `cwd=${cwd}`,
        `command=${JSON.stringify([command, ...(args.args ?? [])])}`,
        "",
      ].join("\n"),
    );

    proc.stdout.on("data", (chunk: Buffer) => this.append(session, chunk));
    proc.stderr.on("data", (chunk: Buffer) => this.append(session, chunk));
    proc.on("error", (err) => {
      this.append(session, Buffer.from(`\n[process error: ${err.message}]\n`, "utf-8"));
    });
    proc.on("exit", (code, signal) => {
      session.exitState = { code, signal };
      this.append(session, Buffer.from(`\n[process exited code=${code ?? "null"} signal=${signal ?? "null"}]\n`, "utf-8"));
    });

    await delay(clampWait(args.waitMs));
    return this.formatRead(session, clampOutputBytes(args.maxOutputBytes), `terminal_start ${id}`);
  }

  async write(args: TerminalWriteArgs): Promise<string> {
    const session = this.sessions.get(args.terminalId);
    if (!session) return `terminal_write unknown terminal_id: ${args.terminalId}`;
    if (session.exitState) return `terminal_write ${session.id} is not running.\n${this.formatRead(session, clampOutputBytes(args.maxOutputBytes), "unread output")}`;

    const data = args.input + (args.appendNewline ?? true ? "\n" : "");
    try {
      this.writeLog(session, `\n[stdin ${new Date().toISOString()}]\n${data}`);
      session.proc.stdin.write(data);
    } catch (exc) {
      return `terminal_write failed: ${exc instanceof Error ? exc.message : String(exc)}`;
    }

    await delay(clampWait(args.waitMs));
    return this.formatRead(session, clampOutputBytes(args.maxOutputBytes), `terminal_write ${session.id}`);
  }

  async read(args: TerminalReadArgs): Promise<string> {
    const session = this.sessions.get(args.terminalId);
    if (!session) return `terminal_read unknown terminal_id: ${args.terminalId}`;
    await delay(clampWait(args.waitMs));
    return this.formatRead(session, clampOutputBytes(args.maxOutputBytes), `terminal_read ${session.id}`);
  }

  async stop(args: TerminalStopArgs): Promise<string> {
    const session = this.sessions.get(args.terminalId);
    if (!session) return `terminal_stop unknown terminal_id: ${args.terminalId}`;

    if (!session.exitState) {
      try {
        session.proc.kill(args.signal ?? "SIGTERM");
      } catch (exc) {
        return `terminal_stop failed: ${exc instanceof Error ? exc.message : String(exc)}`;
      }
      await delay(clampWait(args.waitMs));
      if (!session.exitState) {
        try {
          session.proc.kill("SIGKILL");
        } catch {
          // Process may have exited between the checks.
        }
      }
    }

    const output = this.formatRead(session, clampOutputBytes(args.maxOutputBytes), `terminal_stop ${session.id}`);
    this.sessions.delete(session.id);
    return output;
  }

  list(): string {
    if (this.sessions.size === 0) return "terminal_list: no active terminals.";
    const lines = ["terminal_list:"];
    for (const session of this.sessions.values()) {
      const state = session.exitState
        ? `exited code=${session.exitState.code ?? "null"} signal=${session.exitState.signal ?? "null"}`
        : "running";
      lines.push(
        `- ${session.id}: ${state}, command=${JSON.stringify([session.command, ...session.args].join(" "))}, cwd=${session.cwd}, started=${session.startedAt.toISOString()}`,
      );
    }
    return lines.join("\n");
  }

  closeAll(): void {
    for (const session of this.sessions.values()) {
      if (!session.exitState) {
        try {
          session.proc.kill("SIGTERM");
        } catch {
          // Best-effort cleanup on process shutdown.
        }
      }
    }
    this.sessions.clear();
    allManagers.delete(this);
  }

  private append(session: TerminalSession, chunk: Buffer): void {
    this.writeLog(session, chunk);
    session.chunks.push(chunk);
    session.historyBytes += chunk.length;
    while (session.historyBytes > MAX_HISTORY_BYTES && session.chunks.length > 1) {
      const dropped = session.chunks.shift()!;
      session.historyBytes -= dropped.length;
      session.readOffset = Math.max(0, session.readOffset - dropped.length);
    }
  }

  private formatRead(session: TerminalSession, maxBytes: number, label: string): string {
    const history = Buffer.concat(session.chunks, session.historyBytes);
    const start = Math.min(session.readOffset, history.length);
    const unread = history.subarray(start);
    session.readOffset = history.length;
    const shown = unread.length > maxBytes ? unread.subarray(unread.length - maxBytes) : unread;
    const truncated = unread.length > shown.length ? `\n[truncated ${unread.length - shown.length} byte(s)]\n` : "";
    const state = session.exitState
      ? `exited code=${session.exitState.code ?? "null"} signal=${session.exitState.signal ?? "null"}`
      : "running";
    const output = shown.toString("utf-8");
    const logLine = session.logFile ? `\nlog_file=${session.logFile}` : "";
    return `${label}: ${state}\nterminal_id=${session.id}${logLine}\nunread_bytes=${unread.length}\noutput:\n${truncated}${output}`;
  }

  private logFileFor(terminalId: string): string | null {
    if (!this.logRoot) return null;
    return path.join(this.logRoot, `${sanitizePathPart(terminalId)}.log`);
  }

  private writeLog(session: TerminalSession, data: string | Buffer): void {
    if (!session.logFile) return;
    mkdirSync(path.dirname(session.logFile), { recursive: true });
    appendFileSync(session.logFile, data);
  }

  private resolveCwd(cwd: string): string {
    const root = path.resolve(this.workspaceRoot);
    const resolved = path.resolve(root, cwd);
    const relative = path.relative(root, resolved);
    if (relative && (relative.startsWith("..") || path.isAbsolute(relative))) {
      throw new Error("cwd must stay inside the workspace.");
    }
    return resolved;
  }

  private parseEnv(envJson: string): NodeJS.ProcessEnv {
    const env = { ...process.env };
    const text = envJson.trim();
    if (!text) return env;
    const parsed = JSON.parse(text);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      throw new Error("env_json must be a JSON object.");
    }
    for (const [key, value] of Object.entries(parsed)) {
      env[key] = String(value);
    }
    return env;
  }

  private normalizeId(id: string): string {
    const normalized = id.trim().replace(/[^a-zA-Z0-9_.-]/g, "_").slice(0, 64);
    if (!normalized) throw new Error("terminal_id is empty after normalization.");
    return normalized;
  }

  private nextId(command: string): string {
    const base = command.split(/[\\/\s]+/).filter(Boolean).pop() || "terminal";
    for (let i = 1; i <= MAX_SESSIONS + 1; i += 1) {
      const id = this.normalizeId(`${base}-${i}`);
      if (!this.sessions.has(id)) return id;
    }
    return this.normalizeId(`terminal-${Date.now()}`);
  }
}

const defaultManager = new PersistentTerminalManager();

process.once("exit", () => {
  for (const manager of [...allManagers]) manager.closeAll();
});

export function buildPersistentTerminalTools(
  manager: PersistentTerminalManager = defaultManager,
): StructuredToolInterface[] {
  const startTool = tool(
    async (args: {
      terminal_id?: string;
      command: string;
      args?: string[];
      cwd?: string;
      env_json?: string;
      use_shell?: boolean;
      wait_ms?: number;
      max_output_bytes?: number;
    }) =>
      manager.start({
        terminalId: args.terminal_id,
        command: args.command,
        args: args.args ?? [],
        cwd: args.cwd ?? ".",
        envJson: args.env_json ?? "",
        useShell: args.use_shell ?? false,
        waitMs: args.wait_ms,
        maxOutputBytes: args.max_output_bytes,
      }),
    {
      name: "terminal_start",
      description:
        "Start a persistent interactive terminal process in the workspace. Use for debuggers and REPLs that need state across turns, such as gdb/lldb/python.\n\n" +
        "Returns a terminal_id and initial unread output. Use terminal_write and terminal_read to interact, and terminal_stop when done. This is pipe-based, not a full TTY.",
      schema: z.object({
        terminal_id: z.string().default(""),
        command: z.string(),
        args: z.array(z.string()).default([]),
        cwd: z.string().default("."),
        env_json: z.string().default(""),
        use_shell: z.boolean().default(false),
        wait_ms: z.number().default(DEFAULT_WAIT_MS),
        max_output_bytes: z.number().default(DEFAULT_MAX_OUTPUT_BYTES),
      }),
    },
  );

  const writeTool = tool(
    async (args: {
      terminal_id: string;
      input: string;
      append_newline?: boolean;
      wait_ms?: number;
      max_output_bytes?: number;
    }) =>
      manager.write({
        terminalId: args.terminal_id,
        input: args.input,
        appendNewline: args.append_newline ?? true,
        waitMs: args.wait_ms,
        maxOutputBytes: args.max_output_bytes,
      }),
    {
      name: "terminal_write",
      description:
        "Write text to a persistent terminal's stdin, optionally appending a newline, then return newly unread output.",
      schema: z.object({
        terminal_id: z.string(),
        input: z.string(),
        append_newline: z.boolean().default(true),
        wait_ms: z.number().default(DEFAULT_WAIT_MS),
        max_output_bytes: z.number().default(DEFAULT_MAX_OUTPUT_BYTES),
      }),
    },
  );

  const readTool = tool(
    async (args: { terminal_id: string; wait_ms?: number; max_output_bytes?: number }) =>
      manager.read({
        terminalId: args.terminal_id,
        waitMs: args.wait_ms,
        maxOutputBytes: args.max_output_bytes,
      }),
    {
      name: "terminal_read",
      description:
        "Read newly unread output from a persistent terminal. Use after terminal_start or terminal_write when the process may still be running.",
      schema: z.object({
        terminal_id: z.string(),
        wait_ms: z.number().default(DEFAULT_WAIT_MS),
        max_output_bytes: z.number().default(DEFAULT_MAX_OUTPUT_BYTES),
      }),
    },
  );

  const stopTool = tool(
    async (args: {
      terminal_id: string;
      signal?: NodeJS.Signals;
      wait_ms?: number;
      max_output_bytes?: number;
    }) =>
      manager.stop({
        terminalId: args.terminal_id,
        signal: args.signal,
        waitMs: args.wait_ms,
        maxOutputBytes: args.max_output_bytes,
      }),
    {
      name: "terminal_stop",
      description: "Stop a persistent terminal process and remove it from the active terminal list.",
      schema: z.object({
        terminal_id: z.string(),
        signal: z.string().default("SIGTERM"),
        wait_ms: z.number().default(DEFAULT_WAIT_MS),
        max_output_bytes: z.number().default(DEFAULT_MAX_OUTPUT_BYTES),
      }),
    },
  );

  const listTool = tool(async () => manager.list(), {
    name: "terminal_list",
    description: "List active persistent terminal processes.",
    schema: z.object({}),
  });

  return [startTool, writeTool, readTool, stopTool, listTool] as unknown as StructuredToolInterface[];
}

export function buildPersistentTerminalMiddleware(
  optionsOrManager: PersistentTerminalManager | PersistentTerminalManagerOptions = defaultManager,
): AnyAgentMiddleware {
  const manager =
    optionsOrManager instanceof PersistentTerminalManager
      ? optionsOrManager
      : new PersistentTerminalManager(process.cwd(), optionsOrManager);
  return createMiddleware({
    name: "PersistentTerminalMiddleware",
    tools: buildPersistentTerminalTools(manager),
  }) as unknown as AnyAgentMiddleware;
}

function clampWait(value: number | undefined): number {
  return Math.max(0, Math.min(Math.trunc(value ?? DEFAULT_WAIT_MS), 10000));
}

function clampOutputBytes(value: number | undefined): number {
  return Math.max(1, Math.min(Math.trunc(value ?? DEFAULT_MAX_OUTPUT_BYTES), MAX_OUTPUT_BYTES));
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function sanitizePathPart(value: string): string {
  return value.trim().replace(/[^a-zA-Z0-9_.-]/g, "_").slice(0, 80);
}
