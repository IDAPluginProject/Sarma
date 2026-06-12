/**
 * Skill loading for installed SKILL.md directories.
 *
 * A skill is a directory under `~/.sarma/skills/<name>` (global) or
 * `./.sarma/skills/<name>` (workspace) containing a `SKILL.md` file. This
 * module only discovers and parses skill resources; runtime prompt/tool policy
 * is resolved in `runtime/resolver.ts`.
 */

import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
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
