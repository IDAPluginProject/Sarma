import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import { mkdtempSync, rmSync, existsSync, readFileSync, mkdirSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { createRoot } from "solid-js";
import { AgentConfig, CliConfig, KnowledgeBaseConfig, McpServerConfig, ProviderConfig } from "@/config";
import { createController } from "@/tui/controller";
import { parseContextSize } from "@/tui/controller";
import { Store } from "@/store";
import { Session } from "@/session";
import { StreamEvent } from "@/engine/models";
import { StreamEventType } from "@/engine/enums";
import * as paths from "@/paths";

let home: string;
let workspace: string;
let prevHome: string | undefined;
let prevSkillHub: string | undefined;
let prevCwd: string;

beforeEach(() => {
  prevHome = process.env.SARMA_HOME;
  prevSkillHub = process.env.SARMA_SKILLSHUB_URL;
  prevCwd = process.cwd();
  home = mkdtempSync(join(tmpdir(), "sarma-tui-cfg-"));
  workspace = mkdtempSync(join(tmpdir(), "sarma-tui-work-"));
  process.env.SARMA_HOME = home;
  process.chdir(workspace);
});

afterEach(() => {
  process.chdir(prevCwd);
  if (prevHome === undefined) delete process.env.SARMA_HOME;
  else process.env.SARMA_HOME = prevHome;
  if (prevSkillHub === undefined) delete process.env.SARMA_SKILLSHUB_URL;
  else process.env.SARMA_SKILLSHUB_URL = prevSkillHub;
  rmSync(home, { recursive: true, force: true });
  rmSync(workspace, { recursive: true, force: true });
});

describe("TUI controller model config", () => {
  test("starts with no model and reports hasModel() false", async () => {
    await new Promise<void>((resolve, reject) => {
      createRoot((dispose) => {
        void (async () => {
          try {
            const c = createController(new CliConfig(), ["ruflo", "audit", "audit-slim"]);
            expect(c.hasModel()).toBe(false);
            expect(c.modelName()).toBe("(unset)");
            await c.close();
            dispose();
            resolve();
          } catch (exc) {
            dispose();
            reject(exc);
          }
        })();
      });
    });
  });

  test("saveModel writes models.toml, flips hasModel(), and updates modelName()", async () => {
    await new Promise<void>((resolve, reject) => {
      createRoot((dispose) => {
        void (async () => {
          try {
            const config = new CliConfig();
            const c = createController(config, ["ruflo", "audit", "audit-slim"]);

            c.openConfig();
            expect(c.configOpen()).toBe(true);
            expect(c.configStep()).toBe("browse");

            // Step 1: choose the interface type.
            c.chooseInterface("anthropic");
            expect(c.configStep()).toBe("model-fields");

            // Step 2: fill connection details + user-supplied context size.
            c.setModelField("name", "primary");
            c.setModelField("modelName", "claude-sonnet-4-6");
            c.setModelField("baseUrl", "https://example.test/v1");
            c.setModelField("apiKey", "sk-secret");
            c.setModelField("maxContextTokens", "200000");

            const err = await c.saveModel();
            expect(err).toBeNull();

            // Config object mutated in place.
            expect(config.activeModel).toBe("primary");
            expect(config.getModel("primary").modelName).toBe("claude-sonnet-4-6");
            expect(config.getModel("primary").apiMode).toBe("anthropic");
            expect(config.getModel("primary").maxContextTokens).toBe(200000);

            // Reactive getters reflect the new model.
            expect(c.hasModel()).toBe(true);
            expect(c.modelName()).toBe("claude-sonnet-4-6");
            expect(c.configOpen()).toBe(true);
            expect(c.configStep()).toBe("browse");

            // models.toml persisted to disk.
            const file = paths.globalModelsFile();
            expect(existsSync(file)).toBe(true);
            const toml = readFileSync(file, "utf-8");
            expect(toml).toContain('active = "primary"');
            expect(toml).toContain('model_name = "claude-sonnet-4-6"');
            expect(toml).toContain('api_mode = "anthropic"');
            expect(toml).toContain('base_url = "https://example.test/v1"');
            expect(toml).toContain("max_context_tokens = 200000");

            await c.close();
            dispose();
            resolve();
          } catch (exc) {
            dispose();
            reject(exc);
          }
        })();
      });
    });
  });

  test("saveModel rejects an empty Model ID", async () => {
    await new Promise<void>((resolve, reject) => {
      createRoot((dispose) => {
        void (async () => {
          try {
            const c = createController(new CliConfig(), ["ruflo"]);
            c.setModelField("modelName", "   ");
            const err = await c.saveModel();
            expect(err).toBe("Model ID is required.");
            expect(c.hasModel()).toBe(false);
            await c.close();
            dispose();
            resolve();
          } catch (exc) {
            dispose();
            reject(exc);
          }
        })();
      });
    });
  });

  test("saveModel rejects a non-numeric context size", async () => {
    await new Promise<void>((resolve, reject) => {
      createRoot((dispose) => {
        void (async () => {
          try {
            const c = createController(new CliConfig(), ["ruflo"]);
            c.setModelField("modelName", "gpt-4o-mini");
            c.setModelField("maxContextTokens", "lots");
            const err = await c.saveModel();
            expect(err).toContain("Context size");
            expect(c.hasModel()).toBe(false);
            await c.close();
            dispose();
            resolve();
          } catch (exc) {
            dispose();
            reject(exc);
          }
        })();
      });
    });
  });

  test("testModel validates the current model draft before probing the provider", async () => {
    await new Promise<void>((resolve, reject) => {
      createRoot((dispose) => {
        void (async () => {
          try {
            const c = createController(new CliConfig(), ["ruflo"]);
            c.setModelField("modelName", "   ");
            expect(await c.testModel()).toBe("Model ID is required.");

            c.setModelField("modelName", "gpt-4o-mini");
            c.setModelField("maxContextTokens", "lots");
            expect(await c.testModel()).toContain("Context size");

            await c.close();
            dispose();
            resolve();
          } catch (exc) {
            dispose();
            reject(exc);
          }
        })();
      });
    });
  });

  test("chooseInterface sets the apiMode and advances the step", async () => {
    await new Promise<void>((resolve, reject) => {
      createRoot((dispose) => {
        void (async () => {
          try {
            const c = createController(new CliConfig(), ["ruflo"]);
            c.openConfig();
            expect(c.configStep()).toBe("browse");
            c.chooseInterface("openai_responses");
            expect(c.modelDraft.apiMode).toBe("openai_responses");
            expect(c.configStep()).toBe("model-fields");
            c.backToInterface();
            expect(c.configStep()).toBe("browse");
            await c.close();
            dispose();
            resolve();
          } catch (exc) {
            dispose();
            reject(exc);
          }
        })();
      });
    });
  });

  test("saveModel accepts K/M context-size notation", async () => {
    await new Promise<void>((resolve, reject) => {
      createRoot((dispose) => {
        void (async () => {
          try {
            const config = new CliConfig();
            const c = createController(config, ["ruflo"]);
            c.setModelField("name", "primary");
            c.setModelField("modelName", "claude-opus-4-8");
            c.setModelField("apiMode", "anthropic");
            c.setModelField("maxContextTokens", "1M");
            const err = await c.saveModel();
            expect(err).toBeNull();
            expect(config.getModel("primary").maxContextTokens).toBe(1_000_000);
            await c.close();
            dispose();
            resolve();
          } catch (exc) {
            dispose();
            reject(exc);
          }
        })();
      });
    });
  });

  test("newConfigModel starts with a blank model instead of copying the active model", async () => {
    await new Promise<void>((resolve, reject) => {
      createRoot((dispose) => {
        void (async () => {
          try {
            const config = new CliConfig({
              activeModel: "primary",
              models: [
                new ProviderConfig({
                  name: "primary",
                  modelName: "gpt-4o-mini",
                  apiMode: "openai_compatible",
                  enabled: true,
                }),
              ],
            });
            const c = createController(config, ["ruflo"]);

            c.openConfig();
            c.newConfigModel();

            expect(c.configStep()).toBe("model-fields");
            expect(c.modelDraft.name).toBe("new-model");
            expect(c.modelDraft.modelName).toBe("");
            expect(c.modelDraft.apiKey).toBe("");

            await c.close();
            dispose();
            resolve();
          } catch (exc) {
            dispose();
            reject(exc);
          }
        })();
      });
    });
  });

  test("workflow config groups agents under the selected workflow", async () => {
    await new Promise<void>((resolve, reject) => {
      createRoot((dispose) => {
        void (async () => {
          try {
            const c = createController(new CliConfig(), ["ruflo", "audit", "audit-slim"]);

            c.openConfig();
            c.setConfigSection("workflow");
            expect(c.configWorkflowRows().map((row) => row.name)).toEqual(["ruflo", "audit", "audit-slim"]);
            expect(c.configAgentRows().map((row) => row.name)).toEqual(["ruflo"]);

            c.moveConfigWorkflowSelection(1);
            expect(c.configAgentRows().map((row) => row.name)).toEqual([
              "audit",
              "audit.recon",
              "audit.hunt",
              "audit.validate",
              "audit.gapfill",
              "audit.dedupe",
              "audit.trace",
              "audit.feedback",
              "audit.report",
            ]);

            c.moveConfigWorkflowSelection(1);
            expect(c.configAgentRows().map((row) => row.name)).toEqual([
              "audit-slim",
              "audit-slim.recon",
              "audit-slim.hunter",
              "audit-slim.verify",
              "audit-slim.report",
            ]);

            await c.close();
            dispose();
            resolve();
          } catch (exc) {
            dispose();
            reject(exc);
          }
        })();
      });
    });
  });
});

describe("parseContextSize", () => {
  test("parses plain, separated, and SI-suffix forms", () => {
    expect(parseContextSize("128000")).toBe(128_000);
    expect(parseContextSize("128_000")).toBe(128_000);
    expect(parseContextSize("128,000")).toBe(128_000);
    expect(parseContextSize("200K")).toBe(200_000);
    expect(parseContextSize("200 K")).toBe(200_000);
    expect(parseContextSize("200kb")).toBe(200_000);
    expect(parseContextSize("256k")).toBe(256_000);
    expect(parseContextSize("1M")).toBe(1_000_000);
    expect(parseContextSize("1 M")).toBe(1_000_000);
    expect(parseContextSize("1.5m")).toBe(1_500_000);
    expect(parseContextSize("1.5m tokens")).toBe(1_500_000);
    expect(parseContextSize("1G")).toBe(1_000_000_000);
    expect(parseContextSize("1gb")).toBe(1_000_000_000);
    expect(parseContextSize("2T")).toBe(2_000_000_000_000);
    expect(parseContextSize(" 1M ")).toBe(1_000_000);
  });

  test("rejects non-positive and malformed input", () => {
    expect(parseContextSize("")).toBeNull();
    expect(parseContextSize("lots")).toBeNull();
    expect(parseContextSize("0")).toBeNull();
    expect(parseContextSize("-5")).toBeNull();
    expect(parseContextSize("1P")).toBeNull();
    expect(parseContextSize("12x3")).toBeNull();
  });
});

describe("TUI controller stages and lifecycle", () => {
  test("audit stage panel matches the real subagent order", async () => {
    await new Promise<void>((resolve, reject) => {
      createRoot((dispose) => {
        void (async () => {
          try {
            const c = createController(new CliConfig(), ["ruflo", "audit", "audit-slim"]);
            c.setWorkflow("audit");
            const names = c.stages().map((s) => s.name);
            // The real audit pipeline runs these nodes; the panel must list them, not
            // a hardcoded guess like "confirm".
            expect(names).toEqual(["recon", "hunt", "validate", "gapfill", "dedupe", "trace", "feedback", "report"]);
            expect(names).not.toContain("confirm");
            await c.close();
            dispose();
            resolve();
          } catch (exc) {
            dispose();
            reject(exc);
          }
        })();
      });
    });
  });

  test("audit workflow graph exposes router check nodes and graph boundaries", async () => {
    await new Promise<void>((resolve, reject) => {
      createRoot((dispose) => {
        void (async () => {
          try {
            const c = createController(new CliConfig(), ["ruflo", "audit", "audit-slim"]);
            c.setWorkflow("audit");
            const graph = c.workflowGraph();
            const labels = graph.nodes.map((node) => node.label);
            expect(labels).toContain("START");
            expect(labels).toContain("validate_check");
            expect(labels).toContain("gapfill_check");
            expect(labels).toContain("feedback_check");
            expect(labels).toContain("END");
            expect(labels).not.toContain("audit primary agent");
            expect(graph.nodes.find((node) => node.name === "validate_check")?.kind).toBe("router");
            await c.close();
            dispose();
            resolve();
          } catch (exc) {
            dispose();
            reject(exc);
          }
        })();
      });
    });
  });

  test("audit-slim stage panel matches the real subagent order", async () => {
    await new Promise<void>((resolve, reject) => {
      createRoot((dispose) => {
        void (async () => {
          try {
            const c = createController(new CliConfig(), ["ruflo", "audit", "audit-slim"]);
            c.setWorkflow("audit-slim");
            expect(c.stages().map((s) => s.name)).toEqual(["recon", "hunter", "verify", "report"]);
            await c.close();
            dispose();
            resolve();
          } catch (exc) {
            dispose();
            reject(exc);
          }
        })();
      });
    });
  });

  test("audit-slim workflow graph exposes verify router and graph boundaries", async () => {
    await new Promise<void>((resolve, reject) => {
      createRoot((dispose) => {
        void (async () => {
          try {
            const c = createController(new CliConfig(), ["ruflo", "audit", "audit-slim"]);
            c.setWorkflow("audit-slim");
            const graph = c.workflowGraph();
            const labels = graph.nodes.map((node) => node.label);
            expect(labels).toContain("START");
            expect(labels).toContain("verify_check");
            expect(labels).toContain("END");
            expect(labels).not.toContain("audit-slim primary agent");
            expect(graph.nodes.find((node) => node.name === "verify_check")?.kind).toBe("router");
            expect(graph.nodes.find((node) => node.name === "verify_check")?.detail).toContain("hunter | report");
            await c.close();
            dispose();
            resolve();
          } catch (exc) {
            dispose();
            reject(exc);
          }
        })();
      });
    });
  });

  test("ruflo workflow graph shows dynamic delegation instead of fixed stages", async () => {
    await new Promise<void>((resolve, reject) => {
      createRoot((dispose) => {
        void (async () => {
          try {
            const c = createController(new CliConfig(), ["ruflo", "audit", "audit-slim"]);
            const graph = c.workflowGraph();
            expect(graph.workflow).toBe("ruflo");
            expect(graph.nodes.map((node) => node.label)).toContain("model/tools loop");
            expect(graph.nodes.map((node) => node.label)).toContain("parallel delegate_task fan-out");
            expect(graph.nodes.map((node) => node.label)).toContain("delegate_task[*] -> focused subagent");
            expect(graph.nodes.some((node) => node.kind === "parallel")).toBe(true);
            expect(graph.nodes.some((node) => node.kind === "delegate")).toBe(true);
            expect(graph.nodes.some((node) => node.kind === "stage")).toBe(false);
            await c.close();
            dispose();
            resolve();
          } catch (exc) {
            dispose();
            reject(exc);
          }
        })();
      });
    });
  });

  test("close() is idempotent", async () => {
    await new Promise<void>((resolve, reject) => {
      createRoot((dispose) => {
        void (async () => {
          try {
            const c = createController(new CliConfig(), ["ruflo"]);
            await c.close();
            // A second close must not throw (e.g. double store.close()).
            await c.close();
            dispose();
            resolve();
          } catch (exc) {
            dispose();
            reject(exc);
          }
        })();
      });
    });
  });

  test("submit surfaces run failures in transcript and status", async () => {
    await new Promise<void>((resolve, reject) => {
      createRoot((dispose) => {
        void (async () => {
          try {
            const c = createController(new CliConfig(), ["ruflo"]);

            await c.submit("hello");

            expect(c.items.some((item) => item.kind === "error" && item.text.includes("Model name is required"))).toBe(true);
            expect(c.status()).toContain("error:");
            expect(c.status()).toContain("Model name is required");

            await c.close();
            dispose();
            resolve();
          } catch (exc) {
            dispose();
            reject(exc);
          }
        })();
      });
    });
  });

  test("submit keeps streamed text before the tool call that follows it", async () => {
    const originalRunTurn = Session.prototype.runTurn;
    Session.prototype.runTurn = async function* () {
      yield new StreamEvent({
        type: StreamEventType.TOKEN,
        payload: { content: "First I will inspect metadata. " },
      });
      yield new StreamEvent({
        type: StreamEventType.TOOL_START,
        payload: { tool_name: "ida__get_metadata", tool_call_id: "tool-1", args_json: "{}" },
      });
      yield new StreamEvent({
        type: StreamEventType.TOOL_RESULT,
        payload: { tool_name: "ida__get_metadata", tool_call_id: "tool-1", result_summary: "metadata ok" },
      });
      yield new StreamEvent({
        type: StreamEventType.TOKEN,
        payload: { content: "Then I will continue." },
      });
    };
    try {
      await new Promise<void>((resolve, reject) => {
        createRoot((dispose) => {
          void (async () => {
            try {
              const c = createController(new CliConfig(), ["ruflo"]);
              await c.submit("audit target");

              expect(c.items.map((item) => item.kind)).toEqual(["message", "message", "tool", "message"]);
              expect(c.items[1]?.kind).toBe("message");
              expect(c.items[1]?.kind === "message" ? c.items[1].content : "").toContain("inspect metadata");
              expect(c.items[2]?.kind).toBe("tool");
              expect(c.items[3]?.kind).toBe("message");
              expect(c.items[3]?.kind === "message" ? c.items[3].content : "").toContain("continue");

              await c.close();
              dispose();
              resolve();
            } catch (exc) {
              dispose();
              reject(exc);
            }
          })();
        });
      });
    } finally {
      Session.prototype.runTurn = originalRunTurn;
    }
  });

  test("submit updates sidebar todos from write_todos events", async () => {
    const originalRunTurn = Session.prototype.runTurn;
    Session.prototype.runTurn = async function* () {
      yield new StreamEvent({
        type: StreamEventType.TOOL_START,
        payload: {
          tool_name: "write_todos",
          tool_call_id: "todo-1",
          args: {
            todos: [
              { content: "Map init entry points", status: "completed" },
              { content: "Audit SSLVPN handlers", status: "in_progress" },
            ],
          },
          args_json: "",
        },
      });
      yield new StreamEvent({
        type: StreamEventType.TOOL_RESULT,
        payload: { tool_name: "write_todos", tool_call_id: "todo-1", result_summary: "ok" },
      });
    };
    try {
      await new Promise<void>((resolve, reject) => {
        createRoot((dispose) => {
          void (async () => {
            try {
              const c = createController(new CliConfig(), ["ruflo"]);
              await c.submit("audit target");

              expect(c.todoItems()).toEqual([
                { content: "Map init entry points", status: "completed" },
                { content: "Audit SSLVPN handlers", status: "in_progress" },
              ]);

              await c.close();
              dispose();
              resolve();
            } catch (exc) {
              dispose();
              reject(exc);
            }
          })();
        });
      });
    } finally {
      Session.prototype.runTurn = originalRunTurn;
    }
  });

  test("submit stores delegate subagent result and error details", async () => {
    const originalRunTurn = Session.prototype.runTurn;
    Session.prototype.runTurn = async function* () {
      yield new StreamEvent({
        type: StreamEventType.SUBAGENT_START,
        payload: {
          subagent: "ssl-vpn-audit",
          description: "Audit SSLVPN attack surface",
          tool_call_id: "delegate-ssl",
        },
      });
      yield new StreamEvent({
        type: StreamEventType.SUBAGENT_COMPLETE,
        payload: {
          subagent: "ssl-vpn-audit",
          tool_call_id: "delegate-ssl",
          result_summary: "Found portal handlers and auth checks.",
        },
      });
      yield new StreamEvent({
        type: StreamEventType.SUBAGENT_START,
        payload: {
          subagent: "auth-audit",
          description: "Audit authd",
          tool_call_id: "delegate-auth",
        },
      });
      yield new StreamEvent({
        type: StreamEventType.SUBAGENT_ERROR,
        payload: {
          subagent: "auth-audit",
          tool_call_id: "delegate-auth",
          error_text: "delegate failed",
        },
      });
    };
    try {
      await new Promise<void>((resolve, reject) => {
        createRoot((dispose) => {
          void (async () => {
            try {
              const c = createController(new CliConfig(), ["ruflo"]);
              await c.submit("audit target");

              const subagents = c.items.filter((item) => item.kind === "subagent").map((item) => item.subagent);
              expect(subagents[0]?.status).toBe("complete");
              expect(subagents[0]?.result).toContain("portal handlers");
              expect(subagents[1]?.status).toBe("error");
              expect(subagents[1]?.error).toContain("delegate failed");

              await c.close();
              dispose();
              resolve();
            } catch (exc) {
              dispose();
              reject(exc);
            }
          })();
        });
      });
    } finally {
      Session.prototype.runTurn = originalRunTurn;
    }
  });

  test("submit keeps subagent streamed tokens inside the subagent panel", async () => {
    const originalRunTurn = Session.prototype.runTurn;
    Session.prototype.runTurn = async function* () {
      yield new StreamEvent({
        type: StreamEventType.SUBAGENT_START,
        payload: {
          subagent: "recon",
          description: "Map attack surface",
          tool_call_id: "delegate-recon",
        },
      });
      yield new StreamEvent({
        type: StreamEventType.TOKEN,
        payload: {
          subagent: "recon",
          content: "Recon found admin handlers. ",
          reasoning_content: "Looking at routing tables. ",
        },
      });
      yield new StreamEvent({
        type: StreamEventType.SUBAGENT_COMPLETE,
        payload: {
          subagent: "recon",
          tool_call_id: "delegate-recon",
          result_summary: "Compact recon summary.",
        },
      });
      yield new StreamEvent({
        type: StreamEventType.TOKEN,
        payload: { content: "Primary synthesis." },
      });
    };
    try {
      await new Promise<void>((resolve, reject) => {
        createRoot((dispose) => {
          void (async () => {
            try {
              const c = createController(new CliConfig(), ["ruflo"]);
              await c.submit("audit target");

              const subagent = c.items.find((item) => item.kind === "subagent")?.subagent;
              expect(subagent?.output).toContain("Recon found admin handlers");
              expect(subagent?.reasoning).toContain("routing tables");
              expect(subagent?.result).toContain("Compact recon summary");
              const assistantMessages = c.items
                .flatMap((item) => (item.kind === "message" && item.role === "assistant" ? [item.content] : []))
                .join("\n");
              expect(assistantMessages).toContain("Primary synthesis");
              expect(assistantMessages).not.toContain("Recon found admin handlers");

              await c.close();
              dispose();
              resolve();
            } catch (exc) {
              dispose();
              reject(exc);
            }
          })();
        });
      });
    } finally {
      Session.prototype.runTurn = originalRunTurn;
    }
  });

  test("submit records stage ownership for streamed tool calls without creating subagent cards", async () => {
    const originalRunTurn = Session.prototype.runTurn;
    Session.prototype.runTurn = async function* () {
      yield new StreamEvent({
        type: StreamEventType.STAGE_START,
        payload: {
          stage: "recon",
          description: "Map attack surface",
        },
      });
      yield new StreamEvent({
        type: StreamEventType.TOKEN,
        payload: {
          subagent: "recon",
          content: "Recon streamed to main chat. ",
          reasoning_content: "Stage reasoning. ",
        },
      });
      yield new StreamEvent({
        type: StreamEventType.TOOL_START,
        payload: {
          subagent: "recon",
          tool_name: "grep",
          tool_call_id: "grep-1",
          args_json: JSON.stringify({ pattern: "auth" }),
        },
      });
      yield new StreamEvent({
        type: StreamEventType.TOOL_RESULT,
        payload: {
          subagent: "recon",
          tool_name: "grep",
          tool_call_id: "grep-1",
          result_summary: "src/auth.ts: token check",
        },
      });
      yield new StreamEvent({
        type: StreamEventType.STAGE_COMPLETE,
        payload: {
          stage: "recon",
        },
      });
    };
    try {
      await new Promise<void>((resolve, reject) => {
        createRoot((dispose) => {
          void (async () => {
            try {
              const c = createController(new CliConfig(), ["audit"]);
              c.setWorkflow("audit");
              await c.submit("audit target");

              const toolItem = c.items.find((item) => item.kind === "tool");
              const stageItem = c.items.find((item) => item.kind === "stage");
              expect(stageItem?.kind === "stage" ? stageItem.stage.name : "").toBe("recon");
              expect(stageItem?.kind === "stage" ? stageItem.stage.status : "").toBe("complete");
              expect(toolItem?.kind === "tool" ? toolItem.tool.subagent : "").toBe("recon");
              expect(toolItem?.kind === "tool" ? toolItem.tool.result : "").toContain("token check");
              expect(c.items.some((item) => item.kind === "subagent")).toBe(false);
              const assistantMessages = c.items
                .flatMap((item) => (item.kind === "message" && item.role === "assistant" ? [item.content + item.reasoning] : []))
                .join("\n");
              expect(assistantMessages).toContain("Recon streamed to main chat");
              expect(assistantMessages).toContain("Stage reasoning");
              expect(c.stages().find((stage) => stage.name === "recon")?.status).toBe("complete");

              await c.close();
              dispose();
              resolve();
            } catch (exc) {
              dispose();
              reject(exc);
            }
          })();
        });
      });
    } finally {
      Session.prototype.runTurn = originalRunTurn;
    }
  });

  test("submit shows audit router nodes without marking them as stage rows", async () => {
    const originalRunTurn = Session.prototype.runTurn;
    Session.prototype.runTurn = async function* () {
      yield new StreamEvent({
        type: StreamEventType.STAGE_START,
        payload: {
          stage: "validate_check",
          node_kind: "router",
          description: "same-model structured router: gapfill | dedupe",
        },
      });
      yield new StreamEvent({
        type: StreamEventType.STAGE_COMPLETE,
        payload: {
          stage: "validate_check",
          node_kind: "router",
        },
      });
    };
    try {
      await new Promise<void>((resolve, reject) => {
        createRoot((dispose) => {
          void (async () => {
            try {
              const c = createController(new CliConfig(), ["audit"]);
              c.setWorkflow("audit");
              await c.submit("audit target");

              const routerItem = c.items.find((item) => item.kind === "stage" && item.stage.name === "validate_check");
              expect(routerItem?.kind === "stage" ? routerItem.stage.nodeKind : "").toBe("router");
              expect(routerItem?.kind === "stage" ? routerItem.stage.status : "").toBe("complete");
              expect(c.stages().some((stage) => stage.name === "validate_check")).toBe(false);

              await c.close();
              dispose();
              resolve();
            } catch (exc) {
              dispose();
              reject(exc);
            }
          })();
        });
      });
    } finally {
      Session.prototype.runTurn = originalRunTurn;
    }
  });

  test("submit routes implicit delegate tokens into the only running subagent", async () => {
    const originalRunTurn = Session.prototype.runTurn;
    Session.prototype.runTurn = async function* () {
      yield new StreamEvent({
        type: StreamEventType.TOOL_START,
        payload: {
          tool_name: "delegate_task",
          tool_call_id: "delegate-tester",
          args_json: JSON.stringify({ subagent_name: "tester", task: "Answer simple questions" }),
        },
      });
      yield new StreamEvent({
        type: StreamEventType.SUBAGENT_START,
        payload: {
          subagent: "tester",
          description: "Answer simple questions",
          tool_call_id: "delegate-tester",
        },
      });
      yield new StreamEvent({
        type: StreamEventType.TOKEN,
        payload: {
          content: "The answer is 4. ",
          reasoning_content: "The user is asking simple questions. ",
        },
      });
      yield new StreamEvent({
        type: StreamEventType.TOOL_RESULT,
        payload: {
          tool_name: "delegate_task",
          tool_call_id: "delegate-tester",
          result_summary: "Result: done",
        },
      });
      yield new StreamEvent({
        type: StreamEventType.SUBAGENT_COMPLETE,
        payload: {
          subagent: "tester",
          tool_call_id: "delegate-tester",
          result_summary: "Result: done",
        },
      });
      yield new StreamEvent({
        type: StreamEventType.TOKEN,
        payload: { content: "Primary summary." },
      });
    };
    try {
      await new Promise<void>((resolve, reject) => {
        createRoot((dispose) => {
          void (async () => {
            try {
              const c = createController(new CliConfig(), ["ruflo"]);
              await c.submit("quick test");

              const subagent = c.items.find((item) => item.kind === "subagent")?.subagent;
              expect(subagent?.output).toContain("The answer is 4");
              expect(subagent?.reasoning).toContain("simple questions");
              const assistantMessages = c.items
                .flatMap((item) => (item.kind === "message" && item.role === "assistant" ? [item.content + item.reasoning] : []))
                .join("\n");
              expect(assistantMessages).toContain("Primary summary");
              expect(assistantMessages).not.toContain("The answer is 4");
              expect(assistantMessages).not.toContain("simple questions");

              await c.close();
              dispose();
              resolve();
            } catch (exc) {
              dispose();
              reject(exc);
            }
          })();
        });
      });
    } finally {
      Session.prototype.runTurn = originalRunTurn;
    }
  });
});

describe("TUI controller migrated Python slash-command helpers", () => {
  test("reports status, models, graph, plugin, rag, and sessions", async () => {
    await new Promise<void>((resolve, reject) => {
      createRoot((dispose) => {
        void (async () => {
          try {
            const config = new CliConfig({
              activeModel: "primary",
              models: [
                new ProviderConfig({
                  name: "primary",
                  modelName: "gpt-4o-mini",
                  apiMode: "openai_compatible",
                  maxContextTokens: 200_000,
                  enabled: true,
                }),
              ],
              mcpServers: [
                new McpServerConfig({
                  name: "ida",
                  transport: "http",
                  url: "http://127.0.0.1:65535/mcp",
                  enabled: false,
                }),
              ],
            });
            config.rag.embeddingModel = "BAAI/bge-small-en-v1.5";
            config.rag.knowledgeBases = [
              new KnowledgeBaseConfig({
                name: "docs",
                docsPath: "/tmp/docs",
                chromaPath: "/tmp/chroma",
                enabled: true,
              }),
            ];

            const c = createController(config, ["ruflo", "audit", "audit-slim"]);
            c.newConversation();

            expect(await c.statusReport()).toContain("model: gpt-4o-mini via primary");
            expect(await c.mcpReport()).toContain("ida: http, disabled");
            expect(c.skillsReport()).toContain("skills:");
            expect(c.modelsReport()).toContain("* primary: gpt-4o-mini");
            expect(c.modelReport()).toContain("/model <name>");
            expect(c.graphReport()).toContain("workflow: ruflo");
            expect(c.pluginReport()).toContain("ida: http, disabled");
            expect(c.ragReport()).toContain("embedding_model: BAAI/bge-small-en-v1.5");
            expect(c.ragReport()).toContain("docs");
            expect(c.sessionsReport()).toContain("Ruflo session");

            await c.close();
            dispose();
            resolve();
          } catch (exc) {
            dispose();
            reject(exc);
          }
        })();
      });
    });
  });

  test("RAG TUI state saves model settings", async () => {
    await new Promise<void>((resolve, reject) => {
      createRoot((dispose) => {
        void (async () => {
          try {
            const config = new CliConfig();
            const c = createController(config, ["ruflo"]);

            c.openRag();
            c.editRagModelSettings();
            c.setRagModelField("embeddingBackend", "api");
            c.setRagModelField("embeddingModel", "text-embedding-3-small");
            c.setRagModelField("embeddingApiBase", "https://example.test/v1");
            c.setRagModelField("chunkSize", "2K");
            c.setRagModelField("chunkOverlap", "100");
            expect(await c.saveRagModelSettings()).toBeNull();

            const toml = readFileSync(paths.globalRagFile(), "utf-8");
            expect(toml).toContain('embedding_backend = "api"');
            expect(toml).toContain('embedding_model = "text-embedding-3-small"');
            expect(config.rag.chunkSize).toBe(2000);

            await c.close();
            dispose();
            resolve();
          } catch (exc) {
            dispose();
            reject(exc);
          }
        })();
      });
    });
  });

  test("RAG TUI state saves, chunks, searches, and deletes a local knowledge base", async () => {
    await new Promise<void>((resolve, reject) => {
      createRoot((dispose) => {
        void (async () => {
          try {
            const docs = join(workspace, "docs");
            mkdirSync(docs, { recursive: true });
            writeFileSync(join(docs, "auth.md"), "SQL injection in login form.", "utf-8");
            const config = new CliConfig();
            config.rag.chunkSize = 1200;
            config.rag.chunkOverlap = 100;
            const c = createController(config, ["ruflo"]);

            c.openRag();
            c.newRagKnowledgeBase();
            c.setRagKnowledgeBaseField("name", "docs");
            c.setRagKnowledgeBaseField("docsPath", docs);
            expect(await c.saveRagKnowledgeBase()).toBeNull();
            expect(readFileSync(paths.localRagFile(), "utf-8")).toContain('name = "docs"');
            expect(config.rag.knowledgeBases[0]?.name).toBe("docs");

            expect(await c.chunkSelectedRagKnowledgeBase()).toBeNull();
            expect(c.items.some((item) => item.kind === "note" && item.text.includes("Chunked RAG"))).toBe(true);

            c.setRagSearchField("query", "SQL login");
            c.setRagSearchField("knowledgeBase", "docs");
            expect(await c.runRagSearch()).toBeNull();
            expect(c.items.some((item) => item.kind === "note" && item.text.includes("RAG search results:"))).toBe(true);

            expect(await c.deleteSelectedRagKnowledgeBase()).toBeNull();
            expect(config.rag.knowledgeBases).toEqual([]);

            await c.close();
            dispose();
            resolve();
          } catch (exc) {
            dispose();
            reject(exc);
          }
        })();
      });
    });
  });

  test("RAG TUI state can save a global Chroma HTTP knowledge base", async () => {
    await new Promise<void>((resolve, reject) => {
      createRoot((dispose) => {
        void (async () => {
          try {
            const config = new CliConfig();
            const c = createController(config, ["ruflo"]);

            c.openRag();
            c.newRagKnowledgeBase();
            c.setRagKnowledgeBaseField("name", "remote");
            c.setRagKnowledgeBaseField("backend", "chroma_http");
            c.setRagKnowledgeBaseField("chromaUrl", "http://127.0.0.1:8000");
            c.setRagKnowledgeBaseField("collectionName", "docs");
            c.setRagKnowledgeBaseField("scope", "global");
            expect(await c.saveRagKnowledgeBase()).toBeNull();

            const toml = readFileSync(paths.globalRagFile(), "utf-8");
            expect(toml).toContain('name = "remote"');
            expect(toml).toContain('backend = "chroma_http"');
            expect(toml).toContain('chroma_url = "http://127.0.0.1:8000"');

            await c.close();
            dispose();
            resolve();
          } catch (exc) {
            dispose();
            reject(exc);
          }
        })();
      });
    });
  });

  test("selectModel persists the active model and refreshes modelName", async () => {
    await new Promise<void>((resolve, reject) => {
      createRoot((dispose) => {
        void (async () => {
          try {
            const config = new CliConfig({
              activeModel: "default",
              models: [
                new ProviderConfig({ name: "default", modelName: "", enabled: true }),
                new ProviderConfig({ name: "primary", modelName: "gpt-4o-mini", enabled: true }),
              ],
            });
            const c = createController(config, ["ruflo"]);

            expect(c.modelName()).toBe("(unset)");
            const result = await c.selectModel("primary");
            expect(result).toContain("selected model: primary");
            expect(config.activeModel).toBe("primary");
            expect(c.modelName()).toBe("gpt-4o-mini");

            await c.close();
            dispose();
            resolve();
          } catch (exc) {
            dispose();
            reject(exc);
          }
        })();
      });
    });
  });

  test("selectModel migrates agents pinned to the previous active model back to the default alias", async () => {
    await new Promise<void>((resolve, reject) => {
      createRoot((dispose) => {
        void (async () => {
          try {
            const config = new CliConfig({
              activeModel: "old",
              models: [
                new ProviderConfig({ name: "old", modelName: "gpt-4o-mini", enabled: true }),
                new ProviderConfig({ name: "primary", modelName: "claude-sonnet-4-6", enabled: true }),
              ],
              agents: [new AgentConfig({ name: "ruflo", model: "old" })],
            });
            const c = createController(config, ["ruflo"]);

            expect(c.modelName()).toBe("gpt-4o-mini");
            const result = await c.selectModel("primary");

            expect(result).toContain("selected model: primary");
            expect(config.activeModel).toBe("primary");
            expect(config.agents[0]?.model).toBe("default");
            expect(c.modelName()).toBe("claude-sonnet-4-6");

            await c.close();
            dispose();
            resolve();
          } catch (exc) {
            dispose();
            reject(exc);
          }
        })();
      });
    });
  });

  test("model picker selects the active row and activates another model", async () => {
    await new Promise<void>((resolve, reject) => {
      createRoot((dispose) => {
        void (async () => {
          try {
            const config = new CliConfig({
              activeModel: "default",
              models: [
                new ProviderConfig({ name: "default", modelName: "gpt-4o-mini", enabled: true }),
                new ProviderConfig({ name: "primary", modelName: "claude-sonnet-4-6", apiMode: "anthropic", enabled: true }),
              ],
            });
            const c = createController(config, ["ruflo"]);

            c.openModelPicker();
            expect(c.modelPickerOpen()).toBe(true);
            expect(c.modelPickerSelectedIndex()).toBe(0);

            c.moveModelPickerSelection(1);
            expect(c.modelPickerSelectedIndex()).toBe(1);
            const err = await c.activateModelPickerSelection();

            expect(err).toBeNull();
            expect(c.modelPickerOpen()).toBe(false);
            expect(config.activeModel).toBe("primary");
            expect(c.modelName()).toBe("claude-sonnet-4-6");

            await c.close();
            dispose();
            resolve();
          } catch (exc) {
            dispose();
            reject(exc);
          }
        })();
      });
    });
  });

  test("pluginCommand can add and persist an MCP server", async () => {
    await new Promise<void>((resolve, reject) => {
      createRoot((dispose) => {
        void (async () => {
          try {
            const c = createController(new CliConfig(), ["ruflo"]);
            const result = await c.pluginCommand("add mcp ida http://127.0.0.1:5000/mcp");

            expect(result).toContain("MCP ida enabled");
            expect(readFileSync(paths.localMcpFile(), "utf-8")).toContain('name = "ida"');
            expect(readFileSync(paths.localMcpFile(), "utf-8")).toContain('url = "http://127.0.0.1:5000/mcp"');

            await c.close();
            dispose();
            resolve();
          } catch (exc) {
            dispose();
            reject(exc);
          }
        })();
      });
    });
  });

  test("pluginCommand can add a global MCP server", async () => {
    await new Promise<void>((resolve, reject) => {
      createRoot((dispose) => {
        void (async () => {
          try {
            const c = createController(new CliConfig(), ["ruflo"]);
            const result = await c.pluginCommand("add mcp ida http://127.0.0.1:5000/mcp --global");

            expect(result).toContain("MCP ida enabled");
            expect(readFileSync(paths.globalMcpFile(), "utf-8")).toContain('name = "ida"');
            expect(readFileSync(paths.globalMcpFile(), "utf-8")).toContain('url = "http://127.0.0.1:5000/mcp"');
            if (existsSync(paths.localMcpFile())) {
              expect(readFileSync(paths.localMcpFile(), "utf-8")).not.toContain('name = "ida"');
            }

            await c.close();
            dispose();
            resolve();
          } catch (exc) {
            dispose();
            reject(exc);
          }
        })();
      });
    });
  });

  test("pluginCommand can install a SkillHub skill", async () => {
    const server = Bun.serve({
      port: 0,
      fetch(req) {
        const url = new URL(req.url);
        if (url.pathname === "/api/skills/idapython") {
          return Response.json({ name: "idapython", skill_md: "Use IDA carefully." });
        }
        return new Response("not found", { status: 404 });
      },
    });
    process.env.SARMA_SKILLSHUB_URL = `http://127.0.0.1:${server.port}`;
    try {
      await new Promise<void>((resolve, reject) => {
        createRoot((dispose) => {
          void (async () => {
            try {
              const config = new CliConfig({ agents: [new AgentConfig({ name: "ruflo", skills: [] })] });
              const c = createController(config, ["ruflo"]);
              c.setPluginSkillField("enabled", "false");

              const result = await c.pluginCommand("add skill idapython");

              expect(result).toContain("SkillHub skill idapython installed and enabled");
              expect(readFileSync(join(workspace, ".sarma", "skills", "idapython", "SKILL.md"), "utf-8")).toContain("Use IDA carefully.");
              expect(config.agents.find((agent) => agent.name === "ruflo")?.skills).toEqual(["idapython"]);

              await c.close();
              dispose();
              resolve();
            } catch (exc) {
              dispose();
              reject(exc);
            }
          })();
        });
      });
    } finally {
      server.stop(true);
    }
  });

  test("plugin TUI state can add and toggle MCP servers", async () => {
    await new Promise<void>((resolve, reject) => {
      createRoot((dispose) => {
        void (async () => {
          try {
            const config = new CliConfig();
            const c = createController(config, ["ruflo"]);

            c.openPlugin();
            expect(c.pluginOpen()).toBe(true);
            expect(c.pluginSection()).toBe("mcp");

            c.newPluginMcp();
            expect(c.pluginStep()).toBe("mcp-fields");
            c.setPluginMcpField("name", "ida");
            c.setPluginMcpField("transport", "http");
            c.setPluginMcpField("url", "http://127.0.0.1:5000/mcp");
            c.setPluginMcpField("headers", "{\"Authorization\":\"Bearer test\"}");
            c.setPluginMcpField("enabled", "true");
            expect(await c.savePluginMcp()).toBeNull();

            expect(c.pluginStep()).toBe("browse");
            expect(config.mcpServers[0]?.name).toBe("ida");
            expect(config.mcpServers[0]?.transport).toBe("http");
            expect(config.mcpServers[0]?.url).toBe("http://127.0.0.1:5000/mcp");
            expect(config.mcpServers[0]?.headers).toBe("{\"Authorization\":\"Bearer test\"}");
            expect(config.mcpServers[0]?.enabled).toBe(true);
            expect(readFileSync(paths.localMcpFile(), "utf-8")).toContain('name = "ida"');

            expect(await c.toggleSelectedPlugin()).toBeNull();
            expect(config.mcpServers[0]?.enabled).toBe(false);

            await c.close();
            dispose();
            resolve();
          } catch (exc) {
            dispose();
            reject(exc);
          }
        })();
      });
    });
  });

  test("plugin TUI state can add SSE and stdio MCP servers", async () => {
    await new Promise<void>((resolve, reject) => {
      createRoot((dispose) => {
        void (async () => {
          try {
            const config = new CliConfig();
            const c = createController(config, ["ruflo"]);

            c.newPluginMcp();
            c.setPluginMcpField("name", "remote-events");
            c.setPluginMcpField("transport", "sse");
            c.setPluginMcpField("url", "http://127.0.0.1:8000/sse");
            c.setPluginMcpField("headers", "{\"X-Test\":\"1\"}");
            expect(await c.savePluginMcp()).toBeNull();

            expect(config.mcpServers[0]?.transport).toBe("sse");
            expect(config.mcpServers[0]?.url).toBe("http://127.0.0.1:8000/sse");
            expect(config.mcpServers[0]?.headers).toBe("{\"X-Test\":\"1\"}");
            expect(config.mcpServers[0]?.command).toBe("");

            c.newPluginMcp();
            c.setPluginMcpField("name", "local-stdio");
            c.setPluginMcpField("transport", "stdio");
            c.setPluginMcpField("command", "python");
            c.setPluginMcpField("args", "[\"server.py\"]");
            c.setPluginMcpField("env", "{\"TOKEN\":\"secret\"}");
            expect(await c.savePluginMcp()).toBeNull();

            const stdio = config.mcpServers.find((server) => server.name === "local-stdio");
            expect(stdio?.transport).toBe("stdio");
            expect(stdio?.command).toBe("python");
            expect(stdio?.args).toBe("[\"server.py\"]");
            expect(stdio?.env).toBe("{\"TOKEN\":\"secret\"}");
            expect(stdio?.url).toBe("");
            expect(stdio?.headers).toBe("");

            await c.close();
            dispose();
            resolve();
          } catch (exc) {
            dispose();
            reject(exc);
          }
        })();
      });
    });
  });

  test("plugin MCP test validates the current draft before connecting", async () => {
    await new Promise<void>((resolve, reject) => {
      createRoot((dispose) => {
        void (async () => {
          try {
            const c = createController(new CliConfig(), ["ruflo"]);

            c.newPluginMcp();
            c.setPluginMcpField("name", "remote");
            c.setPluginMcpField("transport", "http");
            c.setPluginMcpField("url", "");
            expect(await c.testPluginMcp()).toBe("MCP URL is required.");

            c.setPluginMcpField("url", "http://127.0.0.1:5000/mcp");
            c.setPluginMcpField("headers", "[]");
            expect(await c.testPluginMcp()).toBe("MCP headers must be a JSON object.");

            c.setPluginMcpField("transport", "stdio");
            c.setPluginMcpField("command", "");
            expect(await c.testPluginMcp()).toBe("MCP command is required.");

            c.setPluginMcpField("command", "python");
            c.setPluginMcpField("args", "{}");
            expect(await c.testPluginMcp()).toBe("MCP args must be a JSON array.");

            c.setPluginMcpField("args", "[]");
            c.setPluginMcpField("env", "[]");
            expect(await c.testPluginMcp()).toBe("MCP env must be a JSON object.");

            await c.close();
            dispose();
            resolve();
          } catch (exc) {
            dispose();
            reject(exc);
          }
        })();
      });
    });
  });

  test("plugin TUI state toggles installed skills for the current workflow", async () => {
    await new Promise<void>((resolve, reject) => {
      createRoot((dispose) => {
        void (async () => {
          try {
            const skillDir = join(home, "skills", "idapython");
            mkdirSync(skillDir, { recursive: true });
            writeFileSync(join(skillDir, "SKILL.md"), "Use IDA carefully.", "utf-8");
            const config = new CliConfig({ agents: [new AgentConfig({ name: "ruflo", skills: [] })] });
            const c = createController(config, ["ruflo"]);

            c.openPlugin();
            c.setPluginSection("skills");
            expect(c.pluginSkillRows()).toEqual([{ name: "idapython", enabled: false }]);
            expect(await c.toggleSelectedPlugin()).toBeNull();

            expect(config.agents.find((agent) => agent.name === "ruflo")?.skills).toEqual(["idapython"]);
            expect(c.pluginSkillRows()).toEqual([{ name: "idapython", enabled: true }]);
            const agentsToml = readFileSync(paths.globalAgentsFile(), "utf-8");
            expect(agentsToml).toContain("skills =");
            expect(agentsToml).toContain('"idapython"');

            await c.close();
            dispose();
            resolve();
          } catch (exc) {
            dispose();
            reject(exc);
          }
        })();
      });
    });
  });

  test("plugin TUI state can add a local skill and enable it", async () => {
    await new Promise<void>((resolve, reject) => {
      createRoot((dispose) => {
        void (async () => {
          try {
            const config = new CliConfig({ agents: [new AgentConfig({ name: "ruflo", skills: [] })] });
            const c = createController(config, ["ruflo"]);

            c.openPlugin();
            c.setPluginSection("skills");
            c.newPluginSkill();
            expect(c.pluginStep()).toBe("skill-fields");
            c.setPluginSkillField("name", "web-audit");
            c.setPluginSkillField("prompt", "Audit web applications carefully.");
            c.setPluginSkillField("enabled", "true");
            expect(await c.savePluginSkill()).toBeNull();

            const skillFile = join(workspace, ".sarma", "skills", "web-audit", "SKILL.md");
            expect(readFileSync(skillFile, "utf-8")).toContain("Audit web applications carefully.");
            expect(config.agents.find((agent) => agent.name === "ruflo")?.skills).toEqual(["web-audit"]);
            expect(c.pluginSkillRows()).toEqual([{ name: "web-audit", enabled: true }]);

            await c.close();
            dispose();
            resolve();
          } catch (exc) {
            dispose();
            reject(exc);
          }
        })();
      });
    });
  });

  test("plugin TUI state can search SkillHub and install a skill", async () => {
    const server = Bun.serve({
      port: 0,
      fetch(req) {
        const url = new URL(req.url);
        if (url.pathname === "/api/skills/search") {
          return Response.json({
            skills: [{ name: "idapython", description: "IDA Python helpers" }],
          });
        }
        if (url.pathname === "/api/skills/idapython") {
          return Response.json({
            name: "idapython",
            skill_md: "Use IDA carefully.",
          });
        }
        return new Response("not found", { status: 404 });
      },
    });
    process.env.SARMA_SKILLSHUB_URL = `http://127.0.0.1:${server.port}`;
    try {
      await new Promise<void>((resolve, reject) => {
        createRoot((dispose) => {
          void (async () => {
            try {
              const config = new CliConfig({ agents: [new AgentConfig({ name: "ruflo", skills: [] })] });
              const c = createController(config, ["ruflo"]);

              c.openPlugin();
              c.setPluginSection("skills");
              c.newPluginSkill();
              c.setPluginSkillSearchQuery("ida");
              c.setPluginSkillField("scope", "global");
              expect(await c.searchPluginSkills()).toBeNull();
              expect(c.pluginSkillSearchRows()).toEqual([
                {
                  name: "idapython",
                  description: "IDA Python helpers",
                  installed: false,
                  enabled: false,
                },
              ]);
              expect(await c.installPluginSkill("idapython")).toBeNull();

              const skillFile = join(home, "skills", "idapython", "SKILL.md");
              expect(readFileSync(skillFile, "utf-8")).toContain("Use IDA carefully.");
              expect(existsSync(join(workspace, ".sarma", "skills", "idapython", "SKILL.md"))).toBe(false);
              expect(config.agents.find((agent) => agent.name === "ruflo")?.skills).toEqual(["idapython"]);
              expect(c.pluginSkillRows()).toEqual([{ name: "idapython", enabled: true }]);

              await c.close();
              dispose();
              resolve();
            } catch (exc) {
              dispose();
              reject(exc);
            }
          })();
        });
      });
    } finally {
      server.stop(true);
    }
  });

  test("resumeSession restores persisted chat messages", async () => {
    await new Promise<void>((resolve, reject) => {
      createRoot((dispose) => {
        void (async () => {
          try {
            const c = createController(new CliConfig(), ["ruflo"]);
            const seed = new Store();
            const cid = seed.createConversation("seeded", "gpt-test");
            seed.saveMessage(cid, "turn1", "user", "hello");
            seed.saveMessage(cid, "turn1", "assistant", "world", null, "thinking");
            seed.close();

            expect(c.resumeSession(cid)).toBe(true);
            expect(c.items.some((item) => item.kind === "message" && item.content === "hello")).toBe(true);
            expect(c.items.some((item) => item.kind === "message" && item.content === "world")).toBe(true);
            await c.close();
            dispose();
            resolve();
          } catch (exc) {
            dispose();
            reject(exc);
          }
        })();
      });
    });
  });
});
