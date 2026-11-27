import calendar
import os

import pandas as pd

TEMPS_PATH = os.path.join("data", "city_temperature.csv")
INCIDENTS_PATH = os.path.join("data", "neighbourhood_month_example.parquet")
IDEAL_TEMP_F = 70
WEIGHTS = {"comfort":0.6, "safety":0.4}

def monthly_temperatures(path=TEMPS_PATH, city="New York"):
	"""
	Average temperature per month for the city over 2020-2024, and distance from 70F.
	"""
	df = pd.read_csv(path)
	ny = df[(df["City"] == city) & df["Year"].between(2020, 2024)]
	ny = ny[ny["AvgTemperature"] != -99]

	temps = ny.groupby("Month")["AvgTemperature"].mean().rename("avg_temp_f")
	out = temps.to_frame()
	out["distance_from_70f"] = (out["avg_temp_f"] - IDEAL_TEMP_F).abs()
	return out


def monthly_incidents(path=INCIDENTS_PATH):
	"""
	City-wide incidents per month: the average monthly total over 2022-2024,
	and the average per day (so short months like February are not favoured
	)."""
	df = pd.read_parquet(path)
	totals = df.groupby(["year", "month"])["total_incidents"].sum().reset_index()
	totals["days"] = [calendar.monthrange(y, m)[1] for y, m in zip(totals["year"], totals["month"])]
	totals["per_day"] = totals["total_incidents"] / totals["days"]

	out = totals.groupby("month").agg(
		avg_monthly_incidents=("total_incidents", "mean"),
		avg_incidents_per_day=("per_day", "mean"),
	)
	out.index.name = "Month"
	return out


def minmax(s):
	"""Scale a column to 0-1."""
	return (s - s.min()) / (s.max() - s.min())


def score_months(weights=WEIGHTS):
	"""Combine temperature and incidents into one score per month, best first."""
	df = monthly_temperatures().join(monthly_incidents())
	df["comfort_score"] = 1 - minmax(df["distance_from_70f"])
	df["safety_score"] = 1 - minmax(df["avg_incidents_per_day"])
	df["score"] = weights["comfort"] * df["comfort_score"] + weights["safety"] * df["safety_score"]

	df = df.sort_values("score", ascending=False)
	df["rank"] = range(1, len(df) + 1)
	df.insert(0, "month_name", [calendar.month_name[m] for m in df.index])
	return df.round(3)


if __name__ == "__main__":
	df = score_months()
	print(df.to_string())

	os.makedirs("outputs", exist_ok=True)
	df.to_csv(os.path.join("outputs", "t6_best_months.csv"))
	print(f"\nTop 3: {', '.join(df['month_name'].head(3))}")

	# Sensitivity check: does the top 3 change with different weights?
	for w in [0.5, 0.7]:
		alt = score_months({"comfort": w, "safety": 1 - w})
		print(f"Comfort {w:.0%} / safety {1 - w:.0%}: {', '.join(alt['month_name'].head(3))}")