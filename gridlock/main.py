"""Gridlock FastAPI application."""

import asyncio
import os

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from gridlock.models import Capability, Job, JobStatus, Worker, WorkerStatus
from gridlock import redis_backend as rb

HEARTBEAT_INTERVAL_SECONDS = int(os.getenv("GRIDLOCK_HEARTBEAT_INTERVAL", "10"))

app = FastAPI(
    title="Gridlock",
    description="Distributed task queue with capability matching",
    version="0.3.0",
)


class CreateJobRequest(BaseModel):
    """Request body for creating a new job."""

    name: str
    payload: dict | None = None
    required_capabilities: list[Capability] | None = None
    priority: int = 0


class CreateWorkerRequest(BaseModel):
    """Request body for registering a new worker."""

    id: str
    capabilities: list[Capability] | None = None


@app.get("/health")
async def health() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "ok"}


@app.post("/jobs", response_model=Job, status_code=201)
async def create_job(request: CreateJobRequest) -> Job:
    """Submit a new job to the queue."""
    job_id = f"job-{len(rb.list_jobs()) + 1}"
    job = Job(
        id=job_id,
        name=request.name,
        payload=request.payload or {},
        required_capabilities=request.required_capabilities or [],
        priority=request.priority,
    )
    rb.create_job(job)
    return job


@app.get("/jobs", response_model=list[Job])
async def list_jobs() -> list[Job]:
    """List all jobs."""
    return rb.list_jobs()


@app.get("/jobs/{job_id}", response_model=Job)
async def get_job(job_id: str) -> Job:
    """Get a specific job by ID."""
    job = rb.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.post("/workers", response_model=Worker, status_code=201)
async def create_worker(request: CreateWorkerRequest) -> Worker:
    """Register a new worker."""
    existing = rb.get_worker(request.id)
    if existing is not None:
        raise HTTPException(status_code=409, detail="Worker already exists")
    worker = Worker(
        id=request.id,
        capabilities=request.capabilities or [],
        status=WorkerStatus.AVAILABLE,
    )
    rb.create_worker(worker)
    return worker


@app.get("/workers", response_model=list[Worker])
async def list_workers() -> list[Worker]:
    """List all registered workers."""
    return rb.list_workers()


@app.get("/workers/{worker_id}", response_model=Worker)
async def get_worker(worker_id: str) -> Worker:
    """Get a specific worker by ID."""
    worker = rb.get_worker(worker_id)
    if worker is None:
        raise HTTPException(status_code=404, detail="Worker not found")
    return worker


@app.post("/workers/{worker_id}/heartbeat", response_model=Worker)
async def worker_heartbeat(worker_id: str) -> Worker:
    """Update worker heartbeat timestamp."""
    worker = rb.get_worker(worker_id)
    if worker is None:
        raise HTTPException(status_code=404, detail="Worker not found")
    from datetime import UTC, datetime

    worker.last_heartbeat = datetime.now(UTC)
    if worker.status == WorkerStatus.OFFLINE:
        worker.status = WorkerStatus.AVAILABLE
    rb.update_worker(worker)
    return worker


@app.get("/match/{job_id}")
async def match_job(job_id: str) -> dict:
    """Find workers capable of running a specific job."""
    job = rb.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    matches = rb.find_matching_workers(job_id)
    return {"job_id": job_id, "matches": matches, "match_count": len(matches)}


@app.get("/workers/{worker_id}/health")
async def get_worker_health(worker_id: str) -> dict:
    """Get the health status of a specific worker."""
    worker = rb.get_worker(worker_id)
    if worker is None:
        raise HTTPException(status_code=404, detail="Worker not found")
    stale = rb.get_stale_workers()
    is_stale = any(w.id == worker_id for w in stale)
    return {
        "worker_id": worker_id,
        "status": worker.status.value,
        "healthy": worker.status != WorkerStatus.OFFLINE and not is_stale,
        "last_heartbeat": worker.last_heartbeat.isoformat(),
    }


@app.get("/health/workers")
async def get_all_workers_health() -> dict:
    """Get health status summary for all workers."""
    workers = rb.list_workers()
    stale = rb.get_stale_workers()
    stale_ids = {w.id for w in stale}
    summary = []
    for worker in workers:
        is_stale = worker.id in stale_ids
        summary.append({
            "worker_id": worker.id,
            "status": worker.status.value,
            "healthy": worker.status != WorkerStatus.OFFLINE and not is_stale,
            "last_heartbeat": worker.last_heartbeat.isoformat(),
        })
    healthy_count = sum(1 for s in summary if s["healthy"])
    return {
        "total": len(summary),
        "healthy": healthy_count,
        "unhealthy": len(summary) - healthy_count,
        "workers": summary,
    }


@app.post("/health/check", response_model=dict)
async def run_health_check() -> dict:
    """Manually trigger a health check to mark stale workers offline."""
    affected = rb.check_and_mark_stale_workers()
    return {"stale_workers_marked_offline": affected, "count": len(affected)}


# ---------------------------------------------------------------------------
# Background heartbeat monitor
# ---------------------------------------------------------------------------

_monitor_task: asyncio.Task | None = None


async def _heartbeat_monitor() -> None:
    """Background task that periodically checks for stale workers."""
    while True:
        try:
            await asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS)
            rb.check_and_mark_stale_workers()
        except Exception:
            # Prevent monitor crash from bringing down the app
            pass


@app.on_event("startup")
async def _start_monitor() -> None:
    """Start the background heartbeat monitor on application startup."""
    global _monitor_task
    if _monitor_task is None or _monitor_task.done():
        _monitor_task = asyncio.create_task(_heartbeat_monitor())


@app.on_event("shutdown")
async def _stop_monitor() -> None:
    """Stop the background heartbeat monitor on application shutdown."""
    global _monitor_task
    if _monitor_task is not None and not _monitor_task.done():
        _monitor_task.cancel()
        try:
            await _monitor_task
        except asyncio.CancelledError:
            pass
        _monitor_task = None
