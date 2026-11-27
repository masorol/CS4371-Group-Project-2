"""SafeStay - Task 8
Places to visit and best neighbourhoods: attractions from OpenStreetMap,
combined with Task 2's incident levels and Task 4's hotels.
Run from the repository root: python -m src.task8_attractions
"""

import hashlib
import json
import os
import re
import time
from datetime import datetime, timezone

import pandas as pd
import requests
from dotenv import load_dotenv

from src.geo_utils import load_precincts, find_precinct, haversine_km
from src.task4_hotels import get_precinct_month_avg, STAYS

# TEMPORARY: get_precinct_month_avg() stands in for Person 1's Task 2 output
# (see src/task4_hotels.py). Swap this import for Task 2's real per-precinct,
# per-month averages once that code exists.

CACHE_DIR = os.path.join("cache", "overpass")
HOTELS_PATH = os.path.join("outputs", "t4_hotels.csv")
OUTPUT_DIR = "outputs"

# Reuse the two months already used for Task 4's hotel stays (July, December)
MONTHS = list(STAYS.keys())

# Attractions are how close to a hotel still counts as "nearby" (Task 8 spec: 1 km)
HOTEL_RADIUS_KM = 1.0
MIN_ATTRACTIONS = 30
TOP_N_ATTRACTIONS = 10
TOP_N_NEIGHBOURHOODS = 5

# ---------------------------------------------------
# STEP 2: Fetch attractions from the Overpass API
# ---------------------------------------------------

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
USER_AGENT = "SafeStay-CS4371-GroupProject/1.0 (student coursework project)"
ATTRACTIONS_CACHE_PATH = os.path.join(CACHE_DIR, "attractions.json")

# South, west, north, east: covers all five NYC boroughs
NYC_BBOX = (40.4957, -74.2557, 40.9176, -73.7002)

# tourism=* values named in the Task 8 spec; leisure=park is queried separately
# below since only *named* parks count
ATTRACTION_TOURISM_TAGS = [
	"museum", "gallery", "viewpoint", "zoo", "aquarium", "theme_park", "attraction",
]


def build_overpass_query(bbox=NYC_BBOX):
	"""
	Overpass QL query for every attraction tag in the Task 8 spec, across the
	whole NYC bounding box. "out center" makes ways and relations come back
	with one (lat, lon) coordinate each, same as nodes.
	"""
	south, west, north, east = bbox
	bbox_str = f"{south},{west},{north},{east}"
	tag_regex = "^(" + "|".join(ATTRACTION_TOURISM_TAGS) + ")$"

	clauses = []
	for elem in ("node", "way", "relation"):
		clauses.append(f'  {elem}["tourism"~"{tag_regex}"]({bbox_str});')
	for elem in ("node", "way", "relation"):
		clauses.append(f'  {elem}["leisure"="park"]["name"]({bbox_str});')

	return "[out:json][timeout:90];\n(\n" + "\n".join(clauses) + "\n);\nout center;"


def fetch_attractions_raw(live=False, path=ATTRACTIONS_CACHE_PATH):
	"""
	Run the Overpass query once and cache the raw response to disk, so repeated
	runs reuse the saved copy instead of hitting the shared Overpass server
	again. Returns (record, source), where source is "live" or "cache" and
	record is {"retrieved_at", "query", "response"} ("response" is Overpass's
	own JSON, with an "elements" list).
	With live=False, the cache is used whenever it exists.
	With live=True, the API is always queried again and the cache refreshed.
	"""
	os.makedirs(os.path.dirname(path), exist_ok=True)

	if not live and os.path.exists(path):
		with open(path, encoding="utf-8") as f:
			return json.load(f), "cache"

	query = build_overpass_query()
	resp = requests.post(
		OVERPASS_URL,
		data={"data": query},
		headers={"User-Agent": USER_AGENT},
		timeout=120,
	)
	resp.raise_for_status()

	record = {
		"retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
		"query": query,
		"response": resp.json(),
	}

	with open(path, "w", encoding="utf-8") as f:
		json.dump(record, f)
	time.sleep(1)  # ground rules: wait at least 1s between calls to the same service

	return record, "live"


# ---------------------------------------------------
# STEP 3: Clean and filter the Overpass results
# ---------------------------------------------------

