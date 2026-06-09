"""Tests for Gridlock FastAPI endpoints."""

import pytest
from fastapi.testclient import TestClient

from gridlock.main import app
from gridlock.models import Capability, Worker, WorkerStatus
from gridlock import redis_backend as rb


client = TestClient(app)


class TestHealth:
    """Health endpoint tests."""

    def test_health(self):
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


class TestJobs:
    """Job endpoint tests."""

    def test_create_job_minimal(self):
        response = client.post("/jobs", json={"name": "train-model"})
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "train-model"
        assert data["status"] == "pending"
        assert data["priority"] == 0
        assert data["payload"] == {}

    def test_create_job_with_options(self):
        response = client.post(
            "/jobs",
            json={
                "name": "train-model",
                "payload": {"epochs": 10},
                "required_capabilities": [{"name": "gpu", "value": "nvidia-a100"}],
                "priority": 50,
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["payload"] == {"epochs": 10}
        assert data["priority"] == 50
        assert len(data["required_capabilities"]) == 1
        assert data["required_capabilities"][0]["name"] == "gpu"

    def test_list_jobs(self):
        client.post("/jobs", json={"name": "job-1"})
        client.post("/jobs", json={"name": "job-2"})
        response = client.get("/jobs")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2

    def test_get_job(self):
        create_resp = client.post("/jobs", json={"name": "train-model"})
        job_id = create_resp.json()["id"]
        response = client.get(f"/jobs/{job_id}")
        assert response.status_code == 200
        assert response.json()["name"] == "train-model"

    def test_get_job_not_found(self):
        response = client.get("/jobs/nonexistent")
        assert response.status_code == 404
        assert response.json()["detail"] == "Job not found"


class TestWorkers:
    """Worker endpoint tests."""

    def test_create_worker(self):
        response = client.post("/workers", json={"id": "worker-1"})
        assert response.status_code == 201
        data = response.json()
        assert data["id"] == "worker-1"
        assert data["status"] == "available"

    def test_create_worker_with_capabilities(self):
        response = client.post(
            "/workers",
            json={
                "id": "worker-1",
                "capabilities": [{"name": "gpu", "value": "nvidia-a100"}],
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert len(data["capabilities"]) == 1

    def test_create_worker_duplicate(self):
        client.post("/workers", json={"id": "worker-1"})
        response = client.post("/workers", json={"id": "worker-1"})
        assert response.status_code == 409

    def test_list_workers(self):
        client.post("/workers", json={"id": "worker-1"})
        client.post("/workers", json={"id": "worker-2"})
        response = client.get("/workers")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2

    def test_get_worker(self):
        client.post("/workers", json={"id": "worker-1"})
        response = client.get("/workers/worker-1")
        assert response.status_code == 200
        assert response.json()["id"] == "worker-1"

    def test_get_worker_not_found(self):
        response = client.get("/workers/nonexistent")
        assert response.status_code == 404
        assert response.json()["detail"] == "Worker not found"


class TestHeartbeat:
    """Heartbeat endpoint tests."""

    def test_heartbeat(self):
        client.post("/workers", json={"id": "worker-1"})
        response = client.post("/workers/worker-1/heartbeat")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == "worker-1"
        # last_heartbeat should be updated to near-now
        assert data["last_heartbeat"] is not None

    def test_heartbeat_not_found(self):
        response = client.post("/workers/nonexistent/heartbeat")
        assert response.status_code == 404


class TestWorkerHealth:
    """Worker health check endpoint tests."""

    def test_get_worker_health_healthy(self):
        client.post("/workers", json={"id": "worker-1"})
        client.post("/workers/worker-1/heartbeat")
        response = client.get("/workers/worker-1/health")
        assert response.status_code == 200
        data = response.json()
        assert data["worker_id"] == "worker-1"
        assert data["healthy"] is True
        assert data["status"] == "available"
        assert "last_heartbeat" in data

    def test_get_worker_health_offline(self):
        from datetime import UTC, datetime, timedelta
        old_time = datetime.now(UTC) - timedelta(seconds=60)
        worker = Worker(id="worker-1", status=WorkerStatus.AVAILABLE, last_heartbeat=old_time)
        rb.create_worker(worker)
        response = client.get("/workers/worker-1/health")
        assert response.status_code == 200
        data = response.json()
        assert data["healthy"] is False
        assert data["status"] == "available"

    def test_get_worker_health_not_found(self):
        response = client.get("/workers/nonexistent/health")
        assert response.status_code == 404

    def test_get_all_workers_health(self):
        from datetime import UTC, datetime, timedelta
        old_time = datetime.now(UTC) - timedelta(seconds=60)
        worker1 = Worker(id="worker-1", status=WorkerStatus.AVAILABLE, last_heartbeat=old_time)
        rb.create_worker(worker1)
        client.post("/workers", json={"id": "worker-2"})
        client.post("/workers/worker-2/heartbeat")
        response = client.get("/health/workers")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
        assert data["healthy"] == 1
        assert data["unhealthy"] == 1
        assert len(data["workers"]) == 2

    def test_run_health_check(self):
        from datetime import UTC, datetime, timedelta
        old_time = datetime.now(UTC) - timedelta(seconds=60)
        worker = Worker(id="stale-worker", status=WorkerStatus.AVAILABLE, last_heartbeat=old_time)
        rb.create_worker(worker)
        response = client.post("/health/check")
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 1
        assert "stale-worker" in data["stale_workers_marked_offline"]

    def test_run_health_check_no_stale(self):
        client.post("/workers", json={"id": "worker-1"})
        response = client.post("/health/check")
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 0
        assert data["stale_workers_marked_offline"] == []


class TestMatch:
    """Job-to-worker matching endpoint tests."""

    def test_match_found(self):
        # Create a worker with GPU capability
        client.post(
            "/workers",
            json={
                "id": "worker-gpu",
                "capabilities": [{"name": "gpu", "value": "nvidia-a100"}],
            },
        )
        # Create a job requiring GPU
        create_resp = client.post(
            "/jobs",
            json={
                "name": "train-model",
                "required_capabilities": [{"name": "gpu", "value": "nvidia-a100"}],
            },
        )
        job_id = create_resp.json()["id"]

        response = client.get(f"/match/{job_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["match_count"] == 1
        assert data["matches"][0]["id"] == "worker-gpu"

    def test_match_not_found(self):
        # Create worker without required capability
        client.post("/workers", json={"id": "worker-cpu"})
        create_resp = client.post(
            "/jobs",
            json={
                "name": "train-model",
                "required_capabilities": [{"name": "gpu", "value": "nvidia-a100"}],
            },
        )
        job_id = create_resp.json()["id"]

        response = client.get(f"/match/{job_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["match_count"] == 0

    def test_match_job_not_found(self):
        response = client.get("/match/nonexistent")
        assert response.status_code == 404
