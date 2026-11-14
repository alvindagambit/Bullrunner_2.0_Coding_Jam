from flask import Flask

app = Flask(__name__)

@app.route("/")
def home():
    return "<h1>Bullrunner 2.0</h1><p>Application running successfully!</p>"

if __name__ == "__main__":
    app.run(debug=True)
