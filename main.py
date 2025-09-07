from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.models import MessageEvent, TextMessage, TextSendMessage, FlexSendMessage,BoxComponent, TextComponent
from linebot.exceptions import InvalidSignatureError
import os
import random
import json
import threading
from dotenv import load_dotenv
from collections import defaultdict, deque
import firebase_admin
from firebase_admin import credentials, firestore
import time
from linebot.models import QuickReply, QuickReplyButton, MessageAction


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
user_answer_start_times = {}  # 問題出題時刻を記録
user_daily_counts = defaultdict(lambda: {"date": None, "count": 1})

DEFAULT_NAME = "イキイキした毎日"

def load_user_data(user_id):
    try:
        doc = db.collection("users").document(user_id).get()
        if doc.exists:
            data = doc.to_dict()
            user_scores[user_id] = defaultdict(lambda: 1, data.get("scores", {}))

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


questions_1001_2000 = 
questions_2001_2300 = [
    {"text": "2013 Don’t count your chickens before they ___.\n卵がかえる前にヒヨコを数えるな🐣",
     "answer": "hatch",
    "meaning": "hatch	[自] ①（卵から）かえる，孵化する [他] ②（卵から）～をかえす ③（計画など）を企てる"},
    {"text": "2043 ___ the tale of the Straw Millionaire, trying to exchange a string for a Benz.\nわらしべ長者の物語を省略して,ひもをベンツと交換しようとする.",
     "answer": "Omitting",
    "meaning": "entire	[形] すべての"},
    {"text": "2131 Justice is blind, but apparently not deaf to ___.\n正義は目が見えないが、賄賂にはどうやら耳が聞こえるらしい。", 
     "answer": "bribes",
    "meaning": "entire	[形] すべての"},
   
]
#Dreams are free; reality charges you interest every day.

def get_rank(score):
    return {0: "0%", 1: "25%", 2: "50%", 3: "75%", 4: "100%"}.get(score, "25%")

def score_to_weight(score):
    return {0: 16, 1: 8, 2: 4, 3: 2, 4: 1}.get(score, 8)

def build_result_flex(user_id):
    name = user_names.get(user_id, DEFAULT_NAME)

    # 各範囲の評価計算
    parts = []
    for title, questions in [("1-1000", questions_1_1000), ("1001-2000", questions_1001_2000)]:
        scores = user_scores.get(user_id, {})
        relevant_answers = [q["answer"] for q in questions]
        total_score = sum(scores.get(ans, 1) for ans in relevant_answers)
        count = len(relevant_answers)

        rate = round((total_score / count) * 25, 3) if count else 0
        if rate >= 9000:
            rank = "S🤯"
        elif rate >= 7000:
            rank = "A🤩"
        elif rate >= 4000:
            rank = "B😎"
        elif rate >= 1000:
            rank = "C😍"
        else:
            rank = "D🫠"

        parts.append({
            "type": "box",
            "layout": "vertical",
            "margin": "md",
            "contents": [
                {"type": "text", "text": title, "weight": "bold", "size": "sm", "color": "#000000"},
                {"type": "text", "text": f"把握率: {rate} %", "size": "md", "color": "#333333"},
                {"type": "text", "text": f"{rank}", "size": "md", "color": "#333333"},
            ],
        })

    # ランク別単語数・割合計算
    scores = user_scores.get(user_id, {})
    rank_counts = {"100%": 0, "75%": 0, "50%": 0, "25%": 0, "0%": 0}
    all_answers = [q["answer"] for q in questions_1_1000 + questions_1001_2000]
    for word in all_answers:
        score = scores.get(word, 1)
        rank_counts[get_rank(score)] += 1

    total_words = sum(rank_counts.values())
    rank_ratios = {rank: rank_counts[rank]/total_words for rank in rank_counts}

    # ランク別割合グラフ
    graph_components = []
    max_width = 200  # 最大横幅 px
    for rank in ["100%", "75%", "50%", "25%", "0%"]:
        width_percent = int(rank_ratios[rank]*100)  # 0〜100%
        color_map = {"100%": "#c0c0c0", "75%": "#b22222", "50%": "#4682b4", "25%": "#ffd700", "0%": "#000000"}
        width_px = max(5, int(rank_ratios[rank] * max_width)) 
        graph_components.append({
            "type": "box",
            "layout": "horizontal",
            "contents": [
                # 左にランク・語数を縦にまとめる
                {
                    "type": "box",
                    "layout": "vertical",
                    "contents": [
                        {"type": "text", "text": rank, "size": "sm"},
                        {"type": "text", "text": f"{rank_counts[rank]}語", "size": "sm"}
                    ],
                    "width": "70px"  # 固定幅で棒の開始位置を揃える
                },
                # 棒グラフ
                {
                    "type": "box",
                    "layout": "vertical",
                    "contents": [],
                    "backgroundColor": color_map[rank],
                    "width": f"{width_px}px",  # ← ここを flex から width に変更
                    "height": "12px"
                }
            ],
            "margin": "xs"
        })


    # 合計レート計算
    c1 = len(questions_1_1000)
    c2 = len(questions_1001_2000)
    rate1 = round((sum(user_scores.get(user_id, {}).get(q["answer"], 1) for q in questions_1_1000) / c1) * 2500) if c1 else 0
    rate2 = round((sum(user_scores.get(user_id, {}).get(q["answer"], 1) for q in questions_1001_2000) / c2) * 2500) if c2 else 0
    total_rate = round((rate1 + rate2) / 2)

    flex_message = FlexSendMessage(
        alt_text=f"{name}",
        contents={
            "type": "bubble",
            "body": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {"type": "text", "text": f"{name}", "weight": "bold", "size": "xl", "color": "#000000", "align": "center"},
                    *parts,
                    {"type": "text","text": f"Total Rating: {total_rate}","weight": "bold","size": "lg","color": "#000000","margin": "md"},
                    {"type": "separator",  "margin": "md"},
                    *graph_components,  
                    {"type": "separator",  "margin": "md"},
                    {"type": "text","text": "名前変更は「@(新しい名前)」で送信してください。","size": "sm","color": "#666666","margin": "lg","wrap": True}
                ]
            }
        }
    )
    return flex_message

