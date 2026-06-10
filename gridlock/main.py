"""Gridlock FastAPI application."""

import asyncio
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from typing import Any

from gridlock.models import Capability, Job, JobStatus, ProgressUpdate, Worker, WorkerStatus
from gridlock import redis_backend as rb
from gridlock.matcher import MatchResult

HEARTBEAT_INTERVAL_SECONDS = int(os.getenv("GRIDLOCK_HEARTBEAT_INTERVAL", "10"))


class _ConnectionManager:
    """In-memory manager for WebSocket progress streaming connections."""

    def __init__(self):
        self._connections: dict[str, list[WebSocket]] = {}

    async def connect(self, job_id: str, websocket: WebSocket) -> None:
        if job_id not in self._connections:
            self._connections[job_id] = []
        self._connections[job_id].append(websocket)

    def disconnect(self, job_id: str, websocket: WebSocket) -> None:
        if job_id in self._connections:
            self._connections[job_id] = [ws for ws in self._connections[job_id] if ws != websocket]
            if not self._connections[job_id]:
                del self._connections[job_id]

    async def broadcast(self, job_id: str, data: dict) -> None:
        if job_id not in self._connections:
            return
        for ws in list(self._connections[job_id]):
            try:
                await ws.send_json(data)
            except Exception:
                pass


_connection_manager = _ConnectionManager()

app = FastAPI(
    title="Gridlock",
    description="Distributed task queue with capability matching",
    version="1.0.0",
)

_static_dir = Path(__file__).parent / "static"
if _static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")


@app.get("/", include_in_schema=False)
async def root() -> FileResponse:
    return FileResponse(_static_dir / "index.html")


class CreateJobRequest(BaseModel):
    """Request body for creating a new job."""

    name: str
    payload: dict | None = None
    required_capabilities: list[Capability] | None = None
    priority: int = 0
    max_retries: int = 0
    retry_delay_seconds: int = 1


class CreateWorkerRequest(BaseModel):
    """Request body for registering a new worker."""

    id: str
    capabilities: list[Capability] | None = None


class DispatchJobRequest(BaseModel):
    """Request body for dispatching a job to a specific worker."""

    worker_id: str | None = None


class CompleteJobRequest(BaseModel):
    """Request body for completing a job."""

    result: dict[str, Any] | None = None


class FailJobRequest(BaseModel):
    """Request body for failing a job."""

    error: str | None = None


class ProgressUpdateRequest(BaseModel):
    """Request body for updating job progress."""

    progress: float = Field(..., ge=0.0, le=100.0)
    message: str | None = None
    metadata: dict[str, Any] | None = None


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
        max_retries=request.max_retries,
        retry_delay_seconds=request.retry_delay_seconds,
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


@app.post("/jobs/{job_id}/dispatch", response_model=Job)
async def dispatch_job(job_id: str, request: DispatchJobRequest) -> Job:
    """Dispatch a pending job to a worker.

    If worker_id is provided, dispatch to that specific worker.
    Otherwise, auto-match to the best available worker.
    """
    job = rb.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != JobStatus.PENDING:
        raise HTTPException(status_code=409, detail=f"Job is not pending (status: {job.status.value})")

    worker_id = request.worker_id
    if worker_id is None:
        result = rb.auto_dispatch()
        if result is None:
            raise HTTPException(status_code=409, detail="No available matching workers found")
        dispatched = rb.get_job(result["job_id"])
    else:
        dispatched = rb.dispatch_job(job_id, worker_id)
        if dispatched is None:
            raise HTTPException(status_code=409, detail="Worker not available or does not match job requirements")

    return dispatched


@app.post("/jobs/{job_id}/complete", response_model=Job)
async def complete_job(job_id: str, request: CompleteJobRequest) -> Job:
    """Mark a running job as completed."""
    job = rb.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != JobStatus.RUNNING:
        raise HTTPException(status_code=409, detail=f"Job is not running (status: {job.status.value})")

    completed = rb.complete_job(job_id, result=request.result)
    if completed is None:
        raise HTTPException(status_code=409, detail="Failed to complete job")
    return completed


