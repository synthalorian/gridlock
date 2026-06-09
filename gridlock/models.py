"""Pydantic models for Gridlock distributed task queue."""

from datetime import UTC, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class JobStatus(str, Enum):
    """Job lifecycle states."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class WorkerStatus(str, Enum):
    """Worker availability states."""

    AVAILABLE = "available"
    BUSY = "busy"
    OFFLINE = "offline"


class Capability(BaseModel):
    """A single capability requirement or advertisement.

    Workers advertise capabilities (e.g., gpu=nvidia-a100, os=linux).
    Jobs specify required capabilities as constraints.
    """

    name: str = Field(..., description="Capability name (e.g., 'gpu', 'os', 'arch')")
    value: str = Field(..., description="Capability value (e.g., 'nvidia-a100', 'linux')")
    operator: str = Field(default="eq", description="Comparison operator: eq, neq, gt, gte, lt, lte")

    @field_validator("operator")
    @classmethod
    def _valid_operator(cls, v: str) -> str:
        allowed = {"eq", "neq", "gt", "gte", "lt", "lte"}
        if v not in allowed:
            raise ValueError(f"operator must be one of {allowed}")
        return v

    def matches(self, other: "Capability") -> bool:
        """Check if this capability matches another (typically worker vs job requirement)."""
        if self.name != other.name:
            return False

        # Try numeric comparison first
        try:
            self_val = float(self.value)
            other_val = float(other.value)
            ops = {
                "eq": lambda a, b: a == b,
                "neq": lambda a, b: a != b,
                "gt": lambda a, b: a > b,
                "gte": lambda a, b: a >= b,
                "lt": lambda a, b: a < b,
                "lte": lambda a, b: a <= b,
            }
            return ops[other.operator](self_val, other_val)
        except ValueError:
            # Fallback to string comparison for eq/neq only
            if other.operator == "eq":
                return self.value == other.value
            if other.operator == "neq":
                return self.value != other.value
            return False


class Worker(BaseModel):
    """A worker node that executes jobs."""

    id: str = Field(..., description="Unique worker identifier")
    capabilities: list[Capability] = Field(default_factory=list)
    status: WorkerStatus = Field(default=WorkerStatus.AVAILABLE)
    last_heartbeat: datetime = Field(default_factory=lambda: datetime.now(UTC))
    current_job_id: str | None = Field(default=None)

    model_config = {"json_schema_extra": {"examples": [{"id": "worker-1", "capabilities": [{"name": "gpu", "value": "nvidia-a100", "operator": "eq"}], "status": "available"}]}}


class Job(BaseModel):
    """A unit of work to be dispatched to a matching worker."""

    id: str = Field(..., description="Unique job identifier")
    name: str = Field(..., description="Human-readable job name")
    payload: dict[str, Any] = Field(default_factory=dict, description="Job input data")
    required_capabilities: list[Capability] = Field(default_factory=list)
    priority: int = Field(default=0, ge=0, le=100, description="Higher values = higher priority")
    status: JobStatus = Field(default=JobStatus.PENDING)
    worker_id: str | None = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = Field(default=None)
    completed_at: datetime | None = Field(default=None)
    result: dict[str, Any] | None = Field(default=None)
    error: str | None = Field(default=None)

    model_config = {"json_schema_extra": {"examples": [{"id": "job-1", "name": "train-model", "payload": {"epochs": 10}, "required_capabilities": [{"name": "gpu", "value": "1", "operator": "gte"}], "priority": 50}]}}

    def can_run_on(self, worker: Worker) -> bool:
        """Check if this job can be executed by the given worker."""
        worker_caps = {cap.name: cap for cap in worker.capabilities}
        for req in self.required_capabilities:
            worker_cap = worker_caps.get(req.name)
            if worker_cap is None:
                return False
            if not worker_cap.matches(req):
                return False
        return True
