# Person 3: Hotel Search (Task 4) and Best Month to Visit (Task 6)

Owner: Sal (Salamot Fakoya)
Branch: `person3-hotels-weather`
Tested on Python 3.14.

## Status

- [x] Geo utilities (`src/geo_utils.py`): precinct boundaries, ray-casting, haversine (merged into `main`)
- [x] Task 4 code (`src/task4_hotels.py`): hotel list, rates by site, cheapest options, precinct assignment, nearby alternatives, live calls with labelled cache fallback
- [x] Task 4 test run for July and December (60 hotels)
- [x] Task 4 final run with 800 hotels for July and December (outputs and Xotelo cache committed)
- [x] Task 4: guests parameter (`search_hotels(..., guests=N)`)
- [ ] Task 4: confirm the months with Persons 1 and 2, and swap in the official Task 2 top-5 list
- [ ] Tasks 4 and 6: switch to Person 1's final `neighbourhood_month.parquet` and decide how to handle precinct 116 (see Known data issues)
- [x] Task 6 (`src/task6_best_months.py`): monthly temperatures combined with incident rates, top 3 months, sensitivity check
- [ ] Task 6: rerun on Person 1's final `neighbourhood_month.parquet` (currently uses the example file)

## Setup

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Run everything from the project root with `python -m`, so `from src...` imports resolve:

```powershell
python -m src.task4_hotels
```

## Geo utilities (`src/geo_utils.py`)

Used by Tasks 4, 5 and 8.

| Function | Input | Output |
|---|---|---|
| `load_precincts()` | none | dict of precinct number (int) to MultiPolygon coordinates |
| `find_precinct(lat, lon, precincts)` | latitude, longitude, output of `load_precincts()` | precinct number (int), or `None` if outside NYC |
| `haversine_km(lat1, lon1, lat2, lon2)` | two points | distance in km |

```python
from src.geo_utils import load_precincts, find_precinct, haversine_km

precincts = load_precincts()
find_precinct(40.7484, -73.9857, precincts)          # 14 (Empire State Building)
haversine_km(40.7580, -73.9855, 40.7484, -73.9857)   # about 1.07
```

Notes:
- Boundaries come from NYC Open Data dataset `y76i-bdw7`, saved to `data/precincts.geojson` (78 precincts, matching the 78 in `neighbourhood_month.parquet`).
- Precinct numbers are ints, matching the `precinct` column in Person 1's parquet.
- GeoJSON stores `[lon, lat]`, but `find_precinct` and `haversine_km` take lat first.
- The ray-casting test handles MultiPolygons (precincts made of several pieces, such as precinct 1 with the harbor islands) and holes.

### Validation

| Test point | Expected | Result |
|---|---|---|
| Empire State Building (40.7484, -73.9857) | 14 | 14 |
| Central Park (40.7812, -73.9665) | 22 | 22 |
| Jersey City (40.7282, -74.0776) | None | None |
| Times Square to Empire State Building | about 1.1 km | 1.07 km |

## Task 4: Hotel search (`src/task4_hotels.py`)

### Main entry point for the app

```python
from src.task4_hotels import search_hotels

df, message = search_hotels("2027-03-12", nights=2, max_price=150, guests=2, n_hotels=20, live=True)
print(message)   # e.g. "Live prices for all 18 hotels."
```

- Returns `(DataFrame, message)`. The DataFrame holds only hotels within `max_price`, cheapest first.
- `live=True` calls Xotelo first. If Xotelo fails, cached prices are used and `message` says so, with their age.
- `live=False` answers from the cache only (no API calls).
- Raises `RuntimeError` if Xotelo is down and nothing is cached for those dates. The app should catch this and tell the user.
- `guests` is the number of adults (default 1). It is always sent to Xotelo, so live searches never rely on Xotelo's default. If the user gives no guest count, the app should either ask or use 1 deliberately.
- Prices are per room per night, before taxes and fees.

### Other functions

| Function | Purpose |
|---|---|
| `cheapest_options(df, max_price, month, include_hostels=True)` | `(cheapest hotel within budget, cheapest within budget outside that month's top-5 incident precincts)`. Either can be `None`. Pass `include_hostels=False` to skip hostels. |
| `find_nearby(df, hotel_key, radius_km=2.0)` | Every other hotel within 2 km of the chosen hotel, cheapest first, with distance, precinct and savings. |
| `describe_sources(df)` | One sentence describing where the prices came from and how old they are. |
| `get_top5_precincts(month)` | **Temporary** stand-in for Person 1's Task 2 top-5 list, computed from the example parquet. To be replaced by Task 2's official output. |

### Stay dates

The batch run uses one stay per Task 2 / Task 8 month, set in `STAYS` at the top of `src/task4_hotels.py`:

