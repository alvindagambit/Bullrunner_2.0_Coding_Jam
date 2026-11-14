import logging

from flask import Flask, jsonify

from passio_client import get_usf_buses

app = Flask(__name__)
logger = logging.getLogger(__name__)

@app.route("/")
def home():
    return "<h1>Bullrunner 2.0</h1><p>Application running successfully!</p>"

@app.route("/buses")
def buses():
    try:
        return jsonify(get_usf_buses())
    except Exception:
        logger.exception("Failed to fetch live buses from PassioGo")
        return jsonify({"error": "Failed to fetch live buses"}), 502

if __name__ == "__main__":
    app.run(debug=True)
