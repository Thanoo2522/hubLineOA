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
# REPLY MESSAGE
# =========================================================
def reply_message(reply_token, text):

    url = "https://api.line.me/v2/bot/message/reply"

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}"
    }

    payload = {
        "replyToken": reply_token,
        "messages": [
            {
                "type": "text",
                "text": text
            }
        ]
    }

    response = requests.post(
        url,
        headers=headers,
        json=payload
    )

    print("REPLY STATUS:", response.status_code)

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

        events = body.get("events", [])

        for event in events:

            # =================================================
            # REPLY TOKEN
            # =================================================
            reply_token = event.get("replyToken")

            # =================================================
            # USER ID
            # =================================================
            user_id = event["source"]["userId"]

            # =================================================
            # MESSAGE EVENT
            # =================================================
            if event["type"] == "message":

                message = event["message"]

                # =================================================
                # TEXT MESSAGE
                # รูปแบบ:
                # ชื่อภาพ|คำอธิบาย
                # =================================================
                if message["type"] == "text":

                    text = message["text"]

                    print("TEXT:", text)

                    image_name = ""

                    description = text

                    # ---------------------------------------------
                    # split text
                    # ---------------------------------------------
                    if "|" in text:

                        parts = text.split("|", 1)

                        image_name = parts[0].strip()

                        description = parts[1].strip()

                    # ---------------------------------------------
                    # save temp user data
                    # image_rw_sys1/USER_ID
                    # ---------------------------------------------
                    db.collection("image_rw_sys1") \
                        .document(user_id) \
                        .set({

                            "latestImageName": image_name,
                            "latestDescription": description,
                            "updatedAt": firestore.SERVER_TIMESTAMP

                        }, merge=True)

                    # ---------------------------------------------
                    # reply
                    # ---------------------------------------------
                    reply_message(
                        reply_token,
                        "บันทึกชื่อภาพและคำอธิบายแล้ว\nส่งรูปภาพได้เลย"
                    )

                # =================================================
                # IMAGE MESSAGE
                # =================================================
                elif message["type"] == "image":

                    message_id = message["id"]

                    print("IMAGE:", message_id)

                    # ---------------------------------------------
                    # get temp data
                    # ---------------------------------------------
                    user_doc = db.collection("image_rw_sys1") \
                                 .document(user_id) \
                                 .get()

                    image_name = ""

                    description = ""

                    if user_doc.exists:

                        user_data = user_doc.to_dict()

                        image_name = user_data.get(
                            "latestImageName",
                            ""
                        )

                        description = user_data.get(
                            "latestDescription",
                            ""
                        )

                    # ---------------------------------------------
                    # download image from LINE
                    # ---------------------------------------------
                    headers = {
                        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}"
                    }

                    url = (
                        f"https://api-data.line.me/v2/bot/message/"
                        f"{message_id}/content"
                    )

                    response = requests.get(
                        url,
                        headers=headers
                    )

                    # ---------------------------------------------
                    # error download
                    # ---------------------------------------------
                    if response.status_code != 200:

                        print("DOWNLOAD ERROR")

                        reply_message(
                            reply_token,
                            "ดาวน์โหลดรูปภาพไม่สำเร็จ"
                        )

                        continue

                    # ---------------------------------------------
                    # image binary
                    # ---------------------------------------------
                    image_data = response.content

                    # ---------------------------------------------
                    # create image id
                    # ---------------------------------------------
                    image_id = str(uuid.uuid4())

                    # ---------------------------------------------
                    # default image name
                    # ---------------------------------------------
                    if image_name == "":

                        image_name = f"image_{image_id}"

                    # ---------------------------------------------
                    # storage filename
                    # ---------------------------------------------
                    filename = (
                        f"line_images/"
                        f"{user_id}/"
                        f"{image_id}.jpg"
                    )

                    # ---------------------------------------------
                    # upload firebase storage
                    # ---------------------------------------------
                    blob = bucket.blob(filename)

                    blob.upload_from_string(
                        image_data,
                        content_type="image/jpeg"
                    )

                    # ---------------------------------------------
                    # public url
                    # ---------------------------------------------
                    blob.make_public()

                    image_url = blob.public_url

                    # ---------------------------------------------
                    # firestore save
                    #
                    # image_rw_sys1
                    #   └── USER_ID
                    #         └── images
                    #               └── IMAGE_ID
                    # ---------------------------------------------
                    db.collection("image_rw_sys1") \
                        .document(user_id) \
                        .collection("images") \
                        .document(image_id) \
                        .set({

                            "imageId": image_id,
                            "imageName": image_name,
                            "description": description,
                            "imageUrl": image_url,
                            "filename": filename,
                            "userId": user_id,
                            "createdAt": firestore.SERVER_TIMESTAMP

                        })

                    print("UPLOAD SUCCESS")

                    # ---------------------------------------------
                    # reply success
                    # ---------------------------------------------
                    reply_message(
                        reply_token,
                        f"บันทึกรูปสำเร็จ\nชื่อภาพ: {image_name}"
                    )

        return "OK", 200

    except Exception as e:

        traceback.print_exc()

        return "ERROR", 500

# =========================================================
# GET IMAGE LIST
# =========================================================
@app.route("/get_images/<user_id>", methods=["GET"])
def get_images(user_id):

    try:

        docs = db.collection("image_rw_sys1") \
                 .document(user_id) \
                 .collection("images") \
                 .order_by(
                     "createdAt",
                     direction=firestore.Query.DESCENDING
                 ) \
                 .stream()

        results = []

        for doc in docs:

            data = doc.to_dict()

            results.append(data)

        return jsonify({
            "status": "success",
            "count": len(results),
            "data": results
        })

    except Exception as e:

        traceback.print_exc()

        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

# =========================================================
# DELETE IMAGE
# =========================================================
@app.route("/delete_image/<user_id>/<image_id>", methods=["DELETE"])
def delete_image(user_id, image_id):

    try:

        # ---------------------------------------------
        # get firestore document
        # ---------------------------------------------
        doc_ref = db.collection("image_rw_sys1") \
                    .document(user_id) \
                    .collection("images") \
                    .document(image_id)

        doc = doc_ref.get()

        if not doc.exists:

            return jsonify({
                "status": "error",
                "message": "Image not found"
            }), 404

        data = doc.to_dict()

        filename = data.get("filename")

        # ---------------------------------------------
        # delete storage
        # ---------------------------------------------
        if filename:

            blob = bucket.blob(filename)

            blob.delete()

        # ---------------------------------------------
        # delete firestore
        # ---------------------------------------------
        doc_ref.delete()

        return jsonify({
            "status": "success",
            "message": "Image deleted"
        })

    except Exception as e:

        traceback.print_exc()

        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

# =========================================================
# HOME
# =========================================================
@app.route("/", methods=["GET"])
def home():

    return "HubLineOA OK"

# =========================================================
# MAIN
# =======================================================
if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=8080,
        debug=True
    )