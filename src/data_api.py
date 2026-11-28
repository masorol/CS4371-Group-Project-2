"""The one place where the assistant and the app get their facts.

For every function it tries the real task module first (for example
src/task2_outlook.py with a get_outlook function). If that module does not
exist yet, it uses src/placeholders.py and marks the result as PLACEHOLDER,
so the app can be built and tested before the other tasks are finished.

Every function returns (DataFrame, meta), where meta says where the numbers
came from: {"source", "placeholder", "note"}.
"""
from __future__ import annotations

import importlib
from datetime import date

import pandas as pd

from src import placeholders

SOURCES = {
    "outlook": "NYPD Complaint Data Historic (NYC Open Data, qgea-i56i), "
               "occurrences 2022-2024, aggregated with Spark (Tasks 1-2)",
    "hotels": "Xotelo hotel rates API (location g60763), prices per booking site (Task 4)",
    "best_months": "city_temperature.csv (Homework 2/4), 2020-2024, plus Task 1 "
                   "incident totals 2022-2024 (Task 6)",
    "attractions": "(c) OpenStreetMap contributors via Overpass API, with Task 2 "
                   "incident averages and Task 4 hotels (Task 8)",
}

# function name -> (real module, kind of source)
_REAL = {
    "get_outlook": ("task2_outlook", "outlook"),
    "search_hotels": ("task4_hotels", "hotels"),
    "nearby_hotels": ("task4_hotels", "hotels"),
    "best_months": ("task6_best_months", "best_months"),
    "top_attractions": ("task8_attractions", "attractions"),
    "top_neighbourhoods": ("task8_attractions", "attractions"),
}


def _resolve(func_name: str):
    module, kind = _REAL[func_name]
    note = ""
    try:
        mod = importlib.import_module(f"src.{module}")
        fn = getattr(mod, func_name)
        return fn, {"source": SOURCES[kind], "placeholder": False, "note": note}
    except ModuleNotFoundError as exc:
        if exc.name != f"src.{module}":
            note = f"src/{module}.py failed to import: {exc}"
    except (ImportError, AttributeError) as exc:
        note = f"src/{module}.py is missing {func_name}: {exc}"
    fn = getattr(placeholders, func_name)
    return fn, {"source": "PLACEHOLDER data (real module not ready yet) - " + SOURCES[kind],
                "placeholder": True, "note": note}


def status() -> dict:
    """Which functions are real and which are still placeholders."""
    return {name: not _resolve(name)[1]["placeholder"] for name in _REAL}


def get_outlook(month: int):
    fn, meta = _resolve("get_outlook")
    return fn(month), meta


def search_hotels(check_in: date, nights: int, guests: int = 2,
                  max_price: float | None = None, live: bool = False):
    fn, meta = _resolve("search_hotels")
    df = fn(check_in, nights, guests, max_price, live)
    meta = dict(meta)
    if len(df) and "retrieved_at" in df:
        meta["retrieved_at"] = str(df["retrieved_at"].min())
        meta["from_cache"] = bool(df["from_cache"].any()) if "from_cache" in df else None
    return df, meta


def nearby_hotels(hotel_key: str, check_in: date, nights: int, guests: int = 2,
                  radius_km: float = 2.0):
    fn, meta = _resolve("nearby_hotels")
    return fn(hotel_key, check_in, nights, guests, radius_km), meta


def best_months():
    fn, meta = _resolve("best_months")
    return fn(), meta


def top_attractions(month: int, max_price: float | None = None):
    fn, meta = _resolve("top_attractions")
    return fn(month, max_price), meta


def top_neighbourhoods(month: int, max_price: float | None = None):
    fn, meta = _resolve("top_neighbourhoods")
    return fn(month, max_price), meta


def df_records(df: pd.DataFrame, limit: int | None = None) -> list[dict]:
    """DataFrame -> JSON-safe list of dicts (NaN becomes None)."""
    if limit is not None:
        df = df.head(limit)
    return [{k: (None if (isinstance(v, float) and v != v) else
                 (v.item() if hasattr(v, "item") else v))
             for k, v in row.items()} for row in df.to_dict(orient="records")]