def _element_coords(element):
	"""(lat, lon) for a node, or a way/relation's "out center" point."""
	if "lat" in element and "lon" in element:
		return element["lat"], element["lon"]
	center = element.get("center")
	if center:
		return center["lat"], center["lon"]
	return None, None


def _attraction_category(tags):
	"""Which Task 8 tag this element matched: the tourism value, or "park"."""
	tourism = tags.get("tourism")
	if tourism in ATTRACTION_TOURISM_TAGS:
		return tourism
	if tags.get("leisure") == "park":
		return "park"
	return tourism or "unknown"


def parse_attractions(record, precincts):
	"""
	Turn the raw Overpass elements into one row per real-world attraction:
	keep only named elements with coordinates, drop duplicates (OSM often
	returns the same place as more than one element, e.g. a way and a node),
	record whether each has a Wikipedia/Wikidata tag, and assign a precinct
	with the Task 4 ray-casting code. Attractions outside NYC (no precinct,
	e.g. just across a state line) are dropped.
	Raises ValueError if fewer than MIN_ATTRACTIONS remain (Task 8 spec minimum).
	"""
	elements = record["response"]["elements"]

	rows = []
	seen = set()
	for e in elements:
		tags = e.get("tags", {})
		name = tags.get("name")
		lat, lon = _element_coords(e)
		if not name or lat is None or lon is None:
			continue

		# Round coordinates so the same place mapped as, say, both a way and a
		# node with slightly different center points still dedupes.
		key = (name.strip().lower(), round(lat, 4), round(lon, 4))
		if key in seen:
			continue
		seen.add(key)

		rows.append({
			"osm_type": e["type"],
			"osm_id": e["id"],
			"name": name,
			"lat": lat,
			"lon": lon,
			"category": _attraction_category(tags),
			"has_wikipedia": bool(tags.get("wikipedia") or tags.get("wikidata")),
		})

	df = pd.DataFrame(rows)
	df["precinct"] = pd.array(
		[find_precinct(lat, lon, precincts) for lat, lon in zip(df["lat"], df["lon"])],
		dtype="Int64",
	)

	n_outside = int(df["precinct"].isna().sum())
	df = df[df["precinct"].notna()].reset_index(drop=True)

	print(f"{len(elements)} raw elements -> {len(rows)} named with coordinates, deduped -> "
		  f"{len(df)} inside NYC precincts ({n_outside} dropped, outside NYC)")

	if len(df) < MIN_ATTRACTIONS:
		raise ValueError(
			f"Only {len(df)} named attractions with coordinates inside NYC "
			f"(need at least {MIN_ATTRACTIONS}); widen NYC_BBOX or the tag list."
		)

	return df


def load_hotels(month, path=HOTELS_PATH):
	"""
	Task 4's hotels for one stay month, with the columns Task 8 needs:
	location, precinct, cheapest nightly price and when that price was
	retrieved (ground rules: prices must show when they were retrieved).
	Raises FileNotFoundError with a clear message if t4_hotels.csv hasn't been
	generated yet (run `python -m src.task4_hotels` first).
	"""
	if not os.path.exists(path):
		raise FileNotFoundError(
			f"{path} not found. Run `python -m src.task4_hotels` to generate it first."
		)

	df = pd.read_csv(path)
	cols = ["hotel_key", "name", "lat", "lon", "precinct", "cheapest_nightly",
			"cheapest_site", "retrieved_at"]
	return df.loc[df["stay_month"] == month, cols].reset_index(drop=True)


# ------------------------------------------------------
# STEP 4: Add per-attraction context (incidents, hotels)
# ------------------------------------------------------

