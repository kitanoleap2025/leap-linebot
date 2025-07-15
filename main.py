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

user_states = {}  # ユーザーごとの状態を記録

@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)

    return "OK"

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_id = event.source.user_id
    msg = event.message.text.strip()

    if msg == "問題":
        q = random.choice(questions)
        user_states[user_id] = q["answer"]  # ユーザーごとに正解を保存
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=q["text"])
        )
    else:
        if user_id in user_states:
            correct_answer = user_states[user_id].lower()
            if msg.lower() == correct_answer:
                reply = "Correct answer✅\n\n次の問題はこちらです："
            else:
                reply = f"Incorrect❌ The correct answer is「{correct_answer}」.\n\n次の問題はこちらです："
            # 出題状態をクリア
            del user_states[user_id]

            # 新しい問題をランダムに出す
            q = random.choice(questions)
            user_states[user_id] = q["answer"]

            # 返信を複数メッセージで送る場合はreply_messageにリストを渡す
            messages = [
                TextSendMessage(text=reply),
                TextSendMessage(text=q["text"])
            ]

            line_bot_api.reply_message(
                event.reply_token,
                messages
            )
        else:
            reply = "「問題」と送ってください。"
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text=reply)
            )

import os

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port)
app = app 
