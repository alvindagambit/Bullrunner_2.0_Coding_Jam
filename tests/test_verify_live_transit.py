"""Offline tests for the next-stop diagnostics in scripts/verify_live_transit.py.

No network: production /buses and the vehiclePositions feed are mocked.
"""
import contextlib
import importlib.util
import io
import os
import sys
import unittest
from unittest import mock

import requests

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import next_stop  # noqa: E402
from test_next_stop import (NOW, bus_at, feed_response, make_feed, make_vehicle,  # noqa: E402
                            red_stop_id)

_SCRIPT = os.path.join(os.path.dirname(__file__), "..", "scripts", "verify_live_transit.py")
_spec = importlib.util.spec_from_file_location("verify_live_transit", _SCRIPT)
vlt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vlt)


def vehicles(*specs):
    """Parse a constructed feed with the backend's own fetcher."""
    with mock.patch("next_stop.requests.get", return_value=feed_response(make_feed(*specs))):
        return next_stop.fetch_vehicle_positions()


def prod_bus(seq, **overrides):
    """A production /buses entry that came back without a next stop."""
    bus = bus_at(red_stop_id(seq), nextStop=None, currentStop=None, direction=None)
    bus.update(overrides)
    return bus


class TestDiagnose(unittest.TestCase):
    def setUp(self):
        self.static = next_stop.load_static()

    def diagnose(self, buses, before, after):
        return vlt.diagnose(buses, (before, NOW), (after, NOW + 3), self.static)

    def test_resolved_buses_are_not_reported(self):
        bus = prod_bus(5, nextStop={"id": red_stop_id(5)})
        self.assertEqual(self.diagnose([bus], vehicles(make_vehicle(seq=5)), vehicles(make_vehicle(seq=5))), [])

    def test_outdated_gps_is_confirmed_from_production_data_alone(self):
        [r] = self.diagnose([prod_bus(5, outdatedGps=True)], None, None)
        self.assertEqual((r["status"], r["category"]), (vlt.CONFIRMED, "passio gps outdated"))

    def test_missing_from_feed_on_both_sides_is_confirmed(self):
        other = make_vehicle("99999", seq=5)
        [r] = self.diagnose([prod_bus(5)], vehicles(other), vehicles(other))
        self.assertEqual((r["status"], r["category"]), (vlt.CONFIRMED, "N feed vehicles"))
        self.assertEqual(r["evidence"]["before"]["feed_vehicles_with_id"], 0)
        self.assertEqual((r["bus_id"], r["route"]), (9796, "Red"))

    def test_sequence_conflict_is_confirmed_with_feed_evidence(self):
        bad = make_vehicle(seq=5, stop_id=red_stop_id(9),
                           lat=next_stop.load_static()["stops"][red_stop_id(5)]["lat"],
                           lng=next_stop.load_static()["stops"][red_stop_id(5)]["lng"])
        [r] = self.diagnose([prod_bus(5)], vehicles(bad), vehicles(bad))
        self.assertEqual((r["status"], r["category"]), (vlt.CONFIRMED, "sequence conflict"))
        ev = r["evidence"]["after"]
        self.assertEqual((ev["stop_sequence"], ev["stop_id"], ev["official_stop_at_sequence"]),
                         (5, red_stop_id(9), red_stop_id(5)))
        self.assertEqual(ev["trip_id"], "1187361")
        self.assertEqual(ev["gps_delta_m"], 0)

    def test_route_mismatch_is_confirmed(self):
        v = make_vehicle(seq=5, route_id="3093")
        [r] = self.diagnose([prod_bus(5)], vehicles(v), vehicles(v))
        self.assertEqual((r["status"], r["category"]), (vlt.CONFIRMED, "route mismatch"))
        self.assertEqual(r["evidence"]["before"]["feed_route_id"], "3093")
        self.assertEqual(r["evidence"]["before"]["bus_route_ids"], ["3095"])

    def test_feed_changed_during_capture_is_not_captured(self):
        [r] = self.diagnose([prod_bus(5)], vehicles(make_vehicle(seq=5)), vehicles(make_vehicle("99999", seq=5)))
        self.assertEqual((r["status"], r["category"]), (vlt.NOT_CAPTURED, "feed changed during capture"))
        self.assertIn("before: 'ok'", r["detail"])

    def test_rejection_not_reproduced_is_not_captured(self):
        [r] = self.diagnose([prod_bus(5)], vehicles(make_vehicle(seq=5)), vehicles(make_vehicle(seq=5)))
        self.assertEqual((r["status"], r["category"]), (vlt.NOT_CAPTURED, "not reproduced"))

    def test_feed_unavailable_is_not_captured(self):
        [r] = self.diagnose([prod_bus(5)], None, vehicles(make_vehicle(seq=5)))
        self.assertEqual((r["status"], r["category"]), (vlt.NOT_CAPTURED, "feed snapshot unavailable"))
        self.assertEqual(r["evidence"]["before"], {"feed": "unavailable"})

    def test_reuses_backend_validation(self):
        with mock.patch.object(vlt.next_stop, "_evaluate", wraps=next_stop._evaluate) as spy:
            self.diagnose([prod_bus(5)], vehicles(make_vehicle(seq=5)), vehicles(make_vehicle(seq=5)))
        self.assertEqual(spy.call_count, 2)  # once per feed snapshot

    def test_diagnose_does_not_modify_production_records(self):
        bus = prod_bus(5)
        snapshot = dict(bus)
        self.diagnose([bus], vehicles(make_vehicle(seq=5)), vehicles(make_vehicle(seq=5)))
        self.assertEqual(bus, snapshot)


