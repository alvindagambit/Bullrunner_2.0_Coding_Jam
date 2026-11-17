"""Live next stop and route direction for each bus in /buses.

Sources (all official USF / Passio data):
  - GTFS-Realtime vehiclePositions: per vehicle, the trip, the reported stop ID
    and current_stop_sequence.
  - Static GTFS in gtfs/ (stops.txt, routes.txt, trips.txt, stop_times.txt):
    stop names and coordinates, and the ordered stop sequence of each trip.
    Every USF trip is a loop that starts and ends at the same stop;
    trip_headsign and direction_id are not published.

Stops are read from gtfs/stops.txt, not frontend/public/stops.json. Vercel's
Python builder never bundles any "**/public/**" path into the function, so a
backend dependency on frontend/public silently disables next stops in
production. Names use the same rule as gtfs/convert_gtfs.py (the official name
without its "NNNNN - " stop-code prefix), so they equal stops.json exactly; a
test enforces this.

A bus gets a nextStop only when every check passes; otherwise it is null.
Nothing is inferred from proximity, and nothing is remembered between requests,
so a bus that changes route is evaluated afresh every time.

Checks, in order:
  1. Passio does not flag the bus's GPS as outdated.
  2. Exactly one vehicle in the feed has this bus's exact ID.
  3. The feed position is fresh (<= MAX_POSITION_AGE_SECONDS old).
  4. The feed position agrees with Passio's (<= MAX_GPS_DISTANCE_METERS).
  5. The vehicle's trip route matches the bus's current route.
  6. The reported stop ID exists in the official stop list (gtfs/stops.txt).
  7. If the trip's official stop order is known, the stop at
     current_stop_sequence must be the reported stop. A mismatch is
     conflicting evidence, so the result is null rather than a guess.

current_status: USF's feed omits it. GTFS-Realtime then specifies
IN_TRANSIT_TO, so the reported stop is the upcoming one (confirmed against the
official Passio GO tracker). If the feed ever reports STOPPED_AT, the bus is
*at* that stop: it becomes currentStop, and nextStop is the following stop
in the verified official order (or null if the order is unverified).

direction is set only when the stop order is verified (check 7). It names the
trip's final stop, which for USF's loops is the loop's start/end stop.
"""
import csv
import logging
import math
import re
import time
from collections import Counter
from functools import lru_cache
from pathlib import Path

import requests
from google.protobuf.message import DecodeError
from google.transit import gtfs_realtime_pb2

ROOT = Path(__file__).resolve().parent
GTFS_DIR = ROOT / "gtfs"  # must not live under any "public/" directory (see module docstring)
STOP_CODE_PREFIX = re.compile(r"^\d+\s*-\s*")  # same rule as gtfs/convert_gtfs.py

VEHICLE_POSITIONS_URL = "https://passio3.com/usf/passioTransit/gtfs/realtime/vehiclePositions"
REQUEST_TIMEOUT_SECONDS = 4
MAX_FEED_BYTES = 2_000_000
MAX_POSITION_AGE_SECONDS = 120
MAX_FUTURE_SKEW_SECONDS = 30
MAX_GPS_DISTANCE_METERS = 300

VehicleStatus = gtfs_realtime_pb2.VehiclePosition.VehicleStopStatus
logger = logging.getLogger(__name__)


class FeedError(Exception):
    """The vehiclePositions feed is unavailable or malformed."""


def haversine_meters(lat1, lng1, lat2, lng2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (math.sin((p2 - p1) / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lng2 - lng1) / 2) ** 2)
    return 2 * 6_371_000 * math.asin(math.sqrt(min(1.0, a)))


