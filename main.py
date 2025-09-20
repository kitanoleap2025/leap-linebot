from flask import Flask, request, abort
import os, json, random, threading, time
from collections import defaultdict, deque
from dotenv import load_dotenv

# LINE Bot SDK
from linebot import LineBotApi, WebhookHandler
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage, FlexSendMessage,
    BoxComponent, TextComponent, QuickReply, QuickReplyButton, MessageAction
)
from linebot.exceptions import InvalidSignatureError

# Firebase
import firebase_admin
from firebase_admin import credentials, firestore

load_dotenv()
def load_words(path):
#指定されたJSONファイルを読み込み、Pythonのリストとして返す
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# LEAP公式ラインインスタンス
line_bot_api_leap = LineBotApi(os.getenv("LINE_CHANNEL_ACCESS_TOKEN_LEAP"))
handler_leap = WebhookHandler(os.getenv("LINE_CHANNEL_SECRET_LEAP"))

# TARGET公式ラインインスタンス
line_bot_api_target = LineBotApi(os.getenv("LINE_CHANNEL_ACCESS_TOKEN_TARGET"))
handler_target = WebhookHandler(os.getenv("LINE_CHANNEL_SECRET_TARGET"))

app = Flask(__name__)

#Firebase初期化
cred_json = os.getenv("FIREBASE_CREDENTIALS")
cred_dict = json.loads(cred_json)
cred_dict["private_key"] = cred_dict["private_key"].replace("\\n", "\n")
cred = credentials.Certificate(cred_dict)
firebase_admin.initialize_app(cred)
db = firestore.client()
#ユーザーデータ管理
user_states = {}  # user_id: (range_str, correct_answer)
user_scores = defaultdict(dict)
user_recent_questions = defaultdict(lambda: deque(maxlen=10))
user_answer_counts = defaultdict(int)
user_names = {}  # user_id: name
user_answer_start_times = {}  # 問題出題時刻を記録
user_daily_counts = defaultdict(lambda: {"date": None, "count": 1})

DEFAULT_NAME = "イキイキした毎日"

#LEAP
leap_1_1000 = load_words("data/leap1-1000.json")
leap_1001_2000 = load_words("data/leap1001-2000.json")
leap_2001_2300 = load_words("data/leap2001-2300.json")

# TARGET
target_1_800 = load_words("data/target1-800.json")
target_801_1500 = load_words("data/target801-1500.json")
target_1501_1900 = load_words("data/target1501-1900.json")

#ユーザーデータ読み込み・保存
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

# ABC全範囲まとめ
leap_questions_all = leap_1_1000 + leap_1001_2000 + leap_2001_2300
target_questions_all = target_1_800 + target_801_1500 + target_1501_1900


#範囲ごとの問題取得
def get_questions_by_range(range_str, bot_type):
    # ABCを内部範囲に変換
    if range_str == "A":
        if bot_type == "LEAP":
            return leap_1_1000
        else:  # TARGET
            return target_1_800
    elif range_str == "B":
        if bot_type == "LEAP":
            return leap_1001_2000
        else:  # TARGET
            return target_801_1500
    elif range_str == "C":
        if bot_type == "LEAP":
            return leap_2001_2300
        else:  # TARGET
            return target_1501_1900
            
def get_rank(score):
    return {0: "0%", 1: "25%", 2: "50%", 3: "75%", 4: "100%"}.get(score, "25%")

def score_to_weight(score):
    return {0: 16, 1: 8, 2: 4, 3: 2, 4: 1}.get(score, 8)

