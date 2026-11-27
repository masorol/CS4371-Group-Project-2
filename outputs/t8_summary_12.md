# Places to visit and best neighbourhoods -- December

**Sources:** OpenStreetMap Overpass API (attractions, retrieved 2026-11-27T07:00:33+00:00); Task 4 hotel prices (retrieved 2026-11-27T13:14:50+00:00); Task 2 stand-in incident averages from `data/neighbourhood_month.parquet` (NYPD data, 2022-2024). Map data (c) OpenStreetMap contributors, ODbL.

## Top 10 places to visit

| rank | osm_type | osm_id | name | category | precinct | incidents_avg | hotels_within_1km | cheapest_hotel_name | cheapest_hotel_nightly | has_wikipedia | score |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | way | 546663191 | Gapstow Bridge | attraction | 22 | 14.3 | 37 | West Side YMCA | 121.0 | True | 5.0 |
| 2 | way | 354587586 | Central Park Zoo | zoo | 22 | 14.3 | 29 | West Side YMCA | 121.0 | True | 5.0 |
| 3 | way | 585788256 | Central Park Carousel | attraction | 22 | 14.3 | 28 | West Side YMCA | 121.0 | True | 5.0 |
| 4 | node | 3278932286 | Delacorte Musical Clock | attraction | 22 | 14.3 | 27 | West Side YMCA | 121.0 | True | 5.0 |
| 5 | way | 580516390 | Bow Bridge | attraction | 22 | 14.3 | 4 | West Side YMCA | 121.0 | True | 5.0 |
| 6 | way | 958635828 | Bethesda Fountain | attraction | 22 | 14.3 | 3 | West Side YMCA | 121.0 | True | 5.0 |
| 7 | way | 427818536 | Central Park | park | 22 | 14.3 | 2 | The Carlyle, A Rosewood Hotel | 2225.0 | True | 5.0 |
| 8 | way | 179685272 | Cleopatra's Needle | attraction | 22 | 14.3 | 2 | The Carlyle, A Rosewood Hotel | 2225.0 | True | 5.0 |
| 9 | relation | 3698894 | Metropolitan Museum of Art | museum | 22 | 14.3 | 2 | The Carlyle, A Rosewood Hotel | 2225.0 | True | 5.0 |
| 10 | way | 39243913 | Blockhouse No. 1 | attraction | 22 | 14.3 | 1 | HI New York City Hostel | 76.0 | True | 5.0 |

## Top 5 neighbourhoods to stay in or explore

| rank | precinct | n_attractions | incidents_avg | hotels_in_budget | median_nightly | score |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 10 | 138 | 314.7 | 1 | 129.0 | 4.05 |
| 2 | 5 | 76 | 394.3 | 2 | 145.0 | 3.46 |
| 3 | 1 | 129 | 714.0 | 0 |  | 2.8 |
| 4 | 109 | 80 | 902.7 | 2 | 117.5 | 2.76 |
| 5 | 20 | 29 | 297.7 | 1 | 121.0 | 2.38 |

## Summary

_The LLM summary did not pass the number check twice, so it is left out here. See the tables above for the grounded numbers._
