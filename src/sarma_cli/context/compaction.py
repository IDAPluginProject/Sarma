"""Token-window aware context compaction.

This module owns the policy for deciding when to compact conversation history
and how to split raw tail messages from older messages that should become
structured memory. It deliberately does not depend on Session or Store.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from sarma_cli.engine.models import ConversationMessage

Summarizer = Callable[[list[ConversationMessage]], Awaitable[str]]


@dataclass(frozen=True, slots=True)
class ContextWindowPolicy:
    """Budget knobs for automatic and manual compaction."""

    max_context_tokens: int
    trigger_ratio: float = 0.90
    raw_tail_ratio: float = 0.55
    output_reserve_ratio: float = 0.12
    minimum_output_reserve_tokens: int = 2_048
    static_prompt_tokens: int = 0

    @property
    def budget(self) -> int:
        return max(int(self.max_context_tokens or 1), 1)

    @property
    def trigger_tokens(self) -> int:
        return max(int(self.budget * self.trigger_ratio), 1)

    @property
    def raw_tail_tokens(self) -> int:
        return max(int(self.budget * self.raw_tail_ratio), 1)

    @property
    def output_reserve_tokens(self) -> int:
        ratio_reserve = int(self.budget * self.output_reserve_ratio)
        return max(ratio_reserve, self.minimum_output_reserve_tokens)

    @property
    def fixed_overhead_tokens(self) -> int:
        return max(self.static_prompt_tokens, 0) + self.output_reserve_tokens


@dataclass(frozen=True, slots=True)
class CompactionPlan:
    """A deterministic split of history into structured memory and raw tail."""

    should_compact: bool
    keep_tail: list[ConversationMessage]
    older: list[ConversationMessage]
    estimated_input_tokens: int
    trigger_tokens: int


class ContextCompactor:
    """Apply context-window policy to conversation history."""

    def __init__(self, policy: ContextWindowPolicy) -> None:
        self._policy = policy

    @property
    def policy(self) -> ContextWindowPolicy:
        return self._policy

    def plan(
        self,
        history: list[ConversationMessage],
        *,
        upcoming_text: str = "",
        force: bool = False,
    ) -> CompactionPlan:
        estimated = (
            self.estimate_history_tokens(history)
            + self.estimate_text_tokens(upcoming_text)
            + self._policy.fixed_overhead_tokens
        )
        should_compact = force or estimated >= self._policy.trigger_tokens
        keep_tail: list[ConversationMessage] = []
        older: list[ConversationMessage] = []

        if should_compact:
            keep_tail, older = self.split_raw_tail(history)
            should_compact = bool(older)

        return CompactionPlan(
            should_compact=should_compact,
            keep_tail=keep_tail,
            older=older,
            estimated_input_tokens=estimated,
            trigger_tokens=self._policy.trigger_tokens,
        )

    async def compact(
        self,
        history: list[ConversationMessage],
        summarize: Summarizer,
        *,
        conversation_id: str = "",
        upcoming_text: str = "",
        force: bool = False,
    ) -> tuple[bool, list[ConversationMessage], str]:
        """Return ``(changed, new_history, memory_text)``."""
        plan = self.plan(history, upcoming_text=upcoming_text, force=force)
        if not plan.should_compact:
            return False, history, ""

        memory = (await summarize(plan.older)).strip()
        if not memory:
            return False, history, ""

        memory_message = ConversationMessage(
            conversation_id=conversation_id,
            turn_id="compact",
            role="system",
            content=build_memory_context_message(memory),
        )
        return True, [memory_message, *plan.keep_tail], memory

    def split_raw_tail(
        self,
        history: list[ConversationMessage],
    ) -> tuple[list[ConversationMessage], list[ConversationMessage]]:
        tail: list[ConversationMessage] = []
        total = 0
        target = self._policy.raw_tail_tokens

        for message in reversed(history):
            cost = self.estimate_message_tokens(message)
            if tail and total + cost > target:
                break
            tail.append(message)
            total += cost

        tail.reverse()
        older_count = len(history) - len(tail)
        if older_count == 0 and total > target:
            return [], list(history)
        return tail, history[:older_count]

    def estimate_history_tokens(self, messages: list[ConversationMessage]) -> int:
        return sum(self.estimate_message_tokens(message) for message in messages)

    @classmethod
    def estimate_message_tokens(cls, message: ConversationMessage) -> int:
        framing_tokens = 16
        role_tokens = cls.estimate_text_tokens(message.role)
        content_tokens = cls.estimate_text_tokens(message.content)
        reasoning_tokens = cls.estimate_text_tokens(message.reasoning_content or "")
        return framing_tokens + role_tokens + content_tokens + reasoning_tokens

    @staticmethod
    def estimate_text_tokens(text: str) -> int:
        # Provider-neutral fallback. Exact provider tokenizers can be added
        # behind this interface without changing Session.
        return max(0, len(text or "") // 4)


def estimate_static_prompt_tokens(system_prompt: str, tool_count: int = 0) -> int:
    # Tool schemas are not available here, so reserve a conservative per-tool
    # budget in addition to the actual system prompt text.
    return ContextCompactor.estimate_text_tokens(system_prompt) + max(tool_count, 0) * 128


def build_memory_context_message(memory: str) -> str:
    return (
        "Structured memory compacted from prior conversation. Use it as "
        "durable context; do not treat it as a user request.\n\n"
        f"{memory.strip()}"
    )


STRUCTURED_MEMORY_PROMPT = """\
Compact the prior conversation into structured durable memory.

Return exactly these sections. Preserve all user constraints, decisions,
verified facts, unresolved tasks, and useful artifacts. Prefer precise file
paths, function names, commands, URLs, configuration keys, and test outcomes.
Do not optimize for shortness at the cost of losing facts.

Goals:
- ...

Constraints:
- ...

Decisions:
- ...

Entities:
- Files:
- Functions / symbols:
- Addresses / offsets:
- Commands:
- URLs:
- Other identifiers:

Verified Facts:
- ...

Tool Results:
- ...

Open Tasks:
- ...

Risks / Unknowns:
- ...

Do not include hidden chain-of-thought or verbose transcripts. Return a concise
structured memory artifact.
"""
