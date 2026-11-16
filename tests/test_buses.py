"""Tests for GET /buses. Upstream PassioGo calls are mocked; no network.

Run from the repo root:  python -m unittest discover -s tests -v
"""
import json
import os
import sys
import unittest
from unittest import mock

import requests

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import passio_client  # noqa: E402
from app import app  # noqa: E402


def make_bus(**overrides):
    bus = {
        "busId": 9811,
        "busName": "1801",
        "route": "Plum",
        "routeId": "67171",
        "latitude": "28.073189800",
        "longitude": "-82.409973800",
        "calculatedCourse": "359.66674523748077",
        "outOfService": 0,
        "outdated": 0,
        "paxLoad": 10,
        "totalCap": 40,
        "color": "#8f0154",
        "created": "03:12 PM",
    }
    bus.update(overrides)
    return bus


def payload(*buses):
    return {"buses": {str(i): [b] for i, b in enumerate(buses, start=1)}}


def mock_response(data, status=200):
    resp = mock.Mock()
    resp.status_code = status
    resp.json.return_value = data
    if status >= 400:
        resp.raise_for_status.side_effect = requests.HTTPError(f"{status} error")
    else:
        resp.raise_for_status.return_value = None
    return resp


def _reject_constant(name):
    raise ValueError(f"Invalid JSON constant: {name}")


class BusesEndpointTestBase(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        patcher = mock.patch("passio_client.requests.post")
        self.mock_post = patcher.start()
        self.addCleanup(patcher.stop)
        log_patcher = mock.patch("app.logger")
        self.mock_logger = log_patcher.start()
        self.addCleanup(log_patcher.stop)
        # Keep these tests offline: the optional next-stop feed is "down", so
        # nextStop/currentStop/direction are null (covered in test_next_stop.py).
        feed_patcher = mock.patch("next_stop.requests.get", side_effect=requests.ConnectionError("offline"))
        feed_patcher.start()
        self.addCleanup(feed_patcher.stop)

    def get_buses(self, data=None, status=200):
        if data is not None:
            self.mock_post.return_value = mock_response(data, status)
        resp = self.client.get("/buses")
        # Strict JSON: NaN/Infinity would raise here.
        body = json.loads(resp.get_data(as_text=True), parse_constant=_reject_constant)
        return resp, body


class TestGpsConversion(BusesEndpointTestBase):
    def test_coordinates_are_correct_floats(self):
        resp, body = self.get_buses(payload(make_bus()))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(body), 1)
        bus = body[0]
        self.assertIsInstance(bus["lat"], float)
        self.assertIsInstance(bus["lng"], float)
        self.assertAlmostEqual(bus["lat"], 28.0731898)
        self.assertAlmostEqual(bus["lng"], -82.4099738)
        self.assertNotEqual(bus["lat"], bus["lng"])  # regression: PassioGo lat/lng bug

    def test_legacy_fields_match_contract_fields(self):
        _, body = self.get_buses(payload(make_bus()))
        bus = body[0]
        self.assertEqual(bus["latitude"], bus["lat"])
        self.assertEqual(bus["longitude"], bus["lng"])

    def test_contract_fields_present(self):
        _, body = self.get_buses(payload(make_bus()))
        for field in ("id", "lat", "lng", "route", "color", "load", "outdatedGps"):
            self.assertIn(field, body[0])

    def test_request_targets_usf_system(self):
        self.get_buses(payload(make_bus()))
        _, kwargs = self.mock_post.call_args
        self.assertEqual(kwargs["json"]["s0"], "2343")


class TestEmptyResponses(BusesEndpointTestBase):
    def test_php_empty_array_returns_empty_list(self):
        resp, body = self.get_buses({"buses": []})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(body, [])

    def test_missing_buses_key_returns_empty_list(self):
        resp, body = self.get_buses({"time": 123})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(body, [])

    def test_empty_dict_returns_empty_list(self):
        resp, body = self.get_buses({"buses": {}})
        self.assertEqual((resp.status_code, body), (200, []))

    def test_placeholder_and_malformed_entries_skipped(self):
        data = {"buses": {"-1": [make_bus()], "2": [], "3": None, "4": ["x"], "5": [make_bus()]}}
        resp, body = self.get_buses(data)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(body), 1)


class TestOutOfServiceFiltering(BusesEndpointTestBase):
    def test_out_of_service_values_excluded(self):
        for value in (1, "1", True, "true", "TRUE", "yes", 1.0):
            with self.subTest(value=value):
                resp, body = self.get_buses(payload(make_bus(outOfService=value)))
                self.assertEqual(resp.status_code, 200)
                self.assertEqual(body, [])

    def test_in_service_values_included(self):
        for value in (0, "0", False, "false", None, ""):
            with self.subTest(value=value):
                resp, body = self.get_buses(payload(make_bus(outOfService=value)))
                self.assertEqual(resp.status_code, 200)
                self.assertEqual(len(body), 1)

    def test_mixed_fleet_filters_only_out_of_service(self):
        data = payload(make_bus(busId=1), make_bus(busId=2, outOfService=1), make_bus(busId=3))
        _, body = self.get_buses(data)
        self.assertEqual([b["id"] for b in body], [1, 3])


