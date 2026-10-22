import json

import pytest

from app.core.agent import Agent
from app.core.conversations import ConversationService
from app.llm.base import LLMResponse, LLMUnavailable
from app.llm.scripted import ScriptedProvider, UnconfiguredProvider
from app.security.audit import AuditLog
from app.security.confirmations import ConfirmationStore
from app.security.permissions import PermissionGate
from app.security.workspace import WorkspacePolicy
from app.services.memory import MemoryService


def _ws(tmp_path):
    """The workspace root the agent's filesystem tool resolves against."""
    root = tmp_path / "ws"
    root.mkdir(exist_ok=True)
    return root


def build(tmp_path, responses, granted=(), max_iterations=8):
    """An agent wired to a scripted provider - no network, no API key."""
    gate = PermissionGate()
    for permission in granted:
        gate.grant(permission)
    provider = ScriptedProvider(responses)
    agent = Agent(
        permissions=gate,
        workspace=WorkspacePolicy(str(tmp_path / "ws")),
        confirmations=ConfirmationStore(),
        audit=AuditLog(),
        provider=provider,
        conversations=ConversationService(),
        memory=MemoryService(),
        max_iterations=max_iterations,
        tool_retries=0,
    )
    return agent, provider, gate


# --------------- basic loop ---------------


@pytest.mark.asyncio
async def test_plain_answer_without_tools(db, tmp_path):
    agent, provider, _ = build(tmp_path, [ScriptedProvider.text("Hello, I am ready.")])
    result = await agent.run("hi", plan=False)
    assert result["status"] == "completed"
    assert result["answer"] == "Hello, I am ready."
    assert result["results"] == []


@pytest.mark.asyncio
async def test_tool_call_result_is_fed_back_to_the_model(db, tmp_path):
    (_ws(tmp_path) / "readme.txt").write_text("hello world", encoding="utf-8")
    agent, provider, _ = build(
        tmp_path,
        [
            ScriptedProvider.tool("filesystem", {"operation": "read", "path": "readme.txt"}),
            ScriptedProvider.text("The file says 'hello world'."),
        ],
    )
    result = await agent.run("what is in readme.txt", plan=False)

    assert result["status"] == "completed"
    assert result["answer"] == "The file says 'hello world'."
    assert result["results"][0]["result"]["content"] == "hello world"

    # The second call must carry the tool_result back to the model.
    second_request = provider.calls[1]["messages"]
    tool_results = [
        block
        for message in second_request
        if isinstance(message["content"], list)
        for block in message["content"]
        if isinstance(block, dict) and block.get("type") == "tool_result"
    ]
    assert len(tool_results) == 1
    assert "hello world" in tool_results[0]["content"]
    assert tool_results[0]["is_error"] is False


@pytest.mark.asyncio
async def test_tools_are_offered_to_the_model(db, tmp_path):
    agent, provider, _ = build(tmp_path, [ScriptedProvider.text("ok")])
    await agent.run("hi", plan=False)
    offered = provider.calls[0]["tool_names"]
    assert offered == sorted(offered), "stable order keeps the cached prompt prefix intact"
    assert {"filesystem", "terminal", "web", "http_api", "memory"} <= set(offered)


@pytest.mark.asyncio
async def test_refused_tool_result_is_marked_as_error(db, tmp_path):
    """A permission refusal must not look like success to the model."""
    agent, provider, _ = build(
        tmp_path,
        [
            ScriptedProvider.tool("filesystem", {"operation": "write", "path": "a.txt", "content": "x"}),
            ScriptedProvider.text("I need the filesystem.write permission."),
        ],
    )
    result = await agent.run("write a file", plan=False)

    assert result["results"][0]["result"]["status"] == "permission_required"
    blocks = [
        block
        for message in provider.calls[1]["messages"]
        if isinstance(message["content"], list)
        for block in message["content"]
        if isinstance(block, dict) and block.get("type") == "tool_result"
    ]
    assert blocks[0]["is_error"] is True


