import json
import os
import time
from datetime import date, datetime, timezone

import pandas as pd
import requests

from src.geo_utils import load_precincts, find_precinct, haversine_km


CACHE_DIR = os.path.join("cache", "xotelo")
BASE_URL = "https://data.xotelo.com/api"
NYC_LOCATION_KEY = "g60763"
INCIDENTS_PATH = os.path.join("data", "neighbourhood_month_example.parquet")

CHK_IN = "2027-01-15"
CHK_OUT = "2027-01-18"
NIGHTS = (date.fromisoformat(CHK_OUT) - date.fromisoformat(CHK_IN)).days


def cached_get(endpoint, params):
	"""
	GET from Xotelo, saving each response to disk.
	Later calls with the same params read the saved file instead of hitting the API.
	"""
	os.makedirs(CACHE_DIR, exist_ok=True)
	name = endpoint + "_" + "_".join(f"{k}-{v}" for k, v in sorted(params.items()))
	path = os.path.join(CACHE_DIR, name + ".json")

	if os.path.exists(path):
		with open(path, encoding="utf-8") as f:
			return json.load(f)

	resp = requests.get(f"{BASE_URL}/{endpoint}", params=params, timeout=30)
	resp.raise_for_status()
	data = resp.json()

	with open(path, "w", encoding="utf-8") as f:
		json.dump(data, f)
	time.sleep(1)

	return data


def fetch_hotel_list(n_hotels=60, page_size=30):
	"""
	Page through the Xotelo hotel list for NYC until we have n_hotels unique hotels.
	"""
	hotels = []
	seen = set()
	offset = 0

	while len(hotels) < n_hotels:
		data = cached_get("list", {"location_key": NYC_LOCATION_KEY, "offset": offset, "limit": page_size})
		if data.get("error"):
			raise RuntimeError(f"Xotelo error: {data['error']}")
		page = data["result"]["list"]
		if not page:
			break
		for h in page:
			if h["key"] in seen:
				continue
			seen.add(h["key"])
			hotels.append({
				"hotel_key": h["key"],
				"name": h["name"],
				"type": h["accommodation_type"],
				"rating": h["review_summary"]["rating"],
				"review_count": h["review_summary"]["count"],
				"lat": h["geo"]["latitude"],
				"lon": h["geo"]["longitude"],
			})
		offset += page_size
	return hotels[:n_hotels]


def fetch_rates(hotel_key, chk_in=CHK_IN, chk_out=CHK_OUT):
	"""
	Return a list of {platform, rate, tax, retrieved_at} for one hotel. Empty list if none.
	"""
	data = cached_get("rates", {
		"hotel_key": hotel_key,
		"chk_in": chk_in,
		"chk_out": chk_out,
		"currency": "USD",
	})
	if data.get("error") or not data.get("result"):
		return []

	ts = data.get("timestamp")
	retrieved_at = datetime.fromtimestamp(ts / 1000, tz=timezone.utc).isoformat() if ts else None

	rows = []
	for r in data["result"].get("rates", []):
		if r.get("rate") is None:
			continue
		rows.append({
			"platform": r["name"],
			"rate": r["rate"],
			"tax": r["tax"] or 0,
			"retrieved_at": retrieved_at,
		})
	return rows


def fetch_all_rates(hotels):
	"""
	Fetch rates for every hotel. Skips failures instead of crashing.
	Returns (long-format rate rows, list of (hotel_key, error) for failures).
	"""
	all_rows = []
	failed = []

	for i, h in enumerate(hotels, start=1):
		try:
			for r in fetch_rates(h["hotel_key"]):
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
	df = pd.read_parquet(path)
	monthly = df[df["month"] == month]
	avg = monthly.groupby("precinct")["total_incidents"].mean()
	return [int(p) for p in avg.nlargest(5).index]


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
	cheapest = rates_df.loc[idx, ["hotel_key", "platform", "nightly_with_tax", "retrieved_at"]]
	cheapest = cheapest.rename(columns={"platform": "cheapest_site",
										"nightly_with_tax": "cheapest_nightly"})

	df = hotels_df.merge(cheapest, on="hotel_key", how="inner")
	df = df.merge(prices, left_on="hotel_key", right_index=True, how="left")
	df["nights"] = nights
	df["total_stay"] = df["cheapest_nightly"] * nights

	df["precinct"] = pd.array(
		[find_precinct(lat, lon, precincts) for lat, lon in zip(df["lat"], df["lon"])],
		dtype="Int64",
	)

	return df.sort_values("cheapest_nightly").reset_index(drop=True)


def cheapest_options(df, max_price, month):
	"""
	Return (cheapest hotel within budget, cheapest within budget outside the
	month's top-5 incident precincts). Either can be None if nothing qualifies.
	"""
	in_budget = df[df["cheapest_nightly"] <= max_price].sort_values("cheapest_nightly")
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


if __name__ == "__main__":
	precincts = load_precincts()
	hotels = fetch_hotel_list(60)
	rows, failed = fetch_all_rates(hotels)
	df = build_hotels_table(hotels, rows, precincts)

	print(f"{len(hotels)} hotels fetched, {len(df)} with prices, "
		  f"{df['precinct'].isna().sum()} outside NYC precincts, {len(failed)} failed")
	print(df[["name", "precinct", "cheapest_site", "cheapest_nightly", "total_stay"]].head(10).to_string())

	os.makedirs("outputs", exist_ok=True)
	df.to_csv(os.path.join("outputs", "t4_hotels.csv"), index=False)
	print("Saved outputs/t4_hotels.csv")

	# Cheapest options within budget
	month = date.fromisoformat(CHK_IN).month
	budget = 150
	print(f"\nTop-5 incident precincts for month {month}: {get_top5_precincts(month)}")
	cheapest, cheapest_outside = cheapest_options(df, budget, month)
	for label, h in [("Cheapest under budget", cheapest),
					 ("Cheapest under budget, outside top 5", cheapest_outside)]:
		if h is None:
			print(f"{label}: none found")
		else:
			print(f"{label}: {h['name']} (precinct {h['precinct']}), "
				  f"${h['cheapest_nightly']}/night on {h['cheapest_site']}, ${h['total_stay']} total")

	# Nearby alternatives for two chosen hotels
	chosen = ["ROW NYC", "The FIDI Hotel"]
	nearby_tables = []
	for name in chosen:
		key = df.loc[df["name"] == name, "hotel_key"].iloc[0]
		nb = find_nearby(df, key)
		print(f"\n{name}: {len(nb)} hotels within 2 km, "
			  f"{(nb['savings_per_night'] > 0).sum()} of them cheaper")
		print(nb[["name", "precinct", "cheapest_nightly", "savings_per_night", "distance_km"]].head(5).to_string())
		nearby_tables.append(nb)

	pd.concat(nearby_tables).to_csv(os.path.join("outputs", "t4_nearby.csv"), index=False)
	print("\nSaved outputs/t4_nearby.csv")