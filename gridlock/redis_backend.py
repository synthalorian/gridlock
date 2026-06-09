"""Redis backend for Gridlock queue operations.

Uses Redis lists and sorted sets for queue management:
- Sorted sets for priority queues (score = priority)
- Strings (JSON) for job/worker storage
- Sets for indexing workers and jobs by status
"""

import json
import os
from datetime import UTC, datetime, timedelta
from typing import Any

import redis

from gridlock.models import Job, JobStatus, ProgressUpdate, Worker, WorkerStatus
from gridlock import matcher

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
_redis_client: redis.Redis | None = None


def get_redis() -> redis.Redis:
    """Get or create the Redis client singleton."""
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.from_url(REDIS_URL, decode_responses=True)
    return _redis_client


def _job_key(job_id: str) -> str:
    return f"gridlock:job:{job_id}"


def _worker_key(worker_id: str) -> str:
    return f"gridlock:worker:{worker_id}"


def _dlq_key() -> str:
    return "gridlock:jobs:dlq"


# ---------------------------------------------------------------------------
# Job operations
# ---------------------------------------------------------------------------

def create_job(job: Job) -> Job:
    """Store a job in Redis and add it to the pending queue if status is pending."""
    r = get_redis()
    job_json = job.model_dump_json()
    r.set(_job_key(job.id), job_json)
    if job.status == JobStatus.PENDING:
        r.zadd("gridlock:jobs:pending", {job.id: -job.priority})
    return job


def get_job(job_id: str) -> Job | None:
    """Retrieve a job by ID."""
    r = get_redis()
    data = r.get(_job_key(job_id))
    if data is None:
        return None
    return Job.model_validate_json(data)


def list_jobs() -> list[Job]:
    """List all jobs."""
    r = get_redis()
    keys = r.keys("gridlock:job:*")
    if not keys:
        return []
    data_list = r.mget(keys)
    jobs = []
    for data in data_list:
        if data is not None:
            jobs.append(Job.model_validate_json(data))
    return jobs


def update_job(job: Job) -> Job:
    """Update a job in Redis and move it between status queues."""
    r = get_redis()
    job_json = job.model_dump_json()
    r.set(_job_key(job.id), job_json)

    # Remove from all status queues
    r.zrem("gridlock:jobs:pending", job.id)
    r.srem("gridlock:jobs:running", job.id)
    r.srem("gridlock:jobs:completed", job.id)
    r.srem("gridlock:jobs:failed", job.id)
    r.srem("gridlock:jobs:cancelled", job.id)
    r.srem(_dlq_key(), job.id)

    # Add to appropriate queue
    if job.status == JobStatus.PENDING:
        r.zadd("gridlock:jobs:pending", {job.id: -job.priority})
    elif job.status == JobStatus.RUNNING:
        r.sadd("gridlock:jobs:running", job.id)
    elif job.status == JobStatus.COMPLETED:
        r.sadd("gridlock:jobs:completed", job.id)
    elif job.status == JobStatus.FAILED:
        r.sadd("gridlock:jobs:failed", job.id)
        r.sadd(_dlq_key(), job.id)
    elif job.status == JobStatus.CANCELLED:
        r.sadd("gridlock:jobs:cancelled", job.id)

    return job


def delete_job(job_id: str) -> bool:
    """Delete a job from Redis and all queues."""
    r = get_redis()
    deleted = r.delete(_job_key(job_id))
    r.zrem("gridlock:jobs:pending", job_id)
    r.srem("gridlock:jobs:running", job_id)
    r.srem("gridlock:jobs:completed", job_id)
    r.srem("gridlock:jobs:failed", job_id)
    r.srem("gridlock:jobs:cancelled", job_id)
    r.srem(_dlq_key(), job_id)
    return deleted > 0


def get_pending_jobs() -> list[Job]:
    """Get pending jobs ordered by priority (highest first)."""
    r = get_redis()
    job_ids = r.zrange("gridlock:jobs:pending", 0, -1)
    if not job_ids:
        return []
    jobs = []
    for job_id in job_ids:
        job = get_job(job_id)
        if job is not None:
            jobs.append(job)
    return jobs


# ---------------------------------------------------------------------------
# Worker operations
# ---------------------------------------------------------------------------

def create_worker(worker: Worker) -> Worker:
    """Store a worker in Redis and add to the worker index."""
    r = get_redis()
    worker_json = worker.model_dump_json()
    r.set(_worker_key(worker.id), worker_json)
    r.sadd("gridlock:workers", worker.id)
    return worker


