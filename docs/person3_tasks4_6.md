# Person 3: Hotel Search (Task 4) and Best Month to Visit (Task 6)

Owner: Sal (Salamot Fakoya)
Branch: `person3-hotels-weather`

## Status

- [x] Geo utilities (`src/geo_utils.py`): precinct boundaries, ray-casting, haversine
- [ ] Task 4: Xotelo hotel list and rates, precinct assignment, nearby alternatives
- [ ] Task 6: Monthly temperatures combined with incident trends

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Geo utilities (`src/geo_utils.py`)

Used by Tasks 4, 5 and 8.

| Function | Input | Output |
|---|---|---|
| `load_precincts()` | none | dict of precinct number (int) to MultiPolygon coordinates |
| `find_precinct(lat, lon, precincts)` | latitude, longitude, output of `load_precincts()` | precinct number (int), or `None` if outside NYC |
| `haversine_km(lat1, lon1, lat2, lon2)` | two points | distance in km |

Example:

```python
from src.geo_utils import load_precincts, find_precinct, haversine_km

precincts = load_precincts()
find_precinct(40.7484, -73.9857, precincts)    # 14 (Empire State Building)
haversine_km(40.7580, -73.9855, 40.7484, -73.9857)  # about 1.07
```

Notes:
- Boundaries come from NYC Open Data dataset `y76i-bdw7`, saved to `data/precincts.geojson` (78 precincts).
- Precinct numbers are ints, matching `precinct` in `neighbourhood_month.parquet`.
- GeoJSON stores `[lon, lat]`, but `find_precinct` and `haversine_km` take lat first.

## Validation

| Test point | Expected | Result |
|---|---|---|
| Empire State Building (40.7484, -73.9857) | 14 | 14 |
| Central Park (40.7812, -73.9665) | 22 | 22 |
| Jersey City (40.7282, -74.0776) | None | None |

## Data sources

- NYC Police Precincts: https://data.cityofnewyork.us/resource/y76i-bdw7.geojson
- Xotelo API (NYC location key `g60763`): https://data.xotelo.com/api