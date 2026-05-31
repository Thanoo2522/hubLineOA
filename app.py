from flask import Flask, request, jsonify, render_template
import os
import json
import traceback
import requests
import time
from datetime import datetime

import firebase_admin
from firebase_admin import credentials, firestore

app = Flask(__name__)

# =========================================================
# ENV
# =========================================================
HUB_FIREBASE_KEY = os.environ.get("HUB_FIREBASE_KEY")
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
LIFF_ID = os.environ.get("LIFF_ID")

if not HUB_FIREBASE_KEY or not LINE_CHANNEL_ACCESS_TOKEN or not LIFF_ID:
    raise RuntimeError("Missing ENV")

# =========================================================
# FIREBASE
# =========================================================
hub_cred = credentials.Certificate(json.loads(HUB_FIREBASE_KEY))
hub_app = firebase_admin.initialize_app(hub_cred, name="hub")
hub_db = firestore.client(hub_app)

# =========================================================
# LINE
# =========================================================
LINE_REPLY_API = "https://api.line.me/v2/bot/message/reply"
LINE_HEADERS = {
    "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
    "Content-Type": "application/json"
}

# =========================================================
# HOME
# =========================================================
@app.route("/")
def home():
    return "HUB RUNNING"

# =========================================================
# WORKER ONLINE CHECK
# =========================================================
def is_worker_online(data):
    try:
        if data.get("status") != "online":
            return False

        last = data.get("last_heartbeat")
        if not last:
            return False

        return (int(time.time()) - int(last)) <= 300
    except:
        return False

# =========================================================
# GET BEST WORKER
# =========================================================
def get_best_worker():

    docs = hub_db.collection("hub_system").document("server_pool").collection("servers").stream()

    best = None
    lowest = 999999

    for d in docs:
        data = d.to_dict()

        if not is_worker_online(data):
            continue

        load = float(data.get("load_score", 999999))

        if load < lowest:
            lowest = load
            best = {
                "server_id": d.id,
                "cloud_url": data.get("cloud_url")
            }

    return best

# =========================================================
# REPLY
# =========================================================
def reply(token, text):
    requests.post(
        LINE_REPLY_API,
        headers=LINE_HEADERS,
        json={
            "replyToken": token,
            "messages": [{"type": "text", "text": text}]
        }
    )

# =========================================================
# WEBHOOK
# =========================================================
@app.route("/webhook", methods=["POST"])
def webhook():

    try:

        body = request.get_json(
            silent=True
        ) or {}

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

        for e in events:

            token = e.get(
                "replyToken"
            )

            source = e.get(
                "source",
                {}
            )

            user_id = source.get(
                "userId"
            )

            if not user_id:
                continue

            print("USER =", user_id)

            # =====================================================
            # GET USER MAPPING
            # =====================================================

            mapping = hub_db.collection(
                "hub_system"
            ).document(
                "user_mapping"
            ).collection(
                "users"
            ).document(
                user_id
            ).get()

            # =====================================================
            # CREATE NEW MAPPING
            # =====================================================

            if not mapping.exists:

                print("NEW USER")

                worker = get_best_worker()

                if not worker:

                    reply(
                        token,
                        "ไม่มี worker online"
                    )

                    continue

                # SAVE TEMP MAPPING
                hub_db.collection(
                    "hub_system"
                ).document(
                    "user_mapping"
                ).collection(
                    "users"
                ).document(
                    user_id
                ).set({

                    "user_id":
                        user_id,

                    "worker_id":
                        worker["server_id"],

                    "cloud_url":
                        worker["cloud_url"],

                    "register":
                        False,

                    "created_at":
                        datetime.utcnow()
                })

                worker_url = worker[
                    "cloud_url"
                ]

                worker_id = worker[
                    "server_id"
                ]

            else:

                print("EXIST USER")

                data = mapping.to_dict()

                worker_url = data.get(
                    "cloud_url"
                )

                worker_id = data.get(
                    "worker_id"
                )

            print("WORKER =", worker_id)
            print("URL =", worker_url)

            # =====================================================
            # CHECK WORKER ONLINE
            # =====================================================

            worker_doc = hub_db.collection(
                "hub_system"
            ).document(
                "server_pool"
            ).collection(
                "servers"
            ).document(
                worker_id
            ).get()

            worker_ok = False

            if worker_doc.exists:

                worker_data = worker_doc.to_dict()

                worker_ok = is_worker_online(
                    worker_data
                )

            # =====================================================
            # FAILOVER
            # =====================================================

            if not worker_ok:

                print("WORKER DEAD")

                new_worker = get_best_worker()

                if not new_worker:

                    reply(
                        token,
                        "ไม่มี worker online"
                    )

                    continue

                # UPDATE MAPPING
                hub_db.collection(
                    "hub_system"
                ).document(
                    "user_mapping"
                ).collection(
                    "users"
                ).document(
                    user_id
                ).update({

                    "worker_id":
                        new_worker["server_id"],

                    "cloud_url":
                        new_worker["cloud_url"]
                })

                worker_url = new_worker[
                    "cloud_url"
                ]

                worker_id = new_worker[
                    "server_id"
                ]

                print("NEW WORKER =", worker_id)

            # =====================================================
            # CHECK REGISTER
            # =====================================================

            registered = False

            try:

                r = requests.post(

                    worker_url + "/check-register",

                    json={
                        "user_id": user_id
                    },

                    timeout=10
                )

                print(
                    "CHECK REGISTER STATUS =",
                    r.status_code
                )

                result = r.json()

                registered = result.get(
                    "registered",
                    False
                )

            except Exception as ex:

                print("CHECK REGISTER ERROR")

                traceback.print_exc()

                registered = False

            print("REGISTERED =", registered)

            # =====================================================
            # NOT REGISTER
            # =====================================================

            if not registered:

                register_url = (

                    f"https://liff.line.me/"
                    f"{LIFF_ID}"
                    f"?worker={worker_id}"
                )

                print(
                    "REGISTER URL =",
                    register_url
                )

                reply(

                    token,

                    "กรุณาลงทะเบียน\n\n"
                    + register_url
                )

                continue

            # =====================================================
            # FORWARD EVENT TO WORKER
            # =====================================================

            try:

                r = requests.post(

                    worker_url + "/main-route",

                    json={
                        "events": [e]
                    },

                    timeout=30
                )

                print(
                    "FORWARD STATUS =",
                    r.status_code
                )

                print(
                    "FORWARD RESPONSE =",
                    r.text
                )

            except Exception as ex:

                print("FORWARD ERROR")

                traceback.print_exc()

                reply(

                    token,

                    "worker offline กรุณาลองใหม่"
                )

        return jsonify({
            "status": "ok"
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
# REGISTER USER
# =========================================================
@app.route("/register-user", methods=["POST"])
def register_user():

    body = request.get_json()

    worker = get_best_worker()

    hub_db.collection("hub_system") \
        .document("user_mapping") \
        .collection("users") \
        .document(body["user_id"]) \
        .set({
            "user_id": body["user_id"],
            "worker_id": worker["server_id"],
            "cloud_url": worker["cloud_url"],
            "register": True,
            "created_at": datetime.utcnow()
        })

    requests.post(worker["cloud_url"] + "/register-user", json=body)

    return jsonify({"status": "ok"})

# =========================================================
# RUN
# =========================================================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))