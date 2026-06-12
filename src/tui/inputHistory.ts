import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname } from "node:path";

import { inputHistoryFile } from "@/paths";

const DEFAULT_LIMIT = 1000;

export interface InputHistoryOptions {
  file?: string;
  limit?: number;
}

function pathFrom(options: InputHistoryOptions = {}): string {
  return options.file ?? inputHistoryFile();
}

function limitFrom(options: InputHistoryOptions = {}): number {
  return Math.max(1, options.limit ?? DEFAULT_LIMIT);
}

function normalizeLine(text: string): string {
  return text.replace(/\r?\n/g, " ").trim();
}

export function loadInputHistory(options: InputHistoryOptions = {}): string[] {
  const file = pathFrom(options);
  try {
    const lines = readFileSync(file, "utf8")
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter(Boolean);
    return lines.slice(-limitFrom(options));
  } catch (err) {
    if ((err as NodeJS.ErrnoException).code === "ENOENT") return [];
    throw err;
  }
}

export function appendInputHistory(text: string, options: InputHistoryOptions = {}): string[] {
  const entry = normalizeLine(text);
  if (!entry) return loadInputHistory(options);

  const limit = limitFrom(options);
  const file = pathFrom(options);
  const entries = loadInputHistory({ ...options, limit });
  if (entries.at(-1) !== entry) entries.push(entry);
  const trimmed = entries.slice(-limit);

  mkdirSync(dirname(file), { recursive: true });
  writeFileSync(file, `${trimmed.join("\n")}${trimmed.length ? "\n" : ""}`, "utf8");
  return trimmed;
}
