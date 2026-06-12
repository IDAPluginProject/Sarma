/**
 * Sarma configuration management.
 *
 * Configuration is split into TOML files across global and workspace scopes:
 * - `models.toml`: named model providers.
 * - `agents.toml`: workflow/agent model, MCP, and skill permissions.
 * - `mcp.toml`: MCP server definitions.
 * - `rag.toml`: RAG chunking model and knowledge base registry.
 *
 * Global `models.toml` and `agents.toml` are authoritative. MCP servers and
 * RAG knowledge bases are additive: `~/.sarma` entries remain available, while
 * `./.sarma` can add new entries or override entries with the same name.
 */

import { existsSync, mkdirSync, readFileSync, writeFileSync, renameSync } from "node:fs";
import { dirname, basename, join } from "node:path";
import { parse as parseToml, stringify as stringifyToml } from "smol-toml";
import * as paths from "@/paths";

export const WILDCARD = "*";
export const API_MODES = ["openai_compatible", "openai_responses", "anthropic"] as const;
export const WORKFLOWS = ["ruflo", "audit", "audit-slim"] as const;
export const LEGACY_WORKFLOW_ALIASES: Record<string, string> = { chat: "ruflo" };
const CONTEXT_WINDOW_UNIT_EXPONENTS: Record<string, number> = {
  k: 1,
  kb: 1,
  m: 2,
  mb: 2,
  g: 3,
  gb: 3,
  t: 4,
  tb: 4,
};

export class ProviderConfig {
  name = "default";
  modelName = "";
  apiKey = "";
  baseUrl = "";
  apiMode = "openai_compatible";
  temperature = 0.0;
  topP = 1.0;
  maxContextTokens = 128_000;
  enabled = true;

  constructor(init: Partial<ProviderConfig> = {}) {
    Object.assign(this, init);
  }
}

export class McpServerConfig {
  name = "";
  transport = "stdio";
  command = "";
  args = "";
  env = "";
  cwd = "";
  url = "";
  headers = "";
  enabled = true;
  encoding = "utf-8";
  timeout = 60.0;
  sseReadTimeout = 300.0;

  constructor(init: Partial<McpServerConfig> = {}) {
    Object.assign(this, init);
  }
}

export class AgentConfig {
  name = "ruflo";
  model = "default";
  mcp: string[] = [WILDCARD];
  skills: string[] = [];

  constructor(init: Partial<AgentConfig> = {}) {
    Object.assign(this, init);
  }

  allowsAllMcp(): boolean {
    return this.mcp.includes(WILDCARD);
  }

  allowsAllSkills(): boolean {
    return this.skills.includes(WILDCARD);
  }
}

export class KnowledgeBaseConfig {
  name = "";
  docsPath = "";
  chromaPath = "";
  backend = "sarma_native";
  chromaUrl = "";
  collectionName = "";
  tenant = "";
  database = "";
  headers = "";
  enabled = true;

  constructor(init: Partial<KnowledgeBaseConfig> = {}) {
    Object.assign(this, init);
  }
}

export class RagConfig {
  embeddingBackend = "huggingface";
  embeddingModel = "";
  embeddingApiBase = "";
  embeddingApiKey = "";
  embeddingLocalPath = "";
  chunkSize = 1200;
  chunkOverlap = 150;
  knowledgeBases: KnowledgeBaseConfig[] = [];

  constructor(init: Partial<RagConfig> = {}) {
    Object.assign(this, init);
  }
}

export class CliConfig {
  activeModel = "default";
  models: ProviderConfig[] = [];
  mcpServers: McpServerConfig[] = [];
  agents: AgentConfig[] = [];
  rag: RagConfig = new RagConfig();

  constructor(init: Partial<CliConfig> = {}) {
    Object.assign(this, init);
  }

  get provider(): ProviderConfig {
    return this.getModel(this.activeModel);
  }

  getModel(name?: string | null): ProviderConfig {
    const target = name || this.activeModel;
    for (const model of this.models) {
      if (model.name === target && model.enabled) return model;
    }
    for (const model of this.models) {
      if (model.enabled) return model;
    }
    return new ProviderConfig({ name: target || "default" });
  }