def add_context(attractions, month):
	"""
	Add each attraction's monthly context:
	  - incidents_avg: its precinct's average reported incidents that month
	    (TEMPORARY Task 2 stand-in; see get_precinct_month_avg)
	  - hotels_within_1km: how many Task 4 hotels are within HOTEL_RADIUS_KM
	  - cheapest_hotel_name / cheapest_hotel_nightly: the cheapest of those hotels
	    (None if no hotel is that close)
	Distances are computed with the Task 4 haversine function.
	"""
	incident_avg = get_precinct_month_avg(month)
	hotels = load_hotels(month)

	df = attractions.copy()
	df["incidents_avg"] = df["precinct"].map(incident_avg).round(1)

	hotels_within = []
	cheapest_name = []
	cheapest_price = []

	for lat, lon in zip(df["lat"], df["lon"]):
		distances = [
			haversine_km(lat, lon, hlat, hlon)
			for hlat, hlon in zip(hotels["lat"], hotels["lon"])
		]
		nearby = hotels[[d <= HOTEL_RADIUS_KM for d in distances]]

		hotels_within.append(len(nearby))
		if nearby.empty:
			cheapest_name.append(None)
			cheapest_price.append(None)
		else:
			cheapest = nearby.loc[nearby["cheapest_nightly"].idxmin()]
			cheapest_name.append(cheapest["name"])
			cheapest_price.append(cheapest["cheapest_nightly"])

	df["hotels_within_1km"] = hotels_within
	df["cheapest_hotel_name"] = cheapest_name
	df["cheapest_hotel_nightly"] = cheapest_price

	return df


# ---------------------------------------------------
# STEP 5: Score and rank attractions
# ---------------------------------------------------

def _scale(series, max_points):
	"""Min-max scale a series to [0, max_points]; higher value -> higher score."""
	lo, hi = series.min(), series.max()
	if hi > lo:
		return max_points * (series - lo) / (hi - lo)
	return pd.Series(max_points, index=series.index)  # no spread: give everyone full credit


def _scale_inverse(series, max_points):
	"""Min-max scale a series to [0, max_points]; lower value -> higher score."""
	lo, hi = series.min(), series.max()
	if hi > lo:
		return max_points * (hi - series) / (hi - lo)
	return pd.Series(max_points, index=series.index)


def score_attractions(df):
	"""
	Score each attraction from 0 to 5, to rank the "best places to visit":
	  - +2 if it has a Wikipedia/Wikidata tag: a sign it's a well-known,
	    documented destination rather than something incidentally mapped
	    (the lecture's own hint for this task).
	  - up to +2 for how low its precinct's reported incidents are that
	    month, scaled across this attraction set's min-max range (fewer
	    incidents -> higher score). If every attraction's precinct has the
	    same average that month, everyone gets the full 2 points.
	  - +1 if at least one Task 4 hotel is within 1 km: convenient to stay
	    near without a hotel-count bonus for already having several.
	Adds a "score" column and returns the DataFrame sorted best-first with a
	"rank" column (1 = best). Ties break on has_wikipedia, then hotel
	presence, then name, so the ranking is deterministic and reproducible.
	"""
	df = df.copy()

	wiki_score = df["has_wikipedia"].astype(int) * 2
	incident_score = _scale_inverse(df["incidents_avg"], 2)
	hotel_score = (df["hotels_within_1km"] > 0).astype(int) * 1

	df["score"] = (wiki_score + incident_score + hotel_score).round(2)

	df = df.sort_values(
		["score", "has_wikipedia", "hotels_within_1km", "name"],
		ascending=[False, False, False, True],
	).reset_index(drop=True)
	df["rank"] = df.index + 1

	return df


def top_attractions(df, n=TOP_N_ATTRACTIONS):
	"""The n best-scoring attractions (Task 8 spec: top 10)."""
	return score_attractions(df).head(n)


# ----------------------------------------------------------
# STEP 6: Build and score the neighbourhood (precinct) table
# ----------------------------------------------------------

MAX_PRICE_DEFAULT = 200  # nightly budget used when none is given (matches the app's example)