@pytest.mark.asyncio
async def test_unknown_tool_is_reported_to_the_model(db, tmp_path):
    agent, provider, _ = build(
        tmp_path,
        [ScriptedProvider.tool("database", {"query": "drop"}), ScriptedProvider.text("No such tool.")],
    )
    result = await agent.run("use the database", plan=False)
    assert result["results"][0]["result"]["status"] == "tool_not_found"
    assert result["status"] == "completed"


@pytest.mark.asyncio
async def test_parallel_tool_calls_return_in_one_user_message(db, tmp_path):
    """The API requires every tool_result for a turn in a single message."""
    (_ws(tmp_path) / "a.txt").write_text("A", encoding="utf-8")
    (_ws(tmp_path) / "b.txt").write_text("B", encoding="utf-8")
    agent, provider, _ = build(
        tmp_path,
        [
            ScriptedProvider.tools(
                [
                    ("filesystem", {"operation": "read", "path": "a.txt"}),
                    ("filesystem", {"operation": "read", "path": "b.txt"}),
                ]
            ),
            ScriptedProvider.text("Both read."),
        ],
    )
    await agent.run("read both", plan=False)

    result_messages = [
        m
        for m in provider.calls[1]["messages"]
        if isinstance(m["content"], list)
        and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in m["content"])
    ]
    assert len(result_messages) == 1
    assert len(result_messages[0]["content"]) == 2


# --------------- confirmation suspend / resume ---------------


@pytest.mark.asyncio
async def test_turn_suspends_when_a_tool_needs_approval(db, tmp_path):
    agent, _, _ = build(
        tmp_path,
        [ScriptedProvider.tool("terminal", {"operation": "execute", "command": "python --version"})],
        granted=["terminal.execute"],
    )
    result = await agent.run("check the python version", plan=False)

    assert result["status"] == "awaiting_confirmation"
    assert result["confirmation_token"]
    assert result["pending_call"]["tool"] == "terminal"
    assert (await agent.pending())["status"] == "awaiting_confirmation"


@pytest.mark.asyncio
async def test_resume_after_approval_runs_and_completes(db, tmp_path):
    agent, _, _ = build(
        tmp_path,
        [
            ScriptedProvider.tool("terminal", {"operation": "execute", "command": "python --version"}),
            ScriptedProvider.text("Python is installed."),
        ],
        granted=["terminal.execute"],
    )
    suspended = await agent.run("check the python version", plan=False)
    agent.confirmations.approve(suspended["confirmation_token"])

    resumed = await agent.resume()
    assert resumed["status"] == "completed"
    assert resumed["answer"] == "Python is installed."
    executed = resumed["results"][-1]["result"]
    assert executed["status"] == "completed"
    assert "Python" in executed["stdout"] + executed["stderr"]
    assert (await agent.pending())["status"] == "idle"


@pytest.mark.asyncio
async def test_resume_without_approval_stays_suspended(db, tmp_path):
    agent, _, _ = build(
        tmp_path,
        [ScriptedProvider.tool("terminal", {"operation": "execute", "command": "python --version"})],
        granted=["terminal.execute"],
    )
    await agent.run("check the python version", plan=False)
    again = await agent.resume()
    assert again["status"] == "awaiting_confirmation"
    assert (await agent.pending())["status"] == "awaiting_confirmation"


@pytest.mark.asyncio
async def test_denied_approval_is_reported_and_turn_continues(db, tmp_path):
    agent, _, _ = build(
        tmp_path,
        [
            ScriptedProvider.tool("terminal", {"operation": "execute", "command": "python --version"}),
            ScriptedProvider.text("The operator denied that command."),
        ],
        granted=["terminal.execute"],
    )
    suspended = await agent.run("check the python version", plan=False)
    agent.confirmations.deny(suspended["confirmation_token"])

    resumed = await agent.resume()
    assert resumed["status"] == "completed"
    assert resumed["results"][-1]["result"]["status"] == "token_denied"


