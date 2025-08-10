from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.models import MessageEvent, TextMessage, TextSendMessage, FlexSendMessage
from linebot.exceptions import InvalidSignatureError
import os
import random
import json
import threading
from dotenv import load_dotenv
from collections import defaultdict, deque
import firebase_admin
from firebase_admin import credentials, firestore

load_dotenv()
app = Flask(__name__)

cred_json = os.getenv("FIREBASE_CREDENTIALS")
cred_dict = json.loads(cred_json)
cred_dict["private_key"] = cred_dict["private_key"].replace("\\n", "\n")
cred = credentials.Certificate(cred_dict)
firebase_admin.initialize_app(cred)
db = firestore.client()

line_bot_api = LineBotApi(os.getenv("LINE_CHANNEL_ACCESS_TOKEN"))
handler = WebhookHandler(os.getenv("LINE_CHANNEL_SECRET"))

user_states = {}  # user_id: (range_str, correct_answer)
user_scores = defaultdict(dict)
user_recent_questions = defaultdict(lambda: deque(maxlen=10))
user_answer_counts = defaultdict(int)
user_names = {}  # user_id: name

DEFAULT_NAME = "名無し"

def load_user_data(user_id):
    try:
        doc = db.collection("users").document(user_id).get()
        if doc.exists:
            data = doc.to_dict()
            user_scores[user_id] = defaultdict(int, data.get("scores", {}))

            recent_list = data.get("recent", [])
            user_recent_questions[user_id] = deque(recent_list, maxlen=10)

            user_names[user_id] = data.get("name", DEFAULT_NAME)
        else:
            user_names[user_id] = DEFAULT_NAME
    except Exception as e:
        print(f"Error loading user data for {user_id}: {e}")
        user_names[user_id] = DEFAULT_NAME

def save_user_data(user_id):
    data = {
        "scores": dict(user_scores[user_id]),
        "recent": list(user_recent_questions[user_id]),
        "name": user_names.get(user_id, DEFAULT_NAME)
    }
    try:
        db.collection("users").document(user_id).set(data)
    except Exception as e:
        print(f"Error saving user data for {user_id}: {e}")

def async_save_user_data(user_id):
    threading.Thread(target=save_user_data, args=(user_id,), daemon=True).start()

questions_1_1000 = [
    {"text": "001 I a___ with the idea that students should not be given too much homework.\n生徒に宿題を与えすぎるべきではないという考えに賛成です.",
     "answer": "agree"},
 
]
questions_1001_1935 = [
    {"text": "1001 The ___ made a critical discovery in the lab.\nその科学者は研究室で重大な発見をした。",
     "answer": "scientist"},
    {"text": "1247 Don’t count your chickens before they ___.\n卵がかえる前にヒヨコを数えるな",
     "answer": "hatch"},
    {"text": "1054 The c___ of Hammurabi is one of the oldest laws.\nハンムラビ法典(規定)は最古の法律の一つ。",
     "answer": "code"},
]

def get_rank(score):
    return {0: "D", 1: "C", 2: "B", 3: "A", 4: "S"}.get(score, "D")

def score_to_weight(score):
    return {0: 16, 1: 8, 2: 4, 3: 2, 4: 1}.get(score, 5)

def build_result_text(user_id):
    name = user_names.get(user_id, DEFAULT_NAME)
    text = f"{name}\n\n"
    for title, questions in [("1-1000", questions_1_1000), ("1001-1935", questions_1001_1935)]:
        scores = user_scores.get(user_id, {})
        relevant_answers = [q["answer"] for q in questions]
        total_score = sum(scores.get(ans, 0) for ans in relevant_answers)
        count = len(relevant_answers)

        rate = round((total_score / count) * 2500)
        if rate >= 9900:
            rank = "S🤯"      
        elif rate >= 9000:
            rank = "A+🤩"     
        elif rate >= 8000:
            rank = "A😎"
        elif rate >= 7000:
            rank = "A-😍"      
        elif rate >= 6000:
            rank = "B+🤑"      
        elif rate >= 5000:
            rank = "B🤠"      
        elif rate >= 4000:
            rank = "B-😇"      
        elif rate >= 3000:
            rank = "C+😤"      
        elif rate >= 2000:
            rank = "C🤫"    
        elif rate >= 1000:
            rank = "C-😶‍🌫️"    
        else:
            rank = "D🫠"       

        text += (
            f"[{title}]\n"
            f"Rating:{rate}\n"
            f"Rank:{rank}\n\n"
        )
    rate1 = 0
    rate2 = 0
    c1 = len(questions_1_1000)
    c2 = len(questions_1001_1935)
    if c1 > 0:
        scores1 = user_scores.get(user_id, {})
        total_score1 = sum(scores1.get(q["answer"], 0) for q in questions_1_1000)
        rate1 = round((total_score1 / c1) * 2500)
    if c2 > 0:
        scores2 = user_scores.get(user_id, {})
        total_score2 = sum(scores2.get(q["answer"], 0) for q in questions_1001_1935)
        rate2 = round((total_score2 / c2) * 2500)
    total_rate = round((rate1 + rate2) / 2)
    text += "Total Rating\n"
    text += f"{total_rate}\n\n"
    text += "名前変更は「@(新しい名前)」で送信してください。"
    return text.strip()

