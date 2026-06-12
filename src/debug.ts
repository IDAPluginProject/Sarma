import { appendFileSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import * as paths from "@/paths";

let debugOverride: boolean | undefined;

export function debugEnabled(): boolean {
  if (debugOverride !== undefined) return debugOverride;
  const value = (process.env.SARMA_DEBUG ?? "").trim().toLowerCase();
  return value === "1" || value === "true" || value === "yes" || value === "on";
}

export function setDebugEnabled(enabled: boolean): void {
  debugOverride = enabled;
}

export function debugLogFile(): string {
  return process.env.SARMA_DEBUG_LOG || join(paths.localDir(), "debug.log");
}

export function formatError(error: unknown): string {
  if (error instanceof Error) return error.stack || error.message;
  return String(error);
}

export function debugLog(message: string, error?: unknown): void {
  if (!debugEnabled()) return;
  const text = `[${new Date().toISOString()}] ${message}${error === undefined ? "" : `\n${formatError(error)}`}\n`;
  try {
    console.error(text.trimEnd());
  } catch {
    // ignore console failures in alternate-screen mode
  }
  try {
    const target = debugLogFile();
    mkdirSync(dirname(target), { recursive: true });
    appendFileSync(target, text, "utf-8");
  } catch {
    // debug logging must never break the app
  }
}

export function installDebugHandlers(): void {
  if (!debugEnabled()) return;
  process.on("uncaughtException", (error) => {
    debugLog("uncaughtException", error);
  });
  process.on("unhandledRejection", (reason) => {
    debugLog("unhandledRejection", reason);
  });
}
