"""Tests for Gridlock job dispatch and execution lifecycle."""

from datetime import UTC, datetime

import pytest

from gridlock.models import Capability, Job, JobStatus, Worker, WorkerStatus
from gridlock import redis_backend as rb


class TestDispatchJob:
    """Job dispatch to worker tests."""

    def test_dispatch_success(self):
        worker = Worker(
            id="worker-1",
            capabilities=[Capability(name="gpu", value="nvidia-a100")],
        )
        rb.create_worker(worker)
        job = Job(
            id="job-1",
            name="train",
            required_capabilities=[Capability(name="gpu", value="nvidia-a100")],
        )
        rb.create_job(job)

        result = rb.dispatch_job("job-1", "worker-1")
        assert result is not None
        assert result.status == JobStatus.RUNNING
        assert result.worker_id == "worker-1"
        assert result.started_at is not None

        worker = rb.get_worker("worker-1")
        assert worker.status == WorkerStatus.BUSY
        assert worker.current_job_id == "job-1"

    def test_dispatch_job_not_found(self):
        worker = Worker(id="worker-1")
        rb.create_worker(worker)
        assert rb.dispatch_job("nonexistent", "worker-1") is None

    def test_dispatch_worker_not_found(self):
        job = Job(id="job-1", name="train")
        rb.create_job(job)
        assert rb.dispatch_job("job-1", "nonexistent") is None

    def test_dispatch_job_not_pending(self):
        worker = Worker(id="worker-1")
        rb.create_worker(worker)
        job = Job(id="job-1", name="train", status=JobStatus.RUNNING)
        rb.create_job(job)
        assert rb.dispatch_job("job-1", "worker-1") is None

    def test_dispatch_worker_not_available(self):
        worker = Worker(id="worker-1", status=WorkerStatus.BUSY)
        rb.create_worker(worker)
        job = Job(id="job-1", name="train")
        rb.create_job(job)
        assert rb.dispatch_job("job-1", "worker-1") is None

    def test_dispatch_worker_offline(self):
        worker = Worker(id="worker-1", status=WorkerStatus.OFFLINE)
        rb.create_worker(worker)
        job = Job(id="job-1", name="train")
        rb.create_job(job)
        assert rb.dispatch_job("job-1", "worker-1") is None

    def test_dispatch_capability_mismatch(self):
        worker = Worker(
            id="worker-1",
            capabilities=[Capability(name="gpu", value="amd-mi300")],
        )
        rb.create_worker(worker)
        job = Job(
            id="job-1",
            name="train",
            required_capabilities=[Capability(name="gpu", value="nvidia-a100")],
        )
        rb.create_job(job)
        assert rb.dispatch_job("job-1", "worker-1") is None


class TestCompleteJob:
    """Job completion tests."""

    def test_complete_success(self):
        worker = Worker(id="worker-1")
        rb.create_worker(worker)
        job = Job(id="job-1", name="train", status=JobStatus.RUNNING, worker_id="worker-1")
        rb.create_job(job)

        result = rb.complete_job("job-1", result={"accuracy": 0.95})
        assert result is not None
        assert result.status == JobStatus.COMPLETED
        assert result.result == {"accuracy": 0.95}
        assert result.completed_at is not None

        worker = rb.get_worker("worker-1")
        assert worker.status == WorkerStatus.AVAILABLE
        assert worker.current_job_id is None

    def test_complete_no_result(self):
        worker = Worker(id="worker-1")
        rb.create_worker(worker)
        job = Job(id="job-1", name="train", status=JobStatus.RUNNING, worker_id="worker-1")
        rb.create_job(job)

        result = rb.complete_job("job-1")
        assert result is not None
        assert result.result == {}

    def test_complete_job_not_found(self):
        assert rb.complete_job("nonexistent") is None

    def test_complete_job_not_running(self):
        job = Job(id="job-1", name="train", status=JobStatus.PENDING)
        rb.create_job(job)
        assert rb.complete_job("job-1") is None

    def test_complete_releases_worker(self):
        worker = Worker(id="worker-1", status=WorkerStatus.BUSY, current_job_id="job-1")
        rb.create_worker(worker)
        job = Job(id="job-1", name="train", status=JobStatus.RUNNING, worker_id="worker-1")
        rb.create_job(job)

        rb.complete_job("job-1")
        worker = rb.get_worker("worker-1")
        assert worker.status == WorkerStatus.AVAILABLE
        assert worker.current_job_id is None


