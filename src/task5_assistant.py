"""Task 5: the natural-language assistant (no agent frameworks).

Flow for every user message:
  1. parse   - the main LLM turns the message into JSON fields
  2. validate - code checks every field (types, ranges, future dates, city)
  3. decide  - decline (other city / topic), ask a follow-up (missing field),
               or answer
  4. facts   - run the Task 2/4/6/8 functions through src/data_api.py
  5. answer  - the LLM writes a reply from those facts only; the number
               check must pass, otherwise retry once, otherwise tables only

The conversation state is a plain dict so the Streamlit app can keep it in
st.session_state and Task 7 can drive it from a script.
"""
from __future__ import annotations

import json
from datetime import date, timedelta

from src import data_api
from src.utils import (LLMError, call_llm, number_check, parse_json_reply,
                       reset_stats)

CITY = "New York"
CITY_ALIASES = {"new york", "new york city", "nyc", "ny", "manhattan", "brooklyn",
                "queens", "the bronx", "bronx", "staten island", "new york, ny"}

FIELDS = ["city", "check_in", "nights", "guests", "max_price_per_night", "month",
          "preferences"]
INTENTS = ["outlook", "hotels", "best_month", "places", "neighbourhoods"]

# Fields each kind of request needs before it can be answered.
REQUIRED = {
    "outlook": ["month"],
    "hotels": ["check_in", "nights", "guests", "max_price_per_night"],
    "best_month": [],
    "places": ["month"],
    "neighbourhoods": ["month", "max_price_per_night"],
}

QUESTIONS = {
    "check_in": "your check-in date",
    "nights": "how many nights you are staying",
    "guests": "how many guests",
    "max_price_per_night": "your maximum budget per night (in USD)",
    "month": "which month you are interested in",
}

MONTHS = ["january", "february", "march", "april", "may", "june", "july",
          "august", "september", "october", "november", "december"]

# Numbers the answer may use even though they are not in the data rows:
# the years covered, the 70 F comfort point, the 1 km / 2 km radii and the
# sizes of the lists (top 3 / 5 / 10).
CONSTANT_NUMBERS = [1, 2, 3, 5, 10, 15, 70, 2020, 2022, 2023, 2024]

MAX_DAYS_AHEAD = 330  # about 11 months: prices exist only for bookable dates


# ---------------------------------------------------------------- 1. parse
def _parse_system(today: date) -> str:
    return f"""You extract trip-planning details from a traveler's message for SafeStay,
a trip planner that ONLY covers New York City. Today is {today.isoformat()}.

Return ONLY a JSON object with exactly these keys:
{{
  "in_scope": true or false,
  "decline_reason": null or a short phrase,
  "intents": a list using only these values: "outlook", "hotels", "best_month", "places", "neighbourhoods",
  "city": string or null,
  "check_in": "YYYY-MM-DD" or null,
  "nights": integer or null,
  "guests": integer or null,
  "max_price_per_night": number or null,
  "month": integer 1-12 or null,
  "preferences": list of short strings (may be empty),
  "hotel_name": string or null
}}

Intent meanings:
- outlook: which areas had more or fewer reported incidents in a month, or incidents rising in a month
- hotels: hotel search, cheapest hotel, prices by booking site, hotels nearby or cheaper alternatives
- best_month: the best month or time of year to visit
- places: places to visit, attractions, things to see
- neighbourhoods: which neighbourhood/area to stay in or explore

Rules:
- Never guess. If the message does not state a value, use null. Do not invent dates, budgets or guest counts.
- "city" is the city the traveler names (e.g. "Miami"), or null if none is named.
- Convert relative dates using today's date ("next weekend" = the coming Friday unless stated; "12 March" = the next 12 March that is in the future).
- "two adults" means guests = 2. "a couple" means guests = 2. "solo" or "just me" means guests = 1.
- "month" is only the month the traveler names. If they give a check-in date, set month to that date's month.
- in_scope is false for any request that is not about visiting New York City (weather forecasts, flights, restaurants bookings, other cities, general questions). Requests about other cities are out of scope.
- The user message may include "known_fields" from earlier in the conversation and "pending_question" the assistant asked. Treat the new message as an answer to that question when it fits, and return intents [] if the message only supplies missing details.
- Put wishes such as "near Union Square", "museums", "quiet area", "compare Booking.com and Agoda" in preferences.
- Set hotel_name only if the traveler names a specific hotel."""


