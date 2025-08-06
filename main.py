import os
import random
import json
import threading
import logging
from collections import defaultdict, deque
from typing import Dict, Tuple, List

from flask import Flask, request, abort
from dotenv import load_dotenv

import firebase_admin
from firebase_admin import credentials, firestore

from linebot import LineBotApi, WebhookHandler
from linebot.models import MessageEvent, TextMessage, TextSendMessage
from linebot.exceptions import InvalidSignatureError

load_dotenv()

app = Flask(__name__)

# --- Firebase初期化 ---
cred_json = os.getenv("FIREBASE_CREDENTIALS")
cred_dict = json.loads(cred_json)
cred_dict["private_key"] = cred_dict["private_key"].replace("\\n", "\n")
cred = credentials.Certificate(cred_dict)
firebase_admin.initialize_app(cred)
db = firestore.client()

# --- LINE Bot API ---
line_bot_api = LineBotApi(os.getenv("LINE_CHANNEL_ACCESS_TOKEN"))
handler = WebhookHandler(os.getenv("LINE_CHANNEL_SECRET"))

# --- ロギング設定 ---
logging.basicConfig(level=logging.INFO)

# --- グローバル変数 ---
user_states: Dict[str, Tuple[str, str]] = {}  # user_id: (range_str, correct_answer)
user_scores: Dict[str, Dict[str, int]] = defaultdict(dict)
user_stats: Dict[str, Dict[str, Dict[str, int]]] = defaultdict(lambda: {
    "1-1000": {"correct": 0, "total": 0},
    "1001-1935": {"correct": 0, "total": 0}
})
user_recent_questions: Dict[str, deque] = defaultdict(lambda: deque(maxlen=10))
user_answer_counts: Dict[str, int] = defaultdict(int)
user_names: Dict[str, str] = {}

DEFAULT_NAME = "名無し"

SAVE_LOCK = threading.Lock()  # Firestore同時保存抑制用ロック


# --- ユーザーデータ操作 ---
def load_user_data(user_id: str) -> None:
    try:
        doc = db.collection("users").document(user_id).get()
        if doc.exists:
            data = doc.to_dict()
            user_scores[user_id] = defaultdict(int, data.get("scores", {}))

            raw_stats = data.get("stats", {})
            if "1-1000" in raw_stats and "1001-1935" in raw_stats:
                user_stats[user_id] = raw_stats
            else:
                user_stats[user_id] = {
                    "1-1000": {"correct": raw_stats.get("correct", 0), "total": raw_stats.get("total", 0)},
                    "1001-1935": {"correct": 0, "total": 0}
                }

            recent_list = data.get("recent", [])
            user_recent_questions[user_id] = deque(recent_list, maxlen=10)

            user_names[user_id] = data.get("name", DEFAULT_NAME)
            logging.info(f"Loaded user data for {user_id}: name={user_names[user_id]}")
        else:
            user_names[user_id] = DEFAULT_NAME
            logging.info(f"New user {user_id} set with default name.")
    except Exception as e:
        logging.error(f"Error loading user data for {user_id}: {e}")
        user_names[user_id] = DEFAULT_NAME


def save_user_data(user_id: str) -> None:
    data = {
        "scores": dict(user_scores[user_id]),
        "stats": user_stats[user_id],
        "recent": list(user_recent_questions[user_id]),
        "name": user_names.get(user_id, DEFAULT_NAME)
    }
    try:
        with SAVE_LOCK:
            db.collection("users").document(user_id).set(data)
            logging.info(f"Saved user data for {user_id}")
    except Exception as e:
        logging.error(f"Error saving user data for {user_id}: {e}")


def async_save_user_data(user_id: str) -> None:
    threading.Thread(target=save_user_data, args=(user_id,), daemon=True).start()


# --- 質問データ ---
questions_1_1000 = [
    {"text": "001 I ___ with the idea that students should not be given too much homework.\n生徒に宿題を与えすぎるべきではないという考えに賛成です.",
     "answer": "agree"}
]
questions_1001_1935 = [
    {"text": "1001 The ___ made a critical discovery in the lab.\nその科学者は研究室で重大な発見をした。",
     "answer": "scientist"},
    {"text": "1247 Don’t count your chickens before they ___.\n卵がかえる前にヒヨコを数えるな",
     "answer": "hatch"},
]

