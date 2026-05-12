from itertools import product
from flask import Flask, request, jsonify, Response, stream_with_context, render_template

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

# ------------------------------------
# Flask
# ------------------------------------
app = Flask(__name__)

# ------------------------------------
# Firebase Config
# ------------------------------------
RTD_URL1 = "https://baselineoa-default-rtdb.asia-southeast1.firebasedatabase.app/"

BUCKET_NAME = "baselineoa.firebasestorage.app"

# ------------------------------------
# Service Account
# ------------------------------------
service_account_json = os.environ.get("FIREBASE_SERVICE_KEY")

if not service_account_json:
    raise RuntimeError("Missing FIREBASE_SERVICE_KEY")

cred = credentials.Certificate(
    json.loads(service_account_json)
)

# ------------------------------------
# Firebase Initialize
# ------------------------------------
firebase_admin.initialize_app(
    cred,
    {
        "storageBucket": BUCKET_NAME,
        "databaseURL": RTD_URL1
    }
)

# ------------------------------------
# Firebase Clients
# ------------------------------------
db = firestore.client()

rtdb_ref = rtdb.reference("/")

bucket = storage.bucket()

# =========================================================
# TEST ROUTE
# =========================================================
@app.route("/create_firestore", methods=["GET"])
def create_firestore():

    try:

        # -------------------------------------------------
        # path : data1/doc
        # -------------------------------------------------
        doc_ref = db.collection("data1").document("doc")

        # -------------------------------------------------
        # create/update field
        # -------------------------------------------------
        doc_ref.set({
            "name": "Thanoo",
            "timestamp": firestore.SERVER_TIMESTAMP
        })

        return jsonify({
            "status": "success",
            "message": "Firestore created",
            "path": "data1/doc"
        })

    except Exception as e:

        traceback.print_exc()

        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


# =========================================================
# READ FIRESTORE
# =========================================================
@app.route("/read_firestore", methods=["GET"])
def read_firestore():

    try:

        doc_ref = db.collection("data1").document("doc")

        doc = doc_ref.get()

        if not doc.exists:

            return jsonify({
                "status": "error",
                "message": "Document not found"
            })

        data = doc.to_dict()

        return jsonify({
            "status": "success",
            "data": data
        })

    except Exception as e:

        traceback.print_exc()

        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


# =========================================================
# UPDATE FIRESTORE
# =========================================================
@app.route("/update_firestore", methods=["GET"])
def update_firestore():

    try:

        doc_ref = db.collection("data1").document("doc")

        doc_ref.update({
            "name": "Thanoo Update",
            "age": 20,
            "updated_at": firestore.SERVER_TIMESTAMP
        })

        return jsonify({
            "status": "success",
            "message": "Firestore updated"
        })

    except Exception as e:

        traceback.print_exc()

        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


# =========================================================
# DELETE FIRESTORE
# =========================================================
@app.route("/delete_firestore", methods=["GET"])
def delete_firestore():

    try:

        doc_ref = db.collection("data1").document("doc")

        doc_ref.delete()

        return jsonify({
            "status": "success",
            "message": "Firestore deleted"
        })

    except Exception as e:

        traceback.print_exc()

        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


# =========================================================
# MAIN
# =========================================================
# ------------------------ 
if __name__ == "__main__":
    app.run(debug=True)
