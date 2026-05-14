import sys
from pathlib import Path

import pytest

from shared.ida_mcp_config import IdaMcpConfigStore
from supervisor.config_store import IdeConfigStore
from supervisor.installer import DiaphoraInstaller, EnvironmentInstaller
from supervisor.manager import SupervisorManager
from supervisor.models import (
    DiaphoraInstallationCheck,
    DiaphoraInstallationResult,
    InstallationActionResult,
    InstallationCheck,
)
from supervisor.platform_detector import (
    PlatformDetector,
    _probe_ida_python_via_idapyswitch,
)


@pytest.mark.environment
def test_check_installation_reports_missing_config(tmp_path: Path) -> None:
    plugin_dir = tmp_path / "plugin"
    plugin_dir.mkdir()
    (plugin_dir / "ida_mcp.py").write_text("# plugin\n", encoding="utf-8")
    (plugin_dir / "ida_mcp").mkdir()
    python_path = Path(sys.executable)
    (tmp_path / "requirements.txt").write_text("pytest\n", encoding="utf-8")

    installer = EnvironmentInstaller(repo_root=tmp_path)
    result = installer.check_installation(
        plugin_dir=plugin_dir,
        python_executable=python_path,
    )

    assert result.plugin_dir == str(plugin_dir)
    assert result.config_exists is False
    assert result.ida_mcp_py_exists is True
    assert result.ida_mcp_package_exists is True
    assert result.python_exists is True
    assert result.requirements == ["pytest"]
    assert result.requirements_path == str(tmp_path / "requirements.txt")
    assert "pytest" in result.installed_requirements
    assert result.missing_requirements == []


@pytest.mark.environment
def test_check_installation_reports_missing_requirements(tmp_path: Path) -> None:
    plugin_dir = tmp_path / "plugin"
    plugin_dir.mkdir()
    (plugin_dir / "ida_mcp.py").write_text("# plugin\n", encoding="utf-8")
    (plugin_dir / "ida_mcp").mkdir()
    (tmp_path / "requirements.txt").write_text(
        "definitely-not-installed-package-xyz==1.0\n",
        encoding="utf-8",
    )

    installer = EnvironmentInstaller(repo_root=tmp_path)
    result = installer.check_installation(
        plugin_dir=plugin_dir,
        python_executable=Path(sys.executable),
    )

    assert result.installed_requirements == {}
    assert result.missing_requirements == ["definitely-not-installed-package-xyz==1.0"]


@pytest.mark.environment
def test_check_installation_uses_repo_root_requirements(tmp_path: Path) -> None:
    plugin_dir = tmp_path / "plugin"
    plugin_dir.mkdir()
    (plugin_dir / "ida_mcp.py").write_text("# plugin\n", encoding="utf-8")
    (plugin_dir / "ida_mcp").mkdir()

    repo_requirements = tmp_path / "requirements.txt"
    repo_requirements.write_text("pytest\n", encoding="utf-8")

    installer = EnvironmentInstaller(repo_root=tmp_path)
    result = installer.check_installation(
        plugin_dir=plugin_dir,
        python_executable=Path(sys.executable),
    )

    assert result.requirements == ["pytest"]
    assert result.requirements_path == str(repo_requirements)


def test_repair_config_copies_default_template(tmp_path: Path) -> None:
    plugin_dir = tmp_path / "plugin"
    plugin_dir.mkdir()
    (plugin_dir / "ida_mcp.py").write_text("# plugin\n", encoding="utf-8")
    (plugin_dir / "ida_mcp").mkdir()
    default_config = tmp_path / "ida_mcp" / "config.conf"
    default_config.parent.mkdir()
    default_config.write_text("enable_http = true\n", encoding="utf-8")

    installer = EnvironmentInstaller(repo_root=tmp_path)
    result = installer.repair_config(plugin_dir=plugin_dir)

    assert result.ok is True
    assert result.created is True
    assert (plugin_dir / "ida_mcp" / "config.conf").read_text(
        encoding="utf-8"
    ) == "enable_http = true\n"


def test_reinstall_reports_existing_config(tmp_path: Path) -> None:
    plugin_dir = tmp_path / "plugin"
    plugin_dir.mkdir()
    (plugin_dir / "ida_mcp.py").write_text("# plugin\n", encoding="utf-8")
    (plugin_dir / "ida_mcp").mkdir()
    (plugin_dir / "ida_mcp" / "config.conf").write_text(
        "debug = false\n", encoding="utf-8"
    )
    default_config = tmp_path / "ida_mcp" / "config.conf"
    default_config.parent.mkdir()
    default_config.write_text("enable_http = true\n", encoding="utf-8")

    installer = EnvironmentInstaller(repo_root=tmp_path)
    result = installer.reinstall(plugin_dir=plugin_dir)

    assert result.ok is True
    assert result.already_exists is True
    assert result.created is False


