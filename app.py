from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import random

app = Flask(__name__)

line_bot_api = LineBotApi('YOUR_CHANNEL_ACCESS_TOKEN')
handler = WebhookHandler('YOUR_CHANNEL_SECRET')

questions = [
    "What's the past tense of 'go'?",
    "Translate into English: 彼は昨日学校に来ませんでした。",
    "Choose the correct: (1) He go. (2) He goes.",
    "What is the opposite of 'difficult'?",
    "Which is correct: (1) I have went. (2) I have gone.",
]

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)

    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    msg = event.message.text.strip()
    if msg == "問題":
        question = random.choice(questions)
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=question))
    else:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="「問題」と送ってください！"))

if __name__ == "__main__":
    app.run()
