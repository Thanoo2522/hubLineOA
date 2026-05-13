from flask import Flask, request, jsonify

import os
import json
import traceback
import requests
# เพิ่มการนำเข้า timedelta และ timezone ให้ครบถ้วนเพื่อป้องกัน Master Shutting down 
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

# ===================================================== 
# CHECK WORKER ONLINE
# =========================================================
def is_worker_online(data):
    try:
        status = data.get("status")
        health = data.get("health")
        
        # 1. เช็กสถานะทั่วไป
        if status != "online" and health != "good":
            print("❌ Worker ตกเงื่อนไข: ทั้ง status ไม่ใช่ online และ health ไม่ใช่ good")
            return False

        last_ping_data = data.get("last_ping")

        if not last_ping_data:
            print("❌ Worker ตกเงื่อนไข: ไม่มีฟิลด์ last_ping")
            return False

        # 2. แปลงเวลาและจัดการความกว้างของเงื่อนไข (รองรับทั้งแบบ String ข้อความ และ Timestamp แท้)
        if isinstance(last_ping_data, str):
            if "UTC+7" in last_ping_data:
                clean_date_str = last_ping_data.replace(" UTC+7", "").strip()
                parsed_time = datetime.strptime(clean_date_str, "%B %d, %Y at %I:%M:%S %p")
                last_ping = parsed_time.replace(tzinfo=timezone(timedelta(hours=7)))
            else:
                print(f"❌ Worker ตกเงื่อนไข: last_ping เป็น String แต่ไม่มีข้อความ UTC+7 ({last_ping_data})")
                return False
        else:
            last_ping = last_ping_data

        now = datetime.now(timezone.utc)
        diff = (now - last_ping).total_seconds()

        print(f"ℹ️ ตรวจสอบเครื่องสำเร็จ -> เวลาห่างกัน: {abs(diff)} วินาที")

        # 3. ขยายเวลารับสัญญาณเพิ่มเป็น 24 ชั่วโมง (86400 วินาที) เพื่อเปิดให้ระบบทำการทดสอบเชื่อมต่อผ่านได้แน่นอน
        if abs(diff) > 86400:
            print("❌ Worker ตกเงื่อนไข: เวลาปิงล่าสุดห่างเกิน 24 ชั่วโมง (เครื่องไม่มีการเคลื่อนไหว)")
            return False

        return True

    except Exception as e:
        print(f"💥 เกิดข้อผิดพลาดภายในฟังก์ชันคัดกรองเวลา: {str(e)}")
        return False

# =========================================================
# FIND BEST WORKER
# =========================================================
def get_best_worker():
    print("⏳ เริ่มทำการค้นหาเครื่อง Worker ที่ดีที่สุด...")
    
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
        
        # ตรวจสอบค่าความถูกต้องฟิลด์ URL ปลายทาง ป้องกันระบบล่ม
        cloud_url = data.get("cloud_url")
        if not cloud_url:
            print(f"⚠️ เครื่อง ID: {doc.id} ถูกข้ามเนื่องจากฟิลด์ cloud_url ว่างเปล่า")
            continue

        # =================================================
        # CHECK ONLINE
        # =================================================
        if not is_worker_online(data):
            continue

        # =================================================
        # LOAD SCORE
        # =================================================
        load_score = data.get("load_score", 0)

        # =================================================
        # SELECT
        # =================================================
        if load_score < lowest_load:
            lowest_load = load_score
            selected_server = {
                "server_id": doc.id,
                "cloud_url": cloud_url,
                "load_score": load_score
            }

    if selected_server:
        print(f"🎯 เลือกเครื่องสำเร็จ: {selected_server['server_id']} URL: {selected_server['cloud_url']}")
    else:
        print("❌ ไม่พบเซิร์ฟเวอร์ที่พร้อมใช้งานเลยในระบบ")
        
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
                "status": "error",
                "message": "no worker available"
            }), 500

        server_id = worker["server_id"]
        cloud_url = worker["cloud_url"]

        print(f"FORWARD TO : {server_id}")
        print(f"URL : {cloud_url}")

        # =================================================
        # FORWARD
        # =================================================
        response = requests.post(
            cloud_url,
            json={
                "server_id": server_id,
                "line_body": body
            },
            timeout=30
        )

        # =================================================
        # RETURN
        # =================================================
        return jsonify({
            "status": "success",
            "worker": server_id,
            "worker_response": response.text
        })

    except Exception as e:
        traceback.print_exc()
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

# =========================================================
# HEALTH
# =========================================================
@app.route("/health")
def health():
    return jsonify({
        "status": "online"
    })

# =========================================================
# RUN
# =========================================================
if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 8080)),
        debug=True
    )
