from flask import Flask, request

app = Flask(__name__)

@app.route("/", methods=["GET"])
def health():
    return "OK", 200

@app.route("/callback", methods=["POST"])
def callback():
    # LINEは「200返るか」しか見てない
    return "OK", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