# --- 定数 ---
RANK_THRESHOLDS = [
    (9900, "S🤯"),
    (9000, "A+🤩"),
    (8000, "A😎"),
    (7000, "A-😍"),
    (6000, "B+🤑"),
    (5000, "B🤠"),
    (4000, "B-😇"),
    (3000, "C+😤"),
    (2000, "C🤫"),
    (1000, "C-😶‍🌫️"),
    (0, "D🫠"),
]

TRIVIA_MESSAGES = [
    "🎅低浮上サンタ\nあなたが今電車の中なら、外の景色を見てみて下さい。",
    "🎅低浮上サンタ\n最高のSランクに到達するためには、少なくとも2000問解く必要があります。",
    "🎅低浮上サンタ\n木々は栄養を分け合ったり、病気の木に助け舟を出したりします。",
    "🎅低浮上サンタ\n「ゆっくり行くものは、遠くまで行ける」ということわざがあります。",
    "🎅低浮上サンタ\nWBGTをチェックして、熱中症に気を付けて下さい。",
    "🎅低浮上サンタ\nすべての単語には5段階の把握度が付けられています。",
    "🎅低浮上サンタ\n1回スカイダビングしたいのならばパラシュートは不要ですが、2回なら必要です。",
    "🎅低浮上サンタ\nサンタはいないです。",
    "🎅低浮上サンタ\n聖書は世界的なベストセラーフィクション作品です。",
    "🎅低浮上サンタ\nアメリカはルークを失い、イギリスはクイーンを失いました。",
    "🎅低浮上サンタ\n私は10回に1回出てきます。",
]

# --- ヘルパー関数 ---
def get_rank(score: int) -> str:
    return {0: "D", 1: "C", 2: "B", 3: "A", 4: "S"}.get(score, "D")


def score_to_weight(score: int) -> int:
    return {0: 16, 1: 8, 2: 4, 3: 2, 4: 1}.get(score, 5)


def calculate_rate(scores: Dict[str, int], questions: List[Dict[str, str]]) -> int:
    count = len(questions)
    if count == 0:
        return 0
    total = sum(scores.get(q["answer"], 0) for q in questions)
    return round((total / count) * 2500)


def determine_rank(rate: int) -> str:
    for threshold, rank in RANK_THRESHOLDS:
        if rate >= threshold:
            return rank
    return "D🫠"


# --- ビルド関数 ---
def build_result_text(user_id: str) -> str:
    name = user_names.get(user_id, DEFAULT_NAME)
    text = f"{name}\n\n"
    for title, questions in [("1-1000", questions_1_1000), ("1001-1935", questions_1001_1935)]:
        scores = user_scores.get(user_id, {})
        relevant_answers = [q["answer"] for q in questions]
        total_score = sum(scores.get(ans, 0) for ans in relevant_answers)
        count = len(relevant_answers)

        stat = user_stats.get(user_id, {}).get(title, {"correct": 0, "total": 0})
        filtered_correct = stat["correct"]
        filtered_total = stat["total"]

        if filtered_total == 0:
            text += f"{title}\nNo data yet.\n\n"
            continue

        rate = calculate_rate(scores, questions)
        rank = determine_rank(rate)

        text += (
            f"[{title}]\n"
            f"Correct:{filtered_correct}/Total:{filtered_total}\n"
            f"Rating:{rate}\n"
            f"Rank:{rank}\n\n"
        )

    rate1 = calculate_rate(user_scores.get(user_id, {}), questions_1_1000)
    rate2 = calculate_rate(user_scores.get(user_id, {}), questions_1001_1935)
    total_rate = round((rate1 + rate2) / 2)

    text += "Total Rating\n"
    text += f"{total_rate}\n\n"
    text += "名前変更は「@(新しい名前)」で送信してください。"
    return text.strip()


def build_grasp_text(user_id: str) -> str:
    scores = user_scores.get(user_id, {})
    rank_counts = {"S": 0, "A": 0, "B": 0, "C": 0, "D": 0}
    all_answers = [q["answer"] for q in questions_1_1000 + questions_1001_1935]
    for word in all_answers:
        score = scores.get(word, 0)
        rank_counts[get_rank(score)] += 1
    text = "【単語把握度】\nS-D 覚えている-覚えていない\n"
    for rank in ["S", "A", "B", "C", "D"]:
        text += f"{rank}ランク: {rank_counts[rank]}語\n"
    return text


