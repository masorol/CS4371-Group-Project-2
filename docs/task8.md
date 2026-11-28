# Task 8 — Places to Visit and Best Neighbourhoods

## Overview

Task 8 finds attractions from OpenStreetMap, adds each one's reported-incident and nearby-hotel context, and ranks the best places to visit and the best NYPD precincts to stay in or explore for a chosen month.

**Data sources:**
- OpenStreetMap, via the free Overpass API (attractions: museums, galleries, viewpoints, zoos, aquariums, theme parks, places tagged `tourism=attraction`, and named parks).
- `data/processed/neighbourhood_month.parquet` (Task 1's output) — **temporary** stand-in for Task 2's per-precinct monthly incident averages.
- `outputs/t4_hotels.csv` (Task 4's output) — hotel locations and cheapest nightly prices.
- Groq (`openai/gpt-oss-120b`) for the grounded traveler summary.

**Months used:** July (2027-07-13 to 16) and December (2026-12-08 to 11), the same two stays already used for Task 4 (`src/task4_hotels.STAYS`).

## Required Files

**Input:**
- `data/precincts.geojson` (downloaded automatically by `src.geo_utils.load_precincts`)
- `data/processed/neighbourhood_month.parquet.zip` — Task 1's output, committed zipped (`data/processed/` is otherwise gitignored). `get_precinct_month_avg`/`get_top5_precincts` extract it to `data/processed/neighbourhood_month.parquet` automatically the first time they're called; no manual unzip step needed.
- `outputs/t4_hotels.csv` — **must exist before running Task 8.** Generate it with `python -m src.task4_hotels` if it's missing.

**Implementation:**
- `src/task8_attractions.py`
- Reused from Task 4: `src/geo_utils.py` (`load_precincts`, `find_precinct`, `haversine_km`), `src/task4_hotels.py` (`get_precinct_month_avg`, `STAYS`)

**Generated Outputs** (per month, `<month>` is the plain stay month number, `7` or `12`):
- `outputs/t8_attractions_<month>.csv`
- `outputs/t8_neighbourhoods_<month>.csv`
- `outputs/t8_summary_<month>.md`

**Cached API Responses:**
- `cache/overpass/attractions.json` (one query, shared across both months)
- `cache/t8/groq_summary_<month>.json`

## Setup Instructions

Run all commands from the project's root directory.

### 1. Create and activate a virtual environment, install dependencies

Same as [Task 3](./task3.md#1-create-a-virtual-environment) and [Task 4](./person3_tasks4_6.md#setup):

```bash
python3 -m venv .venv
source .venv/bin/activate      # .venv\Scripts\activate on Windows
python -m pip install -r requirements.txt
```

### 2. Configure API keys

Copy `.env.example` to `.env` and add:

```dotenv
GROQ_API_KEY=your_groq_api_key
```

### 3. Generate Task 4's hotel data first

Task 8 reads `outputs/t4_hotels.csv` for the "hotels within 1 km" and "hotels in budget" context. The real 800-hotel run is already committed at `outputs/t4_hotels.csv` (722 hotels with prices: 397 for July, 325 for December). If it's ever missing or stale, regenerate it with:

```bash
python -m src.task4_hotels
```

## Running Task 8

```bash
python -m src.task8_attractions
```

The Overpass API is a shared, free public server that occasionally answers with a transient 5xx error under load; `fetch_attractions_raw` retries with backoff (up to 4 attempts) before giving up, so a single flaky response shouldn't break the run.

This:
1. Downloads NYC precinct boundaries (cached after the first run).
2. Runs one Overpass query for every attraction tag in the spec across all five boroughs, caches the raw response, and reuses it on later runs.
3. Cleans the results: keeps only named elements with coordinates, deduplicates, records each one's Wikipedia/Wikidata tag, assigns a precinct with the Task 4 ray-casting code, and drops anything outside NYC.
4. For July and December in turn: adds each attraction's precinct incident average and nearby-hotel context, scores and ranks attractions and neighbourhoods, asks Groq for a grounded summary (with the number check), and saves the three output files.

## Scoring Rules

**Best places to visit** (`score_attractions`, 0–5 points):
- **+2** if the attraction has a Wikipedia or Wikidata tag — a sign it's a well-known, documented destination rather than something incidentally mapped.
- **up to +2**, scaled by how low its precinct's reported incidents are that month relative to the min–max range across all attractions in the dataset (fewer incidents → higher score).
- **+1** if at least one Task 4 hotel is within 1 km — kept binary (not scaled by hotel count) so already hotel-dense areas (e.g. Midtown) aren't rewarded further for it.

**Best neighbourhoods to stay in or explore** (`score_neighbourhoods`, 0–5 points), computed over all 78 NYC precincts:
- **up to +2** for the number of attractions in the precinct, min–max scaled (more to see and do → higher).
- **up to +2** for how low its reported incidents are that month, scaled the same way as the attraction rule (fewer incidents → higher).
- **up to +1** for how many Task 4 hotels are within the user's budget (default $200/night), min–max scaled — capped lower than the other two factors since affordability is a convenience, not a reason to visit.

Both rules break ties deterministically (see the docstrings in `src/task8_attractions.py` for the exact tie-break order), so the same inputs always produce the same ranking.

## Output Files

| File | Description |
|---|---|
| `t8_attractions_<month>.csv` | Every cleaned attraction for that month (name, category, coordinates, Wikipedia flag, precinct, incident average, hotels within 1 km, cheapest nearby hotel, score, rank). Sorted best-first; rows 1–10 are the Task 8 "top 10". |
| `t8_neighbourhoods_<month>.csv` | All 78 precincts, with attraction count, incident average, in-budget hotel count, median nightly price, score and rank. Sorted best-first; rows 1–5 are the Task 8 "top 5". |
| `t8_summary_<month>.md` | Data sources and retrieval times, the top 10 attractions table, the top 5 neighbourhoods table, and the grounded LLM summary (or a note that it's unavailable, if the number check failed twice). |

## Grounded Explanation and Number Check

Following the same pattern as Task 2/3: only the top 10 attractions and top 5 neighbourhoods (as JSON) are sent to Groq (`temperature=0`), with a system prompt instructing it to use only the numbers given and to describe areas by "reported incidents," never "dangerous" or "unsafe." Every numeric token in the LLM's reply is then checked against the numbers actually sent (`passes_number_check`); on failure it retries once with an explicit warning, and falls back to showing the tables alone if that also fails. Raw responses are cached per month under `cache/t8/`.

## Notes

- **Precincts, not named neighbourhoods.** Like Task 3/4, NYC's open data only gives NYPD precinct numbers, not named neighbourhoods, so "neighbourhood" in this project's outputs means "precinct."
- **Task 2 stand-in.** `get_precinct_month_avg(month)` (in `src/task4_hotels.py`) is a **temporary** replacement for Person 1's real Task 2 output — the average reported incidents per precinct for a given month, computed directly from `data/processed/neighbourhood_month.parquet`. Swap it out once Task 2's official per-precinct, per-month averages exist.
- **Hotel data is the real 800-hotel run.** `outputs/t4_hotels.csv` now comes from Task 4's final batch (722 hotels with prices: 397 July, 325 December), a big improvement in coverage outside Midtown over the earlier 60-hotel test run — e.g. precinct 10 went from 0 to 3 hotels in budget, precinct 5 from 0 to 7.
- **Responsible language.** Per the ground rules, neighbourhoods are described by their reported incidents, never as "dangerous" — both the scoring rule's framing and the LLM's system prompt enforce this.
- **Validated precinct assignments:** Empire State Building → precinct 14; Central Park Zoo and the Metropolitan Museum of Art → precinct 22 (matching the validation points already recorded for `find_precinct` in [docs/person3_tasks4_6.md](./person3_tasks4_6.md)).
- **Known OSM data-quality quirk:** a handful of `tourism=attraction` nodes are individual zoo exhibits or apparent vandalism (e.g. a single animal enclosure, or a nonsense name). These are kept since they match the spec's tag list as-is, but they score low (no Wikipedia tag) and don't appear in the observed top 10; worth a one-line mention in the report's limitations section.
- **Entry point for Task 5:** `get_places_to_visit(month, max_price, live=False, live_llm=False)` returns `(attractions, neighbourhoods, summary_text)` — the full scored/ranked tables (for the map page's markers and `.head(n)` slicing) plus the grounded summary, mirroring `task4_hotels.search_hotels()`.
