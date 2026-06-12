/**
 * Data transfer objects for cross-layer communication.
 *
 * These are the only types that should cross the config → engine boundary.
 */

export interface ModelProviderInit {
  id: number | null;
  name: string;
  modelName: string;
  apiMode: string;
  apiKey: string;
  baseUrl: string;
  temperature: number;
  topP: number;
  maxContextTokens: number;
  enabled: boolean;
}

export class ModelProviderDTO {
  id: number | null;
  name: string;
  modelName: string;
  apiMode: string;
  apiKey: string;
  baseUrl: string;
  temperature: number;
  topP: number;
  maxContextTokens: number;
  enabled: boolean;

  constructor(init: ModelProviderInit) {
    this.id = init.id;
    this.name = init.name;
    this.modelName = init.modelName;
    this.apiMode = init.apiMode;
    this.apiKey = init.apiKey;
    this.baseUrl = init.baseUrl;
    this.temperature = init.temperature;
    this.topP = init.topP;
    this.maxContextTokens = init.maxContextTokens;
    this.enabled = init.enabled;
  }

  toDict(): Record<string, unknown> {
    return {
      id: this.id,
      name: this.name,
      model_name: this.modelName,
      api_mode: this.apiMode,
      api_key: this.apiKey,
      base_url: this.baseUrl,
      temperature: this.temperature,
      top_p: this.topP,
      max_context_tokens: this.maxContextTokens,
      enabled: this.enabled,
    };
  }
}

export interface McpServerInit {
  id: number | null;
  name: string;
  transport: string;
  enabled: boolean;
  command: string;
  args: string;
  env: string;
  cwd: string;
  encoding: string;
  url: string;
  headers: string;
  timeout: number;
  sseReadTimeout: number;
}

function parseJson<T>(raw: string, fallback: T | undefined): T | undefined {
  if (!raw) return fallback;
  try {
    return JSON.parse(raw) as T;
  } catch {
    return fallback;
  }
}

export class McpServerDTO {
  id: number | null;
  name: string;
  transport: string;
  enabled: boolean;
  command: string;
  args: string;
  env: string;
  cwd: string;
  encoding: string;
  url: string;
  headers: string;
  timeout: number;
  sseReadTimeout: number;

  constructor(init: McpServerInit) {
    this.id = init.id;
    this.name = init.name;
    this.transport = init.transport;
    this.enabled = init.enabled;
    this.command = init.command;
    this.args = init.args;
    this.env = init.env;
    this.cwd = init.cwd;
    this.encoding = init.encoding;
    this.url = init.url;
    this.headers = init.headers;
    this.timeout = init.timeout;
    this.sseReadTimeout = init.sseReadTimeout;
  }

  /**
   * Build a `@langchain/mcp-adapters` (JS) server config entry.
   *
   * NOTE: the JS adapter's connection schema differs from the Python one:
   * - HTTP transport literal is `"http"` (NOT Python's `"streamable_http"`);
   *   SSE fallback is handled internally by the adapter.
   * - The streamable-HTTP schema has no `sseReadTimeout` field, so we do not
   *   emit it (zod would silently strip it). `timeout` (seconds) is emitted for
   *   non-stdio transports — the JS adapter ignores/strips it, but the pool's
   *   own connect-timeout wrapper ({@link McpClientPool}) reads it.
   * - stdio `args` is REQUIRED (must be an array), so we always emit it.
   */
  toLangchainConfig(): Record<string, unknown> {
    // Normalize legacy/Python-style "streamable_http" → JS "http".
    const transport =
      this.transport === "streamable_http" ? "http" : this.transport;
    const config: Record<string, unknown> = { transport };
    if (transport === "stdio") {
      config.command = this.command;
      config.args = parseJson<unknown[]>(this.args, []) ?? [];
      if (this.env) {
        const env = parseJson<Record<string, string>>(this.env, undefined);
        if (env !== undefined) config.env = env;
      }
      if (this.cwd) config.cwd = this.cwd;
      if (this.encoding && this.encoding !== "utf-8") config.encoding = this.encoding;
    } else {
      config.url = this.url;
      if (this.headers) {
        const headers = parseJson<Record<string, string>>(this.headers, undefined);
        if (headers !== undefined) config.headers = headers;
      }
      // Pool-level connect-timeout hint (seconds). Stripped by the adapter.
      if (this.timeout) config.timeout = this.timeout;
    }
    return config;
  }

  toDict(): Record<string, unknown> {
    return {
      id: this.id,
      name: this.name,
      transport: this.transport,
      enabled: this.enabled,
      command: this.command,
      args: this.args,
      env: this.env,
      cwd: this.cwd,
      encoding: this.encoding,
      url: this.url,
      headers: this.headers,
      timeout: this.timeout,
      sse_read_timeout: this.sseReadTimeout,
    };
  }
}
