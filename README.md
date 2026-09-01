# Excursion Agent

A personal planner for the hours you're not at home. It reads your calendar
to find free windows, checks real weather, live bird sightings, city event
permits, tides and subway alerts, remembers how your past outings actually
went, and tells you what's worth doing with a free morning. Ask for a whole
week and it runs a Tree-of-Thought search that knows three birding trips in
one week is a worse week than birding plus a hike plus a museum, even when
the raw scores say otherwise.

The problem, in one line: free time gets spent by default instead of on
purpose. Generic recommenders don't know you've already seen the warblers
at Prospect Park, that Jamaica Bay is miserable at midday, or that the B
train is down this weekend. This agent plans from your own feedback and
today's conditions, and shows the evidence behind every suggestion.

Built as a graded course capstone (see the honesty section near the end),
but it's a real tool. If you live in NYC you can run it as is.

## Quickstart: free, no account, no API key

```
ollama pull llama3.1:8b     # after installing Ollama from https://ollama.com
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python demo.py
```

That's the whole setup. The example env file already points at the local
model, and everything else has a working default. One catch: the Ollama
server must be running when you plan. The desktop app keeps it running in
the background; if you installed the bare CLI (Homebrew), start it with
`ollama serve` in another terminal first (or `brew services start ollama`
to make it automatic). The startup probe tells you if it can't connect.

Fair warning before you compare outputs: the local model is noticeably
weaker than the committed Claude-produced samples. Same system, smaller
model. The guardrails (evidence grounding, validators, fallbacks) don't
depend on which model you pick, but the quality of the reasoning does.
Expect a one-time 5 GB model download, and real fan noise while it thinks.
On this path, your machine is the datacenter. Low-RAM machine? Set
`OLLAMA_MODEL=llama3.2:3b` (or `gemma2:2b`) in `.env`; the same system
runs on the smaller model and the quality warning above applies double.

First-run notes: pip pulls the pinned scientific stack (a few GB, once),
and the first plan downloads about 90 MB of embedding weights into
`.cache/`. The live data sources need network.

### Make it yours (all optional)

- **Better output with Claude.** Set `LLM_PROVIDER=claude-sdk` in `.env`
  if you have a Claude subscription with Claude Code installed. One-time
  setup: run
  `.venv/lib/python*/site-packages/claude_agent_sdk/_bundled/claude setup-token`
  and paste the printed token into `.env` as `CLAUDE_CODE_OAUTH_TOKEN=`.
  This uses your plan's included Agent SDK allowance, never per-token API
  credits. If `ANTHROPIC_API_KEY` is set at the same time the app refuses
  to start, so subscription auth can't quietly turn into metered billing.
- **Your location.** `HOME_LAT` and `HOME_LON` in `.env`. The default is
  an approximate Brooklyn centroid, not anyone's address (see Privacy).
  It drives weather and bird-radius queries. The travel-time matrix stays
  the labeled sample either way; that seam is explained below.
- **Your birds.** A free `EBIRD_API_KEY` (ebird.org/api/keygen) unlocks
  live eBird sightings and the lifer bonus (scenario S4). Without it the
  nature agent runs on iNaturalist alone and says so in its own
  self-report. Point `--life-list` at your own eBird-style CSV.
