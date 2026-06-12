/** Launch the full-screen Sarma TUI. */

import { render } from "@opentui/solid";
import { createCliRenderer } from "@opentui/core";
import type { CliConfig } from "@/config";
import { listWorkflowMetas } from "@/workflows";
import { createController } from "@/tui/controller";
import { App } from "@/tui/app";
import { theme } from "@/tui/theme";
import { debugLog } from "@/debug";
import { printInfo } from "@/cli/renderer";
import pc from "picocolors";

export interface RawCtrlCExitHandler {
  handleInput: (sequence: string) => boolean;
  dispose: () => void;
}

export function createRawCtrlCExitHandler(onExit: () => void, windowMs = 1000): RawCtrlCExitHandler {
  let armed = false;
  let timer: ReturnType<typeof setTimeout> | undefined;

  const clearTimer = () => {
    if (timer) clearTimeout(timer);
    timer = undefined;
  };

  return {
    handleInput(sequence: string): boolean {
      if (sequence !== "\u0003") return false;
      if (armed) {
        armed = false;
        clearTimer();
        onExit();
      } else {
        armed = true;
        clearTimer();
        timer = setTimeout(() => {
          armed = false;
          timer = undefined;
        }, windowMs);
      }
      return true;
    },
    dispose(): void {
      clearTimer();
      armed = false;
    },
  };
}

export async function runTui(config: CliConfig, workflow?: string, resumeSessionId?: string): Promise<void> {
  const workflowNames = listWorkflowMetas().map((w) => w.name);
  const controller = createController(config, workflowNames);
  if (workflow && workflowNames.includes(workflow)) controller.setWorkflow(workflow);
  if (resumeSessionId) {
    if (!controller.resumeSession(resumeSessionId)) {
      controller.note(`session ${resumeSessionId} not found`);
    }
  } else {
    controller.note("Welcome to Sarma. Type a request.");
  }

  const renderer = await createCliRenderer({
    backgroundColor: theme.background,
    exitOnCtrlC: false,
    useMouse: true,
    autoFocus: true,
  });

  await new Promise<void>((resolve, reject) => {
    let cleanupStarted = false;
    let cleanupPromise: Promise<void> | null = null;
    const rawCtrlC = createRawCtrlCExitHandler(() => requestExit());

    const cleanup = (destroyRenderer: boolean, error?: unknown): void => {
      if (error) debugLog("TUI render loop failed", error);
      if (!cleanupPromise) {
        cleanupStarted = true;
        rawCtrlC.dispose();
        process.off("SIGINT", onSignal);
        process.off("SIGTERM", onSignal);
        renderer.removeInputHandler(rawCtrlC.handleInput);
        if (destroyRenderer && !renderer.isDestroyed) {
          renderer.destroy();
        }
        cleanupPromise = controller.close();
      }
      void cleanupPromise.then(
        () => {
          if (error) reject(error);
          else resolve();
        },
        (closeError) => {
          debugLog("TUI cleanup failed", closeError);
          reject(error ?? closeError);
        },
      );
    };

    const requestExit = () => cleanup(true);

    // Ctrl-C is handled in-app (exitOnCtrlC:false), but SIGINT/SIGTERM from the
    // terminal or a kill must still flush the store and disconnect MCP clients
    // rather than leaving orphaned child processes and a half-written DB.
    const onSignal = () => requestExit();
    process.once("SIGINT", onSignal);
    process.once("SIGTERM", onSignal);
    renderer.prependInputHandler(rawCtrlC.handleInput);
    renderer.once("destroy", () => {
      if (!cleanupStarted) cleanup(false);
    });

    void render(() => App({ controller, onExit: requestExit }), renderer).catch((exc) => cleanup(true, exc));
  });

  const sessionId = controller.sessionId();
  if (sessionId) {
    printInfo(pc.dim(`session: ${sessionId}`));
    printInfo(pc.dim(`resume: sarma resume ${sessionId}`));
  }
}
