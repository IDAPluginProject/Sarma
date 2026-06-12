/**
 * Local RAG knowledge base helpers.
 *
 * Port note: the Python implementation uses Chroma + HuggingFace/OpenAI
 * embeddings. This TypeScript port keeps the same on-disk contract — a
 * persist directory containing `chroma.sqlite3` — but stores chunks and
 * embeddings in a `bun:sqlite` database (the same engine used by store.ts).
 * The "api" embedding backend uses @langchain/openai; with no embeddings
 * configured, search falls back to lexical scoring.
 */

import { existsSync, mkdirSync, rmSync, readFileSync, readdirSync, statSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, extname, join, resolve, basename } from "node:path";
import { Database } from "bun:sqlite";
import { tool } from "@langchain/core/tools";
import type { StructuredToolInterface } from "@langchain/core/tools";
import { z } from "zod";

import * as paths from "@/paths";

export interface KnowledgeBaseSettings {
  name: string;
  docsPath: string;
  chromaPath: string;
  backend: string;
  chromaUrl: string;
  collectionName: string;
  tenant: string;
  database: string;
  headers: string;
  enabled: boolean;
}

export interface RagSettings {
  embeddingBackend: string;
  embeddingModel: string;
  embeddingApiBase: string;
  embeddingApiKey: string;
  embeddingLocalPath: string;
  chunkSize: number;
  chunkOverlap: number;
  knowledgeBases: KnowledgeBaseSettings[];
}

const TEXT_SUFFIXES = new Set([
  ".bat", ".c", ".cfg", ".conf", ".cpp", ".css", ".go", ".h", ".hpp", ".htm",
  ".html", ".ini", ".java", ".js", ".json", ".log", ".lua", ".md", ".markdown",
  ".php", ".ps1", ".py", ".rs", ".sh", ".sql", ".toml", ".ts", ".txt", ".xml",
  ".yaml", ".yml",
]);

const CHUNK_SCHEMA = `
CREATE TABLE IF NOT EXISTS chunks (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    knowledge_base  TEXT NOT NULL DEFAULT '',
    source          TEXT NOT NULL DEFAULT '',
    chunk_index     INTEGER NOT NULL DEFAULT 0,
    text            TEXT NOT NULL DEFAULT '',
    embedding_json  TEXT,
    embedding_model TEXT NOT NULL DEFAULT ''
);
`;

export interface ChunkResult {
  files: number;
  chunks: number;
  outputPath: string;
}

export interface PullResult {
  model: string;
  path: string;
}

export interface ChunkDatabaseInfo {
  path: string;
  records: number;
}

interface ChunkDocument {
  text: string;
  metadata: {
    knowledge_base: string;
    embedding_model: string;
    source: string;
    chunk_index: number;
  };
}

type SearchHit = [text: string, metadata: Record<string, unknown>, score: number | null];

type ChromaClientLike = {
  getCollection(args: { name: string; embeddingFunction?: unknown }): Promise<unknown>;
};

let chromaClientFactory: ((kb: KnowledgeBaseSettings) => ChromaClientLike) | null = null;

export function setChromaClientFactoryForTests(factory: ((kb: KnowledgeBaseSettings) => ChromaClientLike) | null): void {
  chromaClientFactory = factory;
}

export function upsertKnowledgeBase(
  knowledgeBases: KnowledgeBaseSettings[],
  knowledgeBase: KnowledgeBaseSettings,
): void {
  const index = knowledgeBases.findIndex((kb) => kb.name === knowledgeBase.name);
  if (index >= 0) knowledgeBases[index] = knowledgeBase;
  else knowledgeBases.push(knowledgeBase);
}

export async function chunkKnowledgeBase(
  kb: KnowledgeBaseSettings,
  rag: RagSettings,
): Promise<ChunkResult> {
  const root = knowledgeBaseDocsPath(kb);
  if (!existsSync(root)) {
    throw new Error(`Knowledge base docs directory does not exist. Put files under: ${root}`);
  }

  const files = iterTextFiles(root);
  const outputPath = knowledgeBaseChromaPath(kb);
  mkdirSync(dirname(outputPath), { recursive: true });
  if (existsSync(outputPath)) rmSync(outputPath, { recursive: true, force: true });

  const documents: ChunkDocument[] = [];
  for (const filePath of files) {
    const text = readText(filePath);
    if (!text.trim()) continue;
    const chunks = splitText(text, rag.chunkSize, rag.chunkOverlap);
    for (let index = 0; index < chunks.length; index++) {
      documents.push({
        text: chunks[index]!,
        metadata: {
          knowledge_base: kb.name,
          embedding_model: rag.embeddingModel,
          source: filePath,
          chunk_index: index,
        },
      });
    }
  }

  if (documents.length > 0) {
    await writeChunkDocuments(kb, rag, documents, outputPath);
  }

  return { files: files.length, chunks: documents.length, outputPath };
}

