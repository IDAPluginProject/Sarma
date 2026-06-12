/**
 * Cross-platform path resolution for Sarma.
 *
 * Two scopes:
 * - **global**  `~/.sarma/`  — base config + skills, shared across projects.
 *                              Override with `SARMA_HOME` (which then *is* the
 *                              sarma dir, JAVA_HOME-style).
 * - **local**   `./.sarma/`  — per-workspace overrides + session database.
 */

import { homedir } from "node:os";
import { join } from "node:path";

const DIR_NAME = ".sarma";
export const MODELS_NAME = "models.toml";
export const AGENTS_NAME = "agents.toml";
export const MCP_NAME = "mcp.toml";
export const RAG_NAME = "rag.toml";
export const INPUT_HISTORY_NAME = ".history";

/** Global config directory: `$SARMA_HOME` or `~/.sarma`. */
export function globalDir(): string {
  const override = process.env.SARMA_HOME;
  if (override) return override;
  return join(homedir(), DIR_NAME);
}

/** Per-workspace directory: `./.sarma` in the current working directory. */
export function localDir(): string {
  return join(process.cwd(), DIR_NAME);
}

export function globalModelsFile(): string {
  return join(globalDir(), MODELS_NAME);
}
export function localModelsFile(): string {
  return join(localDir(), MODELS_NAME);
}
export function globalConfigFile(): string {
  return globalModelsFile();
}
export function localConfigFile(): string {
  return localModelsFile();
}
export function globalAgentsFile(): string {
  return join(globalDir(), AGENTS_NAME);
}
export function localAgentsFile(): string {
  return join(localDir(), AGENTS_NAME);
}
export function globalMcpFile(): string {
  return join(globalDir(), MCP_NAME);
}
export function localMcpFile(): string {
  return join(localDir(), MCP_NAME);
}
export function globalRagFile(): string {
  return join(globalDir(), RAG_NAME);
}
export function localRagFile(): string {
  return join(localDir(), RAG_NAME);
}
export function ragDir(): string {
  return join(localDir(), "rag");
}
export function globalRagDir(): string {
  return join(globalDir(), "rag");
}
export function ragDocsDir(): string {
  return join(ragDir(), "docs");
}
export function ragChromaDir(): string {
  return join(ragDir(), "chroma");
}
export function ragModelsDir(): string {
  return join(globalRagDir(), "models");
}
/** Session database lives per-workspace. */
export function dbPath(): string {
  return join(localDir(), "db.sqlite");
}
/** Line-based user input history for the full-screen TUI. */
export function inputHistoryFile(): string {
  return join(localDir(), INPUT_HISTORY_NAME);
}
export function globalSkillsDir(): string {
  return join(globalDir(), "skills");
}
export function localSkillsDir(): string {
  return join(localDir(), "skills");
}