#総合レート更新
def update_total_rate(user_id):
    scores = user_scores.get(user_id, {})
    total_score1 = sum(scores.get(q["answer"], 0) for q in questions_1_1000)
    total_score2 = sum(scores.get(q["answer"], 0) for q in questions_1001_2000)

    c1 = len(questions_1_1000)
    c2 = len(questions_1001_2000)

    rate1 = round((total_score1 / c1) * 2500) if c1 else 0
    rate2 = round((total_score2 / c2) * 2500) if c2 else 0

    total_rate = round((rate1 + rate2) / 2)

    try:
        db.collection("users").document(user_id).update({"total_rate": total_rate})
    except Exception as e:
        print(f"Error updating total_rate for {user_id}: {e}")

    return total_rate

def periodic_save():
    while True:
        time.sleep(60)  # 1分ごと
        for user_id in list(user_scores.keys()):
            save_user_data(user_id)

# スレッド起動
threading.Thread(target=periodic_save, daemon=True).start()

#FEEDBACK　flex
def build_feedback_flex(user_id, is_correct, score, elapsed, correct_answer=None, label=None, meaning=None):
    body_contents = []

    if is_correct:
        color_map = {"!!Brilliant":"#40e0d0", "!Great":"#4682b4", "✓Correct":"#00ff00"}
        color = color_map.get(label, "#000000")
        body_contents.append({
            "type": "text",
            "text": label or "✓Correct",
            "weight": "bold",
            "size": "xl",
            "color": color,
            "align": "center"
        })
    else:
        body_contents.append({
            "type": "text",
            "text": f"Wrong❌\nAnswer: {correct_answer}",
            "size": "md",
            "color": "#ff4500",
            "wrap": True,
            "margin": "md"
        })

    if meaning:
        body_contents.append({
            "type": "text",
            "text": f"{meaning}",
            "size": "md",
            "color": "#000000",
            "margin": "md",
            "wrap": True
        })

    # ← ここで「今日の解答数」を追加
    count_today = user_daily_counts[user_id]["count"]
    body_contents.append({
        "type": "text",
        "text": f"🔥{count_today}",
        "size": "sm",
        "color": "#333333",
        "margin": "md"
    })

    return FlexSendMessage(
        alt_text="回答フィードバック",
        contents={
            "type": "bubble",
            "body": {
                "type": "box",
                "layout": "vertical",
                "contents": body_contents
            }
        }
    )