def get_worker(worker_id: str) -> Worker | None:
    """Retrieve a worker by ID."""
    r = get_redis()
    data = r.get(_worker_key(worker_id))
    if data is None:
        return None
    return Worker.model_validate_json(data)


def list_workers() -> list[Worker]:
    """List all workers."""
    r = get_redis()
    worker_ids = r.smembers("gridlock:workers")
    if not worker_ids:
        return []
    keys = [_worker_key(wid) for wid in worker_ids]
    data_list = r.mget(keys)
    workers = []
    for data in data_list:
        if data is not None:
            workers.append(Worker.model_validate_json(data))
    return workers


def update_worker(worker: Worker) -> Worker:
    """Update a worker in Redis."""
    r = get_redis()
    worker_json = worker.model_dump_json()
    r.set(_worker_key(worker.id), worker_json)
    r.sadd("gridlock:workers", worker.id)
    return worker


def delete_worker(worker_id: str) -> bool:
    """Delete a worker from Redis and the worker index."""
    r = get_redis()
    deleted = r.delete(_worker_key(worker_id))
    r.srem("gridlock:workers", worker_id)
    return deleted > 0


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------

def find_matching_workers(job_id: str) -> list[Worker]:
    """Find all workers capable of running the given job."""
    job = get_job(job_id)
    if job is None:
        return []
    workers = list_workers()
    return [w for w in workers if job.can_run_on(w)]


def find_ranked_matches(job_id: str, min_score: float = 0.0) -> list[matcher.MatchResult]:
    """Find workers ranked by match quality score.

    Returns workers sorted by descending match score.
    Only includes workers with score >= min_score and no missing capabilities.
    """
    job = get_job(job_id)
    if job is None:
        return []
    workers = list_workers()
    return matcher.find_best_matches(job, workers, min_score=min_score)


def get_compatibility_graph() -> matcher.CompatibilityGraph:
    """Build a full compatibility graph for all pending jobs and available workers."""
    jobs = list_jobs()
    workers = [w for w in list_workers() if w.status != WorkerStatus.OFFLINE]
    return matcher.build_compatibility_graph(jobs, workers)


# ---------------------------------------------------------------------------
# Queue operations (lists for FIFO / sorted sets for priority)
# ---------------------------------------------------------------------------

def enqueue_job(job_id: str) -> bool:
    """Push a job ID to the tail of the FIFO queue (list)."""
    r = get_redis()
    job = get_job(job_id)
    if job is None:
        return False
    r.lpush("gridlock:queue:fifo", job_id)
    return True


def dequeue_job() -> str | None:
    """Pop a job ID from the head of the FIFO queue (list)."""
    r = get_redis()
    job_id = r.rpop("gridlock:queue:fifo")
    return job_id


def get_queue_length() -> int:
    """Get the number of jobs in the FIFO queue."""
    r = get_redis()
    return r.llen("gridlock:queue:fifo")


def get_queue_contents() -> list[str]:
    """Get all job IDs in the FIFO queue without removing them."""
    r = get_redis()
    return r.lrange("gridlock:queue:fifo", 0, -1)


# ---------------------------------------------------------------------------
# Health check / heartbeat
# ---------------------------------------------------------------------------

HEARTBEAT_TIMEOUT_SECONDS = int(os.getenv("GRIDLOCK_HEARTBEAT_TIMEOUT", "30"))


def get_workers_by_status(status: WorkerStatus) -> list[Worker]:
    """Get all workers with the given status."""
    workers = list_workers()
    return [w for w in workers if w.status == status]


def get_stale_workers(timeout_seconds: int = HEARTBEAT_TIMEOUT_SECONDS) -> list[Worker]:
    """Find workers whose last heartbeat is older than timeout_seconds."""
    cutoff = datetime.now(UTC) - timedelta(seconds=timeout_seconds)
    workers = list_workers()
    stale = []
    for worker in workers:
        if worker.last_heartbeat < cutoff:
            stale.append(worker)
    return stale


def mark_worker_offline(worker_id: str) -> Worker | None:
    """Mark a worker as offline."""
    worker = get_worker(worker_id)
    if worker is None:
        return None
    worker.status = WorkerStatus.OFFLINE
    worker.current_job_id = None
    return update_worker(worker)


