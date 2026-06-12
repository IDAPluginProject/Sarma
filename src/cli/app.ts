/** Application run loops for the Sarma CLI. */

import * as readline from "node:readline";
import { type CliConfig } from "@/config";
import { RuntimePolicyResolver } from "@/runtime/resolver";
import { Session } from "@/session";
import { Store } from "@/store";
import { StreamPrinter, handleEvent, printError, printInfo } from "@/cli/renderer";
import { getWorkflowMeta, listWorkflowMetas, defaultWorkflowName } from "@/workflows";
import pc from "picocolors";

/** Run a single message and exit (non-interactive). */
export async function runOneshot(config: CliConfig, message: string, workflow?: string): Promise<void> {
  const resolver = new RuntimePolicyResolver(config);
  const mode = workflow || defaultWorkflowName();
  if (!getWorkflowMeta(mode)) {
    printError(`Unknown workflow: ${mode}`);
    return;
  }
  if (!resolver.providerFor(mode).modelName) {
    printError("No model configured. Run `sarma init` and edit models.toml.");
    return;
  }

  const store = new Store();
  const session = new Session(config, store);
  session.setWorkflow(mode);

  try {
    await runTurnStreaming(session, message);
  } catch (exc) {
    printError(exc instanceof Error ? exc.message : String(exc));
  } finally {
    await session.close();
    store.close();
  }
}

export function sessionsCommand(limit = 20): void {
  const store = new Store();
  try {
    const rows = store.listConversations(limit);
    if (rows.length === 0) {
      printInfo("sessions:\n  (no sessions yet)");
      return;
    }
    const lines = ["sessions:"];
    for (const row of rows) {
      const title = row.title || "Untitled session";
      const model = row.model_name || "(unset)";
      lines.push(`  ${row.id}  ${title}  [${model}, ${row.status}, ${new Date(row.updated_at).toLocaleString()}]`);
    }
    printInfo(lines.join("\n"));
  } finally {
    store.close();
  }
}

async function runTurnStreaming(session: Session, message: string): Promise<void> {
  const printer = new StreamPrinter();
  for await (const event of session.runTurn(message)) {
    handleEvent(event, printer);
  }
  printer.flush();
}

/** Minimal interactive REPL (line-based; no full-screen TUI). */
export async function runInteractive(config: CliConfig, workflow?: string): Promise<void> {
  const resolver = new RuntimePolicyResolver(config);
  const mode = workflow || defaultWorkflowName();
  if (!getWorkflowMeta(mode)) {
    printError(`Unknown workflow: ${mode}`);
    return;
  }
  if (!resolver.providerFor(mode).modelName) {
    printError("No model configured. Run `sarma init` and edit models.toml.");
    return;
  }

  const store = new Store();
  const session = new Session(config, store);
  session.setWorkflow(mode);

  printInfo(pc.bold("Sarma") + pc.dim(" — interactive mode. Type /help for commands, /exit to quit."));
  printInfo(pc.dim(`workflow: ${session.workflow}`));

  const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
  const prompt = () => rl.setPrompt(pc.cyan(`${session.workflow} ❯ `));
  prompt();
  rl.prompt();

  const close = async () => {
    const sessionId = session.conversationId;
    rl.close();
    await session.close();
    store.close();
    if (sessionId) {
      printInfo(pc.dim(`session: ${sessionId}`));
      printInfo(pc.dim(`resume: sarma resume ${sessionId}`));
    }
  };

  for await (const line of rl) {
    const text = line.trim();
    if (!text) {
      rl.prompt();
      continue;
    }
    if (text.startsWith("/")) {
      const done = await handleSlashCommand(text, session);
      if (done) break;
      prompt();
      rl.prompt();
      continue;
    }
    try {
      await runTurnStreaming(session, text);
    } catch (exc) {
      printError(exc instanceof Error ? exc.message : String(exc));
    }
    prompt();
    rl.prompt();
  }

  await close();
}

/** Returns true when the REPL should exit. */
async function handleSlashCommand(text: string, session: Session): Promise<boolean> {
  const [cmd, ...rest] = text.slice(1).split(/\s+/);
  const arg = rest.join(" ").trim();

  switch (cmd) {
    case "exit":
      return true;
    case "help":
      printInfo(
        [
          pc.bold("Commands:"),
          "  /workflow [name]  list or switch workflow",
          "  /clear            start a new session",
          "  /exit             quit",
        ].join("\n"),
      );
      return false;
    case "workflow":
      if (!arg) {
        const current = session.workflow;
        printInfo(pc.bold("Available Workflows:"));
        for (const wf of listWorkflowMetas()) {
          const marker = wf.name === current ? pc.cyan("*") : pc.dim("-");
          printInfo(`  ${marker} ${pc.cyan(wf.name.padEnd(10))} ${wf.description}`);
        }
      } else if (listWorkflowMetas().some((w) => w.name === arg)) {
        session.setWorkflow(arg);
        printInfo(`${pc.green("Switched to")} ${pc.cyan(arg)} workflow`);
      } else {
        printError(`Unknown workflow: ${arg}`);
      }
      return false;
    case "clear":
      session.newConversation();
      printInfo(pc.dim(`Started session ${session.conversationId}.`));
      return false;
    default:
      printError(`Unknown command: /${cmd}`);
      return false;
  }
}

/** Print the workflow list or switch the default (for `sarma workflow`). */
export function workflowCommand(name?: string): void {
  if (!name) {
    printInfo(pc.bold("Available Workflows:"));
    const current = defaultWorkflowName();
    for (const wf of listWorkflowMetas()) {
      const marker = wf.name === current ? pc.cyan("*") : pc.dim("-");
      printInfo(`  ${marker} ${pc.cyan(wf.name.padEnd(10))} ${wf.description}`);
    }
    return;
  }
  if (listWorkflowMetas().some((w) => w.name === name)) {
    printInfo(`${pc.green("Use")} ${pc.cyan(`sarma -c "..." --workflow ${name}`)} ${pc.green("to run this workflow.")}`);
  } else {
    printError(`Unknown workflow: ${name}`);
    process.exitCode = 1;
  }
}
