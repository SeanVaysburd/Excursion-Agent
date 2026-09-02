# Evaluation results

All numbers below are computed exclusively from the trajectory
records of the runs cited here. Synthetic inputs are labeled;
simulated failures are stamped on every trace line.

## Source runs

| tag | trace | first record | provider | eBird |
|---|---|---|---|---|
| S1 | `sample_S1_2026-09-05.jsonl` | 2026-08-31T15:41:36.568-04:00 | claude-sdk | live key |
| S2 | `sample_S2_2026-09-05.jsonl` | 2026-08-31T15:45:23.534-04:00 | claude-sdk | no eBird calls (keyless or cached) |
| S3 | `sample_S3_2026-09-05.jsonl` | 2026-08-31T16:13:43.631-04:00 | claude-sdk | no eBird calls (keyless or cached) |
| S4 | `sample_S4_2026-09-05.jsonl` | 2026-08-31T16:16:39.038-04:00 | claude-sdk | no eBird calls (keyless or cached) |
| S4_control | `sample_S4_control_2026-09-05.jsonl` | 2026-08-31T16:24:15.563-04:00 | claude-sdk | live key |
| S5 | `sample_S5_2026-09-05.jsonl` | 2026-08-31T16:18:56.310-04:00 | claude-sdk | no eBird calls (keyless or cached) |
| escalation | `sample_escalation_2026-09-05.jsonl` | 2026-08-31T16:27:18.881-04:00 | claude-sdk | no eBird calls (keyless or cached) |
| forced_error_open-meteo | `sample_forced_error_open-meteo_2026-09-05.jsonl` | 2026-08-31T16:27:27.089-04:00 | claude-sdk | live key |
| ollama_S1 | `sample_ollama_S1_2026-09-05.jsonl` | 2026-08-31T13:27:33.916-04:00 | ollama | live key |
| ollama_S3 | `sample_ollama_S3_2026-09-05.jsonl` | 2026-08-31T12:39:48.550-04:00 | ollama | live key |
| ollama_S4 | `sample_ollama_S4_2026-09-05.jsonl` | 2026-08-31T12:31:49.859-04:00 | ollama | live key |
| ollama_S5 | `sample_ollama_S5_2026-09-05.jsonl` | 2026-08-31T12:34:05.140-04:00 | ollama | live key |

## Headline metrics

- **Groundedness**: 100.0% of evidence ids emitted by agents resolved to fetched records (1373/1373; the denominator counts everything emitted BEFORE stripping, so 100% means something). 2 candidate(s) dropped for zero valid evidence. Target: 100%.
- **Hard-constraint violations**: 0 across 51 final candidates (target 0; violators are dropped by the gate and logged).
- **Escalation**: triggered in `escalation` (zero_free_windows): "No usable free windows on 2026-09-05 (Saturday) after hard calendar blocks. I won't guess...." (fixture calendar `data/calendar_fullyblocked.ics`); the agent stopped and asked instead of guessing.
- **Forced-error degradation** (SIMULATED, labeled on every line of `sample_forced_error_open-meteo_2026-09-05.jsonl`): source `open-meteo` failed; 1 fallback step(s) taken; the run completed with stated low confidence instead of crashing or inventing data.
- **Fallback steps observed across all runs**: 5 (each labeled in its trace).

## Latency per stage (ms)

| stage | n | median | max |
|---|---|---|---|
| agents | 17 | 158605 | 303985 |
| calendar | 18 | 6 | 11 |
| prefetch | 17 | 1192 | 12175 |
| weather_gate | 16 | 2 | 31758 |

## Call accounting

- External calls across all cited runs: {'ebird': 42, 'inaturalist': 21, 'mta': 7, 'noaa-tides': 13, 'nws': 3, 'nyc-events': 13, 'open-meteo': 9} (total 108 summed over every cited run; the 55-call ceiling applies PER RUN and its flag was not raised in any of them).
- LLM calls: {'agent': 50, 'critic': 72, 'probe': 8, 'total': 130}.
- Critic calls 72 <= designed bound 3+12(D-1) = 75: OK; arithmetic mismatches logged: 0.

## KEY RESULT: naive rank-by-sum vs Tree-of-Thought

### Honest finding

This weekly run uses the authored synthetic calendar
week, selected because it exercises the contrast.
Live-data variance means another week may show no
contrast; that outcome is reported here plainly when it
happens, and re-running with `--date` in another week
is the documented recourse.

| day | naive pick | ToT pick |
|---|---|---|
| 2026-08-31 | Union Square Greenmarket [outdoor_event] | Green-Wood Cemetery [nature] **<-** |
| 2026-09-01 | Green Market [outdoor_event] | Green Market [outdoor_event] |
| 2026-09-02 | Union Square Greenmarket [outdoor_event] | Marine Park Salt Marsh [nature] **<-** |
| 2026-09-03 | Jamaica Bay Wildlife Refuge [nature] | Jamaica Bay Wildlife Refuge [nature] |
| 2026-09-04 | Marine Park Salt Marsh [nature] | Marine Park Salt Marsh [nature] |
| 2026-09-05 | Jamaica Bay Wildlife Refuge [nature] | Rowing in Inwood Park [outdoor_event] **<-** |
| 2026-09-06 | Floyd Bennett Field [nature] | Floyd Bennett Field [nature] |

Naive base sum 52.5 vs ToT adjusted 47.0; 3 day(s) flipped; dominant penalty: **variety**. The Week-4 design claim (a set's value is not the sum of its parts) demonstrated on a real run.

## Lifer bonus on/off

- With the committed list (*synthetic, intentionally incomplete*): 2 potential lifer(s) surfaced; max lifer bonus applied +2.0 (cap 2.5).
- With the fuller-life-list control (*synthetic variant: life_list_full.csv*): 0 lifer(s), bonus +0.0. Same site, same day; the delta is the life-list gap.

## Rubric consistency across domains

Raw model scores (1-10, shared rubric) from agent_report records (every scored candidate, pre-pruning):

| domain | n | mean | min | max |
|---|---|---|---|---|
| indoor | 64 | 5.5 | 4 | 8 |
| nature | 110 | 5.5 | 2 | 9 |
| outdoor_event | 127 | 4.7 | 1 | 9 |

Same scores, surviving top-3 picks only (where the domains compete head to head):

| domain | n | mean | min | max |
|---|---|---|---|---|
| indoor | 3 | 8.0 | 8 | 8 |
| nature | 18 | 7.8 | 6 | 9 |
| outdoor_event | 9 | 8.0 | 7 | 9 |

A domain grading looser than the others would show a systematically higher survivor mean; the shared anchor block in src/agents/rubric.py is what keeps these level.

## Acceptance and calibration

- No accept/pass decisions recorded yet. The capture mechanism ships in the UI (Pass on every suggestion card, and an accept is an Add to calendar with its optional note; both POST /api/feedback); the metrics compute automatically from recorded decisions on the next evaluate run.

---
Generated 2026-09-02T14:14:07-04:00 by scripts/evaluate.py; trajectory traces in `runs/`.
