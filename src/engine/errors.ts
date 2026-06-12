/** Runtime exceptions and error types. */

/** Base exception for Sarma runtime failures. */
export class SarmaRuntimeError extends Error {
  constructor(message = "") {
    super(message);
    this.name = new.target.name;
  }
}

/** No model provider is configured or the selected one is invalid. */
export class ProviderNotConfiguredError extends SarmaRuntimeError {}

/** Failed to connect to an MCP server. */
export class McpConnectionError extends SarmaRuntimeError {
  readonly serverName: string;

  constructor(serverName: string, detail = "") {
    let msg = `MCP connection failed: ${serverName}`;
    if (detail) msg += ` — ${detail}`;
    super(msg);
    this.serverName = serverName;
  }
}

/** Failed to construct the LangGraph agent. */
export class AgentBuildError extends SarmaRuntimeError {}

/** Agent execution failed during streaming. */
export class AgentRunError extends SarmaRuntimeError {
  readonly recoverable: boolean;

  constructor(detail = "", recoverable = true) {
    super(detail);
    this.recoverable = recoverable;
  }
}

/** Database operation for runtime data failed. */
export class PersistenceError extends SarmaRuntimeError {
  readonly operation: string;

  constructor(operation = "", detail = "") {
    let msg = operation
      ? `Runtime persistence failed: ${operation}`
      : "Runtime persistence failed";
    if (detail) msg += ` — ${detail}`;
    super(msg);
    this.operation = operation;
  }
}
