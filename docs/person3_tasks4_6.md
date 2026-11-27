# Person 3: Hotel Search (Task 4) and Best Month to Visit (Task 6)

Owner: Sal (Salamot Fakoya)
Branch: `person3-hotels-weather`
Tested on Python 3.14.

## Status

- [x] Geo utilities (`src/geo_utils.py`): precinct boundaries, ray-casting, haversine (merged into `main`)
- [x] Task 4 code (`src/task4_hotels.py`): hotel list, rates by site, cheapest options, precinct assignment, nearby alternatives, live calls with labelled cache fallback
- [x] Task 4 test run for July and December (60 hotels)
- [ ] Task 4 final run with about 800 hotels
- [ ] Task 4: confirm the months with Persons 1 and 2, and swap in the official Task 2 top-5 list
- [ ] Task 6: monthly temperatures combined with incident trends

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

df, message = search_hotels("2027-02-09", nights=3, max_price=200, n_hotels=20, live=True)
print(message)   # e.g. "Live prices for all 18 hotels."
```

- Returns `(DataFrame, message)`. The DataFrame holds only hotels within `max_price`, cheapest first.
- `live=True` calls Xotelo first. If Xotelo fails, cached prices are used and `message` says so, with their age.
- `live=False` answers from the cache only (no API calls).
- Raises `RuntimeError` if Xotelo is down and nothing is cached for those dates. The app should catch this and tell the user.
- `guests` is not supported yet: Xotelo prices are for its default room.

### Other functions

| Function | Purpose |
|---|---|
| `cheapest_options(df, max_price, month)` | `(cheapest hotel within budget, cheapest within budget outside that month's top-5 incident precincts)`. Either can be `None`. |
| `find_nearby(df, hotel_key, radius_km=2.0)` | Every other hotel within 2 km of the chosen hotel, cheapest first, with distance, precinct and savings. |
| `describe_sources(df)` | One sentence describing where the prices came from and how old they are. |
| `get_top5_precincts(month)` | **Temporary** stand-in for Person 1's Task 2 top-5 list, computed from `data/neighbourhood_month.parquet` (Task 1's real output). To be replaced by Task 2's official output. |
| `get_precinct_month_avg(month)` | **Temporary** stand-in for Task 2's per-precinct monthly averages (every precinct, not just the top 5). Used by Task 8 to rate each attraction's area. Returns a `pandas.Series` indexed by precinct. |

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

### Nearby table columns (`t4_nearby.csv`)

`stay_month`, `chosen_hotel`, `chosen_nightly`, `name`, `hotel_key`, `precinct`, `cheapest_nightly`, `cheapest_site`, `savings_per_night`, `total_savings`, `distance_km`.

`savings_per_night` is the chosen hotel's price minus the alternative's. Positive means the alternative is cheaper. Negative means it costs more.

### Caching

- Every Xotelo response is saved under `cache/xotelo/`, one JSON file per request.
- Error responses are never cached.
- The batch run (`python -m src.task4_hotels`) uses `live=False`, so it only fetches what is missing.

### Validation so far

60-hotel test runs. The first checks used placeholder dates (Jan 15 to 18, 2027). The July and December results come from the stays above.

- January: 60 hotels fetched, 59 with prices, 0 outside NYC precincts, 0 failed.
- July: 59 of 60 hotels priced. December: 54 of 60 priced. The December stay is under two weeks away, so some hotels are likely sold out.
- Cheapest hotel under $150 in all three test stays: West Side YMCA (precinct 20), at $72 a night in January, $101 in July and $121 in December.
- Top-5 incident precincts from the stand-in: July [75, 14, 44, 40, 43], December [75, 14, 40, 44, 43]. Same five precincts in a different order.
- Precinct checks: West Side YMCA (20, Upper West Side), Radio Hotel (34, Washington Heights), The FIDI Hotel (1), Ly New York Hotel (109, Flushing).
- Top-5 filter check: with the three cheapest hotels removed, the cheapest is ROW NYC (precinct 14, a top-5 precinct), and the cheapest outside the top 5 is The FIDI Hotel (precinct 1).
- Nearby (January): ROW NYC (Midtown) has 45 hotels within 2 km, while The FIDI Hotel has 2. July: 45 and 2. December: 41 and 1. The default Xotelo ranking clusters heavily in Midtown, which is why the final run will use more hotels.
- Fallback check: a live search, then the same search with `BASE_URL` pointed at an invalid host, returned cached prices with the message "The hotel price service did not respond for 4 of 4 hotels, so their prices are cached and up to 0.0 hours old."

### Open decisions

- Months: using July and December until Persons 1 and 2 confirm. If they change, only `STAYS` needs editing.
- Number of hotels for the final run (planned: about 800).
- Whether Xotelo supports a guests/adults parameter.

## Data sources

- NYC Police Precincts (NYC Open Data `y76i-bdw7`): https://data.cityofnewyork.us/resource/y76i-bdw7.geojson
- Xotelo API (NYC location key `g60763`, no key required): https://data.xotelo.com/api