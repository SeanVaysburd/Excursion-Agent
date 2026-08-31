"""The ONE place LLMs are constructed. Two providers behind one adapter:

  ollama      (quickstart default) ChatOllama, grammar-constrained
              json_schema structured output, free, local
  claude-sdk  the claude-agent-sdk package wrapping the Claude Code CLI's
              subscription auth, dev runs bill the plan's Agent SDK
              credit, never API credits. Used purely as a completion
              backend: no tools, one turn.

Nothing outside this module may construct a model. The adapter carries the
politeness discipline for LLM calls: a per-provider concurrency semaphore,
per-call timeouts, and per-run call counting via RunContext.llm_calls.

GUARD (user-mandated): claude-sdk with ANTHROPIC_API_KEY set in the
environment refuses to run, a set key silently shadows subscription auth
and would bill API credits unnoticed.

Recovery ladder for structured output (identical shape both providers,
per the no-provider-forks rule): one retry, shrunk evidence pack if the
caller provides a shrink callback (the realistic Ollama failure is a
truncated prompt yielding a degenerate object), else a JSON-schema
reminder, then the caller's fallback path with confidence=low and the
parse failure stated. Schemas are never loosened.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from dataclasses import dataclass
from typing import Callable

from pydantic import BaseModel, ValidationError

from src import config
from src.tools.base import RunContext


class ProviderConfigError(RuntimeError):
    """Misconfiguration that must stop the run loudly, not degrade."""


@dataclass
class LLMResult:
    obj: BaseModel | None
    raw: str
    error: str | None
    retried: bool
    provider: str


def _strip_fences(text: str) -> str:
    text = text.strip()
    match = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    # Fall back to the outermost JSON object if prose surrounds it.
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        return text[start : end + 1]
    return text


class LLMAdapter:
    def __init__(self, provider: str):
        self.provider = provider
        self._semaphore = asyncio.Semaphore(config.LLM_SEMAPHORE.get(provider, 2))
        self._timeout = config.LLM_TIMEOUT_S.get(provider, 120)

    # -- public ------------------------------------------------------------
    async def structured(
        self,
        prompt: str,
        schema: type[BaseModel],
        purpose: str,
        ctx: RunContext,
        shrink: Callable[[str], str] | None = None,
    ) -> LLMResult:
        """One structured completion with the standard recovery ladder."""
        result = await self._attempt(prompt, schema, purpose, ctx)
        if result.obj is not None:
            return result

        retry_prompt = (
            shrink(prompt)
            if shrink is not None
            else prompt
            + "\n\nREMINDER: return ONLY valid JSON matching the schema. "
            "No prose, no markdown fences."
        )
        retried = await self._attempt(retry_prompt, schema, purpose, ctx)
        return LLMResult(
            obj=retried.obj,
            raw=retried.raw,
            error=retried.error if retried.obj is None else None,
            retried=True,
            provider=self.provider,
        )

    # -- internals ---------------------------------------------------------
    async def _attempt(
        self, prompt: str, schema: type[BaseModel], purpose: str, ctx: RunContext
    ) -> LLMResult:
        ctx.llm_calls[purpose] += 1
        ctx.llm_calls["total"] += 1
        try:
            async with self._semaphore:
                raw, obj, error = await asyncio.wait_for(
                    self._invoke(prompt, schema), timeout=self._timeout
                )
        except asyncio.TimeoutError:
            return LLMResult(None, "", f"timeout after {self._timeout}s", False, self.provider)
        except Exception as exc:  # noqa: BLE001 - mapped to the fallback path
            return LLMResult(None, "", f"{type(exc).__name__}: {exc}", False, self.provider)
        return LLMResult(obj, raw, error, False, self.provider)

    async def _invoke(self, prompt: str, schema: type[BaseModel]):
        if self.provider == "ollama":
            return await self._invoke_ollama(prompt, schema)
        if self.provider == "claude-sdk":
            return await self._invoke_claude_sdk(prompt, schema)
        raise ProviderConfigError(f"unknown LLM_PROVIDER {self.provider!r}")

    async def _invoke_ollama(self, prompt: str, schema: type[BaseModel]):
        from langchain_ollama import ChatOllama

        model = ChatOllama(
            model=config.OLLAMA_MODEL,
            temperature=0,
            num_ctx=config.OLLAMA_NUM_CTX,
            num_predict=config.OLLAMA_NUM_PREDICT,
        )
        structured = model.with_structured_output(
            schema, method="json_schema", include_raw=True
        )
        result = await structured.ainvoke(prompt)
        raw_message = result.get("raw")
        raw = getattr(raw_message, "content", "") or ""
        parsed = result.get("parsed")
        parsing_error = result.get("parsing_error")
        if parsed is not None:
            return raw, parsed, None
        return raw, None, f"parse failure: {parsing_error}"

    async def _invoke_claude_sdk(self, prompt: str, schema: type[BaseModel]):
        from claude_agent_sdk import ClaudeAgentOptions, query

        schema_json = json.dumps(schema.model_json_schema(), indent=None)
        full_prompt = (
            f"{prompt}\n\n"
            f"Respond with ONLY a JSON object matching this JSON Schema "
            f"(no prose, no markdown fences):\n{schema_json}"
        )
        options = ClaudeAgentOptions(
            model=config.ANTHROPIC_MODEL,
            allowed_tools=[],
            max_turns=1,
        )
        chunks: list[str] = []
        final: str | None = None
        async for message in query(prompt=full_prompt, options=options):
            kind = type(message).__name__
            if kind == "AssistantMessage":
                for block in getattr(message, "content", []) or []:
                    text = getattr(block, "text", None)
                    if text:
                        chunks.append(text)
            elif kind == "ResultMessage":
                final = getattr(message, "result", None) or None
        raw = final if final is not None else "".join(chunks)
        try:
            obj = schema.model_validate(json.loads(_strip_fences(raw)))
            return raw, obj, None
        except (json.JSONDecodeError, ValidationError) as exc:
            return raw, None, f"parse failure: {type(exc).__name__}: {exc}"


_ADAPTER: LLMAdapter | None = None
_PROBED = False


def get_llm() -> LLMAdapter:
    """Provider adapter singleton, guarded at first construction."""
    global _ADAPTER
    if _ADAPTER is None:
        provider = config.LLM_PROVIDER
        if provider not in config.LLM_SEMAPHORE:
            raise ProviderConfigError(
                f"LLM_PROVIDER={provider!r} is not one of "
                f"{sorted(config.LLM_SEMAPHORE)}, check .env"
            )
        if provider == "claude-sdk" and os.environ.get("ANTHROPIC_API_KEY"):
            raise ProviderConfigError(
                "REFUSING TO RUN: LLM_PROVIDER=claude-sdk but ANTHROPIC_API_KEY "
                "is set. A set key silently shadows subscription auth and would "
                "bill API credits without you noticing. Unset the key (or switch "
                "provider) and re-run."
            )
        _ADAPTER = LLMAdapter(provider)
    return _ADAPTER


async def probe(ctx: RunContext) -> None:
    """One cheap startup call proving the configured provider actually
    works (subscription auth for claude-sdk, a running server for ollama).
    Fails loudly, a broken provider must never degrade into silence."""
    global _PROBED
    if _PROBED:
        return
    adapter = get_llm()

    class _Probe(BaseModel):
        ok: bool

    result = await adapter.structured(
        'Return {"ok": true}', _Probe, purpose="probe", ctx=ctx
    )
    if result.obj is None or result.obj.ok is not True:
        hint = (
            "is the Ollama app running, and did you `ollama pull "
            f"{config.OLLAMA_MODEL}`?"
            if adapter.provider == "ollama"
            else "is Claude Code installed and logged in on this machine?"
        )
        raise ProviderConfigError(
            f"LLM provider {adapter.provider!r} failed its startup probe "
            f"({result.error}), {hint}"
        )
    _PROBED = True