def build_neighbourhoods(attractions, month, max_price=MAX_PRICE_DEFAULT):
	"""
	One row per NYC precinct (this project's "neighbourhood" unit, since the
	NYPD data has no named neighbourhoods -- see Task 3/4's notes):
	  - n_attractions: how many Task 8 attractions are in this precinct
	  - incidents_avg: the precinct's average reported incidents that month
	    (TEMPORARY Task 2 stand-in; see get_precinct_month_avg)
	  - hotels_in_budget: Task 4 hotels in this precinct at or under max_price
	  - median_nightly: their median nightly price (NaN if none in budget)
	Covers every precinct with an incident average that month, not just the
	ones with attractions, so "best neighbourhoods" is judged fairly.
	"""
	incident_avg = get_precinct_month_avg(month)
	hotels = load_hotels(month)
	in_budget = hotels[hotels["cheapest_nightly"] <= max_price]

	attraction_counts = attractions.groupby("precinct").size()
	hotel_counts = in_budget.groupby("precinct").size()
	hotel_medians = in_budget.groupby("precinct")["cheapest_nightly"].median()

	df = incident_avg.rename("incidents_avg").round(1).reset_index()
	df["n_attractions"] = df["precinct"].map(attraction_counts).fillna(0).astype(int)
	df["hotels_in_budget"] = df["precinct"].map(hotel_counts).fillna(0).astype(int)
	df["median_nightly"] = df["precinct"].map(hotel_medians)

	return df[["precinct", "n_attractions", "incidents_avg", "hotels_in_budget", "median_nightly"]]


def score_neighbourhoods(df):
	"""
	Score each neighbourhood from 0 to 5, to rank "best neighbourhoods to
	stay in or explore":
	  - up to +2 for how many attractions it has, scaled across this
	    neighbourhood set's min-max range (more to see and do -> higher).
	  - up to +2 for how low its reported incidents are that month, scaled
	    the same way as the attraction scoring rule (fewer incidents -> higher).
	  - up to +1 for how many Task 4 hotels are within the user's budget
	    (more affordable choice -> higher), capped lower than the other two
	    since it's a convenience, not a reason to visit.
	Adds a "score" column and returns the DataFrame sorted best-first with a
	"rank" column (1 = best). Ties break on cheaper median_nightly, then
	more attractions, then precinct number, so the ranking is deterministic.
	"""
	df = df.copy()

	attraction_score = _scale(df["n_attractions"], 2)
	incident_score = _scale_inverse(df["incidents_avg"], 2)
	hotel_score = _scale(df["hotels_in_budget"], 1)

	df["score"] = (attraction_score + incident_score + hotel_score).round(2)

	df = df.sort_values(
		["score", "median_nightly", "n_attractions", "precinct"],
		ascending=[False, True, False, True],
	).reset_index(drop=True)
	df["rank"] = df.index + 1

	return df


def top_neighbourhoods(df, n=TOP_N_NEIGHBOURHOODS):
	"""The n best-scoring neighbourhoods (Task 8 spec: top 5)."""
	return score_neighbourhoods(df).head(n)


# ----------------------------------------------------------
# STEP 7: Grounded LLM summary, with the Task 2 number check
# ----------------------------------------------------------

LLM_CACHE_DIR = os.path.join("cache", "t8")
GROQ_MODEL = "openai/gpt-oss-120b"
NUMBER_RE = re.compile(r"-?\d[\d,]*\.?\d*")

ATTRACTION_PROMPT_COLS = ["name", "category", "precinct", "incidents_avg",
						  "hotels_within_1km", "cheapest_hotel_nightly", "has_wikipedia"]
NEIGHBOURHOOD_PROMPT_COLS = ["precinct", "n_attractions", "incidents_avg",
							 "hotels_in_budget", "median_nightly"]


def _records_for_prompt(df, cols):
	"""df[cols] as JSON-safe dicts (NaN -> null) for the LLM prompt."""
	records = df[cols].to_dict(orient="records")
	for row in records:
		for k, v in row.items():
			if isinstance(v, float) and pd.isna(v):
				row[k] = None
	return records


def make_summary_prompt(top10, top5, month):
	"""
	Build the Task 8 "grounded explanation" prompt: only the top 10
	attractions and top 5 neighbourhoods, as JSON text, with instructions to
	use only those numbers and to describe areas responsibly (ground rules:
	"reported incidents", not "dangerous neighbourhoods").
	"""
	attraction_rows = _records_for_prompt(top10, ATTRACTION_PROMPT_COLS)
	neighbourhood_rows = _records_for_prompt(top5, NEIGHBOURHOOD_PROMPT_COLS)

	return (
		f"You are writing a short, traveler-friendly summary of the best places "
		f"to visit in New York City in month {month} (1-12), and the best NYPD "
		f"precincts (this city's neighbourhood unit) to stay in or explore. "
		f"Use ONLY the numbers in the INPUT DATA below; do not invent, estimate "
		f"or add any number that is not already there. Talk about \"reported "
		f"incidents\", never \"dangerous\" or \"unsafe\" neighbourhoods -- "
		f"reported incidents are not the same as risk to a visitor. "
		f"Write 4 to 6 sentences.\n\n"
		f"INPUT DATA (top 10 attractions):\n{json.dumps(attraction_rows)}\n\n"
		f"INPUT DATA (top 5 precincts):\n{json.dumps(neighbourhood_rows)}"
	)