def check_and_mark_stale_workers(timeout_seconds: int = HEARTBEAT_TIMEOUT_SECONDS) -> list[str]:
    """Find stale workers and mark them offline. Returns list of worker IDs affected."""
    stale = get_stale_workers(timeout_seconds)
    affected = []
    for worker in stale:
        if worker.status != WorkerStatus.OFFLINE:
            mark_worker_offline(worker.id)
            affected.append(worker.id)
    return affected


# ---------------------------------------------------------------------------
# Job dispatch and execution lifecycle
# ---------------------------------------------------------------------------

def dispatch_job(job_id: str, worker_id: str) -> Job | None:
    """Dispatch a pending job to an available worker.

    Updates job status to RUNNING, assigns worker_id, sets started_at.
    Updates worker status to BUSY, sets current_job_id.
    Returns the updated job or None if dispatch failed.
    """
    job = get_job(job_id)
    if job is None:
        return None
    if job.status != JobStatus.PENDING:
        return None
    if job.next_retry_at is not None and datetime.now(UTC) < job.next_retry_at:
        return None

    worker = get_worker(worker_id)
    if worker is None:
        return None
    if worker.status != WorkerStatus.AVAILABLE:
        return None
    if not job.can_run_on(worker):
        return None

    job.status = JobStatus.RUNNING
    job.worker_id = worker_id
    job.started_at = datetime.now(UTC)
    update_job(job)

    worker.status = WorkerStatus.BUSY
    worker.current_job_id = job_id
    update_worker(worker)

    return job


def complete_job(job_id: str, result: dict[str, Any] | None = None) -> Job | None:
    """Mark a running job as completed and release its worker.

    Returns the updated job or None if the job was not found or not running.
    """
    job = get_job(job_id)
    if job is None:
        return None
    if job.status != JobStatus.RUNNING:
        return None

    job.status = JobStatus.COMPLETED
    job.completed_at = datetime.now(UTC)
    job.result = result or {}
    update_job(job)

    if job.worker_id:
        _release_worker(job.worker_id)

    return job


def fail_job(job_id: str, error: str | None = None) -> Job | None:
    """Handle a running job failure.

    If retries remain, the job is returned to PENDING with exponential-backoff
    scheduling.  Otherwise it is moved to FAILED and added to the dead letter
    queue.  Returns the updated job or None if the job was not found or not
    running.
    """
    job = get_job(job_id)
    if job is None:
        return None
    if job.status != JobStatus.RUNNING:
        return None

    error_msg = error or "Unknown error"

    if job.worker_id:
        _release_worker(job.worker_id)

    if job.retry_count < job.max_retries:
        job.retry_count += 1
        job.errors.append(error_msg)
        job.error = error_msg
        job.status = JobStatus.PENDING
        job.worker_id = None
        job.started_at = None
        job.completed_at = None
        job.progress = 0.0
        backoff = job.retry_delay_seconds * (2 ** (job.retry_count - 1))
        job.next_retry_at = datetime.now(UTC) + timedelta(seconds=backoff)
        update_job(job)
        return job

    job.status = JobStatus.FAILED
    job.completed_at = datetime.now(UTC)
    job.error = error_msg
    job.errors.append(error_msg)
    job.next_retry_at = None
    update_job(job)

    return job


def cancel_job(job_id: str) -> Job | None:
    """Cancel a pending or running job and release its worker if running.

    Returns the updated job or None if the job was not found or already terminal.
    """
    job = get_job(job_id)
    if job is None:
        return None
    if job.status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED):
        return None

    was_running = job.status == JobStatus.RUNNING
    job.status = JobStatus.CANCELLED
    job.completed_at = datetime.now(UTC)
    update_job(job)

    if was_running and job.worker_id:
        _release_worker(job.worker_id)

    return job


def _release_worker(worker_id: str) -> Worker | None:
    """Mark a worker as available and clear its current job assignment."""
    worker = get_worker(worker_id)
    if worker is None:
        return None
    worker.status = WorkerStatus.AVAILABLE
    worker.current_job_id = None
    return update_worker(worker)


def get_next_dispatchable_job() -> Job | None:
    """Find the highest priority pending job that has at least one available matching worker.

    Returns the job or None if no dispatchable jobs exist.
    """
    pending = get_pending_jobs()
    available_workers = [w for w in list_workers() if w.status == WorkerStatus.AVAILABLE]
    now = datetime.now(UTC)

    for job in pending:
        if job.next_retry_at is not None and now < job.next_retry_at:
            continue
        for worker in available_workers:
            if job.can_run_on(worker):
                return job
    return None


