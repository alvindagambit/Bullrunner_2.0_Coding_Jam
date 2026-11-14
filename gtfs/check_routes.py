
import json
from pathlib import Path

folder = Path(__file__).resolve().parent

with open(folder / "routes.json", "r", encoding="utf-8") as file:
    routes = json.load(file)

print("===== GTFS ROUTE NAMES =====")

for route in routes:
    print(f"Route ID: {route['route_id']} | Name: {route['name']}")

print(f"\nTotal Routes: {len(routes)}")
