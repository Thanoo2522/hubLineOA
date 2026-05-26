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
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
LIFF_ID = os.environ.get("LIFF_ID")

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
# WORKER CHECK (UNCHANGED)
# =========================================================
def is_worker_online(data):
    try:
        if data.get("status") != "online":
            return False

        last = data.get("last_heartbeat")
        if not last:
            return False

        now = int(time.time())
        if now - int(last) > 300:
            return False

        return True

    except Exception:
        traceback.print_exc()
        return False

# =========================================================
# GET BEST WORKER (UNCHANGED)
# =========================================================
def get_best_worker():

    docs = hub_db.collection("hub_system") \
        .document("server_pool") \
        .collection("servers") \
        .stream()

    selected = None
    lowest = 999999

    for doc in docs:

        data = doc.to_dict()

        if not is_worker_online(data):
            continue

        url = data.get("cloud_url")
        if not url:
            continue

        score = float(data.get("load_score", 999999))

        if score < lowest:
            lowest = score
            selected = {
                "server_id": doc.id,
                "cloud_url": url
            }

    return selected

# =========================================================
# STATE LOCK (NEW FIX - กันเปิดซ้อน)
# =========================================================
def set_user_state(user_id, mode):
    hub_db.collection("hub_system") \
        .document("user_state") \
        .collection("users") \
        .document(user_id) \
        .set({
            "mode": mode,
            "updated_at": datetime.utcnow()
        })

def get_user_state(user_id):
    doc = hub_db.collection("hub_system") \
        .document("user_state") \
        .collection("users") \
        .document(user_id) \
        .get()

    if not doc.exists:
        return None

    return doc.to_dict()

def clear_user_state(user_id):
    hub_db.collection("hub_system") \
        .document("user_state") \
        .collection("users") \
        .document(user_id) \
        .delete()

# =========================================================
# LINE HELPERS
# =========================================================
def reply_register_message(reply_token, url):

    requests.post(
        LINE_REPLY_API,
        headers=LINE_HEADERS,
        json={
            "replyToken": reply_token,
            "messages": [{
                "type": "text",
                "text": "กรุณาลงทะเบียนก่อนใช้งาน\n\n" + url
            }]
        }
    )

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
# WEBHOOK (FIXED OPEN-SPLIT)
# =========================================================
@app.route("/webhook", methods=["POST"])
def webhook():

    try:
        body = request.get_json()

        events = body.get("events", [])

        for event in events:

            reply_token = event.get("replyToken")
            user_id = event.get("source", {}).get("userId")

            if not user_id:
                continue

            # =================================================
            # CHECK USER REGISTER
            # =================================================
            mapping_doc = hub_db.collection("hub_system") \
                .document("user_mapping") \
                .collection("users") \
                .document(user_id) \
                .get()

            # =================================================
            # NOT REGISTER → LOCK + OPEN REGISTER ONLY ONCE
            # =================================================
            if not mapping_doc.exists:

                state = get_user_state(user_id)

                # 🔥 กันเปิดซ้ำ
                if state and state.get("mode") == "register":
                    print("SKIP DUP REGISTER")
                    continue

                worker = get_best_worker()
                if not worker:
                    return jsonify({"status": "error"})

                set_user_state(user_id, "register")

                register_url = (
                    f"https://liff.line.me/{LIFF_ID}"
                    f"?worker={worker['server_id']}"
                )

                reply_register_message(reply_token, register_url)
                continue

            # =================================================
            # REGISTERED → CLEAR STATE + FORWARD TO WORKER
            # =================================================
            clear_user_state(user_id)

            data = mapping_doc.to_dict()

            worker_url = data.get("cloud_url")

            if not worker_url:
                continue

            requests.post(
                worker_url + "/main-route",
                json={"events": [event]},
                timeout=10
            )

        return jsonify({"status": "success"})

    except Exception as e:
        traceback.print_exc()
        return jsonify({"status": "error"}), 500

# =========================================================
# REGISTER USER (UNCHANGED LOGIC)
# =========================================================
@app.route("/register-user", methods=["POST"])
def register_user():

    try:
        body = request.get_json(silent=True) or {}
        user_id = body.get("user_id")

        if not user_id:
            return jsonify({"status": "error"}), 400

        worker = get_best_worker()
        if not worker:
            return jsonify({"status": "error"}), 500

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

        # 🔥 ปลด lock หลัง register สำเร็จ
        clear_user_state(user_id)

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
        return jsonify({"status": "error"}), 500

# =========================================================
# REGISTER PAGE
# =========================================================
@app.route("/register-page")
def register_page():
    return render_template("register.html", liff_id=LIFF_ID)

# =========================================================
# RUN
# =========================================================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))