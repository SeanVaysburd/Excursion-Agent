"""Domain agent callers: evidence pack in, one structured LLM call out.

The orchestrator PRE-FETCHES all tool data and hands each agent a pack
(design note for the README: pre-fetching is what makes the politeness
batching enforceable, the spec's "one call + tools" is preserved
semantically, the tools feed the call). Agents never touch the network.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.agents.llm import LLMAdapter, LLMResult
from src.agents.rubric import build_prompt
from src.agents.schemas import AgentReport, report_schema_for
from src.tools.base import RunContext

MAX_EVIDENCE_LINES = 80  # pack builders stay under this; shrink halves it


@dataclass
class EvidencePack:
    domain: str  # "nature" | "outdoor_event" | "indoor"
    date: str
    weekday: str
    windows: list[dict]  # {label, minutes, soft: bool}
    sources: list[dict]  # {source, status, note}
    evidence_lines: list[str]  # "<id> | <human-readable record line>"
    allowed_ids: list[str]
    memory_block: str  # formatted entries, or the cold-start statement
    candidates: list[dict]  # {candidate_id, name, site, window}
    cold_start: bool = False
    notes: list[str] = field(default_factory=list)


def _fmt_windows(windows: list[dict]) -> str:
    return "; ".join(
        f"{w['label']} ({w['minutes']} min{', overlaps a tentative block' if w.get('soft') else ''})"
        for w in windows
    ) or "none"


def _fmt_sources(sources: list[dict]) -> str:
    return "\n".join(
        f"  - {s['source']}: {s['status']}" + (f" ({s['note']})" if s.get("note") else "")
        for s in sources
    ) or "  - (none)"


def _fmt_candidates(candidates: list[dict]) -> str:
    return "\n".join(
        f"  - candidate_id={c['candidate_id']} | {c['name']} | site: {c['site']} | window: {c['window']}"
        for c in candidates
    )


def _prompt_from(pack: EvidencePack, evidence_lines: list[str]) -> str:
    return build_prompt(
        domain=pack.domain,
        date=pack.date,
        weekday=pack.weekday,
        windows=_fmt_windows(pack.windows),
        sources=_fmt_sources(pack.sources),
        evidence="\n".join(f"  {line}" for line in evidence_lines) or "  (none)",
        memory=pack.memory_block or "  (none)",
        candidates=_fmt_candidates(pack.candidates),
    )


async def run_agent(
    adapter: LLMAdapter, ctx: RunContext, pack: EvidencePack
) -> tuple[AgentReport | None, LLMResult]:
    """One structured call. On parse failure the retry SHRINKS the evidence
    pack (the realistic local-model failure is a truncated prompt), and a
    second failure returns (None, result) for the caller's fallback path."""
    if not pack.candidates:
        return AgentReport(candidates=[], self_report="no candidates to score"), LLMResult(
            obj=None, raw="", error=None, retried=False, provider=adapter.provider
        )

    lines = pack.evidence_lines[:MAX_EVIDENCE_LINES]
    prompt = _prompt_from(pack, lines)

    def shrink(_previous: str) -> str:
        halved = lines[: max(8, len(lines) // 2)]
        return (
            _prompt_from(pack, halved)
            + "\nREMINDER: return ONLY valid JSON matching the schema."
        )

    schema = report_schema_for(pack.allowed_ids)
    result = await adapter.structured(
        prompt, schema, purpose="agent", ctx=ctx, shrink=shrink
    )
    report = result.obj if isinstance(result.obj, AgentReport) else None
    return report, result
