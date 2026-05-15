from flask import Flask, request, jsonify
from flask import render_template

import os
import json
import traceback
import requests
import uuid

from datetime import datetime, timezone

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

REGISTER_URL = os.environ.get(
    "REGISTER_URL"
)

LINE_CHANNEL_ACCESS_TOKEN = os.environ.get(
    "LINE_CHANNEL_ACCESS_TOKEN"
)

# =========================================================
# DEBUG ENV
# =========================================================
print("=" * 60)
print("REGISTER_URL =", REGISTER_URL)
print(
    "LINE TOKEN EXISTS =",
    bool(LINE_CHANNEL_ACCESS_TOKEN)
)
print("=" * 60)

# =========================================================
# CHECK ENV
# =========================================================
if not HUB_FIREBASE_KEY:
    raise RuntimeError(
        "Missing HUB_FIREBASE_KEY"
    )

if not REGISTER_URL:
    raise RuntimeError(
        "Missing REGISTER_URL"
    )

if not LINE_CHANNEL_ACCESS_TOKEN:
    raise RuntimeError(
        "Missing LINE_CHANNEL_ACCESS_TOKEN"
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

hub_db = firestore.client(
    hub_app
)

# =========================================================
# HOME
# =========================================================
@app.route("/")
def home():

    return "HUB RUNNING"

# =========================================================
# DEBUG WORKERS
# =========================================================
@app.route("/debug-workers")
def debug_workers():

    try:

        result = []

        docs = (
            hub_db.collection("hub_system")
                  .document("server_pool")
                  .collection("servers")
                  .stream()
        )

        for doc in docs:

            data = doc.to_dict()

            result.append({

                "doc_id":
                    doc.id,

                "data":
                    data
            })

        return jsonify({

            "status":
                "ok",

            "workers":
                result
        })

    except Exception as e:

        traceback.print_exc()

        return jsonify({

            "status":
                "error",

            "message":
                str(e)
        })

# =========================================================
# CHECK WORKER ONLINE
# =========================================================
def is_worker_online(data):

    try:

        print(
            "CHECK ONLINE DATA =",
            data
        )

        if data.get("status") != "online":

            print(
                "STATUS NOT ONLINE"
            )

            return False

        last_ping = data.get(
            "last_ping"
        )

        if not last_ping:

            print(
                "NO LAST PING"
            )

            return False

        if last_ping.tzinfo is None:

            last_ping = last_ping.replace(
                tzinfo=timezone.utc
            )

        now = datetime.now(
            timezone.utc
        )

        diff = (
            now - last_ping
        ).total_seconds()

        print(
            "PING DIFF =",
            diff
        )

        return abs(diff) <= 300

    except Exception as e:

        print(
            "ONLINE CHECK ERROR =",
            str(e)
        )

        return False

# =========================================================
# GET BEST WORKER
# =========================================================
def get_best_worker():

    print("=" * 60)
    print("GET BEST WORKER")
    print("=" * 60)

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

        print(
            f"CHECK WORKER => {doc.id}"
        )

        print(
            "WORKER DATA =",
            data
        )

        if not is_worker_online(data):

            print(
                f"{doc.id} OFFLINE"
            )

            continue

        cloud_url = data.get(
            "cloud_url"
        )

        if not cloud_url:

            print(
                f"{doc.id} NO URL"
            )

            continue

        load_score = data.get(
            "load_score",
            0
        )

        print(
            f"{doc.id} load={load_score}"
        )

        if load_score < lowest_load:

            lowest_load = load_score

            selected = {

                "server_id":
                    doc.id,

                "cloud_url":
                    cloud_url
            }

    print(
        "SELECTED WORKER =",
        selected
    )

    print("=" * 60)

    return selected

# =========================================================
# GET WORKER URL
# =========================================================
@app.route(
    "/get-worker-url/<worker_id>"
)
def get_worker_url(worker_id):

    try:

        print(
            "GET WORKER URL =",
            worker_id
        )

        doc = (
            hub_db.collection("hub_system")
                  .document("server_pool")
                  .collection("servers")
                  .document(worker_id)
                  .get()
        )

        if not doc.exists:

            print(
                "WORKER NOT FOUND"
            )

            return jsonify({

                "status":
                    "error",

                "message":
                    "worker not found"
            })

        data = doc.to_dict()

        print(
            "WORKER DOC =",
            data
        )

        cloud_url = data.get(
            "cloud_url"
        )

        register_url = cloud_url.replace(

            "/worker-webhook",
            "/register"
        )

        print(
            "REGISTER URL =",
            register_url
        )

        return jsonify({

            "status":
                "ok",

            "register_url":
                register_url
        })

    except Exception as e:

        traceback.print_exc()

        return jsonify({

            "status":
                "error",

            "message":
                str(e)
        })

# =========================================================
# REPLY REGISTER MESSAGE
# =========================================================
def reply_register_message(

    reply_token,
    register_link
):

    try:

        print("=" * 60)
        print("SEND LINE REPLY")
        print("=" * 60)

        print(
            "REGISTER LINK =",
            register_link
        )

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
                            "กดลิงก์ด้านล่าง\n\n"
                            f"{register_link}"
                        )
                }
            ]
        }

        print(
            "LINE PAYLOAD =",
            json.dumps(
                payload,
                indent=2,
                ensure_ascii=False
            )
        )

        r = requests.post(

            url,

            headers=headers,

            json=payload,

            timeout=10
        )

        print(
            "LINE STATUS =",
            r.status_code
        )

        print(
            "LINE RESPONSE =",
            r.text
        )

        print("=" * 60)

    except Exception as e:

        print(
            "LINE REPLY ERROR =",
            str(e)
        )

        traceback.print_exc()

