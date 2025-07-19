from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.models import MessageEvent, TextMessage, TextSendMessage
from linebot.exceptions import InvalidSignatureError
import os
import random
from dotenv import load_dotenv

load_dotenv()
app = Flask(__name__)  # ここを先に書く

line_bot_api = LineBotApi(os.getenv("LINE_CHANNEL_ACCESS_TOKEN"))
handler = WebhookHandler(os.getenv("LINE_CHANNEL_SECRET"))

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature', '')
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)

    return 'OK'

user_states = {}        # 出題中のユーザーと正解
user_histories = {}     # 出題範囲ごとの正誤履歴（最大100件）
active_games = {}       # 現在ミニゲーム中のユーザー

# --- 出題リスト ---
questions_1_1000 = [
    {"text": "001 I ___ with the idea that students should not be given too much homework.\n生徒に宿題を与えすぎるべきではないという考えに賛成です.", "answer": "agree"}
]

questions_1000_1935 = [
    {"text": "1001 The ___ made a critical discovery in the lab.\nその科学者は研究室で重大な発見をした。", "answer": "scientist"}
]

# --- ゲームクラス定義 ---
class ShotgunRussianRoulette:
    def __init__(self):
        self.player_hp = 4
        self.dealer_hp = 4
        self.reload()
        self.current_index = 0
        self.turn = "player"

    def reload(self):
        self.live = random.randint(1, 3)
        self.empty = random.randint(1, 3)
        self.bullets = ['live'] * self.live + ['empty'] * self.empty
        random.shuffle(self.bullets)
        self.current_index = 0

    def player_action(self, choice):
        if self.current_index >= len(self.bullets):
            self.reload()

        bullet = self.bullets[self.current_index]
        self.current_index += 1
        result_text = ""

        if choice == "1":  # 自分に撃つ
            if bullet == 'live':
                self.player_hp -= 1
                result_text = "BANG💥 実弾だった..."
                self.turn = "dealer"
            else:
                result_text = "CLICK 空砲だった...プレイヤーターン継続."
        elif choice == "2":  # 相手に撃つ
            if bullet == 'live':
                self.dealer_hp -= 1
                result_text = "BANG💥 実弾だった..."
            else:
                result_text = "CLICK 空砲だった..."
            self.turn = "dealer"
        else:
            return "1:SHOOT YOURSELF / 2:SHOOT THE DEALER", False

        # 撃った後に弾が尽きたら再装填
        if self.current_index >= len(self.bullets):
            self.reload()
            result_text += f"\n🔄 新しい装填：実弾{self.live}発、空砲{self.empty}発"

        return result_text, True

    def dealer_action(self):
        if self.current_index >= len(self.bullets):
            self.reload()

        bullet = self.bul


    # --- 成績処理 ---
    if msg == "成績":
        def build_result_text(history, title):
            count = len(history)
            correct = sum(history)
            if count == 0:
                return f"【🤔Your Performance\n（{title}）】\nNo questions solved, but you expect a grade?"
            accuracy = correct / 100  # 常に100問換算
            rate = round(accuracy * 1000)
            if rate >= 970:
                rank = "S Rank🤩"
            elif rate >= 900:
                rank = "A Rank😎"
            elif rate >= 800:
                rank = "B Rank😤"
            elif rate >= 500:
                rank = "C Rank🫠"
            else:
                rank = "D Rank😇"
            return (
                f"【✏️Your Performance\n（{title}）】\n"
                f"✅ Score: {correct} / {count}\n"
                f"📈 Rating: {rate}\n"
                f"🏆 Grade: {rank}"
            )

        h1 = user_histories.get(user_id + "_1_1000", [])
        h2 = user_histories.get(user_id + "_1000_1935", [])
        result_text = build_result_text(h1, "1-1000") + "\n\n" + build_result_text(h2, "1000-1935")
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=result_text))
        return

    # --- 出題処理 ---
    if msg == "1-1000":
        q = random.choice(questions_1_1000)
        user_states[user_id] = ("1-1000", q["answer"])
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=q["text"]))
        return

    if msg == "1000-1935":
        q = random.choice(questions_1000_1935)
        user_states[user_id] = ("1000-1935", q["answer"])
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=q["text"]))
        return

    # --- 回答処理 ---
    if user_id in user_states:
        question_range, correct_answer = user_states[user_id]
        is_correct = (msg == correct_answer.lower())

        key = user_id + ("_1_1000" if question_range == "1-1000" else "_1000_1935")
        history = user_histories.get(key, [])
        history.append(1 if is_correct else 0)
        if len(history) > 100:
            history.pop(0)
        user_histories[key] = history

        feedback = (
            "Correct answer✅\n\nNext：" if is_correct else f"Incorrect❌ The correct answer is 「{correct_answer}」.\nNext："
        )

        if question_range == "1-1000":
            q = random.choice(questions_1_1000)
        else:
            q = random.choice(questions_1000_1935)
        user_states[user_id] = (question_range, q["answer"])

        line_bot_api.reply_message(
            event.reply_token,
            messages=[
                TextSendMessage(text=feedback),
                TextSendMessage(text=q["text"])
            ]
        )
    else:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="Press button 1-1000 or 1000-1935!")
        )

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port)