def choose_weighted_question(user_id: str, questions: List[Dict[str, str]]) -> Dict[str, str]:
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


def build_ranking_text() -> str:
    docs = db.collection("users").stream()
    ranking = []
    for doc in docs:
        data = doc.to_dict()
        name = data.get("name", DEFAULT_NAME)
        scores = data.get("scores", {})
        rate1 = calculate_rate(scores, questions_1_1000)
        rate2 = calculate_rate(scores, questions_1001_1935)
        total_rate = round((rate1 + rate2) / 2)
        ranking.append((name, total_rate))
    ranking.sort(key=lambda x: x[1], reverse=True)

    text = "Rating Ranking\n"
    for i, (name, rate) in enumerate(ranking[:10], 1):
        text += f"{i}. {name} - {rate}\n"
    if not ranking:
        text += "まだランキングデータがありません。"
    return text


# --- 各コマンド処理関数 ---
def handle_name_change(event, user_id: str, msg: str) -> None:
    new_name = msg[1:].strip()
    if not new_name:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="名前が空白です。もう一度「@(新しい名前)」で送ってください。")
        )
        return

    if len(new_name) > 20:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="名前は20文字以内でお願いします。")
        )
        return

    user_names[user_id] = new_name
    async_save_user_data(user_id)
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=f"名前を「{new_name}」に変更しました！")
    )


def handle_ranking(event) -> None:
    text = build_ranking_text()
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=text))


def handle_question(event, user_id: str, range_str: str) -> None:
    questions = questions_1_1000 if range_str == "1-1000" else questions_1001_1935
    q = choose_weighted_question(user_id, questions)
    user_states[user_id] = (range_str, q["answer"])
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=q["text"]))


def handle_result(event, user_id: str) -> None:
    text = build_result_text(user_id)
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=text))


def handle_grasp(event, user_id: str) -> None:
    text = build_grasp_text(user_id)
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=text))


def handle_answer(event, user_id: str, msg: str) -> None:
    if user_id not in user_states:
        # 質問状態がないなら案内メッセージ
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="1-1000 または 1001-1935 を押してね。")
        )
        return

    range_str, correct_answer = user_states[user_id]
    is_correct = (msg.lower() == correct_answer.lower())
    score = user_scores[user_id].get(correct_answer, 0)

    if is_correct:
        user_scores[user_id][correct_answer] = min(4, score + 2)
        user_stats[user_id][range_str]["correct"] += 1
    else:
        user_scores[user_id][correct_answer] = max(0, score - 1)

    user_stats[user_id][range_str]["total"] += 1
    async_save_user_data(user_id)

    user_answer_counts[user_id] += 1

    feedback = (
        "Correct✅\n\nNext:" if is_correct else f"Wrong❌\nAnswer: {correct_answer}\n\nNext:"
    )

    questions = questions_1_1000 if range_str == "1-1000" else questions_1001_1935
    next_q = choose_weighted_question(user_id, questions)
    user_states[user_id] = (range_str, next_q["answer"])

    if user_answer_counts[user_id] % 10 == 0:
        trivia = random.choice(TRIVIA_MESSAGES)
        line_bot_api.reply_message(
            event.reply_token,
            messages=[
                TextSendMessage(text=feedback),
                TextSendMessage(text=trivia),
                TextSendMessage(text=next_q["text"])
            ],
        )
    else:
        line_bot_api.reply_message(
            event.reply_token,
            messages=[
                TextSendMessage(text=feedback),
                TextSendMessage(text=next_q["text"])
            ],
        )


# --- Flaskのルート ---
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
    if user_id not in user_answer_counts:
        user_answer_counts[user_id] = 0

    # 名前変更コマンド @(新しい名前)
    if msg.startswith("@") and len(msg) > 1:
        handle_name_change(event, user_id, msg)
        return

    if msg == "ランキング":
        handle_ranking(event)
        return

    if msg in ["1-1000", "1001-1935"]:
        handle_question(event, user_id, msg)
        return

    if msg == "成績":
        handle_result(event, user_id)
        return

    if msg == "把握度":
        handle_grasp(event, user_id)
        return

    handle_answer(event, user_id, msg)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port)
