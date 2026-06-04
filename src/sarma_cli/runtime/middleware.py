"""Runtime middleware construction for LangChain agents.

The defaults here must be conservative. Middleware can expose powerful tools
to the model, so Sarma starts with a virtual in-state filesystem and leaves
host filesystem or shell execution for an explicit future sandbox policy.
"""

from __future__ import annotations

from typing import Any


def build_agent_middleware() -> tuple[Any, ...]:
    """Build default LangChain v1 agent middleware.

    DeepAgents' ``StateBackend`` stores files in graph state. This gives agents
    scratch-file semantics without granting direct access to the user's working
    tree.
    """
    from deepagents.backends import StateBackend
    from deepagents.middleware import FilesystemMiddleware

    return (FilesystemMiddleware(backend=StateBackend()),)
