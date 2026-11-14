
import json
from pathlib import Path

import pandas as pd

# Folder containing the extracted GTFS files
GTFS = Path(__file__).resolve().parent


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
    ).fillna("")

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
            points.append({
                "lat": float(point["shape_pt_lat"]),
                "lng": float(point["shape_pt_lon"])
            })

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

        route_shapes = []

        for shape_id in group["shape_id"].unique():
            if shape_id in grouped_shapes:
                route_shapes.append({
                    "shape_id": shape_id,
                    "points": grouped_shapes[shape_id]
                })

        output.append({
            "route_id": route_id,
            "name": name,
            "color": color,
            "shapes": route_shapes
        })

    with open("routes.json", "w", encoding="utf-8") as file:
        json.dump(output, file, indent=2)

    print(f"Created routes.json with {len(output)} routes")


def convert_stops():
    stops = pd.read_csv(
        GTFS / "stops.txt",
        dtype={"stop_id": str}
    ).fillna("")

    output = []

    for _, stop in stops.iterrows():
        output.append({
            "stop_id": stop["stop_id"],
            "name": stop["stop_name"],
            "lat": float(stop["stop_lat"]),
            "lng": float(stop["stop_lon"])
        })

    with open("stops.json", "w", encoding="utf-8") as file:
        json.dump(output, file, indent=2)

    print(f"Created stops.json with {len(output)} stops")


if __name__ == "__main__":
    convert_routes()
    convert_stops()
