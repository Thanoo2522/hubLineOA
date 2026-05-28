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
# WEBHOOK (FORWARD ONLY)
# =========================================================
@app.route("/webhook", methods=["POST"])
def webhook():

    try:
        body = request.get_json()
        events = body.get("events", [])

        for e in events:

            token = e.get("replyToken")
            user_id = e.get("source", {}).get("userId")

            if not user_id:
                continue

            mapping = hub_db.collection("hub_system") \
                .document("user_mapping") \
                .collection("users") \
                .document(user_id).get()

            if not mapping.exists:

                worker = get_best_worker()
                if not worker:
                    return jsonify({"error": "no worker"})

                url = f"https://liff.line.me/{LIFF_ID}?worker={worker['server_id']}"

                reply(token, "กรุณาลงทะเบียน\n" + url)
                continue

            data = mapping.to_dict()

            worker_url = data.get("cloud_url")

            requests.post(
                worker_url + "/main-route",
                json={"events": [e]}
            )

        return jsonify({"status": "ok"})

    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)})

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