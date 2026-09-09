# debug_parse.py
import json
from pathlib import Path

raw_path = Path("ais_attribution_output/sanchi_2018_gfw_raw.json")

with open(raw_path, "r", encoding="utf-8") as f:
    data = json.load(f)

print("Top-level keys:", list(data.keys()))
print()

if "entries" in data:
    entries = data["entries"]
    print("entries type:", type(entries))
    if isinstance(entries, list):
        print("len(entries):", len(entries))
        if entries:
            first = entries[0]
            print("First entry type:", type(first))
            if isinstance(first, dict):
                print("First entry keys:", list(first.keys()))
                for k, v in first.items():
                    if isinstance(v, list):
                        print(f"  {k}: list of length {len(v)}")
                        if v and isinstance(v[0], dict):
                            print(f"    first element keys: {list(v[0].keys())}")
    else:
        print("entries:", entries)
else:
    print("No 'entries' key found.")

print()
print("Full JSON (first 3000 chars):")
print(json.dumps(data, indent=2)[:3000])