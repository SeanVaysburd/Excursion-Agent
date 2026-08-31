# Excursion Agent

A personal planning agent for the hours you're *not* at home: it reads your
calendar for free windows, checks real weather, live bird sightings, city
event permits, tides, and subway alerts, remembers how your past outings
actually went, and recommends what to do with a free morning — or plans your
whole week with a Tree-of-Thought search that understands a week of three
birding trips is worse than birding + a hike + a museum, even when the
numbers say otherwise.

**The problem it addresses:** free time gets spent by default, not by
intention — and generic recommenders don't know that you've already seen the
warblers at Prospect Park, that Jamaica Bay is miserable at midday, or that
the B train isn't running this weekend. This agent plans from *your*
feedback and *today's* conditions, and shows its evidence for every
recommendation.

**Who it's for:** course reviewers (this is a graded capstone — see
*Provenance & honesty*), and anyone in NYC who wants a local, inspectable
planning agent they can actually run.

---

## Quickstart — free path, no account, no API key

```
1. Install Ollama (https://ollama.com) and run:  ollama pull llama3.1:8b
2. python3 -m venv .venv && source .venv/bin/activate
   && pip install -r requirements.txt
3. cp .env.example .env && python demo.py
```

That's everything. `.env.example` defaults to `LLM_PROVIDER=ollama`, and
every other setting ships with a working default.

Honesty note, up front: **local-model output is weaker than the committed
Claude-produced samples — same system, smaller model.** The rails
(evidence-grounding, validators, fallbacks) don't depend on the model; the
prose and judgment quality do. Expect the ~5 GB model download once, and
CPU-heavy (fan-spinning) inference while it plans.

First-run expectations: `pip install` pulls the pinned scientific stack
(torch etc., a few GB the first time); the first plan also downloads the
~90 MB sentence-transformer weights into `.cache/`. Both are one-time.
Network is required for the live data sources.

### Make it yours (optional)

- **Claude-quality output** — `LLM_PROVIDER=claude-sdk` in `.env` if you
  have a Claude subscription with Claude Code installed: run the bundled
  CLI's one-time login,
  `.venv/lib/python*/site-packages/claude_agent_sdk/_bundled/claude setup-token`,
  and paste the printed token as `CLAUDE_CODE_OAUTH_TOKEN=` in `.env`.
  Runs bill your plan's included Agent SDK usage, never per-token API
  credits — and the app **refuses to start** if `ANTHROPIC_API_KEY` is set
  at the same time, so subscription auth can't be silently shadowed into
  metered billing.
- **Your location** — `HOME_LAT`/`HOME_LON` in `.env` (default: an
  approximate Brooklyn centroid; see *Privacy*). Drives weather and
  bird-radius queries. The travel-time matrix stays the labeled sample —
  it's the documented swappable seam (below).
