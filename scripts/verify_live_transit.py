"""Read-only live feed checks for Bullrunner 2.0.

From the repository root after activating the venv:
    pip install gtfs-realtime-bindings==3.0.0
    python scripts/verify_live_transit.py

Checks production bus locations against USF's independently published
GTFS-Realtime vehiclePositions feed. Reports candidate next-stop IDs but
NEVER treats nearest-stop geometry as a verified next stop.
No files, deployments or application state are modified.
"""
import json
import math
from pathlib import Path
import time

from google.transit import gtfs_realtime_pb2
import requests

ROOT = Path(__file__).resolve().parents[1]
BUS_URL = "https://bullrunner-2-0-coding-jam.vercel.app/api/buses"
GTFS_URL = "https://passio3.com/usf/passioTransit/gtfs/realtime/vehiclePositions"
STOPS_PATH = ROOT / "frontend" / "public" / "stops.json"
ROUTES_PATH = ROOT / "frontend" / "public" / "routes.json"
TIMEOUT = 10
MAX_GPS_DISTANCE_METERS = 350
MAX_POSITION_AGE_SECONDS = 120


def haversine_meters(lat1, lng1, lat2, lng2):
    radius_m = 6_371_000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * radius_m * math.atan2(math.sqrt(a), math.sqrt(max(0, 1 - a)))


def snapshot():
    response = requests.get(BUS_URL, timeout=TIMEOUT)
    response.raise_for_status()
    buses = response.json()
    if not isinstance(buses, list):
        raise ValueError("Production /api/buses returned a non-array")
    response = requests.get(GTFS_URL, timeout=TIMEOUT)
    response.raise_for_status()
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.ParseFromString(response.content)
    if not feed.HasField("header"):
        raise ValueError("VehiclePositions feed has no GTFS-Realtime header")
    vehicles = [e.vehicle for e in feed.entity if e.HasField("vehicle")]
    return buses, vehicles


def matches(bus, vehicles):
    identifiers = {str(v) for v in (bus.get("id"), bus.get("name")) if v is not None and str(v)}
    result = []
    for vehicle in vehicles:
        if not vehicle.HasField("vehicle"):
            continue
        fields = {vehicle.vehicle.id, vehicle.vehicle.label} - {""}
        if identifiers & fields:
            result.append(vehicle)
    return result


def inspect_snapshot(buses, vehicles, stops, routes):
    print(f"Production buses: {len(buses)} | Official GTFS-RT vehicles: {len(vehicles)}")
    match_count, verified_count, next_stop_count = 0, 0, 0
    now = int(time.time())
    for bus in buses:
        found = matches(bus, vehicles)
        if len(found) != 1:
            print(f"  Bus {bus.get('id')}: {len(found)} exact vehicle ID/label matches; next stop UNKNOWN")
            continue
        match_count += 1
        vehicle = found[0]
        if not vehicle.HasField("position"):
            print(f"  Bus {bus.get('id')}: matched but GTFS position missing")
            continue
        try:
            distance = haversine_meters(
                float(bus["lat"]), float(bus["lng"]),
                float(vehicle.position.latitude), float(vehicle.position.longitude),
            )
        except (ValueError, TypeError, KeyError):
            print(f"  Bus {bus.get('id')}: invalid production coordinates")
            continue

        timestamp = int(vehicle.timestamp) if vehicle.HasField("timestamp") else None
        age = now - timestamp if timestamp else None
        fresh = age is not None and 0 <= age <= MAX_POSITION_AGE_SECONDS
        close = distance <= MAX_GPS_DISTANCE_METERS
        route_name = bus.get("route")
        expected_route_id = routes.get(route_name)
        reported_route_id = vehicle.trip.route_id if vehicle.HasField("trip") else ""
        route_ok = not (expected_route_id and reported_route_id) or expected_route_id == reported_route_id
        if close and fresh and route_ok:
            verified_count += 1
        print(
            f"  Bus {bus.get('id')} ({route_name}): GTFS match; "
            f"GPS delta={distance:.0f}m, age={age if age is not None else 'unknown'}s, "
            f"route compatible={route_ok}, stale={bus.get('outdatedGps')}"
        )

        # In GTFS-RT, an IN_TRANSIT_TO/INCOMING_AT stop_id identifies the
        # upcoming stop, but only after vehicle ID and GPS have been validated.
        status = vehicle.current_status
        stop_id = vehicle.stop_id if vehicle.HasField("stop_id") else ""
        if close and fresh and route_ok and not bus.get("outdatedGps") and status in (0, 2) and stop_id in stops:
            next_stop_count += 1
            print(f"    Candidate upcoming stop: {stops[stop_id]['name']} (ID {stop_id}); confirm against Passio GO")
        else:
            print("    Next stop: NOT VERIFIED (missing stop ID, uncertain match, or stale data)")
    print(f"Exact matches: {match_count}; close+fresh+route-compatible: {verified_count}; next-stop candidates: {next_stop_count}")
    return {str(b["id"]): b for b in buses if b.get("id") is not None}


def main():
    stops = {str(s["id"]): s for s in json.loads(STOPS_PATH.read_text())}
    routes = {r["name"]: str(r["id"]) for r in json.loads(ROUTES_PATH.read_text())}
    print("Reading production and official GTFS-RT (no simulated data)...")
    first_buses, first_gtfs = snapshot()
    first = inspect_snapshot(first_buses, first_gtfs, stops, routes)
    print("Taking a second reading in 10 seconds. A stopped bus may not move.")
    time.sleep(10)
    second_buses, second_gtfs = snapshot()
    second = inspect_snapshot(second_buses, second_gtfs, stops, routes)
    common = sorted(set(first) & set(second))
    moved = []
    for bus_id in common:
        a, b = first[bus_id], second[bus_id]
        distance = haversine_meters(a["lat"], a["lng"], b["lat"], b["lng"])
        if distance > 3:
            moved.append((bus_id, round(distance, 1)))
    print(f"Same vehicle IDs across samples: {len(common)}; moved >3m: {moved}")
    print("A nonmoving bus is not automatically a failure. Compare several polls and the official Passio GO map.")


if __name__ == "__main__":
    main()
