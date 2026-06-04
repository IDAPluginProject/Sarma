"""Ruflo orchestration helpers.

Ruflo is the default conversational workflow. It keeps a primary ReAct agent,
but gives it a controlled delegation tool for spawning focused subagents. Each
subagent returns a compact result template instead of a full reasoning trace.
"""

from __future__ import annotations

from typing import Any

RUFLO_SYSTEM_PROMPT = """\
You are Sarma running in Ruflo mode.

You are the primary agent. You may solve tasks directly or delegate focused
subtasks to subagents with the delegate_task tool. Use delegation when a task
benefits from independent investigation, tool-heavy exploration, or parallel
lines of inquiry. Keep the conversation concise and synthesize compact results
from subagents instead of replaying their full work.

When delegating:
- give the subagent a specific task and expected output
- ask for evidence and useful artifacts, not private reasoning
- combine multiple subagent results into a final user-facing answer

Do not expose hidden chain-of-thought. Provide concise reasoning summaries,
conclusions, evidence, and next actions.
"""

SUBAGENT_RESULT_TEMPLATE = """\
Return only this result template. Do not include hidden chain-of-thought,
private reasoning, or a full transcript.

Result:
- Outcome:
- Key evidence:
- Files / functions / addresses / commands:
- Risks or confidence:
- Recommended next action:
"""


def build_ruflo_prompt(base_prompt: str) -> str:
    """Compose the Ruflo primary-agent prompt."""
    return f"{base_prompt.strip()}\n\n---\n\n{RUFLO_SYSTEM_PROMPT.strip()}"


def build_delegate_tool(model: Any, tools: list[Any]) -> Any:
    """Create the Ruflo delegation tool."""
    from langchain.agents import create_agent
    from langchain_core.messages import HumanMessage
    from langchain_core.tools import tool
    from sarma_cli.runtime.middleware import build_agent_middleware_for_model

    @tool
    async def delegate_task(
        subagent_name: str,
        task: str,
        expected_output: str = "",
    ) -> str:
        """Run a focused subagent and return a compact result.

        Args:
            subagent_name: Short label for the subagent, e.g. recon, verifier,
                code-reviewer, reverse-engineer.
            task: Focused task for the subagent.
            expected_output: Optional output requirements for the result.
        """
        label = (subagent_name or "subagent").strip()
        expected = expected_output.strip() or "Return useful findings for the primary agent."
        prompt = f"""\
You are a focused Ruflo subagent named {label}.

Task:
{task}

Expected output:
{expected}

{SUBAGENT_RESULT_TEMPLATE}
"""
        subagent = create_agent(
            model,
            tools,
            system_prompt=prompt,
            middleware=build_agent_middleware_for_model(model),
        )
        result = await subagent.ainvoke(
            {"messages": [HumanMessage(content=task)]},
            config={"recursion_limit": 100},
        )
        messages = result.get("messages", []) if isinstance(result, dict) else []
        if not messages:
            return "Result:\n- Outcome: No subagent result returned."
        content = getattr(messages[-1], "content", "")
        return _stringify_content(content)

    return delegate_task


def _stringify_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                if item.get("type") == "text":
                    parts.append(str(item.get("text", "")))
                elif "content" in item:
                    parts.append(str(item["content"]))
        return "\n".join(part for part in parts if part).strip()
    return str(content)
