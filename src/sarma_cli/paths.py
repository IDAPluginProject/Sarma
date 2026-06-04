"""Cross-platform path resolution for Sarma.

Two scopes:
- **global**  ``~/.sarma/``         — base config + skills, shared across projects.
                                        Override this directory with ``SARMA_HOME``
                                        (which then *is* the sarma dir, JAVA_HOME-style).
- **local**   ``./.sarma/``         — per-workspace overrides + session database.

``Path.home()`` resolves to ``C:\\Users\\<user>`` on Windows and ``/home/<user>``
(or ``/Users/<user>``) on Unix, so the same ``~/.sarma`` layout works everywhere.
"""

from __future__ import annotations

import os
from pathlib import Path

_DIR_NAME = ".sarma"
MODELS_NAME = "models.toml"
AGENTS_NAME = "agents.toml"
MCP_NAME = "mcp.toml"
INPUT_HISTORY_NAME = ".history"


def global_dir() -> Path:
    """Global config directory: ``$SARMA_HOME`` or ``~/.sarma``."""
    override = os.environ.get("SARMA_HOME")
    if override:
        return Path(override).expanduser()
    return Path.home() / _DIR_NAME


def local_dir() -> Path:
    """Per-workspace directory: ``./.sarma`` in the current working directory."""
    return Path.cwd() / _DIR_NAME


def global_config_file() -> Path:
    return global_models_file()


def local_config_file() -> Path:
    return local_models_file()


def global_models_file() -> Path:
    return global_dir() / MODELS_NAME


def local_models_file() -> Path:
    return local_dir() / MODELS_NAME


def global_agents_file() -> Path:
    return global_dir() / AGENTS_NAME


def local_agents_file() -> Path:
    return local_dir() / AGENTS_NAME


def global_mcp_file() -> Path:
    return global_dir() / MCP_NAME


def local_mcp_file() -> Path:
    return local_dir() / MCP_NAME


def db_path() -> Path:
    """Session database lives per-workspace."""
    return local_dir() / "db.sqlite"


def input_history_file() -> Path:
    """Line-based user input history for the full-screen TUI."""
    return local_dir() / INPUT_HISTORY_NAME


def global_skills_dir() -> Path:
    return global_dir() / "skills"


def local_skills_dir() -> Path:
    return local_dir() / "skills"
