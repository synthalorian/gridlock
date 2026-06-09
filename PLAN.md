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
- [ ] Core implementation
- [ ] Tests
- [ ] Documentation update

**Notes:**
- 

---

### Phase 2: Redis queue backend

**Goal:** Implement Redis-backed queue using lists and sorted sets

**Deliverables:**
- [ ] Core implementation
- [ ] Tests
- [ ] Documentation update

**Notes:**
- 

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
- [ ] Core implementation
- [ ] Tests
- [ ] Documentation update

**Notes:**
- 

---

### Phase 6: WebSocket progress streaming

**Goal:** Real-time progress updates via WebSocket

**Deliverables:**
- [ ] Core implementation
- [ ] Tests
- [ ] Documentation update

**Notes:**
- 

---

### Phase 7: Retry logic and dead letter queue

**Goal:** Exponential backoff retry and dead letter queue for failed jobs

**Deliverables:**
- [ ] Core implementation
- [ ] Tests
- [ ] Documentation update

**Notes:**
- 

---

### Phase 8: Control plane UI and Docker compose

**Goal:** FastAPI static UI and Docker compose for full stack deployment

**Deliverables:**
- [ ] Core implementation
- [ ] Tests
- [ ] Documentation update

**Notes:**
- 

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
