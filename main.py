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

user_states = {}        # 出題中のユーザーと正解
user_histories = {}     # 出題範囲ごとの正誤履歴（最大100件）
active_games = {}       # ゲーム進行中のユーザーと状態

# --- 出題リスト ---
questions_1_1000 = [
    {"text": "001 I ___ with the idea that students should not be given too much homework.\n生徒に宿題を与えすぎるべきではないという考えに賛成です.", "answer": "agree"}
]

questions_1000_1935 = [
    {"text": "1001 The ___ made a critical discovery in the lab.\nその科学者は研究室で重大な発見をした。", "answer": "scientist"}
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
    msg = event.message.text.strip().lower()

    # --- ゲーム処理 ---
    if msg == "game":
        active_games[user_id] = {"phase": "choose"}
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="BackShot Roulette\nChoose:\n1: Shoot yourself\n2: Shoot the dealer")
        )
        return

    # --- ゲーム中の選択処理 ---
    if user_id in active_games:
        if msg not in ["1", "2"]:
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="1 か 2 を選んでください。")
            )
            return

        player_choice = msg
        chamber = [0] * 5 + [1]
        random.shuffle(chamber)
        bullet = chamber[0]

        if player_choice == "1":
            if bullet == 1:
                result = "💥 You shot yourself... Game Over."
            else:
                result = "😮 Click! You survived. The dealer shoots next..."
        else:
            if bullet == 1:
                result = "🔫 Bang! You eliminated the dealer. You win!"
            else:
                result = "😓 Click! The dealer survived. Your turn next..."

        del active_games[user_id]
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=result)
        )
        return

    # --- 成績処理 ---
    if msg == "成績":
        if user_id in active_games:
            del active_games[user_id]
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="🎮ゲームを強制終了しました。成績を表示します。")
            )
            return

        def build_result_text(history, title):
            count = len(history)
            correct = sum(history)
            if count == 0:
                return f"【🤔Your Performance\n（{title}）】\nNo questions solved, but you expect a grade?"
            accuracy = correct / 100
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
        if user_id in active_games:
            del active_games[user_id]
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="🎮ゲームを強制終了しました。問題を出題します。")
            )
            return

        q = random.choice(questions_1_1000)
        user_states[user_id] = ("1-1000", q["answer"])
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=q["text"]))
        return

    if msg == "1000-1935":
        if user_id in active_games:
            del active_games[user_id]
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="🎮ゲームを強制終了しました。問題を出題します。")
            )
            return

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

        # 次の問題（同じ範囲から）
        q = random.choice(questions_1_1000 if question_range == "1-1000" else questions_1000_1935)
        user_states[user_id] = (question_range, q["answer"])

        line_bot_api.reply_message(
            event.reply_token,
            messages=[
                TextSendMessage(text=feedback),
                TextSendMessage(text=q["text"])
            ]
        )
        return

    # --- ゲーム中以外で "1" や "2" を送っても反応しないように ---
    if msg in ["1", "2"]:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="まず「game」と送ってゲームを開始して下さい。")
        )
        return

    # --- 未対応コマンド ---
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text="Press button 1-1000 or 1000-1935!")
    )

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port)

