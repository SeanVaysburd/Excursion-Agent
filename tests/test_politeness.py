"""Politeness wrapper: the six rules that keep this agent a good API
citizen, proven against a stubbed transport (tests never touch the
network, the no-fixture-replay rule binds the agent runtime, not unit
tests)."""

from __future__ import annotations

import asyncio

import pytest

from src import config
from src.tools import base
from src.tools.base import DisallowedHostError, RunContext, fetch


class StubResponse:
    def __init__(self, status_code: int, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {"ok": True}

    def json(self):
        return self._payload


class StubClient:
    """Records every attempted GET; scripted status codes per call."""

    is_closed = False

    def __init__(self, statuses):
        self.statuses = list(statuses)
        self.calls: list[str] = []

    async def get(self, url, params=None, headers=None):
        self.calls.append(url)
        status = self.statuses.pop(0) if self.statuses else 200
        return StubResponse(status)


@pytest.fixture(autouse=True)
def fast_politeness(monkeypatch):
    """Zero the pacing so tests run instantly without changing semantics."""
    monkeypatch.setattr(config, "RATE_MIN_INTERVAL_S", {})
    monkeypatch.setattr(config, "BACKOFF_BASE_S", 0.0)


def make_ctx(statuses) -> tuple[RunContext, StubClient]:
    ctx = RunContext(scenario="test")
    stub = StubClient(statuses)
    ctx._client = stub  # transport substitution is the whole point
    return ctx, stub


URL = "https://api.open-meteo.com/v1/forecast"


async def test_identical_requests_fetch_once_under_concurrency():
    ctx, stub = make_ctx([200])
    results = await asyncio.gather(
        *(fetch(ctx, "open-meteo", URL, params={"a": 1}) for _ in range(8))
    )
    assert len(stub.calls) == 1, "single-flight cache must coalesce a stampede"
    assert all(r.status == "ok" for r in results)
    assert ctx.calls["open-meteo"] == 1
    assert ctx.cache_hits["open-meteo"] == 7


async def test_different_params_are_different_cache_keys():
    ctx, stub = make_ctx([200, 200])
    await fetch(ctx, "open-meteo", URL, params={"day": 1})
    await fetch(ctx, "open-meteo", URL, params={"day": 2})
    assert len(stub.calls) == 2


async def test_429_circuit_breaks_source_for_the_run():
    ctx, stub = make_ctx([429])
    first = await fetch(ctx, "ebird", "https://api.ebird.org/v2/x", params={"q": 1})
    assert first.status == "error" and "429" in first.note
    second = await fetch(ctx, "ebird", "https://api.ebird.org/v2/x", params={"q": 2})
    assert second.status == "error" and "circuit open" in second.note
    assert len(stub.calls) == 1, "a broken source must not be called again"


async def test_4xx_is_never_retried():
    ctx, stub = make_ctx([404])
    result = await fetch(ctx, "nws", "https://api.weather.gov/alerts/active")
    assert result.status == "error" and "404" in result.note
    assert len(stub.calls) == 1


async def test_5xx_retries_then_reports():
    ctx, stub = make_ctx([500, 502, 503])
    result = await fetch(ctx, "mta", "https://api-endpoint.mta.info/x")
    assert result.status == "error"
    assert len(stub.calls) == config.RETRY_MAX + 1


async def test_disallowed_host_raises_before_any_connection():
    ctx, stub = make_ctx([200])
    with pytest.raises(DisallowedHostError):
        await fetch(ctx, "evil", "https://attacker.example.com/data")
    assert stub.calls == []


async def test_call_ceiling_flags_never_blocks(monkeypatch):
    monkeypatch.setattr(config, "CALL_CEILING", 2)
    flagged: list[dict] = []
    ctx = RunContext(scenario="test", log=flagged.append)
    ctx._client = StubClient([200, 200, 200])
    for i in range(3):
        result = await fetch(ctx, "open-meteo", URL, params={"i": i})
        assert result.status == "ok", "the ceiling flags; it must never block"
    assert ctx.ceiling_flagged
    assert any("ceiling" in r.get("note", "") for r in flagged)
