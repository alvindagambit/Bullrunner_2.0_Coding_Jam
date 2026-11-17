"""Read-only live feed checks for Bullrunner 2.0.

From the repository root after activating the venv:
    pip install -r requirements.txt   # includes gtfs-realtime-bindings and protobuf
    python scripts/verify_live_transit.py                    # comparison + diagnostics
    python scripts/verify_live_transit.py --diagnose-only    # only why buses lack a next stop
    python scripts/verify_live_transit.py --diagnose-only --samples 24 --interval 10   # ~4 min

Checks production bus locations against USF's independently published
GTFS-Realtime vehiclePositions feed. Reports candidate next-stop IDs but
NEVER treats nearest-stop geometry as a verified next stop.

Diagnostics explain every production bus with nextStop = null. They re-run the
backend's own validation (next_stop._evaluate); nothing is re-implemented.
Two conditions are distinguished, both read directly from production data:
  - validation rejection: nextStop and currentStop are both null
  - at stop, no next stop: currentStop is set (so every validation check
    passed), but no following stop could be given. This is not a rejection.
Production is bracketed by two feed snapshots (before and after). Evidence
levels:
  CONFIRMED     established by production's own data (outdatedGps, or
                currentStop set without nextStop)
  REPRODUCED    both feed snapshots show the same cause. This supports a likely
                cause but cannot prove what production itself received.
  NOT CAPTURED  the snapshots disagree, don't reproduce it, or weren't readable

Only GET requests are made. No files, deployments or application state are modified.
"""
import argparse
import json
import math
from pathlib import Path
import sys
import time

from google.transit import gtfs_realtime_pb2
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import next_stop  # noqa: E402  (backend validation, reused rather than duplicated)

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


VehicleStatus = gtfs_realtime_pb2.VehiclePosition.VehicleStopStatus
UPCOMING_STATUSES = (VehicleStatus.INCOMING_AT, VehicleStatus.IN_TRANSIT_TO)


def describe_status(vehicle):
    """Return (reported, status, label) for VehiclePosition.current_status.

    current_status is optional in GTFS-Realtime. When the feed omits it, protobuf
    returns the spec default IN_TRANSIT_TO, which is an assumption, not a report.
    The label always says which case applies.
    """
    status = vehicle.current_status
    name = VehicleStatus.Name(status)
    if vehicle.HasField("current_status"):
        return True, status, f"{name} (reported)"
    return False, status, f"{name} (ASSUMED: not reported by feed; GTFS-RT default)"


def inspect_snapshot(buses, vehicles, stops, routes):
    print(f"Production buses: {len(buses)} | Official GTFS-RT vehicles: {len(vehicles)}")
    match_count, verified_count, next_stop_count, explicit_status_count = 0, 0, 0, 0
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
        status_reported, status, status_label = describe_status(vehicle)
        if status_reported:
            explicit_status_count += 1
        stop_id = vehicle.stop_id if vehicle.HasField("stop_id") else ""
        sequence = vehicle.current_stop_sequence if vehicle.HasField("current_stop_sequence") else None
        print(f"    current_status: {status_label}; stop_id={stop_id or 'none'}; current_stop_sequence={sequence}")
        if close and fresh and route_ok and not bus.get("outdatedGps") and status in UPCOMING_STATUSES and stop_id in stops:
            next_stop_count += 1
            basis = "status reported by feed" if status_reported else "status ASSUMED (GTFS-RT default, not reported)"
            print(f"    Candidate upcoming stop: {stops[stop_id]['name']} (ID {stop_id}); {basis}; confirm against Passio GO")
        else:
            print("    Next stop: NOT VERIFIED (missing stop ID, at-stop status, uncertain match, or stale data)")
    print(
        f"Exact matches: {match_count}; close+fresh+route-compatible: {verified_count}; "
        f"next-stop candidates: {next_stop_count}; "
        f"current_status reported: {explicit_status_count}/{match_count} (others assumed IN_TRANSIT_TO)"
    )
    return {str(b["id"]): b for b in buses if b.get("id") is not None}


# --- Next-stop validation diagnostics ---------------------------------------

CONFIRMED = "CONFIRMED"        # established by production's own response
REPRODUCED = "REPRODUCED"      # both feed snapshots agree; likely, not proven
NOT_CAPTURED = "NOT CAPTURED"  # evidence unavailable or inconsistent

