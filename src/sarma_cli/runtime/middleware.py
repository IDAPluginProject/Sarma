"""Runtime middleware construction for LangChain agents.

Middleware can expose powerful tools to the model. Sarma gives agents direct
file and shell access rooted at the current workspace.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any


def build_agent_middleware() -> tuple[Any, ...]:
    return _build_agent_middleware(None)


def build_agent_middleware_for_model(model: Any) -> tuple[Any, ...]:
    """Build LangChain v1 agent middleware that needs a model instance."""
    return _build_agent_middleware(model)


def _build_agent_middleware(model: Any | None) -> tuple[Any, ...]:
    """Build default LangChain v1 agent middleware.

    File tools and shell commands both operate in the real current workspace.
    The filesystem backend uses virtual path mode so relative file operations
    are anchored to ``Path.cwd()`` instead of an in-memory graph state.
    """
    import warnings

    from deepagents.backends import FilesystemBackend
    from deepagents.middleware import (
        FilesystemMiddleware,
        RubricMiddleware,
        SummarizationMiddleware,
        SummarizationToolMiddleware,
    )
    from langchain.agents.middleware import (
        FilesystemFileSearchMiddleware,
        ModelRetryMiddleware,
        TodoListMiddleware,
        ToolRetryMiddleware,
    )
    from langchain.agents.middleware.shell_tool import ShellToolMiddleware

    workspace_root = Path.cwd()
    backend = FilesystemBackend(root_dir=workspace_root, virtual_mode=True)
    middleware: list[Any] = [
        TodoListMiddleware(),
        FilesystemFileSearchMiddleware(
            root_path=str(workspace_root),
            use_ripgrep=shutil.which("rg") is not None,
        ),
        FilesystemMiddleware(backend=backend),
        ShellToolMiddleware(
            workspace_root=workspace_root,
            shell_command=_shell_command(),
            tool_name="shell",
        ),
        ModelRetryMiddleware(max_retries=2),
        ToolRetryMiddleware(max_retries=2),
    ]

    if model is None:
        return tuple(middleware)

    summarization = SummarizationMiddleware(model, backend=backend)
    middleware.extend([
        summarization,
        SummarizationToolMiddleware(summarization=summarization),
    ])

    try:
        from langchain_core._api import LangChainBetaWarning
    except ImportError:  # pragma: no cover - compatibility fallback
        LangChainBetaWarning = Warning
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", LangChainBetaWarning)
        middleware.append(RubricMiddleware(model=model))

    return tuple(middleware)


def _shell_command() -> tuple[str, ...] | None:
    """Return a POSIX-compatible shell command for ShellToolMiddleware."""
    if os.name != "nt":
        return None
    candidates = [
        shutil.which("bash"),
        r"C:\Program Files\Git\bin\bash.exe",
        r"C:\Program Files\Git\usr\bin\bash.exe",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return (candidate,)
    return None
