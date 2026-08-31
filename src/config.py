"""
Every tunable threshold in one commented place.

Units are stated beside each value because the tools are pinned to imperial
units and America/New_York time -- a number without its unit here is how a
weather gate silently shifts four hours or twenty degrees.

This module must stay import-free of `src.*` (it is imported by everything,
including `src.memory.retrieval`; a `src.*` import here would be a cycle).
Stdlib only.
"""

from __future__ import annotations

import os
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]

# --------------------------------------------------------------------------
# Cache pinning: keep writes inside the repo (public-repo safety decision).
# LLAMA_INDEX_CACHE_DIR is the knob llama-index actually reads for the
# embedding weights (NOT HF_HOME -- verified on this machine). Offline mode
# is enabled only when the weights are already present, so a fresh clone can
# still perform its one-time ~90 MB download.
# --------------------------------------------------------------------------
_MODEL_CACHE = ROOT / ".cache" / "llama_index"
os.environ.setdefault("LLAMA_INDEX_CACHE_DIR", str(_MODEL_CACHE))
if (_MODEL_CACHE / "models--sentence-transformers--all-MiniLM-L6-v2").exists():
    os.environ.setdefault("HF_HUB_OFFLINE", "1")

# --------------------------------------------------------------------------
# Time. One rule system-wide: every tool converts to this zone at its
# boundary; no naive datetime crosses a module edge (tests assert it).
# --------------------------------------------------------------------------
TZ = ZoneInfo("America/New_York")

# --------------------------------------------------------------------------
# Identity / provider selection (env-driven; .env is loaded by entrypoints)
# --------------------------------------------------------------------------
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "ollama")  # quickstart default
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.1:8b")

# Approximate home origin (privacy: a neighborhood centroid near Grand Army
# Plaza, Brooklyn -- deliberately NOT a residential address; README labels
# it). Overridable per user via .env.
HOME_LAT = float(os.environ.get("HOME_LAT", "40.67"))
HOME_LON = float(os.environ.get("HOME_LON", "-73.97"))

# --------------------------------------------------------------------------
# Calendar / free windows
# --------------------------------------------------------------------------
WAKING_HOURS = (6, 22)  # local hours considered plannable
MIN_WINDOW_MINUTES = 90  # slivers shorter than this are discarded
SOFT_CONFLICT_PENALTY = -1.0  # score delta when a soft calendar block overlaps

# --------------------------------------------------------------------------
# Weather gate (extreme-weather thresholds; Open-Meteo is pinned to
# fahrenheit / mph / inch / America/New_York in the tool)
# --------------------------------------------------------------------------
PRECIP_PROB_GATE = 60  # % chance in any window hour -> outdoor gated
PRECIP_IN_GATE = 0.10  # inches/hour forecast rain -> outdoor gated
TEMP_MIN_F = 25  # below this, outdoor categories are gated
TEMP_MAX_F = 95  # above this, outdoor categories are gated
WIND_GATE_MPH = 25  # sustained wind above this gates outdoor categories

# --------------------------------------------------------------------------
# Transit
# --------------------------------------------------------------------------
# Exact MTA mercury_alert.alert_type strings -> action. Anything not listed
# is ignored. Verified against the live feed's vocabulary.
MTA_ALERT_ACTIONS: dict[str, tuple[str, float]] = {
    # alert_type:                      (action, score delta when "penalty")
    "Suspended": ("prune", 0.0),
    "Planned - Suspended": ("prune", 0.0),
    "Part Suspended": ("penalty", -1.5),
    "Planned - Part Suspended": ("penalty", -1.0),
    "No Scheduled Service": ("prune", 0.0),
    "Severe Delays": ("penalty", -1.5),
    "Delays": ("penalty", -0.5),
    "Planned - Stops Skipped": ("penalty", -0.5),
    "Stops Skipped": ("penalty", -0.5),
    # "Boarding Change" and similar informational types: ignored on purpose.
}
UNREACHABLE_FRACTION = 0.5  # trip is pruned if round-trip transit exceeds
#                             this fraction of the free window

# --------------------------------------------------------------------------
# Scoring / lifer bonus (ratings and scores are 1-10; final_score clamped)
# --------------------------------------------------------------------------
LIFER_BONUS_BASE = 1.0
LIFER_BONUS_PER_SPECIES = 0.5
LIFER_BONUS_CAP = 2.5  # min(CAP, BASE + PER * lifer_count)
FINAL_SCORE_MIN, FINAL_SCORE_MAX = 0.0, 10.0

# --------------------------------------------------------------------------
# Memory (Week-3 module; calibrated on the 20-entry corpus -- see
# scripts/week3/calibrate.py before changing)
# --------------------------------------------------------------------------
SIMILARITY_CUTOFF = 0.55