  upsertModel(provider: ProviderConfig): void {
    const idx = this.models.findIndex((m) => m.name === provider.name);
    if (idx >= 0) {
      this.models[idx] = provider;
    } else {
      this.models.push(provider);
    }
  }
}

// ---------------------------------------------------------------------------
// Default TOML templates
// ---------------------------------------------------------------------------

const AUDIT_AGENT_NAMES = [
  "audit",
  "audit.recon",
  "audit.hunt",
  "audit.validate",
  "audit.gapfill",
  "audit.dedupe",
  "audit.trace",
  "audit.feedback",
  "audit.report",
  "audit-slim",
  "audit-slim.recon",
  "audit-slim.hunter",
  "audit-slim.verify",
  "audit-slim.report",
];

const DEFAULT_MODELS_TOML = `# Sarma model providers
# \`active\` is used when an agent does not specify its own model.
active = "default"

[[models]]
name = "default"
model_name = ""
api_key = ""
base_url = ""
api_mode = "openai_compatible"   # openai_compatible | openai_responses | anthropic
temperature = 0.0
top_p = 1.0
max_context_tokens = 128000
enabled = true
`;

const DEFAULT_AGENTS_TOML = (() => {
  const block = (name: string) =>
    `[[agents]]\nname = "${name}"\nmodel = "default"\nmcp = ["*"]\nskills = []\n`;
  const names = ["ruflo", ...AUDIT_AGENT_NAMES];
  return (
    "# Sarma workflow agent routing.\n" +
    "# `model` references a name from models.toml.\n" +
    '# `mcp` and `skills` accept ["*"] for all, or a list of names.\n\n' +
    names.map(block).join("\n")
  );
})();

const DEFAULT_MCP_TOML = `# MCP servers (repeat [[mcp_servers]] for each server)

# [[mcp_servers]]
# name = "local-http-tools"
# transport = "http"  # stdio | http | sse
# url = "http://127.0.0.1:8000/mcp"
# enabled = true
`;

const DEFAULT_RAG_TOML = `# RAG knowledge base settings.
# \`embedding_model\` is independent from chat models in models.toml.
embedding_backend = "huggingface"  # huggingface | api
embedding_model = ""
embedding_api_base = ""
embedding_api_key = ""
embedding_local_path = ""
chunk_size = 1200
chunk_overlap = 150

# [[knowledge_bases]]
# name = "project-docs"
# backend = "sarma_native" # sarma_native | chroma_http
# docs_path = ""
# chroma_path = ""
# chroma_url = ""
# collection_name = ""
# tenant = ""
# database = ""
# headers = ""
# enabled = true
`;

// ---------------------------------------------------------------------------
// Parsing helpers
// ---------------------------------------------------------------------------

function parseContextWindowStrict(value: unknown): number | null {
  if (value === null || value === undefined) return null;
  if (typeof value === "number") {
    const tokens = Math.trunc(value);
    return Number.isFinite(tokens) && tokens > 0 ? tokens : null;
  }
  if (typeof value !== "string") {
    const tokens = Math.trunc(Number(value));
    return Number.isFinite(tokens) && tokens > 0 ? tokens : null;
  }
  const text = value.trim();
  if (!text) return null;
  const compact = text.replace(/[_,]/g, "").replace(/\s+/g, " ");
  const match = /^(\d+(?:\.\d+)?)\s*([a-zA-Z]+)?(?:\s+(?:tokens?|tok))?$/.exec(compact);
  if (!match) return null;
  const amount = Number(match[1]);
  const unit = (match[2] ?? "").toLowerCase();
  const exponent = unit ? CONTEXT_WINDOW_UNIT_EXPONENTS[unit] : 0;
  if (exponent === undefined) return null;
  const tokens = Math.trunc(amount * 1000 ** exponent);
  return Number.isFinite(tokens) && tokens > 0 ? tokens : null;
}

/**
 * Parse a context window token count. Supports strict numeric strings and
 * decimal shorthand such as `200K`, `1 M`, `1.5M`, and `2GB`.
 */
export function parseContextWindow(value: unknown, dflt = 128_000): number {
  if (value === null || value === undefined || value === "") return dflt;
  const tokens = parseContextWindowStrict(value);
  if (tokens === null) {
    throw new Error("Max context window must be greater than 0.");
  }
  return tokens;
}

