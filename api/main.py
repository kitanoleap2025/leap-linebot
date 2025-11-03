# api/main.py
import os
import json
from linebot import LineBotApi, WebhookHandler
from linebot.models import MessageEvent, TextMessage, TextSendMessage
from linebot.exceptions import InvalidSignatureError

line_bot_api = LineBotApi(os.environ["LINE_CHANNEL_ACCESS_TOKEN_LEAP"])
line_handler = WebhookHandler(os.environ["LINE_CHANNEL_SECRET_LEAP"])

def handler(request):
    if request.method != "POST":
        return {"statusCode": 405, "body": "Method Not Allowed"}

    try:
        body = request.get_data(as_text=True)
    except Exception as e:
        return {"statusCode": 400, "body": f"Bad Request: {str(e)}"}

    signature = request.headers.get("x-line-signature", "")

    try:
        line_handler.handle(body, signature)
    except InvalidSignatureError:
        return {"statusCode": 400, "body": "Invalid signature"}

    return {"statusCode": 200, "body": "OK"}

@line_handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    text = event.message.text
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=f"受け取りました: {text}")
    )