class TestStaleGps(BusesEndpointTestBase):
    def test_outdated_bus_included_and_flagged(self):
        for value in (1, "1", True, "true"):
            with self.subTest(value=value):
                _, body = self.get_buses(payload(make_bus(outdated=value)))
                self.assertEqual(len(body), 1)
                self.assertIs(body[0]["outdatedGps"], True)

    def test_current_bus_not_flagged(self):
        for value in (0, "0", False, None):
            with self.subTest(value=value):
                _, body = self.get_buses(payload(make_bus(outdated=value)))
                self.assertIs(body[0]["outdatedGps"], False)


class TestCoordinateValidation(BusesEndpointTestBase):
    def test_invalid_coordinates_rejected(self):
        cases = [
            ("nan", "-82.4"), ("28.0", "nan"), ("inf", "-82.4"), ("28.0", "-inf"),
            (None, "-82.4"), ("28.0", None), ("", "-82.4"), ("abc", "-82.4"),
            ("91", "-82.4"), ("-91", "-82.4"), ("28.0", "181"), ("28.0", "-181"),
            ("0", "0"), (True, "-82.4"),
        ]
        for lat, lng in cases:
            with self.subTest(lat=lat, lng=lng):
                resp, body = self.get_buses(payload(make_bus(latitude=lat, longitude=lng)))
                self.assertEqual(resp.status_code, 200)
                self.assertEqual(body, [])

    def test_missing_coordinate_keys_rejected(self):
        bus = make_bus()
        del bus["latitude"]
        _, body = self.get_buses(payload(bus))
        self.assertEqual(body, [])

    def test_boundary_coordinates_accepted(self):
        _, body = self.get_buses(payload(make_bus(latitude="90", longitude="-180")))
        self.assertEqual(len(body), 1)

    def test_one_bad_bus_does_not_break_others(self):
        data = payload(make_bus(busId=1, latitude="nan"), make_bus(busId=2))
        resp, body = self.get_buses(data)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual([b["id"] for b in body], [2])


class TestOccupancy(BusesEndpointTestBase):
    def load_for(self, **fields):
        _, body = self.get_buses(payload(make_bus(**fields)))
        return body[0]["load"]

    def test_percentage_calculation(self):
        self.assertEqual(self.load_for(paxLoad=10, totalCap=40), 25.0)
        self.assertEqual(self.load_for(paxLoad="11", totalCap="40"), 27.5)
        self.assertEqual(self.load_for(paxLoad=0, totalCap=25), 0.0)
        self.assertEqual(self.load_for(paxLoad=40, totalCap=40), 100.0)
        self.assertEqual(self.load_for(paxLoad=1, totalCap=3), 33.3)

    def test_over_capacity_capped_at_100(self):
        self.assertEqual(self.load_for(paxLoad=50, totalCap=40), 100.0)

    def test_null_when_data_unavailable(self):
        cases = [
            {"paxLoad": None}, {"totalCap": None}, {"totalCap": 0}, {"totalCap": -5},
            {"paxLoad": -1}, {"paxLoad": "abc"}, {"totalCap": "nan"}, {"paxLoad": "inf"},
        ]
        for fields in cases:
            with self.subTest(**{k: repr(v) for k, v in fields.items()}):
                self.assertIsNone(self.load_for(**fields))

    def test_null_when_fields_missing(self):
        bus = make_bus()
        del bus["paxLoad"], bus["totalCap"]
        _, body = self.get_buses(payload(bus))
        self.assertIsNone(body[0]["load"])


class TestUpstreamFailures(BusesEndpointTestBase):
    def assert_clean_502(self, resp, body):
        self.assertEqual(resp.status_code, 502)
        self.assertEqual(body, {"error": "Failed to fetch live buses"})
        self.mock_logger.exception.assert_called()

    def test_timeout_is_set(self):
        self.get_buses(payload(make_bus()))
        _, kwargs = self.mock_post.call_args
        self.assertIn("timeout", kwargs)
        self.assertGreater(kwargs["timeout"], 0)

    def test_timeout_returns_clean_502(self):
        self.mock_post.side_effect = requests.Timeout("read timed out secret-host")
        self.assert_clean_502(*self.get_buses())

    def test_connection_error_returns_clean_502(self):
        self.mock_post.side_effect = requests.ConnectionError("dns failure")
        self.assert_clean_502(*self.get_buses())

    def test_http_error_returns_clean_502(self):
        self.assert_clean_502(*self.get_buses({}, status=500))

    def test_invalid_json_returns_clean_502(self):
        resp = mock_response(None)
        resp.json.side_effect = ValueError("not json")
        self.mock_post.return_value = resp
        self.assert_clean_502(*self.get_buses())

    def test_api_error_field_returns_clean_502(self):
        self.assert_clean_502(*self.get_buses({"error": "Invalid system internal-detail"}))

    def test_non_dict_response_returns_clean_502(self):
        self.assert_clean_502(*self.get_buses(["unexpected"]))

    def test_error_details_not_leaked(self):
        self.mock_post.side_effect = requests.Timeout("SECRET-INTERNAL-DETAIL")
        resp, _ = self.get_buses()
        self.assertNotIn("SECRET-INTERNAL-DETAIL", resp.get_data(as_text=True))


class TestHomepage(unittest.TestCase):
    def test_homepage_preserved(self):
        resp = app.test_client().get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Bullrunner 2.0", resp.get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
