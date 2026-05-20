"""Business logic for managing IDE skills."""

from __future__ import annotations

import json
import logging
import shutil
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from app.chat.models import ResolvedSkill
from app.services.settings_service import SettingsService

logger = logging.getLogger(__name__)

_NATIVE_SKILLS_DIR_NAME = "skills"


class SkillService:
    def __init__(self, settings_service: SettingsService | None = None) -> None:
        self._settings_service = settings_service or SettingsService()

    def seed_native_skills(self) -> None:
        """Register built-in skills from the bundled skills/ directory.

        Scans each subdirectory for a SKILL.md (with YAML frontmatter) or
        skill.json manifest. Skips skills already registered by name.
        """
        try:
            native_dir = self._get_native_skills_source()
            if not native_dir or not native_dir.is_dir():
                logger.debug("No native skills directory found")
                return

            existing_names = {s.name for s in self._settings_service.get_skills()}
            skills_dir = self._settings_service.get_skills_dir()
            skills_dir.mkdir(parents=True, exist_ok=True)

            for entry in sorted(native_dir.iterdir()):
                if not entry.is_dir():
                    continue
                meta = self._read_skill_metadata(entry)
                if not meta:
                    continue
                name = meta["name"]
                if name in existing_names:
                    continue

                dest = skills_dir / name
                if not dest.exists():
                    shutil.copytree(entry, dest)

                now = datetime.now(timezone.utc).isoformat()
                self._settings_service.add_skill(
                    name=name,
                    description=meta.get("description", ""),
                    version=meta.get("version", ""),
                    file_path="",
                    install_dir=name,
                    installed_at=now,
                )
                logger.info("Seeded native skill: %s", name)
        except Exception as exc:
            logger.error("Failed to seed native skills: %s", exc)

    @staticmethod
    def _get_native_skills_source() -> Path | None:
        """Locate the bundled skills/ directory relative to the project root."""
        import sys

        candidates = [
            Path(__file__).resolve().parents[3] / _NATIVE_SKILLS_DIR_NAME,
            Path(__file__).resolve().parents[2] / _NATIVE_SKILLS_DIR_NAME,
            Path(sys.argv[0]).resolve().parent / _NATIVE_SKILLS_DIR_NAME,
            Path(sys.argv[0]).resolve().parent.parent / _NATIVE_SKILLS_DIR_NAME,
            Path.cwd() / _NATIVE_SKILLS_DIR_NAME,
            Path.cwd().parent / _NATIVE_SKILLS_DIR_NAME,
        ]
        for c in candidates:
            if c.is_dir():
                return c
        return None

    @staticmethod
    def _read_skill_metadata(skill_dir: Path) -> dict[str, str] | None:
        """Read skill name/description from skill.json or SKILL.md frontmatter."""
        manifest = skill_dir / "skill.json"
        if manifest.exists():
            try:
                data = json.loads(manifest.read_text(encoding="utf-8"))
                if data.get("name"):
                    return data
            except (json.JSONDecodeError, OSError):
                pass

        skill_md = skill_dir / "SKILL.md"
        if skill_md.exists():
            try:
                text = skill_md.read_text(encoding="utf-8")
                return _parse_skill_md_frontmatter(text)
            except OSError:
                pass
        return None

    def import_skill_zip(self, zip_path: str | Path) -> dict[str, Any]:
        """Import a skill package ZIP and persist its metadata."""
        zip_path = Path(zip_path)
        file_name = zip_path.name

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            with zipfile.ZipFile(zip_path, "r") as zf:
                for info in zf.infolist():
                    name = info.filename
                    if (
                        ".." in name
                        or name.startswith(("/", "\\"))
                        or PurePosixPath(name).is_absolute()
                        or PureWindowsPath(name).is_absolute()
                    ):
                        raise ValueError(f"Invalid path in ZIP: {name}")
                zf.extractall(tmp)

            manifest = None
            skill_root = tmp
            for candidate in (tmp / "skill.json", tmp / "package.json"):
                if candidate.exists():
                    manifest = json.loads(candidate.read_text(encoding="utf-8"))
                    break

            if manifest is None:
                for subdir in tmp.iterdir():
                    if subdir.is_dir():
                        for candidate in (subdir / "skill.json", subdir / "package.json"):
                            if candidate.exists():
                                manifest = json.loads(candidate.read_text(encoding="utf-8"))
                                skill_root = subdir
                                break
                        if manifest:
                            break

            skill_name = manifest.get("name", "") if manifest else zip_path.stem
            if not skill_name:
                skill_name = zip_path.stem
            skill_description = manifest.get("description", "") if manifest else ""
            skill_version = manifest.get("version", "") if manifest else ""

            safe_name = "".join(
                c if c.isalnum() or c in ("-", "_") else "_" for c in skill_name
            )
            install_dir_name = safe_name

            skills_dir = self._settings_service.get_skills_dir()
            dest = skills_dir / install_dir_name
            if dest.exists():
                shutil.rmtree(dest)
            shutil.copytree(skill_root, dest)

        now = datetime.now(timezone.utc).isoformat()
        skill_id = self._settings_service.add_skill(
            name=skill_name,
            description=skill_description,
            version=skill_version,
            file_path=file_name,
            install_dir=install_dir_name,
            installed_at=now,
        )
        return {
            "id": skill_id,
            "name": skill_name,
            "description": skill_description,
            "version": skill_version,
            "file_path": file_name,
            "install_dir": install_dir_name,
            "installed_at": now,
        }

    def delete_skill(self, skill_id: int, install_dir: str | None) -> None:
        """Remove a skill record and its installed files."""
        self._settings_service.remove_skill(skill_id)

        if install_dir:
            try:
                skills_dir = self._settings_service.get_skills_dir()
                dest = skills_dir / install_dir
                if dest.exists():
                    shutil.rmtree(dest)
            except Exception:
                pass

    def save_skill_advanced(
        self,
        skill_id: int,
        *,
        system_prompt_template: str,
        tool_allowlist: str,
        tool_denylist: str,
        model_override: str,
        temperature_override: float,
    ) -> bool:
        """Serialize and persist advanced skill settings."""
        allow_text = tool_allowlist.strip()
        allow_json_val = (
            json.dumps([t.strip() for t in allow_text.split(",") if t.strip()])
            if allow_text else None
        )
        deny_text = tool_denylist.strip()
        deny_json_val = (
            json.dumps([t.strip() for t in deny_text.split(",") if t.strip()])
            if deny_text else None
        )
        model_val = model_override.strip() or ""
        temp_val = temperature_override if temperature_override > 0 else None

        return self._settings_service.update_skill(
            skill_id,
            system_prompt_template=system_prompt_template,
            tool_allowlist_json=allow_json_val,
            tool_denylist_json=deny_json_val,
            model_override=model_val,
            temperature_override=temp_val,
        )

    # --- Runtime resolution (formerly in skill_resolver.py) ---

    def resolve(self, skill_id: int) -> ResolvedSkill | None:
        """Load a single skill by id and return a ResolvedSkill."""
        for dto in self._settings_service.get_skills():
            if dto.id == skill_id and dto.enabled:
                return self._to_resolved(dto)
        return None

    def list_available(self) -> list[dict]:
        """Return all enabled skills as lightweight dicts for the selector UI."""
        result: list[dict] = []
        for dto in self._settings_service.get_skills():
            if dto.enabled:
                result.append({
                    "id": dto.id,
                    "name": dto.name,
                    "description": dto.description,
                })
        return result

    @staticmethod
    def _to_resolved(dto: Any) -> ResolvedSkill:
        allowlist: set[str] | None = None
        denylist: set[str] | None = None
        if dto.tool_allowlist_json:
            try:
                allowlist = set(json.loads(dto.tool_allowlist_json))
            except (json.JSONDecodeError, TypeError):
                logger.warning("Invalid tool_allowlist_json for skill %s", dto.name)
        if dto.tool_denylist_json:
            try:
                denylist = set(json.loads(dto.tool_denylist_json))
            except (json.JSONDecodeError, TypeError):
                logger.warning("Invalid tool_denylist_json for skill %s", dto.name)
        return ResolvedSkill(
            id=dto.id,
            name=dto.name,
            system_prompt_suffix=dto.system_prompt_template,
            tool_allowlist=allowlist,
            tool_denylist=denylist,
            preferred_model_name=dto.model_override or None,
            temperature_override=dto.temperature_override,
        )


def _parse_skill_md_frontmatter(text: str) -> dict[str, str] | None:
    """Extract name/description from YAML frontmatter in SKILL.md."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    meta: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if ":" in line:
            key, _, value = line.partition(":")
            meta[key.strip()] = value.strip()
    return meta if meta.get("name") else None
