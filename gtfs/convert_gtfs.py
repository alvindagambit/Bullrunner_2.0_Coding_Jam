
import json
import re
from pathlib import Path
 
import pandas as pd
 
# Folder containing the extracted GTFS files
GTFS = Path(__file__).resolve().parent
 
# The frontend loads routes.json / stops.json from frontend/public/
OUTPUT = GTFS.parent / "frontend" / "public"
 
# Route names Passio sends in /buses ("route"). The frontend matches buses to
# route lines by exact name, so every one of these should appear in routes.json.
PASSIO_ROUTE_NAMES = [
    "Green", "Blue", "Purple", "Red", "Brown", "Plum", "Orange",
]
 
# Where GTFS and Passio disagree on a color, use Passio's so the line and the
# bus dots match.
COLOR_OVERRIDES = {
    "Red": "#eb1b00",
}
 
 
def convert_routes():
    # Load GTFS files
    shapes = pd.read_csv(GTFS / "shapes.txt", dtype={"shape_id": str})
    trips = pd.read_csv(
        GTFS / "trips.txt",
        dtype={"shape_id": str, "route_id": str}
    )
    routes = pd.read_csv(
        GTFS / "routes.txt",
        dtype={"route_id": str}
    )

    routes = pd.read_csv(
    GTFS / "routes.txt",
    dtype={"route_id": str}
)

    routes["route_short_name"] = routes["route_short_name"].fillna("")
    routes["route_long_name"] = routes["route_long_name"].fillna("")
    routes["route_color"] = routes["route_color"].fillna("")
 
    # Sort coordinates in the correct order
    shapes = shapes.sort_values(
        ["shape_id", "shape_pt_sequence"]
    )
 
    # Connect each shape to its route
    shape_routes = trips[
        ["shape_id", "route_id"]
    ].dropna().drop_duplicates()
 
    shape_routes = shape_routes.merge(
        routes,
        on="route_id",
        how="left"
    )
 
    # Group shape coordinates
    grouped_shapes = {}
 
    for shape_id, group in shapes.groupby("shape_id"):
        points = []
 
        for _, point in group.iterrows():
            # Contract: [lat, lng] pairs
            points.append([
                float(point["shape_pt_lat"]),
                float(point["shape_pt_lon"])
            ])
 
        grouped_shapes[shape_id] = points
 
    # Build route JSON
    output = []
 
    for route_id, group in shape_routes.groupby("route_id"):
        route = group.iloc[0]
 
        name = (
            str(route["route_short_name"]).strip()
            or str(route["route_long_name"]).strip()
        )
 
        color = str(route.get("route_color", "")).strip()
        color = "#" + color.lstrip("#") if color else "#000000"
        color = COLOR_OVERRIDES.get(name, color)
 
        route_shapes = []
 
        for shape_id in group["shape_id"].unique():
            if shape_id in grouped_shapes:
                route_shapes.append({
                    "shape_id": shape_id,
                    "points": grouped_shapes[shape_id]
                })
 
        if not route_shapes:
            print(f"WARNING: route '{name}' has no shape, skipping")
            continue
 
        # Contract wants ONE flat list of points per route, so keep the
        # longest shape (usually the full loop).
        longest = max(route_shapes, key=lambda shape: len(shape["points"]))
 
        output.append({
            "id": route_id,
            "name": name,
            "color": color,
            "points": longest["points"]
        })
 
        if len(route_shapes) > 1:
            print(f"NOTE: route '{name}' has {len(route_shapes)} shapes, "
                  f"kept the longest ({len(longest['points'])} points)")
 
    OUTPUT.mkdir(parents=True, exist_ok=True)
 
    with open(OUTPUT / "routes.json", "w", encoding="utf-8") as file:
        json.dump(output, file, indent=2)
 
    print(f"Created routes.json with {len(output)} routes")
 
    # Compare against the names Passio uses
    gtfs_names = {route["name"] for route in output}
 
    missing = [n for n in PASSIO_ROUTE_NAMES if n not in gtfs_names]
    extra = sorted(gtfs_names - set(PASSIO_ROUTE_NAMES))
 
    if missing:
        print(f"MISSING from GTFS (Passio has them): {missing}")
    if extra:
        print(f"In GTFS but not in the Passio list: {extra}")
    if not missing and not extra:
        print("All route names match Passio")
 
 
def convert_stops():
    stops = pd.read_csv(
        GTFS / "stops.txt",
        dtype={"stop_id": str}
    )
    stops["stop_name"] = stops["stop_name"].fillna("")
 
    output = []
 
    for _, stop in stops.iterrows():
        # "00101 - Library" -> "Library"
        name = re.sub(r"^\d+\s*-\s*", "", str(stop["stop_name"]).strip())
 
        output.append({
            "id": stop["stop_id"],
            "name": name,
            "lat": float(stop["stop_lat"]),
            "lng": float(stop["stop_lon"])
        })
 
    OUTPUT.mkdir(parents=True, exist_ok=True)
 
    with open(OUTPUT / "stops.json", "w", encoding="utf-8") as file:
        json.dump(output, file, indent=2)
 
    print(f"Created stops.json with {len(output)} stops")
 
 
if __name__ == "__main__":
    convert_routes()
    convert_stops()
 