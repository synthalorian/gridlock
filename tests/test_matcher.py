"""Tests for Gridlock graph-based capability matching engine."""

import pytest

from gridlock.models import Capability, Job, Worker
from gridlock.matcher import (
    CompatibilityGraph,
    MatchResult,
    _capacity_bonus,
    _score_capability_match,
    build_compatibility_graph,
    find_best_matches,
    score_job_worker_match,
)


class TestScoreCapabilityMatch:
    """Unit tests for _score_capability_match."""

    def test_eq_exact_match(self):
        worker_cap = Capability(name="gpu", value="nvidia-a100")
        job_req = Capability(name="gpu", value="nvidia-a100", operator="eq")
        assert _score_capability_match(worker_cap, job_req) == 1.0

    def test_eq_mismatch(self):
        worker_cap = Capability(name="gpu", value="nvidia-a100")
        job_req = Capability(name="gpu", value="amd-mi300", operator="eq")
        assert _score_capability_match(worker_cap, job_req) == 0.0

    def test_neq_match(self):
        worker_cap = Capability(name="os", value="windows")
        job_req = Capability(name="os", value="linux", operator="neq")
        assert _score_capability_match(worker_cap, job_req) == 1.0

    def test_neq_mismatch(self):
        worker_cap = Capability(name="os", value="linux")
        job_req = Capability(name="os", value="linux", operator="neq")
        assert _score_capability_match(worker_cap, job_req) == 0.0

    def test_gt_meets_requirement(self):
        worker_cap = Capability(name="cores", value="8")
        job_req = Capability(name="cores", value="4", operator="gt")
        score = _score_capability_match(worker_cap, job_req)
        assert score > 1.0  # Should get bonus

    def test_gt_exact_fails(self):
        worker_cap = Capability(name="cores", value="4")
        job_req = Capability(name="cores", value="4", operator="gt")
        assert _score_capability_match(worker_cap, job_req) == 0.0

    def test_gt_below_fails(self):
        worker_cap = Capability(name="cores", value="2")
        job_req = Capability(name="cores", value="4", operator="gt")
        assert _score_capability_match(worker_cap, job_req) == 0.0

    def test_gte_exact_match(self):
        worker_cap = Capability(name="memory", value="32")
        job_req = Capability(name="memory", value="32", operator="gte")
        assert _score_capability_match(worker_cap, job_req) == 1.0

    def test_gte_exceeds(self):
        worker_cap = Capability(name="memory", value="64")
        job_req = Capability(name="memory", value="32", operator="gte")
        score = _score_capability_match(worker_cap, job_req)
        assert score > 1.0  # Bonus for extra capacity

    def test_lt_meets_requirement(self):
        worker_cap = Capability(name="latency", value="5")
        job_req = Capability(name="latency", value="10", operator="lt")
        score = _score_capability_match(worker_cap, job_req)
        assert score > 1.0  # Bonus for being well under

    def test_lt_exact_fails(self):
        worker_cap = Capability(name="latency", value="10")
        job_req = Capability(name="latency", value="10", operator="lt")
        assert _score_capability_match(worker_cap, job_req) == 0.0

    def test_lte_exact_match(self):
        worker_cap = Capability(name="latency", value="10")
        job_req = Capability(name="latency", value="10", operator="lte")
        assert _score_capability_match(worker_cap, job_req) == 1.0

    def test_lte_below(self):
        worker_cap = Capability(name="latency", value="5")
        job_req = Capability(name="latency", value="10", operator="lte")
        score = _score_capability_match(worker_cap, job_req)
        assert score > 1.0  # Bonus for being well under

    def test_wrong_name_returns_zero(self):
        worker_cap = Capability(name="gpu", value="nvidia-a100")
        job_req = Capability(name="cpu", value="intel", operator="eq")
        assert _score_capability_match(worker_cap, job_req) == 0.0

    def test_string_comparison_with_numeric_operator(self):
        worker_cap = Capability(name="arch", value="arm64")
        job_req = Capability(name="arch", value="x86_64", operator="gt")
        assert _score_capability_match(worker_cap, job_req) == 0.0


