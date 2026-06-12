/**
 * Runtime middleware construction for LangChain agents.
 *
 * Middleware can expose powerful tools to the model. Sarma gives agents direct
 * file and shell access rooted at the current workspace.
 *
 * JS mapping notes (vs the Python build):
 * - Python wired separate `FilesystemMiddleware`, `FilesystemFileSearchMiddleware`
 *   and `ShellToolMiddleware`. In deepagents-js a single
 *   `createFilesystemMiddleware` over an execution-capable backend
 *   (`LocalShellBackend`) exposes `ls/read_file/write_file/edit_file/glob/grep`
 *   AND an `execute` shell tool — so one middleware covers all three roles.
 * - `RubricMiddleware` and `SummarizationToolMiddleware` have no JS equivalent
 *   and are intentionally omitted; `summarizationMiddleware` covers context
 *   compaction.
 */

import {
  createMiddleware,
  todoListMiddleware,
  toolRetryMiddleware,
  summarizationMiddleware,
} from "langchain";
import { AIMessage } from "@langchain/core/messages";
import { isCommand } from "@langchain/langgraph";
import { createFilesystemMiddleware, LocalShellBackend } from "deepagents";
import type { BaseChatModel } from "@langchain/core/language_models/chat_models";
import type { AnyAgentMiddleware } from "langchain";

/** Build middleware that does not require a model instance. */
export function buildAgentMiddleware(): AnyAgentMiddleware[] {
  return buildMiddleware(null);
}

/** Build LangChain v1 agent middleware that needs a model instance. */
export function buildAgentMiddlewareForModel(model: BaseChatModel): AnyAgentMiddleware[] {
  return buildMiddleware(model);
}

function buildMiddleware(model: BaseChatModel | null): AnyAgentMiddleware[] {
  const workspaceRoot = process.cwd();

  // LocalShellBackend extends FilesystemBackend and adds `execute`. virtualMode
  // anchors relative file paths under the workspace (matching the Python
  // FilesystemBackend(virtual_mode=True)); shell commands run from rootDir with
  // the inherited environment.
  const backend = new LocalShellBackend({
    rootDir: workspaceRoot,
    virtualMode: true,
    inheritEnv: true,
  });

  const middleware: AnyAgentMiddleware[] = [
    todoListMiddleware(),
    createFilesystemMiddleware({ backend }) as unknown as AnyAgentMiddleware,
    sarmaModelRetryMiddleware({ maxRetries: 2 }),
    toolRetryMiddleware({
      maxRetries: 2,
      onFailure: (error: Error) => formatErrorMessage(error),
    }),
  ];

  if (model === null) {
    return middleware;
  }

  middleware.push(summarizationMiddleware({ model }) as unknown as AnyAgentMiddleware);

  return middleware;
}

export function sarmaModelRetryMiddleware(options: { maxRetries?: number } = {}): AnyAgentMiddleware {
  const maxRetries = Math.max(0, Math.trunc(options.maxRetries ?? 2));
  return createMiddleware({
    name: "modelRetryMiddleware",
    wrapModelCall: async (request, handler) => {
      let lastError: unknown = null;
      for (let attempt = 0; attempt <= maxRetries; attempt += 1) {
        try {
          return normalizeModelResponse(await handler(request));
        } catch (exc) {
          lastError = exc;
          if (attempt === maxRetries) break;
        }
      }
      throw new Error(`Model call failed after ${maxRetries + 1} attempts: ${formatErrorMessage(lastError)}`);
    },
  }) as unknown as AnyAgentMiddleware;
}

function formatErrorMessage(error: unknown): string {
  if (!(error instanceof Error)) return String(error ?? "unknown error");

  const parts = [`${error.name}: ${error.message}`];
  let cause = error.cause;
  while (cause) {
    if (cause instanceof Error) {
      parts.push(`${cause.name}: ${cause.message}`);
      cause = cause.cause;
    } else {
      parts.push(String(cause));
      break;
    }
  }
  return parts.join(" <- ");
}

// LangChain's handler may return internal response envelopes in some versions;
// only normalize shapes we know are semantically model responses.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
function normalizeModelResponse(value: unknown): any {
  if (AIMessage.isInstance(value)) return value;
  if (isCommand(value)) return value;
  if (!value || typeof value !== "object") {
    throw new Error(`Unsupported model response from handler: ${typeof value}`);
  }

  const record = value as Record<string, unknown>;
  if (AIMessage.isInstance(record.message)) return record.message;
  if (Array.isArray(record.messages)) {
    const lastAi = [...record.messages].reverse().find((msg) => AIMessage.isInstance(msg));
    if (lastAi) return lastAi;
  }
  throw new Error(`Unsupported model response envelope from handler: ${Object.keys(record).join(", ") || "(empty)"}`);
}
