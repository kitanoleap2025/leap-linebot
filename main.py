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
    """
    指定されたJSONファイルを読み込み、
    Pythonのリストとして返す
    """
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# LEAP公式ラインインスタンス
line_bot_api_leap = LineBotApi(os.getenv("LINE_CHANNEL_ACCESS_TOKEN_LEAP"))
handler_leap = WebhookHandler(os.getenv("LINE_CHANNEL_SECRET_LEAP"))

# TARGET公式ラインインスタンス
line_bot_api_target = LineBotApi(os.getenv("LINE_CHANNEL_ACCESS_TOKEN_TARGET"))
handler_target = WebhookHandler(os.getenv("LINE_CHANNEL_SECRET_TARGET"))

 # TARGET
target_1001_1900 = load_words("data/target1001-1900.json") 


app = Flask(__name__)

cred_json = os.getenv("FIREBASE_CREDENTIALS")
cred_dict = json.loads(cred_json)
cred_dict["private_key"] = cred_dict["private_key"].replace("\\n", "\n")
cred = credentials.Certificate(cred_dict)
firebase_admin.initialize_app(cred)
db = firestore.client()

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

# TARGET
target_1_1000 = load_words("data/target1-1000.json")


#range_str と bot_type を使って関数化する
def get_questions_by_range(range_str, bot_type):
    if bot_type == "LEAP":
        questions_1_1000 = leap_1_1000
        questions_1001_2000 = leap_1001_2000
    else:
        questions_1_1000 = target_1_1000
        questions_1001_2000 = target_1001_1900

    return questions_1_1000 if range_str == "1-1000" else questions_1001_2000


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

#Dreams are free; reality charges you interest every day.

def get_rank(score):
    return {0: "0%", 1: "25%", 2: "50%", 3: "75%", 4: "100%"}.get(score, "25%")

def score_to_weight(score):
    return {0: 16, 1: 8, 2: 4, 3: 2, 4: 1}.get(score, 8)

def build_result_flex(user_id, bot_type):
    name = user_names.get(user_id, DEFAULT_NAME)

    # 各範囲の評価計算
    parts = []
    questions_1_1000 = get_questions_by_range("1-1000", bot_type)
    questions_1001_2000 = get_questions_by_range("1001-2000", bot_type)

    for title, qs in [("1-1000", questions_1_1000), ("1001-2000", questions_1001_2000)]:
        count = len(qs)
        total_score = sum(user_scores.get(user_id, {}).get(q["answer"], 1) for q in qs)
        # 平均スコア(0〜4)→把握率(0〜100%)
        rate_percent = int((total_score / count ) * 2500) if count else 0.0
       
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
    all_answers = [q["answer"] for q in questions_1_1000 + questions_1001_2000]
    for word in all_answers:
        score = scores.get(word, 1)
        rank_counts[get_rank(score)] += 1

    total_words = sum(rank_counts.values())
    rank_ratios = {rank: (rank_counts[rank]/total_words if total_words else 0) for rank in rank_counts}

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

    rate1 = round((sum(user_scores.get(user_id, {}).get(q["answer"], 1) for q in questions_1_1000) / c1) * 2500, 3) if c1 else 0
    rate2 = round((sum(user_scores.get(user_id, {}).get(q["answer"], 1) for q in questions_1001_2000) / c2) * 2500, 3) if c2 else 0

    total_rate = round((rate1 + rate2) / 2, 3)

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
def compute_rate_percent_for_questions(user_id, questions):
    if not questions:
        return 0.0
    scores = user_scores.get(user_id, {})
    total_score = sum(scores.get(q["answer"], 0) for q in questions)
    avg_score = total_score / len(questions)  # 0..4
    return int(avg_score * 2500)

def update_total_rate(user_id, bot_type):
    bot_type_lower = bot_type.lower() 
    field_name = f"total_rate_{bot_type_lower}"

    if bot_type_lower == "leap":
        q1 = get_questions_by_range("1-1000", "LEAP")
        q2 = get_questions_by_range("1001-2000", "LEAP")
    else:
        q1 = get_questions_by_range("1-1000", "TARGET")
        q2 = get_questions_by_range("1001-2000", "TARGET")

    scores = user_scores.get(user_id, {})

    def calc_rate(questions):
        if not questions:
            return 0.0
        total = sum(scores.get(q["answer"], 1) for q in questions)
        avg = total / len(questions)      # 平均スコア (1〜4)
        return int(avg * 2500)       # ← 平均スコア × 2500

    rate1 = calc_rate(q1)
    rate2 = calc_rate(q2)
    total_rate = int((rate1 + rate2) / 2)

    try:
        db.collection("users").document(user_id).set({field_name: total_rate}, merge=True)
    except Exception as e:
        print(f"Error updating {field_name} for {user_id}: {e}")
    return total_rate

def periodic_save():
    while True:
        time.sleep(600)  # 10分ごと
        for user_id in list(user_scores.keys()):
            save_user_data(user_id)

# スレッド起動
threading.Thread(target=periodic_save, daemon=True).start()

#FEEDBACK　flex
def build_ranking_flex_fast(bot_type):
    field_name = f"total_rate_{bot_type.lower()}"
    try:
        docs = db.collection("users")\
            .order_by(field_name, direction=firestore.Query.DESCENDING)\
            .limit(10).stream()
        ranking_data = [(doc.to_dict().get("name", DEFAULT_NAME), doc.to_dict().get(field_name, 0)) for doc in docs]
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
                {"type": "text", "text": f"{rate:.2f}%", "flex": 1, "size": "sm", "align": "end"}
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

    return FlexSendMessage(alt_text=f"{bot_type.upper()}ランキング", contents=flex_content)