export function tryParseContextWindow(value: unknown): number | null {
  return parseContextWindowStrict(value);
}

type TomlData = Record<string, unknown>;

function readToml(path: string): TomlData {
  if (!existsSync(path)) return {};
  try {
    return parseToml(readFileSync(path, "utf-8")) as TomlData;
  } catch (exc) {
    // Surface the failure instead of silently returning {} — a parse error
    // means the file's settings are about to be ignored (and on next save,
    // overwritten). The user needs to know their config didn't load.
    const msg = exc instanceof Error ? exc.message : String(exc);
    console.error(`Warning: failed to parse ${path}: ${msg}\n` + `Its settings will be ignored until the file is fixed.`);
    return {};
  }
}

function asArray(value: unknown): TomlData[] {
  return Array.isArray(value) ? (value as TomlData[]) : [];
}

function str(value: unknown, dflt = ""): string {
  return value === null || value === undefined ? dflt : String(value);
}

function num(value: unknown, dflt: number): number {
  if (value === null || value === undefined || value === "") return dflt;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : dflt;
}

function ensureGlobalConfigSuite(): void {
  const g = paths.globalDir();
  mkdirSync(g, { recursive: true });
  mkdirSync(paths.globalSkillsDir(), { recursive: true });
  mkdirSync(paths.ragModelsDir(), { recursive: true });
  const defaults: [string, string][] = [
    [paths.globalModelsFile(), DEFAULT_MODELS_TOML],
    [paths.globalAgentsFile(), DEFAULT_AGENTS_TOML],
    [paths.globalMcpFile(), DEFAULT_MCP_TOML],
    [paths.globalRagFile(), DEFAULT_RAG_TOML],
  ];
  for (const [target, text] of defaults) {
    if (!existsSync(target)) writeFileSync(target, text, "utf-8");
  }
}

/** Create local workspace directories without copying global config files. */
export function ensureWorkspaceConfig(): void {
  ensureGlobalConfigSuite();
  mkdirSync(paths.localDir(), { recursive: true });
  mkdirSync(paths.localSkillsDir(), { recursive: true });
  mkdirSync(paths.ragDocsDir(), { recursive: true });
  mkdirSync(paths.ragChromaDir(), { recursive: true });
}

function parseModels(data: TomlData): [string, ProviderConfig[]] {
  const models: ProviderConfig[] = [];
  for (const raw of asArray(data.models)) {
    models.push(
      new ProviderConfig({
        name: str(raw.name, "default"),
        modelName: str(raw.model_name),
        apiKey: str(raw.api_key),
        baseUrl: str(raw.base_url),
        apiMode: str(raw.api_mode, "openai_compatible"),
        temperature: num(raw.temperature, 0.0),
        topP: num(raw.top_p, 1.0),
        maxContextTokens: parseContextWindow(raw.max_context_tokens),
        enabled: raw.enabled === undefined ? true : Boolean(raw.enabled),
      }),
    );
  }
  if (models.length === 0) models.push(new ProviderConfig());
  const active = str(data.active) || models[0]!.name;
  return [active, models];
}

function parseMcp(data: TomlData): McpServerConfig[] {
  const servers: McpServerConfig[] = [];
  for (const srv of asArray(data.mcp_servers)) {
    servers.push(
      new McpServerConfig({
        name: str(srv.name),
        transport: str(srv.transport, "stdio"),
        command: str(srv.command),
        args: str(srv.args),
        env: str(srv.env),
        cwd: str(srv.cwd),
        url: str(srv.url),
        headers: str(srv.headers),
        enabled: srv.enabled === undefined ? true : Boolean(srv.enabled),
        encoding: str(srv.encoding, "utf-8"),
        timeout: srv.timeout === undefined ? 60.0 : Number(srv.timeout),
        sseReadTimeout: srv.sse_read_timeout === undefined ? 300.0 : Number(srv.sse_read_timeout),
      }),
    );
  }
  return servers;
}