class TestCaptureAndOutput(unittest.TestCase):
    def test_capture_is_read_only_and_brackets_production(self):
        calls = []
        feed = feed_response(make_feed(make_vehicle(seq=5)))
        prod = mock.Mock(); prod.json.return_value = [prod_bus(5)]; prod.raise_for_status.return_value = None

        def fake_get(url, **kwargs):
            calls.append(url)
            return prod if url == vlt.BUS_URL else feed

        def forbidden(*args, **kwargs):
            raise AssertionError("diagnostics must be read-only (GET only)")

        with mock.patch("requests.get", side_effect=fake_get), \
                mock.patch.multiple("requests", post=forbidden, put=forbidden, patch=forbidden, delete=forbidden):
            buses, before, after = vlt.capture()
        self.assertEqual(calls, [next_stop.VEHICLE_POSITIONS_URL, vlt.BUS_URL, next_stop.VEHICLE_POSITIONS_URL])
        self.assertIsNotNone(before[0])
        self.assertIsNotNone(after[0])
        self.assertEqual(len(buses), 1)

    def test_capture_tolerates_feed_failure(self):
        prod = mock.Mock(); prod.json.return_value = []; prod.raise_for_status.return_value = None

        def fake_get(url, **kwargs):
            if url == vlt.BUS_URL:
                return prod
            raise requests.ConnectionError("down")

        with mock.patch("requests.get", side_effect=fake_get):
            _, before, after = vlt.capture()
        self.assertIsNone(before[0])
        self.assertIsNone(after[0])

    def test_diagnose_only_end_to_end_output(self):
        feed = feed_response(make_feed(make_vehicle("99999", seq=5)))
        prod = mock.Mock(); prod.raise_for_status.return_value = None
        prod.json.return_value = [prod_bus(5), prod_bus(6, id=21338, outdatedGps=True),
                                  prod_bus(7, id=1, nextStop={"id": red_stop_id(7)})]
        out = io.StringIO()
        with mock.patch("requests.get", side_effect=lambda url, **k: prod if url == vlt.BUS_URL else feed), \
                contextlib.redirect_stdout(out):
            vlt.main(["--diagnose-only"])
        text = out.getvalue()
        self.assertIn("Next-stop diagnostics: 1/3 buses resolved (2 eligible); 2 without a next stop", text)
        self.assertIn("Bus 9796 (Red): CONFIRMED: N feed vehicles", text)
        self.assertIn("Bus 21338 (Red): CONFIRMED: passio gps outdated", text)
        self.assertNotIn("WARNING", text)

    def test_systematic_warning_when_no_eligible_bus_resolves(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            vlt.print_diagnostics([prod_bus(5), prod_bus(6, id=2)], [])
        self.assertIn("WARNING: no eligible bus resolved", out.getvalue())


if __name__ == "__main__":
    unittest.main()
