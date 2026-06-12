/** Built-in network exchange tools. */

import { tool } from "@langchain/core/tools";
import { z } from "zod";
import type { StructuredToolInterface } from "@langchain/core/tools";
import * as net from "node:net";
import * as tls from "node:tls";
import * as dgram from "node:dgram";

/** Build the built-in LangChain packet exchange tool. */
export function buildPacketExchangeTool(): StructuredToolInterface {
  const packetExchange = tool(
    async (args: {
      host: string;
      port: number;
      protocol?: string;
      payload?: string;
      payload_hex?: string;
      timeout?: number;
      recv_bytes?: number;
      verify_tls?: boolean;
    }): Promise<string> =>
      exchangePacket({
        host: args.host,
        port: args.port,
        protocol: args.protocol ?? "tcp",
        payload: args.payload ?? "",
        payloadHex: args.payload_hex ?? "",
        timeout: args.timeout ?? 5.0,
        recvBytes: args.recv_bytes ?? 4096,
        verifyTls: args.verify_tls ?? false,
      }),
    {
      name: "packet_exchange",
      description:
        "Send one low-level TCP/UDP/TLS payload and return the response.\n\n" +
        "Only use against hosts you are authorized to test — this sends raw " +
        "traffic to an arbitrary host:port and TLS verification is off by " +
        "default (verify_tls).\n\n" +
        "Args: host, port, protocol (tcp|udp|tls), payload, payload_hex, timeout, " +
        "recv_bytes, verify_tls.",
      schema: z.object({
        host: z.string(),
        port: z.number(),
        protocol: z.string().default("tcp"),
        payload: z.string().default(""),
        payload_hex: z.string().default(""),
        timeout: z.number().default(5.0),
        recv_bytes: z.number().default(4096),
        verify_tls: z.boolean().default(false),
      }),
    },
  );
  return packetExchange as unknown as StructuredToolInterface;
}

/** Build the built-in LangChain HTTP/HTTPS exchange tool. */
export function buildHttpExchangeTool(): StructuredToolInterface {
  const httpExchange = tool(
    async (args: {
      url?: string;
      host?: string;
      port?: number;
      scheme?: string;
      method?: string;
      path?: string;
      headers_json?: string;
      body?: string;
      body_hex?: string;
      timeout?: number;
      max_response_bytes?: number;
      verify_tls?: boolean;
    }): Promise<string> =>
      exchangeHttp({
        url: args.url ?? "",
        host: args.host ?? "",
        port: args.port ?? 0,
        scheme: args.scheme ?? "",
        method: args.method ?? "GET",
        path: args.path ?? "/",
        headersJson: args.headers_json ?? "",
        body: args.body ?? "",
        bodyHex: args.body_hex ?? "",
        timeout: args.timeout ?? 10.0,
        maxResponseBytes: args.max_response_bytes ?? 16384,
        verifyTls: args.verify_tls ?? true,
      }),
    {
      name: "http_exchange",
      description:
        "Send one HTTP/HTTPS request for service and port testing.\n\n" +
        "Only use against hosts you are authorized to test — this issues a " +
        "request to an arbitrary target and can disable TLS verification " +
        "(verify_tls=false).\n\n" +
        "Args: url (overrides host/port/scheme/path), host, port, scheme, method, " +
        "path, headers_json, body, body_hex, timeout, max_response_bytes, verify_tls.",
      schema: z.object({
        url: z.string().default(""),
        host: z.string().default(""),
        port: z.number().default(0),
        scheme: z.string().default(""),
        method: z.string().default("GET"),
        path: z.string().default("/"),
        headers_json: z.string().default(""),
        body: z.string().default(""),
        body_hex: z.string().default(""),
        timeout: z.number().default(10.0),
        max_response_bytes: z.number().default(16384),
        verify_tls: z.boolean().default(true),
      }),
    },
  );
  return httpExchange as unknown as StructuredToolInterface;
}

function payloadBytes(payload: string, payloadHex: string): Buffer {
  if (payloadHex.trim()) {
    const hex = payloadHex.split(/\s+/).join("");
    if (!/^[0-9a-fA-F]*$/.test(hex) || hex.length % 2 !== 0) {
      throw new Error("invalid hex");
    }
    return Buffer.from(hex, "hex");
  }
  return Buffer.from(payload, "utf-8");
}

interface PacketArgs {
  host: string;
  port: number;
  protocol: string;
  payload: string;
  payloadHex: string;
  timeout: number;
  recvBytes: number;
  verifyTls: boolean;
}

