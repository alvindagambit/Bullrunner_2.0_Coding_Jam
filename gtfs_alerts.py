"""Official USF Bull Runner GTFS-Realtime service alerts.

Source: https://passio3.com/usf/passioTransit/gtfs/realtime/serviceAlerts
A feed failure is an error, not proof that there are no advisories.
"""
from datetime import datetime, timezone
from html import unescape
import re

from google.protobuf.message import DecodeError
from google.transit import gtfs_realtime_pb2
import requests

SERVICE_ALERTS_URL = (
    "https://passio3.com/usf/passioTransit/gtfs/realtime/serviceAlerts"
)
REQUEST_TIMEOUT_SECONDS = 5
MAX_FEED_BYTES = 2_000_000


class AlertsFeedError(Exception):
    """USF's service-alert feed is unavailable or malformed."""


# Real HTML: line/paragraph breaks become newlines; every other tag is removed.
_HTML_BREAK = re.compile(r"<\s*/?\s*(?:br|p)\b[^>]*>", re.IGNORECASE)
_HTML_TAG = re.compile(r"<[^>]*>")

# USF's feed sometimes arrives with the angle brackets already stripped, leaving
# bare tag names ("br", "p", "/a", "a href tel:...") inside the text. Only
# unambiguous fragments are removed, as whole whitespace-separated tokens:
#   - "a href <target>" (link opener; the link's visible text is kept)
#   - closing tags, which always start with "/"
#   - the standalone words "br" and "p" (line/paragraph breaks)
# Ordinary words such as the article "a", times ("p.m."), phone numbers, dates
# and paths ("and/or", "08/24/2026") are left untouched.
_BARE_LINK_OPEN = re.compile(r"(?<!\S)a\s+href\s*=?\s*\S+")
_BARE_CLOSING_TAG = re.compile(
    r"(?<!\S)/(?:a|b|i|u|p|em|strong|span|div|font|li|ul|ol)(?!\S)", re.IGNORECASE
)
_BARE_BREAK = re.compile(r"(?<!\S)(?:br|/?p)(?!\S)")
_SPACE_BEFORE_PUNCTUATION = re.compile(r"\s+([.,;:!?])(?=\s|$)")


def _clean_text(value):
    """Render GTFS alert text safely as plain text, never raw HTML.

    Line breaks are kept as "\\n" (at most one blank line in a row); all other
    whitespace is collapsed.
    """
    text = unescape(value or "")
    text = _HTML_BREAK.sub("\n", text)
    text = _HTML_TAG.sub(" ", text)
    text = _BARE_LINK_OPEN.sub(" ", text)
    text = _BARE_CLOSING_TAG.sub(" ", text)
    text = _BARE_BREAK.sub("\n", text)

    lines = []
    for raw_line in text.split("\n"):
        line = _SPACE_BEFORE_PUNCTUATION.sub(r"\1", " ".join(raw_line.split()))
        if line or (lines and lines[-1]):
            lines.append(line)
    return "\n".join(lines).strip()


def _translation(message):
    translations = list(message.translation)
    if not translations:
        return ""
    # Prefer English; fall back to the first available translation.
    translation = next(
        (entry for entry in translations if entry.language.lower().startswith("en")),
        translations[0],
    )
    return _clean_text(translation.text)


def _is_current(alert, now):
    """GTFS: no active periods means no time restriction."""
    if not alert.active_period:
        return True
    for period in alert.active_period:
        start = period.start if period.HasField("start") else 0
        end = period.end if period.HasField("end") else float("inf")
        if start <= now <= end:
            return True
    return False


def get_usf_alerts(now=None):
    """Return currently active official alerts, or raise AlertsFeedError."""
    if now is None:
        now = int(datetime.now(timezone.utc).timestamp())
    try:
        response = requests.get(
            SERVICE_ALERTS_URL,
            timeout=REQUEST_TIMEOUT_SECONDS,
            headers={"Accept": "application/x-protobuf"},
        )
        response.raise_for_status()
        if len(response.content) > MAX_FEED_BYTES:
            raise AlertsFeedError("Service alert feed exceeds the permitted size")
        feed = gtfs_realtime_pb2.FeedMessage()
        feed.ParseFromString(response.content)
        if not feed.HasField("header"):
            raise AlertsFeedError("Missing GTFS-Realtime feed header")
    except (requests.RequestException, DecodeError, ValueError) as exc:
        raise AlertsFeedError("Unable to retrieve USF service alerts") from exc

    alerts = []
    for entity in feed.entity:
        if entity.is_deleted or not entity.HasField("alert"):
            continue
        alert = entity.alert
        if not _is_current(alert, now):
            continue
        name = _translation(alert.header_text)
        message = _translation(alert.description_text)
        if not name and not message:
            continue
        alerts.append({
            "id": entity.id,
            "name": name or message[:160],
            "message": message or None,
        })
    return alerts