def build_result_flex(user_id, bot_type):
    name = user_names.get(user_id, DEFAULT_NAME)

    # Firebase から総合レートを取得
    field_name = f"total_rate_{bot_type.lower()}"
    try:
        doc = db.collection("users").document(user_id).get()
        total_rate = doc.to_dict().get(field_name, 0)
    except Exception:
        total_rate = 0
        
    # bot_type による範囲設定
    if bot_type == "LEAP":
        ranges = [("A", "1-1000"), ("B", "1001-2000"), ("C", "2001-2300")]
    else:  # TARGET
        ranges = [("A", "1-800"), ("B", "801-1500"), ("C", "1501-1900")]

    parts = []
    all_answers = []

    for range_label, title in ranges:
        qs = get_questions_by_range(range_label, bot_type)
        all_answers.extend([q["answer"] for q in qs])

        count = len(qs)
        total_score = sum(user_scores.get(user_id, {}).get(q["answer"], 1) for q in qs)
        rate_percent = int((total_score / count) * 2500) if count else 0

        parts.append({
            "type": "box",
            "layout": "vertical",
            "margin": "md",
            "contents": [
                {"type": "text", "text": title, "weight": "bold", "size": "sm", "color": "#000000"},
                {"type": "text", "text": f"Rating: {rate_percent}", "size": "md", "color": "#333333"},
            ],
        })

    # ランク別単語数・割合計算
    scores = user_scores.get(user_id, {})
    rank_counts = {"100%": 0, "75%": 0, "50%": 0, "25%": 0, "0%": 0}
    for word in all_answers:
        score = scores.get(word, 1)
        rank_counts[get_rank(score)] += 1

    total_words = sum(rank_counts.values())
    rank_ratios = {rank: (rank_counts[rank]/total_words if total_words else 0) for rank in rank_counts}

    # ランク別割合グラフ
    graph_components = []
    max_width = 200
    color_map = {"100%": "#c0c0c0", "75%": "#b22222", "50%": "#4682b4", "25%": "#ffd700", "0%": "#000000"}

    for rank in ["100%", "75%", "50%", "25%", "0%"]:
        width_px = max(5, int(rank_ratios[rank] * max_width))
        graph_components.append({
            "type": "box",
            "layout": "horizontal",
            "contents": [
                {"type": "box",
                 "layout": "vertical",
                 "contents": [
                     {"type": "text", "text": rank, "size": "sm"},
                     {"type": "text", "text": f"{rank_counts[rank]}語", "size": "sm"}
                 ],
                 "width": "70px"
                 },
                {"type": "box",
                 "layout": "vertical",
                 "contents": [],
                 "backgroundColor": color_map[rank],
                 "width": f"{width_px}px",
                 "height": "12px"
                 }
            ],
            "margin": "xs"
        })

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
                    {"type": "text", "text": f"Total Rating: {total_rate}", "weight": "bold", "size": "lg", "color": "#000000", "margin": "md"},
                    {"type": "separator", "margin": "md"},
                    *graph_components,
                    {"type": "separator", "margin": "md"},
                    {"type": "text", "text": "名前変更は「@(新しい名前)」で送信してください。", "size": "sm", "color": "#666666", "margin": "lg", "wrap": True}
                ]
            }
        }
    )

    return flex_message

def update_total_rate(user_id, bot_type):
    field_name = f"total_rate_{bot_type.lower()}"
    
    # 単語リストをまとめる
    if bot_type.lower() == "leap":
        questions = leap_1_1000 + leap_1001_2000 + leap_2001_2300
    else:
        questions = target_1_800 + target_801_1500 + target_1501_1900

    total_words = len(questions)  # 現在ロードされている単語数を使用

    scores = user_scores.get(user_id, {})
    total_score = sum(scores.get(q["answer"], 1) for q in questions)
    
    total_rate = int(total_score / total_words * 2500) if total_words else 0

    try:
        db.collection("users").document(user_id).set({field_name: total_rate}, merge=True)
    except Exception as e:
        print(f"Error updating {field_name} for {user_id}: {e}")

    return total_rate

def send_question(user_id, range_str, bot_type="LEAP"):
    questions = get_questions_by_range(range_str, bot_type)

    # 出題
    q = choose_weighted_question(user_id, questions)
    user_states[user_id] = (range_str, q["answer"])
    user_answer_start_times[user_id] = time.time()

    correct_answer = q["answer"]

    # スコア取得
    if correct_answer not in user_scores.get(user_id, {}):
        score_display = "❓"  # 未出題
    else:
        score = user_scores[user_id][correct_answer]
        # スコア0〜4を🔥で表現
        flames = 5 - score
        score_display = "🔥" * flames

    other_answers = [item["answer"] for item in questions if item["answer"] != correct_answer]
    wrong_choices = random.sample(other_answers, k=min(3, len(other_answers)))
    choices = wrong_choices + [correct_answer]
    random.shuffle(choices)

    quick_buttons = [QuickReplyButton(action=MessageAction(label=choice, text=choice))
                     for choice in choices]

    # 出題文にスコア表示
    text_to_send = f"{score_display}\n\n{q['text']}"

    return TextSendMessage(text=text_to_send, quick_reply=QuickReply(items=quick_buttons))

