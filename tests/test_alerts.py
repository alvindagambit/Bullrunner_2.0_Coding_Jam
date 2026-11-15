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

    # Verbatim description_text of alert 3 from USF's live serviceAlerts feed
    # (2026-11-15). The feed had already stripped "<" and ">", leaving bare tags.
    MALFORMED_HOURS_ALERT = (
        "Monday - Thursday 7:00 a.m. - midnight br - Brown, Green, Orange, Purple, Red br "
        "- Blue: 7:00 a.m.-9:30 p.m. br br Friday 7:00 a.m. - 6:00 p.m. br - All routes br br "
        "Saturday - Sunday 11:00 a.m. - 6:00 p.m. br - Brown, Orange, Plum, and Red br br "
        "USF Holiday Closures br - November 11 br - November 26, 27 br br p For Bull Runner "
        "service information, call a href tel:8139746902 813-974-6902 /a or visit a href "
        "https://www.usf.edu/bullrunner/ usf.edu/BullRunner /a . /p"
    )

    def test_regression_bracketless_html_fragments_removed(self):
        self.assertEqual(
            gtfs_alerts._clean_text(self.MALFORMED_HOURS_ALERT),
            "Monday - Thursday 7:00 a.m. - midnight\n"
            "- Brown, Green, Orange, Purple, Red\n"
            "- Blue: 7:00 a.m.-9:30 p.m.\n"
            "\n"
            "Friday 7:00 a.m. - 6:00 p.m.\n"
            "- All routes\n"
            "\n"
            "Saturday - Sunday 11:00 a.m. - 6:00 p.m.\n"
            "- Brown, Orange, Plum, and Red\n"
            "\n"
            "USF Holiday Closures\n"
            "- November 11\n"
            "- November 26, 27\n"
            "\n"
            "For Bull Runner service information, call 813-974-6902 or visit usf.edu/BullRunner.",
        )

    def test_regression_malformed_alert_through_endpoint(self):
        self.request.return_value = fake_response(make_feed([
            {"name": "Fall 2026 Hours of Operation: 08/24/2026 thru 12/13/2026",
             "message": self.MALFORMED_HOURS_ALERT},
        ]))
        body = json.loads(self.client.get("/alerts").get_data(as_text=True))
        self.assertEqual(body[0]["name"], "Fall 2026 Hours of Operation: 08/24/2026 thru 12/13/2026")
        for fragment in (" br", "/a", "/p", "href", "tel:"):
            self.assertNotIn(fragment, body[0]["message"])
        self.assertIn("call 813-974-6902 or visit usf.edu/BullRunner.", body[0]["message"])

    def test_legitimate_text_is_preserved(self):
        cases = [
            # Verbatim live alerts 1, 2 and 4 (no markup): must be unchanged.
            "Passengers who use adaptive equipment can contact the USF Bull Runner to request an "
            "accessible space on a specific bus route. To do so, please call (813) 974-6902. "
            "It's recommended to make this call 20 to 30 minutes before you wish to board. "
            "We ll ensure a space is reserved for you",
            "Due to construction activities on Sycamore Drive, as well as off campus Club Drive, "
            "expect minor delays on the Orange and Red routes. All stops remain open. "
            "Please call 813-974-6902 for more info.",
            "Weekdays, 2-3 p.m.: Expect up to a 10-minute delay due to driver shift changes.",
            # Words and tokens that resemble tag names but are real content.
            "Board at stop A or B and/or transfer at a stop near Building P; route 24/7 on 08/24/2026.",
            "Call 813.974.6902 ext. 5, visit usf.edu/bullrunner or email a@usf.edu.",
            # Addresses, times, dates and abbreviations.
            "Stops moved to 4202 E. Fowler Ave, Tampa, FL 33620 (Bldg. ALN 147).",
            "Use the stop at 12901 Bruce B. Downs Blvd. near Lot 43; Suite 100/B is closed.",
            "Detour via USF Pine Dr & Leroy Collins Blvd from 8:00 a.m. to 5:30 p.m. on 11/16/2026.",
            "Br. Smith and P. Jones will assist riders at Lot P; see usf.edu/bullrunner/alerts?id=5&p=2.",
        ]
        for text in cases:
            with self.subTest(text=text[:40]):
                self.assertEqual(gtfs_alerts._clean_text(text), text)

    def test_real_html_breaks_and_tags(self):
        self.assertEqual(
            gtfs_alerts._clean_text("<b>Monday</b><br>Red<br/><br />Blue<p>Call <a href='tel:1'>813-974-6902</a>.</p>"),
            "Monday\nRed\n\nBlue\nCall 813-974-6902.",
        )
        self.assertEqual(gtfs_alerts._clean_text("Tom &amp; Jerry &lt;b&gt;x&lt;/b&gt;"), "Tom & Jerry x")

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
