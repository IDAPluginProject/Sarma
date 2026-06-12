/**
 * Self-contained MCP servers for tests — one per transport (http / sse / stdio).
 *
 * These are real MCP servers built on the official `@modelcontextprotocol/sdk`,
 * each exposing a single `ping` tool. They let us exercise the full
 * DTO → McpClientPool.connect() → live tools path for every transport WITHOUT
 * depending on any externally installed/running MCP server (e.g. IDA-MCP).
 *
 * - HTTP: WebStandardStreamableHTTPServerTransport served via `Bun.serve`.
 * - SSE: SSEServerTransport served via `node:http` (GET = stream, POST = msg).
 * - stdio: a spawned `bun` child running `mockMcpStdioServer.ts`.
 */

import http from "node:http";
import { fileURLToPath } from "node:url";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { WebStandardStreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/webStandardStreamableHttp.js";
import { SSEServerTransport } from "@modelcontextprotocol/sdk/server/sse.js";
import { z } from "zod";

/** Build a fresh MCP server instance exposing a single `ping` tool. */
function buildPingServer(name: string): McpServer {
  const server = new McpServer({ name, version: "1.0.0" });
  server.registerTool(
    "ping",
    { description: "Returns pong.", inputSchema: { msg: z.string().optional() } },
    async ({ msg }) => ({ content: [{ type: "text", text: msg ? `pong: ${msg}` : "pong" }] }),
  );
  return server;
}

export interface LiveMcpServer {
  url: string;
  close: () => Promise<void>;
}

/** Start a streamable-HTTP MCP server on a random port via Bun.serve. */
export async function startHttpMcpServer(): Promise<LiveMcpServer> {
  // Stateless JSON mode: the WebStandard transport cannot be reused across
  // requests, so build a fresh server+transport per request and dispose it
  // once the response is produced.
  const bun = Bun.serve({
    port: 0,
    async fetch(req) {
      const server = buildPingServer("mock-http");
      const transport = new WebStandardStreamableHTTPServerTransport({
        sessionIdGenerator: undefined,
        enableJsonResponse: true,
      });
      await server.connect(transport);
      try {
        return await transport.handleRequest(req);
      } finally {
        await transport.close();
        await server.close();
      }
    },
  });

  return {
    url: `http://127.0.0.1:${bun.port}/mcp`,
    close: async () => {
      bun.stop(true);
    },
  };
}

/** Start an SSE MCP server on a random port via node:http. */
export async function startSseMcpServer(): Promise<LiveMcpServer> {
  const server = buildPingServer("mock-sse");
  let transport: SSEServerTransport | null = null;

  const httpServer = http.createServer(async (req, res) => {
    const url = new URL(req.url ?? "/", "http://127.0.0.1");
    if (req.method === "GET" && url.pathname === "/sse") {
      transport = new SSEServerTransport("/messages", res);
      await server.connect(transport);
      return;
    }
    if (req.method === "POST" && url.pathname === "/messages") {
      if (!transport) {
        res.writeHead(503).end();
        return;
      }
      await transport.handlePostMessage(req, res);
      return;
    }
    res.writeHead(404).end();
  });

  await new Promise<void>((resolve) => httpServer.listen(0, "127.0.0.1", resolve));
  const addr = httpServer.address();
  const port = typeof addr === "object" && addr ? addr.port : 0;

  return {
    url: `http://127.0.0.1:${port}/sse`,
    close: async () => {
      await transport?.close();
      await server.close();
      await new Promise<void>((resolve) => httpServer.close(() => resolve()));
    },
  };
}

/** Absolute path to the spawnable stdio server script. */
export function stdioServerScriptPath(): string {
  return fileURLToPath(new URL("./mockMcpStdioServer.ts", import.meta.url));
}
