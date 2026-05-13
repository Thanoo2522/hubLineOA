from flask import Flask, request, jsonify, Response, stream_with_context, render_template

import uuid
import os
import json
import io
import traceback
import requests
import time
import urllib.parse

from io import BytesIO
from datetime import datetime, timedelta

import firebase_admin

from firebase_admin import (
    credentials,
    storage,
    db as rtdb,
    firestore,
    messaging
)

from werkzeug.security import (
    generate_password_hash,
    check_password_hash
)

# =========================================================
# Flask
# =========================================================
app = Flask(__name__)

# =========================================================
# Firebase Config
# =========================================================
RTD_URL1 = "https://baselineoa-default-rtdb.asia-southeast1.firebasedatabase.app/"

BUCKET_NAME = "baselineoa.firebasestorage.app"

# =========================================================
# ENV
# =========================================================
service_account_json = os.environ.get("FIREBASE_SERVICE_KEY")

LINE_CHANNEL_ACCESS_TOKEN = os.environ.get(
    "LINE_CHANNEL_ACCESS_TOKEN"
)

if not service_account_json:
    raise RuntimeError("Missing FIREBASE_SERVICE_KEY")

if not LINE_CHANNEL_ACCESS_TOKEN:
    raise RuntimeError("Missing LINE_CHANNEL_ACCESS_TOKEN")

# =========================================================
# Firebase Credential
# =========================================================
cred = credentials.Certificate(
    json.loads(service_account_json)
)

# =========================================================
# Firebase Initialize
# =========================================================
firebase_admin.initialize_app(
    cred,
    {
        "storageBucket": BUCKET_NAME,
        "databaseURL": RTD_URL1
    }
)

# =========================================================
# Firebase Clients
# =========================================================
db = firestore.client()

rtdb_ref = rtdb.reference("/")

bucket = storage.bucket()

# =========================================================
# HOME
# =========================================================
@app.route("/")
def home():

    return "HUB SYSTEM RUNNING"

# =========================================================
# CREATE SERVER
# hub_system/server_pool/{server_id}
# =========================================================
@app.route("/create-server", methods=["POST"])
def create_server():

    try:

        data = request.get_json()

        server_id = data.get("server_id")
        cloud_url = data.get("cloud_url")

        if not server_id or not cloud_url:

            return jsonify({
                "status": "error",
                "message": "missing data"
            }), 400

        doc_ref = (
            db.collection("hub_system")
              .document("server_pool")
              .collection("servers")
              .document(server_id)
        )

        doc_ref.set({

            "server_id": server_id,

            "cloud_url": cloud_url,

            "status": "online",

            "health": "good",

            "cpu": 0,
            "ram": 0,

            "requests_per_sec": 0,

            "response_ms": 0,

            "active_users": 0,

            "load_score": 0,

            "worker_type": "normal",

            "created_at": firestore.SERVER_TIMESTAMP,

            "last_ping": firestore.SERVER_TIMESTAMP
        })

        return jsonify({
            "status": "success",
            "server_id": server_id
        })

    except Exception as e:

        traceback.print_exc()

        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

# =========================================================
# GET SERVER POOL
# =========================================================
@app.route("/get-server-pool", methods=["GET"])
def get_server_pool():

    try:

        docs = (
            db.collection("hub_system")
              .document("server_pool")
              .collection("servers")
              .stream()
        )

        results = []

        for doc in docs:

            results.append(doc.to_dict())

        return jsonify({
            "status": "success",
            "servers": results
        })

    except Exception as e:

        traceback.print_exc()

        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

