/** Resolve workspace configuration into concrete agent run plans. */

import {
  type CliConfig,
  type McpServerConfig,
  type ProviderConfig,
  type RagConfig,
  AgentConfig,
  WILDCARD,
} from "@/config";
import { McpServerDTO, ModelProviderDTO } from "@/engine/dto";
import { ResolvedSkill, resolveSkill } from "@/engine/models";
import { buildSystemPrompt } from "@/engine/prompts";
import { subagentsForWorkflow } from "@/workflows";
import { listAvailableSkills, loadSkills, type SkillConfigDict } from "@/resources/skills";

const AUDIT_SKILL_DICT: SkillConfigDict = {
  id: null,
  name: "vuln-audit-workflow",
  system_prompt_template: "",
  tool_allowlist_json: null,
  tool_denylist_json: null,
  model_override: null,
  temperature_override: null,
};

export interface RunPlan {
  workflow: string;
  provider: ModelProviderDTO;
  enabledServers: McpServerDTO[];
  skill: ResolvedSkill | null;
  systemPrompt: string;
  subagentProviders: Record<string, ModelProviderDTO>;
  subagentMcpAllow: Record<string, string[] | null>;
  subagentSkills: Record<string, ResolvedSkill | null>;
  rag: RagConfig;
}

/** Converts config files into the policy needed for one agent run. */
export class RuntimePolicyResolver {
  constructor(private readonly config: CliConfig) {}

  providerFor(workflow: string, subagent: string | null = null): ProviderConfig {
    const agent = this.agentFor(workflow, subagent);
    return this.model(agent.model);
  }

  /** Return display-ready agent-name → model-id assignments. */
  modelAssignmentsFor(workflow: string): [string, string][] {
    const subagents = subagentsForWorkflow(workflow);
    if (subagents.length === 0) {
      const provider = this.providerFor(workflow);
      return [["primary", provider.modelName || "not configured"]];
    }
    return subagents.map(
      (name) => [name, this.providerFor(workflow, name).modelName || "not configured"] as [string, string],
    );
  }

  resolve(workflow: string): RunPlan {
    const subagents = subagentsForWorkflow(workflow);
    const configuredSkill = loadSkills(this.skillNamesFor(workflow));
    const skillDict =
      workflow === "audit" || workflow === "audit-slim"
        ? mergeSkillDicts(AUDIT_SKILL_DICT, configuredSkill)
        : configuredSkill;
    const skill = resolveSkill((skillDict ?? undefined) as Record<string, unknown> | undefined);

    const subagentSkills: Record<string, ResolvedSkill | null> = {};
    const subagentProviders: Record<string, ModelProviderDTO> = {};
    const subagentMcpAllow: Record<string, string[] | null> = {};
    for (const name of subagents) {
      subagentSkills[name] = resolveSkill(
        (loadSkills(this.skillNamesFor(workflow, name)) ?? undefined) as Record<string, unknown> | undefined,
      );
      subagentProviders[name] = providerToDto(this.providerFor(workflow, name));
      subagentMcpAllow[name] = this.mcpAllowFor(workflow, name);
    }

    return {
      workflow,
      provider: providerToDto(this.providerFor(workflow)),
      enabledServers: this.workflowServers(workflow, subagents),
      skill,
      systemPrompt: buildSystemPrompt(skill, null, workflow),
      subagentProviders,
      subagentMcpAllow,
      subagentSkills,
      rag: this.config.rag,
    };
  }

  private agentFor(workflow: string, subagent: string | null = null): AgentConfig {
    const names: string[] = [];
    if (subagent) names.push(`${workflow}.${subagent}`, subagent);
    names.push(workflow, "ruflo");

    for (const name of names) {
      for (const agent of this.config.agents) {
        if (agent.name === name) return agent;
      }
    }
    return new AgentConfig({ name: names[0] ?? "ruflo" });
  }

