/**
 * SkillHub client for discovering and installing SKILL.md packages.
 *
 * The hub URL can be overridden with SARMA_SKILLSHUB_URL. The response parser
 * accepts a few common shapes so Sarma is not tied to one early hub schema.
 */

import { existsSync, mkdirSync, statSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import * as paths from "@/paths";

export const DEFAULT_SKILLSHUB_URL = "https://www.skillhub.club";

export interface SkillHubSearchResult {
  name: string;
  description: string;
  author: string;
  version: string;
}

export interface InstalledSkill {
  name: string;
  path: string;
  installed: boolean;
}

type FetchLike = typeof fetch;

interface SkillHubOptions {
  baseUrl?: string;
  fetchImpl?: FetchLike;
}

function fetcher(options: SkillHubOptions = {}): FetchLike {
  return options.fetchImpl ?? fetch;
}

export function skillHubBaseUrl(): string {
  const raw = process.env.SARMA_SKILLSHUB_URL || DEFAULT_SKILLSHUB_URL;
  return raw.trim().replace(/\/+$/, "");
}

function isFile(path: string): boolean {
  try {
    return statSync(path).isFile();
  } catch {
    return false;
  }
}

function validSkillName(name: string): boolean {
  return /^[A-Za-z0-9_.-]+$/.test(name);
}

function candidates(baseUrl: string, paths: string[]): string[] {
  const base = baseUrl.replace(/\/+$/, "");
  return paths.map((path) => `${base}${path.startsWith("/") ? "" : "/"}${path}`);
}

async function fetchFirst(urls: string[], fetchImpl: FetchLike): Promise<Response> {
  let lastError: unknown = null;
  for (const url of urls) {
    try {
      const response = await fetchImpl(url, {
        headers: { accept: "application/json, text/markdown, text/plain;q=0.9" },
      });
      if (response.ok) return response;
      lastError = new Error(`${response.status} ${response.statusText}`.trim());
      if (response.status !== 404) break;
    } catch (exc) {
      lastError = exc;
      break;
    }
  }
  throw lastError instanceof Error ? lastError : new Error(String(lastError ?? "SkillHub request failed"));
}

async function readPayload(response: Response): Promise<unknown> {
  const contentType = response.headers.get("content-type") ?? "";
  const text = await response.text();
  if (contentType.includes("json")) {
    try {
      return JSON.parse(text);
    } catch {
      return text;
    }
  }
  if (text.trim().startsWith("{") || text.trim().startsWith("[")) {
    try {
      return JSON.parse(text);
    } catch {
      return text;
    }
  }
  return text;
}

function arrayPayload(payload: unknown): unknown[] {
  if (Array.isArray(payload)) return payload;
  if (payload && typeof payload === "object") {
    const record = payload as Record<string, unknown>;
    for (const key of ["skills", "results", "items", "data"]) {
      if (Array.isArray(record[key])) return record[key] as unknown[];
    }
  }
  return [];
}

function stringField(record: Record<string, unknown>, keys: string[]): string {
  for (const key of keys) {
    const value = record[key];
    if (typeof value === "string") return value.trim();
  }
  return "";
}

export async function searchSkillHub(
  query: string,
  options: SkillHubOptions = {},
): Promise<SkillHubSearchResult[]> {
  const q = query.trim();
  if (!q) return [];
  const baseUrl = options.baseUrl ?? skillHubBaseUrl();
  const encoded = encodeURIComponent(q);
  const response = await fetchFirst(
    candidates(baseUrl, [
      `/api/skills/search?q=${encoded}`,
      `/api/skills?q=${encoded}`,
      `/skills/search?q=${encoded}`,
    ]),
    fetcher(options),
  );
  const payload = await readPayload(response);
  return arrayPayload(payload)
    .map((item): SkillHubSearchResult | null => {
      if (!item || typeof item !== "object") return null;
      const record = item as Record<string, unknown>;
      const name = stringField(record, ["name", "slug", "id"]);
      if (!name || !validSkillName(name)) return null;
      return {
        name,
        description: stringField(record, ["description", "summary", "title"]),
        author: stringField(record, ["author", "publisher", "owner"]),
        version: stringField(record, ["version", "latestVersion", "latest_version"]),
      };
    })
    .filter((item): item is SkillHubSearchResult => item !== null);
}

function skillMarkdownFromPayload(payload: unknown): string {
  if (typeof payload === "string") return payload;
  if (!payload || typeof payload !== "object") return "";
  const record = payload as Record<string, unknown>;
  const skill = record.skill;
  if (skill && typeof skill === "object") {
    const nested = stringField(skill as Record<string, unknown>, [
      "skill_md",
      "skillMd",
      "content",
      "markdown",
      "body",
    ]);
    if (nested) return nested;
  }
  return stringField(record, ["skill_md", "skillMd", "content", "markdown", "body", "readme"]);
}

export async function downloadSkillFromHub(
  name: string,
  options: SkillHubOptions = {},
): Promise<string> {
  const skillName = name.trim();
  if (!validSkillName(skillName)) {
    throw new Error("Skill name may only contain letters, numbers, dot, dash, and underscore.");
  }
  const baseUrl = options.baseUrl ?? skillHubBaseUrl();
  const encoded = encodeURIComponent(skillName);
  const response = await fetchFirst(
    candidates(baseUrl, [
      `/api/skills/${encoded}`,
      `/api/skills/${encoded}/download`,
      `/skills/${encoded}/SKILL.md`,
    ]),
    fetcher(options),
  );
  const content = skillMarkdownFromPayload(await readPayload(response)).trim();
  if (!content) throw new Error(`SkillHub returned empty skill content for ${skillName}.`);
  return `${content}\n`;
}

export async function installSkillFromHub(
  name: string,
  options: SkillHubOptions & { targetDir?: string } = {},
): Promise<InstalledSkill> {
  const skillName = name.trim();
  if (!validSkillName(skillName)) {
    throw new Error("Skill name may only contain letters, numbers, dot, dash, and underscore.");
  }
  const dir = join(options.targetDir ?? paths.localSkillsDir(), skillName);
  const skillPath = join(dir, "SKILL.md");
  if (existsSync(skillPath) && isFile(skillPath)) {
    return { name: skillName, path: skillPath, installed: false };
  }
  const markdown = await downloadSkillFromHub(skillName, options);
  mkdirSync(dir, { recursive: true });
  writeFileSync(skillPath, markdown, "utf-8");
  return { name: skillName, path: skillPath, installed: true };
}
