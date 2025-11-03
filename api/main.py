from http.server import BaseHTTPRequestHandler
import json
import os
import urllib.request

# LINE Messaging API設定
LINE_ACCESS_TOKEN = os.environ.get("LINE_ACCESS_TOKEN_LEAP")

class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        content_length = int(self.headers['Content-Length'])
        body = self.rfile.read(content_length)
        data = json.loads(body.decode('utf-8'))

        # LINEのイベントを処理
        for event in data.get("events", []):
            if event["type"] == "message" and event["message"]["type"] == "text":
                reply_token = event["replyToken"]
                user_message = event["message"]["text"]

                self.reply_message(reply_token, f"あなたのメッセージ: {user_message}")

        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

    def reply_message(self, reply_token, text):
        url = "https://api.line.me/v2/bot/message/reply"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {LINE_ACCESS_TOKEN_LEAP}"
        }
        payload = {
            "replyToken": reply_token,
            "messages": [{"type": "text", "text": text}]
        }
        req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers)
        urllib.request.urlopen(req)
