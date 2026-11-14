"""Live USF vehicle positions from PassioGo.

PassioGo 0.2.2's Vehicle constructor drops the real longitude
(`self.longitude = latitude`, `self.latitude` never set), so we issue the
same request getVehicles() makes and read the raw API response instead.
The request is sent directly (rather than via passiogo.sendApiRequest) so
we can apply a timeout.
"""
import math

import passiogo
import requests

USF_SYSTEM_ID = 2343
_BUSES_URL = f"{passiogo.BASE_URL}/mapGetData.php?getBuses=2"
REQUEST_TIMEOUT_SECONDS = 5


class PassioError(Exception):
    """Upstream PassioGo request failed or returned an error."""


def _to_float(value):
    """Convert to a finite float, or None."""
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _is_truthy(value):
    """Interpret PassioGo flag values: 1, "1", True, "true", "yes"."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        text = value.strip().lower()
        if text in ("true", "yes", "y"):
            return True
        number = _to_float(text)
        return number is not None and number != 0
    return False


def _valid_coordinates(lat, lng):
    if lat is None or lng is None:
        return False
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return False
    if lat == 0 and lng == 0:  # common "no GPS fix" placeholder
        return False
    return True


def _occupancy_percent(pax_load, total_cap):
    """paxLoad / totalCap * 100, capped at 100; None if data unavailable."""
    pax = _to_float(pax_load)
    cap = _to_float(total_cap)
    if pax is None or cap is None or cap <= 0 or pax < 0:
        return None
    return round(min(pax / cap * 100, 100.0), 1)


def _fetch_raw_buses():
    body = {"s0": str(USF_SYSTEM_ID), "sA": 1}
    try:
        response = requests.post(_BUSES_URL, json=body, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError) as e:
        raise PassioError(f"PassioGo request failed: {e}") from e

    if not isinstance(data, dict):
        raise PassioError(f"Unexpected PassioGo response type: {type(data).__name__}")
    if data.get("error"):
        raise PassioError(f"PassioGo returned an error: {data['error']}")
    return data


def get_usf_buses():
    """Return in-service USF buses with validated GPS coordinates.

    Buses with stale GPS are included and flagged with outdatedGps=True.
    Raises PassioError if the upstream request fails.
    """
    raw = _fetch_raw_buses()
    entries_by_id = raw.get("buses")
    if not isinstance(entries_by_id, dict):  # PHP encodes "no buses" as []
        return []

    buses = []
    for key, entries in entries_by_id.items():
        if key == "-1" or not isinstance(entries, list) or not entries:
            continue
        v = entries[0]
        if not isinstance(v, dict):
            continue

        if _is_truthy(v.get("outOfService")):
            continue

        lat = _to_float(v.get("latitude"))
        lng = _to_float(v.get("longitude"))
        if not _valid_coordinates(lat, lng):
            continue

        buses.append({
            "id": v.get("busId"),
            "name": v.get("busName"),
            "route": v.get("route"),
            "routeId": v.get("routeId"),
            "lat": lat,
            "lng": lng,
            "latitude": lat,
            "longitude": lng,
            "load": _occupancy_percent(v.get("paxLoad"), v.get("totalCap")),
            "heading": _to_float(v.get("calculatedCourse")),
            "color": v.get("color"),
            "updated": v.get("created"),
            "outdatedGps": _is_truthy(v.get("outdated")),
        })
    return buses