@app.post("/jobs/{job_id}/fail", response_model=Job)
async def fail_job(job_id: str, request: FailJobRequest) -> Job:
    """Mark a running job as failed."""
    job = rb.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != JobStatus.RUNNING:
        raise HTTPException(status_code=409, detail=f"Job is not running (status: {job.status.value})")

    failed = rb.fail_job(job_id, error=request.error)
    if failed is None:
        raise HTTPException(status_code=409, detail="Failed to fail job")
    return failed


@app.post("/jobs/{job_id}/cancel", response_model=Job)
async def cancel_job(job_id: str) -> Job:
    """Cancel a pending or running job."""
    job = rb.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED):
        raise HTTPException(status_code=409, detail=f"Job is already terminal (status: {job.status.value})")

    cancelled = rb.cancel_job(job_id)
    if cancelled is None:
        raise HTTPException(status_code=409, detail="Failed to cancel job")
    return cancelled


@app.get("/jobs/dead-letter", response_model=list[Job])
async def list_dead_letter_jobs() -> list[Job]:
    """List all jobs currently in the dead letter queue."""
    return rb.list_dead_letter_jobs()


@app.post("/jobs/{job_id}/retry", response_model=Job)
async def retry_failed_job(job_id: str) -> Job:
    """Move a failed job from the dead letter queue back to pending for retry."""
    job = rb.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != JobStatus.FAILED:
        raise HTTPException(status_code=409, detail=f"Job is not failed (status: {job.status.value})")

    retried = rb.retry_failed_job(job_id)
    if retried is None:
        raise HTTPException(status_code=409, detail="Failed to retry job")
    return retried


@app.post("/jobs/{job_id}/progress", response_model=Job)
async def update_job_progress(job_id: str, request: ProgressUpdateRequest) -> Job:
    """Update the progress of a running job."""
    job = rb.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    updated = rb.update_job_progress(
        job_id,
        progress=request.progress,
        message=request.message,
        metadata=request.metadata,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="Job not found")

    from datetime import UTC, datetime

    await _connection_manager.broadcast(
        job_id,
        {
            "job_id": job_id,
            "progress": request.progress,
            "message": request.message,
            "timestamp": datetime.now(UTC).isoformat(),
            "metadata": request.metadata,
        },
    )
    return updated


@app.websocket("/ws/jobs/{job_id}/progress")
async def job_progress_websocket(websocket: WebSocket, job_id: str) -> None:
    """Stream real-time progress updates for a specific job via WebSocket."""
    job = rb.get_job(job_id)
    if job is None:
        await websocket.close(code=4004, reason="Job not found")
        return

    await websocket.accept()
    await _connection_manager.connect(job_id, websocket)
    try:
        while True:
            try:
                message = await websocket.receive_text()
                if message == "ping":
                    await websocket.send_text("pong")
            except WebSocketDisconnect:
                break
    finally:
        _connection_manager.disconnect(job_id, websocket)


@app.post("/dispatch/auto")
async def auto_dispatch() -> dict:
    """Automatically dispatch the highest priority pending job to the best matching worker."""
    result = rb.auto_dispatch()
    if result is None:
        raise HTTPException(status_code=409, detail="No dispatchable jobs found")
    return {"dispatched": True, "job_id": result["job_id"], "worker_id": result["worker_id"]}


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


@app.get("/match/{job_id}/ranked")
async def match_job_ranked(job_id: str, min_score: float = 0.0) -> dict:
    """Find workers ranked by match quality score.

    Query param `min_score` filters out workers below that threshold (default 0.0).
    """
    job = rb.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    results = rb.find_ranked_matches(job_id, min_score=min_score)
    return {
        "job_id": job_id,
        "matches": [
            {
                "worker_id": r.worker_id,
                "score": round(r.score, 4),
                "matched_capabilities": r.matched_capabilities,
                "missing_capabilities": r.missing_capabilities,
            }
            for r in results
        ],
        "match_count": len(results),
    }


@app.get("/graph/compatibility")
async def get_compatibility_graph() -> dict:
    """Get the full job-worker compatibility graph."""
    graph = rb.get_compatibility_graph()
    return {
        "jobs": graph.job_nodes,
        "workers": graph.worker_nodes,
        "edges": [
            {"job_id": j, "worker_id": w, "score": round(s, 4)}
            for j, w, s in graph.edges
        ],
        "edge_count": len(graph.edges),
    }


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