def auto_dispatch() -> dict[str, str] | None:
    """Automatically dispatch the highest priority pending job to the best matching worker.

    Returns a dict with job_id and worker_id on success, or None if no dispatch occurred.
    """
    job = get_next_dispatchable_job()
    if job is None:
        return None

    from gridlock.matcher import find_best_matches

    available_workers = [w for w in list_workers() if w.status == WorkerStatus.AVAILABLE]
    matches = find_best_matches(job, available_workers, min_score=0.0)
    if not matches:
        return None

    best_worker_id = matches[0].worker_id
    dispatched = dispatch_job(job.id, best_worker_id)
    if dispatched is None:
        return None

    return {"job_id": job.id, "worker_id": best_worker_id}


# ---------------------------------------------------------------------------
# Progress updates (WebSocket streaming)
# ---------------------------------------------------------------------------

def update_job_progress(job_id: str, progress: float, message: str | None = None, metadata: dict[str, Any] | None = None) -> Job | None:
    """Update a job's progress percentage and broadcast a progress update.

    Returns the updated job or None if the job was not found.
    """
    job = get_job(job_id)
    if job is None:
        return None

    job.progress = progress
    update_job(job)

    update = ProgressUpdate(
        job_id=job_id,
        progress=progress,
        message=message,
        metadata=metadata,
    )
    publish_progress_update(update)
    return job


def _progress_channel(job_id: str) -> str:
    return f"gridlock:progress:{job_id}"


def publish_progress_update(update: ProgressUpdate) -> None:
    """Publish a progress update to the Redis pub/sub channel for the job."""
    r = get_redis()
    channel = _progress_channel(update.job_id)
    r.publish(channel, update.model_dump_json())


def subscribe_progress_updates(job_id: str):
    """Subscribe to progress updates for a specific job.

    Yields ProgressUpdate objects as they are published.
    """
    r = get_redis()
    pubsub = r.pubsub()
    channel = _progress_channel(job_id)
    pubsub.subscribe(channel)
    try:
        for message in pubsub.listen():
            if message["type"] == "message":
                data = message["data"]
                if isinstance(data, bytes):
                    data = data.decode("utf-8")
                yield ProgressUpdate.model_validate_json(data)
    finally:
        pubsub.unsubscribe(channel)
        pubsub.close()


# ---------------------------------------------------------------------------
# Retry and dead letter queue
# ---------------------------------------------------------------------------

MAX_RETRY_DELAY_SECONDS = int(os.getenv("GRIDLOCK_MAX_RETRY_DELAY_SECONDS", "3600"))


def retry_failed_job(job_id: str) -> Job | None:
    """Move a failed job from the dead letter queue back to PENDING.

    Resets retry state so it can be dispatched again.  Returns the updated job
    or None if the job was not found or not in a failed state.
    """
    job = get_job(job_id)
    if job is None:
        return None
    if job.status != JobStatus.FAILED:
        return None

    job.status = JobStatus.PENDING
    job.retry_count = 0
    job.next_retry_at = None
    job.completed_at = None
    job.error = None
    update_job(job)
    return job


def list_dead_letter_jobs() -> list[Job]:
    """Return all jobs currently in the dead letter queue."""
    r = get_redis()
    job_ids = r.smembers(_dlq_key())
    jobs = []
    for job_id in job_ids:
        job = get_job(job_id)
        if job is not None:
            jobs.append(job)
    return jobs


def process_retries(now: datetime | None = None) -> list[str]:
    """Process jobs whose retry backoff has expired and ensure they are queued.

    Because update_job already adds retried jobs to the pending sorted set,
    this function currently validates queue consistency and returns the IDs of
    jobs that are ready for dispatch.  Callers can use it in a background loop.
    """
    if now is None:
        now = datetime.now(UTC)
    r = get_redis()
    pending = get_pending_jobs()
    ready: list[str] = []
    for job in pending:
        if job.next_retry_at is None:
            continue
        if now >= job.next_retry_at:
            r.zadd("gridlock:jobs:pending", {job.id: -job.priority})
            ready.append(job.id)
    return ready


# ---------------------------------------------------------------------------
# Cleanup / testing helpers
# ---------------------------------------------------------------------------

def flush_all() -> None:
    """Delete all Gridlock keys from Redis.  USE WITH CARE."""
    r = get_redis()
    keys = r.keys("gridlock:*")
    if keys:
        r.delete(*keys)
