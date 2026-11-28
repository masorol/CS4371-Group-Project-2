"""
One-off: add _received at at to cache files saved before cached_get recorded it.
Uses each file's modification time, which on the original machine is when it was saved.
"""

import json
import os
from datetime import datetime, timezone


CACHE_DIR = os.path.join("cache", "xotelo")

updated = 0

for name in os.listdir(CACHE_DIR):
	path = os.path.join(CACHE_DIR, name)
	with open(path, encoding="utf-8") as f:
		data = json.load(f)
	if "_received_at" in data:
		continue
	saved = datetime.fromtimestamp(os.path.getmtime(path), tz=timezone.utc)
	data["_received_at"] = saved.isoformat(timespec="seconds")
	data["_received_at_source"] = "file modification time (backfilled)"

	with open(path, "w", encoding="utf-8") as f:
		json.dump(data, f)

	updated += 1

print(f"Backfilled {updated} cache files")