# --------------------------------------------------------------------------
# Weekly Tree-of-Thought
# --------------------------------------------------------------------------
BEAM_WIDTH = 4
BEAM_DEPTH = 7  # Monday..Sunday; days without windows are skipped
PRUNE_MARGIN = 3.0  # drop sets more than this below the depth leader.
#   Spec-frozen ABSOLUTE margin: note it bites hardest at depth 1, where
#   running totals are smallest -- documented behavior, not a bug.
WALKING_WEEK_MILES = 40.0  # critic penalizes weekly walking above this
TRANSIT_FATIGUE_WEEK_MIN = 420  # critic penalizes weekly transit above this
SEED = 20260831  # tie-breaks only; per-run random.Random(SEED)

# --------------------------------------------------------------------------
# API politeness (enforced by the single shared wrapper in src/tools/base.py)
# --------------------------------------------------------------------------
USER_AGENT = "excursion-agent-capstone (educational project; no scraping)"
RATE_MIN_INTERVAL_S: dict[str, float] = {
    # seconds between calls to the same source (conservative; iNat's
    # published ceiling is 60/min -- we stay far under it)
    "open-meteo": 1.0,
    "nws": 1.0,
    "noaa-tides": 1.0,
    "nyc-events": 1.0,
    "inaturalist": 3.0,
    "ebird": 2.0,
    "mta": 2.0,
    "ollama": 0.0,  # loopback
}
RETRY_MAX = 2  # network errors / 5xx only; NEVER 4xx; 429 -> circuit-break
BACKOFF_BASE_S = 1.5

# Per-scenario call budget (the ceiling is derived from this table, not a
# round number). Exceeding CALL_CEILING flags the run in trace + eval; it
# never raises limits.
CALL_BUDGET = {
    "daily": 12,  # 1 weather + 1 events + 1 mta + <=2 tides + <=6 bird/region
    "weekly": 35,  # 7 daily waterfalls sharing the invocation cache
    "full_demo": 80,  # S1-S5 under one invocation-scoped cache
}
CALL_CEILING = 90

# Hostname allowlist: documented public API GETs + Anthropic POST + loopback
# Ollama. The shared wrapper raises on anything else.
ALLOWED_HOSTS = {
    "api.open-meteo.com",
    "api.weather.gov",
    "api.tidesandcurrents.noaa.gov",
    "data.cityofnewyork.us",
    "api.inaturalist.org",
    "api.ebird.org",
    "api-endpoint.mta.info",
    "api.anthropic.com",  # claude-sdk provider (subscription auth)
    "localhost",
    "127.0.0.1",
}

# --------------------------------------------------------------------------
# Source-specific query parameters
# --------------------------------------------------------------------------
FORECAST_DAYS = 16  # one Open-Meteo call per run covers the whole horizon
TIDE_STATION_DEFAULT = "8518750"  # The Battery, per the frozen spec;
#   sites.json may override per site (the accuracy seam -- a data edit)
EBIRD_DIST_KM = 25
EBIRD_BACK_DAYS = 7
INAT_RADIUS_KM = 25
INAT_PER_PAGE = 20

# NYC permitted events: ALLOW-list (the live vocabulary has no "film" type;
# film/TV appears as the two excluded types below, and 82% of rows are
# permitted youth/adult sports we also don't want as excursions).
EVENT_TYPE_ALLOW = {
    "Special Event",
    "Farmers Market",
    "Street Event",
    "Street Festival",
    "Single Block Festival",
    "Parade",
    "Athletic Race / Tour",
    "Block Party",
    "Plaza Event",
    "Plaza Partner Event",
    "Open Street Partner Event",
    "Health Fair",
}
EVENT_TYPE_EXCLUDED_FILM = {"Production Event", "Theater Load in and Load Outs"}

# --------------------------------------------------------------------------
# LLM call discipline (applies to every provider through the factory)
# --------------------------------------------------------------------------
LLM_SEMAPHORE = {"claude-sdk": 2, "ollama": 1}
LLM_TIMEOUT_S = {"claude-sdk": 180, "ollama": 300}
LLM_MAX_TOKENS = 4096  # explicit output cap for every provider
OLLAMA_NUM_CTX = 16384  # default 2048 silently truncates evidence packs
OLLAMA_NUM_PREDICT = 2048

# --------------------------------------------------------------------------
# Server
# --------------------------------------------------------------------------
API_HOST = "127.0.0.1"
API_PORT = 8000
UI_ORIGIN = "http://localhost:5173"

# --------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------
DATA_DIR = ROOT / "data"
RUNS_DIR = ROOT / "runs"
EVAL_DIR = ROOT / "eval"
STORAGE_DIR = ROOT / "storage"
