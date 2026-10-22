"""Conversation persistence.

These matter because a malformed history makes the next Messages API request
invalid, and because a parked approval has to survive a restart.
"""

import pytest

from app.core.conversations import ConversationService, SuspendedTurn


@pytest.mark.asyncio
async def test_history_round_trips_text_and_blocks(db):
    service = ConversationService()
    await service.add_user("s1", "hello subh")
    await service.add_assistant("s1", [{"type": "text", "text": "hi"}], text="hi")

    history = await service.history("s1")
    assert history[0] == {"role": "user", "content": "hello subh"}
    # Assistant content must come back as the provider's own blocks.
    assert history[1]["content"] == [{"type": "text", "text": "hi"}]


@pytest.mark.asyncio
async def test_thinking_and_tool_use_blocks_survive(db):
    """Thinking blocks must be replayable unchanged on the same model."""
    service = ConversationService()
    blocks = [
        {"type": "thinking", "thinking": "reasoning"},
        {"type": "tool_use", "id": "tu_1", "name": "filesystem", "input": {"operation": "list"}},
    ]
    await service.add_user("s1", "list files")
    await service.add_assistant("s1", blocks)

    stored = (await service.history("s1"))[1]["content"]
    assert stored == blocks


@pytest.mark.asyncio
async def test_tool_results_are_one_message(db):
    service = ConversationService()
    await service.add_user("s1", "do two things")
    await service.add_assistant("s1", [{"type": "tool_use", "id": "a", "name": "x", "input": {}}])
    await service.add_tool_results(
        "s1",
        [
            {"type": "tool_result", "tool_use_id": "a", "content": "1"},
            {"type": "tool_result", "tool_use_id": "b", "content": "2"},
        ],
    )
    history = await service.history("s1")
    assert len(history) == 3
    assert len(history[-1]["content"]) == 2


@pytest.mark.asyncio
async def test_window_never_starts_with_orphaned_tool_results(db):
    """A dangling tool_result would make the next API request invalid."""
    service = ConversationService(history_limit=3)
    for index in range(6):
        await service.add_user("s1", f"message {index}")
        await service.add_assistant("s1", [{"type": "tool_use", "id": f"tu_{index}", "name": "x", "input": {}}])
        await service.add_tool_results("s1", [{"type": "tool_result", "tool_use_id": f"tu_{index}", "content": "{}"}])

    history = await service.history("s1")
    assert len(history) <= 3
    first = history[0]
    orphaned = isinstance(first["content"], list) and any(
        b.get("type") == "tool_result" for b in first["content"]
    )
    assert orphaned is False


@pytest.mark.asyncio
async def test_suspended_turn_survives_a_restart(db):
    """The parked turn is in the database, not process memory."""
    parked = SuspendedTurn(
        completed_results=[{"type": "tool_result", "tool_use_id": "a", "content": "{}"}],
        pending_call={"id": "b", "name": "terminal", "arguments": {"command": "python --version"}},
        queued_calls=[{"id": "c", "name": "filesystem", "arguments": {}}],
        confirmation_token="tok_123",
    )
    await ConversationService().add_user("s1", "run something")
    await ConversationService().set_suspended("s1", parked)

    # A brand-new service object stands in for a fresh process.
    restored = await ConversationService().get_suspended("s1")
    assert restored.confirmation_token == "tok_123"
    assert restored.pending_call["arguments"]["command"] == "python --version"
    assert len(restored.queued_calls) == 1
    assert len(restored.completed_results) == 1


@pytest.mark.asyncio
async def test_clearing_a_suspension(db):
    service = ConversationService()
    await service.add_user("s1", "x")
    await service.set_suspended("s1", SuspendedTurn(confirmation_token="t"))
    await service.set_suspended("s1", None)
    assert await service.get_suspended("s1") is None


@pytest.mark.asyncio
async def test_sessions_and_reset(db):
    service = ConversationService()
    await service.add_user("s1", "first message becomes the title")
    await service.add_user("s2", "another")

    listing = {s["session_id"]: s for s in await service.sessions()}
    assert set(listing) == {"s1", "s2"}
    assert listing["s1"]["title"] == "first message becomes the title"
    assert listing["s1"]["messages"] == 1

    assert await service.reset("s1") is True
    assert await service.reset("s1") is False
    assert await service.history("s1") == []


@pytest.mark.asyncio
async def test_transcript_is_human_readable(db):
    service = ConversationService()
    await service.add_user("s1", "hello")
    await service.add_assistant("s1", [{"type": "text", "text": "hi there"}], text="hi there")
    # Tool-result messages carry no text and must not clutter a chat UI.
    await service.add_tool_results("s1", [{"type": "tool_result", "tool_use_id": "a", "content": "{}"}])

    transcript = await service.transcript("s1")
    assert [(m["role"], m["text"]) for m in transcript] == [("user", "hello"), ("assistant", "hi there")]