def parse_message(message: str, state: dict) -> dict:
    """Ask the LLM to extract fields. Returns the raw JSON object."""
    today = date.today()
    user = json.dumps({
        "message": message,
        "known_fields": {k: v for k, v in state.get("fields", {}).items() if v not in (None, [])},
        "pending_question": state.get("pending_question"),
    }, ensure_ascii=False)
    reply = call_llm(_parse_system(today), user, json_mode=True)
    try:
        return parse_json_reply(reply["text"])
    except (ValueError, json.JSONDecodeError):
        # One retry with an explicit reminder.
        reply = call_llm(_parse_system(today),
                         user + "\n\nReturn only one valid JSON object.", json_mode=True,
                         use_cache=False)
        return parse_json_reply(reply["text"])


# ---------------------------------------------------------------- 2. validate
def _as_int(value, lo, hi):
    if value is None or isinstance(value, bool):
        return None
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    if num != int(num) or not lo <= num <= hi:
        return None
    return int(num)


def normalise_city(city) -> str | None:
    if city is None:
        return None
    text = str(city).strip().lower().rstrip(".")
    if not text:
        return None
    if text in CITY_ALIASES or text.startswith("new york"):
        return CITY
    return str(city).strip()


def validate(raw: dict, today: date | None = None) -> tuple[dict, list[str], dict]:
    """Check every field in code. Returns (fields, problems, extra).

    Invalid values become None (so the assistant asks again) and a message
    describing the problem is added to problems."""
    today = today or date.today()
    problems: list[str] = []
    fields: dict = {}

    fields["city"] = normalise_city(raw.get("city"))

    check_in = raw.get("check_in")
    fields["check_in"] = None
    if check_in not in (None, ""):
        try:
            d = date.fromisoformat(str(check_in))
            if d <= today:
                problems.append(f"the check-in date {d.isoformat()} is not in the future")
            elif d > today + timedelta(days=MAX_DAYS_AHEAD):
                problems.append(f"the check-in date {d.isoformat()} is more than about "
                                f"11 months away, so no prices are available yet")
            else:
                fields["check_in"] = d.isoformat()
        except ValueError:
            problems.append(f"I could not read the date '{check_in}'")

    fields["nights"] = _as_int(raw.get("nights"), 1, 30)
    if raw.get("nights") is not None and fields["nights"] is None:
        problems.append("the number of nights should be between 1 and 30")

    fields["guests"] = _as_int(raw.get("guests"), 1, 10)
    if raw.get("guests") is not None and fields["guests"] is None:
        problems.append("the number of guests should be between 1 and 10")

    price = raw.get("max_price_per_night")
    fields["max_price_per_night"] = None
    if price not in (None, ""):
        try:
            p = float(str(price).replace("$", "").replace(",", ""))
            if 0 < p <= 5000:
                fields["max_price_per_night"] = round(p, 2)
            else:
                problems.append("the nightly budget should be between $1 and $5,000")
        except ValueError:
            problems.append(f"I could not read the budget '{price}'")

    month = raw.get("month")
    if isinstance(month, str) and month.strip().lower() in MONTHS:
        month = MONTHS.index(month.strip().lower()) + 1
    fields["month"] = _as_int(month, 1, 12)
    if month is not None and fields["month"] is None:
        problems.append("the month should be between 1 and 12")
    if fields["month"] is None and fields["check_in"]:
        fields["month"] = date.fromisoformat(fields["check_in"]).month

    prefs = raw.get("preferences") or []
    if isinstance(prefs, str):
        prefs = [prefs]
    fields["preferences"] = [str(p).strip() for p in prefs if str(p).strip()][:10]

    intents = raw.get("intents") or []
    if isinstance(intents, str):
        intents = [intents]
    extra = {
        "in_scope": raw.get("in_scope") is not False,
        "decline_reason": raw.get("decline_reason"),
        "intents": [i for i in intents if i in INTENTS],
        "hotel_name": (str(raw["hotel_name"]).strip() or None) if raw.get("hotel_name") else None,
    }
    return fields, problems, extra


