from flask import Flask, request, jsonify
from flask import render_template
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

REGISTER_URL = os.environ.get(
    "REGISTER_URL"
)

LINE_CHANNEL_ACCESS_TOKEN = os.environ.get(
    "LINE_CHANNEL_ACCESS_TOKEN"
)

# =========================================================
# CHECK ENV
# =========================================================
if not HUB_FIREBASE_KEY:
    raise RuntimeError("Missing HUB_FIREBASE_KEY")

if not REGISTER_URL:
    raise RuntimeError("Missing REGISTER_URL")

# =========================================================
# FIREBASE
# =========================================================
hub_cred = credentials.Certificate(
    json.loads(HUB_FIREBASE_KEY)
)

hub_app = firebase_admin.initialize_app(
    hub_cred,
    name="hub"
)

hub_db = firestore.client(
    hub_app
)

# =========================================================
# HOME
# =========================================================
@app.route("/")
def home():

    return "HUB RUNNING"

# =========================================================
# CHECK WORKER ONLINE
# =========================================================
def is_worker_online(data):

    try:

        if data.get("status") != "online":
            return False

        last_ping = data.get("last_ping")

        if not last_ping:
            return False

        if last_ping.tzinfo is None:

            last_ping = last_ping.replace(
                tzinfo=timezone.utc
            )

        now = datetime.now(timezone.utc)

        diff = (
            now - last_ping
        ).total_seconds()

        return abs(diff) <= 300

    except:
        return False

# =========================================================
# GET BEST WORKER
# =========================================================
def get_best_worker():

    docs = (
        hub_db.collection("hub_system")
              .document("server_pool")
              .collection("servers")
              .stream()
    )

    selected = None
    lowest_load = 999999

    for doc in docs:

        data = doc.to_dict()

        if not is_worker_online(data):
            continue

        cloud_url = data.get(
            "cloud_url"
        )

        if not cloud_url:
            continue

        load_score = data.get(
            "load_score",
            0
        )

        if load_score < lowest_load:

            lowest_load = load_score

            selected = {

                "server_id":
                    doc.id,

                "cloud_url":
                    cloud_url
            }

    return selected

# =========================================================
# GET WORKER URL
# =========================================================
@app.route(
    "/get-worker-url/<worker_id>"
)
def get_worker_url(worker_id):

    try:

        doc = (
            hub_db.collection("hub_system")
                  .document("server_pool")
                  .collection("servers")
                  .document(worker_id)
                  .get()
        )

        if not doc.exists:

            return jsonify({

                "status":
                    "error",

                "message":
                    "worker not found"
            })

        data = doc.to_dict()

        cloud_url = data.get(
            "cloud_url"
        )

        register_url = cloud_url.replace(

            "/worker-webhook",
            "/register"
        )

        return jsonify({

            "status":
                "ok",

            "register_url":
                register_url
        })

    except Exception as e:

        return jsonify({

            "status":
                "error",

            "message":
                str(e)
        })

# =========================================================
# REPLY LINE
# =========================================================
def reply_line(reply_token, text):

    url = (
        "https://api.line.me/v2/bot/message/reply"
    )

    headers = {

        "Authorization":
            f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",

        "Content-Type":
            "application/json"
    }

    payload = {

        "replyToken":
            reply_token,

        "messages": [

            {
                "type":
                    "text",

                "text":
                    text
            }
        ]
    }

    requests.post(
        url,
        headers=headers,
        json=payload
    )

# =========================================================
# WEBHOOK
# =========================================================
@app.route("/webhook", methods=["POST"])
def webhook():

    try:

        body = request.get_json()

        request_id = str(uuid.uuid4())

        worker = get_best_worker()

        if not worker:

            return jsonify({

                "status":
                    "error",

                "message":
                    "no worker"
            })

        cloud_url = worker["cloud_url"]

        events = body.get(
            "events",
            []
        )

        for event in events:

            reply_token = event.get(
                "replyToken"
            )

            source = event.get(
                "source",
                {}
            )

            user_id = source.get(
                "userId"
            )

            # =============================================
            # CHECK REGISTER
            # =============================================
            check_url = cloud_url.replace(

                "/worker-webhook",
                "/check-register"
            )

            response = requests.post(

                check_url,

                json={

                    "user_id":
                        user_id
                }
            )

            result = response.json()

            is_registered = result.get(
                "registered",
                False
            )

            # =============================================
            # NOT REGISTER
            # =============================================
            if not is_registered:

                register_link = (

                    f"{REGISTER_URL}"
                    f"?worker={worker['server_id']}"
                )

                reply_line(

                    reply_token,

                    (
                        "กรุณาลงทะเบียนก่อนใช้งาน\n\n"
                        f"{register_link}"
                    )
                )

                continue

            # =============================================
            # REGISTERED
            # =============================================
            requests.post(

                cloud_url,

                json={

                    "request_id":
                        request_id,

                    "payload":
                        body
                }
            )

        return jsonify({

            "status":
                "success"
        })

    except Exception as e:

        traceback.print_exc()

        return jsonify({

            "status":
                "error",

            "message":
                str(e)
        }), 500
# =======================================================
# REGISTER PAGE
# =========================================================
@app.route("/register-page")
def register_page():

    return render_template(
        "register.html"
    )
# =========================================================
# RUN
# =========================================================
if __name__ == "__main__":

    app.run(

        host="0.0.0.0",

        port=int(
            os.environ.get("PORT", 8080)
        )
    )