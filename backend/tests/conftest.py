"""Test fixtures — each test gets a fresh engine bound to its own event loop."""

import pytest
from app.db.session import dispose_engine


@pytest.fixture(autouse=True)
async def _fresh_engine_per_test():
    yield
    await dispose_engine()
