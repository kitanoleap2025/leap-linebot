# api/main.py
import os
from linebot import LineBotApi, WebhookHandler
from linebot.models import MessageEvent, TextMessage, TextSendMessage
from linebot.exceptions import InvalidSignatureError
from http.server import BaseHTTPRequestHandler
import json

line_bot_api = LineBotApi(os.environ["LINE_CHANNEL_ACCESS_TOKEN_LEAP"])
handler = WebhookHandler(os.environ["LINE_CHANNEL_SECRET_LEAP"])

def handler(request):
    # POST 以外は許可しない
    if request.method != "POST":
        return {
            "statusCode": 405,
            "body": "Method Not Allowed"
        }

    body = request.get_data(as_text=True)
    signature = request.headers.get("x-line-signature", "")

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        return {
            "statusCode": 400,
            "body": "Invalid signature"
        }

    return {
        "statusCode": 200,
        "body": "OK"
    }

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=f"受け取りました: {event.message.text}")
    )