- **Your calendar.** Export a real one and run
  `python demo.py --calendar path/to/your.ics`. From Google Calendar:
  Settings, then Import & export, then Export (unzip and use your
  calendar's .ics). From Apple Calendar: select a calendar, then File,
  then Export. Hard events block time. Events marked tentative or
  optional (or carrying `X-SOFT:true`) stay plannable but cost a visible
  score penalty. Recurring events (RRULE) aren't expanded, so prefer a
  flattened export. Live Google Calendar sync is future work. Without
  your own file, the committed synthetic sample calendar is used: five
  weeks of realistic blocks, regenerated onto the coming weeks with a
  printed notice whenever it goes stale.
- **Your feedback.** The UI is the front door: every suggestion card has
  **Pass** (with a quick why) and, after you take a trip, **Log this
  trip** with a 1-10 rating and a note. The Day tab's **Log an outing**
  covers trips the agent never suggested, and the accept dialog offers an
  optional note after a calendar write. All of it appends to
  `data/excursions.json` behind an explicit save, and the same server
  process retrieves it from the next run on. Editing the file by hand
  still works too (same fields as the samples; the next run reindexes).
  Verified end to end: one added kayaking note turned that activity from
  a cold start into a 0.75-similarity retrieval.

### The UI

```
uvicorn src.api.app:app --host 127.0.0.1 --port 8000     # backend
cd ui && npm ci && npm run dev                            # http://localhost:5173
```

Four tabs. **Ask** is the front door: type "what should I do saturday
morning?" and an intent guardrail (deterministic parsing first, one
validated LLM call only for fuzzy text) picks the day, refuses anything
outside the 16-day forecast horizon, and asks back when the request is
ambiguous; the run then streams live as an orchestration diagram whose
nodes light up only when trace records prove them. **Day plan** shows the
top 3 cards per free window: score breakdown, confidence badge, evidence
chips, lifer badge, weather-gate flags, Add to calendar behind a confirm,
plus Pass and Log this trip feeding the memory. A run picker pins any
committed clean run; test fixtures (simulated failures, the escalation
calendar) stay out of this surface and live labeled in Runs. **Week
plan** shows the winning set, two collapsed alternates, the critic's
penalties, the naive-vs-ToT comparison, and **Add week to calendar**: one
confirm writes every pick. **Runs** renders any trace as the flow diagram
plus an expandable timeline, including each agent's complete structured
output (`agent_report` records). Day and Week load the latest completed
run instantly; Run live starts a fresh one on a server task (one at a
time; a second request gets a clear 409) and the UI polls the growing
trace. A model switch in the header picks which provider runs the next
live run (Claude on a subscription, or the local Ollama model); the
choice rides along on each request and every trace's run summary records
the provider that actually ran, so provenance survives the switch. Light
and dark theme. Node is only needed for the UI. `pytest` runs the
offline test suite with no network and no keys.

### Don't want to run it?

