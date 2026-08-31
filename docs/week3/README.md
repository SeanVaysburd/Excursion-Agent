# Excursion agent, semantic memory layer

Capstone checkpoint. This implements **only** the long-term memory layer of a
personal excursion-planning agent: the free-text notes from past outings,
which can only be queried semantically.

The agent's other inputs, weather, eBird, transit, calendar, are structured
API calls. They are not retrieval and are not in scope here.

## Run it

This checkpoint now lives inside the full capstone repo; run its scripts as
modules from the repo root (path-invoked scripts cannot see `src.*`):

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m scripts.week3.memory_demo --rebuild
```

All local. No API keys. The first run downloads the all-MiniLM-L6-v2 weights
(~90 MB) from the HuggingFace hub; after that it works offline.

Other flags:

```bash
python -m scripts.week3.memory_demo --emit-prompts   # write prompts to docs/week3/prompts/
python -m scripts.week3.memory_demo --llm            # also show the saved Claude completions
python -m scripts.week3.calibrate                    # re-derive the similarity cutoff
```

## Files (migrated layout)

| file | what it is |
| --- | --- |
| `data/excursions.json` | the 20 synthetic entries (repo root; the live agent shares this corpus, and feedback saved through the app appends to it tagged `"source": "user"`) |
| `src/memory/retrieval.py` | the retrieval layer, documents, index, re-ranking, cutoff (imported by the live agent AND these scripts) |
| `scripts/week3/recommend.py` | rule-based planner stand-in, with and without memory |
| `scripts/week3/planner_prompt.py` | the prompts a real planner LLM would receive |
| `scripts/week3/memory_demo.py` | the three scenarios and their traces |
| `scripts/week3/calibrate.py` | evidence for the similarity cutoff; run when data changes |
| `docs/week3/prompts/` | emitted planner prompts, one per scenario per condition |
| `docs/week3/llm_output/` | Claude's answers to those prompts (see *Provenance*) |
| `docs/week3/expected_demo_output.txt` | the committed demo output; `tests/test_week3_regression.py` diffs the deterministic blocks against it |

## Pipeline

```
data/excursions.json
  → one llama_index Document per entry
      body:     the notes text
      metadata: entry_id, date, season, type, site, rating
  → HuggingFaceEmbedding(all-MiniLM-L6-v2), local
  → SentenceSplitter(chunk_size=1024), sized so it never fires;
    parse_nodes() raises if an entry is ever split
  → ChromaVectorStore, persistent, cosine space → VectorStoreIndex
  → VectorIndexRetriever(similarity_top_k=7) over the WHOLE corpus
  → SimilarityPostprocessor(similarity_cutoff=0.55)      ← stage 1
  → composite re-rank of the survivors                   ← stage 2
  → top 3                                                ← stage 3
