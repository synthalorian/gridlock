# gridlock

> Distributed task queue with capability matching. Workers announce what they can do and the scheduler matches jobs like a dating app.

**Language:** Python  
**Constraint:** Automate the annoying thing  
**Stack:** FastAPI, redis, websockets, pydantic

---

## Features

- Workers advertise capabilities (GPU, ARM, OS, toolchain)
- Scheduler matches jobs to workers via capability graph
- Redis-backed queue with priority support
- WebSocket progress streaming
- FastAPI control plane with OpenAPI docs
- Job retry with exponential backoff
- Dead letter queue for failed jobs

---

## Development Plan

- [x] Phase 1: FastAPI scaffold + Pydantic models (Job, Worker, Capability)
- [x] Phase 2: Redis queue backend (lists + sorted sets)
- [x] Phase 3: Worker registration and heartbeat protocol
- [x] Phase 4: Capability matching engine (graph-based scoring)
- [x] Phase 5: Job dispatch and execution lifecycle
- [x] Phase 6: WebSocket progress streaming
- [x] Phase 7: Retry logic and dead letter queue
- [ ] Phase 8: Control plane UI (FastAPI static)
- [ ] Phase 9: Docker compose for full stack

### Phase 1 Complete

- **Models**: `Capability` (with operator-based matching: eq, neq, gt, gte, lt, lte), `Worker` (status, heartbeat, capabilities), `Job` (priority, payload, required capabilities)
- **API Endpoints**: `POST /jobs`, `GET /jobs`, `GET /jobs/{id}`, `POST /workers`, `GET /workers`, `GET /workers/{id}`, `POST /workers/{id}/heartbeat`, `GET /workers/{id}/health`, `GET /health/workers`, `POST /health/check`, `GET /match/{job_id}`
- **Tests**: 41 tests covering model validation, capability matching logic, and all API endpoints

### Phase 2 Complete

- **Redis Backend**: `gridlock/redis_backend.py` with full CRUD for jobs and workers
- **Queue Operations**: Sorted sets for priority queues, lists for FIFO queue, sets for status indexing
- **Tests**: 26 new Redis backend tests + updated integration tests = 67 total tests
- **Run**: `uvicorn gridlock.main:app --reload` (requires Redis at `REDIS_URL`)

### Phase 3 Complete

- **Heartbeat Health Checks**: Background task monitors worker heartbeats and automatically marks stale workers as `offline`
- **Health Endpoints**: `GET /workers/{id}/health` (per-worker health), `GET /health/workers` (all workers summary), `POST /health/check` (manual stale worker check)
- **Configuration**: `GRIDLOCK_HEARTBEAT_TIMEOUT` (default 30s, time before worker considered stale), `GRIDLOCK_HEARTBEAT_INTERVAL` (default 10s, monitor check frequency)
- **Redis Backend**: Added `get_stale_workers()`, `mark_worker_offline()`, `check_and_mark_stale_workers()` for health management
- **Tests**: 17 new health check tests covering stale detection, offline marking, and API endpoints
- **Run**: Same command, monitor starts automatically with the app

### Phase 4 Complete

- **Capability Matching Engine**: Graph-based scoring with `matcher.py` for job-to-worker compatibility
- **Match Scoring**: Per-capability scoring with capacity bonuses (exceeding requirements gives higher scores)
- **Ranked Matches**: `GET /match/{job_id}/ranked` returns workers sorted by match quality
- **Compatibility Graph**: `GET /graph/compatibility` returns full bipartite graph for visualization
- **Tests**: 29 matcher tests covering scoring algorithms, capacity bonuses, and graph construction

### Phase 5 Complete

- **Job Dispatch**: `POST /jobs/{job_id}/dispatch` assigns a pending job to an available worker (auto-match or specify worker_id)
- **Auto-Dispatch**: `POST /dispatch/auto` automatically dispatches the highest priority job to the best matching worker
- **Job Completion**: `POST /jobs/{job_id}/complete` marks a running job as completed with optional result payload
- **Job Failure**: `POST /jobs/{job_id}/fail` marks a running job as failed with error message
- **Job Cancellation**: `POST /jobs/{job_id}/cancel` cancels a pending or running job
- **Worker Release**: Completing, failing, or cancelling a running job automatically releases the worker back to available status
- **Redis Backend**: Added `dispatch_job()`, `complete_job()`, `fail_job()`, `cancel_job()`, `auto_dispatch()`, `get_next_dispatchable_job()`
- **Tests**: 50 new dispatch and lifecycle tests covering success paths, error conditions, and full lifecycles
- **Total Tests**: 193 tests passing

### Phase 6 Complete

- **Progress Updates**: `POST /jobs/{job_id}/progress` updates a job's progress percentage (0-100) with optional status message and metadata
- **WebSocket Streaming**: `WS /ws/jobs/{job_id}/progress` streams real-time progress updates to connected clients
- **In-Memory Broadcasting**: WebSocket connections are managed in-memory for reliable real-time delivery; Redis pub/sub also available for cross-server setups
- **Ping/Pong**: WebSocket connections support `ping` messages for keepalive
- **Tests**: 6 new progress streaming tests covering REST updates, WebSocket streaming, invalid ranges, and not-found handling
- **Total Tests**: 199 tests passing

### Phase 7 Complete

- **Retry Fields**: `Job` model now includes `retry_count`, `max_retries`, `retry_delay_seconds`, `next_retry_at`, and `errors`
- **Automatic Retry**: `POST /jobs/{job_id}/fail` automatically retries failed jobs up to `max_retries` with exponential backoff (`delay * 2^(retry_count - 1)`)
- **Dead Letter Queue**: Jobs that exhaust retries are added to the DLQ and can be inspected via `GET /jobs/dead-letter`
- **Manual Retry**: `POST /jobs/{job_id}/retry` moves a failed DLQ job back to pending with reset retry state
- **Retry Timing**: Dispatch and auto-dispatch respect `next_retry_at` so jobs are not redispatched before their backoff expires
- **Tests**: 16 new retry/DLQ tests covering backoff, DLQ membership, retry endpoint, and dispatch timing
- **Total Tests**: 215 tests passing

---

## Getting Started

### Prerequisites

- Python 3.11+
- Redis

### Build

```bash
cd gridlock
pip install -e ".[dev]"
```

### Run

```bash
uvicorn gridlock.main:app --reload
```

---

## Architecture

See `PLAN.md` for detailed architecture decisions and implementation notes.

---

## License

MIT
