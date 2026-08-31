# How it developed

This is the honest build story across the six checkpoints, written from
the commit history and the decisions that actually got made, including
the ones that reversed earlier plans. The through line: every pivot moved
the system toward being honest under live data.

## Weeks 1 and 2: the shape of the problem

The concept started as a personal assistant for a specific, real problem:
free time gets spent by default instead of on purpose. Week 1 committed
to the sources that a prompt-only model cannot have (weather, eBird and
iNaturalist, city events, transit, my calendar, my own trip history) and
to a feedback loop where I accept or reject suggestions with a reason and
rate finished trips 1 to 10. Week 2 turned that into a reasoning loop: a
waterfall that spends nothing on times the calendar already blocks,
gates outdoor categories on extreme weather before any expensive call,
runs the scoring agents only on what survives, and applies transit last
because a subway alert can quietly break an otherwise perfect plan. Two
ideas from these weeks survived every later refactor: cheapest checks
first, and hard versus soft calendar conflicts read from language rather
than a rigid schema.

## Week 3: the retrieval layer, and the first real reversal

The memory layer was built standalone first (it is the initial commit of
this repo). The first version used a metadata pre-filter: only entries
matching the query's season and activity type could reach the ranker,
with a 0.45 similarity cutoff. Testing against the corpus showed the
filtered bucket could be thin, and the calibration margin was a knife
edge of 0.027. So the design reversed: no pre-filter at all, semantic
search over the whole corpus, top 7 re-ranked by a composite of
similarity, season proximity, type match and recency, top 3 returned.
That reversal had a measurable cost and payoff. The usable calibration
gap widened from 0.027 to 0.193, but the cutoff became the only guard
against a cold start being answered from the wrong notes, and
recalibration caught exactly that failure: a kayaking-adjacent request
with no history matched an unrelated note at 0.472, which is why the
cutoff moved to 0.55. Two smaller decisions from this week also stuck:
one feedback entry is one vector-store node (chunking would split "went
midday" from "packed with people", which is the whole lesson), and the
store's exp(-distance) scores are inverted back to real cosine so the
cutoff stays a number a person can argue with.

## Week 4: the week is not the sum of its days

The Tree-of-Thought design came from a concrete observation: picking
each day's top scorer builds weeks like museum, museum, museum. A thought
became "add one excursion to the partial week", searched with beam width
4 to depth 7, with an LLM critic re-scoring each partial set for variety,
weekly walking load and transit fatigue. Building it forced decisions the
writeup never had to face: beam nodes became frozen dataclasses expanded
by replacement so a parent is structurally impossible to mutate, children
are built from argument-ordered results so async completion order can
never change the answer, and the code recomputes the critic's arithmetic
instead of trusting it (mismatches are logged; the committed run has
zero). Deriving the real call bound also fixed the plan's own math: depth
one expands a single root, so the bound is 3 + 12(D-1) = 75, not the 84 a
naive width-times-branching estimate gives. The naive rank-by-sum
baseline costs zero extra calls because it is computed from the same
daily lists in code, which is what lets the evaluation assert the
contrast instead of describing it.

## Week 5: five agents and one rubric

The multi-agent split settled at exactly five: three domain scorers
(nature, outdoor events, indoor), the weekly critic, and a supervisor
that is deliberately plain code. The week's hardest question was rubric
drift: parallel specialists could quietly grade at different strictness
and one domain would always win. The answer was structural rather than
hopeful: a single 1 to 10 anchor block is injected verbatim into all
three prompts, only the few-shot examples translating "a 9" into each
domain's terms differ, and every post-score adjustment is code-side and
identical. The other durable Week 5 decision: agents do not call tools.
The supervisor pre-fetches everything through one polite wrapper and
hands each agent an evidence pack, which is what makes rate limiting
enforceable and lets each call's schema restrict citations to evidence
that actually exists.

## Week 6: safety became the architecture

The safety plan turned into the parts of the system that now do the most
work. Zero usable windows became a typed escalation that stops and asks.
Groundedness became a two-layer enforcement: the per-call schema types
evidence ids as a literal enum of what was fetched this run, and a
validator re-checks membership afterward, with the metric counting
everything emitted before stripping so 100% means something. The
"regex and sentiment" idea became the self-report scan, which promptly
produced its own lesson: it flagged "no errors or missing coverage" as
trouble, so it grew a negation guard, and a later audit hardened that
guard again. Secrets redaction went in at three exits (logging, stdout
and stderr, the exception hook) because a public repo was always the
destination. And the trajectory log stopped being a debugging aid and
became the single source of truth: the evaluation reads only trace
records, and the UI's run view reads the same file.

## Assembly: where the plan met reality

The capstone build (24 commits, each phase gated by tests) forced the
last set of honest changes.

The provider story changed twice. The original stack line named the
metered Claude API through LangChain. First the Agent SDK path was added
so development runs bill a subscription instead of per-token credits,
with a guard that refuses to run if an API key would silently shadow
that auth. Then, at the dependency review gate, the metered path was
dropped entirely as a cost decision: reviewers run free on Ollama or on
a subscription they already have. Later the UI gained a per-run switch
between the two, with every trace recording the provider that actually
ran.

Live data kept teaching. Open-Meteo had a real outage during development
(an error string inside an HTTP 200), which validated the whole fallback
chain unplanned: the run completed on stated low confidence, the trace
recorded the failure, and the plan carried a degraded-sources notice. It
also earned the fetch layer a bounded retry for exactly that failure
shape. The lifer feature went through the most versions: a toy species
list made everything a lifer, a realistic 150-species list still left 72
"lifers" stamped identically on every card (a flat metro-wide list, a
real bug), and the final design scopes lifers to each site's own region
against a list reseeded from live observations, deliberately missing two
seasonally common shorebirds so the bonus is small, named and checkable.

The feedback loop closed last, and honestly. An audit against the Week 1
writeup showed the promised accept/reject-with-reason and post-trip
ratings had no surface: the design existed, the product did not. That
became the gated feedback endpoint and the Pass, Log this trip and
Log an outing controls, plus a fix deep in the memory layer (the vector
store caches its client per process, so rebuilds now go through that
same client) proven by saving a real decision through the UI and
watching an agent cite it minutes later in the same server process.

The interface followed the same arc: it began as the spec's three plain
tabs, then real usage kept promoting it. Asking in natural language
needed an intent guardrail, and a real bug ("plan the week of september
7th" silently anchored to the current week) hardened that guardrail into
a rule: the deterministic parser must refuse to answer whenever it did
not consume the whole date phrase. Live runs needed progress a person
can watch, so the orchestration diagram renders only states the trace
records prove. And the test fixtures (simulated failures, the fully
blocked calendar) stayed committed for the guardrail story but moved off
the demo surface, because a demo that ambushes you with staged errors
teaches the wrong lesson about a system whose real failures are already
logged honestly.