/** Build the configured embedding model, or null when none is usable. */
export function buildEmbeddingModel(rag: RagSettings): EmbeddingModel | null {
  const backend = rag.embeddingBackend.trim().toLowerCase() || "huggingface";
  const modelName = embeddingModelName(rag);
  if (!modelName) return null;

  if (backend === "api") {
    return new OpenAIEmbeddingAdapter(rag);
  }
  // The HuggingFace local backend has no Bun-native runtime here; callers fall
  // back to lexical search. Returning null signals "no vectors available".
  return null;
}

export function pullEmbeddingModel(_rag: RagSettings): PullResult {
  throw new Error(
    "Local HuggingFace model pulling is not supported in the TypeScript port. " +
      "Use the 'api' embedding backend (set rag.embedding_backend = \"api\").",
  );
}

export function buildRagSearchTool(rag: RagSettings): StructuredToolInterface {
  return tool(
    async ({ query, knowledge_base = "", top_k = 5 }: {
      query: string;
      knowledge_base?: string;
      top_k?: number;
    }): Promise<string> => {
      return searchKnowledgeBases(rag, { query, knowledgeBase: knowledge_base, topK: top_k });
    },
    {
      name: "rag_search",
      description:
        "Search chunked local RAG knowledge bases. knowledge_base is optional " +
        "(empty searches all enabled bases); top_k caps the number of chunks returned.",
      schema: z.object({
        query: z.string().describe("Search query."),
        knowledge_base: z.string().optional().describe("Optional knowledge base name."),
        top_k: z.number().int().optional().describe("Max matching chunks to return."),
      }),
    },
  ) as unknown as StructuredToolInterface;
}

export async function searchKnowledgeBases(
  rag: RagSettings,
  options: { query: string; knowledgeBase?: string; topK?: number },
): Promise<string> {
  const query = options.query.trim();
  if (!query) return "RAG search requires a non-empty query.";

  const requested = (options.knowledgeBase ?? "").trim();
  const topK = options.topK ?? 5;
  let enabled = rag.knowledgeBases.filter((kb) => kb.enabled && kb.name);
  if (requested) enabled = enabled.filter((kb) => kb.name === requested);
  if (enabled.length === 0) return "No enabled RAG knowledge bases matched the request.";

  const results: SearchHit[] = [];
  for (const kb of enabled) {
    if (kb.backend === "chroma_http") {
      results.push(...(await searchChromaHttpKnowledgeBase(kb, query, topK)));
    } else {
      const chromaPath = knowledgeBaseChromaPath(kb);
      if (!isChromaDatabase(chromaPath)) continue;
      results.push(...(await searchChunkDatabase(kb, rag, query, topK)));
    }
  }
  if (results.length === 0) {
    return "No RAG database results found. Run `chunk` on the knowledge base first.";
  }

  // Higher score = better. Sort descending; lexical/cosine both produce scores.
  results.sort((a, b) => (b[2] ?? 0) - (a[2] ?? 0));
  const limit = Math.max(1, Math.min(Math.trunc(topK || 5), 10));
  const top = results.slice(0, limit);

  const parts = ["RAG search results:"];
  top.forEach((hit, i) => {
    const [text, metadata, score] = hit;
    const source = String(metadata.source ?? "unknown");
    const kbName = String(metadata.knowledge_base ?? "");
    const chunkIndex = metadata.chunk_index ?? "?";
    const scoreText = score === null ? "" : ` score=${score.toFixed(4)}`;
    parts.push(
      `\n[${i + 1}] knowledge_base=${kbName}${scoreText} source=${source} chunk=${chunkIndex}\n${snippet(text)}`,
    );
  });
  return parts.join("\n");
}

export function validateChromaDatabase(path: string): ChunkDatabaseInfo {
  if (!existsSync(path) || !statSync(path).isDirectory()) {
    throw new Error(`RAG database directory not found: ${path}`);
  }
  if (!isChromaDatabase(path)) {
    throw new Error("RAG database must be a persist directory containing chroma.sqlite3.");
  }
  let db: Database | null = null;
  try {
    db = new Database(join(path, "chroma.sqlite3"), { readonly: true });
    const row = db.query("SELECT COUNT(*) AS count FROM chunks").get() as { count: number };
    return { path, records: Number(row.count) || 0 };
  } catch (exc) {
    const detail = exc instanceof Error ? exc.message : String(exc);
    throw new Error(
      "RAG database is not a Sarma native chunk database. " +
        "For an external Chroma database, run a Chroma server for that path " +
        "and register its URL with `sarma rag --add http://host:port --collection <name>`. " +
        `Details: ${detail}`,
    );
  } finally {
    db?.close();
  }
}