def call_groq(prompt):
	"""One Groq chat completion call, temperature 0 (ground rules: same request, same answer)."""
	from groq import Groq

	client = Groq(api_key=os.environ["GROQ_API_KEY"])
	response = client.chat.completions.create(
		model=GROQ_MODEL,
		messages=[
			{
				"role": "system",
				"content": (
					"Write plain, traveler-friendly prose. Use only the numbers "
					"given to you; never invent or guess a number. Describe areas "
					"by their reported incidents, not as \"dangerous\" or \"safe\"."
				),
			},
			{"role": "user", "content": prompt},
		],
		temperature=0,
	)
	return response.choices[0].message.content


def cached_summary_call(month, prompt, cache_dir=LLM_CACHE_DIR, live=False):
	"""
	Cache the LLM's raw summary to disk per month, the same way Task 3 caches
	its calls: keyed on a hash of the model and prompt, so a changed prompt
	(a new top 10/5, or a retry) triggers a fresh call instead of reusing
	stale text, while an unchanged prompt reuses the cache.
	"""
	os.makedirs(cache_dir, exist_ok=True)
	path = os.path.join(cache_dir, f"groq_summary_{month:02d}.json")
	digest = hashlib.sha256((GROQ_MODEL + prompt).encode()).hexdigest()

	if os.path.exists(path) and not live:
		with open(path, encoding="utf-8") as f:
			record = json.load(f)
		if record.get("prompt_sha256") == digest:
			return record["raw_response"]

	raw = call_groq(prompt)
	record = {
		"model": GROQ_MODEL,
		"month": month,
		"retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
		"prompt_sha256": digest,
		"prompt": prompt,
		"raw_response": raw,
	}
	with open(path, "w", encoding="utf-8") as f:
		json.dump(record, f, indent=2)
	time.sleep(1)  # ground rules: wait at least 1s between calls to the same service

	return raw


def extract_numbers(text):
	"""Every numeric token in a piece of text, as floats (commas stripped)."""
	return [float(tok.replace(",", "")) for tok in NUMBER_RE.findall(text)]


def allowed_numbers(top10, top5):
	"""Every number that appeared in the rows sent to the LLM (the number check's allow-list)."""
	values = set()
	for df, cols in [(top10, ATTRACTION_PROMPT_COLS), (top5, NEIGHBOURHOOD_PROMPT_COLS)]:
		for col in cols:
			if col in ("name", "category", "has_wikipedia"):
				continue
			for v in df[col]:
				if pd.isna(v):
					continue
				values.add(round(float(v), 2))
	return values


def passes_number_check(summary, top10, top5, tolerance=0.05):
	"""
	True if every number in the summary is close to one that was sent to the
	LLM (a relative tolerance, so "1,290" still matches a sent 1289.7).
	Mirrors the Task 2 number check.
	"""
	allowed = allowed_numbers(top10, top5)
	if not allowed:
		return True  # nothing numeric was sent, so nothing to check

	for n in extract_numbers(summary):
		if not any(abs(n - a) <= tolerance * max(abs(a), 1) for a in allowed):
			return False
	return True


def summarize(top10, top5, month, live=False, max_attempts=2):
	"""
	Ask Groq for a short traveler-friendly summary of the top 10 attractions
	and top 5 neighbourhoods, and run the number check on every attempt.
	Returns (summary_text, passed). On a failed check, retries once with an
	extra warning appended to the prompt; if that also fails, returns
	(None, False) so the caller falls back to showing the tables alone.
	"""
	base_prompt = make_summary_prompt(top10, top5, month)

	for attempt in range(max_attempts):
		prompt = base_prompt
		if attempt > 0:
			prompt += (
				"\n\nYour previous answer used a number that was not in the "
				"INPUT DATA above. Write it again using ONLY numbers that "
				"appear there."
			)
		raw = cached_summary_call(month, prompt, live=live)
		if passes_number_check(raw, top10, top5):
			return raw, True

	return None, False


