"""LLM-backed planner.

Turns a natural-language request into a structured plan before any tool runs.
The plan is a declaration of intent, not an execution script: the executor loop
still lets the model choose tools turn by turn, because tool results routinely
change what the next step should be. The plan's value is that it is inspectable
and auditable up front.
"""

import json

from app.llm.base import LLMProvider, LLMUnavailable

PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "understanding": {
            "type": "string",
            "description": "One sentence restating what the user is asking for.",
        },
        "steps": {
            "type": "array",
            "description": "Ordered steps needed to satisfy the request.",
            "items": {
                "type": "object",
                "properties": {
                    "description": {"type": "string", "description": "What this step accomplishes."},
                    "tool": {
                        "type": ["string", "null"],
                        "description": "Tool expected for this step, or null for a reasoning/answering step.",
                    },
                    "requires_approval": {
                        "type": "boolean",
                        "description": "True if this step is likely to need human approval to run.",
                    },
                },
                "required": ["description", "tool", "requires_approval"],
                "additionalProperties": False,
            },
        },
        "clarification_needed": {
            "type": ["string", "null"],
            "description": "A question to ask the user if the request is too ambiguous to plan, else null.",
        },
    },
    "required": ["understanding", "steps", "clarification_needed"],
    "additionalProperties": False,
}

PLANNER_SYSTEM = """You are the planning stage of a permission-controlled AI agent.

Produce a short, concrete plan for the user's request using only the tools listed
below. Prefer the fewest steps that genuinely satisfy the request.

{tool_summary}

Rules:
- Use a tool name only if it appears in the list above; otherwise use null.
- Set requires_approval to true for any step that runs a command, writes a file,
  or deletes a file. These are gated and a human must approve them.
- If the request is too vague to act on, put a single question in
  clarification_needed and leave steps empty.
- Do not invent capabilities the tools do not have."""


class Planner:
    def __init__(self, provider: LLMProvider = None):
        self.provider = provider

    async def create_plan(self, message: str, tools: list[dict] = None) -> list[dict]:
        """Backwards-compatible entry point: returns just the step list."""
        plan = await self.create_structured_plan(message, tools)
        return plan.get("steps", [])

    async def create_structured_plan(self, message: str, tools: list[dict] = None) -> dict:
        if self.provider is None or not self.provider.configured:
            return {
                "understanding": message,
                "steps": [],
                "clarification_needed": None,
                "status": "planner_not_configured",
            }

        tool_summary = _summarise_tools(tools or [])
        try:
            response = await self.provider.complete(
                system=PLANNER_SYSTEM.format(tool_summary=tool_summary),
                messages=[{"role": "user", "content": message}],
                output_schema=PLAN_SCHEMA,
            )
        except LLMUnavailable as exc:
            return {
                "understanding": message,
                "steps": [],
                "clarification_needed": None,
                "status": "planner_unavailable",
                "detail": str(exc),
            }

        if response.stop_reason == "refusal":
            return {
                "understanding": message,
                "steps": [],
                "clarification_needed": None,
                "status": "refused",
                "detail": response.refusal,
            }

        try:
            plan = json.loads(response.text)
        except (ValueError, TypeError):
            # The schema makes this unlikely, but a plan is not worth a 500.
            return {
                "understanding": message,
                "steps": [],
                "clarification_needed": None,
                "status": "unparsable_plan",
                "raw": response.text[:500],
            }

        plan["status"] = "ok"
        return plan


def _summarise_tools(tools: list[dict]) -> str:
    if not tools:
        return "No tools are available."
    lines = ["Available tools:"]
    for tool in tools:
        lines.append(f"- {tool['name']}: {tool.get('description', '').strip()}")
    return "\n".join(lines)
