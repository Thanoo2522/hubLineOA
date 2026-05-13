from flask import Flask, request, jsonify

import os
import json
import traceback
import requests
from datetime import datetime, timezone, timedelta

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
FIREBASE_SERVICE_KEY = os.environ.get(
    "FIREBASE_SERVICE_KEY"
)

if not FIREBASE_SERVICE_KEY:

    raise RuntimeError(
        "Missing FIREBASE_SERVICE_KEY"
    )

# =========================================================
# FIREBASE INIT
# =========================================================
hub_cred = credentials.Certificate(
    json.loads(FIREBASE_SERVICE_KEY)
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
    try:
        # 1. ตรวจสอบสถานะจากฟิลด์ health (รองรับทั้งฟิลด์ status เผื่ออนาคตเปลี่ยน)
        status = data.get("status")
        health = data.get("health")
        
        if status != "online" and health != "good":
            return False

        last_ping_data = data.get("last_ping")

        if not last_ping_data:
            return False

        # 2. ตรวจสอบประเภทข้อมูลของ last_ping (เผื่อเป็น String หรือ Native Firestore Timestamp)
        if isinstance(last_ping_data, str):
            # รองรับฟอร์แมต String: "May 13, 2026 at 11:04:50 AM UTC+7" ที่ปรากฏในฐานข้อมูลของคุณ
            if "UTC+7" in last_ping_data:
                clean_date_str = last_ping_data.replace(" UTC+7", "").strip()
                # แปลงข้อความให้กลายเป็น datetime object (เวลาไทยภูมิภาค GMT+7)
                parsed_time = datetime.strptime(clean_date_str, "%B %d, %Y at %I:%M:%S %p")
                # ระบุ timezone ให้ถูกต้องตามฐานข้อมูลของคุณ (+7 ชั่วโมง)
                last_ping = parsed_time.replace(tzinfo=timezone(timedelta(hours=7)))
            else:
                return False
        else:
            # กรณีที่ตั้งค่าฟิลด์ใน Firestore เป็นประเภท Timestamp เรียบร้อยแล้ว
            last_ping = last_ping_data

        # 3. คำนวณหาความต่างของเวลาปัจจุบันกับเวลาปิงล่าสุดในรูปแบบ UTC เหมือนกัน
        now = datetime.now(timezone.utc)

        diff = (
            now - last_ping
        ).total_seconds()

        # ตรวจสอบค่าสัมบูรณ์หากเวลาของเซิร์ฟเวอร์ทั้งสองฝั่งไม่ตรงกันเล็กน้อย
        if abs(diff) > 90:
            return False

        return True

    except Exception as e:
        print(f"Error validating worker online status: {str(e)}")
        return False

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
