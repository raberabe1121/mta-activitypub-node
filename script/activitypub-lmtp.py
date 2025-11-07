#!/usr/bin/env python3
import sys
import os
import json
import email
from email import policy
from datetime import datetime
import subprocess

LOG_FILE = "/var/log/activitypub-lmtp.log"
INBOX_FILE = "/var/www/activitypub/inbox.json"
OUTBOX_FILE = "/var/www/activitypub/outbox.json"
MESSAGES_FILE = "/var/www/activitypub/messages.json"

def save_message(activity):
    """受信したActivityPubメッセージをmessages.jsonに保存"""
    try:
        if not os.path.exists(MESSAGES_FILE):
            with open(MESSAGES_FILE, "w") as f:
                json.dump([], f, indent=2)

        with open(MESSAGES_FILE, "r") as f:
            messages = json.load(f)

        messages.append({
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "type": activity.get("type"),
            "actor": activity.get("actor"),
            "object": activity.get("object"),
        })

        with open(MESSAGES_FILE, "w") as f:
            json.dump(messages, f, indent=2)

    except Exception as e:
        print(f"[ERROR] Could not save message: {e}")

def log(msg: str):
    with open(LOG_FILE, "a") as f:
        f.write(f"[{datetime.now().isoformat()}] {msg}\n")

def load_json(path):
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                return json.load(f)
        except json.JSONDecodeError:
            return []
    return []

def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def load_inbox():
    if os.path.exists(INBOX_FILE):
        with open(INBOX_FILE, "r") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return []
    return []

def save_inbox(messages):
    with open(INBOX_FILE, "w") as f:
        json.dump(messages, f, indent=2, ensure_ascii=False)

def load_outbox():
    if os.path.exists(OUTBOX_FILE):
        try:
            with open(OUTBOX_FILE, 'r') as f:
                data = json.load(f)
                # ファイルがリストならそのまま返す
                if isinstance(data, list):
                    return data
                # 辞書だったらリスト化
                elif isinstance(data, dict):
                    return [data]
        except Exception as e:
            log(f"Failed to load outbox: {e}")
    return []

def save_outbox(activities):
    with open(OUTBOX_FILE, "w") as f:
        json.dump(activities, f, indent=2, ensure_ascii=False)

def main():
    # --- メールを読み取る ---
    raw_data = sys.stdin.read()
    log(f"stdin bytes={len(raw_data)}")

    msg = email.message_from_string(raw_data, policy=policy.default)
    from_addr = msg.get("From")
    to_addr = msg.get_all("To", [])
    subject = msg.get("Subject")

    # --- 本文を抽出 ---
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "application/activity+json":
                body = part.get_content()
                break
            elif part.get_content_type() == "text/plain" and not body:
                body = part.get_content()
    else:
        body = msg.get_content()

    log(f"From: {from_addr} To: {to_addr}")
    log(f"Subject: {subject}")
    log(f"Body:\n{body}\n")

    # --- ActivityPub JSON として解析 ---
    try:
        activity = json.loads(body)
        log("Detected ActivityPub JSON payload")

        inbox = load_json(INBOX_FILE)
        inbox.append({
            "timestamp": datetime.now().isoformat(),
            "from": from_addr,
            "to": to_addr,
            "subject": subject,
            "activity": activity
        })
        save_json(INBOX_FILE, inbox)

        activities = activity if isinstance(activity, list) else [activity]
        for act in activities:
            # Follow を受信したら自動で Accept を返信
            if isinstance(act, dict) and act.get("type") == "Follow":
                follower_actor = act.get("actor")
                object_actor = act.get("object")
                log(f"Follow detected from {follower_actor} → {object_actor}")
                save_message(act)

                accept_activity = {
                    "@context": "https://www.w3.org/ns/activitystreams",
                    "id": f"https://ipcnode.local/activities/{datetime.utcnow().timestamp()}",
                    "type": "Accept",
                    "actor": object_actor,
                    "object": act,
                    "timestamp": datetime.utcnow().isoformat()
                }

                outbox = load_outbox()
                outbox.append(accept_activity)
                save_outbox(outbox)

                # 返信は Dovecot LMTP ソケットを優先（自己ハンドラ再入によるタイムアウト回避）。無ければ 127.0.0.1:2626
                socket_path = "/var/run/dovecot/lmtp"
                base_cmd = [
                    "/usr/local/bin/activitypub-send.py",
                    "--from", "follow@ipcnode.local",
                    "--to", from_addr,
                    "--outbox", OUTBOX_FILE,
                ]
                if os.path.exists(socket_path):
                    cmd = base_cmd + ["--socket", socket_path]
                else:
                    cmd = base_cmd + ["--host", "127.0.0.1", "--port", "2626"]
                try:
                    result = subprocess.run(cmd, check=False, capture_output=True, text=True)
                    log(f"auto-accept send returncode={result.returncode}")
                    if result.stdout:
                        for line in result.stdout.splitlines():
                            log(f"send stdout: {line}")
                    if result.stderr:
                        for line in result.stderr.splitlines():
                            log(f"send stderr: {line}")
                    if result.returncode == 0:
                        log(f"Sent Accept for Follow from {follower_actor}")
                    else:
                        log("Failed to send Accept")
                except Exception as e:
                    log(f"Exception while sending Accept: {e}")

    except json.JSONDecodeError:
        log("No valid JSON found in body, skipping ActivityPub parse.")

    print("250 OK Message received")

if __name__ == "__main__":
    main()
