from flask import Flask, render_template, jsonify, request, redirect, url_for
import json
import subprocess
import os
from datetime import datetime
from pathlib import Path

app = Flask(__name__)

INBOX_PATH = Path("/var/www/activitypub/inbox.json")
OUTBOX_PATH = Path("/var/www/activitypub/outbox.json")

def load_json(path):
    if path.exists():
        try:
            with open(path, "r") as f:
                return json.load(f)
        except json.JSONDecodeError:
            return []
    return []

def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

@app.route("/")
def index():
    """受信メッセージ一覧ページ"""
    messages = sorted(load_json(INBOX_PATH), key=lambda m: m.get("timestamp", ""), reverse=True)
    return render_template("inbox.html", messages=messages)

@app.route("/reply", methods=["POST"])
def reply():
    """Followに対してAcceptを返信"""
    actor = request.form.get("actor")
    object_ = request.form.get("object")
    mail_from = request.form.get("mail_from") or "follow@ipcnode.local"
    rcpt_to = request.form.get("rcpt_to") or "test@ipcnode.local"

    if not actor or not object_:
        return "Invalid request", 400

    activity = {
        "@context": "https://www.w3.org/ns/activitystreams",
        "type": "Accept",
        "actor": object_,
        "object": actor,
        "timestamp": datetime.utcnow().isoformat()
    }

    outbox = load_json(OUTBOX_PATH)
    if not isinstance(outbox, list):
        outbox = []
    outbox.append(activity)
    save_json(OUTBOX_PATH, outbox)

    print(f"[{activity['timestamp']}] Generated Accept reply for {actor}")

    # LMTP経由で返信送信
    try:
        script_path = "/usr/local/bin/activitypub-send.py"
        socket_path = "/var/run/dovecot/lmtp"  # LMTPソケットを指定

        base_cmd = [
            script_path,
            "--from", mail_from,
            "--to", rcpt_to,
            "--socket", socket_path,
            "--outbox", str(OUTBOX_PATH),
        ]

        # 実行権限がない場合は python3 経由で実行
        cmd = base_cmd if os.access(script_path, os.X_OK) else ["python3"] + base_cmd

        result = subprocess.run(cmd, check=False, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"activitypub-send.py failed ({result.returncode}): {result.stderr}")
        else:
            print(result.stdout)
    except Exception as e:
        print(f"Failed to invoke activitypub-send.py: {e}")

    return redirect(url_for("index"))

@app.route("/api/reply", methods=["POST"])
def api_reply():
    """Followに対してAcceptを返信（JSON API, リダイレクトなし）"""
    data = request.json or {}
    actor = data.get("actor")
    object_ = data.get("object")
    mail_from = data.get("mail_from") or "follow@ipcnode.local"
    rcpt_to = data.get("rcpt_to") or "test@ipcnode.local"

    if not actor or not object_:
        return jsonify({"status": "error", "error": "Invalid request"}), 400

    activity = {
        "@context": "https://www.w3.org/ns/activitystreams",
        "type": "Accept",
        "actor": object_,
        "object": actor,
        "timestamp": datetime.utcnow().isoformat()
    }

    outbox = load_json(OUTBOX_PATH)
    if not isinstance(outbox, list):
        outbox = []
    outbox.append(activity)
    save_json(OUTBOX_PATH, outbox)

    try:
        script_path = "/usr/local/bin/activitypub-send.py"
        socket_path = "/var/run/dovecot/lmtp"

        base_cmd = [
            script_path,
            "--from", mail_from,
            "--to", rcpt_to,
            "--outbox", str(OUTBOX_PATH),
        ]

        if os.path.exists(socket_path):
            send_cmd = base_cmd + ["--socket", socket_path]
        else:
            send_cmd = base_cmd + ["--host", "127.0.0.1", "--port", "2626"]

        cmd = send_cmd if os.access(script_path, os.X_OK) else ["python3"] + send_cmd
        result = subprocess.run(cmd, check=False, capture_output=True, text=True)

        if result.returncode == 0:
            return jsonify({
                "status": "ok",
                "sent_to": rcpt_to,
                "activity": activity,
                "stdout": result.stdout,
            })
        else:
            return jsonify({
                "status": "error",
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }), 500
    except Exception as e:
        return jsonify({"status": "error", "exception": str(e)}), 500