```

There is **no metadata pre-filter**. Season and activity type are inputs to
the re-ranking score rather than hard gates, so a strong match in an adjacent
season can still surface.

## Re-ranking

```
composite = 0.60·similarity + 0.15·season + 0.15·type + 0.10·recency
```

- **season**, 1.0 same, 0.5 adjacent, 0.0 opposite. Seasons are a cycle, so
  winter is adjacent to spring.
- **type**, 1.0 exact match, 0.0 otherwise.
- **recency**, 1.0 for the newest entry in the log, 0.0 for the oldest,
  linear in between. Anchored to the corpus rather than to `date.today()` so
  the demo is reproducible; swap the anchor if you want real-time decay.

**Order matters.** The cutoff is applied to raw cosine *before* re-ranking.
If it ran afterwards, a recency or season bonus could lift an irrelevant note
over the bar, and the threshold would stop meaning anything.

## Three decisions worth defending

**One entry, one node.** Entries are one to three sentences and are already
the natural semantic unit. Chunking would separate "went midday" from "packed
with people", which is the entire lesson of entry `e02`.

**Scores are converted back to real cosine similarity.** The Chroma
integration returns `exp(-distance)`, which ranks correctly but is not a
similarity anyone can reason about, orthogonal vectors score 0.37, not 0.
`exp` is invertible, so `to_cosine()` recovers `1 + ln(score)` exactly.
`calibrate.py` step 1 checks this against cosine computed straight from the
embedding model; the delta is 0.000000.

**The cutoff is measured, not guessed.** `calibrate.py` prints three bands:

| band | range |
| --- | --- |
| genuine history for the request | 0.665 .. 0.820 |
| real outing, nothing in the log about it | 0.418 .. 0.472 |
| unrelated text | 0.051 .. 0.304 |

0.55 sits inside the gap: 0.078 above band 2, 0.115 below band 1.
`calibrate.py` distinguishes *unseparable* bands from a merely *misplaced*
cutoff, and tells you where to move it.

## What removing the pre-filter actually cost and bought

Dropping the metadata filter was not free, and the numbers moved in both
directions.

**It bought a wider margin.** Band 1 is now measured over the whole corpus
instead of inside a possibly-thin filtered bucket, so its floor rose from
0.470 to 0.665. The usable gap went from **0.027 to 0.193**, the old cutoff
was balanced on a knife edge that no longer exists.

**It cost the free relevance guarantee.** The filter used to make topical
relevance structural: nothing outside the right season and activity could
reach the ranker at all. Now the cutoff is the *only* guard. Calibration
caught this immediately, at the old 0.45 threshold, a **cycling** request
with no history matched a Governors Island note at 0.472 and would have been
served as though it were relevant experience. That false positive is what
moved the cutoff to 0.55.

## The recency weight has a sharp edge

Look at stage 2 of scenario 1:

| entry | cos | recency | composite | |
| --- | --- | --- | --- | --- |
| `e07` | 0.579 | 0.95 | **0.742** | Central Park Ramble, 5/10, *different site* |
| `e01` | 0.726 | 0.00 | 0.735 | Jamaica Bay, **9/10**, the early-start exemplar |

`e01` is the best single piece of evidence for this query, same site, same
season, rated 9/10, and the trip the user's own notes describe as the pattern
that works. It is excluded from the top 3, and a mediocre trip to a different
park takes its place, because `e01` happens to be the oldest entry in the log.

The arithmetic: recency swings 0.095 across its full range (weight 0.10),
which is enough to overturn a 0.147 cosine gap (worth 0.088 at weight 0.60).
**Any entry can be outranked by a less relevant one that is merely newer.**

This is a property of the specified weights, not a bug. Dropping recency to
0.05 restores `e01` to the top 3 while leaving the rest of the ordering
intact. Worth deciding deliberately rather than inheriting.

## What the demo shows

**Scenario 1**, mid-May Saturday, free 06:00-14:00, birding at Jamaica Bay.
Seven candidates, three dropped by the cutoff, four re-ranked. Re-ranking
changes the order from `e02 > e01 > e19 > e07` to `e19 > e02 > e07 > e01`.
The recommendation moves from a generic 08:00-12:00 to **06:00-09:30**.

**Scenarios 2 and 3**, kayaking, and a Catskills overnight backpacking trip.
Both cold-start, and now by the *same* mechanism: every candidate falls below
the cutoff (best 0.443 and 0.418), nothing reaches re-ranking, and the agent
falls back to the unpersonalized plan. They remain worth keeping as two
different *kinds* of cold start, an activity with no history at all, versus
a logged activity type used for a genuinely different kind of outing, but
under this design the code path is identical. (Under the previous
filter-based design these two were caught by different guards.)

## The result that complicates the story

Run `python demo.py --llm` and compare `s1_a` (no memory) with `s1_b` (memory).

**The LLM baseline already says "go early."** With no memory at all, Claude
recommends 06:00-10:00 for spring birding, because "passerine activity peaks
in the first hours after sunrise" is general ornithological knowledge. It does
not need your notes to work that out.

So the honest claim is *not* "retrieval fixes the timing." Against a competent
baseline it doesn't. What retrieval changes is the **specificity and the
confidence**: a concrete stop time drawn from a real trip, the site's actual
failure mode, and grounded citations in place of "I have no history for you."

The baseline hedged about **tides**, reasonable for a coastal refuge, and
wrong here: across the logged Jamaica Bay trips the thing that actually ruins
the morning is *crowds*. Retrieval replaced a plausible generic caution with
the observed one.

**Note that the rule-based baseline in `recommend.py` overstates the delta** -
it starts from a naive mid-window default, so the shift to 06:00 looks
dramatic. The LLM baseline is the stronger control, and the delta against
*that* is the real measure of what this retrieval layer buys.

## Provenance of the LLM output

`recommend.py` is rule-based: it keyword-matches the retrieved notes so that
`python demo.py` runs anywhere, deterministically, with no key. That is the
default and it is what the traces show.

`llm_output/` holds what a real planner LLM produces from the same retrieved
context. Those files were generated **once**, by Claude, from the prompts in
`prompts/`, they are not produced by running `demo.py`, and `--llm` replays
them rather than calling anything. Each cell was generated in an **isolated
context** that saw only its own prompt file. That isolation is the point: if
one model wrote both the `without retrieval` and `with retrieval` answers, the
baseline would be contaminated by having already read the notes.

## Honest limitations

- **The LLM answers are a fixed artifact, not a live call.** Reproducing them
  means re-running the `prompts/` files through a model yourself.
- **Recency can outrank relevance.** See above.
- **Rating is not in the composite score.** Similarity finds relevant entries;
  nothing in the ranking prefers the *instructive* ones. `e02` (4/10) ranks
  second on merit, it is highly relevant and highly informative, but that is
  the embedding's doing, not the ranker's.
- **Headroom below the cutoff is 0.078**, with no pre-filter behind it.
- **20 synthetic entries.** Every number here should be re-derived on real data.

---

*Note: the corpus notes in `data/excursions.json` were later rewritten into
a more natural personal-log voice (same entries, dates, sites, ratings, and
facts, wording only). The replayed LLM outputs and prompts in this folder
predate that rewrite and quote the original wording; the retrieval traces
and calibration were regenerated against the current text (cutoff 0.55
re-verified, margin noted in `calibrate.py` output).*
