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

questions = [
    {"text": "001 I ___ with the idea that students should not be given too much homework.\n生徒に宿題を与えすぎるべきではないという考えに賛成です.",
     "answer": "agree"},
    {"text": "002 He strongly ___ corruption until he was promoted.\n昇進するまでは,彼は汚職に強く反対していた.",
     "answer": "opposed"},
    {"text": "003 The teacher ___ me to study English vocabulary.\n先生は私に英単語を勉強するよう助言した.",
     "answer": "advised"},
    {"text": "004 ___: Don’t argue with fools. From a distance, people might not be able to tell who is who.\nヒント：ばかとは口論するな.遠くから見たら,どっちがどっちか分からないから.",
     "answer": "tip"},
    {"text": "005 We ___ the problem so much, we forgot to solve it.\n私たちはその問題についてあまりに議論しすぎて,解決するのを忘れていた.",
     "answer": "discussed"},
    {"text": "006 \n",
     "answer": ""},
    {"text": "007 He ___ that sleep wasn’t necessary for eaxms.\n彼は試験のために睡眠は必要ないと主張した.",
     "answer": "argued"},
    {"text": "008 I ___ that learning classical Japanese in high school is unnecessary.\n高校で古文を学ぶことは不必要だと主張する.",
     "answer": "claim"},
    {"text": "009 He ___ about having to buy a math textbook he would never use.\n彼は使うことのない数学の教科書を買わされることに不満を言っていました.",
     "answer": "complained"},
    {"text": "010 The company ___ him a job after the interview.\n面接の後,会社は彼に仕事を申し出た.",
     "answer": "offered"},
    {"text": "011 \n",
     "answer": ""},
    {"text": "012 \n",
     "answer": ""},
    {"text": "013 He said he was ___ to her for the feedback, but he ignored all of it.\n彼は彼女のフィードバックに感謝していると言ったが,すべて無視した.",
     "answer": "grateful"},
    {"text": """019 She was ___ "Best Excuse Maker" for always avoiding responsibility.\n彼女は常に責任を避けたことで「最高の言い訳メーカー」を受賞した.""",
     "answer": "awarded"},
    {"text": """020 They ___ ignoring the group project as "respecting individual effort."\n彼らはグループ課題を無視することを「個人の努力を尊重する」と表現しました.""",
     "answer": "described"},
    {"text": "026 With modern ___, we can talk to anyone in the world except the person next to you.\n現代のテクノロジーでは,隣にいる人以外の誰とでも話すことができる.",
     "answer": ""},
    {"text": "043 This machine can ___ 10 parts in one minute.\nこの機械は１分で10個の部品を生産出来る.",
     "answer": "produce"},
    {"text": "044 ___ LINE stickers using the teather's face\n先生の顔でLINEスタンプを作る",
     "answer": "create"},
    {"text": "045 Kitano high school was ___ in 1873.\n北野高校は1873年に設立された.",
     "answer": "established"},
    {"text": "074 the key ___ that led to the suspension \n停学への決定打となる証拠",
     "answer": "evidence"},
    {"text": "079 They ___ for confidence without thinking.\n彼らは考えずに信任に投票した.",
     "answer": "voted"},
    {"text": "101 ___ the pen of the person sitting next to me\n隣の席の人のペンを破壊する",
     "answer": "destroy"},
]

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
                reply = "Correct answer✅\n\n Next："
            else:
                reply = f"Incorrect❌ The correct answer is「{correct_answer}」.\n\n Next："
            # 出題状態をクリア
            del user_states[user_id]

            # 新しい問題をランダムに出す
            q = random.choice(questions)
            user_states[user_id] = q["answer"]

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

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port)
