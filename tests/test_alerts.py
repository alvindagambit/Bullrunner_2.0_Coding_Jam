"""Offline tests for the official USF GTFS-Realtime service-alert adapter."""
import json
import os
import sys
import unittest
from unittest import mock

from google.transit import gtfs_realtime_pb2
import requests

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import gtfs_alerts  # noqa: E402
from app import app  # noqa: E402

NOW = 1_700_000_000


def make_feed(entries=()):
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.header.gtfs_realtime_version = "2.0"
    for index, item in enumerate(entries):
        entity = feed.entity.add()
        entity.id = str(index + 1)
        alert = entity.alert
        if item.get("name"):
            alert.header_text.translation.add().text = item["name"]
        if item.get("message"):
            alert.description_text.translation.add().text = item["message"]
        if "start" in item or "end" in item:
            period = alert.active_period.add()
            if "start" in item:
                period.start = item["start"]
            if "end" in item:
                period.end = item["end"]
    return feed.SerializeToString()


def fake_response(body, status=200):
    response = mock.Mock()
    response.content = body
    response.raise_for_status.return_value = None
    if status >= 400:
        response.raise_for_status.side_effect = requests.HTTPError(str(status))
    return response


class TestServiceAlerts(unittest.TestCase):
    def setUp(self):
        self.patcher = mock.patch("gtfs_alerts.requests.get")
        self.request = self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.client = app.test_client()

    def test_active_alerts_have_id_name_and_message(self):
        self.request.return_value = fake_response(make_feed([
            {"name": "Construction delay", "message": "<b>Red</b> route delayed", "start": NOW - 60, "end": NOW + 60},
        ]))
        alerts = gtfs_alerts.get_usf_alerts(now=NOW)
        self.assertEqual(alerts, [{"id": "1", "name": "Construction delay", "message": "Red route delayed"}])

    def test_expired_alert_is_ignored(self):
        self.request.return_value = fake_response(make_feed([
            {"name": "Old advisory", "start": NOW - 120, "end": NOW - 1},
            {"name": "Current advisory", "start": NOW - 30, "end": NOW + 30},
        ]))
        alerts = gtfs_alerts.get_usf_alerts(now=NOW)
        self.assertEqual([item["name"] for item in alerts], ["Current advisory"])

    def test_future_alert_is_not_active(self):
        self.request.return_value = fake_response(make_feed([{"name": "Future", "start": NOW + 10}]))
        self.assertEqual(gtfs_alerts.get_usf_alerts(now=NOW), [])

    def test_no_time_restriction_is_active(self):
        self.request.return_value = fake_response(make_feed([{"name": "General advisory"}]))
        self.assertEqual(gtfs_alerts.get_usf_alerts(now=NOW)[0]["name"], "General advisory")

    def test_empty_feed_is_a_valid_empty_alert_list(self):
        self.request.return_value = fake_response(make_feed())
        self.assertEqual(gtfs_alerts.get_usf_alerts(now=NOW), [])

    def test_description_only_alert(self):
        self.request.return_value = fake_response(make_feed([{"message": "Accessible boarding available"}]))
        alerts = gtfs_alerts.get_usf_alerts(now=NOW)
        self.assertEqual(alerts[0]["name"], "Accessible boarding available")

    def test_request_has_timeout_and_uses_official_feed(self):
        self.request.return_value = fake_response(make_feed())
        gtfs_alerts.get_usf_alerts(now=NOW)
        args, kwargs = self.request.call_args
        self.assertEqual(args[0], gtfs_alerts.SERVICE_ALERTS_URL)
        self.assertGreater(kwargs["timeout"], 0)

    def test_api_endpoint_returns_current_alerts(self):
        self.request.return_value = fake_response(make_feed([{"name": "Service alert"}]))
        response = self.client.get("/alerts")
        self.assertEqual(response.status_code, 200)
        body = json.loads(response.get_data(as_text=True))
        self.assertEqual(body[0]["name"], "Service alert")

    def test_api_failure_is_502_not_false_no_alerts(self):
        self.request.side_effect = requests.Timeout("SECRET INTERNAL URL")
        with mock.patch("app.logger"):
            response = self.client.get("/alerts")
        self.assertEqual(response.status_code, 502)
        body = json.loads(response.get_data(as_text=True))
        self.assertIn("error", body)
        self.assertNotIn("SECRET", response.get_data(as_text=True))

    def test_http_failure_is_502(self):
        self.request.return_value = fake_response(b"", status=503)
        with mock.patch("app.logger"):
            response = self.client.get("/alerts")
        self.assertEqual(response.status_code, 502)

    def test_malformed_feed_is_502(self):
        self.request.return_value = fake_response(b"\xff")
        with mock.patch("app.logger"):
            response = self.client.get("/alerts")
        self.assertEqual(response.status_code, 502)

    def test_missing_header_is_502(self):
        self.request.return_value = fake_response(b"")
        with mock.patch("app.logger"):
            response = self.client.get("/alerts")
        self.assertEqual(response.status_code, 502)


if __name__ == "__main__":
    unittest.main()
