/** MCP client pool — persistent MultiServerMCPClient lifecycle management. */

import { MultiServerMCPClient } from "@langchain/mcp-adapters";
import type { StructuredToolInterface } from "@langchain/core/tools";
import { McpConnectionError } from "@/engine/errors";

export const DEFAULT_MCP_CONNECT_TIMEOUT = 20_000; // ms

/** Connection summary for one configured MCP server. */
export interface McpServerStatus {
  name: string;
  connected: boolean;
  toolCount: number;
  error: string;
}

type ServerConfigs = Record<string, Record<string, unknown>>;

/** Stable serialization of server configs for equality comparison. */
function configFingerprint(configs: ServerConfigs): string {
  try {
    return stableStringify(configs);
  } catch {
    return "";
  }
}

function stableStringify(value: unknown): string {
  return JSON.stringify(value, (_key, val) => {
    if (val && typeof val === "object" && !Array.isArray(val)) {
      const sorted: Record<string, unknown> = {};
      for (const k of Object.keys(val as object).sort()) {
        sorted[k] = (val as Record<string, unknown>)[k];
      }
      return sorted;
    }
    return val;
  });
}

/** Connect timeout in ms = min(default, configured server timeouts). */
function connectTimeout(configs: ServerConfigs): number {
  const timeouts = [DEFAULT_MCP_CONNECT_TIMEOUT];
  for (const config of Object.values(configs)) {
    const t = config.timeout;
    if (typeof t === "number" && t > 0) {
      // Server timeouts are expressed in seconds (parity with Python config).
      timeouts.push(t * 1000);
    }
  }
  return Math.min(...timeouts);
}

function toolBelongsToServer(toolName: string, serverName: string): boolean {
  return (
    toolName === serverName ||
    toolName.startsWith(`${serverName}_`) ||
    toolName.startsWith(`${serverName}__`) ||
    toolName.startsWith(`${serverName}.`) ||
    toolName.startsWith(`${serverName}:`)
  );
}

async function withTimeout<T>(promise: Promise<T>, ms: number): Promise<T> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  const timeout = new Promise<never>((_resolve, reject) => {
    timer = setTimeout(() => reject(new Error(`timed out after ${ms}ms`)), ms);
  });
  try {
    return await Promise.race([promise, timeout]);
  } finally {
    if (timer) clearTimeout(timer);
  }
}

/**
 * Manages persistent MCP client connections.
 *
 * Lazy-connects on first tool request, keeps clients alive for reuse, and
 * provides health-check / reconnect on failure.
 */
export class McpClientPool {
  private client: MultiServerMCPClient | null = null;
  private serverConfigs: ServerConfigs = {};
  private fingerprint = "";
  private toolList: StructuredToolInterface[] = [];
  private connected = false;
  private statuses = new Map<string, McpServerStatus>();

  get isConnected(): boolean {
    return this.connected;
  }

  get tools(): StructuredToolInterface[] {
    return [...this.toolList];
  }

  get serverStatuses(): McpServerStatus[] {
    return [...this.statuses.values()];
  }

  /**
   * Connect (or reconnect) to MCP servers and return available tools.
   *
   * @param serverConfigs map of server name → connection config, as produced
   *        by {@link McpServerDTO.toLangchainConfig}.
   */
  async connect(serverConfigs: ServerConfigs): Promise<StructuredToolInterface[]> {
    const fingerprint = configFingerprint(serverConfigs);
    if (this.connected && fingerprint && fingerprint === this.fingerprint) {
      return this.toolList;
    }

    await this.disconnect();

    this.serverConfigs = { ...serverConfigs };
    this.fingerprint = fingerprint;
    this.statuses = new Map(
      Object.keys(serverConfigs).map((name) => [
        name,
        { name, connected: false, toolCount: 0, error: "" },
      ]),
    );

    if (Object.keys(serverConfigs).length === 0) {
      this.toolList = [];
      this.connected = true;
      return this.toolList;
    }

    try {
      this.client = new MultiServerMCPClient({
        mcpServers: serverConfigs as never,
        prefixToolNameWithServerName: true,
        additionalToolNamePrefix: "",
        throwOnLoadError: true,
      });
      this.toolList = (await withTimeout(
        this.client.getTools(),
        connectTimeout(serverConfigs),
      )) as StructuredToolInterface[];
      this.connected = true;
      this.statuses = new Map(
        Object.keys(serverConfigs).map((name) => [
          name,
          { name, connected: true, toolCount: this.countServerTools(name), error: "" },
        ]),
      );
      return this.toolList;
    } catch (exc) {
      await this.disconnect();
      this.serverConfigs = { ...serverConfigs };
      const message = exc instanceof Error ? exc.message : String(exc);
      this.statuses = new Map(
        Object.keys(serverConfigs).map((name) => [
          name,
          { name, connected: false, toolCount: 0, error: message },
        ]),
      );
      throw new McpConnectionError(Object.keys(serverConfigs).join(", "), message);
    }
  }

  /** Reconnect using the last known server configs. */
  async reconnect(): Promise<StructuredToolInterface[]> {
    if (Object.keys(this.serverConfigs).length === 0) return [];
    return this.connect(this.serverConfigs);
  }

  /** Cleanly close all MCP connections. */
  async disconnect(): Promise<void> {
    if (this.client !== null) {
      try {
        await this.client.close();
      } catch {
        /* best-effort close */
      } finally {
        this.client = null;
      }
    }
    this.toolList = [];
    this.connected = false;
    this.fingerprint = "";
    this.statuses = new Map(
      Object.keys(this.serverConfigs).map((name) => [
        name,
        { name, connected: false, toolCount: 0, error: "" },
      ]),
    );
  }

  /** Apply allow/deny lists to a set of tools. */
  filterTools(
    tools: StructuredToolInterface[],
    allowlist: Set<string> | null = null,
    denylist: Set<string> | null = null,
  ): StructuredToolInterface[] {
    let result = tools;
    if (allowlist !== null) {
      result = result.filter((t) => allowlist.has(t.name));
    }
    if (denylist !== null) {
      result = result.filter((t) => !denylist.has(t.name));
    }
    return result;
  }

  private countServerTools(serverName: string): number {
    return this.toolList.filter((t) => toolBelongsToServer(t.name ?? "", serverName)).length;
  }
}
