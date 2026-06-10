# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2025-06-10

### Added

- **Phase 1 — Core Models & API**: `Capability` (operator-based matching: eq, neq, gt, gte, lt, lte), `Worker` (status, heartbeat, capabilities), `Job` (priority, payload, required capabilities). REST endpoints for job and worker CRUD, heartbeat, and health checks.
- **Phase 2 — Redis Backend**: Full CRUD for jobs and workers via `gridlock/redis_backend.py`. Sorted sets for priority queues, lists for FIFO, sets for status indexing.
- **Phase 3 — Health Monitoring**: Background heartbeat monitor automatically marks stale workers as `offline`. Configurable `GRIDLOCK_HEARTBEAT_TIMEOUT` and `GRIDLOCK_HEARTBEAT_INTERVAL`.
- **Phase 4 — Capability Matching**: Graph-based scoring engine (`matcher.py`) with per-capacity bonuses. Ranked match endpoint and compatibility graph visualization.
- **Phase 5 — Job Dispatch & Lifecycle**: Manual and auto-dispatch, job completion, failure, cancellation, and automatic worker release.
- **Phase 6 — WebSocket Progress**: Real-time progress streaming via `WS /ws/jobs/{job_id}/progress` with in-memory broadcasting.
- **Phase 7 — Retry & Dead Letter Queue**: Exponential backoff retries, DLQ for exhausted jobs, and manual retry endpoint.
- **Phase 8 — Control Plane UI**: Static HTML dashboard served at `/` with live job/worker monitoring, filtering, and action buttons.
- **Phase 9 — Docker Compose**: Multi-stage `Dockerfile` and `docker-compose.yml` with Redis service, health checks, and persistent volumes.

### Changed

- Bumped version to 1.0.0 for stable release.

[1.0.0]: https://github.com/synth/gridlock/releases/tag/v1.0.0
