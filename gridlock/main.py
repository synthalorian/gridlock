"""Gridlock FastAPI application."""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from gridlock.models import Capability, Job, JobStatus, Worker, WorkerStatus
from gridlock import redis_backend as rb

app = FastAPI(
    title="Gridlock",
    description="Distributed task queue with capability matching",
    version="0.2.0",
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
