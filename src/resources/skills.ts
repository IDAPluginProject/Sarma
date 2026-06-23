/**
 * Skill loading for installed SKILL.md directories.
 *
 * A skill is a directory under `~/.sarma/skills/<name>` (global) or
 * `./.sarma/skills/<name>` (workspace) containing a `SKILL.md` file. This
 * module only discovers and parses skill resources; runtime prompt/tool policy
 * is resolved in `runtime/resolver.ts`.
 */

import { existsSync, mkdirSync, readdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { inflateRawSync } from "node:zlib";
import { dirname, join } from "node:path";
import * as paths from "@/paths";

export interface SkillConfigDict {
  id: number | null;
  name: string;
  system_prompt_template: string;
  tool_allowlist_json: string | null;
  tool_denylist_json: string | null;
  model_override: string | null;
  temperature_override: number | null;
}

export interface InstalledSkill {
  name: string;
  path: string;
  installed: boolean;
}

interface ZipEntry {
  name: string;
  compressedSize: number;
  uncompressedSize: number;
  method: number;
  flags: number;
  externalAttrs: number;
  localHeaderOffset: number;
  directory: boolean;
}

const MAX_SKILL_ZIP_BYTES = 50 * 1024 * 1024;
const MAX_SKILL_UNCOMPRESSED_BYTES = 20 * 1024 * 1024;

function isDir(p: string): boolean {
  try {
    return statSync(p).isDirectory();
  } catch {
    return false;
  }
}

function isFile(p: string): boolean {
  try {
    return statSync(p).isFile();
  } catch {
    return false;
  }
}

function validSkillName(name: string): boolean {
  return /^[A-Za-z0-9_.-]+$/.test(name);
}

/** Return the skill directory for `name`, local taking precedence. */
function skillDir(name: string): string | null {
  for (const base of [paths.localSkillsDir(), paths.globalSkillsDir()]) {
    const candidate = join(base, name);
    if (isDir(candidate)) return candidate;
  }
  return null;
}

/** Return available skill names, with local skills taking precedence. */
export function listAvailableSkills(): string[] {
  const found: string[] = [];
  const seen = new Set<string>();
  for (const base of [paths.localSkillsDir(), paths.globalSkillsDir()]) {
    if (!existsSync(base)) continue;
    const entries = readdirSync(base).sort();
    for (const entry of entries) {
      const candidate = join(base, entry);
      if (isDir(candidate) && isFile(join(candidate, "SKILL.md")) && !seen.has(entry)) {
        seen.add(entry);
        found.push(entry);
      }
    }
  }
  return found;
}

export function installSkillFromZip(
  zipPath: string,
  options: { targetDir?: string; name?: string } = {},
): InstalledSkill {
  const sourcePath = zipPath.trim();
  if (!sourcePath) throw new Error("Skill zip path is required.");
  if (!sourcePath.toLowerCase().endsWith(".zip")) throw new Error("Skill upload must be a .zip file.");
  if (!isFile(sourcePath)) throw new Error(`Skill zip does not exist: ${sourcePath}`);

  const stat = statSync(sourcePath);
  if (stat.size <= 0) throw new Error("Skill zip is empty.");
  if (stat.size > MAX_SKILL_ZIP_BYTES) throw new Error("Skill zip is too large.");

  const archive = readFileSync(sourcePath);
  const entries = readZipCentralDirectory(archive);
  const skillMdEntries = entries.filter((entry) => !entry.directory && zipBaseName(entry.name).toLowerCase() === "skill.md");
  if (skillMdEntries.length === 0) throw new Error("Skill zip must contain a SKILL.md file.");
  if (skillMdEntries.length > 1) throw new Error("Skill zip must contain exactly one SKILL.md file.");

  const skillMd = skillMdEntries[0]!;
  const prefix = zipDirName(skillMd.name);
  const explicitName = options.name?.trim() ?? "";
  const skillName = explicitName || (prefix ? zipBaseName(prefix) : "");
  if (!skillName) throw new Error("Skill name is required when SKILL.md is at the zip root.");
  if (!validSkillName(skillName)) {
    throw new Error("Skill name may only contain letters, numbers, dot, dash, and underscore.");
  }

  const targetBase = options.targetDir ?? paths.localSkillsDir();
  const skillDir = join(targetBase, skillName);
  const skillPath = join(skillDir, "SKILL.md");
  if (existsSync(skillPath) && isFile(skillPath)) {
    return { name: skillName, path: skillPath, installed: false };
  }

  let totalUncompressed = 0;
  const files: Array<{ relativePath: string; data: Uint8Array }> = [];
  for (const entry of entries) {
    if (entry.directory) continue;
    if (prefix && !(entry.name === prefix || entry.name.startsWith(`${prefix}/`))) continue;
    if (!prefix && entry.name.includes("/")) continue;

    const relativePath = prefix ? entry.name.slice(prefix.length).replace(/^\/+/, "") : entry.name;
    if (!relativePath || !isSafeZipRelativePath(relativePath)) continue;
    totalUncompressed += entry.uncompressedSize;
    if (totalUncompressed > MAX_SKILL_UNCOMPRESSED_BYTES) {
      throw new Error("Skill zip expands to too much data.");
    }
    files.push({ relativePath, data: readZipEntryData(archive, entry) });
  }

  if (!files.some((file) => file.relativePath.toLowerCase() === "skill.md")) {
    throw new Error("Skill zip must contain SKILL.md in the selected skill directory.");
  }

  for (const file of files) {
    const output = join(skillDir, ...file.relativePath.split("/"));
    mkdirSync(dirname(output), { recursive: true });
    writeFileSync(output, file.data);
  }
  return { name: skillName, path: skillPath, installed: true };
}

/** Parse an inline frontmatter value: JSON list, number, or string. */
function parseScalar(raw: string): unknown {
  if (raw.startsWith("[") && raw.endsWith("]")) {
    try {
      return JSON.parse(raw);
    } catch {
      return [];
    }
  }
  if (/^-?\d+$/.test(raw)) return parseInt(raw, 10);
  if (/^-?\d*\.\d+$/.test(raw)) return parseFloat(raw);
  return raw.trim().replace(/^["']|["']$/g, "");
}

/** Split optional `---` frontmatter from the markdown body. */
function splitFrontmatter(text: string): [Record<string, unknown>, string] {
  if (!text.startsWith("---")) return [{}, text];
  const parts = text.split("---");
  // text.split("---", 2) in Python keeps the remainder; emulate maxsplit=2.
  if (parts.length < 3) return [{}, text];
  const frontmatter = parts[1]!;
  const body = parts.slice(2).join("---");
  const meta: Record<string, unknown> = {};
  for (const rawLine of frontmatter.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || line.startsWith("#") || !line.includes(":")) continue;
    const idx = line.indexOf(":");
    const key = line.slice(0, idx).trim();
    const value = line.slice(idx + 1).trim();
    meta[key] = parseScalar(value);
  }
  return [meta, body.replace(/^\n+/, "")];
}

/** Load a skill directory by name into a runtime skill-config dict. */
export function loadSkill(name: string): SkillConfigDict | null {
  const dir = skillDir(name);
  if (dir === null) return null;
  const md = join(dir, "SKILL.md");
  if (!isFile(md)) return null;

  const [meta, body] = splitFrontmatter(readFileSync(md, "utf-8"));
  const allow = meta.tools_allow;
  const deny = meta.tools_deny;
  return {
    id: null,
    name,
    system_prompt_template: body.trim(),
    tool_allowlist_json: Array.isArray(allow) && allow.length ? JSON.stringify(allow) : null,
    tool_denylist_json: Array.isArray(deny) && deny.length ? JSON.stringify(deny) : null,
    model_override: (meta.model as string | undefined) || null,
    temperature_override:
      typeof meta.temperature === "number" ? meta.temperature : null,
  };
}

/** Load and merge multiple skills into one combined skill-config dict. */
export function loadSkills(names: string[]): SkillConfigDict | null {
  const loaded = names.map(loadSkill).filter((s): s is SkillConfigDict => s !== null);
  if (loaded.length === 0) return null;
  if (loaded.length === 1) return loaded[0]!;

  const prompts: string[] = [];
  const allow = new Set<string>();
  const deny = new Set<string>();
  let model: string | null = null;
  let temp: number | null = null;
  for (const skill of loaded) {
    if (skill.system_prompt_template) prompts.push(skill.system_prompt_template);
    if (skill.tool_allowlist_json) {
      for (const t of JSON.parse(skill.tool_allowlist_json) as string[]) allow.add(t);
    }
    if (skill.tool_denylist_json) {
      for (const t of JSON.parse(skill.tool_denylist_json) as string[]) deny.add(t);
    }
    model = model || skill.model_override;
    temp = temp !== null ? temp : skill.temperature_override;
  }

  return {
    id: null,
    name: loaded.map((s) => s.name).join("+"),
    system_prompt_template: prompts.join("\n\n---\n\n"),
    tool_allowlist_json: allow.size ? JSON.stringify([...allow].sort()) : null,
    tool_denylist_json: deny.size ? JSON.stringify([...deny].sort()) : null,
    model_override: model,
    temperature_override: temp,
  };
}

function readZipCentralDirectory(archive: Buffer): ZipEntry[] {
  const eocdOffset = findEndOfCentralDirectory(archive);
  if (eocdOffset < 0) throw new Error("Invalid zip: missing end of central directory.");
  const entryCount = archive.readUInt16LE(eocdOffset + 10);
  const centralDirSize = archive.readUInt32LE(eocdOffset + 12);
  const centralDirOffset = archive.readUInt32LE(eocdOffset + 16);
  if (centralDirOffset + centralDirSize > archive.length) throw new Error("Invalid zip: central directory is out of bounds.");

  const entries: ZipEntry[] = [];
  let offset = centralDirOffset;
  for (let i = 0; i < entryCount; i += 1) {
    if (archive.readUInt32LE(offset) !== 0x02014b50) throw new Error("Invalid zip: malformed central directory.");
    const flags = archive.readUInt16LE(offset + 8);
    const method = archive.readUInt16LE(offset + 10);
    const compressedSize = archive.readUInt32LE(offset + 20);
    const uncompressedSize = archive.readUInt32LE(offset + 24);
    const nameLength = archive.readUInt16LE(offset + 28);
    const extraLength = archive.readUInt16LE(offset + 30);
    const commentLength = archive.readUInt16LE(offset + 32);
    const externalAttrs = archive.readUInt32LE(offset + 38);
    const localHeaderOffset = archive.readUInt32LE(offset + 42);
    const name = archive.subarray(offset + 46, offset + 46 + nameLength).toString("utf-8").replace(/\\/g, "/");
    if (!isSafeZipEntryPath(name)) throw new Error(`Invalid zip entry path: ${name}`);
    if ((flags & 0x1) !== 0) throw new Error("Encrypted skill zips are not supported.");
    if (method !== 0 && method !== 8) throw new Error(`Unsupported zip compression method: ${method}`);
    if (compressedSize === 0xffffffff || uncompressedSize === 0xffffffff || localHeaderOffset === 0xffffffff) {
      throw new Error("Zip64 skill archives are not supported.");
    }
    if (isUnixSymlink(externalAttrs)) throw new Error(`Skill zip may not contain symlinks: ${name}`);
    entries.push({
      name,
      compressedSize,
      uncompressedSize,
      method,
      flags,
      externalAttrs,
      localHeaderOffset,
      directory: name.endsWith("/"),
    });
    offset += 46 + nameLength + extraLength + commentLength;
  }
  return entries;
}

function findEndOfCentralDirectory(archive: Buffer): number {
  const min = Math.max(0, archive.length - 0xffff - 22);
  for (let offset = archive.length - 22; offset >= min; offset -= 1) {
    if (archive.readUInt32LE(offset) === 0x06054b50) return offset;
  }
  return -1;
}

function readZipEntryData(archive: Buffer, entry: ZipEntry): Uint8Array {
  const offset = entry.localHeaderOffset;
  if (archive.readUInt32LE(offset) !== 0x04034b50) throw new Error(`Invalid zip: missing local header for ${entry.name}`);
  const nameLength = archive.readUInt16LE(offset + 26);
  const extraLength = archive.readUInt16LE(offset + 28);
  const dataOffset = offset + 30 + nameLength + extraLength;
  const dataEnd = dataOffset + entry.compressedSize;
  if (dataEnd > archive.length) throw new Error(`Invalid zip: entry data out of bounds for ${entry.name}`);
  const compressed = archive.subarray(dataOffset, dataEnd);
  const data = entry.method === 0 ? compressed : inflateRawSync(compressed);
  if (data.length !== entry.uncompressedSize) throw new Error(`Invalid zip: size mismatch for ${entry.name}`);
  return data;
}

function isSafeZipEntryPath(name: string): boolean {
  if (!name || name.startsWith("/") || name.startsWith("\\") || /^[A-Za-z]:/.test(name)) return false;
  const path = name.endsWith("/") ? name.slice(0, -1) : name;
  return path.split("/").every((part) => part !== "" && part !== "." && part !== "..");
}

function isSafeZipRelativePath(name: string): boolean {
  return isSafeZipEntryPath(name) && !name.endsWith("/");
}

function zipBaseName(name: string): string {
  const parts = name.replace(/\/+$/, "").split("/");
  return parts[parts.length - 1] ?? "";
}

function zipDirName(name: string): string {
  const normalized = name.replace(/\/+$/, "");
  const idx = normalized.lastIndexOf("/");
  return idx < 0 ? "" : normalized.slice(0, idx);
}

function isUnixSymlink(externalAttrs: number): boolean {
  const mode = (externalAttrs >>> 16) & 0o170000;
  return mode === 0o120000;
}
