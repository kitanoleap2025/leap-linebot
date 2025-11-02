import os, json
from collections import defaultdict, deque
from linebot import LineBotApi, WebhookHandler
from linebot.models import MessageEvent, TextMessage, TextSendMessage
from linebot.exceptions import InvalidSignatureError

from flask import Request, jsonify

# LINE Bot SDK
line_bot_api = LineBotApi(os.environ["LINE_CHANNEL_ACCESS_TOKEN_LEAP"])
handler = WebhookHandler(os.environ["LINE_CHANNEL_SECRET_LEAP"])

# ユーザーデータ
user_scores = defaultdict(dict)
user_names = {}
user_recent_questions = defaultdict(lambda: deque(maxlen=10))

# 共通処理
def handle_message_common(event):
    user_id = event.source.user_id
    msg = event.message.text.strip()
    if user_id not in user_scores:
        user_scores[user_id] = {}
        user_names[user_id] = "イキイキした毎日"

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

# Vercel向けエントリポイント
def handler_main(request: Request):
    if request.method != "POST":
        return "Method Not Allowed", 405

    body = request.get_data(as_text=True)
    signature = request.headers.get("X-Line-Signature", "")
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        return "Invalid signature", 400
    return "OK", 200

# LINEイベント
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    handle_message_common(event)