REJECTION = "validation rejection"
AT_STOP = "at stop, no next stop"


def fetch_production_buses():
    response = requests.get(BUS_URL, timeout=TIMEOUT)
    response.raise_for_status()
    buses = response.json()
    if not isinstance(buses, list):
        raise ValueError("Production /api/buses returned a non-array")
    return buses


def _try_feed():
    """One vehiclePositions snapshot via the backend's fetcher, or None if unavailable."""
    try:
        return next_stop.fetch_vehicle_positions(), int(time.time())
    except next_stop.FeedError:
        return None, int(time.time())


def capture():
    """Feed snapshot, then production /buses, then a second feed snapshot (all GET)."""
    before, t_before = _try_feed()
    buses = fetch_production_buses()
    after, t_after = _try_feed()
    return buses, (before, t_before), (after, t_after)


def _evidence(bus, vehicles, static, now):
    """Feed facts relevant to the rejection, for one snapshot."""
    if vehicles is None:
        return {"feed": "unavailable"}
    found = vehicles.get(str(bus.get("id")), [])
    evidence = {"feed_vehicles_with_id": len(found)}
    if len(found) != 1:
        return evidence
    v = found[0]
    trip_id = v.trip.trip_id if v.HasField("trip") and v.trip.HasField("trip_id") else None
    seq = v.current_stop_sequence if v.HasField("current_stop_sequence") else None
    pattern = static["trips"].get(trip_id) if trip_id else None
    ordered = sorted(pattern["stops"]) if pattern else []
    is_loop = bool(ordered) and pattern["stops"][ordered[0]] == pattern["stops"][ordered[-1]]
    evidence.update({
        "trip_id": trip_id,
        "feed_route_id": v.trip.route_id if v.HasField("trip") and v.trip.HasField("route_id") else None,
        "bus_route_ids": sorted(static["route_ids_by_name"].get(bus.get("route"), set())),
        "current_status": (next_stop.VehicleStatus.Name(v.current_status) if v.HasField("current_status")
                           else "not reported (IN_TRANSIT_TO assumed)"),
        "stop_sequence": seq,
        "stop_id": v.stop_id if v.HasField("stop_id") else None,
        "official_stop_at_sequence": pattern["stops"].get(seq) if pattern and seq is not None else None,
        "trip_is_loop": is_loop if pattern else None,
        "at_final_stop": (seq == ordered[-1]) if ordered and seq is not None else None,
        "at_loop_boundary": bool(is_loop and seq is not None and seq in (ordered[0], ordered[-1])),
        "position_age_s": now - int(v.timestamp) if v.HasField("timestamp") else None,
    })
    try:
        evidence["gps_delta_m"] = round(next_stop.haversine_meters(
            float(bus["lat"]), float(bus["lng"]), v.position.latitude, v.position.longitude))
    except (KeyError, TypeError, ValueError):
        evidence["gps_delta_m"] = None
    return evidence


def _at_stop_cause(result, evidence):
    """Why a snapshot shows the bus stopped without a following stop, or None."""
    next_stop_, current_stop, _direction, reason = result
    if reason != "ok" or not current_stop or next_stop_:
        return None
    if evidence.get("official_stop_at_sequence") is None:
        return "following stop not verifiable (official stop order unavailable for this trip/sequence)"
    if evidence.get("at_final_stop") and not evidence.get("trip_is_loop"):
        return "terminal stop: no following stop in the official order"
    return "no following stop in the official order"


