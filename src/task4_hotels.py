import json
import os
import time
from datetime import date, datetime, timezone

import requests
import pandas as pd

from src.geo_utils import load_precincts, find_precinct


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
	Later calls with the same params read the saved file instead of hitting the API
	"""
	os.makedirs(CACHE_DIR, exist_ok=True)
	name = endpoint + "_" + "_".join(f"{k}-{v}" for k, v in sorted(params.items()))
	path = os.path.join(CACHE_DIR, name + ".json")

	if os.path.exists(path):
		with open(path, encoding="utf-8") as f:
			return json.load(f)
	
	resp = requests.get(f"{BASE_URL}/{endpoint}", params=params, timeout = 30)
	resp.raise_for_status()
	data = resp.json()

	with open(path, "w", encoding="utf-8") as f:
		json.dump(data, f)
	time.sleep(1)

	return data


def fetch_hotel_list(n_hotels=60, page_size=30):
	"""
	Page through the Xotelo hotel list for NYC until we have n_hotels.
	"""
	hotels=[]
	seen=set()
	offset=0

	while len(hotels) < n_hotels:
		data = cached_get("list", {"location_key":NYC_LOCATION_KEY, "offset":offset, "limit":page_size})
		if data.get("error"):
			raise RuntimeError(f"Xotelo error: {data["error"]}")
		page = data["result"]["list"]
		if not page:
			break
		for h in page:
			if h["key"] in seen:
				continue
			seen.add(h["key"])
			hotels.append({
				"hotel_key" : h["key"],
				"name": h["name"],
				"type": h["accommodation_type"],
				"rating":h["review_summary"]["rating"],
				"review_count": h["review_summary"]["count"],
				"lat":h["geo"]["latitude"],
				"lon":h["geo"]["longitude"],
			})
		offset += page_size
	return hotels[:n_hotels]


def fetch_rates(hotel_key, chk_in=CHK_IN, chk_out=CHK_OUT):
	"""
	Return a list of {platform, rate, tax} for one hotel. Empty list if None.
	"""
	data = cached_get("rates", {
		"hotel_key": hotel_key,
		"chk_in":chk_in,
		"chk_out":chk_out,
		"currency":"USD"
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
			"platform":r["name"],
			"rate":r["rate"],
			"tax":r["tax"] or 0,
			"retrieved_at": retrieved_at,
		})
	return rows


def fetch_all_rates(hotels):
	"""
	Fetch rates for every hotel. Skips failures instead of crashing.
	Returns (long-format rate rows, list of hotel_keys that failed).
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
		
		if i % 50 == 0 or i == len(hotels):
			print(f" rates: {i}/{len(hotels)} hotels, {len(failed)} failed")

	return all_rows, failed

def get_top5_precincts(months, path=INCIDENTS_PATH):
	"""
	TEMPORARY stand-in for Person 1's Task 2 output.
	Top 5 precincts by average incidents in the given month (1-2), 2022 - 2024.
	"""
	df = pd.read_parquet(path)
	monthly = df[df["month"] == month]
	avg = monthly.groupby("precinct")["total_incidents"].mean()
	return [int(p) for p in avg.nlargest(5).index]


def build_hotels_table(hotels, rate_rows, precincts, nights=NIGHTS):
	"""
	One row per hotel, location, precinct, price per site, cheapest site, total stay.
	""" 
	hotels_df = pd.DataFrame(hotels)
	rates_df = pd.DataFrame(rate_rows)
	rates_df["nightly_with_tax"] = rates_df["rate"] + rates_df["tax"]

	# One column per booking site:
	prices = rates_df.pivot_table(index="hotel_key", columns="platform", values="nightly_with_tax", aggfunc="min")
	prices.columns = ["price_" + c for c in prices.columns]

	# The cheapest for each hotel:
	idx = rates_df.groupby("hotel_key")["nightly_with_tax"].idxmin()
	cheapest = rates_df.loc[idx, ["hotel_key", "platform", "nightly_with_tax", "retrieved_at"]]
	cheapest = cheapest.rename(columns={"platform":"cheapest site", "nightly_with_tax":"cheapest_nightly"})

	df = hotels_df.merge(cheapest, on="hotel_key", how="inner")
	df = df.merge(prices, left_on="hotel_key", right_index=True, how="left")
	df["nights"] = nights
	df["total_stay"] = df["cheapest_nightly"] * nights

	df["precinct"] = pd.array(
		[find_precinct(lat, lon, precincts) for lat, lon in zip(df["lat"], df["lon"])],
		dtype="Int64",
	)

	return df.sort_values("cheapest_nightly").reset_index(drop=True)



if __name__ == "__main__":
	precincts = load_precincts()
	hotels = fetch_hotel_list(60)
	rows, failed = fetch_all_rates(hotels)
	df = build_hotels_table(hotels, rows, precincts)

	print(f"{len(hotels)} hotels fetched, {len(df)} with prices, {df["precinct"].isna().sum()} outside NYC precincts, {len(failed)} failed")
	print(df[["name", "precinct", "cheapest site", "cheapest_nightly", "total_stay"]].head(10).to_string())