#1001-2000を4択
def send_question(user_id, range_str):
    if range_str == "1-1000":
        questions = questions_1_1000
    else:
        questions = questions_1001_2000

    # 4択問題 QuickReply版
    q, _ = choose_multiple_choice_question(user_id, questions)
    user_states[user_id] = (range_str, q["answer"])
    user_answer_start_times[user_id] = time.time()

    correct_answer = q["answer"]
    other_answers = [item["answer"] for item in questions if item["answer"] != correct_answer]
    wrong_choices = random.sample(other_answers, k=min(3, len(other_answers)))
    choices = wrong_choices + [correct_answer]
    random.shuffle(choices)

    quick_buttons = [QuickReplyButton(action=MessageAction(label=choice, text=choice))
                     for choice in choices]

    message = TextSendMessage(
        text=q["text"],
        quick_reply=QuickReply(items=quick_buttons)
    )

    return message

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
    "ヒント🤖\n私は5回に1回出てきます。",
    "ヒント🤖\n私は5回に1回出てきます。",
    "ヒント🤖\n継続は力なり。",
    "ヒント🤖\n継続は力なり。",
    "ヒント🤖\n継続は力なり。",
    "ヒント🤖\n勉強して下さい。",
    "ヒント🤖\n勉強して下さい。",
    "ヒント🤖\n勉強して下さい。",
    "ヒント🤖\n雲外蒼天",
    "ヒント🤖\nあなたが今電車の中なら、外の景色を見てみて下さい。",
    "ヒント🤖\n木々は栄養を分け合ったり、病気の木に助け舟を出したりします。",
    "ヒント🤖\n「ゆっくり行くものは、遠くまで行ける」ということわざがあります。",
    "ヒント🤖\nWBGTをチェックして、熱中症に気を付けて下さい。",
    "ヒント🤖\nすべての単語には5段階の把握度が付けられています。",
    "ヒント🤖\n1回スカイダビングしたいのならばパラシュートは不要ですが、2回なら必要です。",
    "ヒント🤖\n@新しい名前　でランキングに表示される名前を変更できます。",
    "ヒント🤖\n口を大きく開けずに済むので「I am」→「I'm」となりました。",
    
    "ヒント🤖\n to begin with「まず初めに」",
    "ヒント🤖\n strange to say「奇妙なことに」",
    "ヒント🤖\n needless to say「言うまでもなく」",
    "ヒント🤖\n to be sure 「確かに」",
    "ヒント🤖\n to make matters worse「さらに悪いことには」",
    "ヒント🤖\n to tell the truth　「実を言えば」",        
    "ヒント🤖\n not to say～　「～とは言わぬでも」",
    "ヒント🤖\n not to mention～\n not to speak of～   「～は言うまでもなく」\n to say nothing of～",
    "ヒント🤖\n in – 「中に、内部に包まれている」,「月・年・季節などの期間」",        
    "ヒント🤖\n on – 「上に、接触している」,「日・特定の日付」",
    "ヒント🤖\n at – 「地点・一点」,「時刻・瞬間」",
    "ヒント🤖\n to – 「到達点・目的地」",        
    "ヒント🤖\n into – 「中に入り込む動作」",
    "ヒント🤖\n onto – 「上に乗る動作」",
    "ヒント🤖\n for – 「目的・対象」",        
    "ヒント🤖\n of – 「所有・起源・属性」",
    "ヒント🤖\n by – 「手段・行為者」",
]

def choose_multiple_choice_question(user_id, questions):
    q = choose_weighted_question(user_id, questions)
    correct_answer = q["answer"]

    # 誤答候補をquestions全体からランダムに抽出
    other_answers = [item["answer"] for item in questions if item["answer"] != correct_answer]
    wrong_choices = random.sample(other_answers, k=min(3, len(other_answers)))

    # シャッフルして選択肢作成
    choices = wrong_choices + [correct_answer]
    random.shuffle(choices)

    # 選択肢を文字ラベルに変換（A, B, C, D）
    labels = ["A", "B", "C", "D"]
    choice_texts = [f"{labels[i]}: {choices[i]}" for i in range(len(choices))]

    # 問題文を作成
    question_text = q["text"] + "\n\n" + "\n".join(choice_texts)
    return q, question_text

def evaluate_X(elapsed, score, answer, is_multiple_choice=False):
    X = elapsed**1.7 + score**1.5

    if X <= 5:
        return "!!Brilliant", 3
    elif X <= 20:
        return "!Great", 2
    else:
        return "✓Correct", 1

