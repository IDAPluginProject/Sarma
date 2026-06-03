"""Plugin resource helpers for MCP presets and skill installation.

This module owns configuration-side plugin operations only. It validates and
creates MCP config entries, installs skills from directories/zip files/URLs,
and provides a best-effort Skillshub search adapter. It does not render UI and
does not connect to MCP servers.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sarma_cli import paths
from sarma_cli.config import McpServerConfig

MCP_TRANSPORTS = ("stdio", "http", "sse")
DEFAULT_SKILLSHUB_URL = "https://skillshub.wtf"


@dataclass(frozen=True)
class SkillSearchResult:
    name: str
    description: str = ""
    url: str = ""


def list_mcp_quick_modes() -> list[str]:
    """Return supported MCP quick-create modes."""
    return list(MCP_TRANSPORTS)


def create_mcp_server(
    *,
    name: str,
    transport: str,
    url: str = "",
    command: str = "",
    args: str = "",
    env: str = "",
    cwd: str = "",
    headers: str = "",
    enabled: bool = True,
) -> McpServerConfig:
    """Create a validated MCP server config."""
    server = McpServerConfig(
        name=name.strip(),
        transport=_normalize_transport(transport),
        url=url.strip(),
        command=command.strip(),
        args=args.strip(),
        env=env.strip(),
        cwd=cwd.strip(),
        headers=headers.strip(),
        enabled=enabled,
    )
    errors = validate_mcp_server(server)
    if errors:
        raise ValueError("; ".join(errors))
    return server


def validate_mcp_server(server: McpServerConfig) -> list[str]:
    """Return validation errors for an MCP server config."""
    errors: list[str] = []
    if not server.name.strip():
        errors.append("MCP name is required")
    if _normalize_transport(server.transport) not in MCP_TRANSPORTS:
        errors.append("MCP transport must be stdio, http, or sse")
    if _normalize_transport(server.transport) == "stdio":
        if not server.command.strip():
            errors.append("stdio MCP requires a command")
        _validate_json(server.args, "args", list, errors)
        _validate_json(server.env, "env", dict, errors)
    else:
        if not server.url.strip():
            errors.append(f"{server.transport} MCP requires a URL")
        _validate_json(server.headers, "headers", dict, errors)
    return errors


def upsert_mcp_server(servers: list[McpServerConfig], server: McpServerConfig) -> None:
    """Insert or replace an MCP server config in a server list."""
    for index, existing in enumerate(servers):
        if existing.name == server.name:
            servers[index] = server
            return
    servers.append(server)


def skill_install_base(scope: str) -> Path:
    """Return the skill installation base for workspace or global scope."""
    if scope == "global":
        return paths.global_skills_dir()
    return paths.local_skills_dir()


def validate_skill_directory(source: Path) -> list[str]:
    """Return validation errors for a skill directory."""
    errors: list[str] = []
    if not source.is_dir():
        return ["Skill source must be a directory"]
    normalized = _find_skill_root(source)
    if normalized is None:
        errors.append("Skill directory or archive must contain SKILL.md")
    return errors


def install_skill_from_path(
    source: Path,
    *,
    scope: str = "workspace",
    name: str = "",
    overwrite: bool = True,
) -> Path:
    """Install a skill from a local directory or .zip archive."""
    source = source.expanduser().resolve()
    if source.is_file() and source.suffix.lower() == ".zip":
        return install_skill_from_zip(source, scope=scope, name=name, overwrite=overwrite)
    if source.is_file() and source.name == "SKILL.md":
        source = source.parent
    return _install_skill_tree(source, scope=scope, name=name, overwrite=overwrite)


def install_skill_from_zip(
    archive: Path,
    *,
    scope: str = "workspace",
    name: str = "",
    overwrite: bool = True,
) -> Path:
    """Install a skill from a local zip archive."""
    archive = archive.expanduser().resolve()
    if not archive.is_file():
        raise ValueError(f"Skill zip not found: {archive}")
    with tempfile.TemporaryDirectory(prefix="sarma-skill-") as tmp:
        tmp_dir = Path(tmp)
        _safe_extract_zip(archive, tmp_dir)
        return _install_skill_tree(
            tmp_dir,
            scope=scope,
            name=name or archive.stem,
            overwrite=overwrite,
        )


def install_skill_from_url(
    url: str,
    *,
    scope: str = "workspace",
    name: str = "",
    overwrite: bool = True,
) -> Path:
    """Download and install a remote skill zip URL."""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Remote skill URL must use http or https")
    with tempfile.TemporaryDirectory(prefix="sarma-skill-download-") as tmp:
        archive = Path(tmp) / "skill.zip"
        with urllib.request.urlopen(url, timeout=30) as response:
            archive.write_bytes(response.read())
        return install_skill_from_zip(
            archive,
            scope=scope,
            name=name or _name_from_url(url),
            overwrite=overwrite,
        )


def search_skillshub(
    query: str,
    *,
    registry_url: str = DEFAULT_SKILLSHUB_URL,
    limit: int = 20,
) -> list[SkillSearchResult]:
    """Best-effort search against a Skillshub-compatible registry."""
    query = query.strip()
    if not query:
        return []
    base = registry_url.rstrip("/")
    endpoints = [
        f"{base}/api/v1/skills/search?q={urllib.parse.quote(query)}",
        f"{base}/api/v1/skills?search={urllib.parse.quote(query)}",
    ]
    last_error: Exception | None = None
    for endpoint in endpoints:
        try:
            with urllib.request.urlopen(endpoint, timeout=15) as response:
                data = json.loads(response.read().decode("utf-8"))
            return _parse_skill_search_results(data, limit=limit)
        except Exception as exc:
            last_error = exc
    if last_error:
        raise ValueError(f"Skillshub search failed: {last_error}")
    return []


def _install_skill_tree(
    source: Path,
    *,
    scope: str,
    name: str,
    overwrite: bool,
) -> Path:
    source = source.expanduser().resolve()
    skill_root = _find_skill_root(source)
    if skill_root is None:
        raise ValueError("Skill source must contain SKILL.md")
    skill_name = _safe_skill_name(name or skill_root.name)
    target = skill_install_base(scope) / skill_name
    if target.exists():
        if not overwrite:
            return target
        shutil.rmtree(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(skill_root, target)
    errors = validate_skill_directory(target)
    if errors:
        shutil.rmtree(target, ignore_errors=True)
        raise ValueError("; ".join(errors))
    return target


def _find_skill_root(source: Path) -> Path | None:
    if (source / "SKILL.md").is_file():
        return source
    children = [child for child in source.iterdir() if child.is_dir()]
    if len(children) == 1 and (children[0] / "SKILL.md").is_file():
        return children[0]
    return None


def _safe_extract_zip(archive: Path, target: Path) -> None:
    root = target.resolve()
    with zipfile.ZipFile(archive) as zf:
        for member in zf.infolist():
            destination = (target / member.filename).resolve()
            try:
                destination.relative_to(root)
            except ValueError:
                raise ValueError("Skill zip contains unsafe paths")
        zf.extractall(target)


def _validate_json(
    value: str,
    label: str,
    expected_type: type,
    errors: list[str],
) -> None:
    if not value.strip():
        return
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        errors.append(f"{label} must be valid JSON")
        return
    if not isinstance(parsed, expected_type):
        errors.append(f"{label} must be a JSON {expected_type.__name__}")


def _normalize_transport(value: str) -> str:
    transport = value.strip().lower() or "stdio"
    if transport == "streamable_http":
        return "http"
    return transport


def _parse_skill_search_results(data: Any, *, limit: int) -> list[SkillSearchResult]:
    if isinstance(data, dict):
        raw_items = (
            data.get("skills")
            or data.get("items")
            or data.get("results")
            or data.get("data")
            or []
        )
    else:
        raw_items = data
    if not isinstance(raw_items, list):
        return []

    results: list[SkillSearchResult] = []
    for item in raw_items[:limit]:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or item.get("slug") or item.get("id") or "").strip()
        if not name:
            continue
        url = str(
            item.get("download_url")
            or item.get("archive_url")
            or item.get("zip_url")
            or item.get("url")
            or item.get("html_url")
            or ""
        )
        results.append(SkillSearchResult(
            name=name,
            description=str(item.get("description") or item.get("summary") or ""),
            url=url,
        ))
    return results


def _safe_skill_name(value: str) -> str:
    name = "".join(ch if ch.isalnum() or ch in ("-", "_", ".") else "-" for ch in value)
    return name.strip(".-_") or "skill"


def _name_from_url(url: str) -> str:
    path = urllib.parse.urlparse(url).path
    stem = Path(path).stem
    return _safe_skill_name(stem or "skill")