Real committed output from real runs: sample trajectories in
[`runs/`](runs/), computed metrics in [`eval/results.md`](eval/results.md)
(groundedness, hard-constraint violations, escalation, forced-error
degradation, fallback counts, per-stage latency, call accounting against
the budget, critic-bound adherence, the naive-vs-ToT key result, the
lifer on/off ablation, rubric consistency across domains, and acceptance
rate + calibration from recorded decisions), screenshots in
[`docs/screenshots/`](docs/screenshots/). The Week-3
retrieval checkpoint (the memory layer's own demo and calibration) is in
[`docs/week3/`](docs/week3/).

## Architecture

```
                       daily waterfall (cheapest first)
  calendar.ics ──► free windows ──► weather gate ──► 3 domain agents ──► transit
      │               │  zero windows?     │   (parallel, one LLM call    adjust
      │               ▼                    │    each + evidence pack)       │
      │           ESCALATE:                │         │                      ▼
      │           ask, don't guess         │         ▼                 top-3 per
      │                                    │   post-processing:        free slot
      │      ┌─────────────────────────────┘   groundedness, cold-start,
      │      │  evidence registry              lifer bonus, soft-conflict,
      ▼      ▼                                 transit alerts, self-report,
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

### Project layout

```
src/agents/         domain agents, shared rubric, schemas, LLM adapter,
                    intent guardrail, post-processing pipeline
src/orchestration/  daily waterfall + weekly Tree-of-Thought beam search
src/memory/         the Week-3 retrieval layer (LlamaIndex + Chroma)
src/tools/          one polite wrapper + the seven API tools, calendar
                    read/write, travel matrix
src/safety/         validators, self-report scan, redaction, trajectory log
src/api/            FastAPI backend        ui/          React frontend
data/               synthetic inputs (labeled)           runs/   trajectories
eval/               computed results        docs/week3/  retrieval checkpoint
scripts/            evaluate, calendar + life-list generators, week3 demos
```

### Where each course checkpoint lives

| checkpoint | design item | implementation |
|---|---|---|
| Week 1 | problem, user, environment, actions | this README's opening + the architecture above |
| Week 2 | waterfall reasoning loop, hard/soft calendar logic | [`src/orchestration/waterfall.py`](src/orchestration/waterfall.py), [`src/tools/calendar_tool.py`](src/tools/calendar_tool.py) |
| Week 2 | short-term memory (fetched-once, ruled-out, scores) | `RunContext` cache + evidence registry in [`src/tools/base.py`](src/tools/base.py) |
| Week 3 | semantic retrieval over feedback, re-rank, cutoff | [`src/memory/retrieval.py`](src/memory/retrieval.py), calibration in [`docs/week3/`](docs/week3/) |
| Week 4 | Tree-of-Thought weekly beam + critic + pruning | [`src/orchestration/tot_beam.py`](src/orchestration/tot_beam.py) |
| Week 5 | five agents, shared rubric, supervisor coordination | roster below; rubric in [`src/agents/rubric.py`](src/agents/rubric.py) |
| Week 6 | guardrails, escalation, approval gates, redaction | [`src/safety/`](src/safety/), [`src/agents/intent.py`](src/agents/intent.py), the two gated write paths |
| Week 6 | evaluation metrics from real traces | [`scripts/evaluate.py`](scripts/evaluate.py) -> [`eval/results.md`](eval/results.md) |
| Weeks 1/2/4 | accept/reject + rating feedback into memory | `POST /api/feedback` in [`src/api/app.py`](src/api/app.py) + the UI's Pass / Log this trip |

### The agents

| agent | kind | role | where |
|---|---|---|---|
| nature | LLM, shared rubric | scores birding/hike/kayak sites from eBird, iNaturalist, tides, weather, memory | [`src/agents/domain_agents.py`](src/agents/domain_agents.py) |
| outdoor events | LLM, shared rubric | scores permitted city events from the live feed, weather, memory | same file, different evidence pack |
| indoor | LLM, shared rubric | scores museums/venues from hours, transit, memory | same file |
| weekly critic | LLM | re-scores partial week sets for variety, walking, transit fatigue | [`src/orchestration/tot_beam.py`](src/orchestration/tot_beam.py) |
| supervisor | code, deterministic | runs the waterfall, fans out the agents, owns the beam loop and every validator | [`src/orchestration/`](src/orchestration/) |
| intent guardrail | code first, LLM fallback | turns free text into a validated day/week request, refuses out-of-horizon dates | [`src/agents/intent.py`](src/agents/intent.py) |

Every number a reviewer might want to argue with sits commented in
[`src/config.py`](src/config.py): weather gates (with units), penalties,
beam parameters, rate limits, the call-budget table, the similarity
cutoff.

### Scenarios (`python demo.py --scenario S1..S5|all`)

| # | shows | how |
|---|---|---|
| S1 | a daily plan from live weather plus memory | the full waterfall; cites the retrieved "midday crowds, rated 4/10" memory at Jamaica Bay |
| S2 | weekly naive vs ToT | rank-by-sum picks repetition; the critic's variety penalty flips it |
| S3 | cold start | kayaking has no logged history, so it's planned from live evidence only, confidence low, and it says so |
| S4 | lifer bonus | species seen nearby but missing from the life list, named in the reason; `--life-list data/life_list_full.csv` is the fuller-life-list control (live data can still surface a lifer or two even against the fuller list, and the eval reports whatever actually happened) |
| S5 | the approval gate | the only write tool appends a calendar event to a local working copy after an explicit confirm, and shows the diff |

Other flags: `--date YYYY-MM-DD` plans a specific day (rejected outside
the 16-day forecast horizon), `--approve prompt|auto|deny` controls the
S5 write gate (deny under `--scenario all` so unattended runs never
block), `--trace-tag` names the trace file, `--rebuild-memory` forces a
re-embed. `--force-error <source>` runs a labeled degradation demo: every
line of that trace is stamped `injected_failure`, so a simulated outage
can never pass for a real one (those fixture traces are also kept off the
UI's demo surface, visible only in the Runs tab). `python -m
scripts.evaluate` reruns the whole suite and regenerates
`eval/results.md`; `--skip-runs` recomputes the report from existing
traces. Beyond the headline metrics, the report includes a per-domain
rubric-consistency table (the three agents share one 1-10 rubric; the
table shows no domain drifts stricter or looser) and acceptance-rate and
calibration sections computed from whatever accept/pass decisions you
have recorded, with the honest n stated.

## Design decisions, and why

- **No CrewAI, no MCP, no OAuth, no scraping.** The orchestration is
  plain async Python on purpose. The waterfall and the beam search are
  the design; a framework would just be in the way. (You'll see `mcp` in
  the lockfile. That's the Agent SDK's internal transport protocol, not
  agent-coordination architecture.)
- **Two providers: `ollama` (free) and `claude-sdk` (subscription).** The
  original stack sketch named the metered `langchain-anthropic` API path.
  We dropped it on purpose at the dependency gate, for cost: reviewers
  run free, or on a subscription they already pay for. The factory in
  `src/agents/llm.py` is one adapter, and adding a provider back is about
  thirty lines.
- **Agents don't call tools. Tools feed agents.** The orchestrator
  fetches everything through one polite wrapper and hands each agent an
  evidence pack. That's what makes the rate-limit discipline enforceable,
  keeps the local model offline by construction, and lets each call's
  schema restrict citations to evidence that actually exists.
- **Transit is a static matrix plus live alerts.** A full GTFS routing
  engine is out of scope. Base minutes come from
  [`data/travel_times.json`](data/travel_times.json) behind one swappable
  function ([`src/tools/travel_matrix.py`](src/tools/travel_matrix.py)).
  Live MTA alerts are fetched each run: a suspension on a line your trip
  needs prunes it, delays cost points, and the alert text is quoted on
  the card. City events come with no coordinates, so they fall back to
  per-borough default times, flagged as approximate.
- **Weather is a gate at the extremes and evidence everywhere else.**
  Dangerous conditions (thresholds in `src/config.py`, with units) remove
  outdoor categories from a window in code, before any model call. Below
  those extremes, weather shapes scores continuously through the agents:
  every outdoor pack carries the hour-by-hour forecast as citable
  evidence and the shared rubric anchors the 1-10 scale to conditions,
  so a 45%-rain afternoon drags a festival toward a 5 while barely
  touching a museum. In the committed traces, 83% of outdoor and nature
  candidates reason about weather explicitly. There is deliberately no
  code-side "rain minus N points" formula: weather's cost depends on the
  activity, which is exactly the judgment the scoring agent exists to
  make, and a flat penalty would double-count it.
- **The model's score and the code's arithmetic never mix.** Agents
  output a raw 1-10. Everything after that (lifer bonus, soft-conflict
  penalty, transit) is a code-side adjustment with a label, and the final
  score is clamped. The UI chips and the trace show exactly who added
  what.
- **One rubric, three specialists.** The parallel domain agents could
  quietly drift into different strictness and let one domain always win.
  The guard is a single shared 1-10 anchor block injected verbatim into
  all three prompts ([`src/agents/rubric.py`](src/agents/rubric.py));
  only the few-shot examples that translate "a 9" into each domain's
  terms differ, and every post-score adjustment is code-side and
  identical. `eval/results.md` carries the per-domain score table that
  shows the scale holding.
- **Groundedness is enforced twice.** Each call's schema types the
  evidence ids as a literal enum of what was actually fetched this run
  (the local model's grammar decoder physically can't cite anything
  else), and a validator re-checks membership afterward. The metric
  counts everything the agents emitted before stripping; measuring after
  the strip would make 100% meaningless.
- **Fallbacks are always visible, never silent.** Every degradation
  (a down source, a widened radius, a parser failure) lands in the
  trace as a labeled fallback step and costs stated confidence; there
  is no mock or canned-response mode anywhere, because an unlabeled
  stand-in would undermine every claim the trace makes.
- **The Ask tab is a build-time addition** to the frozen three-tab
  spec, in the same spirit as `sites.json`: a thin natural-language
  router ([`src/agents/intent.py`](src/agents/intent.py)) into exactly
  the same waterfall and ToT runs the buttons start, with the same
  input check. No parallel planning path exists behind it.
- **Reproducibility, stated plainly.** Beam results are deterministic
  given the same critic verdicts: ordered expansion, a total sort key,
  a seeded tie-break. They aren't reproducible across days, because
  weather and model outputs are live. Memory's recency weight is
  anchored to the corpus rather than the clock for the same reason.

## Synthetic data statement

Everything under [`data/`](data/) is synthetic and labeled where the
format allows a label (an .ics or CSV cannot carry one, so this section
is their label): the five-week sample calendar (regenerated onto the
coming weeks when stale, with a printed notice), the fully-blocked
escalation fixture,
the venue catalog with simplified hours, the travel-time matrix, the
outdoor-site catalog (`sites.json`, an addition to the original data-file
list, needed for coordinates, regions and tides), and the life list. The
life list is seeded from live regional observations and intentionally
missing exactly two seasonally common shorebirds (Semipalmated and Least
Sandpiper), so the lifer path demonstrates on live data with a small,
named, believable bonus; the fuller control list includes them, and
`scripts/seed_life_list.py` reseeds both when the season shifts.
`data/excursions.json` is the synthetic 20-entry feedback corpus the
memory layer was calibrated on in Week 3; entries you add through the
feedback UI are appended there tagged `"source": "user"`, so your real
feedback and the seeded corpus stay distinguishable.

**Privacy:** the "home" origin used everywhere in this repo is an
approximate Brooklyn neighborhood centroid, not a residential address,
and the committed travel matrix is anchored to it.

## Known limitations

- One metro-wide forecast serves all sites. Harriman is about 40 miles
  out and its hours carry the same `wx:` evidence ids.
- Each category is offered in its first ungated free window. On a day
  with two free windows the second can sit empty even when something
  could fit; a deliberate simplification, not a scheduling bug.
- Recurring calendar events (RRULE) aren't expanded. The synthetic
  calendar doesn't use them; bring a flattened .ics.
- Memory matching is the Week-3 design: exact season and type match with
  a measured 0.55 cosine cutoff. The calibration bands and the margin
  live in `docs/week3/`.
- Feedback saved through the UI is retrievable from the next run in the
  same server process (the rebuild goes through the vector store's own
  client). Hand-editing `data/excursions.json` while a server is already
  running is the one case that still needs a restart, because nothing
  tells the server the file changed; `python demo.py` runs always see
  the latest.
- The S1 rain branch depends on the real forecast, on purpose. The
  committed rainy trace names its real date. Run it on a sunny day and
  you get the sunny plan. That's the system working, not a bug. Same
  logic for S2: if a given week's live data produces no naive-vs-ToT
  contrast, `eval/results.md` says so, and the fix is trying another
  week.

## API politeness

One shared wrapper enforces all of it: per-source minimum intervals
(iNaturalist far under its 60/min), in-run caching with single-flight
coalescing so concurrent agents can't stampede a miss, at most two
retries on network errors and 5xx only (never 4xx), circuit-breaking a
source for the rest of the run on a 429, batch-by-design fetching (one
weather call per run covers 16 days; two eBird calls (recent plus
notable) and one iNaturalist call per site region), a custom User-Agent, and a hostname allowlist that
raises on anything undocumented. Per-source call counts print at the end
of every run and land in each trace's run summary. A config ceiling flags
runaway designs instead of raising limits. The same discipline covers LLM
calls: per-provider concurrency caps, counted per run, checked against
the beam-search bound in eval.

## Safety layer

If there are no usable free windows, the run stops and asks instead of
guessing. When a data source is down, the run does not stop: it proceeds
on fallbacks with confidence lowered and the failure stated, and the plan
carries a `degraded_sources` list the UI renders as a notice, which is
the ask-the-human moment for outages without blocking every run on one
flaky feed. Groundedness and hard-constraint validators gate final
outputs (the violations metric targets zero). There are exactly two
write paths, both behind an explicit confirm: the calendar tool (writes
a gitignored working copy, never the committed sample) and the feedback
endpoint (appends to the corpus). Every agent's complete structured
output lands in the trace as an `agent_report` record, so a reviewer can
audit what each agent said before any post-processing touched it; the
honest limit is that the model API exposes outputs, not chain-of-thought,
and the guardrails act on exactly what is logged. Agent self-reports get
scanned by the keyword and negative-lexicon check (the regex plus
sentiment guard from the safety plan) for narrated trouble ("assumed",
"no data" and friends), which costs confidence; the threat model there is
honest self-described failure, not adversarial agents, because the agents
are ours. Secrets are redacted at every exit (logging, stdout, stderr,
exception hook) and `.env` has been gitignored since the first commit.
Every run writes a full trajectory to [`runs/`](runs/). The audit trail,
the eval's only data source, and the Runs tab all read the same file.

## Tests

`pytest`, all offline, no keys, no network (after the one-time embedding
model download on first setup): politeness wrapper semantics, Week-3
regression (byte-exact against the committed checkpoint output),
re-ranker and calibration bands, groundedness including the honest
denominator, lifer code-matching, the weather gate over synthetic
payloads, ICS hard/soft parsing, hard constraints, beam isolation (frozen
nodes, sibling independence, the variety-penalty flip), parser fallback
(garbage model output becomes a stated low-confidence default, never a
crash), the Ask-surface intent guardrails, and the feedback path
(validation, atomic append in the committed file style, and the
same-process reindex that makes a new entry retrievable without a
restart). Fixtures in unit tests are normal engineering; the no-replay
honesty rule applies to the agent runtime.

## Provenance and honesty

Committed sample traces are real runs. Each trace's run summary names its
provider: the headline samples come from `claude-sdk`, plus labeled
`ollama` traces for S1, S3, S4 and S5 as proof of the free path (the
weekly S2 on the local model is a long CPU burn and is run separately).
Simulated failures are stamped on every line. The Week-3 demo in
`docs/week3/` replays its committed LLM outputs (it says so in its own
output), which is different from the live agent runs here.
`eval/results.md` cites the exact trace file behind every number. How the
design evolved across the six checkpoints, reversals included, is written
up in [`docs/development_history.md`](docs/development_history.md).

## Future work

Google Calendar / CalDAV sync (today: bring an .ics), a real routing API
behind the travel-matrix seam, per-site weather, an air-quality gate
(Open-Meteo's AQI endpoint drops into the same polite wrapper; today the
gate covers rain, temperature and wind), and RRULE expansion.

## License

MIT, see [LICENSE](LICENSE).

---

<sub>Written with Claude Code as a pair programmer; the design and the
decisions are the author's.</sub>
