"""Chat presenter — view models and data transformation for ChatPage.

Separates business logic (config resolution, message parsing, stream routing)
from the UI widget. ChatPage delegates all data decisions here.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from app.chat.models import ResolvedSkill
from app.services.supervisor_client import SupervisorClient
from app.services.skill_service import SkillService

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# View models
# ---------------------------------------------------------------------------


@dataclass
class ProviderViewModel:
    id: int
    display_name: str
    api_mode: str


@dataclass
class MessageViewModel:
    role: str              # "user" | "assistant" | "tool"
    content: str
    show_role: bool         # show the role label?
    tool_name: str | None
    args_text: str
    result_text: str
    summary: str


@dataclass
class ConversationViewModel:
    conversation_id: str
    messages: list[MessageViewModel]
    provider_id: int | None
    is_running: bool


@dataclass
class SubmissionConfig:
    provider_dict: dict[str, Any]
    servers_list: list[dict[str, Any]]
    skill_dict: dict[str, Any] | None
    history_dicts: list[dict[str, Any]]


# ---------------------------------------------------------------------------
# ChatPresenter
# ---------------------------------------------------------------------------


class ChatPresenter:
    """Data-transformation layer between data and ChatPage UI."""

    def __init__(
        self,
        supervisor_client: SupervisorClient | None = None,
        skill_service: SkillService | None = None,
    ) -> None:
        self._supervisor_client: SupervisorClient | None = supervisor_client
        self._skill_service = skill_service or SkillService()

    # --- Provider models ---

    def get_enabled_providers(self) -> list[ProviderViewModel]:
        if self._supervisor_client is None:
            return []
        try:
            providers = self._supervisor_client.get_model_providers()
        except Exception:
            logger.exception("Failed to load model providers")
            return []
        return [
            ProviderViewModel(
                id=p.id or 0,
                display_name=p.name or p.model_name or "",
                api_mode=p.api_mode,
            )
            for p in providers if p.enabled
        ]

    def get_provider_display_name(self, provider_id: int | None) -> str:
        if self._supervisor_client is None or provider_id is None:
            return ""
        try:
            for p in self._supervisor_client.get_model_providers():
                if p.id == provider_id and p.enabled:
                    return p.name or p.model_name or ""
        except Exception:
            pass
        return ""

    # --- Skills ---

    def list_available_skills(self) -> list[dict]:
        return self._skill_service.list_available()

    def resolve_skill(self, skill_id: int | None) -> ResolvedSkill | None:
        if skill_id is None:
            return None
        return self._skill_service.resolve(skill_id)

    # --- Message submission ---

    def prepare_submission_config(
        self,
        conversation_id: str,
        provider_id: int | None,
        skill_id: int | None,
        message_history: list[dict[str, Any]] | None,
    ) -> SubmissionConfig | None:
        if self._supervisor_client is None:
            return None

        try:
            providers = self._supervisor_client.get_model_providers()
            provider_dict: dict[str, Any] = {}
            if provider_id is not None:
                for p in providers:
                    if p.id == provider_id and p.enabled:
                        provider_dict = p.to_dict()
                        break

            servers = self._supervisor_client.get_mcp_servers()
            servers_list = [s.to_dict() for s in servers if s.enabled]

            skill_dict = None
            if skill_id is not None:
                resolved = self._skill_service.resolve(skill_id)
                if resolved:
                    skill_dict = {
                        "id": resolved.id,
                        "name": resolved.name,
                        "system_prompt_template": resolved.system_prompt_suffix,
                        "tool_allowlist_json": (
                            json.dumps(sorted(resolved.tool_allowlist))
                            if resolved.tool_allowlist is not None else None
                        ),
                        "tool_denylist_json": (
                            json.dumps(sorted(resolved.tool_denylist))
                            if resolved.tool_denylist is not None else None
                        ),
                        "model_override": resolved.preferred_model_name or "",
                        "temperature_override": resolved.temperature_override,
                    }

            return SubmissionConfig(
                provider_dict=provider_dict,
                servers_list=servers_list,
                skill_dict=skill_dict,
                history_dicts=message_history or [],
            )
        except Exception:
            logger.exception("Failed to build submission config")
            return None

    # --- Message parsing (for conversation replay) ---

    @staticmethod
    def parse_messages_for_display(
        messages: list[Any],
        unknown_label: str = "unknown",
        done_label: str = "done",
        completed_label: str = "completed",
    ) -> list[MessageViewModel]:
        result: list[MessageViewModel] = []
        first_assistant_in_turn = True
        for msg in messages:
            content = msg.content or ""
            if msg.role == "user":
                result.append(MessageViewModel(
                    role="user", content=content,
                    show_role=True, tool_name=None,
                    args_text="", result_text="", summary="",
                ))
                first_assistant_in_turn = True
            elif msg.role == "assistant":
                result.append(MessageViewModel(
                    role="assistant", content=content,
                    show_role=first_assistant_in_turn,
                    tool_name=None, args_text="", result_text="", summary="",
                ))
                first_assistant_in_turn = False
            elif msg.role == "tool":
                tool_name = msg.tool_name or unknown_label
                args_text = ""
                result_text = ""
                try:
                    data = json.loads(content)
                    if isinstance(data, dict):
                        args_data = data.get("args", {})
                        if args_data:
                            args_text = json.dumps(args_data, ensure_ascii=False)
                        result_text = data.get("result", "") or ""
                    elif isinstance(data, (list, str)):
                        args_text = str(data)
                except (json.JSONDecodeError, TypeError):
                    args_text = content
                summary = result_text[:100] if result_text else done_label
                result.append(MessageViewModel(
                    role="tool", content=content,
                    show_role=False, tool_name=tool_name,
                    args_text=args_text, result_text=result_text, summary=summary,
                ))
                first_assistant_in_turn = False
        return result