def build_grasp_text(user_id):
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

trivia_messages = [
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

def build_ranking_flex(user_id=None):
    docs = db.collection("users").stream()
    ranking = []
    for doc in docs:
        data = doc.to_dict()
        name = data.get("name", DEFAULT_NAME)
        scores = data.get("scores", {})

        total_score1 = sum(scores.get(q["answer"], 0) for q in questions_1_1000)
        total_score2 = sum(scores.get(q["answer"], 0) for q in questions_1001_1935)

        c1 = len(questions_1_1000)
        c2 = len(questions_1001_1935)
        rate1 = round((total_score1 / c1) * 2500) if c1 else 0
        rate2 = round((total_score2 / c2) * 2500) if c2 else 0
        total_rate = round((rate1 + rate2) / 2)

        ranking.append((doc.id, name, total_rate))

    ranking.sort(key=lambda x: x[2], reverse=True)

    # 上位5位まで表示
    contents = []
    for i, (uid, name, rate) in enumerate(ranking[:5], 1):
        if i == 1:
            size = "lg"
            color = "#FFD700"  # 金
        elif i == 2:
            size = "md"
            color = "#C0C0C0"  # 銀
        elif i == 3:
            size = "md"
            color = "#CD7F32"  # 銅
        else:
            size = "sm"
            color = "#1DB446"  # 通常色

        contents.append({
            "type": "box",
            "layout": "baseline",
            "contents": [
                {"type": "text", "text": f"{i}位", "flex": 1, "weight": "bold", "size": size, "color": color},
                {"type": "text", "text": name, "flex": 4, "weight": "bold", "size": size},
                {"type": "text", "text": str(rate), "flex": 2, "align": "end", "size": size}
            ]
        })
        if i < 5:
            contents.append({"type": "separator", "margin": "md"})

    # 自分の順位を取得
    user_index = None
    for i, (uid, _, _) in enumerate(ranking):
        if uid == user_id:
            user_index = i
            break

    if user_index is not None:
        uid, name, rate = ranking[user_index]
        contents.append({"type": "separator", "margin": "lg"})

        if user_index < 5:
            # 5位以内 → 名前とレートのみ
            contents.append({
                "type": "box",
                "layout": "baseline",
                "contents": [
                    {"type": "text", "text": "あなた", "flex": 3, "weight": "bold"},
                    {"type": "text", "text": str(rate), "flex": 1, "align": "end"}
                ]
            })
        else:
            # 6位以降 → 名前とレート + 1つ上との差
            above_name = ranking[user_index - 1][1]
            above_rate = ranking[user_index - 1][2]
            diff = above_rate - rate

            contents.append({
                "type": "box",
                "layout": "baseline",
                "contents": [
                    {"type": "text", "text": f"{user_index+1}位 あなた", "flex": 3, "weight": "bold"},
                    {"type": "text", "text": str(rate), "flex": 1, "align": "end"}
                ]
            })
            contents.append({
                "type": "text",
                "text": f"{user_index}位の{above_name}まで {diff} レート差",
                "margin": "md",
                "size": "sm",
                "color": "#000000"
            })

    flex_message = FlexSendMessage(
        alt_text="🏆 Rating Ranking 🏆",
        contents={
            "type": "bubble",
            "body": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {"type": "text", "text": "🏆 Rating Ranking 🏆", "weight": "bold", "size": "lg", "align": "center"},
                    {"type": "separator", "margin": "md"},
                    *contents
                ]
            }
        }
    )
    return flex_message



# —————— ここからLINEイベントハンドラ部分 ——————

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get("X-Line-Signature")
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)

    return "OK"

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_id = event.source.user_id
    msg = event.message.text

    if user_id not in user_scores:
        load_user_data(user_id)

    # 名前変更コマンド
    if msg.startswith("@"):
        new_name = msg[1:].strip()
        if not new_name:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="名前が空です。"))
            return
        if len(new_name) > 10:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="名前は10文字以内で入力してください。"))
            return
        user_names[user_id] = new_name
        async_save_user_data(user_id)
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"名前を「{new_name}」に変更しました。"))
        return

    if msg == "ランキング":
        flex_msg = build_ranking_flex(user_id)
        line_bot_api.reply_message(event.reply_token, flex_msg)
        return

    if msg in ["1-1000", "1001-1935"]:
        questions = questions_1_1000 if msg == "1-1000" else questions_1001_1935
        q = choose_weighted_question(user_id, questions)
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
            user_scores[user_id][correct_answer] = min(4, score + 2)
        else:
            user_scores[user_id][correct_answer] = max(0, score - 1)

        async_save_user_data(user_id)

        user_answer_counts[user_id] += 1

        feedback = (
            "Correct✅\n\nNext:" if is_correct else f"Wrong❌\nAnswer: {correct_answer}\n\nNext:"
        )

        questions = questions_1_1000 if range_str == "1-1000" else questions_1001_1935
        next_q = choose_weighted_question(user_id, questions)
        user_states[user_id] = (range_str, next_q["answer"])

        if user_answer_counts[user_id] % 10 == 0:
            trivia = random.choice(trivia_messages)
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
        return

    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text="1-1000 または 1001-1935 を押してね。")
    )

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port)
