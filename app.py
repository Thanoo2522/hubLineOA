from flask import Flask, request, jsonify, render_template

import os
import json
import traceback
import requests
import time

from datetime import datetime

import firebase_admin
from firebase_admin import credentials, firestore
import base64

# =========================================================
# FLASK
# =========================================================
app = Flask(__name__)

# =========================================================
# ENV
# =========================================================
HUB_FIREBASE_KEY = os.environ.get("HUB_FIREBASE_KEY")
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
LIFF_ID = os.environ.get("LIFF_ID")

# =========================================================
# VALIDATE ENV
# =========================================================
if not HUB_FIREBASE_KEY:
    raise RuntimeError("Missing HUB_FIREBASE_KEY")

if not LINE_CHANNEL_ACCESS_TOKEN:
    raise RuntimeError("Missing LINE_CHANNEL_ACCESS_TOKEN")

if not LIFF_ID:
    raise RuntimeError("Missing LIFF_ID")

# =========================================================
# FIREBASE
# =========================================================
hub_cred = credentials.Certificate(json.loads(HUB_FIREBASE_KEY))

hub_app = firebase_admin.initialize_app(
    hub_cred,
    name="hub"
)

hub_db = firestore.client(hub_app)

# =========================================================
# LINE API
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
# CHECK WORKER ONLINE (UNCHANGED)
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
# GET BEST WORKER (UNCHANGED)
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

        cloud_url = data.get("cloud_url")
        if not cloud_url:
            continue

        load_score = float(data.get("load_score", 999999))

        if load_score < lowest_load:

            lowest_load = load_score

            selected = {
                "server_id": doc.id,
                "cloud_url": cloud_url
            }

    print("SELECTED =", selected)
    return selected

# =========================================================
# REPLY REGISTER MESSAGE (UNCHANGED)
# =========================================================
def reply_register_message(reply_token, register_url):

    payload = {
        "replyToken": reply_token,
        "messages": [{
            "type": "text",
            "text": "กรุณาลงทะเบียนก่อนใช้งาน\n\n" + register_url
        }]
    }

    requests.post(
        LINE_REPLY_API,
        headers=LINE_HEADERS,
        json=payload
    )

# =========================================================
# REPLY MESSAGE (UNCHANGED)
# =========================================================
def reply_message(reply_token, text):

    try:
        requests.post(
            LINE_REPLY_API,
            headers=LINE_HEADERS,
            json={
                "replyToken": reply_token,
                "messages": [{
                    "type": "text",
                    "text": text
                }]
            },
            timeout=10
        )
    except Exception as e:
        print("reply error:", e)

# =========================================================
# WEBHOOK (UNCHANGED LOGIC)
# =========================================================
@app.route("/webhook", methods=["POST"])
def webhook():

    try:
        body = request.get_json()

        print("=" * 50)
        print("WEBHOOK")
        print(json.dumps(body, indent=2, ensure_ascii=False))
        print("=" * 50)

        events = body.get("events", [])

        for event in events:

            reply_token = event.get("replyToken")

            source = event.get("source", {})
            user_id = source.get("userId")

            if not user_id:
                continue

            # ================================
            # USER CHECK
            # ================================
            mapping_doc = (
                hub_db.collection("hub_system")
                .document("user_mapping")
                .collection("users")
                .document(user_id)
                .get()
            )

            # ================================
            # NOT REGISTER
            # ================================
            if not mapping_doc.exists:

                worker = get_best_worker()

                if not worker:
                    return jsonify({"status": "error", "message": "no worker"})

                register_url = (
                    f"https://liff.line.me/{LIFF_ID}"
                    f"?worker={worker['server_id']}"
                )

                reply_register_message(reply_token, register_url)
                continue

            # ================================
            # FORWARD TO WORKER
            # ================================
            mapping_data = mapping_doc.to_dict()

            worker_url = mapping_data.get("cloud_url")
            worker_id = mapping_data.get("worker_id")

            if not worker_url:
                continue

            rr = requests.post(
                worker_url + "/main-route",
                json={"events": [event]},
                timeout=10
            )

            print("WORKER STATUS =", rr.status_code)

        return jsonify({"status": "success"})

    except Exception as e:
        traceback.print_exc()

        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


# =========================================================
# REGISTER USER (UNCHANGED LOGIC)
# =========================================================
@app.route("/register-user", methods=["POST"])
def register_user():

    try:
        body = request.get_json(silent=True) or {}

        user_id = body.get("user_id")

        if not user_id:
            return jsonify({"status": "error", "message": "no user_id"}), 400

        worker = get_best_worker()

        if not worker:
            return jsonify({"status": "error", "message": "no worker"}), 500

        hub_db.collection("hub_system") \
            .document("user_mapping") \
            .collection("users") \
            .document(user_id) \
            .set({
                "user_id": user_id,
                "fullname": body.get("name", ""),
                "phone": body.get("phone", ""),
                "email": body.get("email", ""),
                "worker_id": worker["server_id"],
                "cloud_url": worker["cloud_url"],
                "register": True,
                "created_at": datetime.utcnow()
            })

        # forward to worker
        requests.post(
            worker["cloud_url"] + "/register-user",
            json=body,
            timeout=10
        )

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
# REGISTER PAGE (UNCHANGED)
# =========================================================
@app.route("/register-page")
def register_page():

    return render_template(
        "register.html",
        liff_id=LIFF_ID
    )

# =========================================================
# RUN
# =========================================================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))