class TestCapacityBonus:
    """Unit tests for _capacity_bonus."""

    def test_exact_match(self):
        assert _capacity_bonus(10.0, 10.0) == 1.0

    def test_double_capacity(self):
        score = _capacity_bonus(20.0, 10.0)
        assert score == 1.5  # 1.0 + 0.5 bonus

    def test_triple_capacity_capped(self):
        score = _capacity_bonus(30.0, 10.0)
        assert score == 1.5  # Bonus capped at 0.5

    def test_slight_excess(self):
        score = _capacity_bonus(11.0, 10.0)
        assert 1.0 < score < 1.1

    def test_zero_requirement(self):
        assert _capacity_bonus(5.0, 0.0) == 1.0


class TestScoreJobWorkerMatch:
    """Integration tests for score_job_worker_match."""

    def test_no_requirements(self):
        job = Job(id="j1", name="simple")
        worker = Worker(id="w1", capabilities=[])
        result = score_job_worker_match(job, worker)
        assert result.score == 1.0
        assert result.worker_id == "w1"

    def test_exact_capability_match(self):
        job = Job(
            id="j1",
            name="train",
            required_capabilities=[Capability(name="gpu", value="nvidia-a100")],
        )
        worker = Worker(
            id="w1",
            capabilities=[Capability(name="gpu", value="nvidia-a100")],
        )
        result = score_job_worker_match(job, worker)
        assert result.score == 1.0
        assert "gpu" in result.matched_capabilities
        assert result.missing_capabilities == []

    def test_numeric_match_with_bonus(self):
        job = Job(
            id="j1",
            name="big-task",
            required_capabilities=[Capability(name="memory", value="32", operator="gte")],
        )
        worker = Worker(
            id="w1",
            capabilities=[Capability(name="memory", value="64")],
        )
        result = score_job_worker_match(job, worker)
        assert result.score > 1.0  # Bonus for extra memory
        assert "memory" in result.matched_capabilities

    def test_missing_capability(self):
        job = Job(
            id="j1",
            name="train",
            required_capabilities=[Capability(name="gpu", value="nvidia-a100")],
        )
        worker = Worker(id="w1", capabilities=[])
        result = score_job_worker_match(job, worker)
        assert result.score == 0.0
        assert "gpu" in result.missing_capabilities
        assert result.matched_capabilities == []

    def test_partial_match_multiple_caps(self):
        job = Job(
            id="j1",
            name="train",
            required_capabilities=[
                Capability(name="gpu", value="nvidia-a100"),
                Capability(name="os", value="linux"),
            ],
        )
        worker = Worker(
            id="w1",
            capabilities=[Capability(name="gpu", value="nvidia-a100")],
        )
        result = score_job_worker_match(job, worker)
        assert result.score == 0.5  # 1 match out of 2
        assert "gpu" in result.matched_capabilities
        assert "os" in result.missing_capabilities

    def test_all_match_multiple_caps(self):
        job = Job(
            id="j1",
            name="train",
            required_capabilities=[
                Capability(name="gpu", value="nvidia-a100"),
                Capability(name="os", value="linux"),
            ],
        )
        worker = Worker(
            id="w1",
            capabilities=[
                Capability(name="gpu", value="nvidia-a100"),
                Capability(name="os", value="linux"),
            ],
        )
        result = score_job_worker_match(job, worker)
        assert result.score == 1.0
        assert "gpu" in result.matched_capabilities
        assert "os" in result.matched_capabilities

    def test_capability_scores_present(self):
        job = Job(
            id="j1",
            name="train",
            required_capabilities=[Capability(name="memory", value="32", operator="gte")],
        )
        worker = Worker(
            id="w1",
            capabilities=[Capability(name="memory", value="64")],
        )
        result = score_job_worker_match(job, worker)
        assert "memory" in result.capability_scores
        assert result.capability_scores["memory"] > 1.0

    def test_score_capping(self):
        """Ensure very high scores are capped."""
        job = Job(
            id="j1",
            name="train",
            required_capabilities=[Capability(name="memory", value="1", operator="gte")],
        )
        worker = Worker(
            id="w1",
            capabilities=[Capability(name="memory", value="999999")],
        )
        result = score_job_worker_match(job, worker)
        assert result.score <= 2.0


