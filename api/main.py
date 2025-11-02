# api/main.py
from flask import Flask, request, abort
import os, json
from collections import defaultdict, deque
from dotenv import load_dotenv

from linebot import LineBotApi, WebhookHandler
from linebot.models import MessageEvent, TextMessage, TextSendMessage
from linebot.exceptions import InvalidSignatureError

import firebase_admin
from firebase_admin import credentials, firestore

load_dotenv()

app = Flask(__name__)

# LINE Bot SDK (LEAPだけ)
line_bot_api = LineBotApi(os.getenv("LINE_CHANNEL_ACCESS_TOKEN_LEAP"))
handler = WebhookHandler(os.getenv("LINE_CHANNEL_SECRET_LEAP"))

# Firebase初期化
cred_json = os.getenv("FIREBASE_CREDENTIALS")
cred_dict = json.loads(cred_json)
cred_dict["private_key"] = cred_dict["private_key"].replace("\\n", "\n")
cred = credentials.Certificate(cred_dict)
firebase_admin.initialize_app(cred)
db = firestore.client()

# ユーザーデータ
user_scores = defaultdict(dict)
user_names = {}
user_recent_questions = defaultdict(lambda: deque(maxlen=10))

# --- Flaskルート ---
@app.route("/callback/leap", methods=["POST"])
def callback_leap():
    body = request.get_data(as_text=True)
    signature = request.headers.get("X-Line-Signature", "")
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return "OK"

@app.route("/health")
def health():
    ua = request.headers.get("User-Agent", "")
    if "cron-job.org" in ua:
        return "ok", 200
    return "unauthorized", 403

# --- メッセージ処理共通 ---
def handle_message_common(event):
    user_id = event.source.user_id
    msg = event.message.text.strip()
    if user_id not in user_scores:
        user_scores[user_id] = {}
        user_names[user_id] = "イキイキした毎日"

    # 名前変更
    if msg.startswith("@"):
        new_name = msg[1:].strip()
        if not new_name:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="名前が空です。"))
            return
        if len(new_name) > 10:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="名前は10文字以内です。"))
            return
        user_names[user_id] = new_name
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"名前を「{new_name}」に変更しました。"))
        return

# --- LINEイベント登録 ---
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    handle_message_common(event)
