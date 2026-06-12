import { expect, test, describe, beforeEach, afterEach } from "bun:test";
import { mkdtempSync, rmSync, writeFileSync, mkdirSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { KnowledgeBaseConfig, RagConfig } from "@/config";
import {
  chunkKnowledgeBase,
  searchKnowledgeBases,
  splitText,
  upsertKnowledgeBase,
  isChromaDatabase,
  validateChromaDatabase,
  ragKnowledgeBaseName,
  knowledgeBaseChromaPath,
  setChromaClientFactoryForTests,
} from "@/resources/rag";

let tmpHome: string;
let tmpCwd: string;
let origHome: string | undefined;
let origCwd: string;

beforeEach(() => {
  tmpHome = mkdtempSync(join(tmpdir(), "sarma-rag-home-"));
  tmpCwd = mkdtempSync(join(tmpdir(), "sarma-rag-cwd-"));
  origHome = process.env.SARMA_HOME;
  origCwd = process.cwd();
  process.env.SARMA_HOME = tmpHome;
  process.chdir(tmpCwd);
});

afterEach(() => {
  setChromaClientFactoryForTests(null);
  process.chdir(origCwd);
  if (origHome === undefined) delete process.env.SARMA_HOME;
  else process.env.SARMA_HOME = origHome;
  rmSync(tmpHome, { recursive: true, force: true });
  rmSync(tmpCwd, { recursive: true, force: true });
});

describe("splitText", () => {
  test("returns single chunk when shorter than chunkSize", () => {
    expect(splitText("short text", 100, 10)).toEqual(["short text"]);
  });

  test("splits with overlap", () => {
    const text = "a".repeat(250);
    const chunks = splitText(text, 100, 20);
    expect(chunks.length).toBeGreaterThan(1);
    // step = 80, so starts at 0, 80, 160, 240
    expect(chunks[0]!.length).toBe(100);
  });

  test("normalizes CRLF", () => {
    const chunks = splitText("line1\r\nline2", 100, 0);
    expect(chunks[0]).toBe("line1\nline2");
  });
});

describe("upsertKnowledgeBase", () => {
  test("appends new and replaces existing by name", () => {
    const list: KnowledgeBaseConfig[] = [];
    upsertKnowledgeBase(list, new KnowledgeBaseConfig({ name: "kb1", docsPath: "/a" }));
    expect(list.length).toBe(1);
    upsertKnowledgeBase(list, new KnowledgeBaseConfig({ name: "kb1", docsPath: "/b" }));
    expect(list.length).toBe(1);
    expect(list[0]!.docsPath).toBe("/b");
  });
});

describe("ragKnowledgeBaseName", () => {
  test("uses explicit name when provided", () => {
    expect(ragKnowledgeBaseName("custom", "/x/y.txt")).toBe("custom");
  });

  test("derives from directory name", () => {
    const dir = mkdtempSync(join(tmpdir(), "kbdir-"));
    try {
      expect(ragKnowledgeBaseName("", dir)).toBe(dir.split(/[\\/]/).pop()!);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });
});

describe("chunk + search (lexical fallback)", () => {
  test("chunks a docs dir and finds matching chunk", async () => {
    const docsDir = join(tmpCwd, "docs");
    mkdirSync(docsDir, { recursive: true });
    writeFileSync(join(docsDir, "notes.md"), "The vulnerability is a SQL injection in the login handler.");
    writeFileSync(join(docsDir, "other.txt"), "Unrelated content about deployment pipelines.");

    const kb = new KnowledgeBaseConfig({ name: "testkb", docsPath: docsDir, enabled: true });
    const rag = new RagConfig({ embeddingBackend: "huggingface", chunkSize: 1200, chunkOverlap: 100 });
    rag.knowledgeBases = [kb];

    const result = await chunkKnowledgeBase(kb, rag);
    expect(result.files).toBe(2);
    expect(result.chunks).toBe(2);
    expect(isChromaDatabase(result.outputPath)).toBe(true);

    const out = await searchKnowledgeBases(rag, { query: "SQL injection login", topK: 3 });
    expect(out).toContain("RAG search results:");
    expect(out).toContain("SQL injection");
    expect(out).toContain("testkb");
  });

  test("returns helpful message when no KB enabled", async () => {
    const rag = new RagConfig();
    const out = await searchKnowledgeBases(rag, { query: "anything" });
    expect(out).toContain("No enabled RAG knowledge bases");
  });

  test("rejects empty query", async () => {
    const rag = new RagConfig();
    const out = await searchKnowledgeBases(rag, { query: "   " });
    expect(out).toContain("non-empty query");
  });

  test("searches Chroma HTTP knowledge base through client adapter", async () => {
    const kb = new KnowledgeBaseConfig({
      name: "remote",
      backend: "chroma_http",
      chromaUrl: "http://127.0.0.1:8000",
      collectionName: "audit-docs",
      enabled: true,
    });
    const rag = new RagConfig({ knowledgeBases: [kb] });
    setChromaClientFactoryForTests(() => ({
      async getCollection(args: { name: string }) {
        expect(args.name).toBe("audit-docs");
        return {
          async query() {
            return {
              documents: [["Remote SQL injection notes"]],
              metadatas: [[{ source: "remote.md", chunk_index: 7 }]],
              distances: [[0.25]],
            };
          },
        };
      },
    }));

    const out = await searchKnowledgeBases(rag, { query: "SQL", topK: 1 });
    expect(out).toContain("Remote SQL injection");
    expect(out).toContain("remote.md");
    expect(out).toContain("remote");
  });
});

describe("validateChromaDatabase", () => {
  test("throws for missing directory", () => {
    expect(() => validateChromaDatabase(join(tmpCwd, "nope"))).toThrow();
  });

  test("accepts a valid chunk database", async () => {
    const docsDir = join(tmpCwd, "d");
    mkdirSync(docsDir, { recursive: true });
    writeFileSync(join(docsDir, "a.txt"), "hello world content here");
    const kb = new KnowledgeBaseConfig({ name: "vk", docsPath: docsDir, enabled: true });
    const rag = new RagConfig();
    rag.knowledgeBases = [kb];
    const result = await chunkKnowledgeBase(kb, rag);
    const info = validateChromaDatabase(result.outputPath);
    expect(info.path).toBe(result.outputPath);
    expect(existsSync(knowledgeBaseChromaPath(kb))).toBe(true);
  });

  test("rejects non-Sarma Chroma persist directories with a clear message", () => {
    const dir = join(tmpCwd, "external-chroma");
    mkdirSync(dir, { recursive: true });
    writeFileSync(join(dir, "chroma.sqlite3"), "");
    expect(() => validateChromaDatabase(dir)).toThrow(/not a Sarma native chunk database/);
  });
});