| Month | Check-in | Check-out | Nights |
|---|---|---|---|
| July | 2027-07-13 (Tue) | 2027-07-16 (Fri) | 3 |
| December | 2026-12-08 (Tue) | 2026-12-11 (Fri) | 3 |

Both are midweek, avoid holidays, and fall within Xotelo's roughly 11-month booking window (December 2027 is outside it). These are provisional until the team confirms its two months. `N_HOTELS` sets how many hotels the batch run fetches (60 for testing, about 800 for the final run).

### Hotel table columns (`t4_hotels.csv`, and the DataFrame from `search_hotels`)

`t4_hotels.csv` holds both stays. Filter on `stay_month` to get one (for example `df[df["stay_month"] == 7]`). The DataFrame from `search_hotels` has no `stay_month` or `check_in` columns, since it covers one search.

| Column | Meaning |
|---|---|
| `stay_month`, `check_in` | Which stay the row belongs to (batch output only) |
| `hotel_key` | Xotelo / TripAdvisor hotel ID |
| `name`, `type`, `rating`, `review_count` | From the Xotelo hotel list |
| `lat`, `lon` | Coordinates |
| `precinct` | Precinct containing the hotel (nullable int) |
| `price_<site>` | Nightly price on each booking site, e.g. `price_Agoda.com`, `price_Booking.com` (blank if the hotel is not on that site) |
| `cheapest_site`, `cheapest_nightly` | Cheapest site and its nightly price (USD, tax included when Xotelo reports it) |
| `nights`, `total_stay` | Stay length and `cheapest_nightly x nights` |
| `retrieved_at` | When Xotelo produced the price (UTC) |
| `source` | `live`, `cache` or `cache_fallback` |
| `price_age_hours` | Hours since `retrieved_at` |
| `is_hostel` | True if `type` is `Hostel` or the name contains "hostel" (some hostels are labelled `Hotel`) |

### Nearby table columns (`t4_nearby.csv`)

`stay_month`, `chosen_hotel`, `chosen_nightly`, `name`, `hotel_key`, `precinct`, `cheapest_nightly`, `cheapest_site`, `savings_per_night`, `total_savings`, `distance_km`.

`savings_per_night` is the chosen hotel's price minus the alternative's. Positive means the alternative is cheaper. Negative means it costs more.

### Caching

- Every Xotelo response is saved under `cache/xotelo/`, one JSON file per request.
- Error responses are never cached.
- The batch run (`python -m src.task4_hotels`) uses `live=False`, so it only fetches what is missing. A run that is interrupted or rate-limited can simply be rerun.
- The committed cache (`cache/xotelo/`, about 1,700 files, 0.7 MB) covers both batch stays, so the outputs can be rebuilt without calling Xotelo.
- The guest count is part of the cache key: a 2-adult search is cached separately (`..._adults-2_...`) and never mixed with default prices.

### Guests

Xotelo's `adults` parameter changes both prices and which booking sites can sell the stay. For one hotel (West Side YMCA, July 13-16, 2027):

| Adults | Agoda | Booking.com | Official site |
|---|---|---|---|
| 1 | $101 | $136 | $141 |
| 2 | $108 | $145 | $151 |
| 4 | $188 | $254 | $273 |