export async function exchangePacket(args: PacketArgs): Promise<string> {
  const host = args.host.trim();
  if (!host) return "packet_exchange requires a host.";
  const port = Math.trunc(args.port);
  if (!(port > 0 && port <= 65535)) return "packet_exchange port must be between 1 and 65535.";

  const proto = args.protocol.trim().toLowerCase();
  let data: Buffer;
  try {
    data = payloadBytes(args.payload, args.payloadHex);
  } catch (exc) {
    return `packet_exchange invalid payload_hex: ${exc instanceof Error ? exc.message : exc}`;
  }
  const maxRecv = Math.max(1, Math.min(Math.trunc(args.recvBytes || 4096), 1024 * 1024));
  const timeoutMs = Math.max(0.1, args.timeout || 5.0) * 1000;

  try {
    let response: Buffer;
    if (proto === "tcp") {
      response = await tcpExchange(host, port, data, timeoutMs, maxRecv, false, false);
    } else if (proto === "tls" || proto === "ssl") {
      response = await tcpExchange(host, port, data, timeoutMs, maxRecv, true, args.verifyTls);
    } else if (proto === "udp") {
      response = await udpExchange(host, port, data, timeoutMs, maxRecv);
    } else {
      return "packet_exchange protocol must be 'tcp', 'udp', or 'tls'.";
    }
    return formatResponse(proto, host, port, data, response);
  } catch (exc) {
    return `packet_exchange failed: ${exc instanceof Error ? exc.message : exc}`;
  }
}

function tcpExchange(
  host: string,
  port: number,
  data: Buffer,
  timeoutMs: number,
  recvBytes: number,
  useTls: boolean,
  verifyTls: boolean,
): Promise<Buffer> {
  return new Promise((resolve, reject) => {
    const chunks: Buffer[] = [];
    let total = 0;
    let settled = false;
    const socket: net.Socket = useTls
      ? tls.connect({ host, port, rejectUnauthorized: verifyTls, servername: host })
      : net.connect({ host, port });

    const finish = () => {
      if (settled) return;
      settled = true;
      socket.destroy();
      resolve(Buffer.concat(chunks).subarray(0, recvBytes));
    };
    const fail = (err: Error) => {
      if (settled) return;
      settled = true;
      socket.destroy();
      reject(err);
    };
    socket.setTimeout(timeoutMs);
    const onReady = () => {
      if (data.length) socket.write(data);
    };
    socket.on(useTls ? "secureConnect" : "connect", onReady);
    socket.on("data", (chunk: Buffer) => {
      chunks.push(chunk);
      total += chunk.length;
      if (total >= recvBytes) finish();
    });
    socket.on("timeout", finish);
    socket.on("end", finish);
    socket.on("close", finish);
    socket.on("error", (err) => {
      if (chunks.length) finish();
      else fail(err);
    });
  });
}

function udpExchange(
  host: string,
  port: number,
  data: Buffer,
  timeoutMs: number,
  recvBytes: number,
): Promise<Buffer> {
  return new Promise((resolve, reject) => {
    const socket = dgram.createSocket("udp4");
    // Guard against double-settle: timeout, message, and error can race, and
    // calling socket.close() twice throws "Not running".
    let settled = false;
    const finish = (fn: () => void) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      socket.close();
      fn();
    };
    const timer = setTimeout(() => {
      finish(() => resolve(Buffer.alloc(0)));
    }, timeoutMs);
    socket.on("message", (msg: Buffer) => {
      finish(() => resolve(msg.subarray(0, recvBytes)));
    });
    socket.on("error", (err) => {
      finish(() => reject(err));
    });
    socket.send(data, port, host, (err) => {
      if (err) finish(() => reject(err));
    });
  });
}

interface HttpArgs {
  url: string;
  host: string;
  port: number;
  scheme: string;
  method: string;
  path: string;
  headersJson: string;
  body: string;
  bodyHex: string;
  timeout: number;
  maxResponseBytes: number;
  verifyTls: boolean;
}

interface HttpTarget {
  scheme: string;
  host: string;
  port: number;
  path: string;
}