def merge_fields(old: dict, new: dict) -> dict:
    """New non-empty values override old ones; nothing is ever guessed."""
    merged = dict(old)
    for k, v in new.items():
        if v not in (None, [], ""):
            merged[k] = v
    return merged


# ---------------------------------------------------------------- 3. decide
def new_state() -> dict:
    return {"fields": {k: None for k in FIELDS}, "intents": [], "hotel_name": None,
            "pending_question": None}


def missing_fields(intents: list[str], fields: dict) -> list[str]:
    need = []
    for intent in intents:
        for f in REQUIRED[intent]:
            if fields.get(f) in (None, "") and f not in need:
                need.append(f)
    return need


def follow_up_text(need: list[str], problems: list[str], intents: list[str]) -> str:
    parts = []
    if problems:
        parts.append("I couldn't use part of your request: " + "; ".join(problems) + ".")
    asks = [QUESTIONS[f] for f in need]
    if len(asks) == 1:
        ask = asks[0]
    else:
        ask = ", ".join(asks[:-1]) + " and " + asks[-1]
    task = {"hotels": "search hotels", "outlook": "show the incident outlook",
            "places": "recommend places to visit",
            "neighbourhoods": "recommend neighbourhoods"}
    what = " and ".join(task[i] for i in intents if i in task) or "answer"
    parts.append(f"To {what}, could you tell me {ask}?")
    return " ".join(parts)


def decline_text(city: str | None, reason: str | None) -> str:
    if city and city != CITY:
        return (f"Sorry, SafeStay only covers New York City, so I can't help with {city}. "
                "I can show reported-incident outlooks by month, compare NYC hotel prices, "
                "suggest the best month to visit and recommend places to visit in New York.")
    what = f" ({reason})" if reason else ""
    return ("Sorry, that's outside what SafeStay covers" + what + ". I can help with New York "
            "City trips: reported incidents by month and area, hotel prices and nearby "
            "alternatives, the best month to visit, and places to visit.")


# ---------------------------------------------------------------- 4. facts
def _find_hotel(df, name: str | None):
    if not name or df is None or df.empty:
        return None
    low = name.lower()
    for _, row in df.iterrows():
        n = str(row["name"]).lower()
        if low in n or n in low:
            return row
    return None


