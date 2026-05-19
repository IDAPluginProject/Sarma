"""Supervisor API — stable contract for the IDE application layer.

The app layer must import from this module only; never from supervisor.manager
or supervisor.models directly. This keeps the boundary explicit and testable.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Protocol, runtime_checkable

from shared.dto import McpServerDTO, ModelProviderDTO, SkillDTO
from shared.models import ConfigStoreInfo, IdaMcpConfig
from supervisor.models import (
    DiaphoraInstallationCheck,
    DiaphoraInstallationResult,
    HealthReport,
    IdeConfig,
    InstallationActionResult,
    InstallationCheck,
    SupervisorSnapshot,
)


@runtime_checkable
class ISupervisorAPI(Protocol):
    """Contract that the IDE app layer depends on."""

    def get_snapshot(self, log: Callable[[str], None] | None = None) -> SupervisorSnapshot: ...
    def get_health_report(self, log: Callable[[str], None] | None = None) -> HealthReport: ...

    def get_ide_config(self) -> IdeConfig: ...
    def get_config(self) -> IdeConfig: ...
    def get_ida_mcp_config(self) -> IdaMcpConfig: ...
    def get_ide_config_store_info(self) -> ConfigStoreInfo: ...
    def get_ida_mcp_config_store_info(self) -> ConfigStoreInfo: ...
    def update_ide_config(self, **updates: object) -> IdeConfig: ...
    def update_config(self, **updates: object) -> IdeConfig: ...
    def update_ida_mcp_config(self, **updates: object) -> IdaMcpConfig: ...

    def start_gateway(self, log: Callable[[str], None] | None = None) -> SupervisorSnapshot: ...
    def stop_gateway(self, *, log: Callable[[str], None] | None = None) -> SupervisorSnapshot: ...

    def check_installation(self) -> InstallationCheck: ...
    def repair_installation(self) -> InstallationActionResult: ...
    def reinstall(self, *, on_progress: Callable[[str], None] | None = None) -> InstallationActionResult: ...
    def detect_ida_executable(self, ida_dir: str) -> str | None: ...
    def detect_ida_python(self, ida_dir: str) -> str | None: ...

    def check_diaphora_installation(self) -> DiaphoraInstallationCheck: ...
    def install_diaphora(self) -> DiaphoraInstallationResult: ...

    def get_model_providers(self) -> list[ModelProviderDTO]: ...
    def add_model_provider(self, name: str, base_url: str, api_key: str, api_mode: str,
                           model_name: str, max_context_tokens: int, top_p: float,
                           temperature: float, *, enabled: bool) -> int: ...
    def update_model_provider(self, provider_id: int, **updates: object) -> bool: ...
    def remove_model_provider(self, provider_id: int) -> bool: ...

    def get_mcp_servers(self) -> list[McpServerDTO]: ...
    def add_mcp_server(self, name: str, transport: str, *, enabled: bool, command: str,
                       args: str, env: str, cwd: str, encoding: str, url: str,
                       headers: str, timeout: float, sse_read_timeout: float) -> int: ...
    def update_mcp_server(self, server_id: int, **updates: object) -> bool: ...
    def remove_mcp_server(self, server_id: int) -> bool: ...

    def get_skills(self) -> list[SkillDTO]: ...
    def add_skill(self, name: str, description: str, *, enabled: bool, version: str,
                  file_path: str, install_dir: str, installed_at: str) -> int: ...
    def update_skill(self, skill_id: int, **updates: object) -> bool: ...
    def remove_skill(self, skill_id: int) -> bool: ...
    def get_skills_dir(self) -> Path: ...


class SupervisorAPIImpl:
    """In-process implementation backed by SupervisorManager."""

    def __init__(self) -> None:
        from supervisor.manager import SupervisorManager
        self._manager = SupervisorManager()

    def get_snapshot(self, log=None) -> SupervisorSnapshot:
        return self._manager.get_snapshot(log=log)

    def get_health_report(self, log=None) -> HealthReport:
        return self._manager.get_health_report(log=log)

    def get_ide_config(self) -> IdeConfig:
        return self._manager.get_ide_config()

    def get_config(self) -> IdeConfig:
        return self._manager.get_config()

    def get_ida_mcp_config(self) -> IdaMcpConfig:
        return self._manager.get_ida_mcp_config()

    def get_ide_config_store_info(self) -> ConfigStoreInfo:
        return self._manager.get_ide_config_store_info()

    def get_ida_mcp_config_store_info(self) -> ConfigStoreInfo:
        return self._manager.get_ida_mcp_config_store_info()

    def update_ide_config(self, **updates: object) -> IdeConfig:
        return self._manager.update_ide_config(**updates)

    def update_config(self, **updates: object) -> IdeConfig:
        return self._manager.update_config(**updates)

    def update_ida_mcp_config(self, **updates: object) -> IdaMcpConfig:
        return self._manager.update_ida_mcp_config(**updates)

    def start_gateway(self, log=None) -> SupervisorSnapshot:
        self._manager.start_gateway(log=log)
        return self._manager.get_snapshot(log=log)

    def stop_gateway(self, *, log=None) -> SupervisorSnapshot:
        self._manager.stop_gateway(log=log)
        return self._manager.get_snapshot(log=log)

    def check_installation(self) -> InstallationCheck:
        return self._manager.check_installation()

    def repair_installation(self) -> InstallationActionResult:
        return self._manager.repair_installation()

    def reinstall(self, *, on_progress=None) -> InstallationActionResult:
        return self._manager.reinstall(on_progress=on_progress)

    def detect_ida_executable(self, ida_dir: str) -> str | None:
        return self._manager.installer.detect_ida_executable(ida_dir)

    def detect_ida_python(self, ida_dir: str) -> str | None:
        return self._manager.installer.detect_ida_python(ida_dir)

    def check_diaphora_installation(self) -> DiaphoraInstallationCheck:
        return self._manager.check_diaphora_installation()

    def install_diaphora(self) -> DiaphoraInstallationResult:
        return self._manager.install_diaphora()

    def get_model_providers(self) -> list[ModelProviderDTO]:
        return [p.to_dto() for p in self._manager.get_model_providers()]

    def add_model_provider(self, name="", base_url="", api_key="",
                           api_mode="openai_compatible", model_name="",
                           max_context_tokens=0, top_p=1.0, temperature=0.7,
                           *, enabled=True) -> int:
        return self._manager.add_model_provider(
            name=name, base_url=base_url, api_key=api_key, api_mode=api_mode,
            model_name=model_name, max_context_tokens=max_context_tokens,
            top_p=top_p, temperature=temperature, enabled=enabled,
        )

    def update_model_provider(self, provider_id: int, **updates: object) -> bool:
        return self._manager.update_model_provider(provider_id, **updates)

    def remove_model_provider(self, provider_id: int) -> bool:
        return self._manager.remove_model_provider(provider_id)

    def get_mcp_servers(self) -> list[McpServerDTO]:
        return [s.to_dto() for s in self._manager.get_mcp_servers()]

    def add_mcp_server(self, name="", transport="stdio", *, enabled=True,
                       command="", args="", env="", cwd="", encoding="utf-8",
                       url="", headers="", timeout=30.0, sse_read_timeout=300.0) -> int:
        return self._manager.add_mcp_server(
            name=name, transport=transport, enabled=enabled, command=command,
            args=args, env=env, cwd=cwd, encoding=encoding, url=url,
            headers=headers, timeout=timeout, sse_read_timeout=sse_read_timeout,
        )

    def update_mcp_server(self, server_id: int, **updates: object) -> bool:
        return self._manager.update_mcp_server(server_id, **updates)

    def remove_mcp_server(self, server_id: int) -> bool:
        return self._manager.remove_mcp_server(server_id)

    def get_skills(self) -> list[SkillDTO]:
        return [s.to_dto() for s in self._manager.get_skills()]

    def add_skill(self, name, description="", *, enabled=True, version="",
                  file_path="", install_dir="", installed_at="") -> int:
        return self._manager.add_skill(
            name, description, enabled=enabled, version=version,
            file_path=file_path, install_dir=install_dir, installed_at=installed_at,
        )

    def update_skill(self, skill_id: int, **updates: object) -> bool:
        return self._manager.update_skill(skill_id, **updates)

    def remove_skill(self, skill_id: int) -> bool:
        return self._manager.remove_skill(skill_id)

    def get_skills_dir(self) -> Path:
        return self._manager.get_skills_dir()


def create_api() -> ISupervisorAPI:
    return SupervisorAPIImpl()


# Backward-compatible alias
def create_manager():
    return create_api()
