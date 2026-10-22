import json

import pytest

from app.core.planner import PLAN_SCHEMA, Planner
from app.llm.base import LLMResponse, LLMUnavailable
from app.llm.scripted import ScriptedProvider, UnconfiguredProvider

TOOLS = [
    {"name": "filesystem", "description": "Read and write workspace files.", "input_schema": {}},
    {"name": "terminal", "description": "Run allowlisted commands.", "input_schema": {}},
]

GOOD_PLAN = {
    "understanding": "The user wants the Python version.",
    "steps": [
        {"description": "Run python --version", "tool": "terminal", "requires_approval": True},
        {"description": "Report the version", "tool": None, "requires_approval": False},
    ],
    "clarification_needed": None,
}


@pytest.mark.asyncio
async def test_structured_plan_is_parsed():
    provider = ScriptedProvider([ScriptedProvider.text(json.dumps(GOOD_PLAN))])
    plan = await Planner(provider).create_structured_plan("what python version is installed?", TOOLS)

    assert plan["status"] == "ok"
    assert plan["understanding"] == "The user wants the Python version."
    assert plan["steps"][0]["tool"] == "terminal"
    assert plan["steps"][0]["requires_approval"] is True


@pytest.mark.asyncio
async def test_plan_request_sends_schema_and_tool_summary():
    provider = ScriptedProvider([ScriptedProvider.text(json.dumps(GOOD_PLAN))])
    await Planner(provider).create_structured_plan("check python", TOOLS)

    call = provider.calls[0]
    # The plan is schema-constrained, and no tools are offered to the planner -
    # planning must not execute anything.
    assert call["output_schema"] == PLAN_SCHEMA
    assert call["tool_names"] == []
    assert "filesystem: Read and write workspace files." in call["system"]
    assert "terminal: Run allowlisted commands." in call["system"]


@pytest.mark.asyncio
async def test_create_plan_returns_only_steps_for_backwards_compatibility():
    provider = ScriptedProvider([ScriptedProvider.text(json.dumps(GOOD_PLAN))])
    steps = await Planner(provider).create_plan("check python", TOOLS)
    assert isinstance(steps, list)
    assert steps[0]["description"] == "Run python --version"


@pytest.mark.asyncio
async def test_ambiguous_request_asks_for_clarification():
    vague = {"understanding": "Unclear.", "steps": [], "clarification_needed": "Which file do you mean?"}
    provider = ScriptedProvider([ScriptedProvider.text(json.dumps(vague))])
    plan = await Planner(provider).create_structured_plan("fix it", TOOLS)
    assert plan["clarification_needed"] == "Which file do you mean?"
    assert plan["steps"] == []


@pytest.mark.asyncio
async def test_unparsable_plan_degrades_gracefully():
    provider = ScriptedProvider([ScriptedProvider.text("not json at all")])
    plan = await Planner(provider).create_structured_plan("do a thing", TOOLS)
    assert plan["status"] == "unparsable_plan"
    assert plan["steps"] == []


@pytest.mark.asyncio
async def test_provider_outage_degrades_gracefully():
    class Failing(ScriptedProvider):
        async def complete(self, system, messages, tools=None, output_schema=None):
            raise LLMUnavailable("no network")

    plan = await Planner(Failing([])).create_structured_plan("do a thing", TOOLS)
    assert plan["status"] == "planner_unavailable"
    assert "no network" in plan["detail"]


@pytest.mark.asyncio
async def test_refusal_degrades_gracefully():
    refused = LLMResponse(stop_reason="refusal", refusal={"category": "cyber"})
    plan = await Planner(ScriptedProvider([refused])).create_structured_plan("bad thing", TOOLS)
    assert plan["status"] == "refused"


@pytest.mark.asyncio
async def test_unconfigured_provider_skips_planning():
    plan = await Planner(UnconfiguredProvider()).create_structured_plan("anything", TOOLS)
    assert plan["status"] == "planner_not_configured"


@pytest.mark.asyncio
async def test_no_provider_skips_planning():
    plan = await Planner(None).create_structured_plan("anything", TOOLS)
    assert plan["status"] == "planner_not_configured"


def test_plan_schema_is_strict():
    """additionalProperties must be closed so the model cannot invent fields."""
    assert PLAN_SCHEMA["additionalProperties"] is False
    assert PLAN_SCHEMA["items" if "items" in PLAN_SCHEMA else "properties"]
    step_schema = PLAN_SCHEMA["properties"]["steps"]["items"]
    assert step_schema["additionalProperties"] is False
    assert set(step_schema["required"]) == {"description", "tool", "requires_approval"}
