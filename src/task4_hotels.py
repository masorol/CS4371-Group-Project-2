import json
import os
import time
import zipfile
from datetime import date, datetime, timedelta, timezone

import pandas as pd
import requests

from src.geo_utils import load_precincts, find_precinct, haversine_km

N_HOTELS = 800
CACHE_DIR = os.path.join("cache", "xotelo")
BASE_URL = "https://data.xotelo.com/api"
NYC_LOCATION_KEY = "g60763"
INCIDENTS_PATH = os.path.join("data", "processed", "neighbourhood_month.parquet")

# One stay per Task 2 / Task 8 month: Tuesday to Friday, 3 nights, no holidays
STAYS = {
	7: ("2027-07-13", "2027-07-16"),
	12: ("2026-12-08", "2026-12-11"),
}

# Defaults for functions called without dates (the first stay)
CHK_IN, CHK_OUT = STAYS[7]
NIGHTS = (date.fromisoformat(CHK_OUT) - date.fromisoformat(CHK_IN)).days


def cached_get(endpoint, params, live=False):
	"""
	GET from Xotelo with a disk cache. Returns (data, source), where source is:
	  "live"           fresh answer from the API (and saved to the cache)
	  "cache"          read from the cache without calling the API
	  "cache_fallback" the API call failed, so the cached copy was used instead
	With live=False, the cache is used whenever it exists.
	With live=True, the API is always tried first.
	"""
	os.makedirs(CACHE_DIR, exist_ok=True)
	name = endpoint + "_" + "_".join(f"{k}-{v}" for k, v in sorted(params.items()))
	path = os.path.join(CACHE_DIR, name + ".json")
	have_cache = os.path.exists(path)

	if live or not have_cache:
		try:
			resp = requests.get(f"{BASE_URL}/{endpoint}", params=params, timeout=30)
			resp.raise_for_status()
			data = resp.json()
			if data.get("error"):
				raise RuntimeError(f"Xotelo error: {data['error']}")
		except (requests.RequestException, ValueError, RuntimeError):
			if not have_cache:
				raise
			with open(path, encoding="utf-8") as f:
				return json.load(f), "cache_fallback"

		with open(path, "w", encoding="utf-8") as f:
			json.dump(data, f)
		time.sleep(1)
		return data, "live"

	with open(path, encoding="utf-8") as f:
		return json.load(f), "cache"


def fetch_hotel_list(n_hotels=60, page_size=30, live=False):
	"""
	Page through the Xotelo hotel list for NYC until we have n_hotels unique hotels.
	"""
	hotels = []
	skipped_no_geo = 0
	seen = set()
	offset = 0

	while len(hotels) < n_hotels:
		data, _ = cached_get("list", {"location_key": NYC_LOCATION_KEY, "offset": offset, "limit": page_size}, live=live)
		page = data["result"]["list"]
		if not page:
			break
		for h in page:
			if h["key"] in seen:
				continue
			seen.add(h["key"])

			geo = h.get("geo") or {}
			if geo.get("latitude") is None or geo.get("longitude") is None:
				skipped_no_geo += 1
				continue
			review = h.get("review_summary") or {}

			hotels.append({
				"hotel_key": h["key"],
				"name": h["name"],
				"type": h["accommodation_type"],
				"rating": review.get("rating"),
				"review_count": review.get("count"),
				"lat": geo["latitude"],
				"lon": geo["longitude"],
			})
		offset += page_size
	if skipped_no_geo:
		print(f"  skipped {skipped_no_geo} hotels with no coordinates")
	return hotels[:n_hotels]


def fetch_rates(hotel_key, chk_in=CHK_IN, chk_out=CHK_OUT, live=False, adults=None):
	"""
	Return a list of {platform, rate, tax, retrieved_at, source} for one hotel. Empty list if none.
	adults=None leaves the guest count to Xotelo's default (matches the batch cache).
	"""
	params = {
		"hotel_key": hotel_key,
		"chk_in":chk_in,
		"chk_out":chk_out,
		"currency": "USD",
	}
	if adults is not None:
		params["adults"] = adults
	data, source = cached_get("rates", params, live=live)
	
	if not data.get("result"):
		return []

	ts = data.get("timestamp")
	retrieved_at = datetime.fromtimestamp(ts / 1000, tz=timezone.utc).isoformat(timespec="seconds") if ts else None

	rows = []
	for r in data["result"].get("rates", []):
		if r.get("rate") is None:
			continue
		rows.append({
			"platform": r["name"],
			"rate": r["rate"],
			"tax": r["tax"] or 0,
			"retrieved_at": retrieved_at,
			"source": source,
		})
	return rows


def fetch_all_rates(hotels, chk_in=CHK_IN, chk_out=CHK_OUT, live=False, adults=None):
	"""
	Fetch rates for every hotel. Skips failures instead of crashing.
	Returns (long-format rate rows, list of (hotel_key, error) for failures).
	"""
	all_rows = []
	failed = []

	for i, h in enumerate(hotels, start=1):
		try:
			for r in fetch_rates(h["hotel_key"], chk_in, chk_out, live=live, adults=adults):
				r["hotel_key"] = h["hotel_key"]
				all_rows.append(r)
		except Exception as e:
			failed.append((h["hotel_key"], str(e)))

		if i % 10 == 0 or i == len(hotels):
			print(f"  rates: {i}/{len(hotels)} hotels, {len(failed)} failed")

	return all_rows, failed