// -- path helpers --

export function knowledgeBaseDocsDir(name: string): string {
  return join(paths.ragDocsDir(), safeName(name));
}

export function knowledgeBaseDocsPath(kb: KnowledgeBaseSettings): string {
  if (kb.docsPath.trim()) return expandUser(kb.docsPath);
  return knowledgeBaseDocsDir(kb.name);
}

export function knowledgeBaseChromaPath(kb: KnowledgeBaseSettings): string {
  if (kb.chromaPath.trim()) return expandUser(kb.chromaPath);
  return join(paths.ragChromaDir(), safeName(kb.name));
}

export function isChromaDatabase(path: string): boolean {
  return (
    existsSync(path) &&
    statSync(path).isDirectory() &&
    existsSync(join(path, "chroma.sqlite3")) &&
    statSync(join(path, "chroma.sqlite3")).isFile()
  );
}

export function embeddingModelLocalPath(rag: RagSettings): string {
  if (rag.embeddingLocalPath.trim()) return expandUser(rag.embeddingLocalPath);
  return join(paths.ragModelsDir(), safeName(rag.embeddingModel));
}

// -- internals --

interface EmbeddingModel {
  embedDocuments(texts: string[]): Promise<number[][]>;
  embedQuery(text: string): Promise<number[]>;
}

class OpenAIEmbeddingAdapter implements EmbeddingModel {
  private impl: { embedDocuments(t: string[]): Promise<number[][]>; embedQuery(t: string): Promise<number[]> } | null =
    null;
  constructor(private readonly rag: RagSettings) {}

  private async load() {
    if (this.impl) return this.impl;
    const { OpenAIEmbeddings } = await import("@langchain/openai");
    const cfg: Record<string, unknown> = { model: this.rag.embeddingModel };
    if (this.rag.embeddingApiKey) cfg.apiKey = this.rag.embeddingApiKey;
    if (this.rag.embeddingApiBase) cfg.configuration = { baseURL: this.rag.embeddingApiBase };
    this.impl = new OpenAIEmbeddings(cfg) as unknown as typeof this.impl;
    return this.impl!;
  }

  async embedDocuments(texts: string[]): Promise<number[][]> {
    return (await this.load()).embedDocuments(texts);
  }
  async embedQuery(text: string): Promise<number[]> {
    return (await this.load()).embedQuery(text);
  }
}

function embeddingModelName(rag: RagSettings): string {
  if (rag.embeddingBackend.trim().toLowerCase() === "huggingface") {
    const localPath = embeddingModelLocalPath(rag);
    if (existsSync(localPath)) return localPath;
  }
  return rag.embeddingModel.trim();
}

function openChunkDb(persistDirectory: string): Database {
  mkdirSync(persistDirectory, { recursive: true });
  const db = new Database(join(persistDirectory, "chroma.sqlite3"));
  db.run("PRAGMA journal_mode = WAL;");
  db.run(CHUNK_SCHEMA);
  return db;
}

async function writeChunkDocuments(
  kb: KnowledgeBaseSettings,
  rag: RagSettings,
  records: ChunkDocument[],
  persistDirectory: string,
): Promise<void> {
  const db = openChunkDb(persistDirectory);
  try {
    db.run("DELETE FROM chunks WHERE knowledge_base = ?", [kb.name]);

    const embedder = buildEmbeddingModel(rag);
    let embeddings: (number[] | null)[] = records.map(() => null);
    if (embedder) {
      embeddings = await embedder.embedDocuments(records.map((r) => r.text));
    }

    const insert = db.query(
      "INSERT INTO chunks (knowledge_base, source, chunk_index, text, embedding_json, embedding_model) " +
        "VALUES (?, ?, ?, ?, ?, ?)",
    );
    const tx = db.transaction((rows: ChunkDocument[]) => {
      rows.forEach((record, i) => {
        const vec = embeddings[i] ?? null;
        insert.run(
          record.metadata.knowledge_base,
          record.metadata.source,
          record.metadata.chunk_index,
          record.text,
          vec ? JSON.stringify(vec) : null,
          rag.embeddingModel,
        );
      });
    });
    tx(records);
  } finally {
    db.close();
  }
}

