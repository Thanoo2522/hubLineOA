from flask import Flask, request, jsonify

import os
import json
import traceback
import requests
import uuid

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
HUB_FIREBASE_KEY = os.environ.get(
    "HUB_FIREBASE_KEY"
)

if not HUB_FIREBASE_KEY:

    raise RuntimeError(
        "Missing HUB_FIREBASE_KEY"
    )

# =========================================================
# INIT HUB FIREBASE
# =========================================================
hub_cred = credentials.Certificate(
    json.loads(HUB_FIREBASE_KEY)
)

hub_app = firebase_admin.initialize_app(

    hub_cred,

    name="hub"
)

# =========================================================
# HUB FIRESTORE
# =========================================================
hub_db = firestore.client(
    hub_app
)

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

    try:

        status = data.get("status")

        if status != "online":

            return False

        last_ping = data.get("last_ping")

        if not last_ping:

            return False

        # =================================================
        # FIX TZ
        # =================================================
        if last_ping.tzinfo is None:

            last_ping = last_ping.replace(
                tzinfo=timezone.utc
            )

        now = datetime.now(timezone.utc)

        diff = (now - last_ping).total_seconds()

        print("TIME DIFF =", diff)

        if abs(diff) > 300:

            return False

        return True

    except Exception as e:

        print(str(e))

        return False

# =========================================================
# FIND BEST WORKER
# =========================================================
def get_best_worker():

    docs = (
        hub_db.collection("hub_system")
              .document("server_pool")
              .collection("servers")
              .stream()
    )

    selected_server = None

    lowest_load = 999999

    for doc in docs:

        data = doc.to_dict()

        print("================================")
        print("DOC :", doc.id)
        print(data)

        if not is_worker_online(data):

            print("WORKER OFFLINE")

            continue

        cloud_url = data.get("cloud_url")

        if not cloud_url:

            print("NO CLOUD URL")

            continue

        load_score = data.get(
            "load_score",
            0
        )

        if load_score < lowest_load:

            lowest_load = load_score

            selected_server = {

                "server_id":
                    doc.id,

                "cloud_url":
                    cloud_url,

                "load_score":
                    load_score
            }

    print("SELECTED =", selected_server)

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
        # REQUEST ID
        # =================================================
        request_id = str(uuid.uuid4())

        # =================================================
        # SAVE HUB LOG
        # =================================================
        hub_db.collection("hub_logs") \
              .document(request_id) \
              .set({

                  "request_id":
                      request_id,

                  "body":
                      body,

                  "created_at":
                      firestore.SERVER_TIMESTAMP
              })

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

        print("FORWARD TO =", cloud_url)

        # =================================================
        # FORWARD
        # =================================================
        response = requests.post(

            cloud_url,

            json={

                "request_id":
                    request_id,

                "payload":
                    body
            },

            timeout=30
        )

        # =================================================
        # UPDATE HUB LOG
        # =================================================
        hub_db.collection("hub_logs") \
              .document(request_id) \
              .update({

                  "worker":
                      server_id,

                  "worker_status":
                      response.status_code
              })

        # =================================================
        # RETURN
        # =================================================
        return jsonify({

            "status":
                "success",

            "worker":
                server_id,

            "worker_response":
                response.json()
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