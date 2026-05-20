"""Shared enums for the Sarma IDE application."""

from __future__ import annotations

from enum import Enum


class StreamEventType(str, Enum):
    """Type discriminator for StreamEvent instances.

    Inherits from ``str`` so members compare equal to their raw string
    values and serialize transparently via ``dataclasses.asdict()``.
    """

    TOKEN = "token"
    TOOL_START = "tool_start"
    TOOL_RESULT = "tool_result"
    TOOL_ERROR = "tool_error"
    RUN_STARTED = "run_started"
    RUN_COMPLETED = "run_completed"
    RUN_FAILED = "run_failed"
    SKILL_TRIGGERED = "skill_triggered"
    SUBAGENT_START = "subagent_start"
    SUBAGENT_COMPLETE = "subagent_complete"
    SUBAGENT_ERROR = "subagent_error"
    CUSTOM_PROGRESS = "custom_progress"