def choose_weighted_question(user_id, questions):
    scores = user_scores.get(user_id, {})
    recent = user_recent_questions[user_id]
    candidates = []
    weights = []
    for q in questions:
        if q["answer"] in recent:
            continue
        weight = score_to_weight(scores.get(q["answer"], 1))
        candidates.append(q)
        weights.append(weight)
    if not candidates:
        user_recent_questions[user_id].clear()
        for q in questions:
            weight = score_to_weight(scores.get(q["answer"], 1))
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
    "ヒント🤖\nあなたが今電車の中なら、外の景色を見てみて下さい。",
    "ヒント🤖\n木々は栄養を分け合ったり、病気の木に助け舟を出したりします。",
    "ヒント🤖\n「ゆっくり行くものは、遠くまで行ける」ということわざがあります。",
    "ヒント🤖\nWBGTをチェックして、熱中症に気を付けて下さい。",
    "ヒント🤖\nすべての単語には5段階の把握度が付けられています。",
    "ヒント🤖\n1回スカイダビングしたいのならばパラシュートは不要ですが、2回なら必要です。",
    "ヒント🤖\n@新しい名前　でランキングに表示される名前を変更できます。",
    "ヒント🤖\n口を大きく開けずに済むので「I am」→「I'm」となりました。",
    "ヒント🤖\n若さは、ニュースを楽しめるようになった日で終わる。",
    "ヒント🤖\n2010年、大西洋を横断していたエアバスA380にユーロファイター戦闘機が接近し、スピードやアクロバットを披露した。戦闘機のパイロットが「すごいだろ？」と尋ねると、エアバスのパイロットは「確かに。でもこれを見てみろ」と答えた。戦闘機のパイロットは観察したが、何も起きなかった。不思議に思い「何をしたんだ？」と再び聞くと、数分後エアバスのパイロットが無線で答えた。「立ち上がって足を伸ばし、トイレに行き、コーヒーとシナモンロールを取ってきたんだ。」",
    "ヒント🤖\n世界一礼儀正しい争い\nカナダとデンマークの間には領有権を争う島があります。両国の軍人は定期的に島を訪れ、相手の国旗を外して自国の旗を立て、代わりにデンマークのシュナッツかカナダのウイスキーを置いていきます。",
    "ヒント🤖\nワシの上を飛べる唯一の鳥はカラスです。カラスはワシの背中にとまり、首をつついて邪魔をします。しかしワシは反撃もせず、無駄に力を使うこともありません。その代わり、ただどんどん高く舞い上がっていきます。酸素が薄くなるとカラスは耐えられず、自ら落ちてしまうのです。教訓は明らかです。あなたを引きずり下ろそうとする相手と議論する必要はありません。ただ自分が高く昇れば、相手は勝手に落ちていくのです。",
    "ヒント🤖\nジョエル・バーガーという名前の男性が、アシュリー・キングという名前の女性と結婚しました。バーガーキングが結婚式の費用を全額負担しました。",
    "ヒント🤖\nトラは人間にはオレンジ色に見えますが、私たちは三色型色覚だからです。一方、シカやイノシシには二色型色覚しかないため、トラの色は周囲の緑に溶け込みます。オレンジと黒の縞模様は完璧なカモフラージュとして機能し、トラが身を隠して獲物に気付かれずに効率よく狩りができるのです。",
    "ヒント🤖\nこのハヤブサのヒナたちは、「怪物」が近づいてきたとき最大戒態勢に入りました...でも、実はただの好奇心旺盛なチョウでした。教訓：自分の本当の力を知らないと、小さなことでも怖くなるのです。",
    "ヒント🤖\n",
]

def evaluate_X(elapsed, score, answer, is_multiple_choice=True):
    X = elapsed**1.7 + score**1.5

    if X <= 8:
        return "!!Brilliant", 3
    elif X <= 20:
        return "!Great", 2
    else:
        return "✓Correct", 1

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