async function searchChunkDatabase(
  kb: KnowledgeBaseSettings,
  rag: RagSettings,
  query: string,
  topK: number,
): Promise<SearchHit[]> {
  const persistDir = knowledgeBaseChromaPath(kb);
  const db = new Database(join(persistDir, "chroma.sqlite3"), { readonly: true });
  try {
    const rows = db
      .query("SELECT source, chunk_index, text, embedding_json FROM chunks WHERE knowledge_base = ?")
      .all(kb.name) as {
      source: string;
      chunk_index: number;
      text: string;
      embedding_json: string | null;
    }[];
    if (rows.length === 0) return [];

    const k = Math.max(1, Math.min(Math.trunc(topK || 5), 10));
    const hasVectors = rows.every((r) => r.embedding_json);
    const embedder = hasVectors ? buildEmbeddingModel(rag) : null;

    let scored: { row: (typeof rows)[number]; score: number }[];
    if (embedder) {
      const queryVec = await embedder.embedQuery(query);
      scored = rows.map((row) => ({
        row,
        score: cosineSimilarity(queryVec, JSON.parse(row.embedding_json!) as number[]),
      }));
    } else {
      scored = rows.map((row) => ({ row, score: lexicalScore(query, row.text) }));
    }

    scored.sort((a, b) => b.score - a.score);
    return scored.slice(0, k).map((s) => [
      s.row.text,
      {
        knowledge_base: kb.name,
        source: s.row.source,
        chunk_index: s.row.chunk_index,
      },
      s.score,
    ]);
  } finally {
    db.close();
  }
}

async function searchChromaHttpKnowledgeBase(
  kb: KnowledgeBaseSettings,
  query: string,
  topK: number,
): Promise<SearchHit[]> {
  const collectionName = kb.collectionName.trim() || kb.name;
  if (!kb.chromaUrl.trim()) {
    throw new Error(`Chroma knowledge base '${kb.name}' requires chroma_url.`);
  }
  const client = await chromaClient(kb);
  const collection = await client.getCollection({ name: collectionName, embeddingFunction: undefined });
  const k = Math.max(1, Math.min(Math.trunc(topK || 5), 10));
  const result = await queryChromaCollection(collection, query, k);
  return result.map((row) => [
    row.text,
    {
      knowledge_base: kb.name,
      source: row.source,
      chunk_index: row.chunkIndex,
    },
    row.score,
  ]);
}

async function chromaClient(kb: KnowledgeBaseSettings): Promise<ChromaClientLike> {
  if (chromaClientFactory) return chromaClientFactory(kb);
  const { ChromaClient } = await import("chromadb");
  const headers = parseHeaders(kb.headers);
  return new ChromaClient({
    path: kb.chromaUrl,
    ...(kb.tenant ? { tenant: kb.tenant } : {}),
    ...(kb.database ? { database: kb.database } : {}),
    ...(Object.keys(headers).length ? { headers } : {}),
  }) as ChromaClientLike;
}

async function queryChromaCollection(
  collection: unknown,
  query: string,
  topK: number,
): Promise<{ text: string; source: string; chunkIndex: string | number; score: number | null }[]> {
  const anyCollection = collection as {
    query?: (args: Record<string, unknown>) => Promise<Record<string, unknown>>;
    search?: (searches: unknown, options?: Record<string, unknown>) => Promise<{ rows?: () => unknown[][] } | Record<string, unknown>>;
  };

  if (typeof anyCollection.query === "function") {
    const result = await anyCollection.query({
      queryTexts: [query],
      nResults: topK,
      include: ["documents", "metadatas", "distances"],
    });
    return rowsFromLegacyChromaQuery(result);
  }

  if (typeof anyCollection.search === "function") {
    const { Search, Knn } = await import("chromadb");
    const result = await anyCollection.search(
      new Search({ rank: Knn({ query, limit: topK }), limit: topK }).select("Document", "Metadata", "Score"),
    );
    if (result && typeof result === "object" && typeof (result as { rows?: unknown }).rows === "function") {
      return rowsFromChromaSearchRows((result as { rows: () => unknown[][] }).rows());
    }
  }

  throw new Error("Unsupported Chroma collection client: expected query() or search().");
}

function rowsFromLegacyChromaQuery(result: Record<string, unknown>) {
  const documents = ((result.documents as unknown[][] | undefined)?.[0] ?? []) as unknown[];
  const metadatas = ((result.metadatas as unknown[][] | undefined)?.[0] ?? []) as unknown[];
  const distances = ((result.distances as unknown[][] | undefined)?.[0] ?? []) as unknown[];
  return documents.map((doc, i) => {
    const meta = metadatas[i] && typeof metadatas[i] === "object" ? (metadatas[i] as Record<string, unknown>) : {};
    const distance = typeof distances[i] === "number" ? distances[i] as number : null;
    return {
      text: String(doc ?? ""),
      source: String(meta.source ?? meta.uri ?? "chroma"),
      chunkIndex: scalarLabel(meta.chunk_index ?? meta.id, i),
      score: distance === null ? null : 1 / (1 + distance),
    };
  });
}

