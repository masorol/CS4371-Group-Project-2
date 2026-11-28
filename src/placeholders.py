"""PLACEHOLDER data with the same function names and columns as the real
task modules (see INTERFACES.md). The app uses these only until the real
module exists, and labels every number from here as PLACEHOLDER on screen.

Nothing in this file is real data. Do not use it in the report.
"""
from __future__ import annotations

import math
import random
from datetime import date, timedelta

import pandas as pd

from src.utils import now_iso

MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July",
               "August", "September", "October", "November", "December"]

# Real NYPD precinct numbers, fake figures.
PRECINCTS = [1, 5, 6, 7, 9, 10, 13, 14, 17, 18, 19, 20, 23, 24, 25, 26, 28, 30,
             32, 33, 34, 40, 43, 44, 46, 52, 60, 61, 67, 75, 77, 84, 90, 94,
             103, 108, 109, 112, 114, 120]

# Rough Manhattan precinct centres, used only to place fake hotels.
_CENTRES = {1: (40.7128, -74.0090), 5: (40.7165, -73.9970), 6: (40.7340, -74.0050),
            7: (40.7160, -73.9840), 9: (40.7265, -73.9840), 10: (40.7470, -74.0010),
            13: (40.7390, -73.9840), 14: (40.7540, -73.9930), 17: (40.7540, -73.9700),
            18: (40.7640, -73.9870), 19: (40.7710, -73.9590), 20: (40.7780, -73.9800)}


def _rng(*parts) -> random.Random:
    return random.Random("|".join(map(str, parts)))


def _precinct_month_avg(pct: int, month: int) -> float:
    r = _rng("level", pct)
    base = r.uniform(80, 420)
    season = 1 + 0.15 * math.sin((month - 4) / 12 * 2 * math.pi) * r.uniform(0.5, 1.5)
    return round(base * season, 1)


# ---------------------------------------------------------------- Task 2
def get_outlook(month: int) -> pd.DataFrame:
    rows = []
    city_total = sum(_precinct_month_avg(p, month) for p in PRECINCTS)
    for p in PRECINCTS:
        avg = _precinct_month_avg(p, month)
        yearly = sum(_precinct_month_avg(p, m) for m in range(1, 13)) / 12
        persons = round(avg * _rng("p", p).uniform(0.25, 0.4), 1)
        prop = round(avg * _rng("q", p).uniform(0.4, 0.55), 1)
        rows.append({"precinct": f"Precinct {p}", "avg_incidents": avg,
                     "share_pct": round(100 * avg / city_total, 2),
                     "seasonal_ratio": round(avg / yearly, 3),
                     "persons": persons, "property": prop,
                     "other": round(avg - persons - prop, 1)})
    df = pd.DataFrame(rows)
    most = df.nlargest(5, "avg_incidents").assign(list_type="most")
    rise = df.nlargest(5, "seasonal_ratio").assign(list_type="largest_rise")
    fewest = df.nsmallest(5, "avg_incidents").assign(list_type="fewest")
    out = pd.concat([most, rise, fewest], ignore_index=True)
    out.insert(0, "month", month)
    return out[["month", "list_type", "precinct", "avg_incidents", "share_pct",
                "seasonal_ratio", "persons", "property", "other"]]


# ---------------------------------------------------------------- Task 4
SITES = ["Booking.com", "Agoda", "Trip.com", "Hotel website"]


def _hotels_base() -> list[dict]:
    hotels = []
    for i in range(24):
        r = _rng("hotel", i)
        pct = r.choice(list(_CENTRES))
        lat, lon = _CENTRES[pct]
        hotels.append({"hotel_key": f"PH{i:03d}", "name": f"Placeholder Hotel {i + 1}",
                       "lat": round(lat + r.uniform(-0.006, 0.006), 5),
                       "lon": round(lon + r.uniform(-0.006, 0.006), 5),
                       "neighbourhood": f"Precinct {pct}",
                       "base": r.uniform(110, 420)})
    return hotels


def search_hotels(check_in: date, nights: int, guests: int = 2,
                  max_price: float | None = None, live: bool = False) -> pd.DataFrame:
    rows = []
    stamp = now_iso()
    for h in _hotels_base():
        r = _rng("price", h["hotel_key"], check_in, guests)
        prices = {s: round(h["base"] * r.uniform(0.92, 1.12), 2) for s in SITES
                  if r.random() > 0.15}
        if not prices:
            continue
        site = min(prices, key=prices.get)
        row = {k: h[k] for k in ("hotel_key", "name", "lat", "lon", "neighbourhood")}
        row.update({f"price_{s}": prices.get(s) for s in SITES})
        row.update({"cheapest_site": site, "cheapest_price": prices[site],
                    "total": round(prices[site] * nights, 2),
                    "retrieved_at": stamp, "from_cache": not live})
        rows.append(row)
    return pd.DataFrame(rows).sort_values("cheapest_price", ignore_index=True)


