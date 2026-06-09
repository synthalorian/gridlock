"""Tests for Gridlock Pydantic models."""

import pytest
from pydantic import ValidationError

from gridlock.models import Capability, Job, JobStatus, Worker, WorkerStatus


class TestCapability:
    """Capability model tests."""

    def test_create_basic(self):
        cap = Capability(name="gpu", value="nvidia-a100")
        assert cap.name == "gpu"
        assert cap.value == "nvidia-a100"
        assert cap.operator == "eq"

    def test_create_with_operator(self):
        cap = Capability(name="memory", value="32", operator="gte")
        assert cap.operator == "gte"

    def test_invalid_operator(self):
        with pytest.raises(ValidationError) as exc_info:
            Capability(name="x", value="y", operator="invalid")
        assert "operator" in str(exc_info.value)

    def test_matches_equal(self):
        worker_cap = Capability(name="gpu", value="nvidia-a100")
        job_req = Capability(name="gpu", value="nvidia-a100", operator="eq")
        assert worker_cap.matches(job_req)

    def test_matches_not_equal(self):
        worker_cap = Capability(name="gpu", value="nvidia-a100")
        job_req = Capability(name="gpu", value="amd-mi300", operator="eq")
        assert not worker_cap.matches(job_req)

    def test_matches_numeric_gte(self):
        worker_cap = Capability(name="memory", value="64")
        job_req = Capability(name="memory", value="32", operator="gte")
        assert worker_cap.matches(job_req)

    def test_matches_numeric_gte_fails(self):
        worker_cap = Capability(name="memory", value="16")
        job_req = Capability(name="memory", value="32", operator="gte")
        assert not worker_cap.matches(job_req)

    def test_matches_numeric_gt(self):
        worker_cap = Capability(name="cores", value="8")
        job_req = Capability(name="cores", value="4", operator="gt")
        assert worker_cap.matches(job_req)

    def test_matches_numeric_lt(self):
        worker_cap = Capability(name="latency", value="10")
        job_req = Capability(name="latency", value="20", operator="lt")
        assert worker_cap.matches(job_req)

    def test_matches_wrong_name(self):
        worker_cap = Capability(name="gpu", value="nvidia-a100")
        job_req = Capability(name="os", value="linux", operator="eq")
        assert not worker_cap.matches(job_req)

    def test_matches_neq(self):
        worker_cap = Capability(name="os", value="windows")
        job_req = Capability(name="os", value="linux", operator="neq")
        assert worker_cap.matches(job_req)

    def test_matches_lte(self):
        worker_cap = Capability(name="temperature", value="30")
        job_req = Capability(name="temperature", value="40", operator="lte")
        assert worker_cap.matches(job_req)


class TestWorker:
    """Worker model tests."""

    def test_create_minimal(self):
        worker = Worker(id="worker-1")
        assert worker.id == "worker-1"
        assert worker.status == WorkerStatus.AVAILABLE
        assert worker.capabilities == []
        assert worker.current_job_id is None

    def test_create_with_capabilities(self):
        caps = [Capability(name="gpu", value="nvidia-a100")]
        worker = Worker(id="worker-1", capabilities=caps)
        assert len(worker.capabilities) == 1
        assert worker.capabilities[0].name == "gpu"

    def test_worker_json_schema(self):
        # Verify model config doesn't break instantiation
        worker = Worker(id="test")
        assert worker.id == "test"


class TestJob:
    """Job model tests."""

    def test_create_minimal(self):
        job = Job(id="job-1", name="test-job")
        assert job.id == "job-1"
        assert job.name == "test-job"
        assert job.status == JobStatus.PENDING
        assert job.priority == 0
        assert job.payload == {}

    def test_create_with_payload(self):
        job = Job(id="job-1", name="test", payload={"epochs": 10})
        assert job.payload["epochs"] == 10

    def test_priority_validation(self):
        with pytest.raises(ValidationError):
            Job(id="job-1", name="test", priority=-1)
        with pytest.raises(ValidationError):
            Job(id="job-1", name="test", priority=101)

    def test_can_run_on_exact_match(self):
        worker = Worker(
            id="w1",
            capabilities=[Capability(name="gpu", value="nvidia-a100")],
        )
        job = Job(
            id="j1",
            name="train",
            required_capabilities=[Capability(name="gpu", value="nvidia-a100")],
        )
        assert job.can_run_on(worker)

    def test_can_run_on_numeric_match(self):
        worker = Worker(
            id="w1",
            capabilities=[Capability(name="memory", value="64")],
        )
        job = Job(
            id="j1",
            name="big-task",
            required_capabilities=[Capability(name="memory", value="32", operator="gte")],
        )
        assert job.can_run_on(worker)

    def test_can_run_on_missing_capability(self):
        worker = Worker(id="w1", capabilities=[])
        job = Job(
            id="j1",
            name="train",
            required_capabilities=[Capability(name="gpu", value="nvidia-a100")],
        )
        assert not job.can_run_on(worker)

    def test_can_run_on_multiple_requirements_all_met(self):
        worker = Worker(
            id="w1",
            capabilities=[
                Capability(name="gpu", value="nvidia-a100"),
                Capability(name="os", value="linux"),
            ],
        )
        job = Job(
            id="j1",
            name="train",
            required_capabilities=[
                Capability(name="gpu", value="nvidia-a100"),
                Capability(name="os", value="linux"),
            ],
        )
        assert job.can_run_on(worker)

    def test_can_run_on_multiple_requirements_one_missing(self):
        worker = Worker(
            id="w1",
            capabilities=[Capability(name="gpu", value="nvidia-a100")],
        )
        job = Job(
            id="j1",
            name="train",
            required_capabilities=[
                Capability(name="gpu", value="nvidia-a100"),
                Capability(name="os", value="linux"),
            ],
        )
        assert not job.can_run_on(worker)

    def test_job_status_enum(self):
        job = Job(id="j1", name="test", status=JobStatus.RUNNING)
        assert job.status == JobStatus.RUNNING
