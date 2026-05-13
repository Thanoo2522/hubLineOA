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
        status = data.get("status")
        health = data.get("health")
        
        # เช็กว่ามีสถานะพร้อมทำงานตัวใดตัวหนึ่งเปิดอยู่หรือไม่
        if status != "online" and health != "good":
            print("❌ Worker Offline: status ไม่ใช่ online และ health ไม่ใช่ good")
            return False

        last_ping = data.get("last_ping")

        if not last_ping:
            print("❌ Worker Offline: ไม่พบฟิลด์ last_ping ในระบบ")
            return False

        # ตรวจสอบเวลาปัจจุบันในรูปแบบ UTC 
        now = datetime.now(timezone.utc)

        # คำนวณความต่างของเวลา (Firestore Timestamp จะแปลงเป็น Python datetime อัตโนมัติ)
        try:
            # กรณีข้อมูลเป็นวัตถุ Timestamp แท้ตามขั้นตอนที่ 1
            diff = (now - last_ping).total_seconds()
        except TypeError:
            # กรณีหลงเหลือข้อมูลเก่าที่เป็น String ข้อความอยู่ ระบบจะข้ามไปก่อนเพื่อไม่ให้แอปพัง
            print("❌ Worker Offline: ฟิลด์ last_ping ยังคงเป็น String ข้อความเก่าอยู่ กรุณาเปลี่ยนเป็นประเภท Timestamp")
            return False

        print(f"ℹ️ ตรวจสอบเครื่องสำเร็จ -> เวลาปิงห่างจากปัจจุบัน: {abs(diff)} วินาที")

        # ปรับขยายเวลาเพิ่มความยืดหยุ่นให้อยู่ในเกณฑ์ 5 นาที (300 วินาที) เผื่อเครือข่ายดีเลย์
        if abs(diff) > 300:
            print("❌ Worker Offline: เครื่องไม่ได้ปิงส่งสัญญาณนานเกิน 5 นาทีแล้ว")
            return False

        return True

    except Exception as e:
        print(f"💥 ระบบตรวจสอบพังเนื่องจากข้อผิดพลาดภายใน: {str(e)}")
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
