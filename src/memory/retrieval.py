"""
Long-term memory for the excursion-planning agent.

This is the ONLY retrieval component in the agent. The structured feeds it
also uses -- weather, eBird, transit, calendar -- are ordinary API calls and
have no place here. What lives here is the part that is free text and can
only be queried semantically: the user's own notes on past excursions.

Pipeline
    data/excursions.json
      -> one llama_index Document per entry (notes in the body, the rest in
         metadata)
      -> HuggingFaceEmbedding(all-MiniLM-L6-v2), local, no API key
      -> node parser sized so one Document stays exactly one node
      -> ChromaVectorStore (persistent) wrapped in a VectorStoreIndex
      -> VectorIndexRetriever(similarity_top_k=7) over the WHOLE corpus
      -> SimilarityPostprocessor(similarity_cutoff) drops weak matches
      -> composite re-rank (similarity + season + type + recency)
      -> top 3

There is no metadata pre-filter. Season and activity type are inputs to the
re-ranking score rather than hard gates, so a strong match in an adjacent
season can still surface. The cost of that choice is that the similarity
cutoff is now the only thing standing between a cold start and a confidently
wrong answer -- see SIMILARITY_CUTOFF below.
"""

from __future__ import annotations

import hashlib
import json
import math
import shutil
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import chromadb

# Importing config FIRST is load-bearing: it pins LLAMA_INDEX_CACHE_DIR (and
# offline mode when the weights are already cached) before any model load.
from src import config
from llama_index.core import Settings, StorageContext, VectorStoreIndex
from llama_index.core.llms import MockLLM
from llama_index.core.node_parser import SentenceSplitter
from llama_index.core.postprocessor import SimilarityPostprocessor
from llama_index.core.retrievers import VectorIndexRetriever
from llama_index.core.schema import Document, NodeWithScore
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from llama_index.vector_stores.chroma import ChromaVectorStore

ROOT = Path(__file__).resolve().parents[2]  # src/memory/ -> repo root
DATA_PATH = ROOT / "data" / "excursions.json"
PERSIST_DIR = ROOT / "storage" / "chroma"
CORPUS_HASH_PATH = ROOT / "storage" / "corpus.sha256"
COLLECTION_NAME = "excursion_memory"

EMBED_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

CANDIDATE_K = 7  # pulled from the vector store, before re-ranking
TOP_K = 3  # returned to the planner, after re-ranking

# Cosine similarity, so the number means something you can argue about.
# Measured on this corpus (run calibrate.py to reproduce):
#
#   genuine history for the request .............. 0.665 .. 0.820
#   real outing, nothing in the log about it
#     (kayaking, ice-skating, cycling, overnight
#     backpacking) ............................... 0.418 .. 0.472
#   unrelated text ("debugging a python import
#     error", "best pizza in Bushwick") .......... 0.051 .. 0.304
#
# This moved when the metadata pre-filter was removed, and it moved in a
# useful direction. Band 1 is now measured over the whole corpus instead of
# inside a possibly-thin filtered bucket, so its floor rose from 0.470 to
# 0.665 and the gap widened from 0.027 to 0.193.
#
# 0.45 no longer works: a cycling request with no history matches a Governors
# Island note at 0.472 and would have been answered as though that were
# relevant experience. 0.55 sits inside the real gap, 0.078 above band 2 and
# 0.115 below band 1.
#
# With the pre-filter gone this cutoff is the ONLY guard against a cold start
# being answered from the wrong notes. Re-run calibrate.py on real data.
# Single source of truth is src/config.py; re-exported here because the
# Week-3 scripts (and the calibration evidence) import it from this module.
SIMILARITY_CUTOFF = config.SIMILARITY_CUTOFF

# Composite re-ranking. Similarity dominates -- the other three are nudges
# that break ties and pull the genuinely comparable outing above the merely
# similarly-worded one. They deliberately do not sum to enough to rescue
# something the embedding thought was irrelevant.
WEIGHTS = {
    "similarity": 0.60,
    "season": 0.15,
    "type": 0.15,
    "recency": 0.10,
}

