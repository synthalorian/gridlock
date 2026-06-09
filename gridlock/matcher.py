"""Graph-based capability matching engine for Gridlock.

Builds a bipartite compatibility graph between jobs and workers,
with edge weights representing match quality scores.
"""

from dataclasses import dataclass, field

from gridlock.models import Capability, Job, Worker


@dataclass
class MatchResult:
    """Result of matching a job to a worker."""

    worker_id: str
    score: float
    matched_capabilities: list[str] = field(default_factory=list)
    missing_capabilities: list[str] = field(default_factory=list)
    capability_scores: dict[str, float] = field(default_factory=dict, repr=False)

    def __post_init__(self):
        """Ensure score is between 0.0 and 1.0 (or slightly above with bonuses)."""
        # Cap score at 2.0 to avoid runaway bonuses
        if self.score > 2.0:
            self.score = 2.0


def _score_capability_match(worker_cap: Capability, job_req: Capability) -> float:
    """Score how well a worker capability matches a job requirement.

    Returns a float from 0.0 to ~1.5:
    - 0.0 = does not match
    - 1.0 = exact/minimum match
    - >1.0 = worker exceeds requirements (bonus for extra capacity)
    """
    if worker_cap.name != job_req.name:
        return 0.0

    # Try numeric comparison
    try:
        worker_val = float(worker_cap.value)
        req_val = float(job_req.value)
    except ValueError:
        # String comparison
        if job_req.operator == "eq":
            return 1.0 if worker_cap.value == job_req.value else 0.0
        if job_req.operator == "neq":
            return 1.0 if worker_cap.value != job_req.value else 0.0
        # gt/gte/lt/lte don't make sense for strings
        return 0.0

    # Numeric comparison with capacity bonus
    ops = {
        "eq": lambda w, r: 1.0 if w == r else 0.0,
        "neq": lambda w, r: 1.0 if w != r else 0.0,
        "gt": lambda w, r: _capacity_bonus(w, r) if w > r else 0.0,
        "gte": lambda w, r: _capacity_bonus(w, r) if w >= r else 0.0,
        "lt": lambda w, r: _capacity_bonus(r, w) if w < r else 0.0,
        "lte": lambda w, r: _capacity_bonus(r, w) if w <= r else 0.0,
    }

    return ops[job_req.operator](worker_val, req_val)


def _capacity_bonus(worker_val: float, req_val: float) -> float:
    """Calculate a bonus score for exceeding requirements.

    Base score is 1.0 for meeting the requirement.
    Bonus up to 0.5 for significantly exceeding it (2x or more).
    """
    if req_val == 0:
        return 1.0
    ratio = worker_val / req_val
    # Base 1.0 + bonus capped at 0.5
    bonus = min((ratio - 1.0) * 0.5, 0.5)
    return 1.0 + max(bonus, 0.0)


def score_job_worker_match(job: Job, worker: Worker) -> MatchResult:
    """Score how well a worker matches a job's requirements.

    Returns a MatchResult with:
    - score: average of individual capability scores (0.0 to ~1.5)
    - matched_capabilities: list of cap names that matched
    - missing_capabilities: list of cap names the worker lacks
    - capability_scores: per-capability breakdown
    """
    if not job.required_capabilities:
        # No requirements = perfect match
        return MatchResult(
            worker_id=worker.id,
            score=1.0,
            matched_capabilities=[],
            missing_capabilities=[],
        )

    worker_caps = {cap.name: cap for cap in worker.capabilities}
    scores: dict[str, float] = {}
    matched: list[str] = []
    missing: list[str] = []

    for req in job.required_capabilities:
        worker_cap = worker_caps.get(req.name)
        if worker_cap is None:
            scores[req.name] = 0.0
            missing.append(req.name)
            continue

        score = _score_capability_match(worker_cap, req)
        scores[req.name] = score
        if score > 0.0:
            matched.append(req.name)
        else:
            missing.append(req.name)

    # Average score across all required capabilities
    avg_score = sum(scores.values()) / len(job.required_capabilities) if scores else 1.0

    return MatchResult(
        worker_id=worker.id,
        score=avg_score,
        matched_capabilities=matched,
        missing_capabilities=missing,
        capability_scores=scores,
    )


def find_best_matches(job: Job, workers: list[Worker], min_score: float = 0.0) -> list[MatchResult]:
    """Find and rank all workers that can run a job.

    Workers are returned sorted by match score (highest first).
    Only workers with score >= min_score are included.
    """
    results: list[MatchResult] = []
    for worker in workers:
        result = score_job_worker_match(job, worker)
        if result.score >= min_score and not result.missing_capabilities:
            results.append(result)

    # Sort by score descending
    results.sort(key=lambda r: r.score, reverse=True)
    return results


@dataclass
class CompatibilityGraph:
    """Bipartite graph representing job-worker compatibility.

    Nodes are partitioned into jobs and workers.
    Edges have weights representing match quality.
    """

    job_nodes: list[str] = field(default_factory=list)
    worker_nodes: list[str] = field(default_factory=list)
    edges: list[tuple[str, str, float]] = field(default_factory=list)
    # (job_id, worker_id, score)

    def get_worker_matches(self, job_id: str) -> list[tuple[str, float]]:
        """Get all workers that match a given job, sorted by score."""
        matches = [(w, s) for j, w, s in self.edges if j == job_id]
        matches.sort(key=lambda x: x[1], reverse=True)
        return matches

    def get_job_matches(self, worker_id: str) -> list[tuple[str, float]]:
        """Get all jobs that match a given worker, sorted by score."""
        matches = [(j, s) for j, w, s in self.edges if w == worker_id]
        matches.sort(key=lambda x: x[1], reverse=True)
        return matches


def build_compatibility_graph(jobs: list[Job], workers: list[Worker]) -> CompatibilityGraph:
    """Build a full bipartite compatibility graph for all job-worker pairs.

    This is useful for batch scheduling and visualization.
    """
    graph = CompatibilityGraph(
        job_nodes=[j.id for j in jobs],
        worker_nodes=[w.id for w in workers],
    )

    for job in jobs:
        for worker in workers:
            result = score_job_worker_match(job, worker)
            if result.score > 0.0 and not result.missing_capabilities:
                graph.edges.append((job.id, worker.id, result.score))

    return graph