def haversine_km(lat1, lon1, lat2, lon2) -> float:
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def nearby_hotels(hotel_key: str, check_in: date, nights: int, guests: int = 2,
                  radius_km: float = 2.0) -> pd.DataFrame:
    df = search_hotels(check_in, nights, guests)
    me = df[df["hotel_key"] == hotel_key]
    if me.empty:
        return df.iloc[0:0]
    lat, lon = me.iloc[0]["lat"], me.iloc[0]["lon"]
    df = df[df["hotel_key"] != hotel_key].copy()
    df["distance_km"] = [round(haversine_km(lat, lon, a, b), 2)
                         for a, b in zip(df["lat"], df["lon"])]
    df = df[df["distance_km"] <= radius_km].sort_values("cheapest_price")
    return df[["hotel_key", "name", "neighbourhood", "cheapest_price", "cheapest_site",
               "distance_km", "retrieved_at"]].reset_index(drop=True)


# ---------------------------------------------------------------- Task 6
def best_months() -> pd.DataFrame:
    rows = []
    for m in range(1, 13):
        temp = round(54.5 - 22 * math.cos((m - 1) / 12 * 2 * math.pi), 1)
        inc = round(sum(_precinct_month_avg(p, m) for p in PRECINCTS), 0)
        rows.append({"month": m, "month_name": MONTH_NAMES[m - 1], "avg_temp_f": temp,
                     "temp_distance": round(abs(temp - 70), 1), "avg_incidents": inc})
    df = pd.DataFrame(rows)
    t = df["temp_distance"] / df["temp_distance"].max()
    i = (df["avg_incidents"] - df["avg_incidents"].min()) / (
        df["avg_incidents"].max() - df["avg_incidents"].min())
    df["score"] = (1 - (0.7 * t + 0.3 * i)).round(3)
    df["rank"] = df["score"].rank(ascending=False, method="first").astype(int)
    return df.sort_values("rank", ignore_index=True)


# ---------------------------------------------------------------- Task 8
_ATTRACTIONS = [
    ("Placeholder Museum A", 40.7794, -73.9632, True), ("Placeholder Park B", 40.7829, -73.9654, True),
    ("Placeholder Gallery C", 40.7614, -73.9776, True), ("Placeholder Viewpoint D", 40.7484, -73.9857, True),
    ("Placeholder Attraction E", 40.7580, -73.9855, False), ("Placeholder Museum F", 40.7813, -73.9740, True),
    ("Placeholder Park G", 40.7480, -74.0048, True), ("Placeholder Memorial H", 40.7115, -74.0134, True),
    ("Placeholder Gallery I", 40.7397, -74.0080, False), ("Placeholder Square J", 40.7359, -73.9911, True),
    ("Placeholder Museum K", 40.7180, -73.9990, False), ("Placeholder Park L", 40.7308, -73.9973, True),
    ("Placeholder Attraction M", 40.7527, -73.9772, True), ("Placeholder Garden N", 40.7536, -73.9832, False),
]


def top_attractions(month: int, max_price: float | None = None) -> pd.DataFrame:
    hotels = search_hotels(date.today() + timedelta(days=30), 1)
    level = {f"Precinct {p}": _precinct_month_avg(p, month) for p in PRECINCTS}
    rows = []
    for name, lat, lon, wiki in _ATTRACTIONS:
        dist = [haversine_km(lat, lon, a, b) for a, b in zip(hotels["lat"], hotels["lon"])]
        near = hotels[[d <= 1.0 for d in dist]]
        nb = min(_CENTRES, key=lambda p: haversine_km(lat, lon, *_CENTRES[p]))
        cheapest = near.nsmallest(1, "cheapest_price")
        rows.append({"name": name, "lat": lat, "lon": lon, "neighbourhood": f"Precinct {nb}",
                     "has_wikipedia": wiki, "nbhd_avg_incidents": level[f"Precinct {nb}"],
                     "hotels_within_1km": len(near),
                     "cheapest_hotel": cheapest["name"].iloc[0] if len(cheapest) else None,
                     "cheapest_hotel_price": cheapest["cheapest_price"].iloc[0] if len(cheapest) else None})
    df = pd.DataFrame(rows)
    df["score"] = (df["has_wikipedia"].astype(int) * 2 + df["hotels_within_1km"].clip(upper=5) * 0.5
                   - df["nbhd_avg_incidents"] / df["nbhd_avg_incidents"].max()).round(3)
    df["rank"] = df["score"].rank(ascending=False, method="first").astype(int)
    return df.sort_values("rank", ignore_index=True)


def top_neighbourhoods(month: int, max_price: float | None = None) -> pd.DataFrame:
    att = top_attractions(month, max_price)
    hotels = search_hotels(date.today() + timedelta(days=30), 1)
    if max_price:
        hotels = hotels[hotels["cheapest_price"] <= max_price]
    rows = []
    for nb, grp in att.groupby("neighbourhood"):
        h = hotels[hotels["neighbourhood"] == nb]
        rows.append({"neighbourhood": nb, "attractions": len(grp),
                     "avg_incidents": grp["nbhd_avg_incidents"].iloc[0],
                     "hotels_in_budget": len(h),
                     "median_price": round(h["cheapest_price"].median(), 2) if len(h) else None})
    df = pd.DataFrame(rows)
    df["score"] = (df["attractions"] + df["hotels_in_budget"] * 0.5
                   - df["avg_incidents"] / df["avg_incidents"].max()).round(3)
    df["rank"] = df["score"].rank(ascending=False, method="first").astype(int)
    return df.sort_values("rank", ignore_index=True).head(5)
