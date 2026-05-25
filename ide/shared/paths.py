"""Shared path helpers for development and packaged IDE runtimes."""

from __future__ import annotations

from pathlib import Path

from shared.runtime import get_packaging_root as get_runtime_packaging_root
from shared.runtime import get_runtime_root


def get_project_root() -> Path:
    """Return the IDE project root for both dev and packaged modes."""
    return get_runtime_root()


def get_resources_root() -> Path:
    """Return the bundled resources directory (contains ida_mcp source, etc.)."""
    return get_project_root() / "resources"


def get_ida_mcp_resources_dir() -> Path:
    """Return the ida_mcp bundled resource directory."""
    return get_resources_root() / "ida_mcp"


def get_soff_resources_dir() -> Path:
    """Return the soff bundled resource directory."""
    return get_resources_root() / "soff"


def get_logs_root() -> Path:
    """Return the logs directory for the current runtime mode."""
    return get_project_root() / "logs"


def get_workspaces_root() -> Path:
    """Return the workspaces directory for the current runtime mode."""
    return get_project_root() / "workspaces"


def get_build_root() -> Path:
    """Return the local build root used by developer tooling."""
    return get_project_root() / "build"


def get_nuitka_output_root() -> Path:
    """Return the base output root used by Nuitka builds."""
    return get_build_root() / "nuitka"


def get_packaging_root() -> Path:
    """Return the packaging helpers root for the current runtime mode."""
    return get_runtime_packaging_root()


def get_data_root() -> Path:
    """Return the portable user data directory inside the IDE installation.

    In packaged mode this is ``{exe_dir}/data/``.
    In development mode this is ``{ide}/data/``.

    All persistent user state (database, skills, etc.) lives here so the
    entire installation is self-contained and portable.  This directory
    must **never** be deleted during updates or reinstalls.
    """
    return get_project_root() / "data"


def get_ide_user_config_root() -> Path:
    """Return the IDE user data root.

    Historically this pointed to ``%APPDATA%/ida-mcp/ide/``.  It now
    returns ``{exe_dir}/data/`` so all user data stays inside the
    installation directory for full portability.
    """
    return ensure_directory(get_data_root())


def get_skills_dir() -> Path:
    """Return the skills installation directory under the IDE data root.

    Skills are stored in ``{exe_dir}/data/skills/`` so they survive
    plugin reinstalls and updates.
    """
    return ensure_directory(get_data_root() / "skills")


def ensure_directory(path: Path) -> Path:
    """Create a directory if needed and return it."""
    path.mkdir(parents=True, exist_ok=True)
    return path
