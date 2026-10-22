"""Task automation, scheduling and error recovery (Phase 5)."""

import pytest

from app.core.scheduler import Scheduler
from app.db.repository import TaskRepository
from app.security.audit import AuditLog


class FakeAgent:
    """Records calls and returns a scripted sequence of outcomes."""

    def __init__(self, outcomes=None, raises=None):
        self.outcomes = list(outcomes or [{"status": "completed", "answer": "done"}])
        self.raises = raises
        self.calls = []

    async def run(self, message, session_id="default", plan=True):
        self.calls.append({"message": message, "session_id": session_id})
        if self.raises:
            raise self.raises
        return self.outcomes.pop(0) if self.outcomes else {"status": "completed", "answer": "done"}


def build(agent, backoff=0):
    return Scheduler(agent, TaskRepository(), AuditLog(), tick_seconds=1, backoff_seconds=backoff)


# --------------- scheduling ---------------


@pytest.mark.asyncio
async def test_due_once_task_runs_on_a_tick(db):
    agent = FakeAgent()
    scheduler = build(agent)
    await TaskRepository().create(name="greet", prompt="say hello", schedule_kind="once")

    outcomes = await scheduler.tick()
    assert [o["status"] for o in outcomes] == ["completed"]
    assert agent.calls[0]["message"] == "say hello"


@pytest.mark.asyncio
async def test_a_once_task_does_not_run_twice(db):
    agent = FakeAgent(outcomes=[{"status": "completed"}, {"status": "completed"}])
    scheduler = build(agent)
    await TaskRepository().create(name="greet", prompt="hello", schedule_kind="once")

    await scheduler.tick()
    await scheduler.tick()
    assert len(agent.calls) == 1


@pytest.mark.asyncio
async def test_interval_task_rearms_after_running(db):
    repository = TaskRepository()
    task = await repository.create(
        name="ping", prompt="check", schedule_kind="interval", interval_seconds=60
    )
    await build(FakeAgent()).run_task(task)
    assert (await repository.get(task["id"]))["next_run_at"] is not None


@pytest.mark.asyncio
async def test_future_tasks_are_not_due(db):
    agent = FakeAgent()
    await TaskRepository().create(
        name="later", prompt="x", schedule_kind="interval", interval_seconds=3600
    )
    assert await build(agent).tick() == []
    assert agent.calls == []


@pytest.mark.asyncio
async def test_disabled_task_is_skipped(db):
    repository = TaskRepository()
    task = await repository.create(name="off", prompt="x", schedule_kind="once")
    await repository.set_enabled(task["id"], False)

    agent = FakeAgent()
    assert await build(agent).tick() == []
    assert agent.calls == []


@pytest.mark.asyncio
async def test_run_now_ignores_the_schedule(db):
    repository = TaskRepository()
    task = await repository.create(
        name="manual", prompt="go", schedule_kind="interval", interval_seconds=3600
    )
    agent = FakeAgent()
    outcome = await build(agent).run_now(task["id"])
    assert outcome["status"] == "completed"
    assert len(agent.calls) == 1


@pytest.mark.asyncio
async def test_run_now_on_a_missing_task(db):
    assert await build(FakeAgent()).run_now(9999) is None


# --------------- error recovery ---------------


@pytest.mark.asyncio
async def test_failure_is_retried_then_recorded(db):
    """A transient failure should be retried up to max_retries."""
    agent = FakeAgent(
        outcomes=[
            {"status": "llm_unavailable", "detail": "rate limited"},
            {"status": "llm_unavailable", "detail": "rate limited"},
            {"status": "completed", "answer": "finally"},
        ]
    )
    repository = TaskRepository()
    task = await repository.create(name="flaky", prompt="x", schedule_kind="once", max_retries=2)

    outcome = await build(agent).run_task(task)
    assert outcome["status"] == "completed"
    assert len(agent.calls) == 3

    runs = await repository.runs(task["id"])
    assert [r["attempt"] for r in runs] == [3, 2, 1]
    assert [r["status"] for r in runs] == ["completed", "llm_unavailable", "llm_unavailable"]


@pytest.mark.asyncio
async def test_retries_are_bounded(db):
    agent = FakeAgent(outcomes=[{"status": "llm_unavailable"}] * 5)
    task = await TaskRepository().create(name="always", prompt="x", schedule_kind="once", max_retries=1)
    await build(agent).run_task(task)
    # One initial attempt plus one retry.
    assert len(agent.calls) == 2


@pytest.mark.asyncio
async def test_awaiting_confirmation_is_not_retried(db):
    """Retrying an approval request would just queue another one."""
    agent = FakeAgent(outcomes=[{"status": "awaiting_confirmation", "confirmation_token": "t"}] * 3)
    task = await TaskRepository().create(name="gated", prompt="run a command", schedule_kind="once", max_retries=2)

    outcome = await build(agent).run_task(task)
    assert outcome["status"] == "awaiting_confirmation"
    assert len(agent.calls) == 1


@pytest.mark.asyncio
async def test_clarification_is_not_retried(db):
    agent = FakeAgent(outcomes=[{"status": "clarification_needed", "question": "which?"}] * 3)
    task = await TaskRepository().create(name="vague", prompt="fix it", schedule_kind="once", max_retries=2)
    await build(agent).run_task(task)
    assert len(agent.calls) == 1


@pytest.mark.asyncio
async def test_an_exception_is_captured_as_a_failed_run(db):
    agent = FakeAgent(raises=RuntimeError("tool exploded"))
    repository = TaskRepository()
    task = await repository.create(name="boom", prompt="x", schedule_kind="once", max_retries=0)

    outcome = await build(agent).run_task(task)
    assert outcome["status"] == "error"
    runs = await repository.runs(task["id"])
    assert runs[0]["status"] == "error"
    assert "tool exploded" in runs[0]["detail"]["detail"]


@pytest.mark.asyncio
async def test_a_bad_task_does_not_kill_the_scheduler(db):
    """The loop must survive one task raising."""
    agent = FakeAgent(raises=RuntimeError("bad"))
    scheduler = build(agent)
    await TaskRepository().create(name="boom", prompt="x", schedule_kind="once", max_retries=0)

    await scheduler.tick()  # must not raise
    assert scheduler.ticks == 1


# --------------- lifecycle ---------------


@pytest.mark.asyncio
async def test_start_and_stop_are_idempotent(db):
    scheduler = build(FakeAgent())
    await scheduler.start()
    await scheduler.start()
    assert scheduler.running is True
    await scheduler.stop()
    assert scheduler.running is False
    await scheduler.stop()


@pytest.mark.asyncio
async def test_status_reports_state(db):
    scheduler = build(FakeAgent())
    status = scheduler.status()
    assert status["running"] is False
    assert status["tick_seconds"] == 1
    assert status["last_error"] is None


@pytest.mark.asyncio
async def test_scheduled_runs_go_through_the_normal_agent_path(db):
    """A scheduled task must be as gated as an interactive one."""
    agent = FakeAgent()
    task = await TaskRepository().create(
        name="nightly", prompt="summarise", schedule_kind="once", session_id="scheduled"
    )
    await build(agent).run_task(task)
    # Same Agent.run entry point, same session plumbing.
    assert agent.calls[0]["session_id"] == "scheduled"