function normalizeAgentName(name: string): string {
  const dotIdx = name.indexOf(".");
  if (dotIdx < 0) {
    return LEGACY_WORKFLOW_ALIASES[name] ?? name;
  }
  const workflow = name.slice(0, dotIdx);
  const subagent = name.slice(dotIdx + 1);
  const mapped = LEGACY_WORKFLOW_ALIASES[workflow] ?? workflow;
  return `${mapped}.${subagent}`;
}

function parseAgents(data: TomlData): AgentConfig[] {
  const agents: AgentConfig[] = [];
  const seen = new Set<string>();
  for (const raw of asArray(data.agents)) {
    const name = normalizeAgentName(str(raw.name, "ruflo"));
    if (seen.has(name)) continue;
    seen.add(name);
    agents.push(
      new AgentConfig({
        name,
        model: str(raw.model, "default"),
        mcp: Array.isArray(raw.mcp) ? raw.mcp.map((x) => String(x)) : [WILDCARD],
        skills: Array.isArray(raw.skills) ? raw.skills.map((x) => String(x)) : [],
      }),
    );
  }
  if (agents.length === 0) agents.push(new AgentConfig());
  return agents;
}

function parseRag(data: TomlData): RagConfig {
  let chunkSize = data.chunk_size === undefined ? 1200 : Math.trunc(Number(data.chunk_size));
  let chunkOverlap = data.chunk_overlap === undefined ? 150 : Math.trunc(Number(data.chunk_overlap));
  if (!Number.isFinite(chunkSize) || chunkSize <= 0) chunkSize = 1200;
  if (!Number.isFinite(chunkOverlap) || chunkOverlap < 0) chunkOverlap = 0;
  if (chunkOverlap >= chunkSize) chunkOverlap = Math.max(0, Math.floor(chunkSize / 4));

  const knowledgeBases = asArray(data.knowledge_bases).map(
    (raw) =>
      new KnowledgeBaseConfig({
        name: str(raw.name),
        docsPath: str(raw.docs_path),
        chromaPath: str(raw.chroma_path),
        backend: normalizeKnowledgeBaseBackend(str(raw.backend, raw.chroma_url ? "chroma_http" : "sarma_native")),
        chromaUrl: str(raw.chroma_url),
        collectionName: str(raw.collection_name),
        tenant: str(raw.tenant),
        database: str(raw.database),
        headers: str(raw.headers),
        enabled: raw.enabled === undefined ? true : Boolean(raw.enabled),
      }),
  );

  let embeddingBackend = str(data.embedding_backend, "huggingface").toLowerCase();
  if (embeddingBackend !== "huggingface" && embeddingBackend !== "api") {
    embeddingBackend = "huggingface";
  }
  return new RagConfig({
    embeddingBackend,
    embeddingModel: str(data.embedding_model) || str(data.model),
    embeddingApiBase: str(data.embedding_api_base),
    embeddingApiKey: str(data.embedding_api_key),
    embeddingLocalPath: str(data.embedding_local_path),
    chunkSize,
    chunkOverlap,
    knowledgeBases,
  });
}

function normalizeKnowledgeBaseBackend(value: string): string {
  const backend = value.trim().toLowerCase();
  if (backend === "chroma" || backend === "chroma_http") return "chroma_http";
  return "sarma_native";
}

function mergeNamed<T extends { name: string }>(globalItems: T[], localItems: T[]): T[] {
  const byName = new Map<string, T>();
  const order: string[] = [];
  for (const item of [...globalItems, ...localItems]) {
    const name = String(item.name ?? "").trim();
    if (!name) continue;
    if (!byName.has(name)) order.push(name);
    byName.set(name, item);
  }
  return order.map((name) => byName.get(name)!);
}

// ---------------------------------------------------------------------------
// Loaders
// ---------------------------------------------------------------------------

/** Initialize global and workspace config files. Returns the dirs touched. */
export function initConfig(local = false): { global: string; workspace: string } {
  ensureGlobalConfigSuite();
  ensureWorkspaceConfig();
  return { global: paths.globalDir(), workspace: paths.localDir() };
}

export function loadGlobalMcpServers(): McpServerConfig[] {
  ensureGlobalConfigSuite();
  return parseMcp(readToml(paths.globalMcpFile()));
}