- **Your birds** — `EBIRD_API_KEY` (free at https://ebird.org/api/keygen)
  unlocks live eBird sightings and the life-list "lifer bonus" (scenario
  S4). Without it, the nature agent runs on iNaturalist alone and says so
  in its own self-report. Point `--life-list` at your own eBird-style CSV.
- **Your calendar** — `python demo.py --calendar path/to/your.ics`.
  (Google Calendar sync is deliberate future work; for now, export an
  .ics. Hard events block time; events marked tentative/optional — or
  `X-SOFT:true` — survive as a visible score penalty instead.)

### The UI

```
uvicorn src.api.app:app --host 127.0.0.1 --port 8000     # backend
cd ui && npm ci && npm run dev                            # http://localhost:5173
```

Three tabs: **Day Plan** (top-3 cards per free window: score breakdown,
confidence badge, evidence chips, lifer badge, weather-gate flags, and an
Approve button with a confirm dialog), **Week Plan** (the winning weekly
set, two collapsed alternates, critic penalties as chips, and the
naive-vs-ToT contrast), **Run Trace** (every run's full audit log as an
expandable timeline). Day/Week serve the latest completed run instantly;
*Refresh* triggers a live run (the weekly one takes minutes and says so).
Node is needed only for the UI. `pytest` runs the offline test suite
(no network, no keys).

### Don't want to run it?

Real, committed output from real runs: sample trajectories in
[`runs/`](runs/), computed metrics in [`eval/results.md`](eval/results.md),
screenshots in [`docs/screenshots/`](docs/screenshots/). The Week-3
retrieval checkpoint (the memory layer's own demo and calibration) lives in
[`docs/week3/`](docs/week3/).

---

## Architecture

```
                       daily waterfall (cheapest first)
  calendar.ics ──► free windows ──► weather gate ──► 3 domain agents ──► transit
      │               │  zero windows?     │   (parallel, one LLM call    adjust
      │               ▼                    │    each + evidence pack)       │
      │           ESCALATE:                │         │                      ▼
      │           ask, don't guess         │         ▼                 top-3 per
      │                                    │   post-processing:        free slot
      │      ┌─────────────────────────────┘   groundedness → cold-start →
      │      │  evidence registry              lifer bonus → soft-conflict →
      ▼      ▼                                 transit alerts → self-report →
  ┌─────────────────────────────┐              clamp(final_score)
  │ tools (one polite wrapper): │
  │ Open-Meteo · NWS · NOAA     │           weekly Tree-of-Thought
  │ tides · NYC events · eBird  │   Mon→Sun, branch = day's top-3, beam 4
  │ · iNaturalist · MTA alerts  │   critic re-scores each partial set for
  │ · travel matrix (static)    │   variety / walking / transit fatigue;
  └─────────────────────────────┘   prune top-4 + 3-below-leader;
             ▲                      naive rank-by-sum shown alongside
             │
  ┌──────────┴──────────────────┐   every step → runs/<name>.jsonl
  │ memory: LlamaIndex + Chroma │   (stage, tool, latency, evidence ids,
  │ over past-excursion notes,  │    prune reasons, critic penalties,
  │ top-7 → re-rank → top-3,    │    validations, run summary)
  │ cosine cutoff 0.55,         │
  │ cold-start fallback         │
  └─────────────────────────────┘
```

Every number a reviewer might challenge lives commented in
[`src/config.py`](src/config.py) — weather gates (with units), penalties,
beam parameters, rate limits, the call-budget table, the similarity cutoff.

### Scenarios (`python demo.py --scenario S1..S5|all`)

| # | shows | mechanism |
|---|---|---|
| S1 | daily plan, live weather + memory | the full waterfall; cites the retrieved "midday crowds, 4/10" memory at Jamaica Bay |
| S2 | weekly naive-vs-ToT contrast | rank-by-sum picks repetition; the critic's variety penalty flips it |
| S3 | cold start | kayaking has no logged history → planned from live evidence, `confidence=low`, stated out loud |
| S4 | lifer bonus | species observed nearby but missing from the life list, NAMED in the reason; `--life-list data/life_list_full.csv` is the zero-lifers control |
| S5 | approval-gated write | the ONLY write tool appends a VEVENT to a local working copy after an explicit confirm; semantic diff shown |

`--force-error <source>` runs a labeled degradation demo (every trace line
is stamped `injected_failure` — a simulated outage can never masquerade as
a real one). `python -m scripts.evaluate` reruns the whole suite and
regenerates `eval/results.md`.

---

## Design decisions (and their whys)

- **No CrewAI, no MCP, no OAuth, no scraping.** The orchestration is plain
  async Python on purpose: the waterfall and the beam search are the
  design, not a framework's opinion. (You'll see `mcp` in the lockfile —
  it's the Agent SDK's internal transport protocol, not agent-coordination
  architecture.)
- **Providers: `ollama` (free) and `claude-sdk` (subscription).** The
  original stack sketch named the metered `langchain-anthropic` API path;
  it was deliberately dropped at the dependency gate on cost grounds —
  reviewers run free or on a subscription they already have. The factory
  seam (`src/agents/llm.py`) is one adapter; re-adding a provider is ~30
  lines.
- **Agents don't call tools; tools feed agents.** The orchestrator
  pre-fetches everything through ONE polite wrapper and hands each agent
  an evidence pack. That's what makes rate-limit discipline enforceable
  (batching by design), keeps the local model network-free by
  construction, and lets a per-call schema constrain citations to real
  evidence ids.
- **Transit = static matrix + live alerts.** A full GTFS routing engine is
  out of scope; base minutes come from
  [`data/travel_times.json`](data/travel_times.json) behind a single
  swappable function ([`src/tools/travel_matrix.py`](src/tools/travel_matrix.py)),
  while LIVE MTA service alerts are fetched per run — a suspension on a
  line a trip depends on prunes it; delays penalize it; the alert text is
  cited in the card. Events carry no coordinates, so they fall back to
  per-borough default times, flagged as approximate.
- **The model's score and the code's arithmetic never mix.** Agents emit a
  raw 1–10; every adjustment after that (lifer bonus, soft-conflict,
  transit) is an attributable code-side delta, and `final_score` is
  clamped. The UI chips and the trace show exactly who contributed what.
- **Groundedness is enforced twice.** The per-call schema types
  `evidence_ids` as a literal enum of this run's real ids (the local
  model's grammar decoder physically can't invent one), and a validator
  re-checks membership afterward. The metric's denominator is everything
  agents *emitted*, pre-strip — a post-drop rate would be trivially 100%.
