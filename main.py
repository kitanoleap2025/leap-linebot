from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.models import MessageEvent, TextMessage, TextSendMessage
from linebot.exceptions import InvalidSignatureError
import os
import random
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

line_bot_api = LineBotApi(os.getenv("LINE_CHANNEL_ACCESS_TOKEN"))
handler = WebhookHandler(os.getenv("LINE_CHANNEL_SECRET"))

questions = [
    "1:I ___ with the idea that students should not be given too much homework.",
    "2:He strongly ___ corruption until he was promoted.",
    "3:The teacher ___ me to study English vocabulary",
    "4:___: Don’t argue with fools. From a distance, people might not be able to tell who is who.",
    "5:We ___ the problem so much, we forgot to solve it."
]

@app.route("/")
def home():
    return "LINE Bot is running!"

@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers["X-Line-Signature"]
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)

    return "OK"

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    if event.message.text.strip() == "問題":
        question = random.choice(questions)
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=question)
        )

import os

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port)