# ---------------------------------------------------
# STEP 8: Save outputs for each month
# ---------------------------------------------------

MONTH_NAMES = {7: "July", 12: "December"}

ATTRACTION_OUTPUT_COLS = ["rank", "osm_type", "osm_id", "name", "category", "precinct",
						  "incidents_avg", "hotels_within_1km", "cheapest_hotel_name",
						  "cheapest_hotel_nightly", "has_wikipedia", "score"]
NEIGHBOURHOOD_OUTPUT_COLS = ["rank", "precinct", "n_attractions", "incidents_avg",
							 "hotels_in_budget", "median_nightly", "score"]


def _markdown_table(df, cols):
	"""A minimal Markdown table, written by hand to avoid an extra dependency."""
	def cell(v):
		return "" if (isinstance(v, float) and pd.isna(v)) else str(v)

	header = "| " + " | ".join(cols) + " |"
	sep = "| " + " | ".join("---" for _ in cols) + " |"
	rows = [
		"| " + " | ".join(cell(row[c]) for c in cols) + " |"
		for row in df[cols].to_dict(orient="records")
	]
	return "\n".join([header, sep] + rows)


def format_summary_markdown(month, top10, top5, summary_text, passed,
							 overpass_retrieved_at, hotels_retrieved_at):
	"""
	The Task 8 grounded-explanation markdown: sources and retrieval times,
	the top 10 attractions, the top 5 neighbourhoods, and the LLM summary
	(or a note that it's unavailable, if the number check failed twice).
	"""
	month_name = MONTH_NAMES.get(month, str(month))
	lines = [f"# Places to visit and best neighbourhoods -- {month_name}", ""]

	lines.append(
		f"**Sources:** OpenStreetMap Overpass API (attractions, retrieved "
		f"{overpass_retrieved_at}); Task 4 hotel prices (retrieved "
		f"{hotels_retrieved_at}); Task 2 stand-in incident averages from "
		f"`data/neighbourhood_month.parquet` (NYPD data, 2022-2024). "
		f"Map data (c) OpenStreetMap contributors, ODbL."
	)
	lines.append("")

	lines.append("## Top 10 places to visit")
	lines.append("")
	lines.append(_markdown_table(top10, ATTRACTION_OUTPUT_COLS))
	lines.append("")

	lines.append("## Top 5 neighbourhoods to stay in or explore")
	lines.append("")
	lines.append(_markdown_table(top5, NEIGHBOURHOOD_OUTPUT_COLS))
	lines.append("")

	lines.append("## Summary")
	lines.append("")
	if passed:
		lines.append(summary_text)
	else:
		lines.append(
			"_The LLM summary did not pass the number check twice, so it is "
			"left out here. See the tables above for the grounded numbers._"
		)

	return "\n".join(lines) + "\n"


def save_outputs(attractions, month, overpass_retrieved_at, max_price=MAX_PRICE_DEFAULT,
				  output_dir=OUTPUT_DIR, live_llm=False):
	"""
	Build this month's scored attractions and neighbourhoods, ask the LLM for
	a grounded summary, and save the three Task 8 output files:
	t8_attractions_<month>.csv, t8_neighbourhoods_<month>.csv and
	t8_summary_<month>.md. Returns (scored_attractions, scored_neighbourhoods).
	"""
	os.makedirs(output_dir, exist_ok=True)

	with_context = add_context(attractions, month)
	scored_attractions = score_attractions(with_context)
	top10 = scored_attractions.head(TOP_N_ATTRACTIONS)

	neighbourhoods = build_neighbourhoods(attractions, month, max_price)
	scored_neighbourhoods = score_neighbourhoods(neighbourhoods)
	top5 = scored_neighbourhoods.head(TOP_N_NEIGHBOURHOODS)

	summary_text, passed = summarize(top10, top5, month, live=live_llm)

	hotels = load_hotels(month)
	hotels_retrieved_at = hotels["retrieved_at"].max() if not hotels.empty else "no hotels for this stay"

	attractions_path = os.path.join(output_dir, f"t8_attractions_{month}.csv")
	neighbourhoods_path = os.path.join(output_dir, f"t8_neighbourhoods_{month}.csv")
	summary_path = os.path.join(output_dir, f"t8_summary_{month}.md")

	scored_attractions.to_csv(attractions_path, index=False)
	scored_neighbourhoods.to_csv(neighbourhoods_path, index=False)
	with open(summary_path, "w", encoding="utf-8") as f:
		f.write(format_summary_markdown(
			month, top10, top5, summary_text, passed,
			overpass_retrieved_at, hotels_retrieved_at,
		))

	print(f"Saved {attractions_path} ({len(scored_attractions)} rows), "
		  f"{neighbourhoods_path} ({len(scored_neighbourhoods)} rows), {summary_path}")

	return scored_attractions, scored_neighbourhoods