class TestFindBestMatches:
    """Tests for find_best_matches ranking function."""

    def test_empty_workers(self):
        job = Job(id="j1", name="test", required_capabilities=[])
        assert find_best_matches(job, []) == []

    def test_single_match(self):
        job = Job(
            id="j1",
            name="train",
            required_capabilities=[Capability(name="gpu", value="nvidia-a100")],
        )
        worker = Worker(
            id="w1",
            capabilities=[Capability(name="gpu", value="nvidia-a100")],
        )
        results = find_best_matches(job, [worker])
        assert len(results) == 1
        assert results[0].worker_id == "w1"
        assert results[0].score == 1.0

    def test_sorted_by_score(self):
        job = Job(
            id="j1",
            name="train",
            required_capabilities=[Capability(name="memory", value="32", operator="gte")],
        )
        workers = [
            Worker(id="w1", capabilities=[Capability(name="memory", value="32")]),
            Worker(id="w2", capabilities=[Capability(name="memory", value="48")]),
            Worker(id="w3", capabilities=[Capability(name="memory", value="64")]),
        ]
        results = find_best_matches(job, workers)
        assert len(results) == 3
        # Should be sorted by score descending
        assert results[0].worker_id == "w3"
        assert results[1].worker_id == "w2"
        assert results[2].worker_id == "w1"
        assert results[0].score > results[1].score > results[2].score

    def test_min_score_filter(self):
        job = Job(
            id="j1",
            name="train",
            required_capabilities=[
                Capability(name="gpu", value="nvidia-a100"),
                Capability(name="os", value="linux"),
            ],
        )
        workers = [
            Worker(id="w1", capabilities=[Capability(name="gpu", value="nvidia-a100")]),
            Worker(id="w2", capabilities=[
                Capability(name="gpu", value="nvidia-a100"),
                Capability(name="os", value="linux"),
            ]),
        ]
        # With min_score=0.6, w1 (score=0.5) should be excluded
        results = find_best_matches(job, workers, min_score=0.6)
        assert len(results) == 1
        assert results[0].worker_id == "w2"

    def test_missing_capability_excluded(self):
        job = Job(
            id="j1",
            name="train",
            required_capabilities=[Capability(name="gpu", value="nvidia-a100")],
        )
        workers = [
            Worker(id="w1", capabilities=[]),
            Worker(id="w2", capabilities=[Capability(name="gpu", value="nvidia-a100")]),
        ]
        results = find_best_matches(job, workers)
        assert len(results) == 1
        assert results[0].worker_id == "w2"

    def test_no_requirements_all_match(self):
        job = Job(id="j1", name="simple")
        workers = [
            Worker(id="w1", capabilities=[Capability(name="gpu", value="a100")]),
            Worker(id="w2", capabilities=[]),
        ]
        results = find_best_matches(job, workers)
        assert len(results) == 2
        # Both should have perfect score since no requirements
        assert all(r.score == 1.0 for r in results)


