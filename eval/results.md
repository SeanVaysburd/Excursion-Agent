# Evaluation results

All numbers below are computed exclusively from the trajectory
records of the runs cited here. Synthetic inputs are labeled;
simulated failures are stamped on every trace line.

## Source runs

| tag | trace | first record | provider | eBird |
|---|---|---|---|---|
| S1 | `sample_S1_2026-09-05.jsonl` | 2026-08-31T13:09:44.443-04:00 | claude-sdk | live key |
| S2 | `sample_S2_2026-09-05.jsonl` | 2026-08-31T13:11:54.096-04:00 | claude-sdk | keyless/cached |
| S3 | `sample_S3_2026-09-05.jsonl` | 2026-08-31T13:39:01.885-04:00 | claude-sdk | keyless/cached |
| S4 | `sample_S4_2026-09-05.jsonl` | 2026-08-31T13:43:20.051-04:00 | claude-sdk | keyless/cached |
| S4_control | `sample_S4_control_2026-09-05.jsonl` | 2026-08-31T13:50:33.192-04:00 | claude-sdk | live key |
| S5 | `sample_S5_2026-09-05.jsonl` | 2026-08-31T13:45:36.457-04:00 | claude-sdk | keyless/cached |
| escalation | `sample_escalation_2026-09-05.jsonl` | 2026-08-31T14:21:15.138-04:00 | claude-sdk | keyless/cached |
| forced_error_open-meteo | `sample_forced_error_open-meteo_2026-09-05.jsonl` | 2026-08-31T14:21:24.692-04:00 | claude-sdk | live key |
| ollama_S1 | `sample_ollama_S1_2026-09-05.jsonl` | 2026-08-31T13:27:33.916-04:00 | ollama | live key |
| ollama_S3 | `sample_ollama_S3_2026-09-05.jsonl` | 2026-08-31T12:39:48.550-04:00 | ollama | live key |
| ollama_S4 | `sample_ollama_S4_2026-09-05.jsonl` | 2026-08-31T12:31:49.859-04:00 | ollama | live key |
| ollama_S5 | `sample_ollama_S5_2026-09-05.jsonl` | 2026-08-31T12:34:05.140-04:00 | ollama | live key |

## Headline metrics

- **Groundedness**: 100.0% of evidence ids emitted by agents resolved to fetched records (1309/1309; the denominator counts everything emitted BEFORE stripping, so 100% means something). 0 candidate(s) dropped for zero valid evidence. Target: 100%.
- **Hard-constraint violations**: 0 across 51 final candidates (target 0; violators are dropped by the gate and logged).
- **Escalation**: triggered in `escalation` (zero_free_windows): "No usable free windows on 2026-09-05 (Saturday) after hard calendar blocks. I won't guess...." (fixture calendar `data/calendar_fullyblocked.ics`); the agent stopped and asked instead of guessing.
- **Forced-error degradation** (SIMULATED, labeled on every line of `sample_forced_error_open-meteo_2026-09-05.jsonl`): source `open-meteo` failed; 1 fallback step(s) taken; the run completed with stated low confidence instead of crashing or inventing data.
- **Fallback steps observed across all runs**: 6 (each labeled in its trace).

## Latency per stage (ms)

| stage | n | median | max |
|---|---|---|---|
| agents | 17 | 130284 | 286653 |
| calendar | 18 | 2 | 6 |
| prefetch | 17 | 665 | 11276 |
| weather_gate | 5 | 186 | 31758 |

## Call accounting

- External calls across all cited runs: {'ebird': 42, 'inaturalist': 21, 'mta': 7, 'noaa-tides': 13, 'nyc-events': 13, 'open-meteo': 9} (total 105 summed over every cited run; the 55-call ceiling applies PER RUN and its flag was not raised in any of them).
- LLM calls: {'agent': 49, 'critic': 72, 'probe': 8, 'total': 129}.
- Critic calls 72 <= designed bound 3+12(D-1) = 75: OK; arithmetic mismatches logged: 0.

## KEY RESULT: naive rank-by-sum vs Tree-of-Thought

*(Disclosure: this weekly run uses the authored synthetic
calendar week, selected because it exercises the
contrast. Live-data variance means another week may show
no contrast; that outcome is reported here honestly when
it happens, and re-running with `--date` in another week
is the documented recourse.)*

| day | naive pick | ToT pick |
|---|---|---|
| 2026-08-31 | Union Square Greenmarket [outdoor_event] | Union Square Greenmarket [outdoor_event] |
| 2026-09-01 | Prospect Park [nature] | Prospect Park [nature] |
| 2026-09-02 | Rowing in Inwood Park [outdoor_event] | Rowing in Inwood Park [outdoor_event] |
| 2026-09-03 | Marine Park Salt Marsh [nature] | Marine Park Salt Marsh [nature] |
| 2026-09-04 | Union Square Greenmarket [outdoor_event] | Union Square Greenmarket [outdoor_event] |
| 2026-09-05 | Jamaica Bay Wildlife Refuge [nature] | Floyd Bennett Field [nature] **<-** |
| 2026-09-06 | Brooklyn Museum [indoor] | Brooklyn Museum [indoor] |

Naive base sum 51.0 vs ToT adjusted 47.0; 1 day(s) flipped; dominant penalty: **transit_fatigue**. The Week-4 design claim (a set's value is not the sum of its parts) demonstrated on a real run.

## Lifer bonus on/off

- With the committed list (*synthetic, intentionally incomplete*): 71 potential lifer(s) surfaced; max lifer bonus applied +2.5 (cap 2.5).
- With the fuller-life-list control (*synthetic variant: life_list_full.csv*): 1 lifer(s), bonus +1.5. Same site, same day; the delta is the life-list gap.

## Rubric consistency across domains

Raw model scores (1-10, shared rubric) from day_plan slot survivors (post-pipeline):

| domain | n | mean | min | max |
|---|---|---|---|---|
| indoor | 4 | 8.0 | 8 | 8 |
| nature | 18 | 7.7 | 6 | 9 |
| outdoor_event | 8 | 7.8 | 7 | 8 |

## Acceptance and calibration

- No accept/pass decisions recorded yet. The capture mechanism ships in the UI (Accept/Pass on every suggestion card, POST /api/feedback); both metrics compute automatically from recorded decisions on the next evaluate run.

---
Generated 2026-08-31T15:11:20-04:00 by scripts/evaluate.py; trajectory traces in `runs/`.