- **Reproducibility, stated honestly:** beam results are deterministic
  given the same critic verdicts (ordered expansion, total sort key,
  seeded tie-break) — not across days, since weather and LLM outputs are
  live. Memory's recency weight is corpus-anchored rather than
  wall-clock-anchored for the same reason.

## Synthetic data statement (course requirement)

Everything under [`data/`](data/) is synthetic and labeled in-file:
the sample calendar week (regenerated onto the current week when stale —
the demo prints a notice), the fully-blocked escalation fixture, the venue
catalog and hours (simplified approximations), the travel-time matrix, the
outdoor-site catalog (`sites.json`, an addition to the original data-file
list, needed for coordinates/regions/tides), and the life list —
**seeded from real regional observations but intentionally incomplete**
(~150 of the species currently being seen, always missing the two demo
shorebirds), so the lifer path demonstrates on live data.
`data/excursions.json` is the synthetic 20-entry feedback corpus the
memory layer was calibrated on in Week 3.

**Privacy:** the "home" origin everywhere in this repo is an approximate
Brooklyn neighborhood centroid, not a residential address, and the
committed matrix is anchored to it.

## Known limitations

- One metro-wide forecast serves all sites (Harriman is ~40 mi out; its
  hours carry the same `wx:` evidence).
- Recurring calendar events (RRULE) are not expanded — the synthetic
  calendar doesn't use them; bring a flattened .ics.
- Season/type matching in memory is the Week-3 design: exact-match with a
  measured 0.55 cosine cutoff (see `docs/week3/` for the calibration
  bands and the margin).
- The S1 "rain" branch depends on the real forecast — by design. The
  committed rainy trace names its real date; run on a sunny day and you'll
  get the sunny plan. **That's the system working, not a bug.** Same for
  S2: if a given week's live data produces no naive-vs-ToT contrast,
  `eval/results.md` says so and the recourse is another week.

## API politeness

One shared wrapper enforces: per-source minimum intervals (iNaturalist far
under its 60/min), in-run caching with single-flight coalescing, max-2
retries on network/5xx only (never 4xx), circuit-breaking a source for the
run on 429, batch-by-design fetching (ONE weather call per run covers 16
days; one eBird+iNat call per site region), a custom User-Agent, and a
hostname allowlist that raises on anything undocumented. Per-source call
counts print at the end of every run and land in each trace's
`run_summary`; a config ceiling flags runaway designs instead of raising
limits. The same discipline covers LLM calls (per-provider concurrency
caps, counted per run, checked against the beam-search bound in eval).

## Safety layer

Zero usable free windows → the run **escalates with a question instead of
guessing**. Groundedness and hard-constraint validators gate final outputs
(violations metric target: 0). The single write tool (calendar) runs only
after an explicit confirm — and writes to a gitignored working copy, never
the committed sample. Agent self-reports are scanned for narrated
degradation ("assumed", "no data"…) which costs confidence — the threat
model is honest self-described failure, not adversarial agents (they're
ours). Secrets are redacted at every exit (logging, stdout/stderr,
exception hook) and `.env` is gitignored from the first commit. Every run
writes a full trajectory to [`runs/`](runs/) — the audit trail, the eval's
only data source, and the Run Trace tab's material are the same file.

## Tests

`pytest` — all offline, no keys, no network: politeness wrapper semantics,
Week-3 regression (byte-exact against the committed checkpoint output),
re-ranker + calibration bands, groundedness (including the honest
denominator), lifer code-matching, weather gate over synthetic payloads,
ICS hard/soft parsing, hard constraints, beam isolation (frozen nodes,
sibling non-contamination, the variety-penalty flip), and parser fallback
(garbage LLM output → stated low-confidence default, never a crash).
Fixtures in unit tests are normal engineering; the no-replay honesty rule
binds the agent runtime.

## Provenance & honesty (course requirement)

Committed sample traces are real runs (provider named in each trace's
`run_summary`; Claude-produced samples via `claude-sdk`, plus one labeled
`ollama` trace as the free-path proof). Simulated failures are stamped on
every line. The Week-3 demo in `docs/week3/` REPLAYS its committed LLM
outputs (labeled in its output) — distinct from the live agent runs here.
`eval/results.md` cites the exact trace file behind every number.

## Future work

Google Calendar / CalDAV sync (today: bring an .ics), a real routing API
behind the travel-matrix seam, per-site weather, and RRULE expansion.
