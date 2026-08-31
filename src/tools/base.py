"""
The uniform tool contract and the ONE place API politeness is enforced.

Every external data source goes through `fetch()` on a `RunContext`. That
single chokepoint is what makes the politeness rules real instead of
aspirational:

  1. per-source minimum intervals (config.RATE_MIN_INTERVAL_S)
  2. in-run caching: identical (source, url, params) fetched once,
     single-flight so concurrent agents can't stampede a cache miss
  3. retries: max 2, exponential backoff, network/5xx only, NEVER 4xx;
     a 429 circuit-breaks the source for the rest of the run
  4. batching is a caller-side design rule (one weather call per run, one
     bird call per region), the cache makes accidental duplicates free,
     the counters make them visible
  5. custom User-Agent on every request
  6. call accounting: per-source counters land in the run summary, and a
     config ceiling flags runaway designs instead of raising limits

The hostname allowlist is the security boundary: a URL outside
config.ALLOWED_HOSTS raises before any connection is attempted, so a bug
(or a prompt-injected URL) cannot turn this agent into a generic HTTP
client.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any, Callable, Literal
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel

from src import config


class ToolResult(BaseModel):
    """Uniform envelope every tool returns (frozen spec contract)."""

    source: str
    fetched_at: datetime
    status: Literal["ok", "empty", "error"]
    data: Any = None
    note: str = ""


class DisallowedHostError(RuntimeError):
    """A request tried to leave the documented API allowlist."""


class EvidenceRegistry:
    """Every record fetched this run, addressable by a stable evidence id.

    Groundedness is a set-membership question, so the registry is the whole
    mechanism: an id that isn't here refers to nothing that was fetched, and
    the candidate citing it loses that citation.
    """

    def __init__(self) -> None:
        self._records: dict[str, Any] = {}

    def register(self, evidence_id: str, record: Any) -> str:
        self._records[evidence_id] = record
        return evidence_id

    def has(self, evidence_id: str) -> bool:
        return evidence_id in self._records

    def get(self, evidence_id: str) -> Any:
        return self._records.get(evidence_id)

    @property
    def ids(self) -> set[str]:
        return set(self._records)

    def __len__(self) -> int:
        return len(self._records)


class RunContext:
    """Everything scoped to one run: politeness state, evidence, counters.

    Never module-level, a long-lived API process must get a fresh context
    per run or it would serve stale cache, keep counters forever, and hold
    circuit breakers open across unrelated runs. `demo.py --scenario all`
    passes one context through every scenario on purpose (the external-call
    cache is invocation-scoped); each scenario snapshots its own counter
    deltas for its run summary.
    """

    def __init__(self, scenario: str = "adhoc", log: Callable[[dict], None] | None = None):
        self.run_id = datetime.now(config.TZ).strftime("%Y%m%dT%H%M%S") + uuid.uuid4().hex[:4]
        self.scenario = scenario
        self.registry = EvidenceRegistry()
        self.calls: Counter[str] = Counter()  # actual HTTP attempts per source
        self.cache_hits: Counter[str] = Counter()
        self.llm_calls: Counter[str] = Counter()  # keyed "agent"/"critic" etc.
        self.broken: set[str] = set()  # sources circuit-broken by a 429
        self.ceiling_flagged = False
        # log is injected by the trajectory logger (P4); default no-op keeps
        # the tools layer usable standalone and in unit tests.
        self.log: Callable[[dict], None] = log or (lambda record: None)

        self._cache: dict[str, asyncio.Task] = {}
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._last_call: dict[str, float] = {}
        self._client: httpx.AsyncClient | None = None

    # -- lifecycle ---------------------------------------------------------
    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                headers={"User-Agent": config.USER_AGENT},
                timeout=httpx.Timeout(20.0, connect=10.0),
                follow_redirects=True,
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()

    # -- accounting --------------------------------------------------------
    def total_external_calls(self) -> int:
        return sum(self.calls.values())

    def check_ceiling(self) -> None:
        if not self.ceiling_flagged and self.total_external_calls() > config.CALL_CEILING:
            self.ceiling_flagged = True
            self.log(
                {
                    "type": "step",
                    "stage": "politeness",
                    "tool": "call_ceiling",
                    "status": "error",
                    "note": (
                        f"external call count {self.total_external_calls()} exceeded "
                        f"the {config.CALL_CEILING} ceiling, design bug, not a "
                        f"reason to raise limits"
                    ),
                }
            )


def _canonical_key(source: str, url: str, params: dict | None) -> str:
    return f"{source}|{url}|{json.dumps(params or {}, sort_keys=True, default=str)}"


def _assert_allowed(url: str) -> None:
    host = urlparse(url).hostname or ""
    if host not in config.ALLOWED_HOSTS:
        raise DisallowedHostError(
            f"host {host!r} is not on the documented API allowlist, refusing"
        )


async def fetch(
    ctx: RunContext,
    source: str,
    url: str,
    params: dict | None = None,
    headers: dict | None = None,
) -> ToolResult:
    """Politeness-enforced GET. Identical requests within a run coalesce."""
    _assert_allowed(url)

    key = _canonical_key(source, url, params)
    if key in ctx._cache:
        ctx.cache_hits[source] += 1
        return await asyncio.shield(ctx._cache[key])

    # Single-flight: publish the task before awaiting it so a concurrent
    # caller finds it in the cache instead of fetching again.
    task = asyncio.ensure_future(_fetch_once(ctx, source, url, params, headers))
    ctx._cache[key] = task
    return await asyncio.shield(task)


async def _fetch_once(
    ctx: RunContext,
    source: str,
    url: str,
    params: dict | None,
    headers: dict | None,
) -> ToolResult:
    now = datetime.now(config.TZ)

    if source in ctx.broken:
        return ToolResult(
            source=source,
            fetched_at=now,
            status="error",
            note="circuit open: source returned 429 earlier this run; using fallback",
        )

    attempts = config.RETRY_MAX + 1
    last_note = ""
    for attempt in range(attempts):
        # Pace under the per-source lock so N concurrent waiters can't all
        # compute the same sleep and fire together.
        async with ctx._locks[source]:
            min_interval = config.RATE_MIN_INTERVAL_S.get(source, 1.0)
            wait = ctx._last_call.get(source, 0.0) + min_interval - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            ctx._last_call[source] = time.monotonic()
            ctx.calls[source] += 1
            ctx.check_ceiling()
            try:
                response = await ctx.client.get(url, params=params, headers=headers)
            except httpx.HTTPError as exc:
                last_note = f"network error: {type(exc).__name__}"
                response = None

        if response is not None:
            if response.status_code == 200:
                try:
                    payload = response.json()
                except ValueError:
                    # Seen live from Open-Meteo: an error string streamed
                    # with a 200 ("timeoutReached"). A transient balancer
                    # glitch, so it earns the same bounded retry as a 5xx;
                    # the body snippet lands in the note for diagnosis.
                    last_note = f"200 but non-JSON body: {response.text[:60]!r}"
                else:
                    return ToolResult(
                        source=source, fetched_at=now, status="ok", data=payload
                    )
            if response.status_code == 429:
                ctx.broken.add(source)
                return ToolResult(
                    source=source,
                    fetched_at=now,
                    status="error",
                    note="HTTP 429: circuit-breaking this source for the run",
                )
            if 400 <= response.status_code < 500:
                # 4xx is a request bug, never retried.
                return ToolResult(
                    source=source,
                    fetched_at=now,
                    status="error",
                    note=f"HTTP {response.status_code} (not retried)",
                )
            if response.status_code != 200:  # keep the non-JSON-200 note
                last_note = f"HTTP {response.status_code}"

        if attempt < attempts - 1:
            await asyncio.sleep(config.BACKOFF_BASE_S * (2**attempt))

    return ToolResult(
        source=source,
        fetched_at=now,
        status="error",
        note=f"failed after {attempts} attempts: {last_note}",
    )


def compact_ts(dt: datetime) -> str:
    """Evidence-id-safe timestamp: no spaces, no colons (`20260905T0305`)."""
    return dt.strftime("%Y%m%dT%H%M")
