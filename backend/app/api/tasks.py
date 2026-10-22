from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.core import runtime
from app.security.auth import SCOPE_ADMIN, SCOPE_READ, require

router = APIRouter(prefix="/tasks", tags=["automation"])

SCHEDULE_KINDS = ("once", "interval", "cron")


class TaskRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    prompt: str = Field(min_length=1)
    session_id: str = "scheduled"
    schedule_kind: str = "once"
    interval_seconds: int | None = None
    cron: str | None = None
    max_retries: int = Field(default=2, ge=0, le=10)


@router.get("")
async def list_tasks(_=Depends(require(SCOPE_READ))):
    return {"tasks": await runtime.task_repository.list(), "scheduler": runtime.scheduler.status()}


@router.post("")
async def create_task(request: TaskRequest, _=Depends(require(SCOPE_ADMIN))):
    if request.schedule_kind not in SCHEDULE_KINDS:
        return {"status": "unsupported_schedule", "allowed": list(SCHEDULE_KINDS)}
    if request.schedule_kind == "interval" and not request.interval_seconds:
        return {"status": "interval_seconds_required"}
    if request.schedule_kind == "cron":
        if not request.cron:
            return {"status": "cron_required"}
        from croniter import croniter

        if not croniter.is_valid(request.cron):
            return {"status": "invalid_cron", "cron": request.cron}

    task = await runtime.task_repository.create(**request.model_dump())
    runtime.audit.record("operator", f"task.create:{task['name']}", "created", {"id": task["id"]})
    return {"status": "created", "task": task}


@router.get("/{task_id}")
async def get_task(task_id: int, _=Depends(require(SCOPE_READ))):
    task = await runtime.task_repository.get(task_id)
    if task is None:
        return {"status": "not_found", "task_id": task_id}
    return {"task": task, "runs": await runtime.task_repository.runs(task_id)}


@router.post("/{task_id}/run")
async def run_task_now(task_id: int, _=Depends(require(SCOPE_ADMIN))):
    """Run a task immediately, independent of its schedule."""
    outcome = await runtime.scheduler.run_now(task_id)
    if outcome is None:
        return {"status": "not_found", "task_id": task_id}
    # The outcome carries its own "status" (the run's result), so it is spread
    # first and the envelope status is set after it rather than being clobbered.
    return {**outcome, "status": "ran", "run_status": outcome.get("status")}


@router.post("/{task_id}/enable")
async def enable_task(task_id: int, _=Depends(require(SCOPE_ADMIN))):
    task = await runtime.task_repository.set_enabled(task_id, True)
    return {"status": "enabled", "task": task} if task else {"status": "not_found"}


@router.post("/{task_id}/disable")
async def disable_task(task_id: int, _=Depends(require(SCOPE_ADMIN))):
    task = await runtime.task_repository.set_enabled(task_id, False)
    return {"status": "disabled", "task": task} if task else {"status": "not_found"}


@router.delete("/{task_id}")
async def delete_task(task_id: int, _=Depends(require(SCOPE_ADMIN))):
    removed = await runtime.task_repository.delete(task_id)
    return {"status": "deleted" if removed else "not_found", "task_id": task_id}