def diagnose(buses, before, after, static):
    """Explain each production bus whose nextStop is null.

    before/after are (vehicles_or_None, unix_time) feed snapshots taken just
    before and just after production was read. Returns one record per bus.
    """
    records = []
    for bus in buses:
        if bus.get("nextStop"):
            continue
        current = bus.get("currentStop")
        record = {"bus_id": bus.get("id"), "route": bus.get("route"),
                  "condition": AT_STOP if current else REJECTION}
        if current:
            # currentStop is only set after every validation check passes.
            record["production_fact"] = (f"{CONFIRMED}: production reports currentStop "
                                         f"{current.get('name')} ({current.get('id')}); validation passed, "
                                         f"not a rejection")
        elif bus.get("outdatedGps") is True:
            record.update(status=CONFIRMED, category="passio gps outdated",
                          detail="production reports outdatedGps=true", evidence={})
            records.append(record)
            continue
        evidence = {"before": _evidence(bus, before[0], static, before[1]),
                    "after": _evidence(bus, after[0], static, after[1])}
        if before[0] is None or after[0] is None:
            record.update(status=NOT_CAPTURED, category="feed snapshot unavailable",
                          detail="could not read vehiclePositions on both sides of the production request",
                          evidence=evidence)
            records.append(record)
            continue
        results = [next_stop._evaluate(dict(bus), vehicles.get(str(bus.get("id")), []), static, now)
                   for vehicles, now in (before, after)]
        if current:
            causes = [_at_stop_cause(res, evidence[side]) for res, side in zip(results, ("before", "after"))]
            if causes[0] and causes[0] == causes[1]:
                record.update(status=REPRODUCED, category=causes[0],
                              detail="both snapshots show the bus stopped with no verifiable following stop",
                              evidence=evidence)
            else:
                record.update(status=NOT_CAPTURED, category="cause not captured",
                              detail=f"snapshots do not both show this state; before: {results[0][3]!r}, "
                                     f"after: {results[1][3]!r}", evidence=evidence)
            records.append(record)
            continue
        reasons = [res[3] for res in results]
        categories = [None if r == "ok" else next_stop._reason_category(r) for r in reasons]
        if categories[0] and categories[0] == categories[1]:
            record.update(status=REPRODUCED, category=categories[0], detail=reasons[1], evidence=evidence)
        elif categories == [None, None]:
            record.update(status=NOT_CAPTURED, category="not reproduced",
                          detail="both feed snapshots validate this bus; production's rejection was not reproduced",
                          evidence=evidence)
        else:
            record.update(status=NOT_CAPTURED, category="feed changed during capture",
                          detail=f"before: {reasons[0]!r}; after: {reasons[1]!r}", evidence=evidence)
        records.append(record)
    return records


def print_diagnostics(buses, records):
    eligible = [b for b in buses if b.get("outdatedGps") is not True]
    with_next = sum(1 for b in buses if b.get("nextStop"))
    at_stop = sum(1 for r in records if r["condition"] == AT_STOP)
    rejected = sum(1 for r in records if r["condition"] == REJECTION)
    print(f"Next-stop diagnostics: {with_next}/{len(buses)} buses with a next stop "
          f"({len(eligible)} eligible); {at_stop} at a stop without a next stop; {rejected} validation rejections")
    for r in records:
        boundary = any(r["evidence"].get(side, {}).get("at_loop_boundary") for side in ("before", "after"))
        print(f"  Bus {r['bus_id']} ({r['route']}): {r['condition']}"
              f"{' (at loop start/end)' if boundary else ''}")
        if "production_fact" in r:
            print(f"      {r['production_fact']}")
        print(f"      cause {r['status']}: {r['category']} | {r['detail']}")
        for side in ("before", "after"):
            if side in r["evidence"]:
                print(f"      {side}: {json.dumps(r['evidence'][side], sort_keys=True)}")
    if eligible and not any(b.get("nextStop") or b.get("currentStop") for b in eligible):
        print("  WARNING: no eligible bus resolved. This looks systematic; check the Vercel logs for [stage=...].")


def run_diagnostics(samples=1, interval=10):
    static = next_stop.load_static()
    for i in range(samples):
        buses, before, after = capture()
        print(f"\n[{time.strftime('%H:%M:%S')}] sample {i + 1}/{samples}")
        print_diagnostics(buses, diagnose(buses, before, after, static))
        if i + 1 < samples:
            time.sleep(interval)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--diagnose-only", action="store_true",
                        help="only explain buses that production returned without a next stop")
    parser.add_argument("--samples", type=int, default=1, help="diagnostic samples to take (default 1)")
    parser.add_argument("--interval", type=float, default=10, help="seconds between samples (default 10)")
    args = parser.parse_args(argv)
    if args.diagnose_only:
        run_diagnostics(args.samples, args.interval)
        return

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
    run_diagnostics(args.samples, args.interval)


if __name__ == "__main__":
    main()