# =========================================================
# UPDATE SERVER METRICS
# =========================================================
@app.route("/update-server-metrics", methods=["POST"])
def update_server_metrics():

    try:

        data = request.get_json()

        server_id = data.get("server_id")

        if not server_id:

            return jsonify({
                "status": "error",
                "message": "missing server_id"
            }), 400

        doc_ref = (
            db.collection("hub_system")
              .document("server_pool")
              .collection("servers")
              .document(server_id)
        )

        doc_ref.update({

            "cpu": data.get("cpu", 0),

            "ram": data.get("ram", 0),

            "requests_per_sec": data.get(
                "requests_per_sec", 0
            ),

            "response_ms": data.get(
                "response_ms", 0
            ),

            "active_users": data.get(
                "active_users", 0
            ),

            "load_score": data.get(
                "load_score", 0
            ),

            "last_ping": firestore.SERVER_TIMESTAMP
        })

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
# CREATE TENANT
# hub_system/tenant_routes/{tenant_id}
# =========================================================
@app.route("/create-tenant", methods=["POST"])
def create_tenant():

    try:

        data = request.get_json()

        tenant_id = data.get("tenant_id")

        default_server = data.get("default_server")

        if not tenant_id:

            return jsonify({
                "status": "error",
                "message": "missing tenant_id"
            }), 400

        doc_ref = (
            db.collection("hub_system")
              .document("tenant_routes")
              .collection("tenants")
              .document(tenant_id)
        )

        doc_ref.set({

            "tenant_id": tenant_id,

            "default_server": default_server,

            "plan": "free",

            "max_users": 1000,

            "created_at": firestore.SERVER_TIMESTAMP
        })

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
# CREATE USER ROUTE
# hub_system/user_routes/{user_id}
# =========================================================
@app.route("/create-user-route", methods=["POST"])
def create_user_route():

    try:

        data = request.get_json()

        user_id = data.get("user_id")

        tenant_id = data.get("tenant_id")

        if not user_id:

            return jsonify({
                "status": "error",
                "message": "missing user_id"
            }), 400

        # =================================================
        # FIND LOWEST LOAD SERVER
        # =================================================
        docs = (
            db.collection("hub_system")
              .document("server_pool")
              .collection("servers")
              .stream()
        )

        selected_server = None

        lowest_load = 999999

        for doc in docs:

            server = doc.to_dict()

            if server.get("status") != "online":
                continue

            load_score = server.get("load_score", 0)

            if load_score < lowest_load:

                lowest_load = load_score

                selected_server = server

        if not selected_server:

            return jsonify({
                "status": "error",
                "message": "no available server"
            }), 500

        # =================================================
        # SAVE USER ROUTE
        # =================================================
        route_ref = (
            db.collection("hub_system")
              .document("user_routes")
              .collection("routes")
              .document(user_id)
        )

        route_ref.set({

            "user_id": user_id,

            "tenant_id": tenant_id,

            "server_id": selected_server["server_id"],

            "cloud_url": selected_server["cloud_url"],

            "created_at": firestore.SERVER_TIMESTAMP,

            "last_active": firestore.SERVER_TIMESTAMP
        })

        # =================================================
        # INCREASE ACTIVE USER
        # =================================================
        server_ref = (
            db.collection("hub_system")
              .document("server_pool")
              .collection("servers")
              .document(selected_server["server_id"])
        )

        server_ref.update({
            "active_users": firestore.Increment(1)
        })

        return jsonify({

            "status": "success",

            "user_id": user_id,

            "server_id": selected_server["server_id"],

            "cloud_url": selected_server["cloud_url"]
        })

    except Exception as e:

        traceback.print_exc()

        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

# =========================================================
# GET USER ROUTE
# =========================================================
@app.route("/get-user-route/<user_id>", methods=["GET"])
def get_user_route(user_id):

    try:

        doc_ref = (
            db.collection("hub_system")
              .document("user_routes")
              .collection("routes")
              .document(user_id)
        )

        doc = doc_ref.get()

        if not doc.exists:

            return jsonify({
                "status": "error",
                "message": "route not found"
            }), 404

        return jsonify({
            "status": "success",
            "data": doc.to_dict()
        })

    except Exception as e:

        traceback.print_exc()

        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

# =========================================================
# AUTO ROUTING
# =========================================================
@app.route("/auto-route", methods=["POST"])
def auto_route():

    try:

        body = request.get_json()

        user_id = body.get("user_id")

        if not user_id:

            return jsonify({
                "status": "error",
                "message": "missing user_id"
            }), 400

        # =================================================
        # CHECK EXISTING ROUTE
        # =================================================
        route_ref = (
            db.collection("hub_system")
              .document("user_routes")
              .collection("routes")
              .document(user_id)
        )

        route_doc = route_ref.get()

        # =================================================
        # EXISTING USER
        # =================================================
        if route_doc.exists:

            route_data = route_doc.to_dict()

            route_ref.update({
                "last_active": firestore.SERVER_TIMESTAMP
            })

            return jsonify({

                "status": "existing",

                "server_id": route_data["server_id"],

                "cloud_url": route_data["cloud_url"]
            })

        # =================================================
        # NEW USER
        # =================================================
        docs = (
            db.collection("hub_system")
              .document("server_pool")
              .collection("servers")
              .stream()
        )

        selected_server = None

        lowest_load = 999999

        for doc in docs:

            server = doc.to_dict()

            if server.get("status") != "online":
                continue

            load_score = server.get("load_score", 0)

            if load_score < lowest_load:

                lowest_load = load_score

                selected_server = server

        if not selected_server:

            return jsonify({
                "status": "error",
                "message": "no server available"
            }), 500

        route_ref.set({

            "user_id": user_id,

            "server_id": selected_server["server_id"],

            "cloud_url": selected_server["cloud_url"],

            "created_at": firestore.SERVER_TIMESTAMP,

            "last_active": firestore.SERVER_TIMESTAMP
        })

        return jsonify({

            "status": "new",

            "server_id": selected_server["server_id"],

            "cloud_url": selected_server["cloud_url"]
        })

    except Exception as e:

        traceback.print_exc()

        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

# =========================================================
# HEALTH CHECK
# =========================================================
@app.route("/health", methods=["GET"])
def health():

    return jsonify({
        "status": "online",
        "service": "hub-switch"
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