class TestFailJob:
    """Job failure tests."""

    def test_fail_success(self):
        worker = Worker(id="worker-1")
        rb.create_worker(worker)
        job = Job(id="job-1", name="train", status=JobStatus.RUNNING, worker_id="worker-1")
        rb.create_job(job)

        result = rb.fail_job("job-1", error="Out of memory")
        assert result is not None
        assert result.status == JobStatus.FAILED
        assert result.error == "Out of memory"
        assert result.completed_at is not None

        worker = rb.get_worker("worker-1")
        assert worker.status == WorkerStatus.AVAILABLE
        assert worker.current_job_id is None

    def test_fail_no_error(self):
        worker = Worker(id="worker-1")
        rb.create_worker(worker)
        job = Job(id="job-1", name="train", status=JobStatus.RUNNING, worker_id="worker-1")
        rb.create_job(job)

        result = rb.fail_job("job-1")
        assert result is not None
        assert result.error == "Unknown error"

    def test_fail_job_not_found(self):
        assert rb.fail_job("nonexistent") is None

    def test_fail_job_not_running(self):
        job = Job(id="job-1", name="train", status=JobStatus.PENDING)
        rb.create_job(job)
        assert rb.fail_job("job-1") is None


class TestCancelJob:
    """Job cancellation tests."""

    def test_cancel_pending(self):
        job = Job(id="job-1", name="train", status=JobStatus.PENDING)
        rb.create_job(job)

        result = rb.cancel_job("job-1")
        assert result is not None
        assert result.status == JobStatus.CANCELLED
        assert result.completed_at is not None

    def test_cancel_running_releases_worker(self):
        worker = Worker(id="worker-1", status=WorkerStatus.BUSY, current_job_id="job-1")
        rb.create_worker(worker)
        job = Job(id="job-1", name="train", status=JobStatus.RUNNING, worker_id="worker-1")
        rb.create_job(job)

        result = rb.cancel_job("job-1")
        assert result is not None
        assert result.status == JobStatus.CANCELLED

        worker = rb.get_worker("worker-1")
        assert worker.status == WorkerStatus.AVAILABLE
        assert worker.current_job_id is None

    def test_cancel_job_not_found(self):
        assert rb.cancel_job("nonexistent") is None

    def test_cancel_already_completed(self):
        job = Job(id="job-1", name="train", status=JobStatus.COMPLETED)
        rb.create_job(job)
        assert rb.cancel_job("job-1") is None

    def test_cancel_already_failed(self):
        job = Job(id="job-1", name="train", status=JobStatus.FAILED)
        rb.create_job(job)
        assert rb.cancel_job("job-1") is None

    def test_cancel_already_cancelled(self):
        job = Job(id="job-1", name="train", status=JobStatus.CANCELLED)
        rb.create_job(job)
        assert rb.cancel_job("job-1") is None


class TestGetNextDispatchableJob:
    """Finding next dispatchable job tests."""

    def test_find_dispatchable_job(self):
        worker = Worker(
            id="worker-1",
            capabilities=[Capability(name="gpu", value="nvidia-a100")],
        )
        rb.create_worker(worker)
        job = Job(
            id="job-1",
            name="train",
            required_capabilities=[Capability(name="gpu", value="nvidia-a100")],
        )
        rb.create_job(job)

        result = rb.get_next_dispatchable_job()
        assert result is not None
        assert result.id == "job-1"

    def test_no_pending_jobs(self):
        worker = Worker(id="worker-1")
        rb.create_worker(worker)
        assert rb.get_next_dispatchable_job() is None

    def test_no_matching_workers(self):
        worker = Worker(id="worker-1", capabilities=[])
        rb.create_worker(worker)
        job = Job(
            id="job-1",
            name="train",
            required_capabilities=[Capability(name="gpu", value="nvidia-a100")],
        )
        rb.create_job(job)
        assert rb.get_next_dispatchable_job() is None

    def test_no_available_workers(self):
        worker = Worker(
            id="worker-1",
            status=WorkerStatus.BUSY,
            capabilities=[Capability(name="gpu", value="nvidia-a100")],
        )
        rb.create_worker(worker)
        job = Job(
            id="job-1",
            name="train",
            required_capabilities=[Capability(name="gpu", value="nvidia-a100")],
        )
        rb.create_job(job)
        assert rb.get_next_dispatchable_job() is None

    def test_priority_order(self):
        worker = Worker(
            id="worker-1",
            capabilities=[Capability(name="gpu", value="nvidia-a100")],
        )
        rb.create_worker(worker)
        rb.create_job(Job(
            id="job-low",
            name="low",
            priority=10,
            required_capabilities=[Capability(name="gpu", value="nvidia-a100")],
        ))
        rb.create_job(Job(
            id="job-high",
            name="high",
            priority=50,
            required_capabilities=[Capability(name="gpu", value="nvidia-a100")],
        ))

        result = rb.get_next_dispatchable_job()
        assert result is not None
        assert result.id == "job-high"

    def test_skips_non_pending(self):
        worker = Worker(
            id="worker-1",
            capabilities=[Capability(name="gpu", value="nvidia-a100")],
        )
        rb.create_worker(worker)
        rb.create_job(Job(
            id="job-running",
            name="running",
            status=JobStatus.RUNNING,
            required_capabilities=[Capability(name="gpu", value="nvidia-a100")],
        ))

        assert rb.get_next_dispatchable_job() is None


