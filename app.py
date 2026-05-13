from flask import Flask, request, jsonify

import os
import json
import traceback
import requests
from datetime import datetime, timezone

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
# ENV
# =========================================================
HUB_FIREBASE_SERVICE_KEY = os.environ.get(
    "HUB_FIREBASE_SERVICE_KEY"
)

if not HUB_FIREBASE_SERVICE_KEY:

    raise RuntimeError(
        "Missing HUB_FIREBASE_SERVICE_KEY"
    )

# =========================================================
# FIREBASE INIT
# =========================================================
hub_cred = credentials.Certificate(
    json.loads(HUB_FIREBASE_SERVICE_KEY)
)

firebase_admin.initialize_app(
    hub_cred
)

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
# CHECK WORKER ONLINE
# =========================================================
def is_worker_online(data):

    status = data.get("status")

    if status != "online":
        return False

    last_ping = data.get("last_ping")

    if not last_ping:
        return False

    now = datetime.now(timezone.utc)

    diff = (
        now - last_ping
    ).total_seconds()

    if diff > 90:
        return False

    return True

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

        # =================================================
        # CHECK ONLINE
        # =================================================
        if not is_worker_online(data):
            continue

        # =================================================
        # LOAD SCORE
        # =================================================
        load_score = data.get(
            "load_score", 0
        )

        # =================================================
        # SELECT
        # =================================================
        if load_score < lowest_load:

            lowest_load = load_score

            selected_server = {

                "server_id":
                    doc.id,

                "cloud_url":
                    data.get("cloud_url"),

                "load_score":
                    load_score
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

                "status":
                    "error",

                "message":
                    "no worker available"

            }), 500

        server_id = worker["server_id"]

        cloud_url = worker["cloud_url"]

        print(
            f"FORWARD TO : {server_id}"
        )

        print(
            f"URL : {cloud_url}"
        )

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

        # =================================================
        # RETURN
        # =================================================
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

        "status":
            "online"
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