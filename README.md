# Excursion Agent

Excursion Agent is a personal planner for the hours you're not at home. It reads your calendar
to find free windows, checks real weather, live bird sightings, city event
permits, tides and subway alerts, remembers how your past outings actually
went, and tells you what's worth doing with a free morning. The idea is to optimize for happiness over time,
where personal feedback makes it tailored to you and better.
You can also ask for a whole week and it runs a Tree-of-Thought search that knows three birding trips in
one week is a worse week than birding plus a hike plus a museum, even when
the raw scores add to less.

Free time often gets spent by default instead of on
purpose. Generic recommenders (such as asking Claude/ChatGPT or Google search for generic things to do) don't know you've already seen the warblers
at Prospect Park, that Jamaica Bay is miserable at midday, or that the B
train is down this weekend. This agent plans from your own feedback and
today's conditions, and shows the evidence behind every suggestion.

## Quickstart: free, no account, no API key

```
ollama pull llama3.1:8b     # after installing Ollama from https://ollama.com
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python demo.py
```

The example env file already points at the local
model, and everything else has a working default. The Ollama
server must be running when you plan. The desktop app keeps it running in
the background; if you installed the bare CLI (Homebrew), start it with
`ollama serve` in another terminal first (or `brew services start ollama`
to make it automatic). The startup probe tells you if it can't connect.

Keep in mind the local model is noticeably
weaker than the committed Claude-produced samples.

The live data sources need network connectivity to work.

### Personalizing it (all optional)

- **Better output with Claude.** Set `LLM_PROVIDER=claude-sdk` in `.env`
  if you have a Claude subscription with Claude Code installed. One-time
  setup: run
  `.venv/lib/python*/site-packages/claude_agent_sdk/_bundled/claude setup-token`
  and paste the printed token into `.env` as `CLAUDE_CODE_OAUTH_TOKEN=`.
  This uses your plan's included Agent SDK allowance to run Excursion Agent.
- **Your location.** `HOME_LAT` and `HOME_LON` in `.env`. The default is
  an approximate Brooklyn centroid, not anyone's address (see Privacy).
  It drives weather and bird-radius queries.
- **Your birds.** A free `EBIRD_API_KEY` (ebird.org/api/keygen) can be used for
  live eBird sightings and the bird lifer bonus (scenario S4). Without it the
  nature agent runs on iNaturalist alone. Point `--life-list` at your own eBird-style CSV.
- **Your calendar.** Export a real calendar and run
  `python demo.py --calendar path/to/your.ics`. From Google Calendar:
  Settings, then Import & export, then Export (unzip and use your
  calendar's .ics). From Apple Calendar: select a calendar, then File,
  then Export. Hard events block time. Events marked tentative or
  optional stay plannable but have a
  score penalty. Live Google Calendar sync will be added in the future. Without your own file, the committed synthetic sample calendar is used.
  This is regenerated automatically whenever it becomes stale.
- **Your feedback.** Every suggestion card has
  **Pass** (with a quick reason why) and, after you take a trip, **Log this
  trip** with a 1-10 rating and a note. The Day tab's **Log an outing**
  covers trips the agent never suggested, and the accept dialog offers an
  optional note after a calendar write. All of it appends to
  `data/excursions.json` and will be used for future agent runs.

### The UI

```
uvicorn src.api.app:app --host 127.0.0.1 --port 8000     # backend
cd ui && npm ci && npm run dev                            # http://localhost:5173
```

**Ask** You can type "what should I do Saturday
morning?" and an intent guardrail (deterministic parsing first, one
validated LLM call only for unclear text) picks the day, refuses anything
outside the 16-day weather forecast horizon, and asks back when the request is
ambiguous; the run then streams live as an orchestration diagram. **Day plan** shows the top 3 suggestions per free window: score breakdown, confidence badge, evidence, lifer badge, weather-gate flags, Add to calendar behind a confirm,
and Pass and Log this trip. **Week
plan** shows the winning set of suggestions for the week, two collapsed alternates, the critic's
penalties, and the naive-vs-ToT comparison. **Add week to calendar**:
confirming writes every pick for the week to the calendar. **Runs** renders any trace as the flow diagram plus an expandable timeline, including each agent's complete structured output (`agent_report` records). 

Switching models between local and Claude and Light vs Dark theme are also pickable in the top right.

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
  ┌─────────────────────────────┐              final_score
  │ tools:
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

### The agents

| agent | kind | role | where |
|---|---|---|---|
| nature | LLM, shared rubric | scores birding/hike/kayak sites from eBird, iNaturalist, tides, weather, memory | [`src/agents/domain_agents.py`](src/agents/domain_agents.py) |
| outdoor events | LLM, shared rubric | scores permitted city events from the live feed, weather, memory | same file|
| indoor | LLM, shared rubric | scores museums/venues from hours, transit, memory | same file |
| weekly critic | LLM | re-scores partial week sets for variety, walking, transit fatigue | [`src/orchestration/tot_beam.py`](src/orchestration/tot_beam.py) |
| supervisor | code, deterministic | runs the waterfall, fans out the agents, owns the beam loop and every validator | [`src/orchestration/`](src/orchestration/) |
| intent guardrail | code first, LLM fallback | turns free text into a validated day/week request, refuses out-of-horizon dates | [`src/agents/intent.py`](src/agents/intent.py) |

### Demo Scenarios
Other than running the full Excursion Agent, can run a few scenarios with demo.py from the command line python demo.py.

## Future work (improving on limitations)

Google Calendar sync, 
per-site weather (currently it is per-county more general)
an air-quality gate

## License

MIT, see [LICENSE](LICENSE).

---

<sub>Coded using Claude Code as a pair programmer. The design and the
decisions are the author's.</sub>
