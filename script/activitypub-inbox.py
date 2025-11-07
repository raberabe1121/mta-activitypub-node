#!/usr/bin/env python3
from flask import Flask, request, jsonify
from datetime import datetime
import os
import json

LOG_FILE = "/var/log/activitypub-inbox.log"
DB_FILE = "/var/www/activitypub/inbox.json"

app = Flask(__name__)
os.makedirs(os.path.dirname(DB_FILE), exist_ok=True)

def log(msg):
    with open(LOG_FILE, "a") as f:
        f.write(f"[{datetime.now()}] {msg}\n")

def save_to_db(data):
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r") as f:
            try:
                db = json.load(f)
            except:
                db = []
    else:
        db = []
    db.append(data)
    with open(DB_FILE, "w") as f:
        json.dump(db, f, indent=2, ensure_ascii=False)

@app.route("/inbox", methods=["POST"])
def inbox():
    try:
        activity = request.json
        save_to_db(activity)
        log(f"Received Activity: {activity.get('type', 'Unknown')} from {activity.get('actor', '?')}")
        return jsonify({"status": "ok"}), 200
    except Exception as e:
        log(f"ERROR: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/inbox", methods=["GET"])
def list_inbox():
    if not os.path.exists(DB_FILE):
        return jsonify([])
    with open(DB_FILE, "r") as f:
        try:
            db = json.load(f)
        except:
            db = []
    return jsonify(db)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