SEASON_CYCLE = ("spring", "summer", "fall", "winter")

# Ratings are 1-10. Used to sort retrieved history into "worked" / "did not".
GOOD_RATING = 7
BAD_RATING = 5


# --------------------------------------------------------------------------
# Similarity bookkeeping
# --------------------------------------------------------------------------
def to_cosine(store_score: float) -> float:
    """Convert a ChromaVectorStore score back to plain cosine similarity.

    The collection is created with hnsw:space=cosine, so Chroma returns
    distance = 1 - cosine_similarity. llama-index's ChromaVectorStore then
    hands back exp(-distance), which ranks correctly but is not a similarity
    anyone can reason about -- two orthogonal vectors score 0.37, not 0.

    exp() is invertible, so nothing is lost: cosine = 1 + ln(score). Scores
    are normalised at retrieval time and the cutoff is applied afterwards,
    which keeps SIMILARITY_CUTOFF readable as "cosine similarity".
    """
    if store_score <= 0.0:
        return -1.0
    return 1.0 + math.log(store_score)


# --------------------------------------------------------------------------
# Re-ranking components
# --------------------------------------------------------------------------
def season_proximity(query_season: str, entry_season: str) -> float:
    """1.0 same season, 0.5 adjacent, 0.0 opposite.

    Seasons are a cycle, not a line: winter is adjacent to spring.
    """
    if query_season not in SEASON_CYCLE or entry_season not in SEASON_CYCLE:
        return 0.0
    i, j = SEASON_CYCLE.index(query_season), SEASON_CYCLE.index(entry_season)
    distance = min((i - j) % 4, (j - i) % 4)  # 0, 1 or 2
    return 1.0 - distance / 2.0


def type_match(query_type: str, entry_type: str) -> float:
    return 1.0 if query_type == entry_type else 0.0


def recency(entry_date: str, oldest: date, newest: date) -> float:
    """1.0 for the newest entry in the log, 0.0 for the oldest.

    Anchored to the corpus rather than to today's date, so the demo produces
    the same numbers whenever it is run. Anchor it to date.today() if you
    want recency to decay in real time.
    """
    span = (newest - oldest).days
    if span <= 0:
        return 1.0
    d = date.fromisoformat(entry_date)
    return 1.0 - (newest - d).days / span


# --------------------------------------------------------------------------
# Planning context -> query string
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class PlanningContext:
    """What the planner knows before it consults memory."""

    label: str  # human-readable scenario name, for the trace
    season: str
    activity_type: str
    site: str
    time_of_day: str
    day_of_week: str
    window: str  # free time, e.g. "06:00-14:00"
    date_label: str = ""  # e.g. "Saturday, 16 May 2026"; display only

    def build_query(self) -> str:
        """Flatten the context into the string that gets embedded.

        Written as a question about outcomes rather than a bag of keywords:
        the entries are outcome notes, so the query embeds closer to them
        when it is phrased the same way.
        """
        activity = self.activity_type.replace("_", " ")
        return (
            f"{self.season} {activity} trip to {self.site}, "
            f"{self.day_of_week} {self.time_of_day}. "
            f"How did past trips like this go -- timing, crowds, conditions, "
            f"and what made them good or bad?"
        )


# --------------------------------------------------------------------------
# A scored candidate
# --------------------------------------------------------------------------
@dataclass
class RankedCandidate:
    """One retrieved entry with its similarity and its re-ranking components."""

    node: NodeWithScore
    similarity: float
    season: float
    type_match: float
    recency: float
    composite: float
    passed_cutoff: bool

    @property
    def entry_id(self) -> str:
        return self.node.metadata["entry_id"]

    @property
    def metadata(self) -> dict:
        return self.node.metadata

    @property
    def score(self) -> float:
        """Alias so callers that expect a NodeWithScore keep working."""
        return self.similarity

    def get_content(self) -> str:
        return self.node.get_content()


