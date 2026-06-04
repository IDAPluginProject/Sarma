"""Runtime services passed into LangChain/LangGraph agent builders."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentRuntimeServices:
    """Session-owned LangChain runtime services.

    Sarma's durable conversation history remains in ``sarma_cli.store.Store``.
    These services are scoped to the live runtime and are recreated on runtime
    restart.
    """

    checkpointer: Any
    store: Any
    cache: Any | None = None
    transformers: tuple[Any, ...] = field(default_factory=tuple)

    @classmethod
    def create(cls) -> "AgentRuntimeServices":
        from langgraph.checkpoint.memory import InMemorySaver
        from langgraph.store.memory import InMemoryStore

        return cls(
            checkpointer=InMemorySaver(),
            store=InMemoryStore(),
            # Cache is intentionally disabled until target-binary identity and
            # mutable IDA state are part of cache keys.
            cache=None,
            transformers=(),
        )

    def create_agent_kwargs(self) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "checkpointer": self.checkpointer,
            "store": self.store,
        }
        if self.cache is not None:
            kwargs["cache"] = self.cache
        if self.transformers:
            kwargs["transformers"] = self.transformers
        return kwargs

    def compile_kwargs(self) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "checkpointer": self.checkpointer,
            "store": self.store,
        }
        if self.cache is not None:
            kwargs["cache"] = self.cache
        if self.transformers:
            kwargs["transformers"] = self.transformers
        return kwargs
