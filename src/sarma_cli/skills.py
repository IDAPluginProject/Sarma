"""Skill loading — read skill directories into skill-config dicts.

A skill is a directory under ``~/.sarma/skills/<name>`` (global) or
``./.sarma/skills/<name>`` (local) containing a ``SKILL.md`` file. The file
may start with an optional YAML-ish frontmatter block delimited by ``---``:

    ---
    model: gpt-4o
    temperature: 0.3
    tools_allow: ["decompile", "disasm"]
    tools_deny: []
    ---
    <markdown body used as the system-prompt overlay>

Only simple scalar / inline-list frontmatter is supported (no PyYAML
dependency). The body becomes ``system_prompt_template``.
"""

from __future__ import annotations

import json
from typing import Any

from sarma_cli import paths


def _skill_dir(name: str) -> Any:
    """Return the skill directory Path for ``name``, local taking precedence."""
    for base in (paths.local_skills_dir(), paths.global_skills_dir()):
        candidate = base / name
        if candidate.is_dir():
            return candidate
    return None


def _split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Split optional ``---`` frontmatter from the markdown body."""
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    meta: dict[str, Any] = {}
    for line in parts[1].splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, _, raw = line.partition(":")
        meta[key.strip()] = _parse_scalar(raw.strip())
    return meta, parts[2].lstrip("\n")


def _parse_scalar(raw: str) -> Any:
    """Parse an inline frontmatter value: JSON list, number, or string."""
    if raw.startswith("[") and raw.endswith("]"):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return []
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        pass
    return raw.strip().strip('"').strip("'")


def load_skill(name: str) -> dict[str, Any] | None:
    """Load a skill directory by name into a skill-config dict.

    Returns a dict matching what ``resolve_skill`` expects, or ``None`` if the
    skill directory or its ``SKILL.md`` is missing.
    """
    skill_dir = _skill_dir(name)
    if skill_dir is None:
        return None
    md = skill_dir / "SKILL.md"
    if not md.is_file():
        return None

    meta, body = _split_frontmatter(md.read_text(encoding="utf-8"))

    allow = meta.get("tools_allow")
    deny = meta.get("tools_deny")
    return {
        "id": None,
        "name": name,
        "system_prompt_template": body.strip(),
        "tool_allowlist_json": json.dumps(allow) if isinstance(allow, list) and allow else None,
        "tool_denylist_json": json.dumps(deny) if isinstance(deny, list) and deny else None,
        "model_override": meta.get("model") or None,
        "temperature_override": meta.get("temperature"),
    }


def load_skills(names: list[str]) -> dict[str, Any] | None:
    """Load and merge multiple skills into one combined skill-config dict.

    Prompt overlays are concatenated; tool allow/deny lists are unioned; the
    first skill that specifies a model/temperature wins. Returns ``None`` if no
    named skill could be loaded.
    """
    loaded = [s for s in (load_skill(n) for n in names) if s]
    if not loaded:
        return None
    if len(loaded) == 1:
        return loaded[0]

    prompts: list[str] = []
    allow: set[str] = set()
    deny: set[str] = set()
    model: Any = None
    temp: Any = None
    for s in loaded:
        if s["system_prompt_template"]:
            prompts.append(s["system_prompt_template"])
        if s["tool_allowlist_json"]:
            allow.update(json.loads(s["tool_allowlist_json"]))
        if s["tool_denylist_json"]:
            deny.update(json.loads(s["tool_denylist_json"]))
        model = model or s["model_override"]
        temp = temp if temp is not None else s["temperature_override"]

    return {
        "id": None,
        "name": "+".join(s["name"] for s in loaded),
        "system_prompt_template": "\n\n---\n\n".join(prompts),
        "tool_allowlist_json": json.dumps(sorted(allow)) if allow else None,
        "tool_denylist_json": json.dumps(sorted(deny)) if deny else None,
        "model_override": model,
        "temperature_override": temp,
    }


