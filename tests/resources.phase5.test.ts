import { expect, test, describe } from "bun:test";
import { existsSync, mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { exchangeHttp, exchangePacket } from "@/resources/networkTools";
import { buildWebSearchTool } from "@/resources/webTools";
import { buildHttpExchangeTool, buildPacketExchangeTool } from "@/resources/networkTools";
import { buildPersistentTerminalTools, PersistentTerminalManager } from "@/resources/terminalTools";

describe("network tool construction", () => {
  test("tools expose expected names", () => {
    expect(buildHttpExchangeTool().name).toBe("http_exchange");
    expect(buildPacketExchangeTool().name).toBe("packet_exchange");
    expect(buildWebSearchTool().name).toBe("web_search");
    expect(buildPersistentTerminalTools().map((t) => t.name)).toEqual([
      "terminal_start",
      "terminal_write",
      "terminal_read",
      "terminal_stop",
      "terminal_list",
    ]);
  });

  test("network tool descriptions carry an authorization notice", () => {
    // These tools hit arbitrary hosts; the description must warn the model to
    // only aim them at authorized targets.
    expect(buildHttpExchangeTool().description.toLowerCase()).toContain("authorized");
    expect(buildPacketExchangeTool().description.toLowerCase()).toContain("authorized");
  });
});

describe("persistent terminal manager", () => {
  test("keeps an interactive process alive across write/read calls", async () => {
    const manager = new PersistentTerminalManager(process.cwd());
    const echo = interactiveEchoCommand();

    try {
      const started = await manager.start({
        terminalId: "echo-test",
        command: echo.command,
        args: echo.args,
        waitMs: 100,
      });
      expect(started).toContain("terminal_id=echo-test");

      const first = await manager.write({ terminalId: "echo-test", input: "hello", waitMs: 200 });
      expect(first).toContain("echo:hello");

      const second = await manager.write({ terminalId: "echo-test", input: "again", waitMs: 200 });
      expect(second).toContain("echo:again");
      expect(second).not.toContain("echo:hello");

      const listed = manager.list();
      expect(listed).toContain("echo-test");
      expect(listed).toContain("running");
    } finally {
      await manager.stop({ terminalId: "echo-test", waitMs: 100 });
    }
  });

  test("rejects working directories outside the workspace", async () => {
    const manager = new PersistentTerminalManager(process.cwd());
    const out = await manager.start({
      terminalId: "bad-cwd",
      command: process.execPath,
      args: ["--version"],
      cwd: "..",
    });
    expect(out).toContain("cwd must stay inside the workspace");
  });

  test("writes terminal transcript under the configured session directory", async () => {
    const root = mkdtempSync(join(tmpdir(), "sarma-terminal-"));
    const logRoot = join(root, ".sarma", "session-123", "terminals");
    const manager = new PersistentTerminalManager(root, {
      conversationId: "session-123",
      logRoot,
    });
    const echo = interactiveEchoCommand();
    try {
      const started = await manager.start({
        terminalId: "log-test",
        command: echo.command,
        args: echo.args,
        waitMs: 100,
      });
      expect(started).toContain(`log_file=${join(logRoot, "log-test.log")}`);

      await manager.write({ terminalId: "log-test", input: "persist me", waitMs: 200 });
      const logFile = join(logRoot, "log-test.log");
      expect(existsSync(logFile)).toBe(true);
      const transcript = readFileSync(logFile, "utf-8");
      expect(transcript).toContain("session_id=session-123");
      expect(transcript).toContain("terminal_id=log-test");
      expect(transcript).toContain("[stdin ");
      expect(transcript).toContain("persist me");
      expect(transcript).toContain("echo:persist me");
    } finally {
      await manager.stop({ terminalId: "log-test", waitMs: 100 });
      rmSync(root, { recursive: true, force: true });
    }
  });
});

function interactiveEchoCommand(): { command: string; args: string[] } {
  if (process.platform === "win32") {
    return {
      command: "powershell.exe",
      args: [
        "-NoLogo",
        "-NoProfile",
        "-Command",
        'while (($line = [Console]::In.ReadLine()) -ne $null) { [Console]::Out.WriteLine("echo:" + $line); [Console]::Out.Flush() }',
      ],
    };
  }
  return {
    command: "sh",
    args: ["-c", 'while IFS= read -r line; do printf "echo:%s\\n" "$line"; done'],
  };
}

describe("exchangeHttp validation", () => {
  test("requires host or url", async () => {
    const out = await exchangeHttp({
      url: "", host: "", port: 0, scheme: "", method: "GET", path: "/",
      headersJson: "", body: "", bodyHex: "", timeout: 5, maxResponseBytes: 1024, verifyTls: true,
    });
    expect(out).toContain("invalid target");
  });

  test("rejects bad scheme", async () => {
    const out = await exchangeHttp({
      url: "ftp://example.com", host: "", port: 0, scheme: "", method: "GET", path: "/",
      headersJson: "", body: "", bodyHex: "", timeout: 5, maxResponseBytes: 1024, verifyTls: true,
    });
    expect(out).toContain("scheme must be http or https");
  });

  test("rejects malformed headers json", async () => {
    const out = await exchangeHttp({
      url: "http://127.0.0.1:1/", host: "", port: 0, scheme: "", method: "GET", path: "/",
      headersJson: "[1,2]", body: "", bodyHex: "", timeout: 1, maxResponseBytes: 1024, verifyTls: true,
    });
    expect(out).toContain("invalid input");
  });
});

describe("exchangePacket validation", () => {
  test("requires host", async () => {
    const out = await exchangePacket({
      host: "", port: 80, protocol: "tcp", payload: "", payloadHex: "",
      timeout: 1, recvBytes: 256, verifyTls: false,
    });
    expect(out).toContain("requires a host");
  });

  test("rejects bad port", async () => {
    const out = await exchangePacket({
      host: "x", port: 0, protocol: "tcp", payload: "", payloadHex: "",
      timeout: 1, recvBytes: 256, verifyTls: false,
    });
    expect(out).toContain("between 1 and 65535");
  });

  test("rejects bad protocol", async () => {
    const out = await exchangePacket({
      host: "127.0.0.1", port: 80, protocol: "carrier-pigeon", payload: "", payloadHex: "",
      timeout: 1, recvBytes: 256, verifyTls: false,
    });
    expect(out).toContain("protocol must be");
  });

  test("rejects invalid hex payload", async () => {
    const out = await exchangePacket({
      host: "127.0.0.1", port: 80, protocol: "tcp", payload: "", payloadHex: "zz",
      timeout: 1, recvBytes: 256, verifyTls: false,
    });
    expect(out).toContain("invalid payload_hex");
  });
});

describe("exchangeHttp live (local server)", () => {
  test("performs a GET and formats response", async () => {
    const server = Bun.serve({
      port: 0,
      fetch: () => new Response("hello world", { status: 200, headers: { "X-Test": "yes" } }),
    });
    try {
      const out = await exchangeHttp({
        url: `http://127.0.0.1:${server.port}/path`, host: "", port: 0, scheme: "",
        method: "GET", path: "/", headersJson: "", body: "", bodyHex: "",
        timeout: 5, maxResponseBytes: 1024, verifyTls: true,
      });
      expect(out).toContain("status=200");
      expect(out).toContain("hello world");
      expect(out).toContain("x-test: yes");
    } finally {
      server.stop(true);
    }
  });
});
