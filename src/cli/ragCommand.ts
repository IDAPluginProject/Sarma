/** `sarma rag` command — manage RAG config, chunk docs, register databases. */

import { resolve } from "node:path";
import { existsSync } from "node:fs";
import pc from "picocolors";
import {
  KnowledgeBaseConfig,
  loadConfig,
  loadGlobalRagConfig,
  loadLocalRagConfig,
  saveRagKnowledgeBases,
  saveRagModel,
} from "@/config";
import {
  chunkKnowledgeBase,
  ragKnowledgeBaseName,
  upsertKnowledgeBase,
  validateChromaDatabase,
  knowledgeBaseChromaPath,
} from "@/resources/rag";
import { printError, printInfo } from "@/cli/renderer";

export interface RagCommandArgs {
  embeddingModel?: string;
  embeddingBackend?: "huggingface" | "api";
  apiBase?: string;
  apiKey?: string;
  localPath?: string;
  split?: string;
  add?: string;
  name?: string;
  collection?: string;
  chromaPath?: string;
  global?: boolean;
}

export async function ragCommand(args: RagCommandArgs): Promise<void> {
  const config = loadConfig();
  let modelChanged = false;
  let kbChanged = false;
  const globalScope = Boolean(args.global);
  const kbScope = globalScope ? "global" : "local";
  const scopedRag = globalScope ? loadGlobalRagConfig() : loadLocalRagConfig();

  if (args.embeddingModel !== undefined) {
    config.rag.embeddingModel = args.embeddingModel.trim();
    modelChanged = true;
  }
  if (args.embeddingBackend !== undefined) {
    config.rag.embeddingBackend = args.embeddingBackend;
    modelChanged = true;
  }
  if (args.apiBase !== undefined) {
    config.rag.embeddingApiBase = args.apiBase.trim();
    modelChanged = true;
  }
  if (args.apiKey !== undefined) {
    config.rag.embeddingApiKey = args.apiKey.trim();
    modelChanged = true;
  }
  if (args.localPath !== undefined) {
    config.rag.embeddingLocalPath = args.localPath.trim();
    modelChanged = true;
  }

  if (args.split !== undefined) {
    const splitPath = resolve(args.split);
    if (!existsSync(splitPath)) {
      printError(`Path does not exist: ${splitPath}`);
      process.exitCode = 1;
      return;
    }
    const kbName = ragKnowledgeBaseName(args.name ?? "", splitPath);
    const existing = scopedRag.knowledgeBases.find((kb) => kb.name === kbName);
    const kb = new KnowledgeBaseConfig({
      name: kbName,
      docsPath: splitPath,
      chromaPath: args.chromaPath ? resolve(args.chromaPath) : existing?.chromaPath ?? "",
      enabled: true,
    });
    upsertKnowledgeBase(scopedRag.knowledgeBases, kb);
    // Search the merged config so embedding settings just set are applied.
    config.rag.knowledgeBases = scopedRag.knowledgeBases;
    const result = await chunkKnowledgeBase(kb, config.rag);
    kbChanged = true;
    printInfo(
      `${pc.green("Chunked")} ${pc.cyan(String(result.files))} file(s) into ` +
        `${pc.cyan(String(result.chunks))} chunk(s): ${pc.cyan(result.outputPath)}`,
    );
  }

  if (args.add !== undefined) {
    if (/^https?:\/\//i.test(args.add.trim())) {
      const collection = (args.collection ?? args.name ?? "").trim();
      if (!collection) {
        printError("Registering a Chroma server requires --collection or --name.");
        process.exitCode = 1;
        return;
      }
      const kbName = (args.name ?? collection).trim();
      const existing = scopedRag.knowledgeBases.find((kb) => kb.name === kbName);
      const kb = new KnowledgeBaseConfig({
        name: kbName,
        backend: "chroma_http",
        chromaUrl: args.add.trim(),
        collectionName: collection,
        docsPath: existing?.docsPath ?? "",
        enabled: true,
      });
      upsertKnowledgeBase(scopedRag.knowledgeBases, kb);
      kbChanged = true;
      printInfo(`${pc.green("Registered")} Chroma collection ${pc.cyan(collection)} at ${pc.cyan(kb.chromaUrl)}`);
    } else {
      const addPath = resolve(args.add);
      let info;
      try {
        info = validateChromaDatabase(addPath);
      } catch (exc) {
        printError(exc instanceof Error ? exc.message : String(exc));
        process.exitCode = 1;
        return;
      }
      const kbName = ragKnowledgeBaseName(args.name ?? "", addPath);
      const existing = scopedRag.knowledgeBases.find((kb) => kb.name === kbName);
      const kb = new KnowledgeBaseConfig({
        name: kbName,
        backend: "sarma_native",
        docsPath: existing?.docsPath ?? "",
        chromaPath: addPath,
        enabled: true,
      });
      upsertKnowledgeBase(scopedRag.knowledgeBases, kb);
      kbChanged = true;
      printInfo(`${pc.green("Registered")} database for ${pc.cyan(kbName)}: ${pc.cyan(info.path)}`);
    }
  }

  const savedPaths: string[] = [];
  if (modelChanged) savedPaths.push(saveRagModel(config));
  if (kbChanged) savedPaths.push(saveRagKnowledgeBases(scopedRag.knowledgeBases, kbScope));
  if (savedPaths.length > 0) {
    for (const path of savedPaths) printInfo(`${pc.green("Saved")} ${pc.cyan(path)}`);
    return;
  }

  // No mutations: print current RAG status.
  printRagStatus(config.rag);
}

function printRagStatus(rag: ReturnType<typeof loadConfig>["rag"]): void {
  printInfo(pc.bold("RAG"));
  printInfo(`  embedding_backend: ${pc.cyan(rag.embeddingBackend)}`);
  printInfo(`  embedding_model: ${pc.cyan(rag.embeddingModel || "(unset)")}`);
  printInfo(`  embedding_api_base: ${pc.cyan(rag.embeddingApiBase || "(unset)")}`);
  printInfo(`  embedding_local_path: ${pc.cyan(rag.embeddingLocalPath || "(default)")}`);
  printInfo(`  chunk_size: ${pc.cyan(String(rag.chunkSize))}  chunk_overlap: ${pc.cyan(String(rag.chunkOverlap))}`);
  if (rag.knowledgeBases.length === 0) {
    printInfo(`  knowledge_bases: ${pc.dim("(none)")}`);
    return;
  }
  printInfo("  knowledge_bases:");
  for (const kb of rag.knowledgeBases) {
    const marker = kb.enabled ? pc.green("enabled") : pc.dim("disabled");
    const chroma = knowledgeBaseChromaPath(kb);
    const target = kb.backend === "chroma_http" ? `${kb.chromaUrl} collection=${kb.collectionName || kb.name}` : chroma;
    printInfo(
      `    - ${pc.cyan(kb.name)} ${marker} backend=${kb.backend} docs=${kb.docsPath || "(default)"} chroma=${target}`,
    );
  }
}