# 高速ランキング（自分の順位も表示）
def build_ranking_flex_fast(user_id):
    docs = db.collection("users").stream()
    ranking = []

    for doc in docs:
        data = doc.to_dict()
        name = data.get("name", DEFAULT_NAME)
        total_rate = data.get("total_rate", 0)
        ranking.append((doc.id, name, total_rate))

    # レート順にソート
    ranking.sort(key=lambda x: x[2], reverse=True)

    # 自分の順位を探す
    user_pos = None
    for i, (uid, _, _) in enumerate(ranking, 1):
        if uid == user_id:
            user_pos = i
            break

    contents = []
    # TOP5表示
    for i, (uid, name, rate) in enumerate(ranking[:5], 1):
        if i == 1: color = "#FFD700"
        elif i == 2: color = "#C0C0C0"
        elif i == 3: color = "#CD7F32"
        else: color = "#1DB446"

        contents.append({
            "type": "box",
            "layout": "baseline",
            "contents": [
                {"type": "text", "text": f"#{i}", "flex": 1, "weight": "bold", "size": "md", "color": color},
                {"type": "text", "text": name, "flex": 4, "weight": "bold", "size": "md"},
                {"type": "text", "text": str(rate), "flex": 2, "align": "end", "size": "md"}
            ]
        })
        if i < 5:
            contents.append({"type": "separator", "margin": "md"})

    # 自分用メッセージ
    if user_pos is not None:
        my_uid, my_name, my_rate = ranking[user_pos - 1]
        if user_pos <= 5:
            msg_text = f"{my_name}\nTotal Rate: {my_rate}\nあなたは表彰台に乗っています！"
        else:
            # 一つ上との差分
            upper_uid, upper_name, upper_rate = ranking[user_pos - 2]
            diff = upper_rate - my_rate
            msg_text = (
                f"{my_name}\n#{user_pos} Total Rate:{my_rate}\n"
                f"#{user_pos - 1}の({upper_name})まで{diff}"
            )

        contents.append({"type": "separator", "margin": "md"})
        contents.append({
            "type": "text",
            "text": msg_text,
            "size": "sm",
            "wrap": True,
            "color": "#333333",
            "margin": "md"
        })

    flex_message = FlexSendMessage(
        alt_text="Ranking",
        contents={
            "type": "bubble",
            "body": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {"type": "text", "text": "Ranking", "weight": "bold", "size": "xl", "align": "center"},
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
        flex_msg = build_ranking_flex_fast(user_id)  
        line_bot_api.reply_message(event.reply_token, flex_msg)
        return

    if msg in ["1-1000", "1001-2000"]:
        question_msg = send_question(user_id, msg)
        line_bot_api.reply_message(event.reply_token, question_msg)
        return
        
    if msg == "成績":
        total_rate = update_total_rate(user_id)
        flex_msg = build_result_flex(user_id)
        line_bot_api.reply_message(event.reply_token, flex_msg)
        return

    if user_id in user_states:
        range_str, correct_answer = user_states[user_id]
        # 正解かどうか判定
        is_correct = (msg.lower() == correct_answer.lower())
        score = user_scores[user_id].get(correct_answer, 1)

        elapsed = time.time() - user_answer_start_times.get(user_id, time.time())
        is_multiple_choice = (range_str == "1001-2000")
        label, delta = evaluate_X(elapsed, score, correct_answer, is_multiple_choice=is_multiple_choice)
        # ラベルに応じたスコア変化
        delta_map = {
            "!!Brilliant": 3,
            "!Great": 2,
            "✓Correct": 1
        }

        if is_correct:
            delta_score = delta_map.get(label, 1)
            user_scores[user_id][correct_answer] = min(user_scores[user_id].get(correct_answer, 1) + delta_score, 4)
        else:
            # 不正解時は -1
            user_scores[user_id][correct_answer] = max(user_scores[user_id].get(correct_answer, 1) - 1, 0)

        # q を取得して meaning を渡す
        questions = questions_1_1000 if range_str == "1-1000" else questions_1001_2000
        q = next((x for x in questions if x["answer"] == correct_answer), None)

        flex_feedback = build_feedback_flex(
            user_id, is_correct, score, elapsed,
            correct_answer=correct_answer,
            label=label if is_correct else None,
            meaning=q.get("meaning") if q else None
        )


        # 次の問題
        next_question_msg = send_question(user_id, range_str)

        today = time.strftime("%Y-%m-%d")
        if user_daily_counts[user_id]["date"] != today:
            user_daily_counts[user_id]["date"] = today
            user_daily_counts[user_id]["count"] = 1
            
        user_daily_counts[user_id]["count"] += 1
        
        user_answer_counts[user_id] += 1
        messages_to_send = [flex_feedback]

        if user_answer_counts[user_id] % 5 == 0:
            trivia = random.choice(trivia_messages)
            messages_to_send.append(TextSendMessage(text=trivia))

        messages_to_send.append(next_question_msg)

        total_rate = update_total_rate(user_id)
        
        line_bot_api.reply_message(
            event.reply_token,
            messages=messages_to_send
        )
        return

    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text="1-1000 または 1001-2000 を押してね。")
    )

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port)