# =========================================================
# WEBHOOK
# =========================================================
@app.route(
    "/webhook",
    methods=["POST"]
)
def webhook():

    try:

        print("=" * 60)
        print("WEBHOOK START")
        print("=" * 60)

        body = request.get_json()

        print(json.dumps(

            body,

            indent=2,

            ensure_ascii=False
        ))

        request_id = str(
            uuid.uuid4()
        )

        print(
            "REQUEST ID =",
            request_id
        )

        worker = get_best_worker()

        if not worker:

            print(
                "NO WORKER FOUND"
            )

            return jsonify({

                "status":
                    "error",

                "message":
                    "no worker"
            })

        cloud_url = worker[
            "cloud_url"
        ]

        print(
            "SELECT CLOUD URL =",
            cloud_url
        )

        events = body.get(
            "events",
            []
        )

        print(
            "EVENT COUNT =",
            len(events)
        )

        for event in events:

            print("=" * 60)
            print("PROCESS EVENT")
            print("=" * 60)

            print(
                json.dumps(
                    event,
                    indent=2,
                    ensure_ascii=False
                )
            )

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

            print(
                "USER ID =",
                user_id
            )

            if not user_id:

                print(
                    "NO USER ID"
                )

                continue

            # =================================================
            # CHECK REGISTER
            # =================================================
            check_url = cloud_url.replace(

                "/worker-webhook",
                "/check-register"
            )

            print(
                "CHECK URL =",
                check_url
            )

            response = requests.post(

                check_url,

                json={

                    "user_id":
                        user_id
                },

                timeout=10
            )

            print(
                "CHECK STATUS =",
                response.status_code
            )

            print(
                "CHECK TEXT =",
                response.text
            )

            result = response.json()

            is_registered = result.get(
                "registered",
                False
            )

            print(
                "REGISTERED =",
                is_registered
            )

            # =================================================
            # NOT REGISTER
            # =================================================
            if not is_registered:

                register_link = (

                    f"{REGISTER_URL}"
                    f"/register-page"
                    f"?worker={worker['server_id']}"
                )

                print(
                    "REGISTER LINK =",
                    register_link
                )

                reply_register_message(

                    reply_token,

                    register_link
                )

                continue

            # =================================================
            # REGISTERED
            # =================================================
            print(
                "FORWARD TO WORKER"
            )

            worker_response = requests.post(

                cloud_url,

                json={

                    "request_id":
                        request_id,

                    "payload":
                        body
                },

                timeout=10
            )

            print(
                "WORKER STATUS =",
                worker_response.status_code
            )

            print(
                "WORKER TEXT =",
                worker_response.text
            )

        print("=" * 60)
        print("WEBHOOK END")
        print("=" * 60)

        return jsonify({

            "status":
                "success"
        })

    except Exception as e:

        print(
            "WEBHOOK ERROR =",
            str(e)
        )

        traceback.print_exc()

        return jsonify({

            "status":
                "error",

            "message":
                str(e)
        }), 500

# =========================================================
# REGISTER PAGE
# =========================================================
@app.route("/register-page")
def register_page():

    print(
        "OPEN REGISTER PAGE"
    )

    return render_template(
        "register.html"
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