def get_top5_precincts(month, path=INCIDENTS_PATH):
	"""
	TEMPORARY stand-in for Person 1's Task 2 output.
	Top 5 precincts by average incidents in the given month (1-12), 2022-2024.
	"""
	avg = get_precinct_month_avg(month, path)
	return [int(p) for p in avg.nlargest(5).index]


def get_precinct_month_avg(month, path=INCIDENTS_PATH):
	"""
	TEMPORARY stand-in for Person 1's Task 2 output.
	Average incidents in the given month (1-12), 2022-2024, for every precinct
	(not just the top 5). Used by Task 8 to give each attraction's precinct an
	incident level. Returns a pandas Series indexed by precinct (int).
	"""
	if not os.path.exists(path):
		zip_path = path + ".zip"
		if os.path.exists(zip_path):
			# Task 1's output is committed zipped (data/processed/ is gitignored
			# otherwise); extract it the first time it's needed.
			with zipfile.ZipFile(zip_path) as zf:
				zf.extractall(os.path.dirname(path))
		else:
			raise FileNotFoundError(
				f"{path} not found (and no {zip_path} to extract it from). "
				f"Make sure Task 1's output is present under data/processed/."
			)

	df = pd.read_parquet(path)
	monthly = df[df["month"] == month]
	return monthly.groupby("precinct")["total_incidents"].mean()


def build_hotels_table(hotels, rate_rows, precincts, nights=NIGHTS):
	"""
	One row per hotel: location, precinct, price per site, cheapest site, total stay.
	"""
	hotels_df = pd.DataFrame(hotels)
	rates_df = pd.DataFrame(rate_rows)
	rates_df["nightly_with_tax"] = rates_df["rate"] + rates_df["tax"]

	# One column per booking site
	prices = rates_df.pivot_table(index="hotel_key", columns="platform",
								  values="nightly_with_tax", aggfunc="min")
	prices.columns = ["price_" + c for c in prices.columns]

	# The cheapest site for each hotel
	idx = rates_df.groupby("hotel_key")["nightly_with_tax"].idxmin()
	cheapest = rates_df.loc[idx, ["hotel_key", "platform", "nightly_with_tax", "retrieved_at", "source"]]
	cheapest = cheapest.rename(columns={"platform": "cheapest_site",
										"nightly_with_tax": "cheapest_nightly"})

	df = hotels_df.merge(cheapest, on="hotel_key", how="inner")
	df = df.merge(prices, left_on="hotel_key", right_index=True, how="left")
	df["nights"] = nights
	df["total_stay"] = df["cheapest_nightly"] * nights

	# How old each price is, so cached prices can be labelled with their age
	now = datetime.now(timezone.utc)
	retrieved = pd.to_datetime(df["retrieved_at"], utc=True, format="ISO8601")
	df["price_age_hours"] = ((now - retrieved).dt.total_seconds() / 3600).round(1)

	df["precinct"] = pd.array(
		[find_precinct(lat, lon, precincts) for lat, lon in zip(df["lat"], df["lon"])],
		dtype="Int64",
	)

	df["is_hostel"] = (df["type"] == "Hostel") | df["name"].str.contains("hostel", case=False)

	return df.sort_values("cheapest_nightly").reset_index(drop=True)


def cheapest_options(df, max_price, month, include_hostels=True):
	"""
	Return (cheapest hotel within budget, cheapest within budget outside the
	month's top-5 incident precincts). Either can be None if nothing qualifies.
	Set include_hostels=False to skip hostels, whose prices may be for a shared dorm bed
	"""
	in_budget = df[df["cheapest_nightly"] <= max_price]
	if not include_hostels:
		in_budget = in_budget[~in_budget["is_hostel"]]
	in_budget = in_budget.sort_values("cheapest_nightly")
	if in_budget.empty:
		return None, None
	
	top5 = get_top5_precincts(month)
	outside_top5 = in_budget[in_budget["precinct"].notna() & ~in_budget["precinct"].isin(top5)]

	cheapest = in_budget.iloc[0]
	cheapest_outside = outside_top5.iloc[0] if not outside_top5.empty else None
	return cheapest, cheapest_outside


def find_nearby(df, hotel_key, radius_km=2.0):
	"""
	Every other hotel within radius_km of the chosen hotel, cheapest first.
	"""
	matches = df[df["hotel_key"] == hotel_key]
	if matches.empty:
		raise ValueError(f"Unknown hotel_key: {hotel_key}")
	base = matches.iloc[0]

	others = df[df["hotel_key"] != hotel_key].copy()
	others["distance_km"] = [
		haversine_km(base["lat"], base["lon"], lat, lon)
		for lat, lon in zip(others["lat"], others["lon"])
	]
	nearby = others[others["distance_km"] <= radius_km].sort_values("cheapest_nightly")

	savings = base["cheapest_nightly"] - nearby["cheapest_nightly"]
	nearby = nearby.assign(
		chosen_hotel=base["name"],
		chosen_nightly=base["cheapest_nightly"],
		savings_per_night=savings,
		total_savings=savings * base["nights"],
		distance_km=nearby["distance_km"].round(2),
	)
	cols = ["chosen_hotel", "chosen_nightly", "name", "hotel_key", "precinct",
			"cheapest_nightly", "cheapest_site", "savings_per_night", "total_savings", "distance_km"]
	return nearby[cols].reset_index(drop=True)


