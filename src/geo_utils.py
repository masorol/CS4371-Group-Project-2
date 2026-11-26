import json
import os
import requests


# to calculate difference between two locations
from math import radians, sin, cos, asin, sqrt


PRECINCTS_URL = "https://data.cityofnewyork.us/resource/y76i-bdw7.geojson"
PRECINCTS_PATH = os.path.join("data", "precincts.geojson")

def load_precincts(path=PRECINCTS_PATH):
	"""
	Download NYC precinct boundaries once, then load from disk.
	Returns a dict mapping precinct number (int) to its MultiPolygon coordinates
	"""

	if not os.path.exists(path):
		resp = requests.get(PRECINCTS_URL, timeout=60)
		resp.raise_for_status()

		with open(path, "w", encoding="utf-8") as f:
			f.write(resp.text)

	with open(path, encoding="utf-8") as f:
		geo = json.load(f)

	precincts = {}

	for feature in geo["features"]:
		pid = int(feature["properties"]["precinct"])
		geom = feature["geometry"]
		coords = geom["coordinates"]
		if geom["type"] == "Polygon":
			coords = [coords]
		precincts[pid] = coords
	
	return precincts


def point_in_ring(lon, lat, ring):
	"""
	Ray casting: cast a ray from the point toward (+x) east and
	count how many ring edges it crosses. Odd = inside, even=outside.
	"""
	inside = False
	n = len(ring)
	j = n - 1

	for i in range(n):
		xi, yi = ring[i]
		xj, yj = ring[j]

		if (yi > lat) != (yj > lat):
			x_cross = xi + (lat - yi) * (xj - xi) / (yj - yi)
			if lon < x_cross:
				inside = not inside

		j = i
	
	return inside


def point_in_multipolygon(lon, lat, multipolygon):
	"""
	True if the point is inside any polygon's outer ring and not in one of its holes
	"""
	for polygon in multipolygon:
		outer, holes = polygon[0], polygon[1:]
		if point_in_ring(lon, lat, outer) and not any(point_in_ring(lon, lat, h) for h in holes):
			return True

	return False


def find_precinct(lat, lon, precincts):
	"""
	Return the int precinct containing (lat, long), or None if outside NYC
	Note: takes lat first, the way coordinates is written
	"""
	for pid, multipolygon in precincts.items():
		if point_in_multipolygon(lon, lat, multipolygon):
			return pid
	return None


def haversine_km(lat1, lon1, lat2, lon2):
	"""
	Great-circle distance in KM between two (lat, lon) points.
	"""
	R = 6371.0
	dlat = radians(lat2 - lat1)
	dlon = radians(lon2 - lon1)
	a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2) ** 2
	return 2*R*asin(sqrt(a))