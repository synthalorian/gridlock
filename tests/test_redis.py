"""Tests for Gridlock Redis backend."""

import pytest

from gridlock.models import Capability, Job, JobStatus, Worker, WorkerStatus
from gridlock import redis_backend as rb


class TestJobOperations:
    """Job CRUD operations via Redis backend."""

    def test_create_and_get_job(self):
        job = Job(id="job-1", name="test-job")
        rb.create_job(job)
        fetched = rb.get_job("job-1")
        assert fetched is not None
        assert fetched.id == "job-1"
        assert fetched.name == "test-job"
        assert fetched.status == JobStatus.PENDING

    def test_get_job_not_found(self):
        assert rb.get_job("nonexistent") is None

    def test_list_jobs(self):
        rb.create_job(Job(id="job-1", name="a"))
        rb.create_job(Job(id="job-2", name="b"))
        jobs = rb.list_jobs()
        assert len(jobs) == 2
        ids = {j.id for j in jobs}
        assert ids == {"job-1", "job-2"}

    def test_list_jobs_empty(self):
        assert rb.list_jobs() == []

    def test_update_job_status(self):
        job = Job(id="job-1", name="test")
        rb.create_job(job)
        job.status = JobStatus.RUNNING
        rb.update_job(job)
        fetched = rb.get_job("job-1")
        assert fetched.status == JobStatus.RUNNING

    def test_update_job_moves_between_queues(self):
        job = Job(id="job-1", name="test", priority=10)
        rb.create_job(job)
        # Should be in pending queue
        pending = rb.get_pending_jobs()
        assert len(pending) == 1

        job.status = JobStatus.RUNNING
        rb.update_job(job)
        # Should no longer be in pending
        pending = rb.get_pending_jobs()
        assert len(pending) == 0

    def test_delete_job(self):
        job = Job(id="job-1", name="test")
        rb.create_job(job)
        assert rb.delete_job("job-1") is True
        assert rb.get_job("job-1") is None

    def test_delete_job_not_found(self):
        assert rb.delete_job("nonexistent") is False

    def test_pending_jobs_ordered_by_priority(self):
        rb.create_job(Job(id="job-low", name="low", priority=10))
        rb.create_job(Job(id="job-high", name="high", priority=50))
        rb.create_job(Job(id="job-mid", name="mid", priority=30))
        pending = rb.get_pending_jobs()
        ids = [j.id for j in pending]
        # Higher priority should come first
        assert ids == ["job-high", "job-mid", "job-low"]

    def test_pending_jobs_excludes_non_pending(self):
        job = Job(id="job-1", name="test")
        rb.create_job(job)
        job.status = JobStatus.RUNNING
        rb.update_job(job)
        assert rb.get_pending_jobs() == []


class TestWorkerOperations:
    """Worker CRUD operations via Redis backend."""

    def test_create_and_get_worker(self):
        worker = Worker(id="worker-1")
        rb.create_worker(worker)
        fetched = rb.get_worker("worker-1")
        assert fetched is not None
        assert fetched.id == "worker-1"
        assert fetched.status == WorkerStatus.AVAILABLE

    def test_get_worker_not_found(self):
        assert rb.get_worker("nonexistent") is None

    def test_list_workers(self):
        rb.create_worker(Worker(id="worker-1"))
        rb.create_worker(Worker(id="worker-2"))
        workers = rb.list_workers()
        assert len(workers) == 2
        ids = {w.id for w in workers}
        assert ids == {"worker-1", "worker-2"}

    def test_list_workers_empty(self):
        assert rb.list_workers() == []

    def test_update_worker(self):
        worker = Worker(id="worker-1")
        rb.create_worker(worker)
        worker.status = WorkerStatus.BUSY
        worker.current_job_id = "job-1"
        rb.update_worker(worker)
        fetched = rb.get_worker("worker-1")
        assert fetched.status == WorkerStatus.BUSY
        assert fetched.current_job_id == "job-1"

    def test_delete_worker(self):
        worker = Worker(id="worker-1")
        rb.create_worker(worker)
        assert rb.delete_worker("worker-1") is True
        assert rb.get_worker("worker-1") is None

    def test_delete_worker_not_found(self):
        assert rb.delete_worker("nonexistent") is False


class TestMatching:
    """Capability matching via Redis backend."""

    def test_find_matching_workers(self):
        worker = Worker(
            id="w1",
            capabilities=[Capability(name="gpu", value="nvidia-a100")],
        )
        rb.create_worker(worker)
        job = Job(
            id="j1",
            name="train",
            required_capabilities=[Capability(name="gpu", value="nvidia-a100")],
        )
        rb.create_job(job)
        matches = rb.find_matching_workers("j1")
        assert len(matches) == 1
        assert matches[0].id == "w1"

    def test_find_matching_workers_none(self):
        worker = Worker(id="w1", capabilities=[])
        rb.create_worker(worker)
        job = Job(
            id="j1",
            name="train",
            required_capabilities=[Capability(name="gpu", value="nvidia-a100")],
        )
        rb.create_job(job)
        matches = rb.find_matching_workers("j1")
        assert matches == []

    def test_find_matching_workers_job_not_found(self):
        assert rb.find_matching_workers("nonexistent") == []


class TestQueueOperations:
    """FIFO queue operations via Redis backend."""

    def test_enqueue_and_dequeue(self):
        job = Job(id="job-1", name="test")
        rb.create_job(job)
        assert rb.enqueue_job("job-1") is True
        assert rb.get_queue_length() == 1
        dequeued = rb.dequeue_job()
        assert dequeued == "job-1"
        assert rb.get_queue_length() == 0

    def test_enqueue_nonexistent_job(self):
        assert rb.enqueue_job("nonexistent") is False

    def test_dequeue_empty(self):
        assert rb.dequeue_job() is None

    def test_queue_order(self):
        for i in range(3):
            job = Job(id=f"job-{i}", name=f"test-{i}")
            rb.create_job(job)
            rb.enqueue_job(job.id)
        # FIFO: first enqueued should be first dequeued
        assert rb.dequeue_job() == "job-0"
        assert rb.dequeue_job() == "job-1"
        assert rb.dequeue_job() == "job-2"

    def test_get_queue_contents(self):
        for i in range(2):
            job = Job(id=f"job-{i}", name=f"test-{i}")
            rb.create_job(job)
            rb.enqueue_job(job.id)
        contents = rb.get_queue_contents()
        assert contents == ["job-1", "job-0"]  # lpush order


class TestCleanup:
    """Cleanup helpers."""

    def test_flush_all(self):
        rb.create_job(Job(id="job-1", name="test"))
        rb.create_worker(Worker(id="worker-1"))
        rb.flush_all()
        assert rb.get_job("job-1") is None
        assert rb.get_worker("worker-1") is None
        assert rb.list_jobs() == []
        assert rb.list_workers() == []