def describe_sources(df):
	"""One sentence saying where the prices came from, for the app to show the user."""
	counts = df["source"].value_counts()
	n_live = int(counts.get("live", 0))
	n_cache = int(counts.get("cache", 0))
	n_fallback = int(counts.get("cache_fallback", 0))

	if n_fallback:
		oldest = df.loc[df["source"] == "cache_fallback", "price_age_hours"].max()
		return (f"The hotel price service did not respond for {n_fallback} of {len(df)} hotels, "
				f"so their prices are cached and up to {oldest} hours old.")
	if n_cache and not n_live:
		oldest = df["price_age_hours"].max()
		return f"Prices for all {len(df)} hotels are cached, up to {oldest} hours old."
	if n_cache:
		return f"Live prices for {n_live} hotels; cached prices for {n_cache}."
	return f"Live prices for all {len(df)} hotels."


def search_hotels(check_in, nights, max_price, guests=1, n_hotels=20, live=True):
	"""
	Entry point for the app (Task 5). Returns (hotels table, sentence describing the price sources).
	Raises RuntimeError if no prices are available at all (API down and nothing cached).
	"""
	chk_in = date.fromisoformat(check_in)
	chk_out = chk_in + timedelta(days=nights)
	precincts = load_precincts()

	hotels = fetch_hotel_list(n_hotels, live=live)
	rows, failed = fetch_all_rates(hotels, chk_in.isoformat(), chk_out.isoformat(), live=live, adults=guests)
	if not rows:
		raise RuntimeError("The hotel price service is unavailable and no cached prices exist for these dates.")

	df = build_hotels_table(hotels, rows, precincts, nights=nights)
	df = df[df["cheapest_nightly"] <= max_price].reset_index(drop=True)
	return df, describe_sources(df)


if __name__ == "__main__":
	precincts = load_precincts()
	hotels = fetch_hotel_list(N_HOTELS)
	budget = 150
	chosen = ["ROW NYC", "The FIDI Hotel"]

	hotel_tables = []
	nearby_tables = []

	for month, (chk_in, chk_out) in STAYS.items():
		nights = (date.fromisoformat(chk_out) - date.fromisoformat(chk_in)).days
		print(f"\n=== Month {month}: {chk_in} to {chk_out} ({nights} nights) ===")

		rows, failed = fetch_all_rates(hotels, chk_in, chk_out)
		if failed:
			print(f"  first failures: {failed[:3]}")
		df = build_hotels_table(hotels, rows, precincts, nights=nights)
		df.insert(0, "stay_month", month)
		df.insert(1, "check_in", chk_in)

		print(f"{len(hotels)} hotels fetched, {len(df)} with prices, "
			  f"{df['precinct'].isna().sum()} outside NYC precincts, {len(failed)} failed")
		print(describe_sources(df))
		hotel_tables.append(df)

		print(f"Top-5 incident precincts: {get_top5_precincts(month)}")
		cheapest, cheapest_outside = cheapest_options(df, budget, month)
		for label, h in [("Cheapest under budget", cheapest),
						 ("Cheapest under budget, outside top 5", cheapest_outside)]:
			if h is None:
				print(f"{label}: none found")
			else:
				print(f"{label}: {h['name']} (precinct {h['precinct']}), "
					  f"${h['cheapest_nightly']}/night on {h['cheapest_site']}, ${h['total_stay']} total")
		cheapest_room, _ = cheapest_options(df, budget, month, include_hostels=False)
		if cheapest_room is not None:
			print(f"Cheapest non-hostel under budget: {cheapest_room["name"]} "
			f"(precinct {cheapest_room["precinct"]}), ${cheapest_room["cheapest_nightly"]}/night")


		for name in chosen:
			match = df.loc[df["name"] == name, "hotel_key"]
			if match.empty:
				print(f"{name}: no price for this stay, skipped")
				continue
			nb = find_nearby(df, match.iloc[0])
			nb.insert(0, "stay_month", month)
			print(f"{name}: {len(nb)} hotels within 2 km, "
				  f"{(nb['savings_per_night'] > 0).sum()} of them cheaper")
			nearby_tables.append(nb)

	os.makedirs("outputs", exist_ok=True)
	pd.concat(hotel_tables).to_csv(os.path.join("outputs", "t4_hotels.csv"), index=False)
	pd.concat(nearby_tables).to_csv(os.path.join("outputs", "t4_nearby.csv"), index=False)
	print("\nSaved outputs/t4_hotels.csv and outputs/t4_nearby.csv")

