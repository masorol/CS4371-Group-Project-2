"""SafeStay NYC - Streamlit web app (Task 5).

Run with:  streamlit run app.py
"""
from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from src import data_api
from src.task5_assistant import MONTHS, handle_message, new_state
from src.utils import age_text, get_key

st.set_page_config(page_title="SafeStay NYC", page_icon="🗽", layout="wide")

MONTH_LABELS = [m.title() for m in MONTHS]
HOTEL_COLOUR = "#1f77b4"       # blue
ATTRACTION_COLOUR = "#ff7f0e"  # orange


# ---------------------------------------------------------------- helpers
def source_caption(meta: dict) -> str:
    text = f"Source: {meta.get('source', 'unknown')}"
    if meta.get("retrieved_at"):
        how = "cached" if meta.get("from_cache") else "live"
        text += (f" · Prices retrieved {meta['retrieved_at']} "
                 f"({how}, {age_text(meta['retrieved_at'])})")
    return text


def show_table(title: str, df: pd.DataFrame, meta: dict, expanded: bool = False) -> None:
    with st.expander(title, expanded=expanded):
        if meta.get("placeholder"):
            st.warning("PLACEHOLDER data: the real module for this task is not in the repo yet.")
        st.dataframe(df, hide_index=True, width="stretch")
        st.caption(source_caption(meta))
        if meta.get("note"):
            st.caption(f"⚠️ {meta['note']}")


def next_date_in_month(month: int) -> date:
    """The 15th of the chosen month, in the future (used to price hotels on the map)."""
    today = date.today()
    year = today.year if (month, 15) > (today.month, today.day) else today.year + 1
    return date(year, month, 15)


@st.cache_data(ttl=3600, show_spinner=False)
def cached_map_data(month: int, budget: float):
    check_in = next_date_in_month(month)
    hotels, hmeta = data_api.search_hotels(check_in, 1, 2, budget, False)
    attractions, ameta = data_api.top_attractions(month, budget)
    neighbourhoods, nmeta = data_api.top_neighbourhoods(month, budget)
    return check_in, hotels, hmeta, attractions, ameta, neighbourhoods, nmeta


# ---------------------------------------------------------------- state
if "conv" not in st.session_state:
    st.session_state.conv = new_state()
    st.session_state.messages = []

# ---------------------------------------------------------------- sidebar
with st.sidebar:
    st.title("🗽 SafeStay NYC")
    page = st.radio("Page", ["Chat", "Map"], label_visibility="collapsed")
    st.divider()
    if st.button("🔄 New conversation", width="stretch"):
        st.session_state.conv = new_state()
        st.session_state.messages = []
        st.rerun()
    live = st.toggle("Fetch live hotel prices", value=False,
                     help="Off: reuse cached prices (labelled with their age).")
    st.divider()
    st.caption("Data modules")
    for name, real in data_api.status().items():
        st.caption(f"{'✅ real' if real else '🟡 placeholder'} · {name}")
    if not (get_key("GROQ_API_KEY") or get_key("OPENROUTER_API_KEY")):
        st.error("No GROQ_API_KEY in .env; only cached LLM answers will work.")
    st.caption("SafeStay compares prices only; it never makes bookings or takes payments.")


# ---------------------------------------------------------------- chat page
def render_message(msg: dict) -> None:
    with st.chat_message(msg["role"]):
        st.markdown(msg["text"])
        for i, (title, df, meta) in enumerate(msg.get("tables", [])):
            show_table(title, df, meta, expanded=(msg.get("type") == "answer" and i == 0
                                                  and msg.get("checked") is False))
        info = []
        if msg.get("number_check"):
            nc = msg["number_check"]
            info.append("number check ✅ passed" if nc["passed"]
                        else f"number check ❌ failed {nc.get('bad_numbers') or ''}")
        if msg.get("stats"):
            s = msg["stats"]
            info.append(f"{s['api_calls']} API calls, {s['cache_hits']} cache hits, "
                        f"{s['seconds']} s")
        if info:
            st.caption(" · ".join(info))


def chat_page() -> None:
    st.header("Plan your New York stay")
    st.caption("Ask about hotel prices, reported incidents by month, the best month to "
               "visit, or places to visit. Incident figures are reported incidents, "
               "not a measure of personal risk.")
    for msg in st.session_state.messages:
        render_message(msg)

    known = {k: v for k, v in st.session_state.conv["fields"].items() if v not in (None, [])}
    if known:
        with st.expander("Details collected so far"):
            st.json(known)

    prompt = st.chat_input("e.g. Cheapest hotel for two nights from 12 March, two adults, under $150 a night")
    if prompt:
        user_msg = {"role": "user", "text": prompt}
        st.session_state.messages.append(user_msg)
        render_message(user_msg)
        with st.spinner("Working on it..."):
            result = handle_message(prompt, st.session_state.conv, live_prices=live)
        st.session_state.messages.append({
            "role": "assistant", "text": result["text"], "type": result["type"],
            "tables": result["tables"], "number_check": result["number_check"],
            "checked": (result["number_check"] or {}).get("passed"),
            "stats": result["stats"]})
        st.rerun()


# ---------------------------------------------------------------- map page
def map_page() -> None:
    st.header("Map: hotels and places to visit")
    c1, c2 = st.columns(2)
    month_label = c1.selectbox("Month", MONTH_LABELS, index=date.today().month % 12)
    budget = c2.number_input("Max price per night (USD)", min_value=20, max_value=2000,
                             value=200, step=10)
    month = MONTH_LABELS.index(month_label) + 1

    with st.spinner("Loading hotels and attractions..."):
        check_in, hotels, hmeta, attractions, ameta, nbhds, nmeta = cached_map_data(month, float(budget))

    in_budget = hotels[hotels["cheapest_price"] <= budget]
    points = pd.concat([
        pd.DataFrame({"lat": in_budget["lat"], "lon": in_budget["lon"],
                      "color": HOTEL_COLOUR, "size": 40}),
        pd.DataFrame({"lat": attractions["lat"], "lon": attractions["lon"],
                      "color": ATTRACTION_COLOUR, "size": 60}),
    ], ignore_index=True)
    st.map(points, latitude="lat", longitude="lon", color="color", size="size")
    st.markdown(f"<span style='color:{HOTEL_COLOUR}'>●</span> Hotels within ${budget} "
                f"({len(in_budget)}) &nbsp; <span style='color:{ATTRACTION_COLOUR}'>●</span> "
                f"Attractions ({len(attractions)})", unsafe_allow_html=True)
    st.caption("Map data © OpenStreetMap contributors (ODbL). "
               f"Hotel prices are for 1 night from {check_in.isoformat()}, 2 guests. "
               + source_caption(hmeta))

    if hmeta.get("placeholder") or ameta.get("placeholder"):
        st.warning("Some of this map uses PLACEHOLDER data until the real Task 4/8 modules are added.")

    st.subheader(f"Top 10 places to visit in {month_label}")
    show_table("Top 10 places", attractions.drop(columns=["lat", "lon"], errors="ignore").head(10),
               ameta, expanded=True)
    st.subheader(f"Top 5 neighbourhoods in {month_label}")
    show_table("Top 5 neighbourhoods", nbhds.head(5), nmeta, expanded=True)


if page == "Chat":
    chat_page()
else:
    map_page()
