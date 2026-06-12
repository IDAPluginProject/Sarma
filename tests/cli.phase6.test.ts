import { expect, test, describe } from "bun:test";
import { StreamPrinter, handleEvent } from "@/cli/renderer";
import { StreamEvent } from "@/engine/models";
import { StreamEventType } from "@/engine/enums";

/** Capture stdout writes during a callback. */
function captureStdout(fn: () => void): string {
  const chunks: string[] = [];
  const orig = process.stdout.write.bind(process.stdout);
  process.stdout.write = ((s: string) => {
    chunks.push(typeof s === "string" ? s : String(s));
    return true;
  }) as typeof process.stdout.write;
  try {
    fn();
  } finally {
    process.stdout.write = orig;
  }
  return chunks.join("");
}

function captureStderr(fn: () => void): string {
  const chunks: string[] = [];
  const orig = process.stderr.write.bind(process.stderr);
  process.stderr.write = ((s: string) => {
    chunks.push(typeof s === "string" ? s : String(s));
    return true;
  }) as typeof process.stderr.write;
  try {
    fn();
  } finally {
    process.stderr.write = orig;
  }
  return chunks.join("");
}

describe("StreamPrinter", () => {
  test("feedToken writes raw tokens", () => {
    const out = captureStdout(() => {
      const p = new StreamPrinter();
      p.feedToken("Hello ");
      p.feedToken("world");
    });
    expect(out).toBe("Hello world");
  });

  test("tool timing returns elapsed seconds", () => {
    const p = new StreamPrinter();
    p.startTool("scan");
    const elapsed = p.endTool("scan");
    expect(elapsed).toBeGreaterThanOrEqual(0);
    expect(p.endTool("missing")).toBe(0);
  });

  test("flush adds newline only when mid-line", () => {
    const out = captureStdout(() => {
      const p = new StreamPrinter();
      p.feedToken("no newline");
      p.flush();
    });
    expect(out.endsWith("\n")).toBe(true);
  });
});

describe("handleEvent", () => {
  test("TOKEN event renders content", () => {
    const out = captureStdout(() => {
      const p = new StreamPrinter();
      handleEvent(
        new StreamEvent({ type: StreamEventType.TOKEN, payload: { content: "answer text" } }),
        p,
      );
    });
    expect(out).toContain("answer text");
  });

  test("TOOL_START event prints tool line", () => {
    const out = captureStdout(() => {
      const p = new StreamPrinter();
      handleEvent(
        new StreamEvent({
          type: StreamEventType.TOOL_START,
          payload: { tool_name: "http_exchange", args_json: '{"url":"x"}' },
        }),
        p,
      );
    });
    expect(out).toContain("http_exchange");
  });

  test("SUBAGENT_START prints banner", () => {
    const out = captureStdout(() => {
      const p = new StreamPrinter();
      handleEvent(
        new StreamEvent({
          type: StreamEventType.SUBAGENT_START,
          payload: { subagent: "recon", description: "map attack surface" },
        }),
        p,
      );
    });
    expect(out).toContain("RECON");
    expect(out).toContain("map attack surface");
  });

  test("STAGE_START prints stage banner", () => {
    const out = captureStdout(() => {
      const p = new StreamPrinter();
      handleEvent(
        new StreamEvent({
          type: StreamEventType.STAGE_START,
          payload: { stage: "recon", description: "map attack surface" },
        }),
        p,
      );
    });
    expect(out).toContain("STAGE RECON");
    expect(out).toContain("map attack surface");
  });

  test("RUN_FAILED prints to stderr", () => {
    const err = captureStderr(() => {
      const p = new StreamPrinter();
      handleEvent(
        new StreamEvent({ type: StreamEventType.RUN_FAILED, payload: { error: "boom" } }),
        p,
      );
    });
    expect(err).toContain("boom");
  });
});
