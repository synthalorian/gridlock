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

1. Phase 1: FastAPI scaffold + Pydantic models (Job, Worker, Capability)
2. Phase 2: Redis queue backend (lists + sorted sets)
3. Phase 2: Worker registration and heartbeat protocol
4. Phase 3: Capability matching engine (graph-based scoring)
5. Phase 4: Job dispatch and execution lifecycle
6. Phase 5: WebSocket progress streaming
7. Phase 6: Retry logic and dead letter queue
8. Phase 7: Control plane UI (FastAPI static)
9. Phase 8: Docker compose for full stack

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
