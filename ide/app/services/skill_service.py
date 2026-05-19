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


class SkillService:
    def __init__(self, settings_service: SettingsService | None = None) -> None:
        self._settings_service = settings_service or SettingsService()

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