function rowsFromChromaSearchRows(rows: unknown[][]) {
  const first = rows[0] ?? [];
  return first.map((row, i) => {
    const obj = row && typeof row === "object" ? (row as Record<string, unknown>) : {};
    const metadata = obj.metadata && typeof obj.metadata === "object" ? (obj.metadata as Record<string, unknown>) : {};
    return {
      text: String(obj.document ?? ""),
      source: String(metadata.source ?? metadata.uri ?? "chroma"),
      chunkIndex: scalarLabel(metadata.chunk_index ?? obj.id, i),
      score: typeof obj.score === "number" ? obj.score : null,
    };
  });
}

function scalarLabel(value: unknown, fallback: number): string | number {
  if (typeof value === "string" || typeof value === "number") return value;
  return fallback;
}

function cosineSimilarity(a: number[], b: number[]): number {
  let dot = 0;
  let na = 0;
  let nb = 0;
  const len = Math.min(a.length, b.length);
  for (let i = 0; i < len; i++) {
    dot += a[i]! * b[i]!;
    na += a[i]! * a[i]!;
    nb += b[i]! * b[i]!;
  }
  if (na === 0 || nb === 0) return 0;
  return dot / (Math.sqrt(na) * Math.sqrt(nb));
}

function lexicalScore(query: string, text: string): number {
  const terms = query.toLowerCase().split(/\s+/).filter(Boolean);
  if (terms.length === 0) return 0;
  const haystack = text.toLowerCase();
  let hits = 0;
  for (const term of terms) {
    let idx = haystack.indexOf(term);
    while (idx !== -1) {
      hits++;
      idx = haystack.indexOf(term, idx + term.length);
    }
  }
  // Normalize by text length so long chunks don't dominate purely by size.
  return hits / Math.max(1, Math.log10(haystack.length + 10));
}

function snippet(text: string, limit = 900): string {
  const compact = text.split(/\s+/).join(" ");
  if (compact.length <= limit) return compact;
  return compact.slice(0, limit - 3) + "...";
}

function iterTextFiles(root: string): string[] {
  if (statSync(root).isFile()) {
    return isTextFile(root) ? [root] : [];
  }
  const out: string[] = [];
  const walk = (dir: string) => {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const full = join(dir, entry.name);
      if (entry.isDirectory()) walk(full);
      else if (entry.isFile() && isTextFile(full)) out.push(full);
    }
  };
  walk(root);
  return out.sort();
}

function isTextFile(path: string): boolean {
  return TEXT_SUFFIXES.has(extname(path).toLowerCase());
}

function readText(path: string): string {
  try {
    return readFileSync(path, "utf-8");
  } catch {
    return readFileSync(path, { encoding: "latin1" }).toString();
  }
}

export function splitText(text: string, chunkSize: number, overlap: number): string[] {
  const normalized = text.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
  if (normalized.length <= chunkSize) return [normalized];

  const chunks: string[] = [];
  let start = 0;
  const step = Math.max(1, chunkSize - overlap);
  while (start < normalized.length) {
    const end = Math.min(normalized.length, start + chunkSize);
    const chunk = normalized.slice(start, end).trim();
    if (chunk) chunks.push(chunk);
    if (end >= normalized.length) break;
    start += step;
  }
  return chunks;
}

export function ragKnowledgeBaseName(explicit: string, path: string): string {
  if (explicit.trim()) return explicit.trim();
  const isFile = existsSync(path) && statSync(path).isFile();
  return isFile ? basename(path, extname(path)) : basename(path);
}

function safeName(name: string): string {
  const safe = name.trim().replace(/[^A-Za-z0-9_.-]+/g, "-").replace(/^-+|-+$/g, "");
  return safe || "knowledge-base";
}

function expandUser(path: string): string {
  if (path === "~" || path.startsWith("~/") || path.startsWith("~\\")) {
    return resolve(join(homedir(), path.slice(1)));
  }
  return resolve(path);
}

function parseHeaders(raw: string): Record<string, string> {
  const text = raw.trim();
  if (!text) return {};
  const parsed = JSON.parse(text);
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("headers must be a JSON object");
  }
  return Object.fromEntries(Object.entries(parsed).map(([k, v]) => [k, String(v)]));
}
