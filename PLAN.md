# gridlock -- Implementation Plan

## Project Overview

Distributed task queue with capability matching. Workers announce what they can do and the scheduler matches jobs like a dating app.

**Language:** Python  
**Constraint:** Automate the annoying thing  
**Stack:** FastAPI, redis, websockets, pydantic

---

## Phase Breakdown

### Phase 1: FastAPI scaffold + Pydantic models

**Goal:** Set up FastAPI app with Pydantic models for Job, Worker, Capability

**Deliverables:**
- [x] Core implementation (`gridlock/models.py`, `gridlock/main.py`)
- [x] Tests (`tests/test_models.py`, `tests/test_main.py` - 41 tests passing)
- [x] Documentation update (README.md)

**Notes:**
- Capability model supports operators: eq, neq, gt, gte, lt, lte with numeric and string comparison
- In-memory stores used for Phase 1 (to be replaced with Redis in Phase 2)
- API endpoints: /jobs, /workers, /match/{job_id}, /workers/{id}/heartbeat

---

### Phase 2: Redis queue backend

**Goal:** Implement Redis-backed queue using lists and sorted sets

**Deliverables:**
- [x] Core implementation (`gridlock/redis_backend.py`)
- [x] Tests (`tests/test_redis.py` - 26 tests, `tests/test_main.py` updated)
- [x] Documentation update

**Notes:**
- Redis data structures: sorted sets for priority queues (score = -priority), strings (JSON) for job/worker storage, sets for indexing
- FIFO queue implemented via Redis lists (`lpush`/`rpop`)
- `fakeredis` used for test isolation (session-scoped fixture for performance)
- All existing 41 Phase 1 tests still pass, plus 26 new Redis backend tests

---

### Phase 3: Worker registration and heartbeat

**Goal:** Worker registration protocol with heartbeat health checks

**Deliverables:**
- [ ] Core implementation
- [ ] Tests
- [ ] Documentation update

**Notes:**
- 

---

### Phase 4: Capability matching engine

**Goal:** Graph-based capability scoring and job-to-worker matching

**Deliverables:**
- [ ] Core implementation
- [ ] Tests
- [ ] Documentation update

**Notes:**
- 

---

### Phase 5: Job dispatch and execution

**Goal:** Full job lifecycle: dispatch, execute, complete/fail

**Deliverables:**
- [x] Core implementation (`gridlock/redis_backend.py` dispatch/complete/fail/cancel/auto_dispatch)
- [x] API endpoints (`gridlock/main.py` - 5 new endpoints)
- [x] Tests (`tests/test_dispatch.py` - 37 tests, `tests/test_main.py` - 13 new lifecycle tests)
- [x] Documentation update (README.md)

**Notes:**
- Dispatch validates job is pending, worker is available, and capabilities match
- Auto-dispatch uses ranked matching to pick the best worker for highest priority job
- Complete/fail/cancel all release the worker back to available status
- 193 total tests passing 

---

### Phase 6: WebSocket progress streaming

**Goal:** Real-time progress updates via WebSocket

**Deliverables:**
- [x] Core implementation (`gridlock/models.py` ProgressUpdate model + progress field, `gridlock/redis_backend.py` update/publish/subscribe, `gridlock/main.py` REST + WS endpoints)
- [x] Tests (`tests/test_main.py` - 6 new progress streaming tests)
- [x] Documentation update (README.md)

**Notes:**
- In-memory WebSocket connection manager for reliable real-time broadcasting within a single server
- Redis pub/sub available for cross-server progress broadcasting
- WebSocket endpoint supports ping/pong keepalive

---

### Phase 7: Retry logic and dead letter queue

**Goal:** Exponential backoff retry and dead letter queue for failed jobs

**Deliverables:**
- [x] Core implementation (`gridlock/models.py` retry fields, `gridlock/redis_backend.py` retry/DLQ logic, `gridlock/main.py` DLQ endpoints)
- [x] Tests (`tests/test_retry.py` - 16 tests)
- [x] Documentation update (README.md)

**Notes:**
- Job model extended with `retry_count`, `max_retries`, `retry_delay_seconds`, `next_retry_at`, and `errors`
- `fail_job` automatically retries up to `max_retries` using exponential backoff (`delay * 2^(retry_count-1)`), then moves the job to the dead letter queue
- `dispatch_job` and `get_next_dispatchable_job` respect `next_retry_at` so retried jobs are not dispatched before their backoff expires
- New API endpoints: `GET /jobs/dead-letter`, `POST /jobs/{job_id}/retry`
- `max_retries` defaults to `0` so existing behavior is preserved unless opted-in 

---

### Phase 8: Control plane UI and Docker compose

**Goal:** FastAPI static UI and Docker compose for full stack deployment

**Deliverables:**
- [x] Core implementation (`gridlock/static/` HTML/CSS/JS dashboard, `gridlock/main.py` static file serving)
- [x] Docker setup (`Dockerfile`, `docker-compose.yml`)
- [x] Tests (`tests/test_ui.py` - 6 tests)
- [x] Documentation update (README.md)

**Notes:**
- Control plane UI served at `GET /` with tabs for Dashboard, Jobs, Workers, and Create
- Dashboard auto-refreshes every 5 seconds via polling
- Docker compose includes Redis with health checks and persistent volume 

---

## Architecture Notes

### Key Decisions

- 

### Data Flow

```
[Job Request] -> [Capability Matcher] -> [Redis Queue] -> [Worker]
                                    -> [WebSocket] -> [Client]
```

### Error Handling Strategy

- 

---

## Testing Strategy

- Unit tests for core functions
- Integration tests for full pipeline
- Benchmarks for performance-critical paths

---

## Open Questions

1. 
2. 

---

*Generated for opencode sprint. Implement phase by phase. DO NOT RESEARCH. Build directly.*
