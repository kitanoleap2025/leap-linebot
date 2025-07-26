from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.models import MessageEvent, TextMessage, TextSendMessage
from linebot.exceptions import InvalidSignatureError
import os
import random
import threading
from dotenv import load_dotenv
from collections import defaultdict, deque
import firebase_admin
from firebase_admin import credentials, firestore

load_dotenv()
app = Flask(__name__)

line_bot_api = LineBotApi(os.getenv("LINE_CHANNEL_ACCESS_TOKEN"))
handler = WebhookHandler(os.getenv("LINE_CHANNEL_SECRET"))

# Firebase Admin SDK初期化
if not firebase_admin._apps:
    cred = credentials.Certificate("path/to/your/firebase-adminsdk.json")  # ←Firebase管理画面で取得したJSONパスに置き換えて
    firebase_admin.initialize_app(cred)
db = firestore.client()

user_states = {}  # user_id: (range_str, correct_answer)
user_scores = defaultdict(dict)  # user_id: {word: score}
user_stats = defaultdict(lambda: {"correct": 0, "total": 0})
user_recent_questions = defaultdict(lambda: deque(maxlen=10))

# --- Firestore関連関数 ---
def load_user_data(user_id):
    doc_ref = db.collection("users").document(user_id)
    doc = doc_ref.get()
    if doc.exists:
        data = doc.to_dict()
        user_scores[user_id] = defaultdict(int, data.get("scores", {}))
        user_stats[user_id] = data.get("stats", {"correct": 0, "total": 0})
        recent_list = data.get("recent", [])
        user_recent_questions[user_id] = deque(recent_list, maxlen=10)
    else:
        user_scores[user_id] = defaultdict(int)
        user_stats[user_id] = {"correct": 0, "total": 0}
        user_recent_questions[user_id] = deque(maxlen=10)

def save_user_data(user_id):
    data = {
        "scores": dict(user_scores[user_id]),
        "stats": user_stats[user_id],
        "recent": list(user_recent_questions[user_id]),
    }
    doc_ref = db.collection("users").document(user_id)
    doc_ref.set(data)

def async_save_user_data(user_id):
    threading.Thread(target=save_user_data, args=(user_id,), daemon=True).start()

# --- 問題リスト（簡略版） ---
questions_1_1000 = [
    {"text": "001 I ___ with the idea that students should not be given too much homework.\n生徒に宿題を与えすぎるべきではないという考えに賛成です.",
     "answer": "agree"}
]
questions_1001_1935 = [
    {"text": "1001 The ___ made a critical discovery in the lab.\nその科学者は研究室で重大な発見をした。",
     "answer": "scientist"},
    {"text": "ooo\nた。",
     "answer": "sist"}
]

# --- ユーティリティ関数 ---
def get_rank(score):
    return {0: "D", 1: "C", 2: "B", 3: "A", 4: "S"}.get(score, "D")

def score_to_weight(score):
    return {0: 16, 1: 8, 2: 4, 3: 2, 4: 1}.get(score, 5)

def build_result_text(user_id):
    text = ""
    for title, questions in [("1-1000", questions_1_1000), ("1001-1935", questions_1001_1935)]:
        scores = user_scores.get(user_id, {})
        relevant_answers = [q["answer"] for q in questions]
        total_score = sum(scores.get(ans, 0) for ans in relevant_answers)
        count = len(relevant_answers)

        stat = user_stats.get(user_id, {})
        correct = stat.get("correct", 0)
        total = stat.get("total", 0)

        filtered_correct = sum(1 for ans in relevant_answers if scores.get(ans, 0) > 0)
        filtered_total = sum(1 for ans in relevant_answers if ans in scores)

        if filtered_total == 0:
            text += f"📝Performance({title}）\nNo data yet.\n\n"
            continue

        avg_score = round(total_score / count, 2)
        rate = round((total_score / count) * 2500)
        if rate >= 9900:
            rank = "S🤯"
        elif rate >= 7500:
            rank = "A🤩"
        elif rate >= 5000:
            rank = "B😎"
        elif rate >= 2500:
            rank = "C😀"
        else:
            rank = "D🫠"

        text += (
            f"Performance（{title})\n"
            f"✅正解数/出題数\n{filtered_correct}/{filtered_total}\n"
            f"📈Rating(max10000)\n{rate}\n"
            f"🏅Grade\n{rank}RANK\n\n"
        )
    return text.strip()

def build_grasp_text(user_id):
    scores = user_scores.get(user_id, {})
    rank_counts = {"S": 0, "A": 0, "B": 0, "C": 0, "D": 0}
    all_answers = [q["answer"] for q in questions_1_1000 + questions_1001_1935]

    for word in all_answers:
        score = scores.get(word, 0)
        rank_counts[get_rank(score)] += 1

    text = "【単語把握度】\n"
    for rank in ["S", "A", "B", "C", "D"]:
        text += f"S-D 覚えている-覚えていない\n{rank}ランク: {rank_counts[rank]}語\n"
    return text

def choose_weighted_question(user_id, questions):
    scores = user_scores.get(user_id, {})
    recent = user_recent_questions[user_id]

    candidates = []
    weights = []
    for q in questions:
        if q["answer"] in recent:
            continue
        weight = score_to_weight(scores.get(q["answer"], 0))
        candidates.append(q)
        weights.append(weight)

    if not candidates:
        user_recent_questions[user_id].clear()
        for q in questions:
            weight = score_to_weight(scores.get(q["answer"], 0))
            candidates.append(q)
            weights.append(weight)

    chosen = random.choices(candidates, weights=weights, k=1)[0]
    user_recent_questions[user_id].append(chosen["answer"])
    return chosen

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

    if user_id not in user_scores:
        load_user_data(user_id)

    if msg in ["1-1000", "1001-1935"]:
        if msg == "1-1000":
            q = choose_weighted_question(user_id, questions_1_1000)
        else:
            q = choose_weighted_question(user_id, questions_1001_1935)
        user_states[user_id] = (msg, q["answer"])
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=q["text"]))
        return

    if msg == "成績":
        text = build_result_text(user_id)
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=text))
        return

    if msg == "把握度":
        text = build_grasp_text(user_id)
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=text))
        return

    if user_id in user_states:
        range_str, correct_answer = user_states[user_id]
        is_correct = (msg.lower() == correct_answer.lower())

        score = user_scores[user_id].get(correct_answer, 0)
        if is_correct:
            user_scores[user_id][correct_answer] = min(4, score + 1)
            user_stats[user_id]["correct"] += 1
        else:
            user_scores[user_id][correct_answer] = max(0, score - 1)
        user_stats[user_id]["total"] += 1

        async_save_user_data(user_id)

        feedback = (
            "Correct✅\n\nNext:" if is_correct else f"Wrong❌\nAnswer: {correct_answer}\n\nNext:"
        )

        questions = questions_1_1000 if range_str == "1-1000" else questions_1001_1935
        next_q = choose_weighted_question(user_id, questions)
        user_states[user_id] = (range_str, next_q["answer"])

        line_bot_api.reply_message(
            event.reply_token,
            messages=[
                TextSendMessage(text=feedback),
                TextSendMessage(text=next_q["text"])
            ]
        )
        return

    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text="1-1000 または 1001-1935 を押してね。")
    )

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port)
