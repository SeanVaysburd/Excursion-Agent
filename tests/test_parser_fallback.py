"""Malformed LLM output must land in the recovery ladder and then the
fallback path -- never crash. Proven with a stub provider returning
garbage (no network, no model)."""

from __future__ import annotations

from pydantic import BaseModel

from src.agents.llm import LLMAdapter
from src.tools.base import RunContext


class TinySchema(BaseModel):
    ok: bool


class GarbageAdapter(LLMAdapter):
    """Provider stub: returns non-JSON garbage every time."""

    def __init__(self):
        super().__init__(provider="ollama")
        self.invocations = 0

    async def _invoke(self, prompt, schema):
        self.invocations += 1
        return "```\nnot json at all {{{", None, "parse failure: garbage"


class HealsOnRetryAdapter(GarbageAdapter):
    async def _invoke(self, prompt, schema):
        self.invocations += 1
        if self.invocations == 1:
            return "garbage", None, "parse failure: garbage"
        return '{"ok": true}', TinySchema(ok=True), None


async def test_double_parse_failure_returns_none_never_raises():
    adapter = GarbageAdapter()
    ctx = RunContext(scenario="test")
    result = await adapter.structured("prompt", TinySchema, purpose="agent", ctx=ctx)
    assert result.obj is None
    assert result.retried is True
    assert result.error and "parse failure" in result.error
    assert adapter.invocations == 2  # exactly one retry
    assert ctx.llm_calls["agent"] == 2  # both attempts counted


async def test_shrink_callback_shapes_the_retry_prompt():
    seen: list[str] = []

    class Recorder(GarbageAdapter):
        async def _invoke(self, prompt, schema):
            seen.append(prompt)
            return await super()._invoke(prompt, schema)

    adapter = Recorder()
    await adapter.structured(
        "LONG PROMPT",
        TinySchema,
        purpose="agent",
        ctx=RunContext(scenario="test"),
        shrink=lambda p: "SHRUNK",
    )
    assert seen == ["LONG PROMPT", "SHRUNK"]


async def test_retry_success_clears_the_error():
    adapter = HealsOnRetryAdapter()
    result = await adapter.structured(
        "prompt", TinySchema, purpose="agent", ctx=RunContext(scenario="test")
    )
    assert result.obj is not None and result.obj.ok is True
    assert result.error is None
    assert result.retried is True