export async function exchangeHttp(args: HttpArgs): Promise<string> {
  let target: HttpTarget;
  try {
    target = resolveHttpTarget(args.url, args.host, args.port, args.scheme, args.path);
  } catch (exc) {
    return `http_exchange invalid target: ${exc instanceof Error ? exc.message : exc}`;
  }

  let headers: Record<string, string>;
  let data: Buffer;
  try {
    headers = parseHeaders(args.headersJson);
    data = payloadBytes(args.body, args.bodyHex);
  } catch (exc) {
    return `http_exchange invalid input: ${exc instanceof Error ? exc.message : exc}`;
  }

  const method = (args.method.trim().toUpperCase() || "GET");
  const maxBody = Math.max(1, Math.min(Math.trunc(args.maxResponseBytes || 16384), 1024 * 1024));
  const timeoutMs = Math.max(0.1, args.timeout || 10.0) * 1000;

  const nodeHttp = target.scheme === "https" ? await import("node:https") : await import("node:http");
  return new Promise<string>((resolve) => {
    let req: ReturnType<typeof nodeHttp.request>;
    try {
      req = nodeHttp.request(
        {
          host: target.host,
          port: target.port,
          method,
          path: target.path,
          headers,
          timeout: timeoutMs,
          ...(target.scheme === "https" && !args.verifyTls ? { rejectUnauthorized: false } : {}),
        },
        (res) => {
          const chunks: Buffer[] = [];
          let total = 0;
          res.on("data", (chunk: Buffer) => {
            if (total < maxBody) {
              chunks.push(chunk);
              total += chunk.length;
            } else {
              // Reached the cap — stop the transfer instead of draining the
              // rest of a potentially huge body into the void.
              res.destroy();
            }
          });
          res.on("end", () => {
            const responseBody = Buffer.concat(chunks).subarray(0, maxBody);
            const headerPairs = Object.entries(res.headers).map(
              ([k, v]) => [k, Array.isArray(v) ? v.join(", ") : String(v ?? "")] as [string, string],
            );
            resolve(
              formatHttpResponse(target, method, data.length, res.statusCode ?? 0, res.statusMessage ?? "", headerPairs, responseBody),
            );
          });
          // After res.destroy() the socket closes without "end"; surface what
          // we captured rather than hanging the promise.
          res.on("close", () => {
            if (total >= maxBody) {
              const responseBody = Buffer.concat(chunks).subarray(0, maxBody);
              const headerPairs = Object.entries(res.headers).map(
                ([k, v]) => [k, Array.isArray(v) ? v.join(", ") : String(v ?? "")] as [string, string],
              );
              resolve(
                formatHttpResponse(target, method, data.length, res.statusCode ?? 0, res.statusMessage ?? "", headerPairs, responseBody),
              );
            }
          });
        },
      );
    } catch (exc) {
      // nodeHttp.request can throw synchronously on bad header values / options.
      resolve(`http_exchange failed: ${exc instanceof Error ? exc.message : String(exc)}`);
      return;
    }
    req.on("timeout", () => req.destroy(new Error("timeout")));
    req.on("error", (exc) => resolve(`http_exchange failed: ${exc.message}`));
    if (data.length) req.write(data);
    req.end();
  });
}

function resolveHttpTarget(
  url: string,
  host: string,
  port: number,
  scheme: string,
  path: string,
): HttpTarget {
  if (url.trim()) {
    const parsed = new URL(url.trim());
    const sch = parsed.protocol.replace(":", "");
    if (sch !== "http" && sch !== "https") throw new Error("url scheme must be http or https");
    if (!parsed.hostname) throw new Error("url must include a host");
    let targetPath = parsed.pathname || "/";
    if (parsed.search) targetPath += parsed.search;
    return {
      scheme: sch,
      host: parsed.hostname,
      port: parsed.port ? Number(parsed.port) : sch === "https" ? 443 : 80,
      path: targetPath,
    };
  }
  const targetHost = host.trim();
  if (!targetHost) throw new Error("host is required when url is empty");
  const targetScheme = scheme.trim().toLowerCase() || "http";
  if (targetScheme !== "http" && targetScheme !== "https") throw new Error("scheme must be http or https");
  const targetPort = Math.trunc(port || (targetScheme === "https" ? 443 : 80));
  if (!(targetPort > 0 && targetPort <= 65535)) throw new Error("port must be between 1 and 65535");
  let targetPath = path.trim() || "/";
  if (!targetPath.startsWith("/")) targetPath = `/${targetPath}`;
  return { scheme: targetScheme, host: targetHost, port: targetPort, path: targetPath };
}

function parseHeaders(headersJson: string): Record<string, string> {
  const text = headersJson.trim();
  if (!text) return {};
  const parsed = JSON.parse(text);
  if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
    throw new Error("headers_json must be a JSON object");
  }
  const result: Record<string, string> = {};
  for (const [key, value] of Object.entries(parsed)) result[String(key)] = String(value);
  return result;
}

function pyRepr(text: string): string {
  // Approximate Python repr() for response_text= fields.
  const escaped = text
    .replace(/\\/g, "\\\\")
    .replace(/'/g, "\\'")
    .replace(/\n/g, "\\n")
    .replace(/\r/g, "\\r")
    .replace(/\t/g, "\\t");
  return `'${escaped}'`;
}

function formatResponse(protocol: string, host: string, port: number, sent: Buffer, response: Buffer): string {
  let text = response.toString("utf-8");
  if (text.length > 2000) text = text.slice(0, 1997) + "...";
  return (
    `packet_exchange ${protocol.toUpperCase()} ${host}:${port}\n` +
    `sent_bytes=${sent.length} received_bytes=${response.length}\n` +
    `response_text=${pyRepr(text)}\n` +
    `response_hex=${response.subarray(0, 512).toString("hex")}`
  );
}

function formatHttpResponse(
  target: HttpTarget,
  method: string,
  sentBytes: number,
  status: number,
  reason: string,
  headers: [string, string][],
  response: Buffer,
): string {
  let text = response.toString("utf-8");
  if (text.length > 4000) text = text.slice(0, 3997) + "...";
  const headerLines = headers.slice(0, 40).map(([name, value]) => `${name}: ${value}`).join("\n");
  return (
    `http_exchange ${method} ${target.scheme}://${target.host}:${target.port}${target.path}\n` +
    `status=${status} reason=${pyRepr(reason)} sent_bytes=${sentBytes} received_bytes=${response.length}\n` +
    `response_headers:\n${headerLines}\n` +
    `response_text=${pyRepr(text)}\n` +
    `response_hex=${response.subarray(0, 512).toString("hex")}`
  );
}