Vio.com offered the stay for 1 and 2 adults but not for 4. Without `adults`, Xotelo prices 1 adult (the batch run's cached $101 matches the 1-adult price), so **the batch outputs `t4_hotels.csv` and `t4_nearby.csv` are 1-adult prices**. Two adults cost roughly 7% more.

Test with 5 hotels in July and a $400 budget: 4 hotels fit for 1 guest and 2 for 4 guests (ROW NYC $186 to $279, The Empire Hotel $212 to $367).

### Test runs (60 hotels)

60-hotel test runs. The first checks used placeholder dates (Jan 15 to 18, 2027). The July and December results come from the stays above.

- January: 60 hotels fetched, 59 with prices, 0 outside NYC precincts, 0 failed.
- July: 59 of 60 hotels priced. December: 54 of 60 priced. The December stay is under two weeks away, so some hotels are likely sold out.
- Cheapest hotel under $150 in all three test stays: West Side YMCA (precinct 20), at $72 a night in January, $101 in July and $121 in December.
- Top-5 incident precincts from the stand-in: July [75, 14, 44, 40, 43], December [75, 14, 40, 44, 43]. Same five precincts in a different order.
- Precinct checks: West Side YMCA (20, Upper West Side), Radio Hotel (34, Washington Heights), The FIDI Hotel (1), Ly New York Hotel (109, Flushing).
- Top-5 filter check: with the three cheapest hotels removed, the cheapest is ROW NYC (precinct 14, a top-5 precinct), and the cheapest outside the top 5 is The FIDI Hotel (precinct 1).
- Nearby (January): ROW NYC (Midtown) has 45 hotels within 2 km, while The FIDI Hotel has 2. July: 45 and 2. December: 41 and 1. The default Xotelo ranking clusters heavily in Midtown, which is why the final run will use more hotels.
- Fallback check: a live search, then the same search with `BASE_URL` pointed at an invalid host, returned cached prices with the message "The hotel price service did not respond for 4 of 4 hotels, so their prices are cached and up to 0.0 hours old."

### Final run (800 hotels, July and December)

| | July (Jul 13-16, 2027) | December (Dec 8-11, 2026) |
|---|---|---|
| Hotels fetched (with coordinates) | 800 | 800 |
| With prices for the stay | 397 | 325 |
| Outside NYC precincts | 1 | 2 |
| Failed requests | 0 | 0 (after one retry run) |
| Precincts covered (of 78) | 28 | 28 |
| Cheapest under $150 | Kama Central Park Hostel (precinct 24), $70 | HI New York City Hostel (precinct 24), $76 |
| Cheapest non-hostel under $150 | New York Spirit Retreats (precinct 10), $93 | Days Inn by Wyndham Staten Island (precinct 121), $87 |
| Hotels within 2 km of ROW NYC | 259 (8 cheaper) | 202 (16 cheaper) |
| Hotels within 2 km of The FIDI Hotel | 49 (21 cheaper) | 46 (9 cheaper) |

Cleaning and data notes:
- 4 hotels in the Xotelo list had no coordinates and were skipped (the list is paged until 800 hotels with coordinates are collected). Duplicate hotel keys across pages are also skipped.
- About half the hotels have no prices for a given stay. Xotelo returns a valid response with no rates for them, usually smaller or less-booked listings further down its ranking.
- During the first December pass, Xotelo stopped answering after about 1,300 requests in one session: every request from hotel 600 onward failed. Failed responses are never cached, so a rerun the next morning retried only those hotels. One "connection refused" error remained, and it succeeded on a further rerun. Most retried hotels turned out to have no prices for the stay.
- Prices change quickly. The West Side YMCA showed $121 a night for the December stay in the batch run and $99 in a live check the next morning, which is why `retrieved_at` is recorded.

Findings for the report:
- **Hotels cover only 28 of 78 precincts**, concentrated in Manhattan, even with 800 hotels. This is where hotels actually are, not a sampling problem, and it limits any hotel-based neighbourhood recommendation (Task 8).
- **The 60-hotel sample was misleading.** It made downtown look empty (2 hotels within 2 km of The FIDI Hotel versus 49 with 800) and picked the West Side YMCA as the cheapest option, which a larger sample overturned.
- **The cheapest options are hostels**, whose prices may be for a bed in a shared dorm. The `is_hostel` flag and `include_hostels=False` give the cheapest private-room alternative.
- **Price alone ignores location.** December's cheapest non-hostel is on Staten Island, far from most attractions.
- 9 of the hotels are hostels by type or name; accommodation types also include small hotels, limited-service properties, condominiums, guest houses, resorts, a lodge and a motel.

### Open decisions

- Months: using July and December until Persons 1 and 2 confirm. If they change, only `STAYS` needs editing.
- Batch outputs stay at 1 adult; rerunning 1,600 requests for 2 adults would add about 7% to prices and risk another rate-limit.

## Task 6: Best month to visit (`src/task6_best_months.py`)

```powershell
python -m src.task6_best_months
```

Output: `outputs/t6_best_months.csv`, one row per month, best first.

### Data

- Temperatures: `data/city_temperature.csv` (from Homework 2 and 4). New York is spelled `"New York"`, with 1,827 daily rows for 2020 to 2024 and no `-99` values (the code still drops them as a safeguard). Temperatures are in °F.
- Incidents: `data/neighbourhood_month_example.parquet` (Person 1's earlier draft of the Task 1 output). Switch `INCIDENTS_PATH` to Person 1's final `neighbourhood_month.parquet` when it exists.

### Columns

| Column | Meaning |
|---|---|
| `month_name` | Month |
| `avg_temp_f` | Average daily temperature, 2020 to 2024 |
| `distance_from_70f` | Degrees away from a comfortable 70°F, hotter or colder |
| `avg_monthly_incidents` | City-wide incidents in that month, averaged over 2022 to 2024 |
| `avg_incidents_per_day` | The same, divided by the days in each month (February 2024 counted as 29 days) |
| `comfort_score`, `safety_score` | Both measures scaled to 0 to 1, where 1 is best |
| `score`, `rank` | Combined score and rank |

### Scoring rule

1. **Comfort.** Min-max scale `distance_from_70f` to 0 to 1 and flip it, so the month closest to 70°F scores 1 and the furthest scores 0.
2. **Safety.** Min-max scale `avg_incidents_per_day` the same way, so the month with the lowest incident rate scores 1.
3. **Score** = 0.6 × comfort + 0.4 × safety.

Why these choices:
- Incidents are compared **per day**, not as monthly totals. February has about 10% fewer days than a 31-day month, so its raw total looks lower even when the daily rate is not. In this data February has the lowest monthly total (40,430) but January has the lowest daily rate (1,402 versus 1,426).
- Both measures are **scaled to 0 to 1** before weighting, because degrees and incident counts are on very different scales.
- **Comfort gets more weight** because weather affects every day of a trip, while the city-wide incident rate varies only about 15% across the year (1,402 to 1,611 per day).

### Results

| Rank | Month | Avg temp | From 70°F | Incidents per day | Score |
|---|---|---|---|---|---|
| 1 | September | 69.4°F | 0.6 | 1,556 | 0.704 |
| 2 | June | 70.4°F | 0.4 | 1,611 | 0.600 |
| 3 | August | 75.8°F | 5.8 | 1,567 | 0.588 |
| 4 | April | 51.3°F | 18.7 | 1,475 | 0.531 |
| 5 | May | 60.4°F | 9.6 | 1,561 | 0.529 |
| ... | | | | | |
| 12 | February | 37.1°F | 32.9 | 1,426 | 0.366 |

**Recommendation: September, June and August.**

### Sensitivity check

| Weights (comfort / safety) | Top 3 |
|---|---|
| 60 / 40 (chosen) | September, June, August |
| 70 / 30 | September, June, August |
| 50 / 50 | September, April, August |

September and August stay in the top 3 under every weighting. June depends on the weights: it has the best weather but the highest incident rate of any month (safety score 0), so it drops out when safety counts as much as comfort, and April takes its place.

### Limitations

- Min-max scaling stretches small differences. Incident rates vary about 15% across the year, but scaling gives them the same 0-to-1 spread as a 33-degree temperature range, so it exaggerates how different the months are on safety.
- Distance from 70°F treats too hot and too cold the same, and ignores humidity, rain and snow.
- City-wide incident rates say little about the precinct a visitor actually stays in. Task 2 and Task 4 handle neighbourhood-level risk.
- The incident figures come from the example parquet (Person 1's earlier draft output, not a course file) until Person 1's final file is in place.
- Temperatures cover 2020-2024 while incidents cover 2022-2024, as the handout specifies.
- Monthly averages hide extremes: a month averaging 70°F can still include heat waves or cold snaps.
- Summer incident rates partly reflect more people being out, not only higher risk.

## Known data issues and limitations

### Precinct 116 (affects Tasks 2, 4, 6 and 8)

NYC created the 116th precinct in southeast Queens from parts of precincts 105 and 113 near the end of the 2022-2024 period. In the incident data it has 6 incidents in 2022, 10 in 2023 and 312 in 2024, against roughly 8,000 to 9,000 a year in 105 and 113. Its low counts mean it barely existed yet, not that it is safe. The precinct boundary file is current, so a hotel or attraction in that area is assigned to 116 and looks far safer than it is. The team needs one rule for it (exclude it, or use 2024 only) and should state it in the report.

### Hotel prices (Task 4)

- **Taxes and fees are not included.** Xotelo returned `tax: null` for every rate, so `cheapest_nightly` and `total_stay` are pre-tax. NYC hotel taxes add roughly 15% plus a small per-night fee.
- **The cheapest site may not be like for like.** Sites can quote different room types or cancellation terms, so a cheap non-refundable rate is not the same product as a flexible one.
- **Prices are snapshots.** They changed noticeably overnight for the December stay. `retrieved_at` records when each was fetched.
- **The hotel list is ranked by popularity, not sampled at random**, so it leans toward well-known Manhattan hotels.
- **Batch prices are for 1 adult** (see Guests).

### Distances and precincts (Tasks 4 and 8)

- **Haversine is straight-line distance.** It ignores rivers, bridges and transit, so a Brooklyn hotel "within 2 km" of Lower Manhattan can be a much longer trip.
- **Points exactly on a shared boundary** are assigned to the first precinct that contains them. This is rare.

### Incident counts (Tasks 2, 4, 6 and 8)

- **Counts are not risk.** Busy areas such as Midtown (precinct 14) rank high partly because so many people pass through them. Without resident or visitor numbers, counts overstate the risk in tourist areas.
- **Reported is not the same as occurring.** Complaint data only includes incidents someone reported.

## Data sources

- NYC Police Precincts (NYC Open Data `y76i-bdw7`): https://data.cityofnewyork.us/resource/y76i-bdw7.geojson
- Xotelo API (NYC location key `g60763`, no key required): https://data.xotelo.com/api
- City temperatures: `city_temperature.csv`, provided with Homework 2 and Homework 4