@pytest.mark.asyncio
async def test_a_new_message_while_suspended_is_refused(db, tmp_path):
    agent, _, _ = build(
        tmp_path,
        [ScriptedProvider.tool("terminal", {"operation": "execute", "command": "python --version"})],
        granted=["terminal.execute"],
    )
    await agent.run("check the python version", plan=False)
    blocked = await agent.run("never mind, do something else", plan=False)
    assert blocked["status"] == "awaiting_confirmation"


@pytest.mark.asyncio
async def test_queued_calls_survive_a_suspension(db, tmp_path):
    """A gated call mid-turn must not discard the calls queued behind it."""
    (_ws(tmp_path) / "a.txt").write_text("A", encoding="utf-8")
    agent, provider, _ = build(
        tmp_path,
        [
            ScriptedProvider.tools(
                [
                    ("terminal", {"operation": "execute", "command": "python --version"}),
                    ("filesystem", {"operation": "read", "path": "a.txt"}),
                ]
            ),
            ScriptedProvider.text("Both done."),
        ],
        granted=["terminal.execute"],
    )
    suspended = await agent.run("run python and read a.txt", plan=False)
    assert suspended["status"] == "awaiting_confirmation"
    assert (await agent.pending())["queued_calls"] == 1

    agent.confirmations.approve(suspended["confirmation_token"])
    resumed = await agent.resume()

    assert resumed["status"] == "completed"
    tools_run = [r["tool"] for r in resumed["results"]]
    assert "filesystem" in tools_run

    # Both results must arrive in one message, matching the two tool_use ids.
    result_messages = [
        m
        for m in provider.calls[1]["messages"]
        if isinstance(m["content"], list)
        and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in m["content"])
    ]
    assert len(result_messages) == 1
    assert len(result_messages[0]["content"]) == 2


@pytest.mark.asyncio
async def test_nothing_to_resume_when_idle(db, tmp_path):
    agent, _, _ = build(tmp_path, [ScriptedProvider.text("ok")])
    assert (await agent.resume())["status"] == "nothing_to_resume"


# --------------- failure modes ---------------


@pytest.mark.asyncio
async def test_unconfigured_provider_reports_itself(db, tmp_path):
    agent = Agent(
        workspace=WorkspacePolicy(str(_ws(tmp_path))),
        provider=UnconfiguredProvider(),
        conversations=ConversationService(),
    )
    result = await agent.run("do something")
    assert result["status"] == "llm_not_configured"
    assert "ANTHROPIC_API_KEY" in result["detail"]


@pytest.mark.asyncio
async def test_provider_outage_is_a_status_not_a_crash(db, tmp_path):
    class Failing(ScriptedProvider):
        async def complete(self, system, messages, tools=None, output_schema=None):
            raise LLMUnavailable("rate limited")

    agent, _, _ = build(tmp_path, [])
    agent.provider = Failing([])
    result = await agent.run("hi", plan=False)
    assert result["status"] == "llm_unavailable"
    assert "rate limited" in result["detail"]


@pytest.mark.asyncio
async def test_refusal_is_surfaced(db, tmp_path):
    refusal = LLMResponse(stop_reason="refusal", refusal={"category": "cyber", "explanation": "declined"})
    agent, _, _ = build(tmp_path, [refusal])
    result = await agent.run("something disallowed", plan=False)
    assert result["status"] == "refused"
    assert result["detail"]["category"] == "cyber"


@pytest.mark.asyncio
async def test_runaway_tool_loop_is_capped(db, tmp_path):
    """A model that only ever calls tools must not loop forever."""
    forever = [
        ScriptedProvider.tool("filesystem", {"operation": "list", "path": "."}, call_id=f"c{i}")
        for i in range(10)
    ]
    agent, _, _ = build(tmp_path, forever, max_iterations=3)
    result = await agent.run("keep listing", plan=False)
    assert result["status"] == "max_iterations_reached"
    assert len(result["results"]) == 3
