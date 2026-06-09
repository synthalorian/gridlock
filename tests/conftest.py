"""Shared test fixtures for Gridlock."""

import pytest
import fakeredis

from gridlock import redis_backend as rb


@pytest.fixture(scope="session", autouse=True)
def fake_redis_session():
    """Patch the Redis backend to use an in-memory fake Redis for all tests."""
    fake = fakeredis.FakeRedis(decode_responses=True)
    original_client = rb._redis_client
    rb._redis_client = fake
    # Warm up fakeredis to avoid the first-operation penalty
    fake.set("__warmup__", "1")
    fake.delete("__warmup__")
    yield fake
    rb._redis_client = original_client


@pytest.fixture(autouse=True)
def clear_redis(fake_redis_session):
    """Clear all Gridlock data from fake Redis before each test."""
    rb.flush_all()
    yield
