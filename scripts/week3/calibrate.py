"""
Sanity-check for the similarity scale, and the evidence behind the cutoff.

Three jobs:

1. Verify that to_cosine() really recovers cosine similarity, by comparing
   what comes back through Chroma against cosine computed directly from the
   embedding model.
2. Print the score bands that SIMILARITY_CUTOFF sits between.
3. Report the margin.

Job 3 matters more than it used to. There is no metadata pre-filter any more,
so this cutoff is the only thing separating "no relevant history" from a
confident answer built on the wrong notes. Run this whenever the corpus or
the embedding model changes, and move the cutoff if the bands have moved.

    python calibrate.py
"""

from __future__ import annotations

import numpy as np
from llama_index.core import Settings
from llama_index.core.retrievers import VectorIndexRetriever

from src.memory.retrieval import SIMILARITY_CUTOFF, ExcursionMemory, PlanningContext, to_cosine


def ctx(season, activity, site, tod="morning", dow="Saturday", window="06:00-14:00"):
    return PlanningContext(
        label=f"{season}/{activity}/{site}",
        season=season,
        activity_type=activity,
        site=site,
        time_of_day=tod,
        day_of_week=dow,
        window=window,
    )


# Band 1: a real planning request that has real history behind it.
GENUINE = [
    ctx("spring", "birding", "Jamaica Bay Wildlife Refuge"),
    ctx("spring", "birding", "Marine Park Salt Marsh", tod="afternoon"),
    ctx("spring", "hike", "Harriman State Park"),
    ctx("winter", "museum", "The Met", tod="afternoon"),
    ctx("winter", "museum", "American Museum of Natural History"),
    ctx("fall", "outdoor_event", "Queens Night Market", tod="evening"),
    ctx("fall", "hike", "Palisades Interstate Park"),
    ctx("summer", "birding", "Marine Park Salt Marsh"),
]

# Band 2: a real outing the log has nothing to say about. With the pre-filter
# gone, these reach the ranker on similarity alone, the cutoff is all that
# stops a hike note being served as kayaking experience.
NO_HISTORY = [
    ctx("summer", "kayaking", "Sebago Canoe Club", window="08:00-13:00"),
    ctx("winter", "ice_skating", "Bryant Park", window="10:00-15:00"),
    ctx("fall", "hike", "Catskills overnight backpacking trip", tod="overnight"),
    ctx("spring", "cycling", "Rockaway boardwalk", window="07:00-12:00"),
]

# Band 3: text that has no business matching anything in the log.
UNRELATED = [
    "debugging a python import error",
    "dentist appointment logistics",
    "best pizza slice in Bushwick",
    "quarterly revenue forecast spreadsheet",
]


def main() -> None:
    memory = ExcursionMemory.build()
    embed = Settings.embed_model

    # ---------------------------------------------------------------- 1
    print("=" * 78)
    print("1. does to_cosine() recover cosine similarity?")
    print("=" * 78)

    probe = GENUINE[0]
    result = memory.retrieve(probe, cutoff=-1.0)  # cutoff off, keep everything
    q_vec = np.array(embed.get_query_embedding(result.query))

    print(f"{'entry':<8}{'via chroma':>13}{'direct cosine':>16}{'delta':>10}")
    for c in result.candidates[:3]:
        stored = memory.collection.get(ids=[c.node.node_id], include=["embeddings"])
        d_vec = np.array(stored["embeddings"][0])
        direct = float(q_vec @ d_vec / (np.linalg.norm(q_vec) * np.linalg.norm(d_vec)))
        print(
            f"{c.entry_id:<8}{c.similarity:>13.4f}{direct:>16.4f}"
            f"{abs(c.similarity - direct):>10.6f}"
        )

    # ---------------------------------------------------------------- 2
    print()
    print("=" * 78)
    print(f"2. score bands (cutoff currently {SIMILARITY_CUTOFF})")
    print("=" * 78)

    band_1: list[float] = []
    print("\n  band 1, genuine history for the request")
    for probe in GENUINE:
        res = memory.retrieve(probe, cutoff=-1.0)
        best = res.candidates[0].similarity
        band_1.append(best)
        print(f"    {best:.3f}   {probe.season:<7}{probe.activity_type:<14}{probe.site}")

    band_2: list[float] = []
    print("\n  band 2, real outing, nothing in the log about it")
    for probe in NO_HISTORY:
        res = memory.retrieve(probe, cutoff=-1.0)
        best = res.candidates[0]
        band_2.append(best.similarity)
        print(
            f"    {best.similarity:.3f}   {probe.season:<7}"
            f"{probe.activity_type:<14}nearest was {best.entry_id} "
            f"({best.metadata['type']})"
        )

    band_3: list[float] = []
    print("\n  band 3, unrelated text")
    for text in UNRELATED:
        nodes = VectorIndexRetriever(index=memory.index, similarity_top_k=1).retrieve(
            text
        )
        best = to_cosine(nodes[0].score)
        band_3.append(best)
        print(f"    {best:.3f}   {text}")

    # ---------------------------------------------------------------- 3
    print()
    print("=" * 78)
    print("3. is the cutoff in the right place?")
    print("=" * 78)
    print()
    for name, band in (
        ("1  genuine history ", band_1),
        ("2  no history      ", band_2),
        ("3  unrelated text  ", band_3),
    ):
        print(f"  band {name}  {min(band):+.3f} .. {max(band):+.3f}")

    gap_lo, gap_hi = max(band_2), min(band_1)
    margin = gap_hi - gap_lo
    print()
    if gap_lo < SIMILARITY_CUTOFF < gap_hi:
        print(
            f"  OK: cutoff {SIMILARITY_CUTOFF:.2f} separates band 2 "
            f"(<= {gap_lo:.3f}) from band 1 (>= {gap_hi:.3f})."
        )
        print(f"  Margin is {margin:.3f}.")
        print()
        print(
            f"  Headroom below the cutoff is only "
            f"{SIMILARITY_CUTOFF - gap_lo:.3f}. With no metadata pre-filter"
        )
        print("  behind it, that is the whole safety margin. Watch it.")
    elif gap_lo >= gap_hi:
        print(
            f"  UNSEPARABLE: bands 1 and 2 overlap (band 2 reaches {gap_lo:.3f}, "
            f"band 1 starts at {gap_hi:.3f})."
        )
        print("  No cutoff can split them. The query or the corpus needs work.")
    else:
        print(
            f"  MISPLACED: the bands are cleanly separated ({gap_lo:.3f} .. "
            f"{gap_hi:.3f}, a gap of {margin:.3f}),"
        )
        print(f"  but the cutoff {SIMILARITY_CUTOFF:.2f} is not inside that gap.")
        print(f"  Move it to about {(gap_lo + gap_hi) / 2:.2f}.")


if __name__ == "__main__":
    main()
