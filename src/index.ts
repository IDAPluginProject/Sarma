#!/usr/bin/env bun
/** Sarma CLI entrypoint (TypeScript / LangChain.js port). */

import yargs from "yargs";
import { hideBin } from "yargs/helpers";
import { loadConfig, initConfig } from "@/config";
import { runInteractive, runOneshot, sessionsCommand, workflowCommand } from "@/cli/app";
import { ragCommand } from "@/cli/ragCommand";
import { printInfo } from "@/cli/renderer";
import { installDebugHandlers } from "@/debug";
import pc from "picocolors";

installDebugHandlers();

async function main(): Promise<void> {
  await yargs(hideBin(process.argv))
    .scriptName("sarma")
    .usage("$0 [options]", "Sarma — AI-powered vulnerability audit agent (CLI).")
    .option("message", {
      alias: "c",
      type: "string",
      describe: "Single message (non-interactive).",
    })
    .option("workflow", {
      alias: "w",
      type: "string",
      describe: "Workflow to run (ruflo | audit | audit-slim).",
    })
    .option("plain", {
      type: "boolean",
      default: false,
      describe: "Use the plain line-based REPL instead of the full-screen TUI.",
    })
    .command(
      "$0",
      "Start Sarma (full-screen TUI, or one-shot with -c).",
      () => {},
      async (argv) => {
        const config = loadConfig();
        if (argv.message) {
          await runOneshot(config, argv.message as string, argv.workflow as string | undefined);
        } else if (argv.plain) {
          await runInteractive(config, argv.workflow as string | undefined);
        } else {
          // Register the SolidJS .tsx transform before loading any TUI module.
          // bunfig preload is cwd-relative, so we do it explicitly here to work
          // regardless of where `sarma` is invoked from.
          const { ensureSolidTransformPlugin } = await import("@opentui/solid/bun-plugin");
          ensureSolidTransformPlugin();
          const { runTui } = await import("@/tui/index");
          await runTui(config, argv.workflow as string | undefined);
        }
      },
    )
    .command(
      "init",
      "Initialize Sarma config files.",
      (y) => y.option("local", { type: "boolean", default: false, describe: "Ensure workspace dirs only." }),
      (argv) => {
        const { global, workspace } = initConfig(Boolean(argv.local));
        if (!argv.local) printInfo(`${pc.green("Global config ready:")} ${pc.cyan(global)}`);
        printInfo(`${pc.green("Workspace config ready:")} ${pc.cyan(workspace)}`);
      },
    )
    .command(
      "workflow [name]",
      "List available workflows or show how to switch.",
      (y) => y.positional("name", { type: "string", describe: "Workflow name." }),
      (argv) => workflowCommand(argv.name as string | undefined),
    )
    .command(
      "sessions",
      "List saved Sarma sessions.",
      (y) => y.option("limit", { type: "number", default: 20, describe: "Maximum sessions to show." }),
      (argv) => sessionsCommand(argv.limit as number),
    )
    .command(
      "resume <sessionId>",
      "Resume a saved Sarma session in the full-screen TUI.",
      (y) => y.positional("sessionId", { type: "string", describe: "Session id from `sarma sessions`." }),
      async (argv) => {
        const config = loadConfig();
        const { ensureSolidTransformPlugin } = await import("@opentui/solid/bun-plugin");
        ensureSolidTransformPlugin();
        const { runTui } = await import("@/tui/index");
        await runTui(config, argv.workflow as string | undefined, argv.sessionId as string);
      },
    )
    .command(
      "rag",
      "Manage RAG config, chunk documents, or register a database.",
      (y) =>
        y
          .option("model", { type: "string", describe: "Set the RAG embedding model name." })
          .option("backend", { choices: ["huggingface", "api"] as const, describe: "Set the embedding backend." })
          .option("api-base", { type: "string", describe: "Set the embedding API base URL." })
          .option("api-key", { type: "string", describe: "Set the embedding API key." })
          .option("local-path", { type: "string", describe: "Set the local model path." })
          .option("split", { type: "string", describe: "Chunk documents from this file or directory." })
          .option("add", { type: "string", describe: "Register an existing database directory." })
          .option("name", { type: "string", describe: "Knowledge base name (defaults to path name)." })
          .option("collection", { type: "string", describe: "Chroma collection name when --add is a server URL." })
          .option("chroma-path", { type: "string", describe: "Database output path for --split." })
          .option("global", { type: "boolean", default: false, describe: "Register KB in global rag.toml." }),
      async (argv) => {
        await ragCommand({
          embeddingModel: argv.model as string | undefined,
          embeddingBackend: argv.backend as "huggingface" | "api" | undefined,
          apiBase: argv["api-base"] as string | undefined,
          apiKey: argv["api-key"] as string | undefined,
          localPath: argv["local-path"] as string | undefined,
          split: argv.split as string | undefined,
          add: argv.add as string | undefined,
          name: argv.name as string | undefined,
          collection: argv.collection as string | undefined,
          chromaPath: argv["chroma-path"] as string | undefined,
          global: argv.global as boolean | undefined,
        });
      },
    )
    .strict()
    .help()
    .alias("help", "h")
    .version("0.1.2")
    .parseAsync();
}

await main();