# --------------------------------------------------------------------------
# Retrieval result
# --------------------------------------------------------------------------
@dataclass
class RetrievalResult:
    """Everything the trace needs to show what memory did and why."""

    context: PlanningContext
    query: str
    corpus_size: int
    candidates: list[RankedCandidate] = field(default_factory=list)  # all K, by sim
    ranked: list[RankedCandidate] = field(default_factory=list)  # survivors, by composite
    kept: list[RankedCandidate] = field(default_factory=list)  # top N after re-rank
    cutoff: float = SIMILARITY_CUTOFF

    @property
    def has_history(self) -> bool:
        return bool(self.kept)

    @property
    def dropped(self) -> list[RankedCandidate]:
        return [c for c in self.candidates if not c.passed_cutoff]

    @property
    def cold_start_reason(self) -> str:
        if self.has_history:
            return ""
        if not self.candidates:
            return "the memory store is empty -- nothing to rank"
        best = max(c.similarity for c in self.candidates)
        return (
            f"all {len(self.candidates)} candidates fell below the "
            f"{self.cutoff:.2f} similarity cutoff (best was {best:.3f})"
        )


# --------------------------------------------------------------------------
# The memory itself
# --------------------------------------------------------------------------
class ExcursionMemory:
    """Semantic memory over past excursion feedback."""

    def __init__(self, index: VectorStoreIndex, collection, docs: list[Document]):
        self.index = index
        self.collection = collection
        self.doc_count = len(docs)
        dates = [date.fromisoformat(d.metadata["date"]) for d in docs]
        self.oldest, self.newest = min(dates), max(dates)

    # -- construction ------------------------------------------------------
    @staticmethod
    def configure_settings() -> None:
        Settings.embed_model = HuggingFaceEmbedding(model_name=EMBED_MODEL)

        # No LLM is involved in retrieval. MockLLM is set explicitly so that
        # nothing can quietly fall back to a hosted default and ask for a key.
        Settings.llm = MockLLM()

        # One entry = one node. Entries are one to three sentences and are
        # already the natural semantic unit -- splitting them would separate
        # "went midday" from "packed with people", which is the whole lesson.
        # The splitter is sized so it can never fire; parse_nodes() below
        # asserts that it didn't.
        Settings.node_parser = SentenceSplitter(chunk_size=1024, chunk_overlap=0)

    @staticmethod
    def load_documents() -> list[Document]:
        entries = json.loads(DATA_PATH.read_text())
        docs: list[Document] = []
        for entry in entries:
            docs.append(
                Document(
                    id_=entry["id"],
                    text=entry["notes"],
                    metadata={
                        "entry_id": entry["id"],
                        "date": entry["date"],
                        "season": entry["season"],
                        "type": entry["type"],
                        "site": entry["site"],
                        "rating": entry["rating"],
                    },
                    # Season, type and site are part of what a planning query
                    # asks about, so they stay in the embedded text. The id,
                    # date and rating are for re-ranking and for explaining a
                    # result -- as embedded tokens they are just noise.
                    excluded_embed_metadata_keys=["entry_id", "date", "rating"],
                )
            )
        return docs

    @staticmethod
    def parse_nodes(docs: list[Document]):
        """Run the node parser and hold it to the one-node-per-entry rule."""
        nodes = Settings.node_parser.get_nodes_from_documents(docs)
        if len(nodes) != len(docs):
            raise RuntimeError(
                f"expected one node per entry, got {len(nodes)} nodes from "
                f"{len(docs)} documents -- an entry was chunked"
            )
        return nodes

    @staticmethod
    def corpus_hash() -> str:
        return hashlib.sha256(DATA_PATH.read_bytes()).hexdigest()

    @classmethod
    def build(cls, rebuild: bool = False) -> "ExcursionMemory":
        cls.configure_settings()

        # A count-only check would serve stale entries forever after the
        # corpus changes (and their memory:eNN evidence ids would point at
        # records the run never loaded), so the corpus hash participates in
        # the rebuild decision.
        current_hash = cls.corpus_hash()
        stored_hash = (
            CORPUS_HASH_PATH.read_text().strip()
            if CORPUS_HASH_PATH.exists()
            else None
        )
        if (rebuild or stored_hash != current_hash) and PERSIST_DIR.exists():
            shutil.rmtree(PERSIST_DIR)
        PERSIST_DIR.mkdir(parents=True, exist_ok=True)

        client = chromadb.PersistentClient(path=str(PERSIST_DIR))
        collection = client.get_or_create_collection(
            COLLECTION_NAME,
            # Explicit: the default is L2, and the cutoff is stated in cosine.
            metadata={"hnsw:space": "cosine"},
        )
        vector_store = ChromaVectorStore(chroma_collection=collection)

        docs = cls.load_documents()

        if collection.count() == 0:
            nodes = cls.parse_nodes(docs)
            storage_context = StorageContext.from_defaults(vector_store=vector_store)
            index = VectorStoreIndex(nodes, storage_context=storage_context)
        else:
            # Already persisted and corpus unchanged: reopen, don't re-embed.
            index = VectorStoreIndex.from_vector_store(vector_store)

        CORPUS_HASH_PATH.parent.mkdir(parents=True, exist_ok=True)
        CORPUS_HASH_PATH.write_text(current_hash + "\n")

        return cls(index=index, collection=collection, docs=docs)

    # -- retrieval ---------------------------------------------------------
    def _score(self, ctx: PlanningContext, node: NodeWithScore) -> RankedCandidate:
        md = node.metadata
        similarity = node.score or 0.0
        s_season = season_proximity(ctx.season, md["season"])
        s_type = type_match(ctx.activity_type, md["type"])
        s_recency = recency(md["date"], self.oldest, self.newest)

        composite = (
            WEIGHTS["similarity"] * similarity
            + WEIGHTS["season"] * s_season
            + WEIGHTS["type"] * s_type
            + WEIGHTS["recency"] * s_recency
        )
        return RankedCandidate(
            node=node,
            similarity=similarity,
            season=s_season,
            type_match=s_type,
            recency=s_recency,
            composite=composite,
            passed_cutoff=similarity >= SIMILARITY_CUTOFF,
        )

    def retrieve(
        self,
        ctx: PlanningContext,
        candidate_k: int = CANDIDATE_K,
        top_k: int = TOP_K,
        cutoff: float = SIMILARITY_CUTOFF,
    ) -> RetrievalResult:
        """Search the whole corpus, drop weak matches, re-rank, return top N.

        Order matters. The cutoff is applied to raw cosine similarity BEFORE
        re-ranking, because that is the space it was calibrated in -- letting
        a recency or season bonus lift an irrelevant note over the bar would
        make the threshold meaningless.
        """
        query = ctx.build_query()
        nodes = VectorIndexRetriever(
            index=self.index, similarity_top_k=candidate_k
        ).retrieve(query)

        for node in nodes:
            node.score = to_cosine(node.score or 0.0)

        # SimilarityPostprocessor does the dropping; the candidate list keeps
        # everything so the trace can show what was thrown away and why.
        survivors = {
            n.node_id
            for n in SimilarityPostprocessor(
                similarity_cutoff=cutoff
            ).postprocess_nodes(nodes)
        }

        candidates = []
        for node in nodes:
            candidate = self._score(ctx, node)
            candidate.passed_cutoff = node.node_id in survivors
            candidates.append(candidate)

        ranked = sorted(
            (c for c in candidates if c.passed_cutoff),
            key=lambda c: c.composite,
            reverse=True,
        )

        return RetrievalResult(
            context=ctx,
            query=query,
            corpus_size=self.doc_count,
            candidates=candidates,
            ranked=ranked,
            kept=ranked[:top_k],
            cutoff=cutoff,
        )