class TestAutoDispatch:
    """Auto-dispatch tests."""

    def test_auto_dispatch_success(self):
        worker = Worker(
            id="worker-1",
            capabilities=[Capability(name="gpu", value="nvidia-a100")],
        )
        rb.create_worker(worker)
        job = Job(
            id="job-1",
            name="train",
            required_capabilities=[Capability(name="gpu", value="nvidia-a100")],
        )
        rb.create_job(job)

        result = rb.auto_dispatch()
        assert result is not None
        assert result["job_id"] == "job-1"
        assert result["worker_id"] == "worker-1"

        dispatched_job = rb.get_job("job-1")
        assert dispatched_job.status == JobStatus.RUNNING
        assert dispatched_job.worker_id == "worker-1"

    def test_auto_dispatch_no_jobs(self):
        assert rb.auto_dispatch() is None

    def test_auto_dispatch_no_matching_workers(self):
        worker = Worker(id="worker-1", capabilities=[])
        rb.create_worker(worker)
        job = Job(
            id="job-1",
            name="train",
            required_capabilities=[Capability(name="gpu", value="nvidia-a100")],
        )
        rb.create_job(job)
        assert rb.auto_dispatch() is None

    def test_auto_dispatch_picks_best_match(self):
        worker_small = Worker(
            id="worker-small",
            capabilities=[Capability(name="memory", value="32")],
        )
        worker_large = Worker(
            id="worker-large",
            capabilities=[Capability(name="memory", value="128")],
        )
        rb.create_worker(worker_small)
        rb.create_worker(worker_large)
        job = Job(
            id="job-1",
            name="big-task",
            required_capabilities=[Capability(name="memory", value="32", operator="gte")],
        )
        rb.create_job(job)

        result = rb.auto_dispatch()
        assert result is not None
        assert result["worker_id"] == "worker-large"

    def test_auto_dispatch_priority_order(self):
        worker = Worker(
            id="worker-1",
            capabilities=[Capability(name="gpu", value="nvidia-a100")],
        )
        rb.create_worker(worker)
        rb.create_job(Job(
            id="job-low",
            name="low",
            priority=10,
            required_capabilities=[Capability(name="gpu", value="nvidia-a100")],
        ))
        rb.create_job(Job(
            id="job-high",
            name="high",
            priority=50,
            required_capabilities=[Capability(name="gpu", value="nvidia-a100")],
        ))

        result = rb.auto_dispatch()
        assert result is not None
        assert result["job_id"] == "job-high"

    def test_auto_dispatch_no_available_workers(self):
        worker = Worker(
            id="worker-1",
            status=WorkerStatus.BUSY,
            capabilities=[Capability(name="gpu", value="nvidia-a100")],
        )
        rb.create_worker(worker)
        job = Job(
            id="job-1",
            name="train",
            required_capabilities=[Capability(name="gpu", value="nvidia-a100")],
        )
        rb.create_job(job)
        assert rb.auto_dispatch() is None


class TestReleaseWorker:
    """Worker release tests."""

    def test_release_busy_worker(self):
        worker = Worker(id="worker-1", status=WorkerStatus.BUSY, current_job_id="job-1")
        rb.create_worker(worker)

        result = rb._release_worker("worker-1")
        assert result is not None
        assert result.status == WorkerStatus.AVAILABLE
        assert result.current_job_id is None

    def test_release_worker_not_found(self):
        assert rb._release_worker("nonexistent") is None