# 高速ランキング（自分の順位も表示）
def build_ranking_flex_fast(bot_type):
    field_name = f"total_rate_{bot_type.lower()}"
    try:
        docs = db.collection("users")\
            .order_by(field_name, direction=firestore.Query.DESCENDING)\
            .limit(10).stream()
        ranking_data = [
            (doc.to_dict().get("name", DEFAULT_NAME), doc.to_dict().get(field_name, 0))
            for doc in docs
        ]
    except Exception as e:
        print(f"Error fetching ranking for {bot_type}: {e}")
        ranking_data = []

    bubbles = []
    for i, (name, rate) in enumerate(ranking_data[:10], 1):
        bubbles.append({
            "type": "box",
            "layout": "baseline",
            "contents": [
                {"type": "text", "text": f"{i}位", "flex": 1, "size": "sm"},
                {"type": "text", "text": name, "flex": 3, "size": "sm"},
                {"type": "text", "text": f"{rate}", "flex": 1, "size": "sm", "align": "end"}
            ]
        })

    flex_content = {
        "type": "bubble",
        "body": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {"type": "text", "text": f"{bot_type.upper()}ランキング", "weight": "bold", "size": "md"},
                {"type": "separator", "margin": "md"},
                *bubbles
            ]
        }
    }

    return FlexSendMessage(
        alt_text=f"{bot_type.upper()}ランキング",
        contents=flex_content
    )



#-----------------------------------------------------------------
# 絵文字定義
emojis = [
    {"emoji": "🍒", "prob": 30, "value": 10},
    {"emoji": "🔔", "prob": 30, "value": 20},
    {"emoji": "💎", "prob": 20, "value": 50},
    {"emoji": "7️⃣", "prob": 20, "value": 100},
]

# 累積確率作成
cumulative_probs = []
cum = 0
for e in emojis:
    cum += e["prob"]
    cumulative_probs.append(cum)

# スロットを回す
def spin_slot():
    grid = []
    for _ in range(3):
        row = []
        for _ in range(3):
            r = random.randint(1, 100)
            for i, cp in enumerate(cumulative_probs):
                if r <= cp:
                    row.append(emojis[i])
                    break
        grid.append(row)
    return grid

# 横列揃いの点数計算
def calculate_score(grid):
    total_score = 0
    
    # 横列
    for row in grid:
        if row[0]["emoji"] == row[1]["emoji"] == row[2]["emoji"]:
            total_score += row[0]["value"]

    # 縦列
    for col in range(3):
        if grid[0][col]["emoji"] == grid[1][col]["emoji"] == grid[2][col]["emoji"]:
            total_score += grid[0][col]["value"]

    # 斜め
    if grid[0][0]["emoji"] == grid[1][1]["emoji"] == grid[2][2]["emoji"]:
        total_score += grid[0][0]["value"]
    if grid[0][2]["emoji"] == grid[1][1]["emoji"] == grid[2][0]["emoji"]:
        total_score += grid[0][2]["value"]

    return total_score

# Flexメッセージ作成
def build_slot_flex(grid):
    score = calculate_score(grid)
    lines_text = [" | ".join([cell["emoji"] for cell in row]) for row in grid]
    flex_msg = FlexSendMessage(
        alt_text="スロットマシン",
        contents={
            "type": "bubble",
            "body": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {"type": "text", "text": line, "size": "xl", "weight": "bold", "align": "center"} for line in lines_text
                ] + [
                    {"type": "text", "text": f"獲得点数: {score} 点", "size": "md", "align": "center", "margin": "md"}
                ]
            }
        }
    )
    return flex_msg
#-----------------------------------------------------------------------------------------

# —————— ここからLINEイベントハンドラ部分 ——————
# LEAP
@app.route("/callback/leap", methods=["POST"])
def callback_leap():
    body = request.get_data(as_text=True)
    signature = request.headers["X-Line-Signature"]
    handler_leap.handle(body, signature)
    return "OK"
#target
@app.route("/callback/target", methods=["POST"])
def callback_target():
    body = request.get_data(as_text=True)
    signature = request.headers["X-Line-Signature"]
    handler_target.handle(body, signature)
    return "OK"

