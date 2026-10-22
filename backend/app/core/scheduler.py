"""Task automation and scheduling (Phase 5).

A single asyncio loop wakes on a tick, claims whatever is due, and runs each
task through the normal agent path - so a scheduled task is subject to exactly
the same permission gate, allowlist and approval rules as an interactive one.

Error recovery is explicit: a failed run is retried with linear backoff up to
the task's `max_retries`, each attempt recorded as its own TaskRun. A task that
needs human approval does not fail and does not retry - it parks, because
retrying would just queue another approval nobody asked for.
"""

import asyncio
import contextlib

from app.db.repository import TaskRepository

# Outcomes that mean "do not retry": the task did what it could.
NON_RETRYABLE = {"completed", "awaiting_confirmation", "clarification_needed", "llm_not_configured"}


class Scheduler:
    def __init__(
        self,
        agent,
        repository: TaskRepository = None,
        audit=None,
        tick_seconds: int = 15,
        backoff_seconds: int = 5,
    ):
        self.agent = agent
        self.repository = repository if repository is not None else TaskRepository()
        self.audit = audit
        self.tick_seconds = tick_seconds
        self.backoff_seconds = backoff_seconds
        self._task: asyncio.Task | None = None
        self._stopping = asyncio.Event()
        self.ticks = 0
        self.last_error: str | None = None

    # ---------- lifecycle ----------

    async def start(self):
        if self._task is not None:
            return
        self._stopping.clear()
        self._task = asyncio.create_task(self._run_forever(), name="subh-scheduler")

    async def stop(self):
        self._stopping.set()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def status(self) -> dict:
        return {
            "running": self.running,
            "tick_seconds": self.tick_seconds,
            "ticks": self.ticks,
            "last_error": self.last_error,
        }

    # ---------- loop ----------

    async def _run_forever(self):
        while not self._stopping.is_set():
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # The scheduler must outlive a single bad task.
                self.last_error = str(exc)[:300]
                self._record("scheduler.tick", "error", {"detail": self.last_error})
            try:
                await asyncio.wait_for(self._stopping.wait(), timeout=self.tick_seconds)
            except asyncio.TimeoutError:
                pass

    async def tick(self) -> list[dict]:
        """Run everything currently due. Returns one summary per task."""
        self.ticks += 1
        outcomes = []
        for task in await self.repository.due():
            outcomes.append(await self.run_task(task))
        return outcomes

    async def run_task(self, task: dict) -> dict:
        """Execute one task with retries. Each attempt is its own TaskRun."""
        attempts = max(1, (task.get("max_retries") or 0) + 1)
        last = {"status": "unknown"}

        for attempt in range(1, attempts + 1):
            run_id = await self.repository.start_run(task["id"], attempt)
            try:
                result = await self.agent.run(task["prompt"], session_id=task["session_id"])
                status = result.get("status", "unknown")
                last = result
            except Exception as exc:
                status = "error"
                last = {"status": "error", "detail": str(exc)[:300]}

            await self.repository.finish_run(
                run_id,
                status,
                {"answer": last.get("answer"), "detail": last.get("detail")},
            )
            self._record(f"task.{task['name']}", status, {"attempt": attempt, "task_id": task["id"]})

            if status in NON_RETRYABLE:
                break
            if attempt < attempts:
                await asyncio.sleep(self.backoff_seconds * attempt)

        await self.repository.mark_ran(task["id"], last.get("status", "unknown"))
        return {"task_id": task["id"], "name": task["name"], "status": last.get("status")}

    async def run_now(self, task_id: int) -> dict | None:
        """Operator-triggered immediate run, bypassing the schedule."""
        task = await self.repository.get(task_id)
        if task is None:
            return None
        return await self.run_task(task)

    def _record(self, action: str, status: str, detail: dict = None):
        if self.audit is not None:
            self.audit.record("scheduler", action, status, detail)
