"""Tests for live next-stop and direction enrichment of /buses.

Uses the real repository data (frontend/public/stops.json and the official
gtfs/*.txt trip sequences) and constructed GTFS-Realtime feeds. No network.

Run from the repo root:  python -m unittest discover -s tests -v
"""
import csv
import json
import os
import sys
import unittest
from unittest import mock

import requests
from google.transit import gtfs_realtime_pb2

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import next_stop  # noqa: E402
from app import app  # noqa: E402
from test_buses import make_bus, mock_response, payload  # noqa: E402

NOW = 1_794_860_000
RED_ROUTE_ID, BLUE_ROUTE_ID = "3095", "3093"
RED_TRIP = "1187361"   # official Red loop: 35 stops, Marshall Student Center -> ... -> Marshall Student Center
BLUE_TRIP = "1076994"
Status = gtfs_realtime_pb2.VehiclePosition


def static():
    return next_stop.load_static()


def stop(stop_id):
    return static()["stops"][stop_id]


def red_stop_id(seq):
    return static()["trips"][RED_TRIP]["stops"][seq]


def make_vehicle(vehicle_id="9796", seq=2, stop_id=None, trip_id=RED_TRIP, route_id=RED_ROUTE_ID,
                 lat=None, lng=None, timestamp=NOW - 5, status=None, label="1124", omit=()):
    stop_id = red_stop_id(seq) if stop_id is None and trip_id == RED_TRIP else stop_id
    s = static()["stops"].get(stop_id, {"lat": 28.06, "lng": -82.41})
    return {"id": vehicle_id, "label": label, "seq": seq, "stop_id": stop_id, "trip_id": trip_id,
            "route_id": route_id, "lat": s["lat"] if lat is None else lat,
            "lng": s["lng"] if lng is None else lng, "timestamp": timestamp, "status": status, "omit": set(omit)}


def make_feed(*vehicles, header=True):
    feed = gtfs_realtime_pb2.FeedMessage()
    if header:
        feed.header.gtfs_realtime_version = "2.0"
        feed.header.timestamp = NOW
    for i, v in enumerate(vehicles):
        e = feed.entity.add()
        e.id = str(i)
        vp = e.vehicle
        vp.vehicle.id = v["id"]
        vp.vehicle.label = v["label"]
        if "trip" not in v["omit"]:
            if "route_id" not in v["omit"]:
                vp.trip.route_id = v["route_id"]
            if "trip_id" not in v["omit"]:
                vp.trip.trip_id = v["trip_id"]
        if "position" not in v["omit"]:
            vp.position.latitude, vp.position.longitude = v["lat"], v["lng"]
        if "timestamp" not in v["omit"]:
            vp.timestamp = v["timestamp"]
        if "stop_id" not in v["omit"] and v["stop_id"]:
            vp.stop_id = v["stop_id"]
        if "seq" not in v["omit"] and v["seq"] is not None:
            vp.current_stop_sequence = v["seq"]
        if v["status"] is not None:
            vp.current_status = v["status"]
    return feed.SerializePartialToString()  # partial: allows a header-less (invalid) feed


def feed_response(body, status=200):
    response = mock.Mock()
    response.content = body
    response.raise_for_status.return_value = None
    if status >= 400:
        response.raise_for_status.side_effect = requests.HTTPError(str(status))
    return response


def bus_at(stop_id, **overrides):
    """A Passio bus (as returned by passio_client) standing near a stop."""
    s = stop(stop_id)
    bus = {"id": 9796, "name": "1124", "route": "Red", "lat": s["lat"], "lng": s["lng"], "outdatedGps": False}
    bus.update(overrides)
    return bus


