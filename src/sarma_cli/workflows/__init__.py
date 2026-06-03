"""Workflow registry for Sarma CLI."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from rich.panel import Panel


class Workflow(ABC):
    """Base class for execution modes (ruflo, audit, etc.)."""

    def __init__(self, name: str, description: str, is_default: bool = False) -> None:
        self.name = name
        self.description = description
        self.is_default = is_default

    @abstractmethod
    def render_graph(self, **kwargs: Any) -> Panel:
        """Render the workflow's execution graph."""


class WorkflowRegistry:
    """Registry of available workflows."""

    def __init__(self) -> None:
        self._workflows: dict[str, Workflow] = {}
        self._current: str | None = None

    def register(self, workflow: Workflow) -> None:
        if workflow.name in self._workflows:
            raise ValueError(f"Workflow '{workflow.name}' already registered")
        self._workflows[workflow.name] = workflow
        if workflow.is_default:
            self._current = workflow.name

    def switch(self, name: str) -> bool:
        if name not in self._workflows:
            return False
        self._current = name
        return True

    def current(self) -> Workflow | None:
        return self._workflows.get(self._current) if self._current else None

    def current_name(self) -> str:
        return self._current or "unknown"

    def list_workflows(self) -> list[Workflow]:
        return list(self._workflows.values())

    def count(self) -> int:
        return len(self._workflows)


_registry: WorkflowRegistry | None = None


def get_registry() -> WorkflowRegistry:
    global _registry
    if _registry is None:
        _registry = WorkflowRegistry()
    return _registry


def init_workflows() -> None:
    registry = get_registry()
    if registry.count() > 0:
        return
    from sarma_cli.workflows.ruflo import RufloWorkflow
    from sarma_cli.workflows.audit import AuditWorkflow
    from sarma_cli.workflows.audit_slim import AuditSlimWorkflow
    registry.register(RufloWorkflow())
    registry.register(AuditWorkflow())
    registry.register(AuditSlimWorkflow())
