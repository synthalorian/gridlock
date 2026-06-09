"""Tests for Gridlock retry logic and dead letter queue."""

from datetime import UTC, datetime, timedelta

import pytest

from gridlock.models import Capability, Job, JobStatus, Worker, WorkerStatus
from gridlock import redis_backend as rb


class TestRetryLogic:
    """Automatic retry on job failure tests."""

    def test_fail_with_no_retries_marks_failed(self):
        worker = Worker(id="worker-1")
        rb.create_worker(worker)
        job = Job(
            id="job-1",
            name="train",
            status=JobStatus.RUNNING,
            worker_id="worker-1",
            max_retries=0,
        )
        rb.create_job(job)

        result = rb.fail_job("job-1", error="Out of memory")
        assert result is not None
        assert result.status == JobStatus.FAILED
        assert result.error == "Out of memory"
        assert result.retry_count == 0

    def test_fail_with_retries_returns_to_pending(self):
        worker = Worker(id="worker-1")
        rb.create_worker(worker)
        job = Job(
            id="job-1",
            name="train",
            status=JobStatus.RUNNING,
            worker_id="worker-1",
            max_retries=3,
            retry_delay_seconds=1,
        )
        rb.create_job(job)

        result = rb.fail_job("job-1", error="Transient error")
        assert result is not None
        assert result.status == JobStatus.PENDING
        assert result.retry_count == 1
        assert result.error == "Transient error"
        assert result.errors == ["Transient error"]
        assert result.worker_id is None
        assert result.started_at is None
        assert result.next_retry_at is not None

    def test_retry_uses_exponential_backoff(self):
        worker = Worker(id="worker-1")
        rb.create_worker(worker)
        job = Job(
            id="job-1",
            name="train",
            status=JobStatus.RUNNING,
            worker_id="worker-1",
            max_retries=3,
            retry_delay_seconds=2,
        )
        rb.create_job(job)

        before = datetime.now(UTC)
        result = rb.fail_job("job-1", error="err")
        after = datetime.now(UTC)
        expected_delay = timedelta(seconds=2)
        assert before + expected_delay <= result.next_retry_at <= after + expected_delay

        result.next_retry_at = datetime.now(UTC) - timedelta(seconds=1)
        rb.update_job(result)
        rb.dispatch_job("job-1", "worker-1")
        result = rb.fail_job("job-1", error="err2")
        expected_delay = timedelta(seconds=4)
        assert before + expected_delay <= result.next_retry_at <= after + expected_delay + timedelta(seconds=8)

    def test_retry_exhausted_moves_to_dlq(self):
        worker = Worker(id="worker-1")
        rb.create_worker(worker)
        job = Job(
            id="job-1",
            name="train",
            status=JobStatus.RUNNING,
            worker_id="worker-1",
            max_retries=1,
            retry_delay_seconds=1,
        )
        rb.create_job(job)

        first = rb.fail_job("job-1", error="first")
        assert first.status == JobStatus.PENDING

        first.next_retry_at = datetime.now(UTC) - timedelta(seconds=1)
        rb.update_job(first)
        rb.dispatch_job("job-1", "worker-1")
        second = rb.fail_job("job-1", error="second")
        assert second.status == JobStatus.FAILED
        assert second.retry_count == 1
        assert second.errors == ["first", "second"]

        dlq = rb.list_dead_letter_jobs()
        assert any(j.id == "job-1" for j in dlq)

    def test_fail_releases_worker_on_retry(self):
        worker = Worker(id="worker-1", status=WorkerStatus.BUSY, current_job_id="job-1")
        rb.create_worker(worker)
        job = Job(
            id="job-1",
            name="train",
            status=JobStatus.RUNNING,
            worker_id="worker-1",
            max_retries=2,
        )
        rb.create_job(job)

        rb.fail_job("job-1", error="err")
        worker = rb.get_worker("worker-1")
        assert worker.status == WorkerStatus.AVAILABLE
        assert worker.current_job_id is None

    def test_fail_not_running_returns_none(self):
        job = Job(id="job-1", name="train", status=JobStatus.PENDING, max_retries=2)
        rb.create_job(job)
        assert rb.fail_job("job-1") is None


