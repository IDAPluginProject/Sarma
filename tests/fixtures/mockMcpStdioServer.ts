#!/usr/bin/env bun
/**
 * Self-contained stdio MCP server used by tests.
 *
 * Spawned as a child process (`bun tests/fixtures/mockMcpStdioServer.ts`) and
 * driven over stdin/stdout by the MCP stdio transport. Exposes a single `ping`
 * tool so tests can assert the full DTO → pool.connect() → live tools path for
 * the stdio transport without depending on any externally installed server.
 */

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";

const server = new McpServer({ name: "mock-stdio", version: "1.0.0" });

server.registerTool(
  "ping",
  {
    description: "Returns pong.",
    inputSchema: { msg: z.string().optional() },
  },
  async ({ msg }) => ({
    content: [{ type: "text", text: msg ? `pong: ${msg}` : "pong" }],
  }),
);

const transport = new StdioServerTransport();
await server.connect(transport);