def send_question(user_id, range_str, bot_type="LEAP"):
    questions = get_questions_by_range(range_str, bot_type)

    # 出題
    q = choose_weighted_question(user_id, questions)
    user_states[user_id] = (range_str, q["answer"])
    user_answer_start_times[user_id] = time.time()

    correct_answer = q["answer"]
    other_answers = [item["answer"] for item in questions if item["answer"] != correct_answer]
    wrong_choices = random.sample(other_answers, k=min(3, len(other_answers)))
    choices = wrong_choices + [correct_answer]
    random.shuffle(choices)

    quick_buttons = [QuickReplyButton(action=MessageAction(label=choice, text=choice))
                     for choice in choices]

    return TextSendMessage(text=q["text"], quick_reply=QuickReply(items=quick_buttons))


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
    "ヒント🤖\nあなたが今電車の中なら、外の景色を見てみて下さい。",
    "ヒント🤖\n木々は栄養を分け合ったり、病気の木に助け舟を出したりします。",
    "ヒント🤖\n「ゆっくり行くものは、遠くまで行ける」ということわざがあります。",
    "ヒント🤖\nWBGTをチェックして、熱中症に気を付けて下さい。",
    "ヒント🤖\nすべての単語には5段階の把握度が付けられています。",
    "ヒント🤖\n1回スカイダビングしたいのならばパラシュートは不要ですが、2回なら必要です。",
    "ヒント🤖\n@新しい名前　でランキングに表示される名前を変更できます。",
    "ヒント🤖\n口を大きく開けずに済むので「I am」→「I'm」となりました。",
    "ヒント🤖\n若さは、ニュースを楽しめるようになった日で終わる。",
    "ヒント🤖\nエアバスA380\n2010年、大西洋を横断していたエアバスA380にユーロファイター戦闘機が接近し、スピードやアクロバットを披露した。戦闘機のパイロットが「すごいだろ？」と尋ねると、エアバスのパイロットは「確かに。でもこれを見てみろ」と答えた。戦闘機のパイロットは観察したが、何も起きなかった。不思議に思い「何をしたんだ？」と再び聞くと、数分後エアバスのパイロットが無線で答えた。「立ち上がって足を伸ばし、トイレに行き、コーヒーとシナモンロールを取ってきたんだ。」",
    "ヒント🤖\n世界一礼儀正しい争い\nカナダとデンマークの間には領有権を争う島があります。両国の軍人は定期的に島を訪れ、相手の国旗を外して自国の旗を立て、代わりにデンマークのシュナッツかカナダのウイスキーを置いていきます。",
    "ヒント🤖\nワシの上を飛べる唯一の鳥はカラスです。カラスはワシの背中にとまり、首をつついて邪魔をします。しかしワシは反撃もせず、無駄に力を使うこともありません。その代わり、ただどんどん高く舞い上がっていきます。酸素が薄くなるとカラスは耐えられず、自ら落ちてしまうのです。教訓は明らかです。あなたを引きずり下ろそうとする相手と議論する必要はありません。ただ自分が高く昇れば、相手は勝手に落ちていくのです。",
    "ヒント🤖\nジョエル・バーガーという名前の男性が、アシュリー・キングという名前の女性と結婚しました。バーガーキングが結婚式の費用を全額負担しました。",
    "ヒント🤖\nトラは人間にはオレンジ色に見えますが、私たちは三色型色覚だからです。一方、シカやイノシシには二色型色覚しかないため、トラの色は周囲の緑に溶け込みます。オレンジと黒の縞模様は完璧なカモフラージュとして機能し、トラが身を隠して獲物に気付かれずに効率よく狩りができるのです。",
    "ヒント🤖\nこのハヤブサのヒナたちは、「怪物」が近づいてきたとき最大戒態勢に入りました...でも、実はただの好奇心旺盛なチョウでした。教訓：自分の本当の力を知らないと、小さなことでも怖くなるのです。",
    "ヒント🤖\n",
    
    "ヒント🤖\n to begin with「まず初めに」",
    "ヒント🤖\n strange to say「奇妙なことに」",
    "ヒント🤖\n needless to say「言うまでもなく」",
    "ヒント🤖\n to be sure 「確かに」",
    "ヒント🤖\n to make matters worse「さらに悪いことには」",
    "ヒント🤖\n to tell the truth　「実を言えば」",        
    "ヒント🤖\n not to say～　「～とは言わぬでも」",
    "ヒント🤖\n not to mention～\n not to speak of～\n to say nothing of～\n「～は言うまでもなく」",
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
                {"type": "text", "text": f"{rate:.2f}%", "flex": 1, "size": "sm", "align": "end"}
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

    # 質問送信
    if msg in ["1-1000", "1001-2000"]:
        question_msg = send_question(user_id, msg, bot_type=bot_type)
        line_bot_api.reply_message(event.reply_token, question_msg)
        return
        
    # 成績表示
    if msg == "成績":
        total_rate = update_total_rate(user_id, bot_type=bot_type)
        flex_msg = build_result_flex(user_id, bot_type=bot_type)
        line_bot_api.reply_message(event.reply_token, flex_msg)
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
        questions = get_questions_by_range(range_str, bot_type)
        q = next((x for x in questions if x["answer"] == correct_answer), None)


        flex_feedback = build_feedback_flex(
            user_id, is_correct, score, elapsed,
            correct_answer=correct_answer,
            label=label if is_correct else None,
            meaning=q.get("meaning") if q else None
        )


        # 次の問題
        next_question_msg = send_question(user_id, range_str, bot_type=bot_type)

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

        total_rate = update_total_rate(user_id, bot_type)
        
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
