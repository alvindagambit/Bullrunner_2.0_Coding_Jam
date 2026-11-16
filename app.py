import logging

from flask import Flask, jsonify

from passio_client import get_usf_buses
from gtfs_alerts import get_usf_alerts
from next_stop import add_next_stops

app = Flask(__name__)
logger = logging.getLogger(__name__)

@app.route("/")
def home():
    return "<h1>Bullrunner 2.0</h1><p>Application running successfully!</p>"

@app.route("/buses")
def buses():
    try:
        live_buses = get_usf_buses()
    except Exception:
        logger.exception("Failed to fetch live buses from PassioGo")
        return jsonify({"error": "Failed to fetch live buses"}), 502
    # Optional enrichment: never raises; on failure nextStop/currentStop/heading stay null.
    return jsonify(add_next_stops(live_buses))

@app.route("/alerts")
def alerts():
    try:
        return jsonify(get_usf_alerts())
    except Exception:
        logger.exception("Failed to fetch official USF service alerts")
        return jsonify({"error": "Service alerts temporarily unavailable"}), 502


if __name__ == "__main__":
    app.run(debug=True)
