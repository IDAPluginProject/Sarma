import { expect, test, describe } from "bun:test";
import { exchangeHttp, exchangePacket } from "@/resources/networkTools";
import { buildWebSearchTool } from "@/resources/webTools";
import { buildHttpExchangeTool, buildPacketExchangeTool } from "@/resources/networkTools";

describe("network tool construction", () => {
  test("tools expose expected names", () => {
    expect(buildHttpExchangeTool().name).toBe("http_exchange");
    expect(buildPacketExchangeTool().name).toBe("packet_exchange");
    expect(buildWebSearchTool().name).toBe("web_search");
  });

  test("network tool descriptions carry an authorization notice", () => {
    // These tools hit arbitrary hosts; the description must warn the model to
    // only aim them at authorized targets.
    expect(buildHttpExchangeTool().description.toLowerCase()).toContain("authorized");
    expect(buildPacketExchangeTool().description.toLowerCase()).toContain("authorized");
  });
});

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
