#!/usr/bin/env python3
import json
import socket
import sys
import argparse
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from datetime import datetime

LMTP_SOCKET = "/var/run/dovecot/lmtp"
OUTBOX_PATH = "/var/www/activitypub/outbox.json"

def _read_reply(s_file, expected_code):
    """サーバ応答を読み切って期待コードを検証する（マルチライン対応）。
    例: 250-... が続き、最後が 250 ... で終わる。
    """
    lines = []
    first = s_file.readline().decode(errors="replace").strip()
    if not first:
        raise RuntimeError("LMTP: empty reply")
    print(first)
    lines.append(first)
    # 先頭3桁をコードとして扱う
    try:
        code = int(first[:3])
    except Exception:
        raise RuntimeError(f"LMTP: invalid reply: {first}")

    # マルチライン: ハイフン継続（例: 250-）
    cont = first[3:4] == "-"
    while cont:
        line = s_file.readline().decode(errors="replace").strip()
        if not line:
            raise RuntimeError("LMTP: unexpected EOF in multiline reply")
        print(line)
        lines.append(line)
        # 継続条件は同じコード+ハイフン。終了は同じコード+スペース
        cont = (line.startswith(f"{code}-"))

    if expected_code is not None and code != expected_code:
        raise RuntimeError(f"LMTP: unexpected code {code}, expected {expected_code}. First line: {first}")
    return code, lines

def send_via_lmtp(message_bytes, mail_from, rcpt_to, socket_path=None, host=None, port=None):
    """LMTPに接続してメッセージ送信（UnixソケットまたはTCP）。"""
    # 接続方式の決定
    if host:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(3.0)
        s.connect((host, port or 24))  # LMTP over TCP の標準ポートは環境依存。明示指定推奨。
    else:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(3.0)
        s.connect(socket_path or LMTP_SOCKET)

    with s:
        s_file = s.makefile("rwb")

        # 一部の環境では 220 バナーが遅延/省略されることがある。
        # まずは短時間バナーを待ち、来なければ LHLO を先行送信して応答を解釈する。
        banner_read = False
        code = None
        try:
            code, _ = _read_reply(s_file, None)
            banner_read = (code == 220)
        except Exception as e:
            # empty reply / timeout 相当は LHLO 先行で再試行
            banner_read = False
            code = None

        if not banner_read:
            # バナー未受信: LHLO を先に送る
            s_file.write(b"LHLO localhost\r\n"); s_file.flush()
            code, _ = _read_reply(s_file, None)
            if code == 220:
                # ここでサーバがバナーを返してきた場合、改めて LHLO を送る
                s_file.write(b"LHLO localhost\r\n"); s_file.flush()
                _read_reply(s_file, 250)
            elif code == 250:
                # すでに LHLO に対する 250
                pass
            else:
                raise RuntimeError(f"LMTP: unexpected code after LHLO: {code}")
        else:
            # バナー受信済み: 通常の LHLO フロー
            s_file.write(b"LHLO localhost\r\n"); s_file.flush()
            _read_reply(s_file, 250)

        # MAIL FROM 250
        s_file.write(f"MAIL FROM:<{mail_from}>\r\n".encode()); s_file.flush()
        _read_reply(s_file, 250)

        # RCPT TO 250
        s_file.write(f"RCPT TO:<{rcpt_to}>\r\n".encode()); s_file.flush()
        _read_reply(s_file, 250)

        # DATA 354
        s_file.write(b"DATA\r\n"); s_file.flush()
        _read_reply(s_file, 354)

        # Message body -> 250
        s_file.write(message_bytes + b"\r\n.\r\n"); s_file.flush()
        _read_reply(s_file, 250)

        # QUIT 221（サーバによっては即切断する場合があるのでエラーは握りつぶす）
        try:
            s_file.write(b"QUIT\r\n"); s_file.flush()
            _read_reply(s_file, 221)
        except Exception:
            pass

def main():
    parser = argparse.ArgumentParser(description="Send ActivityPub activity via LMTP")
    parser.add_argument("--outbox", default=OUTBOX_PATH, help="outbox.json path")
    parser.add_argument("--socket", default=LMTP_SOCKET, help="LMTP UNIX socket path")
    parser.add_argument("--host", default=None, help="LMTP host (use TCP instead of UNIX socket)")
    parser.add_argument("--port", type=int, default=None, help="LMTP TCP port")
    parser.add_argument("--from", dest="mail_from", default="follow@ipcnode.local", help="MAIL FROM address")
    parser.add_argument("--to", dest="rcpt_to", default="alice@ipcnode.local", help="RCPT TO address")
    args = parser.parse_args()

    try:
        with open(args.outbox, "r") as f:
            activities = json.load(f)
    except FileNotFoundError:
        print(f"outbox not found: {args.outbox}")
        sys.exit(1)

    if isinstance(activities, list):
        items = activities
    elif isinstance(activities, dict):
        if isinstance(activities.get("orderedItems"), list):
            items = activities["orderedItems"]
        elif isinstance(activities.get("items"), list):
            items = activities["items"]
        else:
            items = [activities]
    else:
        items = []

    if not items:
        print("No activities in outbox.")
        return

    latest = items[-1]
    msg = EmailMessage()
    msg["From"] = args.mail_from
    msg["To"] = args.rcpt_to
    msg["Subject"] = f"ActivityPub {latest.get('type', 'Activity')}"
    msg["Date"] = formatdate(localtime=True)
    msg["Message-Id"] = make_msgid()

    payload = json.dumps(latest, ensure_ascii=False, indent=2)
    # 一旦 text として設定し、その後 Content-Type を上書き
    msg.set_content(payload, charset="utf-8")
    msg.replace_header("Content-Type", "application/activity+json; charset=utf-8")

    print(f"[{datetime.now().isoformat()}] Sending via LMTP...")
    try:
        send_via_lmtp(
            msg.as_bytes(),
            mail_from=args.mail_from,
            rcpt_to=args.rcpt_to,
            socket_path=args.socket,
            host=args.host,
            port=args.port,
        )
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)
    print("Done.")

if __name__ == "__main__":
    main()
