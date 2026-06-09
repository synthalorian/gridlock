"""Redis backend for Gridlock queue operations.

Uses Redis lists and sorted sets for queue management:
- Sorted sets for priority queues (score = priority)
- Strings (JSON) for job/worker storage
- Sets for indexing workers and jobs by status
"""

import json
import os
from typing import Any

import redis

from gridlock.models import Job, JobStatus, Worker

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


# ---------------------------------------------------------------------------
# Job operations
# ---------------------------------------------------------------------------

def create_job(job: Job) -> Job:
    """Store a job in Redis and add it to the pending queue."""
    r = get_redis()
    job_json = job.model_dump_json()
    r.set(_job_key(job.id), job_json)
    # Add to pending sorted set with priority as score (higher = first)
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

    # Add to appropriate queue
    if job.status == JobStatus.PENDING:
        r.zadd("gridlock:jobs:pending", {job.id: -job.priority})
    elif job.status == JobStatus.RUNNING:
        r.sadd("gridlock:jobs:running", job.id)
    elif job.status == JobStatus.COMPLETED:
        r.sadd("gridlock:jobs:completed", job.id)
    elif job.status == JobStatus.FAILED:
        r.sadd("gridlock:jobs:failed", job.id)
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
# Cleanup / testing helpers
# ---------------------------------------------------------------------------

def flush_all() -> None:
    """Delete all Gridlock keys from Redis.  USE WITH CARE."""
    r = get_redis()
    keys = r.keys("gridlock:*")
    if keys:
        r.delete(*keys)