  private model(name: string | null = null): ProviderConfig {
    // The generated agents.toml uses model="default" for every workflow. In
    // Python Sarma, changing the active model makes those default routes follow
    // the selected provider. Treat "default" as the active-model alias here;
    // explicit non-default agent assignments still pin a workflow/subagent.
    const target = !name || name === "default" ? this.config.activeModel : name;
    for (const m of this.config.models) {
      if (m.name === target && m.enabled) return m;
    }
    for (const m of this.config.models) {
      if (m.enabled) return m;
    }
    return new AgentProviderFallback(target);
  }

  private skillNamesFor(workflow: string, subagent: string | null = null): string[] {
    const agent = this.agentFor(workflow, subagent);
    if (agent.skills.includes(WILDCARD)) {
      return listAvailableSkills();
    }
    return agent.skills.filter((name) => name !== WILDCARD);
  }

  private workflowServers(workflow: string, subagents: string[]): McpServerDTO[] {
    const allowed = new Set<string>();
    let includeAll = false;
    const agents = [this.agentFor(workflow), ...subagents.map((s) => this.agentFor(workflow, s))];
    for (const agent of agents) {
      if (agent.mcp.includes(WILDCARD)) {
        includeAll = true;
        break;
      }
      for (const m of agent.mcp) allowed.add(m);
    }
    return this.config.mcpServers
      .filter((server) => server.enabled && (includeAll || allowed.has(server.name)))
      .map(serverToDto);
  }

  private mcpAllowFor(workflow: string, subagent: string): string[] | null {
    const agent = this.agentFor(workflow, subagent);
    return agent.mcp.includes(WILDCARD) ? null : [...agent.mcp];
  }
}

/** ProviderConfig-shaped fallback when no enabled model is configured. */
class AgentProviderFallback {
  name: string;
  modelName = "";
  apiKey = "";
  baseUrl = "";
  apiMode = "openai_compatible";
  temperature = 0.0;
  topP = 1.0;
  maxContextTokens = 128_000;
  enabled = true;
  constructor(name: string) {
    this.name = name || "default";
  }
}

function providerToDto(provider: ProviderConfig): ModelProviderDTO {
  return new ModelProviderDTO({
    id: null,
    name: provider.name,
    modelName: provider.modelName,
    apiMode: provider.apiMode,
    apiKey: provider.apiKey,
    baseUrl: provider.baseUrl,
    temperature: provider.temperature,
    topP: provider.topP,
    maxContextTokens: provider.maxContextTokens,
    enabled: provider.enabled,
  });
}

function serverToDto(server: McpServerConfig): McpServerDTO {
  return new McpServerDTO({
    id: null,
    name: server.name,
    transport: server.transport,
    enabled: server.enabled,
    command: server.command,
    args: server.args,
    env: server.env,
    cwd: server.cwd,
    encoding: server.encoding,
    url: server.url,
    headers: server.headers,
    timeout: server.timeout,
    sseReadTimeout: server.sseReadTimeout,
  });
}

function loadJsonList(value: string | null | undefined): Set<string> {
  if (!value) return new Set();
  try {
    const parsed = JSON.parse(value);
    if (!Array.isArray(parsed)) return new Set();
    return new Set(parsed.map((x) => String(x)));
  } catch {
    return new Set();
  }
}

function mergeSkillDicts(
  base: SkillConfigDict | null,
  extra: SkillConfigDict | null,
): SkillConfigDict | null {
  if (!base) return extra;
  if (!extra) return base;

  const allow = loadJsonList(base.tool_allowlist_json);
  for (const t of loadJsonList(extra.tool_allowlist_json)) allow.add(t);
  const deny = loadJsonList(base.tool_denylist_json);
  for (const t of loadJsonList(extra.tool_denylist_json)) deny.add(t);

  const prompts = [base.system_prompt_template, extra.system_prompt_template].filter(Boolean);
  const names = [base.name, extra.name].filter(Boolean);

  return {
    id: null,
    name: names.join("+"),
    system_prompt_template: prompts.join("\n\n"),
    tool_allowlist_json: allow.size ? JSON.stringify([...allow].sort()) : null,
    tool_denylist_json: deny.size ? JSON.stringify([...deny].sort()) : null,
    model_override: base.model_override || extra.model_override,
    temperature_override:
      base.temperature_override !== null ? base.temperature_override : extra.temperature_override,
  };
}
