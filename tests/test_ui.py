"""Tests for the control plane UI and static file serving."""

import pytest
from fastapi.testclient import TestClient

from gridlock.main import app


@pytest.fixture
def client():
    return TestClient(app)


class TestControlPlaneUI:
    """Test the control plane UI endpoints."""

    def test_root_serves_ui(self, client):
        """The root endpoint should serve the control plane HTML."""
        response = client.get("/")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert "Gridlock Control Plane" in response.text

    def test_root_contains_dashboard_elements(self, client):
        """The UI should contain dashboard elements."""
        response = client.get("/")
        assert response.status_code == 200
        html = response.text
        assert "Dashboard" in html
        assert "Jobs" in html
        assert "Workers" in html
        assert "Create" in html

    def test_static_css_served(self, client):
        """Static CSS files should be served."""
        response = client.get("/static/style.css")
        assert response.status_code == 200
        assert "text/css" in response.headers["content-type"]
        assert "gridlock" in response.text.lower() or "container" in response.text

    def test_static_js_served(self, client):
        """Static JS files should be served."""
        response = client.get("/static/app.js")
        assert response.status_code == 200
        assert "javascript" in response.headers["content-type"]
        assert "gridlock" in response.text.lower() or "apiFetch" in response.text

    def test_static_files_not_found(self, client):
        """Non-existent static files should return 404."""
        response = client.get("/static/nonexistent.css")
        assert response.status_code == 404


class TestDockerComposeHealth:
    """Test that the application works in Docker-compose-like configuration."""

    def test_health_endpoint(self, client):
        """Health endpoint should be accessible for Docker health checks."""
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    def test_api_endpoints_accessible(self, client):
        """Core API endpoints should be accessible."""
        # Create a worker
        worker_response = client.post(
            "/workers",
            json={"id": "docker-test-worker", "capabilities": []},
        )
        assert worker_response.status_code == 201

        # Create a job
        job_response = client.post(
            "/jobs",
            json={"name": "docker-test-job", "priority": 1},
        )
        assert job_response.status_code == 201

        # List jobs
        list_response = client.get("/jobs")
        assert list_response.status_code == 200
        assert len(list_response.json()) >= 1

        # List workers
        workers_response = client.get("/workers")
        assert workers_response.status_code == 200
        assert len(workers_response.json()) >= 1