@app.route("/api/inbox")
def api_inbox():
    """JSON形式でInboxを返す"""
    return jsonify(load_json(INBOX_PATH))

@app.route("/api/outbox", methods=["GET", "POST"])
def api_outbox():
    """JSON形式でOutboxを返す"""
    if request.method == "GET":
        return jsonify(load_json(OUTBOX_PATH))

    data = request.json or {}
    actor = data.get("actor", "https://ipcnode.local/users/follow")
    object_ = data.get("object", "https://example.com/users/alice")
    activity_type = data.get("type", "Follow")
    mail_from = data.get("mail_from", "follow@ipcnode.local")
    rcpt_to = data.get("rcpt_to", "test@ipcnode.local")

    activity = {
        "@context": "https://www.w3.org/ns/activitystreams",
        "type": activity_type,
        "actor": actor,
        "object": object_,
        "timestamp": datetime.utcnow().isoformat()
    }

    outbox = load_json(OUTBOX_PATH)
    outbox.append(activity)
    save_json(OUTBOX_PATH, outbox)

    try:
        script_path = "/usr/local/bin/activitypub-send.py"
        socket_path = "/var/run/dovecot/lmtp"
        base_cmd = [
            script_path,
            "--from", mail_from,
            "--to", rcpt_to,
            "--outbox", str(OUTBOX_PATH),
        ]
        if os.path.exists(socket_path):
            send_cmd = base_cmd + ["--socket", socket_path]
        else:
            send_cmd = base_cmd + ["--host", "127.0.0.1", "--port", "2626"]

        cmd = send_cmd if os.access(script_path, os.X_OK) else ["python3"] + send_cmd
        result = subprocess.run(cmd, check=False, capture_output=True, text=True)

        if result.returncode == 0:
            return jsonify({
                "status": "ok",
                "sent_to": rcpt_to,
                "activity": activity,
                "stdout": result.stdout,
            })
        else:
            return jsonify({
                "status": "error",
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }), 500
    except Exception as e:
        return jsonify({"status": "error", "exception": str(e)}), 500

@app.route("/api/outbox_post", methods=["POST"])
def api_outbox_post():
    """Web UIからActivityPubメッセージを送信（LMTPハンドラ: 127.0.0.1:2626 経由）"""
    data = request.json
    if not data:
        return jsonify({"error": "Missing JSON body"}), 400

    # --- メッセージ構築 ---
    actor = data.get("actor", "https://ipcnode.local/users/follow")
    object_ = data.get("object", "https://example.com/users/alice")
    activity_type = data.get("type", "Follow")
    mail_from = data.get("mail_from", "follow@ipcnode.local")
    rcpt_to = data.get("rcpt_to", "test@ipcnode.local")

    activity = {
        "@context": "https://www.w3.org/ns/activitystreams",
        "type": activity_type,
        "actor": actor,
        "object": object_,
        "timestamp": datetime.utcnow().isoformat()
    }

    # --- outbox.json に追加保存 ---
    outbox = load_json(OUTBOX_PATH)
    outbox.append(activity)
    save_json(OUTBOX_PATH, outbox)

    # --- 常に独自LMTPハンドラ(127.0.0.1:2626)経由で送信 ---
    try:
        script_path = "/usr/local/bin/activitypub-send.py"
        cmd = [
            script_path,
            "--from", mail_from,
            "--to", rcpt_to,
            "--host", "127.0.0.1",
            "--port", "2626",
            "--outbox", str(OUTBOX_PATH),
        ]

        # 実行権限がない場合は python3 経由
        if not os.access(script_path, os.X_OK):
            cmd = ["python3"] + cmd

        result = subprocess.run(cmd, check=False, capture_output=True, text=True)

        if result.returncode == 0:
            print(f"[{datetime.now().isoformat()}] Sent {activity_type} via LMTP 2626 → {rcpt_to}")
            return jsonify({
                "status": "ok",
                "sent_to": rcpt_to,
                "activity": activity,
                "stdout": result.stdout,
            })
        else:
            print(f"[ERROR] activitypub-send.py exited {result.returncode}")
            print(result.stderr)
            return jsonify({
                "status": "error",
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }), 500
    except Exception as e:
        print(f"[ERROR] Exception while sending LMTP message: {e}")
        return jsonify({"status": "error", "exception": str(e)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
