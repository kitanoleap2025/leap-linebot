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
active_games = {}       # 現在ミニゲーム中のユーザー

# --- 出題リスト ---
questions_1_1000 = [
    {"text": "001 I ___ with the idea that students should not be given too much homework.\n生徒に宿題を与えすぎるべきではないという考えに賛成です.", "answer": "agree"}
]

questions_1000_1935 = [
    {"text": "1001 The ___ made a critical discovery in the lab.\nその科学者は研究室で重大な発見をした。", "answer": "scientist"}
]

# --- ゲームクラス定義 ---
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_id = event.source.user_id
    msg = event.message.text.strip().lower()

    # === ゲーム中の場合の処理 ===
    if user_id in active_games:
        # 強制終了コマンド例
        if msg in ["1-1000", "1000-1935", "成績"]:
            del active_games[user_id]
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="ゲームは強制終了されました。")
            )
            return

        game = active_games[user_id]
        result = ""

        if game.turn == "player":
            if msg == "1":
                player_result, proceed = game.player_action("1")
            elif msg == "2":
                player_result, proceed = game.player_action("2")
            else:
                player_result, proceed = "1 か 2 を入力してください。", False

            result += player_result

            # プレイヤーのターン後、ゲームが続いていればディーラーのターンへ
            if not game.is_game_over() and game.turn == "dealer":
                dealer_result, _ = game.dealer_action()
                result += f"\n\nディーラーの行動: {dealer_result}"

        else:
            dealer_result, _ = game.dealer_action()
            result = f"ディーラーの行動: {dealer_result}"

        # 勝敗判定
        end = game.is_game_over()
        if end:
            winner = "あなたの勝ち！🎉" if end == "player" else "ディーラーの勝ち…😵"
            del active_games[user_id]
            reply = f"{result}\n\n{winner}"
        else:
            reply = f"{result}\n\n{game.get_status()}"

        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))
        return

    # === ゲーム開始 ===
    if msg == "game":
        game = ShotgunRussianRoulette()
        active_games[user_id] = game
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(
                text=(
                    "🎲 Russian Roulette\n"
                    f"新しい装填：実弾{game.live}発、空砲{game.empty}発\n"
                    + game.get_status()
                    + "\n1: 自分を撃つ / 2: 相手を撃つ"
                )
            )
        )
        return


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
