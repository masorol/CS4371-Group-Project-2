Task 4 code and the geo utilities are ready to integrate. Full docs: `docs/person3_tasks4_6.md` on the `person3-hotels-weather` branch.

## For Task 5 (app), Person 4

`search_hotels` is the entry point:

    from src.task4_hotels import search_hotels, cheapest_options, find_nearby

    df, message = search_hotels("2027-02-09", nights=3, max_price=200, n_hotels=20, live=True)

- Returns `(DataFrame, message)`: hotels within budget, cheapest first, plus a sentence saying whether prices are live or cached (and how old). Show `message` to the user. The handout requires cached prices to be labelled with their age.
- `live=True` calls Xotelo and falls back to the cache if it fails. `live=False` answers from the cache only. The TA demo runs a live search, then the same request from cache.
- Raises `RuntimeError` if Xotelo is down and nothing is cached for those dates. Please catch it and show the message.
- `cheapest_options(df, max_price, month)` gives the cheapest hotel and the cheapest outside that month's top-5 incident precincts.
- `find_nearby(df, hotel_key)` gives every hotel within 2 km, cheapest first. Use it for "show me cheaper ones nearby."
- Use ~20 hotels for live searches so the demo finishes in about a minute.

## For Task 8, Person 2

    from src.geo_utils import load_precincts, find_precinct, haversine_km

- `find_precinct(lat, lon, load_precincts())` returns the precinct (int) for an attraction, or `None` if outside NYC.
- `haversine_km(lat1, lon1, lat2, lon2)` gives the distance for "hotels within 1 km."
- Hotel data: `outputs/t4_hotels.csv` (columns `lat`, `lon`, `precinct`, `cheapest_nightly`, `cheapest_site`, ...). The current file is a 60-hotel test run. I'll regenerate it with more hotels once we fix the months.

## Notes

- Run modules from the project root with `python -m`, e.g. `python -m src.task4_hotels`, so `from src...` imports work.
- Precinct numbers are ints everywhere, matching Person 1's parquet.
- `get_top5_precincts(month)` is a temporary stand-in for Task 2's top-5 list. Person 1: if your Task 2 code returns a list of 5 ints for a month, I'll switch to it.

## Still needed from the team

- [ ] Our two months for Tasks 2 and 8 (my final hotel run uses stays in those months)
- [ ] Task 2 top-5 output, to replace the stand-in