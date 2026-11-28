import os
import zipfile

import pandas as pd

PROCESSED_DIR = os.path.join("data", "processed")
INCIDENTS_PATH = os.path.join(PROCESSED_DIR, "neighbourhood_month.parquet")
INCIDENTS_ZIP = INCIDENTS_PATH + ".zip"

# Precincts to leave out of rankings. Empty for now, so nothing is excluded.
# Candidate: 116, created from parts of 105 and 113 near the end of 2022 - 2024, so its
# few reported incidents reflect when it started, not the area. To exclude it" {116}
EXCLUDED_PRECINCTS = set()

def load_incidents(path=INCIDENTS_PATH, zip_path=INCIDENTS_ZIP, exclude=EXCLUDED_PRECINCTS):
	"""
	Load Person 1's Task 1 output (one row per precinct, year, and month).
	Extracts the committed zip the first time, since Git ignores the unzipped folder.
	Precincts in `exclude` are dropped; pass exclude=() to keep every precinct.
	"""
	if not os.path.exists(path):
		with zipfile.ZipFile(zip_path) as z:
			z.extractall(PROCESSED_DIR)
	df = pd.read_parquet(path)

	if exclude:
		df = df[~df["precinct"].isin(exclude)]
	
	return df