class TestDispatchRetryTiming:
    """Dispatch timing for jobs awaiting retry tests."""

    def test_dispatch_skips_job_before_retry_time(self):
        worker = Worker(id="worker-1")
        rb.create_worker(worker)
        job = Job(
            id="job-1",
            name="train",
            status=JobStatus.PENDING,
            next_retry_at=datetime.now(UTC) + timedelta(seconds=60),
        )
        rb.create_job(job)

        assert rb.dispatch_job("job-1", "worker-1") is None

    def test_dispatch_allows_job_after_retry_time(self):
        worker = Worker(id="worker-1")
        rb.create_worker(worker)
        job = Job(
            id="job-1",
            name="train",
            status=JobStatus.PENDING,
            next_retry_at=datetime.now(UTC) - timedelta(seconds=1),
        )
        rb.create_job(job)

        result = rb.dispatch_job("job-1", "worker-1")
        assert result is not None
        assert result.status == JobStatus.RUNNING

    def test_get_next_dispatchable_job_skips_future_retries(self):
        worker = Worker(id="worker-1", capabilities=[Capability(name="gpu", value="nvidia-a100")])
        rb.create_worker(worker)
        rb.create_job(Job(
            id="job-ready",
            name="ready",
            priority=10,
            required_capabilities=[Capability(name="gpu", value="nvidia-a100")],
        ))
        rb.create_job(Job(
            id="job-waiting",
            name="waiting",
            priority=100,
            status=JobStatus.PENDING,
            next_retry_at=datetime.now(UTC) + timedelta(seconds=60),
            required_capabilities=[Capability(name="gpu", value="nvidia-a100")],
        ))

        result = rb.get_next_dispatchable_job()
        assert result is not None
        assert result.id == "job-ready"


class TestDeadLetterQueue:
    """Dead letter queue tests."""

    def test_list_dead_letter_jobs_empty(self):
        assert rb.list_dead_letter_jobs() == []

    def test_list_dead_letter_jobs_includes_failed_only(self):
        worker = Worker(id="worker-1")
        rb.create_worker(worker)
        rb.create_job(Job(id="job-pending", name="pending", status=JobStatus.PENDING))
        rb.create_job(Job(id="job-completed", name="completed", status=JobStatus.COMPLETED))
        rb.create_job(Job(
            id="job-failed",
            name="failed",
            status=JobStatus.RUNNING,
            worker_id="worker-1",
            max_retries=0,
        ))
        rb.fail_job("job-failed", error="boom")

        dlq = rb.list_dead_letter_jobs()
        assert len(dlq) == 1
        assert dlq[0].id == "job-failed"

    def test_retry_failed_job_moves_to_pending(self):
        worker = Worker(id="worker-1")
        rb.create_worker(worker)
        rb.create_job(Job(
            id="job-failed",
            name="failed",
            status=JobStatus.RUNNING,
            worker_id="worker-1",
            max_retries=0,
        ))
        rb.fail_job("job-failed", error="boom")

        result = rb.retry_failed_job("job-failed")
        assert result is not None
        assert result.status == JobStatus.PENDING
        assert result.retry_count == 0
        assert result.error is None
        assert result.next_retry_at is None

        dlq = rb.list_dead_letter_jobs()
        assert not any(j.id == "job-failed" for j in dlq)

    def test_retry_failed_job_not_failed_returns_none(self):
        rb.create_job(Job(id="job-pending", name="pending", status=JobStatus.PENDING))
        assert rb.retry_failed_job("job-pending") is None

    def test_delete_job_removes_from_dlq(self):
        worker = Worker(id="worker-1")
        rb.create_worker(worker)
        rb.create_job(Job(
            id="job-failed",
            name="failed",
            status=JobStatus.RUNNING,
            worker_id="worker-1",
            max_retries=0,
        ))
        rb.fail_job("job-failed", error="boom")

        rb.delete_job("job-failed")
        dlq = rb.list_dead_letter_jobs()
        assert not any(j.id == "job-failed" for j in dlq)


class TestProcessRetries:
    """Background retry processing tests."""

    def test_process_retries_returns_ready_jobs(self):
        rb.create_job(Job(
            id="job-ready",
            name="ready",
            status=JobStatus.PENDING,
            next_retry_at=datetime.now(UTC) - timedelta(seconds=1),
        ))
        rb.create_job(Job(
            id="job-future",
            name="future",
            status=JobStatus.PENDING,
            next_retry_at=datetime.now(UTC) + timedelta(seconds=60),
        ))

        ready = rb.process_retries()
        assert "job-ready" in ready
        assert "job-future" not in ready

    def test_process_retries_ignores_jobs_without_retry_time(self):
        rb.create_job(Job(id="job-no-retry", name="no-retry", status=JobStatus.PENDING))
        assert rb.process_retries() == []