def test_repair_config_uses_explicit_config_path(tmp_path: Path) -> None:
    plugin_dir = tmp_path / "plugin"
    plugin_dir.mkdir()
    (plugin_dir / "ida_mcp.py").write_text("# plugin\n", encoding="utf-8")
    (plugin_dir / "ida_mcp").mkdir()
    default_config = tmp_path / "ida_mcp" / "config.conf"
    default_config.parent.mkdir()
    default_config.write_text("enable_http = true\n", encoding="utf-8")
    explicit_config = tmp_path / "custom" / "config.conf"

    installer = EnvironmentInstaller(repo_root=tmp_path)
    result = installer.repair_config(plugin_dir=plugin_dir, config_path=explicit_config)

    assert result.ok is True
    assert result.created is True
    assert result.config_path == str(explicit_config)
    assert explicit_config.read_text(encoding="utf-8") == "enable_http = true\n"


def _make_diaphora_resources(root: Path, *, complete: bool = True) -> Path:
    resources = root / "diaphora"
    plugin = resources / "plugin"
    plugin.mkdir(parents=True)
    (plugin / "diaphora_plugin.py").write_text("# wrapper\n", encoding="utf-8")
    (plugin / "diaphora_plugin.cfg").write_text(
        "[Diaphora]\npath=/path/to/diaphora/\n",
        encoding="utf-8",
    )
    if complete:
        for name in ("diaphora.py", "diaphora_ida.py", "diaphora_config.py"):
            (resources / name).write_text("# core\n", encoding="utf-8")
    return resources


def test_diaphora_install_writes_cfg_and_reports_success(tmp_path: Path) -> None:
    resources = _make_diaphora_resources(tmp_path)
    plugin_dir = tmp_path / "ida" / "plugins"

    result = DiaphoraInstaller(resources).install(plugin_dir)

    assert result.ok is True
    assert result.installed is True
    assert result.check.cfg_path_correct is True
    assert result.check.bundle_files_exist is True
    cfg = (plugin_dir / "diaphora_plugin.cfg").read_text(encoding="utf-8")
    assert str(resources).replace("\\", "/") in cfg


def test_diaphora_install_fails_when_bundle_core_files_missing(tmp_path: Path) -> None:
    resources = _make_diaphora_resources(tmp_path, complete=False)
    plugin_dir = tmp_path / "ida" / "plugins"

    result = DiaphoraInstaller(resources).install(plugin_dir)

    assert result.ok is False
    assert result.installed is False
    assert result.check.bundle_files_exist is False
    assert "bundled diaphora files are missing" in result.warnings


def test_diaphora_check_rejects_cfg_pointing_elsewhere(tmp_path: Path) -> None:
    resources = _make_diaphora_resources(tmp_path)
    plugin_dir = tmp_path / "ida" / "plugins"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "diaphora_plugin.py").write_text("# wrapper\n", encoding="utf-8")
    (plugin_dir / "diaphora_plugin.cfg").write_text(
        "[Diaphora]\npath=C:/other/diaphora/\n",
        encoding="utf-8",
    )

    check = DiaphoraInstaller(resources).check_installation(plugin_dir)

    assert check.plugin_py_exists is True
    assert check.plugin_cfg_exists is True
    assert check.cfg_path_correct is False
    assert check.bundle_files_exist is True
    assert check.summary == "diaphora installation is incomplete"


def test_manager_reinstall_installs_ida_mcp_and_diaphora(
    monkeypatch,
    tmp_path: Path,
) -> None:
    plugin_dir = tmp_path / "plugins"
    config_store = IdeConfigStore(config_path=tmp_path / "ide.db")
    config_store.update(plugin_dir=str(plugin_dir))
    ida_mcp_config_store = IdaMcpConfigStore(
        config_path=tmp_path / "config.conf",
        db=config_store.database,
    )
    manager = SupervisorManager(
        config_store=config_store,
        ida_mcp_config_store=ida_mcp_config_store,
    )
    manager.update_ida_mcp_config(ida_python=sys.executable)

    run_install_calls: list[dict[str, object]] = []

    def _fake_run_install(**kwargs):
        run_install_calls.append(kwargs)
        return InstallationActionResult(
            action="install",
            ok=True,
            summary="Installation completed successfully",
            check=InstallationCheck(
                plugin_dir=str(plugin_dir),
                plugin_dir_exists=True,
                config_path=str(plugin_dir / "ida_mcp" / "config.conf"),
                config_exists=True,
                python_executable=sys.executable,
                python_exists=True,
                ida_mcp_py_exists=True,
                ida_mcp_package_exists=True,
                summary="Installation completed successfully",
            ),
            config_path=str(plugin_dir / "ida_mcp" / "config.conf"),
            created=True,
        )

    class _FakeDiaphoraInstaller:
        plugin_dir: str | Path | None = None

        def install(self, plugin_dir=None):
            self.plugin_dir = plugin_dir
            return DiaphoraInstallationResult(
                action="install",
                ok=True,
                summary="diaphora installed successfully",
                check=DiaphoraInstallationCheck(
                    plugin_dir=str(plugin_dir),
                    plugin_py_exists=True,
                    plugin_cfg_exists=True,
                    cfg_path_correct=True,
                    bundle_files_exist=True,
                    summary="diaphora is installed and configured",
                ),
                installed=True,
            )

    diaphora_installer = _FakeDiaphoraInstaller()
    manager.diaphora_installer = diaphora_installer
    monkeypatch.setattr("supervisor.install_runner.run_install", _fake_run_install)

    progress: list[str] = []
    result = manager.reinstall(on_progress=progress.append)

    assert result.ok is True
    assert result.summary == "Installation completed successfully"
    assert run_install_calls
    assert run_install_calls[0]["plugin_dir"] == str(plugin_dir)
    assert diaphora_installer.plugin_dir == str(plugin_dir)
    assert "[Diaphora] Installing Diaphora plugin..." in progress
    assert "[Diaphora] diaphora installed successfully" in progress


