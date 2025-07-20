from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.models import MessageEvent, TextMessage, TextSendMessage
from linebot.exceptions import InvalidSignatureError
import os
import random
from dotenv import load_dotenv
from collections import defaultdict

load_dotenv()
app = Flask(__name__)

line_bot_api = LineBotApi(os.getenv("LINE_CHANNEL_ACCESS_TOKEN"))
handler = WebhookHandler(os.getenv("LINE_CHANNEL_SECRET"))

user_states = {}        # 出題中のユーザーと正解
user_histories = {}     # 出題範囲ごとの正誤履歴（最大100件）
user_scores = defaultdict(dict)  # user_scores[user_id][単語] = 0~4のスコア

# --- 英単語問題リスト ---
questions_1_1000 = [
    {"text": "001 I ___ with the idea that students should not be given too much homework.\n生徒に宿題を与えすぎるべきではないという考えに賛成です.", "answer": "agree"},
    # 必要に応じて追加
]

questions_1000_1935 = [
    {"text": "1001 The ___ made a critical discovery in the lab.\nその科学者は研究室で重大な発見をした。", "answer": "scientist"},
    # 必要に応じて追加
]

# --- 成績テキスト生成関数 ---
def build_result_text(user_id):
    h1 = user_histories.get(user_id + "_1_1000", [])
    h2 = user_histories.get(user_id + "_1000_1935", [])

    def score_text(history, title):
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

    return score_text(h1, "1-1000") + "\n\n" + score_text(h2, "1000-1935")

# --- Flask / LINE webhook ---
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

    # --- 把握度コマンド ---
    if msg == "把握度":
        scores = user_scores.get(user_id, {})
        if not scores:
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="まだ学習データがありません。")
            )
            return

        rank_counts = {"S(0点)": 0, "A(1点)": 0, "B(2点)": 0, "C(3点)": 0, "D(4点)": 0}
        for score in scores.values():
            if score == 0:
                rank_counts["S(0点)"] += 1
            elif score == 1:
                rank_counts["A(1点)"] += 1
            elif score == 2:
                rank_counts["B(2点)"] += 1
            elif score == 3:
                rank_counts["C(3点)"] += 1
            elif score == 4:
                rank_counts["D(4点)"] += 1

        text = "【単語把握度内訳】\n"
        for rank, count in rank_counts.items():
            text += f"{rank}: {count}語\n"

        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=text))
        return

    # --- 成績表示 ---
    if msg == "成績":
        result_text = build_result_text(user_id)
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=result_text))
        return

    # --- 英単語問題出題処理 ---
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

    # --- 英単語回答処理 ---
    if user_id in user_states:
        question_range, correct_answer = user_states[user_id]
        is_correct = (msg.lower() == correct_answer.lower())

        # 単語スコアの初期化（0〜4の範囲、初期値2）
        scores = user_scores[user_id]
        if correct_answer not in scores:
            scores[correct_answer] = 2  # 中間値スタート

        # 正解ならスコア1減少（最低0）、間違いなら1増加（最大4）
        if is_correct:
            scores[correct_answer] = max(0, scores[correct_answer] - 1)
        else:
            scores[correct_answer] = min(4, scores[correct_answer] + 1)

        user_scores[user_id] = scores  # 保存

        key = user_id + ("_1_1000" if question_range == "1-1000" else "_1000_1935")
        history = user_histories.get(key, [])
        history.append(1 if is_correct else 0)
        if len(history) > 100:
            history.pop(0)
        user_histories[key] = history

        feedback = (
            "Correct answer✅\n\nNext：" if is_correct else f"Incorrect❌ The correct answer is 「{correct_answer}」.\nNext："
        )

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

    # --- 未対応コマンドのデフォルト応答 ---
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text="Press button 1-1000 or 1000-1935!")
    )

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port)