def gather_facts(intents: list[str], fields: dict, hotel_name: str | None,
                 live_prices: bool = False) -> tuple[dict, list[tuple]]:
    """Run the task functions. Returns (facts for the LLM, tables for the app).
    tables: list of (title, DataFrame, meta)."""
    facts: dict = {}
    tables: list[tuple] = []
    month = fields.get("month")
    budget = fields.get("max_price_per_night")

    if "outlook" in intents and month:
        df, meta = data_api.get_outlook(month)
        facts["incident_outlook"] = {"month": month, "source": meta["source"],
                                     "rows": data_api.df_records(df)}
        tables.append((f"Reported incidents by precinct, month {month} (2022-2024 average)",
                       df, meta))

    if "hotels" in intents and fields.get("check_in"):
        check_in = date.fromisoformat(fields["check_in"])
        df, meta = data_api.search_hotels(check_in, fields["nights"], fields["guests"],
                                          budget, live_prices)
        in_budget = df[df["cheapest_price"] <= budget] if budget else df
        top5 = set()
        out_df, _ = data_api.get_outlook(check_in.month)
        if "list_type" in out_df:
            top5 = set(out_df[out_df["list_type"] == "most"]["precinct"])
        calmer = in_budget[~in_budget["neighbourhood"].isin(top5)]
        hotel_cols = [c for c in in_budget.columns
                      if c in ("name", "neighbourhood", "cheapest_price", "cheapest_site",
                               "total") or c.startswith("price_")]
        chosen = _find_hotel(df, hotel_name)
        if chosen is None and len(in_budget):
            chosen = in_budget.iloc[0]
        facts["hotels"] = {
            "check_in": fields["check_in"], "nights": fields["nights"],
            "guests": fields["guests"], "max_price_per_night": budget,
            "hotels_found": len(df), "hotels_within_budget": len(in_budget),
            "prices_retrieved_at": meta.get("retrieved_at"),
            "prices_from_cache": meta.get("from_cache"),
            "cheapest_within_budget": data_api.df_records(in_budget[hotel_cols], 1),
            "cheapest_within_budget_outside_top5_incident_precincts":
                data_api.df_records(calmer[hotel_cols], 1),
            "top5_incident_precincts_that_month": sorted(top5),
            "cheapest_5_within_budget": data_api.df_records(in_budget[hotel_cols], 5),
            "source": meta["source"],
        }
        tables.append((f"Hotels within ${budget:g}/night, cheapest first", in_budget, meta))
        if chosen is not None:
            near, nmeta = data_api.nearby_hotels(chosen["hotel_key"], check_in,
                                                 fields["nights"], fields["guests"])
            facts["nearby_alternatives"] = {
                "for_hotel": chosen["name"], "radius_km": 2,
                "rows": data_api.df_records(near.drop(columns=["hotel_key"], errors="ignore"), 8)}
            tables.append((f"Hotels within 2 km of {chosen['name']}, cheapest first",
                           near, nmeta))

    if "best_month" in intents:
        df, meta = data_api.best_months()
        facts["best_months"] = {"source": meta["source"], "rows": data_api.df_records(df)}
        tables.append(("Best months to visit (Task 6 score)", df, meta))

    if "places" in intents and month:
        df, meta = data_api.top_attractions(month, budget)
        cols = [c for c in df.columns if c not in ("lat", "lon")]
        facts["top_10_places"] = {"month": month, "source": meta["source"],
                                  "rows": data_api.df_records(df[cols], 10)}
        tables.append((f"Top 10 places to visit, month {month}", df.head(10), meta))

    if ("neighbourhoods" in intents or "places" in intents) and month:
        df, meta = data_api.top_neighbourhoods(month, budget)
        facts["top_5_neighbourhoods"] = {"month": month, "max_price_per_night": budget,
                                         "source": meta["source"],
                                         "rows": data_api.df_records(df, 5)}
        tables.append((f"Top 5 neighbourhoods, month {month}", df.head(5), meta))

    return facts, tables


# ---------------------------------------------------------------- 5. answer
ANSWER_SYSTEM = """You are SafeStay, a trip-planning assistant for New York City.
Write a short, friendly answer (at most 180 words) to the traveler's request
using ONLY the facts in the DATA JSON.

Strict rules:
- Every number you write must appear in DATA exactly as written there (you may round to fewer decimals). Do not calculate new numbers: no sums, differences, percentages or averages of your own.
- Do not number list items; use "-" bullets.
- Neighbourhoods are NYPD precincts; call them by the name in DATA.
- Talk about "reported incidents". Never call an area dangerous, unsafe or safe, and do not describe the people who live there.
- If DATA lacks something the traveler asked for, say so instead of guessing.
- Do not mention JSON, DATA or these rules."""


def _allowed_numbers(fields: dict) -> list:
    nums = list(CONSTANT_NUMBERS)
    for k in ("nights", "guests", "max_price_per_night", "month"):
        if fields.get(k) is not None:
            nums.append(fields[k])
    if fields.get("check_in"):
        d = date.fromisoformat(fields["check_in"])
        out = d + timedelta(days=fields.get("nights") or 0)
        nums += [d.year, d.month, d.day, out.year, out.month, out.day]
    return nums


