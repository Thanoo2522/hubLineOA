from flask import Flask, request, jsonify

import os
import json
import traceback
import requests

import firebase_admin

from firebase_admin import (
    credentials,
    firestore
)

# =========================================================
# FLASK
# =========================================================
app = Flask(__name__)

# =========================================================
# HUB FIREBASE ENV
# =========================================================
service_account_json = os.environ.get(
    "HUB_FIREBASE_SERVICE_KEY"
)

if not service_account_json:

    raise RuntimeError(
        "Missing HUB_FIREBASE_SERVICE_KEY"
    )

# =========================================================
# FIREBASE INIT
# =========================================================
cred = credentials.Certificate(
    json.loads(service_account_json)
)

firebase_admin.initialize_app(cred)

# =========================================================
# FIRESTORE
# =========================================================
db = firestore.client()

# =========================================================
# HOME
# =========================================================
@app.route("/")
def home():

    return "HUB SWITCH RUNNING"

# =========================================================
# FIND BEST WORKER
# =========================================================
def get_best_worker():

    docs = (
        db.collection("hub_system")
          .document("server_pool")
          .collection("servers")
          .stream()
    )

    selected_server = None

    lowest_load = 999999

    for doc in docs:

        data = doc.to_dict()

        if data.get("status") != "online":
            continue

        load_score = data.get(
            "load_score", 0
        )

        if load_score < lowest_load:

            lowest_load = load_score

            selected_server = {

                "server_id":
                    data.get("server_id"),

                "cloud_url":
                    data.get("cloud_url")
            }

    return selected_server

# =========================================================
# WEBHOOK
# =========================================================
@app.route("/webhook", methods=["POST"])
def webhook():

    try:

        body = request.get_json()

        print(json.dumps(
            body,
            indent=2,
            ensure_ascii=False
        ))

        # =================================================
        # GET WORKER
        # =================================================
        worker = get_best_worker()

        if not worker:

            return jsonify({
                "status": "error",
                "message":
                    "no worker available"
            }), 500

        server_id = worker["server_id"]

        cloud_url = worker["cloud_url"]

        print("FORWARD TO :", cloud_url)

        # =================================================
        # FORWARD
        # =================================================
        response = requests.post(

            cloud_url,

            json={

                "server_id":
                    server_id,

                "line_body":
                    body
            },

            timeout=30
        )

        return jsonify({

            "status":
                "success",

            "worker":
                server_id,

            "worker_response":
                response.text
        })

    except Exception as e:

        traceback.print_exc()

        return jsonify({

            "status":
                "error",

            "message":
                str(e)
        }), 500

# =========================================================
# HEALTH
# =========================================================
@app.route("/health")
def health():

    return jsonify({
        "status": "online"
    })

# =========================================================
# RUN
# =========================================================
if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=int(
            os.environ.get("PORT", 8080)
        ),
        debug=True
    )