# LEAP
@handler_leap.add(MessageEvent, message=TextMessage)
def handle_leap_message(event):
    handle_message_common(event, bot_type="LEAP", line_bot_api=line_bot_api_leap)
#target
@handler_target.add(MessageEvent, message=TextMessage)
def handle_target_message(event):
    handle_message_common(event, bot_type="TARGET", line_bot_api=line_bot_api_target)


def handle_message_common(event, bot_type, line_bot_api):
    user_id = event.source.user_id
    msg = event.message.text.strip()

# 以降の questions_1_1000, questions_1001_2000 は send_question 内で判断する

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

    # スロットマシン専用
    if msg == "あ":
        # スロットマシン処理をここに書く
        grid = spin_slot()  # 3x3スロットを回す
        flex_message = build_slot_flex(grid)  # Flexメッセージを作る
        line_bot_api.reply_message(event.reply_token, flex_message)
        return
    
    # 質問送信
    if msg in ["A", "B", "C"]:
        question_msg = send_question(user_id, msg, bot_type=bot_type)
        line_bot_api.reply_message(event.reply_token, question_msg)
        return
        
    # 成績表示
    if msg == "成績":
        total_rate = update_total_rate(user_id, bot_type=bot_type)
        flex_msg = build_result_flex(user_id, bot_type=bot_type)
        line_bot_api.reply_message(event.reply_token, flex_msg)
        return

    if msg == "学ぶ":
        if bot_type == "LEAP":
            quick_buttons = [
                QuickReplyButton(action=MessageAction(label="1-1000", text="A")),
                QuickReplyButton(action=MessageAction(label="1001-2000", text="B")),
                QuickReplyButton(action=MessageAction(label="2001-2300", text="C")),
                QuickReplyButton(action=MessageAction(label="間違えた問題", text="0%")),
            ]
        else:  # TARGET
            quick_buttons = [
                QuickReplyButton(action=MessageAction(label="1-800", text="A")),
                QuickReplyButton(action=MessageAction(label="801-1500", text="B")),
                QuickReplyButton(action=MessageAction(label="1501-1900", text="C")),
                QuickReplyButton(action=MessageAction(label="間違えた問題", text="0%")),
            ]

        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(
                text="学ぶ\n範囲を選択",
                quick_reply=QuickReply(items=quick_buttons)
            )
        )
        return
        
    # ランキング
    if msg == "ランキング":
        flex_msg = build_ranking_flex_fast(bot_type)
        line_bot_api.reply_message(event.reply_token, flex_msg)
        return

    if user_id in user_states:
        range_str, correct_answer = user_states[user_id]
        # 正解かどうか判定
        is_correct = (msg.lower() == correct_answer.lower())
        score = user_scores[user_id].get(correct_answer, 1)

        elapsed = time.time() - user_answer_start_times.get(user_id, time.time())
        label, delta = evaluate_X(elapsed, score, correct_answer)
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
        questions = get_questions_by_range(range_str, bot_type)
        q = next((x for x in questions if x["answer"] == correct_answer), None)


        flex_feedback = build_feedback_flex(
            user_id, is_correct, score, elapsed,
            correct_answer=correct_answer,
            label=label if is_correct else None,
            meaning=q.get("meaning") if q else None
        )
        
        today = time.strftime("%Y-%m-%d")
        if user_daily_counts[user_id]["date"] != today:
            user_daily_counts[user_id]["date"] = today
            user_daily_counts[user_id]["count"] = 1
        user_daily_counts[user_id]["count"] += 1
        user_answer_counts[user_id] += 1
        
        messages_to_send = [flex_feedback]

        if user_answer_counts[user_id] % 5 == 0:
            async_save_user_data(user_id)
            trivia = random.choice(trivia_messages)
            messages_to_send.append(TextSendMessage(text=trivia))

        # 次の問題
        next_question_msg = send_question(user_id, range_str, bot_type=bot_type)
        messages_to_send.append(next_question_msg)

        total_rate = update_total_rate(user_id, bot_type)
        
        line_bot_api.reply_message(event.reply_token, messages=messages_to_send)
        return
        
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text="「学ぶ」を押してみましょう！")
    )

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port)