# ---------------------------------------------------------------
# STEP 9: Entry point for Task 5 (the assistant and the map page)
# ---------------------------------------------------------------

def get_places_to_visit(month, max_price=MAX_PRICE_DEFAULT, live=False, live_llm=False):
	"""
	Entry point for the app (Task 5), mirroring task4_hotels.search_hotels().
	Returns (attractions, neighbourhoods, summary_text):
	  - attractions: every cleaned Task 8 attraction for `month`, with lat/lon
	    for the map page's markers, scored and ranked best-first ("rank" 1 is
	    the top of "best places to visit"; take .head(10) for the Task 8 top 10).
	  - neighbourhoods: every NYC precinct, scored and ranked best-first for
	    "best neighbourhoods to stay in or explore" at max_price (take
	    .head(5) for the Task 8 top 5).
	  - summary_text: the grounded LLM summary of the top 10/top 5 (a
	    traveler-friendly paragraph), or a plain-table fallback message if it
	    failed the number check twice.
	live=True re-fetches OpenStreetMap instead of using the disk cache;
	live_llm=True bypasses the cached LLM summary for a fresh call.
	Raises FileNotFoundError if outputs/t4_hotels.csv hasn't been generated
	yet (run `python -m src.task4_hotels` first); the app should catch this
	and tell the user, the same way it handles Task 4's own RuntimeError.
	"""
	precincts = load_precincts()
	record, _ = fetch_attractions_raw(live=live)
	attractions = parse_attractions(record, precincts)

	with_context = add_context(attractions, month)
	scored_attractions = score_attractions(with_context)
	top10 = scored_attractions.head(TOP_N_ATTRACTIONS)

	neighbourhoods = build_neighbourhoods(attractions, month, max_price)
	scored_neighbourhoods = score_neighbourhoods(neighbourhoods)
	top5 = scored_neighbourhoods.head(TOP_N_NEIGHBOURHOODS)

	summary_text, passed = summarize(top10, top5, month, live=live_llm)
	if not passed:
		summary_text = (
			"A written summary isn't available right now; see the attractions "
			"and neighbourhoods tables for the numbers behind this answer."
		)

	return scored_attractions, scored_neighbourhoods, summary_text


if __name__ == "__main__":
	load_dotenv()
	precincts = load_precincts()
	print(f"Loaded {len(precincts)} precincts")

	record, source = fetch_attractions_raw()
	print(f"Overpass ({source}, retrieved {record['retrieved_at']})")

	attractions = parse_attractions(record, precincts)
	print(f"{attractions['has_wikipedia'].sum()} of {len(attractions)} have a Wikipedia/Wikidata tag")
	print(attractions["category"].value_counts())

	for month in MONTHS:
		print(f"\n=== {MONTH_NAMES.get(month, month)} (month {month}) ===")
		scored_attractions, scored_neighbourhoods = save_outputs(
			attractions, month, overpass_retrieved_at=record["retrieved_at"],
		)
		print(f"Top attraction: {scored_attractions.iloc[0]['name']} "
			  f"(score {scored_attractions.iloc[0]['score']})")
		print(f"Top neighbourhood: precinct {scored_neighbourhoods['precinct'].iloc[0]} "
			  f"(score {scored_neighbourhoods.iloc[0]['score']})")
