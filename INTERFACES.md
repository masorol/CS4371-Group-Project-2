# Function interfaces between the tasks and the app

The web app (Task 5) and the evaluation (Task 7) call these functions through
`src/data_api.py`. Until a module exists, the app uses fake data from
`src/placeholders.py` (shown on screen as **PLACEHOLDER**). As soon as you add
your module with these exact names, the app uses your real data with no other
change. The sidebar of the app shows which functions are real.

Neighbourhoods are NYPD precincts (`addr_pct_cd`), written as `"Precinct 14"`
everywhere, so the tables join correctly.

Each function returns a **pandas DataFrame** with at least the listed columns
(extra columns are fine). See `src/placeholders.py` for a working example.

## Person 1: `src/task2_outlook.py`

```python
def get_outlook(month: int) -> pd.DataFrame   # 15 rows
```
| column | meaning |
|---|---|
| month | 1-12 |
| list_type | `"most"`, `"largest_rise"` or `"fewest"` (5 rows each) |
| precinct | `"Precinct 14"` |
| avg_incidents | average incidents in that month over 2022-2024 |
| share_pct | share of the city total that month, in % |
| seasonal_ratio | month average / average over all months |
| persons, property, other | category split (average per month) |

Task 1 must use the categories **persons / property / other** (not felony/misdemeanor/violation).
Please commit `neighbourhood_month.parquet` to `outputs/` (`data/*.parquet` is git-ignored).

## Person 3: `src/task4_hotels.py`

```python
def search_hotels(check_in: date, nights: int, guests: int = 2,
                  max_price: float | None = None, live: bool = False) -> pd.DataFrame
def nearby_hotels(hotel_key: str, check_in: date, nights: int, guests: int = 2,
                  radius_km: float = 2.0) -> pd.DataFrame
```
`search_hotels` returns **all** hotels found (the app filters by budget), cheapest first:
`hotel_key, name, lat, lon, neighbourhood, price_<site>` (one column per booking site,
e.g. `price_Booking.com`), `cheapest_site, cheapest_price, total, retrieved_at` (ISO time),
`from_cache` (bool). With `live=False`, reuse the cache; if the API fails, return cached
prices with `from_cache=True`.

`nearby_hotels` returns the other hotels within `radius_km`, cheapest first:
`hotel_key, name, neighbourhood, cheapest_price, cheapest_site, distance_km, retrieved_at`.

## Person 3: `src/task6_best_months.py`

```python
def best_months() -> pd.DataFrame   # 12 rows, best first
```
`month, month_name, avg_temp_f, temp_distance, avg_incidents, score, rank`

## Person 2: `src/task8_attractions.py`

```python
def top_attractions(month: int, max_price: float | None = None) -> pd.DataFrame
def top_neighbourhoods(month: int, max_price: float | None = None) -> pd.DataFrame
```
`top_attractions`: **all** ranked attractions, best first (the map shows all, tables the top 10):
`name, lat, lon, neighbourhood, has_wikipedia, nbhd_avg_incidents, hotels_within_1km,
cheapest_hotel, cheapest_hotel_price, score, rank`

`top_neighbourhoods`: top 5, best first:
`neighbourhood, attractions, avg_incidents, hotels_in_budget, median_price, score, rank`

## Shared helpers in `src/utils.py` (use them in Tasks 2, 3 and 8)

- `call_llm(system, user, json_mode=False)`: gpt-oss-120b on Groq, temperature 0,
  cached in `cache/groq/`, 1 s throttle, OpenRouter backup.
- `parse_json_reply(text)`: JSON from an LLM reply.
- `number_check(answer, data, extra_allowed)`: returns `(passed, bad_numbers)`. This is the
  same number check for Tasks 2, 5 and 8.
- `cache_read / cache_write / throttle`: for your own API calls (Xotelo, Overpass, Socrata).