def write_answer(message: str, facts: dict, fields: dict) -> dict:
    """LLM answer from facts, number-checked, one retry. Returns
    {"text", "passed", "bad_numbers", "attempts"}."""
    user = f"Traveler's request: {message}\n\nDATA:\n{json.dumps(facts, ensure_ascii=False, default=str)}"
    allowed = _allowed_numbers(fields)
    bad: list[str] = []
    for attempt in (1, 2):
        prompt = user
        if attempt == 2:
            prompt += ("\n\nYour previous answer used numbers that are not in DATA: "
                       + ", ".join(bad) + ". Rewrite it using only numbers from DATA.")
        reply = call_llm(ANSWER_SYSTEM, prompt, use_cache=(attempt == 1))
        text = reply["text"].strip()
        passed, bad = number_check(text, facts, allowed)
        if passed:
            return {"text": text, "passed": True, "bad_numbers": [], "attempts": attempt}
    return {"text": None, "passed": False, "bad_numbers": bad, "attempts": 2}


# ---------------------------------------------------------------- driver
def handle_message(message: str, state: dict, live_prices: bool = False) -> dict:
    """Process one user message. Updates state in place and returns a result:
    {"type": "answer"|"followup"|"decline"|"error", "text", "tables",
     "fields", "intents", "number_check", "stats"}"""
    stats = reset_stats()
    result = {"type": "error", "text": "", "tables": [], "number_check": None}
    try:
        raw = parse_message(message, state)
    except (LLMError, ValueError, json.JSONDecodeError) as exc:
        result["text"] = ("Sorry, the language model is not available right now, so I "
                          f"can't read your request. ({exc})")
        return _finish(result, state, stats)

    fields, problems, extra = validate(raw)
    state["parsed_raw"] = raw

    # Decline other cities and topics we don't cover.
    if (fields["city"] and fields["city"] != CITY) or not extra["in_scope"]:
        result.update(type="decline", text=decline_text(fields["city"], extra["decline_reason"]))
        state["pending_question"] = None
        return _finish(result, state, stats)

    state["fields"] = merge_fields(state["fields"], fields)
    state["fields"]["city"] = CITY  # NYC-only app: a missing city means New York
    if extra["intents"]:
        state["intents"] = extra["intents"]
    if extra["hotel_name"]:
        state["hotel_name"] = extra["hotel_name"]
    if not state["intents"]:
        result.update(type="followup",
                      text="I can help with your New York trip. Would you like hotel "
                           "prices, the reported-incident outlook for a month, the best "
                           "month to visit, or places to visit?")
        state["pending_question"] = result["text"]
        return _finish(result, state, stats)

    need = missing_fields(state["intents"], state["fields"])
    if need:
        result.update(type="followup", text=follow_up_text(need, problems, state["intents"]))
        state["pending_question"] = result["text"]
        return _finish(result, state, stats)

    state["pending_question"] = None
    facts, tables = gather_facts(state["intents"], state["fields"], state["hotel_name"],
                                 live_prices)
    result["tables"] = tables
    try:
        ans = write_answer(message, facts, state["fields"])
    except LLMError as exc:
        ans = {"text": None, "passed": False, "bad_numbers": [], "attempts": 0,
               "error": str(exc)}
    result["number_check"] = {k: ans.get(k) for k in ("passed", "bad_numbers", "attempts")}
    if ans["passed"]:
        result.update(type="answer", text=ans["text"])
    else:
        why = ("the language model is unavailable" if ans.get("error")
               else "the written summary did not pass the number check")
        result.update(type="answer",
                      text=f"Here are the results as tables ({why}, so I'm not showing it).")
    return _finish(result, state, stats)


def _finish(result: dict, state: dict, stats) -> dict:
    result["fields"] = dict(state.get("fields", {}))
    result["intents"] = list(state.get("intents", []))
    result["stats"] = stats.as_dict()
    return result
