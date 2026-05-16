from flask import Flask, request, jsonify
from flask import render_template

import os
import json
import traceback
import requests
import uuid
import time
from datetime import datetime, timezone

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
REGISTER_URL = os.environ.get("REGISTER_URL")
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")

# =========================================================
# CHECK ENV
# =========================================================
if not HUB_FIREBASE_KEY:
    raise RuntimeError("Missing HUB_FIREBASE_KEY")

if not REGISTER_URL:
    raise RuntimeError("Missing REGISTER_URL")

if not LINE_CHANNEL_ACCESS_TOKEN:
    raise RuntimeError("Missing LINE_CHANNEL_ACCESS_TOKEN")

# =========================================================
# FIREBASE
# =========================================================
hub_cred = credentials.Certificate(json.loads(HUB_FIREBASE_KEY))

hub_app = firebase_admin.initialize_app(hub_cred, name="hub")
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
        status = data.get("status")

        if status != "online":
            return False

        last_heartbeat = data.get("last_heartbeat")

        if last_heartbeat:
            now = int(time.time())
            diff = now - int(last_heartbeat)
            return abs(diff) <= 300

        return False

    except Exception:
        traceback.print_exc()
        return False

# =========================================================
# GET BEST WORKER
# =========================================================
def get_best_worker():

    docs = hub_db.collection("hub_system") \
        .document("server_pool") \
        .collection("servers") \
        .stream()

    selected = None
    lowest_load = 999999

    for doc in docs:

        data = doc.to_dict()

        if not is_worker_online(data):
            continue

        cloud_url = data.get("cloud_url")
        if not cloud_url:
            continue

        load_score = data.get("load_score", 0)

        if load_score < lowest_load:
            lowest_load = load_score

            selected = {
                "server_id": doc.id,
                "cloud_url": cloud_url
            }

    return selected

# =========================================================
# GET WORKER URL (IMPORTANT FIX)
# =========================================================
@app.route("/get-worker-url/<worker_id>")
def get_worker_url(worker_id):

    try:
        doc = hub_db.collection("hub_system") \
            .document("server_pool") \
            .collection("servers") \
            .document(worker_id) \
            .get()

        if not doc.exists:
            return jsonify({"status": "error", "message": "worker not found"})

        data = doc.to_dict()

        return jsonify({
            "status": "ok",
            "register_url": f"{data['cloud_url']}/register"
        })

    except Exception as e:
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)})

# =========================================================
# REPLY REGISTER MESSAGE
# =========================================================
def reply_register_message(reply_token, register_link):

    url = "https://api.line.me/v2/bot/message/reply"

    headers = {
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }

    payload = {
        "replyToken": reply_token,
        "messages": [{
            "type": "text",
            "text": "กรุณาลงทะเบียน\n\n" + register_link
        }]
    }

    requests.post(url, headers=headers, json=payload)

# =========================================================
# WEBHOOK (NO CHANGE LOGIC)
# =========================================================
@app.route("/webhook", methods=["POST"])
def webhook():

    try:
        body = request.get_json()

        request_id = str(uuid.uuid4())

        worker = get_best_worker()

        if not worker:
            return jsonify({"status": "error", "message": "no worker"})

        cloud_url = worker["cloud_url"]

        events = body.get("events", [])

        for event in events:

            reply_token = event.get("replyToken")
            user_id = event.get("source", {}).get("userId")

            if not user_id:
                continue

            # check register
            check_url = cloud_url + "/check-register"

            res = requests.post(check_url, json={"user_id": user_id})
            result = res.json()

            if not result.get("registered", False):

                register_link = (
                    f"{REGISTER_URL}/register-page?worker={worker['server_id']}"
                )

                reply_register_message(reply_token, register_link)
                continue

            # forward worker
            requests.post(cloud_url, json={
                "request_id": request_id,
                "payload": body
            })

        return jsonify({"status": "success"})

    except Exception as e:
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)})

# =========================================================
# REGISTER PAGE
# =========================================================
@app.route("/register-page")
def register_page():
    return render_template("register.html")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)