export function loadLocalMcpServers(): McpServerConfig[] {
  ensureWorkspaceConfig();
  return parseMcp(readToml(paths.localMcpFile()));
}

export function loadGlobalRagConfig(): RagConfig {
  ensureGlobalConfigSuite();
  return parseRag(readToml(paths.globalRagFile()));
}

export function loadLocalRagConfig(): RagConfig {
  ensureWorkspaceConfig();
  return parseRag(readToml(paths.localRagFile()));
}

/** Load the effective config suite using global defaults plus local overlays. */
export function loadConfig(): CliConfig {
  ensureWorkspaceConfig();
  const [active, models] = parseModels(readToml(paths.globalModelsFile()));
  const agents = parseAgents(readToml(paths.globalAgentsFile()));
  const globalRag = loadGlobalRagConfig();
  const localRag = loadLocalRagConfig();
  const rag = new RagConfig({
    embeddingBackend: globalRag.embeddingBackend,
    embeddingModel: globalRag.embeddingModel,
    embeddingApiBase: globalRag.embeddingApiBase,
    embeddingApiKey: globalRag.embeddingApiKey,
    embeddingLocalPath: globalRag.embeddingLocalPath,
    chunkSize: globalRag.chunkSize,
    chunkOverlap: globalRag.chunkOverlap,
    knowledgeBases: mergeNamed(globalRag.knowledgeBases, localRag.knowledgeBases),
  });
  return new CliConfig({
    activeModel: active,
    models,
    mcpServers: mergeNamed(loadGlobalMcpServers(), loadLocalMcpServers()),
    agents,
    rag,
  });
}

// ---------------------------------------------------------------------------
// Savers
// ---------------------------------------------------------------------------

/**
 * Atomically write TOML to `target` with restrictive permissions.
 *
 * `header` lines (TOML comments) are prepended verbatim, since the serializer
 * does not emit comments. The body is produced by smol-toml's `stringify`,
 * which correctly escapes newlines, quotes, and control characters — the
 * hand-rolled serializer this replaces silently corrupted such values, and a
 * single stray newline could make the whole file unparseable (and, because
 * `readToml` falls back to `{}` on parse error, silently wipe all settings).
 *
 * The write goes to a temp file in the same directory and is renamed into
 * place so a crash mid-write cannot truncate the existing config. Files are
 * created mode 0600 because they hold API keys.
 */
function writeToml(target: string, data: Record<string, unknown>, header: string[] = []): string {
  mkdirSync(dirname(target), { recursive: true });
  const headerText = header.length ? header.join("\n") + "\n\n" : "";
  const body = stringifyToml(data);
  const content = (headerText + body).replace(/\s+$/, "") + "\n";
  const tmp = join(dirname(target), `.${basename(target)}.tmp`);
  writeFileSync(tmp, content, { encoding: "utf-8", mode: 0o600 });
  renameSync(tmp, target);
  return target;
}

/** Persist the global models.toml file. */
export function saveModels(config: CliConfig): string {
  const data = {
    active: config.activeModel,
    models: config.models.map((model) => ({
      name: model.name,
      model_name: model.modelName,
      api_mode: model.apiMode,
      api_key: model.apiKey,
      base_url: model.baseUrl,
      temperature: model.temperature,
      top_p: model.topP,
      max_context_tokens: model.maxContextTokens,
      enabled: model.enabled,
    })),
  };
  return writeToml(paths.globalModelsFile(), data);
}

function agentSortKey(agent: AgentConfig): [number, number, string] {
  const workflow = agent.name.split(".", 1)[0]!;
  const idx = (WORKFLOWS as readonly string[]).indexOf(workflow);
  const workflowIndex = idx < 0 ? WORKFLOWS.length : idx;
  const isSubagent = agent.name.includes(".") ? 1 : 0;
  return [workflowIndex, isSubagent, agent.name];
}

