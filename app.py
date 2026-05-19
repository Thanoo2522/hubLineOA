from flask import Flask, request, jsonify, render_template

import os
import json
import traceback
import requests
import time

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

LINE_CHANNEL_ACCESS_TOKEN = os.environ.get(
    "LINE_CHANNEL_ACCESS_TOKEN"
)

LIFF_ID = os.environ.get(
    "LIFF_ID"
)

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

hub_db = firestore.client(hub_app)

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

        cpu = float(data.get("cpu", 999))
        ram = float(data.get("ram", 999))

        if cpu > 85:
            return False

        if ram > 85:
            return False

        last_heartbeat = data.get(
            "last_heartbeat"
        )

        if not last_heartbeat:
            return False

        now = int(time.time())

        diff = now - int(last_heartbeat)

        print("HEARTBEAT DIFF =", diff)

        if diff > 300:
            return False

        return True

    except Exception:
        traceback.print_exc()
        return False

# =========================================================
# GET BEST WORKER
# =========================================================
def get_best_worker():

    docs = (
        hub_db
        .collection("hub_system")
        .document("server_pool")
        .collection("servers")
        .stream()
    )

    selected = None

    lowest_load = 999999

    for doc in docs:

        data = doc.to_dict()

        print("=" * 50)
        print("CHECK WORKER:", doc.id)
        print(data)

        if not is_worker_online(data):

            print("SKIP OFFLINE")

            continue

        cloud_url = data.get(
            "cloud_url"
        )

        if not cloud_url:
            continue

        load_score = float(
            data.get("load_score", 999999)
        )

        if load_score < lowest_load:

            lowest_load = load_score

            selected = {

                "server_id":
                    doc.id,

                "cloud_url":
                    cloud_url
            }

    print("SELECTED =", selected)

    return selected

# =========================================================
# REPLY REGISTER MESSAGE
# =========================================================
def reply_register_message(
    reply_token,
    register_url
):

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
                    (
                        "กรุณาลงทะเบียนก่อนใช้งาน\n\n"
                        f"{register_url}"
                    )
            }
        ]
    }

    r = requests.post(

        url,

        headers=headers,

        json=payload,

        timeout=10
    )

    print(r.status_code)
    print(r.text)

# =========================================================
# WEBHOOK
# =========================================================
@app.route(
    "/webhook",
    methods=["POST"]
)
def webhook():

    try:

        body = request.get_json()

        print("=" * 50)
        print("HUB WEBHOOK")
        print(json.dumps(
            body,
            indent=2,
            ensure_ascii=False
        ))
        print("=" * 50)

        events = body.get(
            "events",
            []
        )

        worker = get_best_worker()

        if not worker:

            return jsonify({

                "status":
                    "error",

                "message":
                    "no worker"
            })

        cloud_url = worker[
            "cloud_url"
        ]

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

            if not user_id:
                continue

            # =========================================
            # CHECK REGISTER
            # =========================================
            check_url = (
                cloud_url +
                "/check-register"
            )

            r = requests.post(

                check_url,

                json={

                    "user_id":
                        user_id
                },

                timeout=10
            )

            result = r.json()

            registered = result.get(
                "registered",
                False
            )

            print("REGISTER =", registered)

            # =========================================
            # NOT REGISTER
            # =========================================
            if not registered:

                register_url = (
                    f"https://liff.line.me/{LIFF_ID}"
                    f"?worker={worker['server_id']}"
                )

                reply_register_message(

                    reply_token,

                    register_url
                )

                continue

            # =========================================
            # FORWARD
            # =========================================
            worker_url = (
                cloud_url +
                "/worker-webhook"
            )

            rr = requests.post(

                worker_url,

                json={

                    "events":
                        [event]
                },

                timeout=20
            )

            print(rr.status_code)
            print(rr.text)

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
# =========================================================
# GET WORKER URL
# =========================================================
@app.route(
    "/get-worker-url/<worker_id>"
)
def get_worker_url(worker_id):

    try:

        doc = (
            hub_db
            .collection("hub_system")
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
            }), 404

        data = doc.to_dict()

        return jsonify({

            "status":
                "success",

            "cloud_url":
                data.get("cloud_url")
        })

    except Exception as e:

        traceback.print_exc()

        return jsonify({

            "status":
                "error",

            "message":
                str(e)
        }), 500       
 #=================================================
@app.route("/register-page")
def register_page():

    worker = request.args.get(
        "worker"
    )

    return render_template(

        "register.html",

        worker=worker,

        liff_id=LIFF_ID
    )
# =========================================================
# RUN
# =========================================================
if __name__ == "__main__":

    app.run(

        host="0.0.0.0",

        port=int(
            os.environ.get(
                "PORT",
                8080
            )
        )
    )