def _read_csv(name):
    with open(GTFS_DIR / name, encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


@lru_cache(maxsize=1)
def load_static():
    """Load and cross-validate stops and official trip patterns (cached)."""
    stops = {}
    for row in _read_csv("stops.txt"):
        stop_id = (row.get("stop_id") or "").strip()
        name = STOP_CODE_PREFIX.sub("", (row.get("stop_name") or "").strip())
        try:
            lat, lng = float(row["stop_lat"]), float(row["stop_lon"])
        except (KeyError, TypeError, ValueError):
            continue
        if stop_id and name and math.isfinite(lat) and math.isfinite(lng):
            stops[stop_id] = {"id": stop_id, "name": name, "lat": lat, "lng": lng}

    route_ids_by_name = {}
    for row in _read_csv("routes.txt"):
        name = (row.get("route_long_name") or row.get("route_short_name") or "").strip()
        if name:
            route_ids_by_name.setdefault(name, set()).add(row["route_id"])

    trip_route = {row["trip_id"]: row["route_id"] for row in _read_csv("trips.txt")}

    sequences = {}
    for row in _read_csv("stop_times.txt"):
        sequences.setdefault(row["trip_id"], {})[int(row["stop_sequence"])] = row["stop_id"]

    trips = {}
    for trip_id, by_seq in sequences.items():
        missing = sorted({s for s in by_seq.values() if s not in stops})
        if trip_id not in trip_route or missing:
            logger.warning("Ignoring trip %s pattern: unknown trip or stops %s", trip_id, missing)
            continue
        trips[trip_id] = {"route_id": trip_route[trip_id], "stops": by_seq}
    logger.info("Next-stop static GTFS loaded: %d stops, %d routes, %d trip patterns",
                len(stops), len(route_ids_by_name), len(trips))
    return {"stops": stops, "route_ids_by_name": route_ids_by_name, "trips": trips}


def fetch_vehicle_positions():
    """Return {vehicle_id: [VehiclePosition, ...]} from the official feed."""
    try:
        response = requests.get(
            VEHICLE_POSITIONS_URL,
            timeout=REQUEST_TIMEOUT_SECONDS,
            headers={"Accept": "application/x-protobuf"},
        )
        response.raise_for_status()
        if len(response.content) > MAX_FEED_BYTES:
            raise FeedError("vehiclePositions feed exceeds the permitted size")
        feed = gtfs_realtime_pb2.FeedMessage()
        feed.ParseFromString(response.content)
        if not feed.HasField("header"):
            raise FeedError("vehiclePositions feed has no header")
    except (requests.RequestException, DecodeError, ValueError) as exc:
        raise FeedError("Unable to retrieve vehiclePositions") from exc

    vehicles = {}
    for entity in feed.entity:
        if entity.is_deleted or not entity.HasField("vehicle"):
            continue
        vehicle = entity.vehicle
        if vehicle.HasField("vehicle") and vehicle.vehicle.id:
            vehicles.setdefault(vehicle.vehicle.id, []).append(vehicle)
    return vehicles


def _following_sequence(by_seq, seq):
    """The official sequence number after seq, wrapping around a loop."""
    ordered = sorted(by_seq)
    later = [n for n in ordered if n > seq]
    if later:
        return later[0]
    first, last = ordered[0], ordered[-1]
    if by_seq[first] == by_seq[last] and len(ordered) > 1:
        return ordered[1]  # loop: the last stop is also the first, continue with the second
    return None


def _evaluate(bus, matches, static, now):
    """Return (nextStop, currentStop, direction, reason) for one bus."""
    if bus.get("outdatedGps") is True:
        return None, None, None, "passio gps outdated"
    if len(matches) != 1:
        return None, None, None, f"{len(matches)} feed vehicles with id {bus.get('id')}"
    v = matches[0]
    if not (v.HasField("position") and v.HasField("timestamp")):
        return None, None, None, "feed position or timestamp missing"
    age = now - int(v.timestamp)
    if age > MAX_POSITION_AGE_SECONDS or age < -MAX_FUTURE_SKEW_SECONDS:
        return None, None, None, f"feed position age {age}s"
    try:
        distance = haversine_meters(float(bus["lat"]), float(bus["lng"]),
                                    v.position.latitude, v.position.longitude)
    except (KeyError, TypeError, ValueError):
        return None, None, None, "invalid bus coordinates"
    if distance > MAX_GPS_DISTANCE_METERS:
        return None, None, None, f"positions disagree by {distance:.0f}m"

    trip_route_id = v.trip.route_id if v.HasField("trip") and v.trip.HasField("route_id") else ""
    if not trip_route_id or trip_route_id not in static["route_ids_by_name"].get(bus.get("route"), set()):
        return None, None, None, f"route mismatch: bus {bus.get('route')!r}, feed route_id {trip_route_id!r}"

    stop_id = v.stop_id if v.HasField("stop_id") else ""
    stop = static["stops"].get(stop_id)
    if stop is None:
        return None, None, None, f"stop id {stop_id!r} missing from gtfs/stops.txt"

    pattern = static["trips"].get(v.trip.trip_id) if v.trip.HasField("trip_id") else None
    if pattern and pattern["route_id"] != trip_route_id:
        pattern = None
    sequence_verified = False
    seq = v.current_stop_sequence if v.HasField("current_stop_sequence") else None
    if pattern and seq is not None:
        if pattern["stops"].get(seq) != stop_id:
            return None, None, None, (f"sequence conflict: trip {v.trip.trip_id} seq {seq} is "
                                      f"{pattern['stops'].get(seq)!r}, feed says {stop_id!r}")
        sequence_verified = True

    stopped_at = v.HasField("current_status") and v.current_status == VehicleStatus.STOPPED_AT
    if stopped_at:
        current_stop, next_stop, next_seq = dict(stop), None, None
        if sequence_verified:
            next_seq = _following_sequence(pattern["stops"], seq)
            if next_seq is not None:
                next_stop = dict(static["stops"][pattern["stops"][next_seq]])
    else:
        current_stop, next_stop, next_seq = None, dict(stop), seq

    direction = None
    if sequence_verified and next_seq is not None:
        # GTFS stop_sequence only has to increase; it need not start at 1 or be
        # consecutive. The rider-facing position is the 1-based index of the
        # sequence value in the trip's ordered stop_times records, so it is
        # always within 1..stopsInTrip. A stop ID visited twice (e.g. a loop's
        # start/end) is told apart by its sequence value, never by its ID.
        ordered = sorted(pattern["stops"])
        end_id = pattern["stops"][ordered[-1]]
        direction = {
            "towardStopId": end_id,
            "toward": static["stops"][end_id]["name"],
            "loop": pattern["stops"][ordered[0]] == end_id,
            "stopPosition": ordered.index(next_seq) + 1,
            "stopsInTrip": len(ordered),
            "stopSequence": next_seq,  # raw GTFS stop_sequence value
        }
    return next_stop, current_stop, direction, "ok"


def add_next_stops(buses, now=None):
    """Add nextStop, currentStop and direction to each bus, in place.

    The existing "heading" field (compass degrees from Passio) is never touched.

    Never raises: on any failure every bus keeps null values and /buses is
    unaffected.
    """
    for bus in buses:
        bus["nextStop"] = bus["currentStop"] = bus["direction"] = None
    if not buses:
        return buses
    # Stage 1: static GTFS (cached after the first success).
    try:
        static = load_static()
    except Exception as exc:
        if _should_log("static"):
            logger.error("Next-stop data unavailable [stage=static]: cannot load gtfs/*.txt (%s: %s)%s",
                         type(exc).__name__, getattr(exc, "filename", None) or exc, _THROTTLE_NOTE)
        return buses
    # Stage 2: live vehiclePositions feed.
    try:
        vehicles = fetch_vehicle_positions()
    except FeedError as exc:
        cause = exc.__cause__ or exc
        if _should_log("feed"):
            logger.warning("Next-stop data unavailable [stage=feed]: vehiclePositions request failed (%s)%s",
                           type(cause).__name__, _THROTTLE_NOTE)
        return buses
    except Exception:
        if _should_log("feed"):
            logger.exception("Next-stop data unavailable [stage=feed]")
        return buses

    # Stage 3: per-vehicle validation. Routine results at DEBUG; a throttled WARNING
    # only when the failure looks systematic (eligible buses exist, none resolved).
    now = int(time.time()) if now is None else now
    reasons = Counter()
    for bus in buses:
        try:
            next_stop, current_stop, direction, reason = _evaluate(
                bus, vehicles.get(str(bus.get("id")), []), static, now)
        except Exception:
            if _should_log("evaluate"):
                logger.exception("Next-stop evaluation failed for bus %s", bus.get("id"))
            reasons["evaluation error"] += 1
            continue
        bus["nextStop"], bus["currentStop"], bus["direction"] = next_stop, current_stop, direction
        if reason != "ok":
            reasons[_reason_category(reason)] += 1
            logger.debug("Bus %s next stop unavailable: %s", bus.get("id"), reason)
    resolved = sum(1 for b in buses if b["nextStop"] or b["currentStop"])
    eligible = sum(1 for b in buses if b.get("outdatedGps") is not True)
    summary = (resolved, len(buses), len(vehicles), dict(reasons) or "{}")
    if eligible and not resolved and _should_log("validate"):
        logger.warning("Next-stop enrichment [stage=validate]: 0 resolved; %d/%d buses resolved; "
                       "feed vehicles=%d; unresolved=%s" + _THROTTLE_NOTE, *summary)
    else:
        logger.debug("Next-stop enrichment [stage=validate]: %d/%d buses resolved; "
                     "feed vehicles=%d; unresolved=%s", *summary)
    return buses


# Each distinct failure is logged at most once per window, so clients polling
# every few seconds cannot flood the logs during an outage.
LOG_THROTTLE_SECONDS = 300
_THROTTLE_NOTE = " (repeats suppressed for 5 min)"
_last_logged = {}


def _should_log(key, clock=time.monotonic):
    now = clock()
    last = _last_logged.get(key)
    if last is not None and now - last < LOG_THROTTLE_SECONDS:
        return False
    _last_logged[key] = now
    return True


def _reason_category(reason):
    """Collapse a detailed reason to a stable category for log summaries."""
    head = re.sub(r"\s+with id\b.*$", "", reason.split(":")[0])
    return re.sub(r"\d+", "N", head).strip()
