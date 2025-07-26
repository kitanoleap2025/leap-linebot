import os
import json
import random
import threading
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.models import MessageEvent, TextMessage, TextSendMessage
from firebase_config import db

app = Flask(__name__)
line_bot_api = LineBotApi(os.getenv("LINE_CHANNEL_ACCESS_TOKEN"))
handler = WebhookHandler(os.getenv("LINE_CHANNEL_SECRET"))

# 単語データ読み込み
with open("leap_words.json", "r", encoding="utf-8") as f:
    leap_words = json.load(f)

# 出題対象：LEAP1〜1000
LEAP_RANGE = list(range(0, 1000))

# スコア別重み（段階的減少型）
def get_weight(score):
    return {0: 16, 1: 8, 2: 4, 3: 2, 4: 1}.get(score, 16)

# Firestoreから読み込み
def load_user_data(user_id):
    doc_ref = db.collection("users").document(user_id)
    doc = doc_ref.get()
    if doc.exists:
        return doc.to_dict()
    else:
        return {
            "scores": {},
            "correct_count": 0,
            "total_count": 0,
            "recent_words": [],
            "current_word": None,
        }

# Firestoreに保存（非同期）
def save_user_data(user_id, data):
    def save():
        db.collection("users").document(user_id).set(data)
    threading.Thread(target=save).start()

# 出題処理
def select_word(user_data):
    weights = []
    candidates = []

    for i in LEAP_RANGE:
        if i in user_data.get("recent_words", []):
            continue
        score = user_data.get("scores", {}).get(str(i), 0)
        weight = get_weight(score)
        weights.append(weight)
        candidates.append(i)

    if not candidates:
        return random.choice(LEAP_RANGE)

    return random.choices(candidates, weights=weights, k=1)[0]

# 正答チェック
def check_answer(user_data, word_index, user_input):
    correct_answer = leap_words[word_index]["意味"].lower()
    is_correct = user_input.strip().lower() == correct_answer

    scores = user_data.setdefault("scores", {})
    current_score = scores.get(str(word_index), 0)

    if is_correct:
        scores[str(word_index)] = min(current_score + 1, 4)
        user_data["correct_count"] = user_data.get("correct_count", 0) + 1
    else:
        scores[str(word_index)] = max(current_score - 1, 0)

    user_data["total_count"] = user_data.get("total_count", 0) + 1
    user_data["recent_words"] = (user_data.get("recent_words", []) + [word_index])[-10:]
    return is_correct, correct_answer

# 成績表示
def generate_stats(user_data):
    scores = user_data.get("scores", {})
    total = user_data.get("total_count", 0)
    correct = user_data.get("correct_count", 0)
    percent = round(correct / total * 100, 1) if total else 0.0

    rank_counts = {i: 0 for i in range(5)}
    for score in scores.values():
        rank_counts[score] += 1

    return (
        f"📊 あなたの成績\n"
        f"正解数: {correct} / {total}（正答率: {percent}%）\n\n"
        f"🔥 LEAP把握度\n"
        f"Sランク(4): {rank_counts[4]}\n"
        f"Aランク(3): {rank_counts[3]}\n"
        f"Bランク(2): {rank_counts[2]}\n"
        f"Cランク(1): {rank_counts[1]}\n"
        f"Dランク(0): {rank_counts[0]}"
    )

@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers["X-Line-Signature"]
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except Exception as e:
        abort(400)
    return "OK"

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_id = event.source.user_id
    text = event.message.text.strip()
    user_data = load_user_data(user_id)

    if text == "1-1000":
        word_index = select_word(user_data)
        word = leap_words[word_index]["単語"]
        user_data["current_word"] = word_index
        save_user_data(user_id, user_data)
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"【問題】\n{word} の意味は？"))

    elif text == "成績":
        result = generate_stats(user_data)
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=result))

    elif user_data.get("current_word") is not None:
        word_index = user_data["current_word"]
        is_correct, correct_answer = check_answer(user_data, word_index, text)
        user_data["current_word"] = None
        save_user_data(user_id, user_data)

        if is_correct:
            reply = f"⭕️ 正解！"
        else:
            reply = f"❌ 不正解\n正解: {correct_answer}"

        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))

    else:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="「1-1000」と送って問題を始めよう！"))

if __name__ == "__main__":
    app.run()
