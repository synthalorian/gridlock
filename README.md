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
- [ ] Phase 3: Worker registration and heartbeat protocol
- [ ] Phase 4: Capability matching engine (graph-based scoring)
- [ ] Phase 5: Job dispatch and execution lifecycle
- [ ] Phase 6: WebSocket progress streaming
- [ ] Phase 7: Retry logic and dead letter queue
- [ ] Phase 8: Control plane UI (FastAPI static)
- [ ] Phase 9: Docker compose for full stack

### Phase 1 Complete

- **Models**: `Capability` (with operator-based matching: eq, neq, gt, gte, lt, lte), `Worker` (status, heartbeat, capabilities), `Job` (priority, payload, required capabilities)
- **API Endpoints**: `POST /jobs`, `GET /jobs`, `GET /jobs/{id}`, `POST /workers`, `GET /workers`, `GET /workers/{id}`, `POST /workers/{id}/heartbeat`, `GET /match/{job_id}`
- **Tests**: 41 tests covering model validation, capability matching logic, and all API endpoints

### Phase 2 Complete

- **Redis Backend**: `gridlock/redis_backend.py` with full CRUD for jobs and workers
- **Queue Operations**: Sorted sets for priority queues, lists for FIFO queue, sets for status indexing
- **Tests**: 26 new Redis backend tests + updated integration tests = 67 total tests
- **Run**: `uvicorn gridlock.main:app --reload` (requires Redis at `REDIS_URL`)

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