class TestCompatibilityGraph:
    """Tests for CompatibilityGraph data structure."""

    def test_get_worker_matches(self):
        graph = CompatibilityGraph(
            job_nodes=["j1", "j2"],
            worker_nodes=["w1", "w2"],
            edges=[
                ("j1", "w1", 1.0),
                ("j1", "w2", 0.8),
                ("j2", "w1", 0.5),
            ],
        )
        matches = graph.get_worker_matches("j1")
        assert len(matches) == 2
        assert matches[0] == ("w1", 1.0)
        assert matches[1] == ("w2", 0.8)

    def test_get_worker_matches_sorted_descending(self):
        graph = CompatibilityGraph(
            job_nodes=["j1"],
            worker_nodes=["w1", "w2", "w3"],
            edges=[
                ("j1", "w2", 0.5),
                ("j1", "w1", 1.0),
                ("j1", "w3", 0.8),
            ],
        )
        matches = graph.get_worker_matches("j1")
        scores = [s for _, s in matches]
        assert scores == [1.0, 0.8, 0.5]

    def test_get_job_matches(self):
        graph = CompatibilityGraph(
            job_nodes=["j1", "j2"],
            worker_nodes=["w1"],
            edges=[
                ("j1", "w1", 1.0),
                ("j2", "w1", 0.9),
            ],
        )
        matches = graph.get_job_matches("w1")
        assert len(matches) == 2
        assert matches[0] == ("j1", 1.0)
        assert matches[1] == ("j2", 0.9)

    def test_empty_graph(self):
        graph = CompatibilityGraph()
        assert graph.get_worker_matches("j1") == []
        assert graph.get_job_matches("w1") == []


class TestBuildCompatibilityGraph:
    """Integration tests for build_compatibility_graph."""

    def test_basic_graph(self):
        jobs = [
            Job(
                id="j1",
                name="train",
                required_capabilities=[Capability(name="gpu", value="nvidia-a100")],
            ),
        ]
        workers = [
            Worker(id="w1", capabilities=[Capability(name="gpu", value="nvidia-a100")]),
            Worker(id="w2", capabilities=[]),
        ]
        graph = build_compatibility_graph(jobs, workers)
        assert "j1" in graph.job_nodes
        assert "w1" in graph.worker_nodes
        assert "w2" in graph.worker_nodes
        assert len(graph.edges) == 1
        assert graph.edges[0] == ("j1", "w1", 1.0)

    def test_multiple_jobs_workers(self):
        jobs = [
            Job(
                id="j1",
                name="small",
                required_capabilities=[Capability(name="memory", value="16", operator="gte")],
            ),
            Job(
                id="j2",
                name="large",
                required_capabilities=[Capability(name="memory", value="64", operator="gte")],
            ),
        ]
        workers = [
            Worker(id="w1", capabilities=[Capability(name="memory", value="32")]),
            Worker(id="w2", capabilities=[Capability(name="memory", value="128")]),
        ]
        graph = build_compatibility_graph(jobs, workers)
        # w1 can only run j1, w2 can run both
        assert len(graph.edges) == 3

    def test_empty_inputs(self):
        graph = build_compatibility_graph([], [])
        assert graph.job_nodes == []
        assert graph.worker_nodes == []
        assert graph.edges == []

    def test_no_matches(self):
        jobs = [
            Job(
                id="j1",
                name="train",
                required_capabilities=[Capability(name="gpu", value="nvidia-a100")],
            ),
        ]
        workers = [Worker(id="w1", capabilities=[Capability(name="gpu", value="amd-mi300")])]
        graph = build_compatibility_graph(jobs, workers)
        assert len(graph.edges) == 0


class TestMatchResult:
    """Tests for MatchResult dataclass."""

    def test_creation(self):
        result = MatchResult(
            worker_id="w1",
            score=1.0,
            matched_capabilities=["gpu"],
            missing_capabilities=[],
        )
        assert result.worker_id == "w1"
        assert result.score == 1.0

    def test_score_capping(self):
        result = MatchResult(worker_id="w1", score=5.0)
        assert result.score == 2.0  # Capped

    def test_score_not_capped_below(self):
        result = MatchResult(worker_id="w1", score=1.5)
        assert result.score == 1.5