# ------------------------------------------------------------------
# probe / find_* / idapyswitch parsing tests
# ------------------------------------------------------------------


def test_probe_with_explicit_plugin_dir(tmp_path: Path) -> None:
    """probe(plugin_dir=...) should mark ida_mcp_importable when files exist."""
    plugin_dir = tmp_path / "plugins"
    plugin_dir.mkdir()
    (plugin_dir / "ida_mcp.py").write_text("# plugin\n", encoding="utf-8")
    (plugin_dir / "ida_mcp").mkdir()

    installer = EnvironmentInstaller(repo_root=tmp_path)
    probe = installer.probe(plugin_dir=str(plugin_dir))

    assert probe.ida_mcp_importable is True
    assert probe.ida_mcp_location == str(plugin_dir)


def test_probe_without_plugin_dir_reports_not_importable(tmp_path: Path) -> None:
    """probe() without explicit plugin_dir should not find resources dir."""
    installer = EnvironmentInstaller(repo_root=tmp_path)
    probe = installer.probe()

    # repo_root (tmp_path) is not a valid IDA plugins directory
    assert probe.ida_mcp_importable is False
    assert "ida_mcp plugin directory not detected" in probe.warnings


def test_find_plugin_dirs_does_not_scan_resources(tmp_path: Path) -> None:
    """find_plugin_dirs must never return the bundled resources directory."""
    resources = tmp_path / "resources" / "ida_mcp"
    resources.mkdir(parents=True)
    (resources / "ida_mcp.py").write_text("# bundled\n", encoding="utf-8")
    (resources / "ida_mcp").mkdir()

    installer = EnvironmentInstaller(repo_root=tmp_path)
    dirs = installer.find_plugin_dirs()

    assert str(resources) not in dirs


def test_idapyswitch_parses_previously_used(monkeypatch, tmp_path: Path) -> None:
    """_probe_ida_python_via_idapyswitch should parse 'IDA previously used:' line."""
    ida_dir = tmp_path / "ida"
    ida_dir.mkdir()
    python_dir = ida_dir / "ida-python"
    python_dir.mkdir()
    (python_dir / "python.exe").write_text("", encoding="utf-8")

    # Create a fake idapyswitch that outputs the expected format
    fake_switch = ida_dir / "idapyswitch.exe"
    fake_switch.write_text("fake", encoding="utf-8")

    mock_output = (
        'IDA previously used: "' + str(python_dir / "python3.dll") + '" '
        "(guessed version: 3.12.10)\n"
        "Applying version 3.12.10\n"
    )

    import subprocess

    class _FakeCompleted:
        stdout = mock_output
        stderr = ""
        returncode = 0

    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: _FakeCompleted())

    result = _probe_ida_python_via_idapyswitch(ida_dir)
    assert len(result) == 1
    assert "python.exe" in result[0]


def test_idapyswitch_not_found_returns_empty(tmp_path: Path) -> None:
    """If idapyswitch doesn't exist, should return empty list."""
    ida_dir = tmp_path / "ida"
    ida_dir.mkdir()

    result = _probe_ida_python_via_idapyswitch(ida_dir)
    assert result == []


def test_find_ida_paths_macos_discovers_bundles(monkeypatch) -> None:
    """On macOS-like platforms, app bundles contribute ida64 candidates."""
    import platform

    if platform.system() == "Windows":
        pytest.skip("macOS app bundle path resolution not testable on Windows")

    installer = EnvironmentInstaller()

    bundle = Path("/Applications/IDA Professional 9.0.app")
    expected = str(bundle / "Contents" / "MacOS" / "ida64")
    _orig_is_dir = Path.is_dir
    _orig_exists = Path.exists
    _orig_glob = Path.glob

    def _mock_is_dir(self):
        if self == Path("/Applications"):
            return True
        if self == bundle / "Contents" / "MacOS":
            return True
        return _orig_is_dir(self)

    def _mock_exists(self):
        if self == bundle / "Contents" / "MacOS" / "ida64":
            return True
        return _orig_exists(self)

    def _mock_glob(self, pattern):
        if self == Path("/Applications") and pattern == "IDA*.app":
            return [bundle]
        return list(_orig_glob(self, pattern))

    monkeypatch.setattr(Path, "is_dir", _mock_is_dir)
    monkeypatch.setattr(Path, "exists", _mock_exists)
    monkeypatch.setattr(Path, "glob", _mock_glob)

    paths = installer.find_ida_paths()
    assert expected in paths
