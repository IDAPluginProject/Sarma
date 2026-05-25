"""Unified supervisor manager for config, gateway and health."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from shared.ida_mcp_config import IdaMcpConfigStore
from shared.models import IdaMcpConfig

from .config_store import IdeConfigStore
from .gateway_controller import GatewayController
from .health import build_health_report
from .installer import EnvironmentInstaller, SoffInstaller
from .models import (
    EnvironmentProbe,
    GatewayStatus,
    HealthReport,
    InstallationActionResult,
    InstallationCheck,
    IdeConfig,
    McpServerEntry,
    ModelProvider,
    SkillEntry,
    SoffInstallationCheck,
    SoffInstallationResult,
    SupervisorSnapshot,
    derive_plugin_dir,
)


class SupervisorManager:
    def __init__(
        self,
        config_store: IdeConfigStore | None = None,
        ida_mcp_config_store: IdaMcpConfigStore | None = None,
        installer: EnvironmentInstaller | None = None,
        gateway_controller: GatewayController | None = None,
    ) -> None:
        self.config_store = config_store or IdeConfigStore()
        self._shared_db = self.config_store.database
        self.ida_mcp_config_store = ida_mcp_config_store
        self.installer = installer or EnvironmentInstaller()
        self.soff_installer = SoffInstaller()
        self.gateway_controller = gateway_controller or GatewayController(
            self.config_store
        )

    def _get_ida_mcp_config_store(self) -> IdaMcpConfigStore:
        if self.ida_mcp_config_store is not None:
            return self.ida_mcp_config_store
        config = self.config_store.load()
        return IdaMcpConfigStore(plugin_dir=config.plugin_dir, db=self._shared_db)

    def get_ide_config(self) -> IdeConfig:
        return self.config_store.load()

    def get_config(self) -> IdeConfig:
        return self.get_ide_config()

    def get_ida_mcp_config(self) -> IdaMcpConfig:
        return self._get_ida_mcp_config_store().load()

    def _effective_python_path(self) -> str | None:
        return self.get_ida_mcp_config().ida_python

    def get_ide_config_store_info(self):
        return self.config_store.info()

    def get_ida_mcp_config_store_info(self):
        return self._get_ida_mcp_config_store().info()

    def update_ide_config(self, **updates: object) -> IdeConfig:
        return self.config_store.update(**updates)

    def update_config(self, **updates: object) -> IdeConfig:
        return self.update_ide_config(**updates)

    def update_ida_mcp_config(self, **updates: object) -> IdaMcpConfig:
        return self._get_ida_mcp_config_store().update(**updates)

    def _resolve_plugin_dir(self, config: IdeConfig) -> str:
        """Return the effective plugin directory, deriving from ida_dir if set."""
        if config.ida_dir:
            return derive_plugin_dir(config.ida_dir)
        return config.plugin_dir

    def probe_environment(self) -> EnvironmentProbe:
        config = self.get_ide_config()
        return self.installer.probe(plugin_dir=self._resolve_plugin_dir(config))

    def check_installation(self) -> InstallationCheck:
        config = self.get_ide_config()
        return self.installer.check_installation(
            plugin_dir=self._resolve_plugin_dir(config),
            python_executable=self._effective_python_path(),
            config_path=None,
        )

    def repair_installation(self) -> InstallationActionResult:
        config = self.get_ide_config()
        return self.installer.repair_config(
            plugin_dir=self._resolve_plugin_dir(config),
            python_executable=self._effective_python_path(),
            config_path=None,
        )

    def reinstall(
        self, *, on_progress: Callable[[str], None] | None = None
    ) -> InstallationActionResult:
        from .install_runner import run_install

        config = self.get_ide_config()
        plugin_dir = self._resolve_plugin_dir(config)
        ida_mcp_config = self.get_ida_mcp_config()
        python_path = self._effective_python_path()
        if not python_path:
            return InstallationActionResult(
                action="install",
                ok=False,
                summary="no Python executable configured",
                check=self.installer.check_installation(
                    plugin_dir=plugin_dir,
                    python_executable=None,
                    config_path=None,
                ),
                warnings=["python_path not configured"],
            )

        config_dict = ida_mcp_config.to_dict()
        ida_mcp_result = run_install(
            python_executable=python_path,
            ida_path=ida_mcp_config.ida_path,
            plugin_dir=plugin_dir,
            ida_mcp_config_dict=config_dict,
            on_progress=on_progress,
        )
        if on_progress:
            on_progress("[Soff] Installing Soff plugin...")
        soff_result = self.soff_installer.install(plugin_dir=plugin_dir)
        if on_progress:
            on_progress(f"[Soff] {soff_result.summary}")

        warnings = list(ida_mcp_result.warnings)
        warnings.extend(
            f"soff: {warning}" for warning in soff_result.warnings
        )
        if not soff_result.ok:
            warnings.append(f"soff: {soff_result.summary}")

        ok = ida_mcp_result.ok and soff_result.ok
        if ida_mcp_result.ok and soff_result.ok:
            summary = "Installation completed successfully"
        elif ida_mcp_result.ok:
            summary = f"ida_mcp installed; {soff_result.summary}"
        elif soff_result.ok:
            summary = f"{ida_mcp_result.summary}; soff installed successfully"
        else:
            summary = f"{ida_mcp_result.summary}; {soff_result.summary}"

        return InstallationActionResult(
            action=ida_mcp_result.action,
            ok=ok,
            summary=summary,
            check=ida_mcp_result.check,
            config_path=ida_mcp_result.config_path,
            created=ida_mcp_result.created,
            already_exists=ida_mcp_result.already_exists,
            warnings=warnings,
        )

    def install_requirements(self) -> InstallationActionResult:
        python_path = self._effective_python_path()
        return self.installer.install_requirements(python_executable=python_path)

    # ------------------------------------------------------------------
    # Soff installation
    # ------------------------------------------------------------------

    def check_soff_installation(self) -> SoffInstallationCheck:
        config = self.get_ide_config()
        return self.soff_installer.check_installation(
            plugin_dir=self._resolve_plugin_dir(config),
        )

    def install_soff(self) -> SoffInstallationResult:
        config = self.get_ide_config()
        return self.soff_installer.install(
            plugin_dir=self._resolve_plugin_dir(config),
        )

    def _controller_with_log(
        self, log: Callable[[str], None] | None
    ) -> GatewayController:
        """Return a controller, optionally with log routing.

        When *log* is None, returns the injected ``self.gateway_controller``
        so that tests and callers can substitute their own controller.

        When *log* is provided, creates a fresh controller sharing the same
        config_store and python_path so that log callbacks don't cross
        between concurrent calls.
        """
        if log is None:
            return self.gateway_controller
        return GatewayController(
            self.config_store,
            log=log,
            python_path=self._effective_python_path(),
        )

    def get_gateway_status(
        self, log: Callable[[str], None] | None = None
    ) -> GatewayStatus:
        return self._controller_with_log(log).status()

    def start_gateway(self, log: Callable[[str], None] | None = None) -> GatewayStatus:
        return self._controller_with_log(log).start()

    def stop_gateway(self, log: Callable[[str], None] | None = None) -> GatewayStatus:
        return self._controller_with_log(log).stop()

    def get_health_report(
        self, log: Callable[[str], None] | None = None
    ) -> HealthReport:
        config = self.get_config()
        gateway = self.get_gateway_status(log=log)
        environment = self.probe_environment()
        return build_health_report(config, gateway, environment)

    def get_snapshot(
        self, log: Callable[[str], None] | None = None
    ) -> SupervisorSnapshot:
        config = self.get_config()
        gateway = self.get_gateway_status(log=log)
        environment = self.probe_environment()
        health = build_health_report(config, gateway, environment)
        return SupervisorSnapshot(
            config=config,
            config_store=self.config_store.info(),
            gateway=gateway,
            environment=environment,
            health=health,
        )

    # ------------------------------------------------------------------
    # Model providers (SQLite)
    # ------------------------------------------------------------------

    def get_model_providers(self) -> list[ModelProvider]:
        rows = self._shared_db.load_rows("model_providers")
        return [ModelProvider.from_dict(r) for r in rows]

    def add_model_provider(
        self,
        name: str = "",
        base_url: str = "",
        api_key: str = "",
        api_mode: str = "openai_compatible",
        model_name: str = "",
        max_context_tokens: int = 0,
        top_p: float = 1.0,
        temperature: float = 0.7,
        *,
        enabled: bool = True,
    ) -> int:
        return self._shared_db.insert_row(
            "model_providers",
            name=name,
            base_url=base_url,
            api_key=api_key,
            api_mode=api_mode,
            model_name=model_name,
            max_context_tokens=max_context_tokens,
            top_p=top_p,
            temperature=temperature,
            enabled=enabled,
        )

    def update_model_provider(self, provider_id: int, **updates: object) -> bool:
        return self._shared_db.update_row("model_providers", provider_id, **updates)

    def remove_model_provider(self, provider_id: int) -> bool:
        return self._shared_db.delete_row("model_providers", provider_id)

    # ------------------------------------------------------------------
    # MCP servers (SQLite)
    # ------------------------------------------------------------------

    def get_mcp_servers(self) -> list[McpServerEntry]:
        rows = self._shared_db.load_rows("mcp_servers")
        return [McpServerEntry.from_dict(r) for r in rows]

    def add_mcp_server(
        self,
        name: str = "",
        transport: str = "stdio",
        *,
        enabled: bool = True,
        command: str = "",
        args: str = "",
        env: str = "",
        cwd: str = "",
        encoding: str = "utf-8",
        url: str = "",
        headers: str = "",
        timeout: float = 30.0,
        sse_read_timeout: float = 300.0,
    ) -> int:
        return self._shared_db.insert_row(
            "mcp_servers",
            name=name,
            transport=transport,
            enabled=enabled,
            command=command,
            args=args,
            env=env,
            cwd=cwd,
            encoding=encoding,
            url=url,
            headers=headers,
            timeout=timeout,
            sse_read_timeout=sse_read_timeout,
        )

    def update_mcp_server(self, server_id: int, **updates: object) -> bool:
        return self._shared_db.update_row("mcp_servers", server_id, **updates)

    def remove_mcp_server(self, server_id: int) -> bool:
        return self._shared_db.delete_row("mcp_servers", server_id)

    # ------------------------------------------------------------------
    # Skills (SQLite)
    # ------------------------------------------------------------------

    def get_skills(self) -> list[SkillEntry]:
        rows = self._shared_db.load_rows("skills")
        return [SkillEntry.from_dict(r) for r in rows]

    def add_skill(
        self,
        name: str,
        description: str = "",
        *,
        enabled: bool = True,
        version: str = "",
        file_path: str = "",
        install_dir: str = "",
        installed_at: str = "",
    ) -> int:
        return self._shared_db.insert_row(
            "skills",
            name=name,
            description=description,
            enabled=enabled,
            version=version,
            file_path=file_path,
            install_dir=install_dir,
            installed_at=installed_at,
        )

    def update_skill(self, skill_id: int, **updates: object) -> bool:
        return self._shared_db.update_row("skills", skill_id, **updates)

    def remove_skill(self, skill_id: int) -> bool:
        return self._shared_db.delete_row("skills", skill_id)

    def get_skills_dir(self) -> Path:
        """Return the skills installation directory under the IDE user data root.

        Skills are stored in ``{exe_dir}/data/skills/`` so they survive
        on other platforms) so they survive plugin reinstalls and updates.
        """
        from shared.paths import get_skills_dir

        return get_skills_dir()

    # --- Agent model assignments ---

    def get_agent_model_assignments(self) -> list[dict]:
        rows = self._shared_db.load_rows("audit_agent_models")
        providers = {p["id"]: p["name"] for p in self._shared_db.load_rows("model_providers")}
        for row in rows:
            pid = row.get("provider_id")
            row["provider_name"] = providers.get(pid, "") if pid else ""
        return rows

    def update_agent_model_assignment(
        self, agent_name: str, provider_id: int | None
    ) -> bool:
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).isoformat()
        with self._shared_db._connect() as conn:
            cursor = conn.execute(
                "SELECT id FROM audit_agent_models WHERE agent_name = ?",
                (agent_name,),
            )
            existing = cursor.fetchone()
            if existing:
                conn.execute(
                    "UPDATE audit_agent_models SET provider_id = ?, updated_at = ? WHERE agent_name = ?",
                    (provider_id, now, agent_name),
                )
            else:
                conn.execute(
                    "INSERT INTO audit_agent_models (agent_name, provider_id, created_at, updated_at) VALUES (?, ?, ?, ?)",
                    (agent_name, provider_id, now, now),
                )
            conn.commit()
        return True
