from flask import Flask, request, jsonify, render_template

import os
import json
import traceback
import requests
import time

from datetime import datetime

import firebase_admin
from firebase_admin import credentials, firestore

# =========================================================
# FLASK
# =========================================================
app = Flask(__name__)

# =========================================================
# ENV
# =========================================================
HUB_FIREBASE_KEY = os.environ.get("HUB_FIREBASE_KEY")

WORKER_FIREBASE_KEY = os.environ.get("WORKER_FIREBASE_KEY")

LINE_CHANNEL_ACCESS_TOKEN = os.environ.get(
    "LINE_CHANNEL_ACCESS_TOKEN"
)

LIFF_ID = os.environ.get("LIFF_ID")

# =========================================================
# VALIDATE ENV
# =========================================================
if not HUB_FIREBASE_KEY:
    raise RuntimeError("Missing HUB_FIREBASE_KEY")

if not WORKER_FIREBASE_KEY:
    raise RuntimeError("Missing WORKER_FIREBASE_KEY")

if not LINE_CHANNEL_ACCESS_TOKEN:
    raise RuntimeError("Missing LINE_CHANNEL_ACCESS_TOKEN")

if not LIFF_ID:
    raise RuntimeError("Missing LIFF_ID")

# =========================================================
# FIREBASE
# =========================================================

# HUB
hub_cred = credentials.Certificate(
    json.loads(HUB_FIREBASE_KEY)
)

hub_app = firebase_admin.initialize_app(
    hub_cred,
    name="hub"
)

hub_db = firestore.client(hub_app)

# WORKER
worker_cred = credentials.Certificate(
    json.loads(WORKER_FIREBASE_KEY)
)

worker_app = firebase_admin.initialize_app(
    worker_cred,
    name="worker"
)

worker_db = firestore.client(worker_app)

# =========================================================
# LINE API
# =========================================================
LINE_REPLY_API = (
    "https://api.line.me/v2/bot/message/reply"
)

LINE_HEADERS = {

    "Authorization":
        f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",

    "Content-Type":
        "application/json"
}

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

        last_heartbeat = data.get("last_heartbeat")

        if not last_heartbeat:
            return False

        now = int(time.time())

        diff = now - int(last_heartbeat)

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

        hub_db.collection("hub_system")
        .document("server_pool")
        .collection("servers")
        .stream()
    )

    for doc in docs:

        data = doc.to_dict()

        if not is_worker_online(data):
            continue

        cloud_url = data.get("cloud_url")

        if not cloud_url:
            continue

        return {

            "server_id": doc.id,

            "cloud_url": cloud_url
        }

    return None

# =========================================================
# REPLY REGISTER MESSAGE
# =========================================================
def reply_register_message(
    reply_token,
    register_url
):

    payload = {

        "replyToken": reply_token,

        "messages": [
            {
                "type": "text",

                "text":
                    "กรุณาลงทะเบียนก่อนใช้งาน\n\n"
                    + register_url
            }
        ]
    }

    r = requests.post(

        LINE_REPLY_API,

        headers=LINE_HEADERS,

        json=payload
    )

    print("LINE STATUS:", r.status_code)
    print(r.text)

# =========================================================
# WEBHOOK
# =========================================================
@app.route("/webhook", methods=["POST"])
def webhook():

    try:

        body = request.get_json()

        print("=" * 50)
        print("WEBHOOK")
        print(json.dumps(
            body,
            indent=2,
            ensure_ascii=False
        ))
        print("=" * 50)

        events = body.get("events", [])

        worker = get_best_worker()

        if not worker:

            return jsonify({

                "status": "error",

                "message": "no worker"
            })

        cloud_url = worker["cloud_url"]

        for event in events:

            reply_token = event.get("replyToken")

            source = event.get("source", {})

            user_id = source.get("userId")

            if not user_id:
                continue

            # ====================================
            # CHECK REGISTER
            # ====================================

            check_url = (
                cloud_url +
                "/check-register"
            )

            r = requests.post(

                check_url,

                json={
                    "user_id": user_id
                },

                timeout=10
            )

            result = r.json()

            registered = result.get(
                "registered",
                False
            )

            print("REGISTERED =", registered)

            # ====================================
            # NOT REGISTER
            # ====================================

            if not registered:

                register_url = (

                    f"https://liff.line.me/{LIFF_ID}"

                    f"?worker={worker['server_id']}"
                )

                print("REGISTER URL =", register_url)

                reply_register_message(
                    reply_token,
                    register_url
                )

                continue

            # ====================================
            # FORWARD TO WORKER
            # ====================================

            worker_url = (
                cloud_url +
                "/worker-webhook"
            )

            rr = requests.post(

                worker_url,

                json={
                    "events": [event]
                },

                timeout=10
            )

            print(
                "WORKER STATUS =",
                rr.status_code
            )

            print(rr.text)

        return jsonify({
            "status": "success"
        })

    except Exception as e:

        traceback.print_exc()

        return jsonify({

            "status": "error",

            "message": str(e)

        }), 500

# =========================================================
# REGISTER USER
# =========================================================
@app.route("/register-user", methods=["POST"])
def register_user():

    try:

        body = request.get_json(
            silent=True
        ) or {}

        print("REGISTER BODY =", body)

        user_id = body.get("user_id")

        if not user_id:

            return jsonify({

                "status": "error",

                "message": "no user_id"

            }), 400

        worker_db.collection("user") \
            .document(user_id) \
            .set({

                "userId": user_id,

                "fullname":
                    body.get("name", ""),

                "phone":
                    body.get("phone", ""),

                "email":
                    body.get("email", ""),

                "register": True,

                "created_at":
                    datetime.utcnow()
            })

        return jsonify({

            "status": "success",

            "message": "ลงทะเบียนสำเร็จ"
        })

    except Exception as e:

        traceback.print_exc()

        return jsonify({

            "status": "error",

            "message": str(e)

        }), 500

# =========================================================
# REGISTER PAGE
# =========================================================
@app.route("/register-page")
def register_page():

    return render_template(

        "register.html",

        liff_id=LIFF_ID
    )

# =========================================================
# RUN
# ==================================================== 
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