class NextStopTestBase(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch("next_stop.requests.get")
        self.get = patcher.start()
        self.addCleanup(patcher.stop)
        log_patcher = mock.patch("next_stop.logger")
        self.log = log_patcher.start()
        self.addCleanup(log_patcher.stop)

    def run_feed(self, buses, *vehicles, **feed_kwargs):
        self.get.return_value = feed_response(make_feed(*vehicles, **feed_kwargs))
        return next_stop.add_next_stops(buses, now=NOW)

    def assertUnavailable(self, bus):
        self.assertIsNone(bus["nextStop"])
        self.assertIsNone(bus["currentStop"])
        self.assertIsNone(bus["direction"])


class TestDatasetConsistency(unittest.TestCase):
    """The stop database must match the official GTFS before any stop is shown."""

    def test_stops_json_matches_official_stops_txt(self):
        with open(next_stop.GTFS_DIR / "stops.txt", encoding="utf-8-sig") as f:
            official = {r["stop_id"]: r for r in csv.DictReader(f)}
        ours = {s["id"]: s for s in json.loads(next_stop.STOPS_PATH.read_text())}
        self.assertEqual(set(ours), set(official))
        for stop_id, s in ours.items():
            self.assertAlmostEqual(s["lat"], float(official[stop_id]["stop_lat"]), places=7)
            self.assertAlmostEqual(s["lng"], float(official[stop_id]["stop_lon"]), places=7)
            self.assertTrue(official[stop_id]["stop_name"].endswith(s["name"]), stop_id)

    def test_every_official_trip_pattern_resolves(self):
        with open(next_stop.GTFS_DIR / "stop_times.txt", encoding="utf-8-sig") as f:
            trip_ids = {r["trip_id"] for r in csv.DictReader(f)}
        self.assertEqual(set(static()["trips"]), trip_ids)
        for trip_id, pattern in static()["trips"].items():
            for stop_id in pattern["stops"].values():
                self.assertIn(stop_id, static()["stops"], trip_id)

    def test_known_red_loop(self):
        red = static()["trips"][RED_TRIP]["stops"]
        self.assertEqual(len(red), 35)
        self.assertEqual(stop(red[1])["name"], "Marshall Student Center")
        self.assertEqual(red[1], red[35])
        self.assertEqual(red[2], "70726")
        self.assertEqual(stop("70726")["name"], "Post Office")

    def test_route_names_map_to_gtfs_route_ids(self):
        by_name = static()["route_ids_by_name"]
        for name, route_id in {"Red": "3095", "Blue": "3093", "Green": "3092", "Purple": "3094",
                               "Brown": "3099", "Plum": "3627", "Orange": "8096"}.items():
            self.assertIn(route_id, by_name.get(name, set()), name)


class TestApproachingStop(NextStopTestBase):
    def test_exact_id_match_gives_next_stop_with_official_name_and_coordinates(self):
        [bus] = self.run_feed([bus_at("70748")], make_vehicle(seq=2, lat=stop("70748")["lat"], lng=stop("70748")["lng"]))
        self.assertEqual(bus["nextStop"], {"id": "70726", "name": "Post Office",
                                           "lat": stop("70726")["lat"], "lng": stop("70726")["lng"]})
        self.assertIsNone(bus["currentStop"])
        self.assertEqual(bus["direction"], {"towardStopId": "70748", "toward": "Marshall Student Center",
                                          "loop": True, "stopSequence": 2, "stopsInTrip": 35})

    def test_unreported_status_is_treated_as_in_transit_to(self):
        [bus] = self.run_feed([bus_at(red_stop_id(10))], make_vehicle(seq=10))
        self.assertEqual(bus["nextStop"]["id"], red_stop_id(10))

    def test_explicit_incoming_at_and_in_transit_to(self):
        for status in (Status.INCOMING_AT, Status.IN_TRANSIT_TO):
            with self.subTest(status=status):
                [bus] = self.run_feed([bus_at(red_stop_id(5))], make_vehicle(seq=5, status=status))
                self.assertEqual(bus["nextStop"]["id"], red_stop_id(5))
                self.assertIsNone(bus["currentStop"])

    def test_multiple_buses_on_one_route_are_independent(self):
        buses = [bus_at(red_stop_id(4)), bus_at(red_stop_id(20), id=21338, name="2620")]
        self.run_feed(buses, make_vehicle(seq=4), make_vehicle("21338", seq=20, label="2620"))
        self.assertEqual(buses[0]["nextStop"]["id"], red_stop_id(4))
        self.assertEqual(buses[1]["nextStop"]["id"], red_stop_id(20))
        self.assertEqual((buses[0]["direction"]["stopSequence"], buses[1]["direction"]["stopSequence"]), (4, 20))

    def test_bus_advances_to_following_stop(self):
        bus = bus_at(red_stop_id(6))
        self.run_feed([bus], make_vehicle(seq=6))
        self.assertEqual(bus["nextStop"]["id"], red_stop_id(6))
        bus.update(lat=stop(red_stop_id(7))["lat"], lng=stop(red_stop_id(7))["lng"])  # Passio moves too
        self.run_feed([bus], make_vehicle(seq=7))
        self.assertEqual(bus["nextStop"]["id"], red_stop_id(7))
        self.assertEqual(bus["direction"]["stopSequence"], 7)

    def test_loop_wraps_from_final_stop_to_second_stop(self):
        bus = bus_at("70748")
        self.run_feed([bus], make_vehicle(seq=35))
        self.assertEqual((bus["nextStop"]["name"], bus["direction"]["stopSequence"]), ("Marshall Student Center", 35))
        self.run_feed([bus], make_vehicle(seq=2))
        self.assertEqual((bus["nextStop"]["name"], bus["direction"]["stopSequence"]), ("Post Office", 2))


class TestStoppedAtStop(NextStopTestBase):
    def test_stopped_at_reports_current_stop_and_official_following_stop(self):
        [bus] = self.run_feed([bus_at("70726")], make_vehicle(seq=2, status=Status.STOPPED_AT))
        self.assertEqual(bus["currentStop"]["name"], "Post Office")
        self.assertEqual(bus["nextStop"]["id"], red_stop_id(3))
        self.assertEqual(bus["direction"]["stopSequence"], 3)

    def test_stopped_at_final_loop_stop_continues_with_second_stop(self):
        [bus] = self.run_feed([bus_at("70748")], make_vehicle(seq=35, status=Status.STOPPED_AT))
        self.assertEqual(bus["currentStop"]["name"], "Marshall Student Center")
        self.assertEqual(bus["nextStop"]["name"], "Post Office")
        self.assertEqual(bus["direction"]["stopSequence"], 2)

    def test_stopped_at_without_verified_sequence_has_no_next_stop(self):
        [bus] = self.run_feed([bus_at("70726")], make_vehicle(seq=None, stop_id="70726", status=Status.STOPPED_AT))
        self.assertEqual(bus["currentStop"]["name"], "Post Office")
        self.assertIsNone(bus["nextStop"])
        self.assertIsNone(bus["direction"])


class TestUnavailable(NextStopTestBase):
    def test_passio_outdated_gps(self):
        [bus] = self.run_feed([bus_at(red_stop_id(5), outdatedGps=True)], make_vehicle(seq=5))
        self.assertUnavailable(bus)

    def test_stale_or_future_feed_position(self):
        for ts in (NOW - next_stop.MAX_POSITION_AGE_SECONDS - 1, NOW + next_stop.MAX_FUTURE_SKEW_SECONDS + 1):
            with self.subTest(timestamp=ts):
                [bus] = self.run_feed([bus_at(red_stop_id(5))], make_vehicle(seq=5, timestamp=ts))
                self.assertUnavailable(bus)

    def test_missing_position_or_timestamp(self):
        for field in ("position", "timestamp"):
            with self.subTest(missing=field):
                [bus] = self.run_feed([bus_at(red_stop_id(5))], make_vehicle(seq=5, omit=[field]))
                self.assertUnavailable(bus)

    def test_vehicle_missing_from_feed(self):
        [bus] = self.run_feed([bus_at(red_stop_id(5))], make_vehicle("99999", seq=5))
        self.assertUnavailable(bus)

    def test_label_match_alone_is_not_enough(self):
        [bus] = self.run_feed([bus_at(red_stop_id(5))], make_vehicle("12345", label="1124", seq=5))
        self.assertUnavailable(bus)

    def test_duplicate_vehicle_ids_are_ambiguous(self):
        [bus] = self.run_feed([bus_at(red_stop_id(5))], make_vehicle(seq=5), make_vehicle(seq=6))
        self.assertUnavailable(bus)

    def test_gps_disagreement(self):
        [bus] = self.run_feed([bus_at(red_stop_id(5))], make_vehicle(seq=5, lat=stop(red_stop_id(5))["lat"] + 0.01))
        self.assertUnavailable(bus)

    def test_route_change_or_mismatch(self):
        cases = [
            ("bus now on Blue, feed still Red trip", {"route": "Blue"}, {}),
            ("feed route_id Blue, bus Red", {}, {"route_id": BLUE_ROUTE_ID}),
            ("route not in GTFS (MSC Express)", {"route": "MSC Express"}, {}),
            ("feed has no trip", {}, {"omit": ["trip"]}),
        ]
        for label, bus_changes, vehicle_changes in cases:
            with self.subTest(label):
                [bus] = self.run_feed([bus_at(red_stop_id(5), **bus_changes)], make_vehicle(seq=5, **vehicle_changes))
                self.assertUnavailable(bus)

    def test_route_change_between_requests_is_not_remembered(self):
        bus = bus_at(red_stop_id(5))
        self.run_feed([bus], make_vehicle(seq=5))
        self.assertEqual(bus["nextStop"]["id"], red_stop_id(5))
        blue_stop = static()["trips"][BLUE_TRIP]["stops"][3]
        bus_blue = bus_at(blue_stop, route="Blue")
        self.run_feed([bus_blue], make_vehicle(seq=3, trip_id=BLUE_TRIP, route_id=BLUE_ROUTE_ID, stop_id=blue_stop))
        self.assertEqual(bus_blue["nextStop"]["id"], blue_stop)
        self.assertEqual(bus_blue["direction"]["stopsInTrip"], len(static()["trips"][BLUE_TRIP]["stops"]))

    def test_stop_missing_from_database_is_not_guessed(self):
        s = stop(red_stop_id(5))
        [bus] = self.run_feed([bus_at(red_stop_id(5))],
                              make_vehicle(seq=5, stop_id="99999999", lat=s["lat"], lng=s["lng"]))
        self.assertUnavailable(bus)
        self.assertTrue(any("missing from stops.json" in str(c) for c in self.log.info.call_args_list))

    def test_no_stop_id(self):
        [bus] = self.run_feed([bus_at(red_stop_id(5))], make_vehicle(seq=5, omit=["stop_id"]))
        self.assertUnavailable(bus)

    def test_sequence_conflict_with_official_order(self):
        [bus] = self.run_feed([bus_at(red_stop_id(5))], make_vehicle(seq=5, stop_id=red_stop_id(9)))
        self.assertUnavailable(bus)


class TestIncompleteGtfs(NextStopTestBase):
    def test_unknown_trip_shows_live_stop_without_direction(self):
        [bus] = self.run_feed([bus_at("70726")], make_vehicle(seq=2, stop_id="70726", trip_id="999999"))
        self.assertEqual(bus["nextStop"]["name"], "Post Office")
        self.assertIsNone(bus["direction"])

    def test_missing_stop_sequence_shows_live_stop_without_direction(self):
        [bus] = self.run_feed([bus_at("70726")], make_vehicle(seq=None, stop_id="70726"))
        self.assertEqual(bus["nextStop"]["name"], "Post Office")
        self.assertIsNone(bus["direction"])


class TestFailuresNeverBreakBuses(NextStopTestBase):
    def test_feed_failures_leave_null_fields(self):
        failures = {
            "timeout": {"side_effect": requests.Timeout("slow")},
            "connection": {"side_effect": requests.ConnectionError("down")},
            "http 503": {"return_value": feed_response(b"", status=503)},
            "not protobuf": {"return_value": feed_response(b"\xff\x00garbage")},
            "no header": {"return_value": feed_response(make_feed(make_vehicle(), header=False))},
            "too large": {"return_value": feed_response(b"\x00" * (next_stop.MAX_FEED_BYTES + 1))},
        }
        for label, behaviour in failures.items():
            with self.subTest(label):
                self.get.reset_mock(side_effect=True, return_value=True)
                self.get.configure_mock(**behaviour)
                [bus] = next_stop.add_next_stops([bus_at("70726")], now=NOW)
                self.assertUnavailable(bus)
                self.assertEqual(bus["id"], 9796)

    def test_static_data_failure(self):
        test_bus = bus_at("70726")
        with mock.patch("next_stop.load_static", side_effect=OSError("missing file")):
            [bus] = next_stop.add_next_stops([test_bus], now=NOW)
        self.assertUnavailable(bus)

    def test_request_uses_official_feed_with_timeout(self):
        self.run_feed([bus_at("70726")], make_vehicle())
        args, kwargs = self.get.call_args
        self.assertEqual(args[0], next_stop.VEHICLE_POSITIONS_URL)
        self.assertGreater(kwargs["timeout"], 0)

    def test_no_buses_skips_feed(self):
        self.assertEqual(next_stop.add_next_stops([]), [])
        self.get.assert_not_called()


class TestBusesEndpoint(NextStopTestBase):
    def setUp(self):
        super().setUp()
        post = mock.patch("passio_client.requests.post")
        self.post = post.start()
        self.addCleanup(post.stop)
        for target in ("app.logger",):
            p = mock.patch(target)
            p.start()
            self.addCleanup(p.stop)
        clock = mock.patch("next_stop.time.time", return_value=NOW)
        clock.start()
        self.addCleanup(clock.stop)
        s = stop("70726")
        self.post.return_value = mock_response(payload(
            make_bus(busId=9796, busName="1124", route="Red", latitude=str(s["lat"]), longitude=str(s["lng"])),
            make_bus(busId=21338, busName="2620", route="Red", outdated=1),
        ))

    def get_json(self):
        response = self.client().get("/buses")
        return response.status_code, json.loads(response.get_data(as_text=True), parse_constant=lambda c: 1 / 0)

    def client(self):
        return app.test_client()

    def test_endpoint_includes_next_stop_fields(self):
        self.get.return_value = feed_response(make_feed(make_vehicle(seq=2), make_vehicle("21338", seq=20, label="2620")))
        status, body = self.get_json()
        self.assertEqual(status, 200)
        by_id = {b["id"]: b for b in body}
        self.assertEqual(by_id[9796]["nextStop"]["name"], "Post Office")
        self.assertEqual(by_id[9796]["direction"]["toward"], "Marshall Student Center")
        self.assertIsNone(by_id[21338]["nextStop"])  # Passio marks its GPS outdated
        self.assertTrue(by_id[21338]["outdatedGps"])
        for bus in body:
            for key in ("id", "lat", "lng", "route", "color", "load", "outdatedGps", "nextStop", "currentStop", "direction"):
                self.assertIn(key, bus)

    def test_feed_down_keeps_live_buses(self):
        self.get.side_effect = requests.ConnectionError("down")
        status, body = self.get_json()
        self.assertEqual(status, 200)
        self.assertEqual(len(body), 2)
        self.assertTrue(all(b["nextStop"] is None and b["direction"] is None for b in body))
        self.assertTrue(all(isinstance(b["lat"], float) for b in body))

    def test_regression_compass_heading_is_preserved(self):
        """/buses already has `heading` (compass degrees from Passio); enrichment must not overwrite it."""
        expected = float(make_bus()["calculatedCourse"])
        for label, setup in (("feed ok", lambda: setattr(self.get, "return_value", feed_response(make_feed(make_vehicle(seq=2))))),
                             ("feed down", lambda: setattr(self.get, "side_effect", requests.ConnectionError("down")))):
            with self.subTest(label):
                setup()
                _, body = self.get_json()
                for bus in body:
                    self.assertEqual(bus["heading"], expected)
                    self.assertIn("direction", bus)


class TestEnrichmentLeavesExistingFields(NextStopTestBase):
    def test_only_new_keys_are_added(self):
        original = bus_at("70726", heading=123.4, load=50.0, color="#eb1b00", name="1124")
        before = dict(original)
        self.run_feed([original], make_vehicle(seq=2))
        self.assertEqual({k: original[k] for k in before}, before)
        self.assertEqual(set(original) - set(before), {"nextStop", "currentStop", "direction"})


if __name__ == "__main__":
    unittest.main()