/** Persist the global agents.toml file. */
export function saveAgents(config: CliConfig): string {
  const header = [
    "# Sarma workflow agent routing.",
    "# `model` references a name from models.toml.",
    '# `mcp` and `skills` accept ["*"] for all, or a list of names.',
  ];
  const sorted = [...config.agents].sort((a, b) => {
    const ka = agentSortKey(a);
    const kb = agentSortKey(b);
    return ka[0] - kb[0] || ka[1] - kb[1] || ka[2].localeCompare(kb[2]);
  });
  const data = {
    agents: sorted.map((agent) => ({
      name: agent.name,
      model: agent.model,
      mcp: agent.mcp,
      skills: agent.skills,
    })),
  };
  return writeToml(paths.globalAgentsFile(), data, header);
}

function resolveScope(value: string): "local" | "global" {
  const scope = value.trim().toLowerCase();
  if (scope !== "local" && scope !== "workspace" && scope !== "global") {
    throw new Error("Scope must be local, workspace, or global.");
  }
  return scope === "workspace" ? "local" : (scope as "local" | "global");
}

/** Persist a concrete MCP server list to local or global scope. */
export function saveMcpServers(servers: McpServerConfig[], scope = "local"): string {
  const header = ["# MCP servers (repeat [[mcp_servers]] for each server)"];
  const data = {
    mcp_servers: servers.map((server) => ({
      name: server.name,
      transport: server.transport,
      command: server.command,
      args: server.args,
      env: server.env,
      cwd: server.cwd,
      url: server.url,
      headers: server.headers,
      enabled: server.enabled,
      encoding: server.encoding,
      timeout: server.timeout,
      sse_read_timeout: server.sseReadTimeout,
    })),
  };
  const target = resolveScope(scope) === "global" ? paths.globalMcpFile() : paths.localMcpFile();
  return writeToml(target, data, header);
}

/** Persist a concrete RAG config to local or global scope. */
export function saveRagConfig(rag: RagConfig, scope = "local"): string {
  const isGlobal = resolveScope(scope) === "global";
  const header = ["# RAG knowledge base settings."];
  const data: Record<string, unknown> = {};
  if (isGlobal) {
    header.push("# `embedding_model` is independent from chat models in models.toml.");
    data.embedding_backend = rag.embeddingBackend;
    data.embedding_model = rag.embeddingModel;
    data.embedding_api_base = rag.embeddingApiBase;
    data.embedding_api_key = rag.embeddingApiKey;
    data.embedding_local_path = rag.embeddingLocalPath;
    data.chunk_size = rag.chunkSize;
    data.chunk_overlap = rag.chunkOverlap;
  } else {
    header.push(
      "# Workspace files register local/private knowledge bases only.",
      "# RAG embedding model settings are loaded from ~/.sarma/rag.toml.",
    );
  }
  // knowledge_bases is an array-of-tables; it must come after scalar keys.
  data.knowledge_bases = rag.knowledgeBases.map((kb) => ({
    name: kb.name,
    backend: kb.backend,
    docs_path: kb.docsPath,
    chroma_path: kb.chromaPath,
    chroma_url: kb.chromaUrl,
    collection_name: kb.collectionName,
    tenant: kb.tenant,
    database: kb.database,
    headers: kb.headers,
    enabled: kb.enabled,
  }));
  const target = isGlobal ? paths.globalRagFile() : paths.localRagFile();
  return writeToml(target, data, header);
}

/** Persist global RAG model settings while preserving global KB entries. */
export function saveRagModel(config: CliConfig): string {
  const globalRag = loadGlobalRagConfig();
  const rag = new RagConfig({
    embeddingBackend: config.rag.embeddingBackend,
    embeddingModel: config.rag.embeddingModel,
    embeddingApiBase: config.rag.embeddingApiBase,
    embeddingApiKey: config.rag.embeddingApiKey,
    embeddingLocalPath: config.rag.embeddingLocalPath,
    chunkSize: config.rag.chunkSize,
    chunkOverlap: config.rag.chunkOverlap,
    knowledgeBases: globalRag.knowledgeBases,
  });
  return saveRagConfig(rag, "global");
}

/** Persist RAG knowledge base registrations in local or global scope. */
export function saveRagKnowledgeBases(knowledgeBases: KnowledgeBaseConfig[], scope = "local"): string {
  const base = resolveScope(scope) === "global" ? loadGlobalRagConfig() : new RagConfig();
  base.knowledgeBases = knowledgeBases;
  return saveRagConfig(base, scope);
}
