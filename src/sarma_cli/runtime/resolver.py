"""Resolve workspace configuration into concrete agent run plans."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from sarma_cli.config import CliConfig, McpServerConfig, ProviderConfig, RagConfig, WILDCARD
from sarma_cli.engine.dto import McpServerDTO, ModelProviderDTO
from sarma_cli.engine.models import ResolvedSkill, resolve_skill
from sarma_cli.engine.prompts import build_system_prompt

_AUDIT_SKILL_DICT: dict[str, Any] = {
    "id": None,
    "name": "vuln-audit-workflow",
    "system_prompt_template": "",
    "tool_allowlist_json": None,
    "tool_denylist_json": None,
    "model_override": None,
    "temperature_override": None,
}


@dataclass(slots=True)
class RunPlan:
    workflow: str
    provider: ModelProviderDTO
    enabled_servers: list[McpServerDTO]
    skill: ResolvedSkill | None
    system_prompt: str
    subagent_providers: dict[str, ModelProviderDTO]
    subagent_mcp_allow: dict[str, list[str] | None]
    subagent_skills: dict[str, ResolvedSkill | None]
    rag: RagConfig


class RuntimePolicyResolver:
    """Converts config files into the policy needed for one agent run."""

    def __init__(self, config: CliConfig) -> None:
        self._config = config

    def provider_for(self, workflow: str, subagent: str | None = None) -> ProviderConfig:
        agent = self._agent_for(workflow, subagent)
        return self._model(agent.model or self._config.active_model)

    def model_assignments_for(self, workflow: str) -> list[tuple[str, str]]:
        """Return display-ready agent name to model id assignments."""
        subagents = _subagents_for_workflow(workflow)
        if not subagents:
            provider = self.provider_for(workflow)
            return [("primary", provider.model_name or "not configured")]
        return [
            (name, self.provider_for(workflow, name).model_name or "not configured")
            for name in subagents
        ]

    def resolve(self, workflow: str) -> RunPlan:
        from sarma_cli.resources.skills import load_skills

        subagents = _subagents_for_workflow(workflow)
        configured_skill = load_skills(self._skill_names_for(workflow))
        skill_dict = (
            _merge_skill_dicts(_AUDIT_SKILL_DICT, configured_skill)
            if workflow in ("audit", "audit-slim")
            else configured_skill
        )
        skill = resolve_skill(skill_dict)

        subagent_skills = {
            name: resolve_skill(load_skills(self._skill_names_for(workflow, name)))
            for name in subagents
        }

        return RunPlan(
            workflow=workflow,
            provider=_provider_to_dto(self.provider_for(workflow)),
            enabled_servers=self._workflow_servers(workflow, subagents),
            skill=skill,
            system_prompt=build_system_prompt(skill=skill, mode=workflow),
            subagent_providers={
                name: _provider_to_dto(self.provider_for(workflow, name))
                for name in subagents
            },
            subagent_mcp_allow={
                name: self._mcp_allow_for(workflow, name)
                for name in subagents
            },
            subagent_skills=subagent_skills,
            rag=self._config.rag,
        )

    def _agent_for(self, workflow: str, subagent: str | None = None) -> Any:
        names: list[str] = []
        if subagent:
            names.extend([f"{workflow}.{subagent}", subagent])
        names.extend([workflow, "ruflo"])

        for name in names:
            for agent in self._config.agents:
                if agent.name == name:
                    return agent
        from sarma_cli.config import AgentConfig

        return AgentConfig(name=names[0] if names else "ruflo")

    def _model(self, name: str | None = None) -> ProviderConfig:
        target = name or self._config.active_model
        for model in self._config.models:
            if model.name == target and model.enabled:
                return model
        for model in self._config.models:
            if model.enabled:
                return model
        return ProviderConfig(name=target or "default")

    def _skill_names_for(self, workflow: str, subagent: str | None = None) -> list[str]:
        agent = self._agent_for(workflow, subagent)
        if WILDCARD in agent.skills:
            from sarma_cli.resources.skills import list_available_skills

            return list_available_skills()
        return [name for name in agent.skills if name != WILDCARD]

    def _workflow_servers(self, workflow: str, subagents: list[str]) -> list[McpServerDTO]:
        allowed: set[str] = set()
        include_all = False
        for agent in [self._agent_for(workflow), *[self._agent_for(workflow, s) for s in subagents]]:
            if WILDCARD in agent.mcp:
                include_all = True
                break
            allowed.update(agent.mcp)

        return [
            _server_to_dto(server)
            for server in self._config.mcp_servers
            if server.enabled and (include_all or server.name in allowed)
        ]

    def _mcp_allow_for(self, workflow: str, subagent: str) -> list[str] | None:
        agent = self._agent_for(workflow, subagent)
        return None if WILDCARD in agent.mcp else list(agent.mcp)


def _subagents_for_workflow(workflow: str) -> list[str]:
    from sarma_cli.workflows import get_registry, init_workflows

    init_workflows()
    registered = get_registry().get(workflow)
    return list(registered.subagents) if registered else []


def _provider_to_dto(provider: ProviderConfig) -> ModelProviderDTO:
    return ModelProviderDTO(
        id=None,
        name=provider.name,
        model_name=provider.model_name,
        api_mode=provider.api_mode,
        api_key=provider.api_key,
        base_url=provider.base_url,
        temperature=provider.temperature,
        top_p=provider.top_p,
        max_context_tokens=provider.max_context_tokens,
        enabled=provider.enabled,
    )


def _server_to_dto(server: McpServerConfig) -> McpServerDTO:
    return McpServerDTO(
        id=None,
        name=server.name,
        transport=server.transport,
        enabled=server.enabled,
        command=server.command,
        args=server.args,
        env=server.env,
        cwd=server.cwd,
        encoding=server.encoding,
        url=server.url,
        headers=server.headers,
        timeout=server.timeout,
        sse_read_timeout=server.sse_read_timeout,
    )


def _merge_skill_dicts(base: dict[str, Any] | None, extra: dict[str, Any] | None) -> dict[str, Any] | None:
    if not base:
        return extra
    if not extra:
        return base

    allow = _load_json_list(base.get("tool_allowlist_json"))
    allow.update(_load_json_list(extra.get("tool_allowlist_json")))
    deny = _load_json_list(base.get("tool_denylist_json"))
    deny.update(_load_json_list(extra.get("tool_denylist_json")))

    return {
        "id": None,
        "name": "+".join(filter(None, [base.get("name"), extra.get("name")])),
        "system_prompt_template": "\n\n".join(
            part
            for part in (
                base.get("system_prompt_template", ""),
                extra.get("system_prompt_template", ""),
            )
            if part
        ),
        "tool_allowlist_json": json.dumps(sorted(allow)) if allow else None,
        "tool_denylist_json": json.dumps(sorted(deny)) if deny else None,
        "model_override": base.get("model_override") or extra.get("model_override"),
        "temperature_override": (
            base.get("temperature_override")
            if base.get("temperature_override") is not None
            else extra.get("temperature_override")
        ),
    }


def _load_json_list(value: Any) -> set[str]:
    if not value:
        return set()
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return set()
    if not isinstance(parsed, list):
        return set()
    return {str(item) for item in parsed}
