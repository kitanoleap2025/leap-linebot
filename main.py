from flask import Flask, request
import os, json, random, threading, time, datetime
from collections import defaultdict
from dotenv import load_dotenv

# LINE Bot SDK
from linebot import LineBotApi, WebhookHandler
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage, FlexSendMessage,
    BoxComponent, TextComponent, QuickReply, QuickReplyButton, MessageAction,
    ButtonsTemplate, TemplateSendMessage, PostbackAction, PostbackEvent
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

#LEAP
leap_1_1000 = load_words("data/leap1-1000.json")
leap_1001_2000 = load_words("data/leap1001-2000.json")
leap_2001_2300 = load_words("data/leap2001-2300.json")

DEFAULT_NAME = "イキイキした毎日"

# LEAP公式ラインインスタンス
line_bot_api_leap = LineBotApi(os.getenv("LINE_CHANNEL_ACCESS_TOKEN_LEAP"))
handler_leap = WebhookHandler(os.getenv("LINE_CHANNEL_SECRET_LEAP"))

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
user_answer_counts = defaultdict(int)
user_names = {}  # user_id: name
user_answer_start_times = {}  # 問題出題時刻を記録
user_daily_counts = defaultdict(lambda: {"date": None, "count": 1})
user_streaks = defaultdict(int)
user_daily_e = defaultdict(lambda: {"date": None, "total_e": 0})
#ユーザーデータ読み込み・保存
def load_user_data(user_id):
    try:
        doc = db.collection("users").document(user_id).get()
        if doc.exists:
            data = doc.to_dict()
            user_scores[user_id] = defaultdict(lambda: 1, data.get("scores", {}))
            user_names[user_id] = data.get("name", DEFAULT_NAME)
        else:
            user_names[user_id] = DEFAULT_NAME
    except Exception as e:
        print(f"Error loading user data for {user_id}: {e}")
        user_names[user_id] = DEFAULT_NAME

def save_user_data(user_id):
    today = time.strftime("%Y-%m-%d")
    total_e = user_daily_e[user_id]["total_e"]
    total_e_date = user_daily_e[user_id]["date"]

    data = {
        "scores": dict(user_scores[user_id]),
        "name": user_names.get(user_id, DEFAULT_NAME),
        "total_e": total_e,
        "total_e_date": total_e_date
    }
    try:
        db.collection("users").document(user_id).set(data, merge=True)
    except Exception as e:
        print(f"Error saving user data for {user_id}: {e}")

def async_save_user_data(user_id):
    threading.Thread(target=save_user_data, args=(user_id,), daemon=True).start()

#範囲ごとの問題取得
def get_questions_by_range(range_str, bot_type, user_id):
    if range_str == "A":
        return leap_1_1000
    elif range_str == "B":
        return leap_1001_2000
    elif range_str == "C":
        return leap_2001_2300
    elif range_str == "WRONG":
        # user_scores 内で score == 0 の単語を集め、該当する問題オブジェクトを返す
        wrong_words = {w for w, s in user_scores.get(user_id, {}).items() if s == 0}
        if not wrong_words:
            return []
        # 全単語リスト（bot_type==LEAP の想定）
        all_questions = leap_1_1000 + leap_1001_2000 + leap_2001_2300
        return [q for q in all_questions if q["answer"] in wrong_words]
    return []
            
def get_rank(score):
    return {0: "✖", 1: "✔/❓", 2: "✔2", 3: "✔3", 4: "✔4"}.get(score, "✔/❓")

def score_to_weight(score):
    return {0: 1000, 1: 1000000, 2:10000, 3: 10000, 4: 1}.get(score, 1000000000000000000000)

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

    parts = []
    all_answers = []

    for range_label, title in ranges:
        qs = get_questions_by_range(range_label, bot_type, user_id)
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
    rank_counts = {"✔4": 0, "✔3": 0, "✔2": 0, "✔/❓": 0, "✖": 0}
    for word in all_answers:
        score = scores.get(word, 1)
        rank_counts[get_rank(score)] += 1

    total_words = sum(rank_counts.values())
    rank_ratios = {rank: (rank_counts[rank]/total_words if total_words else 0) for rank in rank_counts}

    # ランク別割合グラフ
    graph_components = []
    max_width = 180
    color_map = {"✔4": "#c0c0c0", "✔3": "#b22222", "✔2": "#4682b4", "✔/❓": "#ffd700", "✖": "#000000"}

    for rank in ["✔4", "✔3", "✔2", "✔/❓", "✖"]:
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
    scores = user_scores.get(user_id, {})
    
    if range_str == "WRONG":
        questions = get_questions_by_range("WRONG", bot_type, user_id)
        remaining_count = len(questions)
    else:
        questions = get_questions_by_range(range_str, bot_type, user_id)
        # スコアが未設定の単語だけ数える
        remaining_count = sum(1 for q in questions if q["answer"] not in scores)

    if not questions:
        return TextSendMessage(text="🥳🥳🥳間違えた問題はありません！")

    q = choose_weighted_question(user_id, questions)
    if q is None:
        return TextSendMessage(text="🥳🥳🥳間違えた問題はありません！")
    
    user_states[user_id] = (range_str, q)
    user_answer_start_times[user_id] = time.time()

    correct_answer = q["answer"]
    if correct_answer not in scores:
        score_display = "❓初出題の問題"
    else:
        score = scores[correct_answer]
        score_display = "✔" * score + "□" * (4 - score) if score > 0 else "✖間違えた問題"

    # 選択肢作成
    all_questions = leap_1_1000 + leap_1001_2000 + leap_2001_2300
    other_answers = [item["answer"] for item in all_questions if item["answer"] != correct_answer]
    wrong_choices = random.sample(other_answers, k=min(3, len(other_answers)))
    choices = wrong_choices + [correct_answer]
    random.shuffle(choices)
    quick_buttons = [QuickReplyButton(action=MessageAction(label=choice, text=choice))
                     for choice in choices]

    text_to_send = f"{score_display}\n{q['text']}"

    # 0でなければ残り問題数を表示
    if remaining_count > 0:
        if range_str == "WRONG":
            text_to_send = f"間違えた単語:あと{remaining_count}語\n" + text_to_send
        else:
            text_to_send = f"未出題の単語:あと{remaining_count}語\n" + text_to_send

    return TextSendMessage(text=text_to_send, quick_reply=QuickReply(items=quick_buttons))


def choose_weighted_question(user_id, questions):
    scores = user_scores.get(user_id, {})
    candidates = []
    weights = []
    for q in questions:
        weight = score_to_weight(scores.get(q["answer"], 1))
        candidates.append(q)
        weights.append(weight)
    if not candidates:
        return None
    chosen = random.choices(candidates, weights=weights, k=1)[0]
    return chosen

trivia_messages = [
    "ヒントろぼっと🤖\n全ての単語帳はLEAPに通ず。",
    "ヒントろぼっと🤖\n全ての単語帳はLEAPに通ず。",
    "ヒントろぼっと🤖\n全ての単語帳はLEAPに通ず。",
    "ヒントろぼっと🤖\nLEAPは剣よりも強し。",
    "ヒントろぼっと🤖\nLEAPは剣よりも強し。",
    "ヒントろぼっと🤖\nLEAPは剣よりも強し。",
    "ヒントろぼっと🤖\nWBGTとLEAPテストの得点には相関関係があると言われている。",
    "ヒントろぼっと🤖\nWBGTとLEAPテストの得点には相関関係があると言われている。",
    "ヒントろぼっと🤖\nWBGTとLEAPテストの得点には相関関係があると言われている。",
    "ヒントろぼっと🤖\n地球は平面だ。",
    "ヒントろぼっと🤖\n地球は平面だ。",
    "ヒントろぼっと🤖\n地球は平面だ。",
    "ヒントろぼっと🤖\nLEAP:「2秒で伸ばしてやる。」",
    "ヒントろぼっと🤖\nLEAP:「2秒で伸ばしてやる。」",
    "ヒントろぼっと🤖\nLEAP:「2秒で伸ばしてやる。」",
    "ヒントろぼっと🤖\n中国語版LEAP、「跳跃」!",
    "ヒントろぼっと🤖\n中国語版LEAP、「跳跃」!",
    "ヒントろぼっと🤖\n中国語版LEAP、「跳跃」!",
    "ヒントろぼっと🤖\n正解した単語には「✓」が最大4つ付く。",
    "ヒントろぼっと🤖\n正解した単語には「✓」が最大4つ付く。",
    "ヒントろぼっと🤖\n正解した単語には「✓」が最大4つ付く。",
    "ヒントろぼっと🤖\n「@(新しい名前)」と送信するとランキングに表示される名前を変更できる。",
    "ヒントろぼっと🤖\n「@(新しい名前)」と送信するとランキングに表示される名前を変更できる。",
    "ヒントろぼっと🤖\n「@(新しい名前)」と送信するとランキングに表示される名前を変更できる。",
    "ヒントろぼっと🤖\n正解した単語は以降出題されにくくなる。",
    "ヒントろぼっと🤖\n正解した単語は以降出題されにくくなる。",
    "ヒントろぼっと🤖\n正解した単語は以降出題されにくくなる。",
    "ヒントろぼっと🤖\n「学ぶ」→「間違えた問題」では間違えた問題のみ出題される。",
    "ヒントろぼっと🤖\n「学ぶ」→「間違えた問題」では間違えた問題のみ出題される。",
    "ヒントろぼっと🤖\n「学ぶ」→「間違えた問題」では間違えた問題のみ出題される。",
    "ヒントろぼっと🤖\n1回スカイダビングしたいのならばパラシュートは不要だが、2回なら必要だ。",
    "ヒントろぼっと🤖\n若さはニュースを楽しめるようになった日で終わる。",
    "ヒントろぼっと🤖\n医師会は1日に2問の英単語学習を推奨している。",
    "ヒントろぼっと🤖\n1日に2問の英単語学習は認知症予防に役立つ。",
    "ヒントろぼっと🤖\nネットの釣りタイトル禁止法が遂に成立。国民はやんややんやの大喝采！",
    "ヒントろぼっと🤖\n英単語学習は高齢者のキレ症を治すと報告された。",
    "ヒントろぼっと🤖\nノーベン詐欺禁止法が遂に成立。国民はやんややんやの大喝采！",
    "ヒントろぼっと🤖\n統計による予測:次のLEAPテストは難しい。",
    "ヒントろぼっと🤖\n統計による予測:次のLEAPテストは易しい。",
    "ヒントろぼっと🤖\nLEAPを1000周すると魔法使いになる。",
    "ヒントろぼっと🤖\nLEAPは世界で7番目に売れた書物だ。",
    "ヒントろぼっと🤖\nLEAPは投げられた。",
    "ヒントろぼっと🤖\n朕はLEAPなり。",
    "ヒントろぼっと🤖\nLEAPは山より高く、海より低い。",
    "ヒントろぼっと🤖\nLEAPは昔、「CHEAP」という名前だったらしい。",
    "ヒントろぼっと🤖\nDoritosはおいしいです。",
    "ヒントろぼっと🤖\n日本はリープの賜物である。",
    "ヒントろぼっと🤖\nLEAP!1秒ごとに世界で100人が読破中!",
    "ヒントろぼっと🤖\nLEAP一周するとおにぎり3個分のカロリーを消費することが報告された。",
    "ヒントろぼっと🤖\nネイティブも愛す!LEAP!",
    "ヒントろぼっと🤖\nLEAPには大金を払う価値がある。",
    "ヒントろぼっと🤖\nLEAPには莫大な時間を払う価値がある。",
    "ヒントろぼっと🤖\n大谷翔平は全国の小学校にLEAPを送った。",
    "ヒントろぼっと🤖\nヒントろぼっとで表示されるメッセージは合計1000種類ある。",
    "ヒントろぼっと🤖\n北野高校前の横断歩道で間に合う最後の青信号は8:08だ。",
    "ヒントろぼっと🤖\nリープも濡らせばバチが当たる。",
]
    
def evaluate_X(elapsed, score, answer, is_multiple_choice=True):
    X = elapsed**1.7 + score**1.7

    if X <= 16:
        return "!!Brilliant", 3
    elif X <= 28:
        return "!Great", 2
    else:
        return "✓Correct", 1

def get_label_score(lbl):
    score_map = {
        "✓Correct": 1,
        "!Great": 3,
        "!!Brilliant": 10
    }
    return score_map.get(lbl, 0)
        
#FEEDBACK　flex
def build_feedback_flex(user_id, is_correct, score, elapsed, correct_answer=None, label=None, meaning=None):
    body_contents = []
    label_score = get_label_score(label)

    label_symbols = {
        "!!Brilliant": "!!",
        "!Great": "!",
        "✓Correct": "✓",
    }
    label_symbol = label_symbols.get(label, "✓")  
    
    if is_correct:
        color_map = {"!!Brilliant":"#40e0d0", "!Great":"#4682b4", "✓Correct":"#00ff00"}
        color = color_map.get(label, "#000000")
        body_contents.append({
            "type": "text",
            "text": "✔️✔️✔️✔️✔️✔️✔️✔️",
            "weight": "bold",
            "size": "md",
            "color": "#ff1493",
            "align": "center"
        })
        body_contents.append({
            "type": "text",
            "text": label or "✓Correct",
            "weight": "bold",
            "size": "xl",
            "color": color,
            "align": "center"
        })
        
        # 正解時の追加メッセージ
        body_contents.append({
            "type": "text",
            "text": random.choice([
                "🎉 お見事！",
                "🚀 スコア上昇中！",
                "🧠 天才的！",
                "🏆 完璧！",
                "🎯 的中！",
                "👏 さすが！",
                "✨ 素晴らしい！",
                "🧩 すごい！",
                
            ]),
            "size": "md",
            "align": "center",
            "margin": "md"
        })
        body_contents.append({
            "type": "text",
            "text": "✔️✔️✔️✔️✔️✔️✔️✔️",
            "weight": "bold",
            "size": "md",
            "color": "#ff1493",
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

    count_today = user_daily_counts[user_id]["count"]
    if is_correct:
        y = 5 - score
        e = y * label_score * (user_streaks[user_id] ** 3)
        total_e_today = user_daily_e[user_id]["total_e"]
        body_contents.append({
            "type": "text",
            "text": f"{y}×{label_symbol}{label_score}×🔥{user_streaks[user_id]}³=${e}",
            "size": "lg",
            "color": "#333333",
            "margin": "xl"
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
    
def update_total_e_rate(user_id):
    user_data = db.collection("user_data").document(user_id).get().to_dict()
    if not user_data:
        return

    e_words = user_data.get("e_words", {})
    total_e_rate = sum(e_words.values()) / len(e_words) if e_words else 0

    db.collection("users").document(user_id).set({
        "total_e_rate": round(total_e_rate, 2)
    }, merge=True)

def reset_weekly_total_e():
    """全ユーザーのtotal_eを週単位でリセット（バッチ処理）"""
    today = datetime.date.today()
    current_week = today.isocalendar()[1]  # ISO週番号を取得

    try:
        batch = db.batch()
        docs = db.collection("users").stream()
        for doc in docs:
            user_data = doc.to_dict()
            user_total_e_week = user_data.get("total_e_week", None)
            user_week = user_data.get("total_e_week_num", None)

            if user_week != current_week:
                batch.update(db.collection("users").document(doc.id), {
                    "total_e": 0,
                    "total_e_week_num": current_week
                })
        batch.commit()
    except Exception as e:
        print(f"Error resetting weekly total_e: {e}")

medal_colors = {
    1: "#000000", 
    2: "#000000", 
    3: "#000000", 
}

# 高速ランキング（自分の順位も表示）
def build_ranking_with_totalE_flex(bot_type):
    reset_weekly_total_e()
    # total_rateランキング
    field_name_rate = f"total_rate_{bot_type.lower()}"
    try:
        docs_rate = db.collection("users")\
            .order_by(field_name_rate, direction=firestore.Query.DESCENDING)\
            .limit(30).stream()
        ranking_rate = [
            (doc.to_dict().get("name") or "イキイキした毎日",
             doc.to_dict().get(field_name_rate, 0))
            for doc in docs_rate
        ]
    except Exception as e:
        print(f"Error fetching total_rate ranking: {e}")
        ranking_rate = []

    # totalEランキング
    try:
        docs_e = db.collection("users")\
            .order_by("total_e", direction=firestore.Query.DESCENDING)\
            .limit(5).stream()
        ranking_e = [
            (doc.to_dict().get("name") or "イキイキした毎日",
             doc.to_dict().get("total_e", 0))
            for doc in docs_e
        ]
    except Exception as e:
        print(f"Error fetching totalE ranking: {e}")
        ranking_e = []

    bubbles = []
    # totalEランキング部分
    bubbles.append({
        "type": "box",
        "layout": "vertical",
        "contents": [
            {"type": "text", "text": "週間$ランキング", "weight": "bold", "size": "xl"},
            {"type": "separator", "margin": "md"}
        ]
    })
    for i, (name, e_value) in enumerate(ranking_e, start=1):
        color = medal_colors.get(i, "#000000")
        bubbles.append({
            "type": "box",
            "layout": "vertical",
            "contents": [
                {"type": "text", "text": f"{i}位 {name}", "flex": 1, "size": "md", "color": color},
                {"type": "text", "text": str(e_value), "flex": 1, "size": "lg", "align": "end", "color": color}
            ]
        })
    bubbles.append({"type": "separator", "margin": "md"})

    # total_rateランキング部分
    bubbles.append({
        "type": "box",
        "layout": "vertical",
        "contents": [
            {"type": "text", "text": f"{bot_type.upper()}トータルレート", "weight": "bold", "size": "xl"},
            {"type": "separator", "margin": "md"}
        ]
    })
    for i, (name, rate) in enumerate(ranking_rate, start=1):
        color = medal_colors.get(i, "#000000")
        bubbles.append({
            "type": "box",
            "layout": "baseline",
            "contents": [
                {"type": "text", "text": f"{i}位", "flex": 1, "size": "md", "color": color},
                {"type": "text", "text": name, "flex": 3, "size": "md", "color": color},
                {"type": "text", "text": str(rate), "flex": 1, "size": "md", "align": "end", "color": color}
            ]
        })

    flex_content = {
        "type": "bubble",
        "body": {
            "type": "box",
            "layout": "vertical",
            "contents": bubbles
        }
    }

    return FlexSendMessage(
        alt_text=f"{bot_type.upper()}ランキング + TotalEランキング",
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

# LEAP
@handler_leap.add(MessageEvent, message=TextMessage)
def handle_leap_message(event):
    handle_message_common(event, bot_type="LEAP", line_bot_api=line_bot_api_leap)

@app.route("/health")
def health():
    ua = request.headers.get("User-Agent", "")
    if "cron-job.org" in ua:
        return "ok", 200
    else:
        return "unauthorized", 403

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
    if msg in ["A", "B", "C", "WRONG"]:
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
                #QuickReplyButton(action=MessageAction(label="2001-2300", text="C")),
                QuickReplyButton(action=MessageAction(label="間違えた問題", text="WRONG")),
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
        flex_msg = build_ranking_with_totalE_flex(bot_type)
        line_bot_api.reply_message(event.reply_token, flex_msg)
        return

    if user_id in user_states:
        range_str, q = user_states[user_id]
        correct_answer = q["answer"]
        meaning = q.get("meaning")
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
            update_total_e_rate(user_id)
            user_streaks[user_id] += 1
            delta_score = delta_map.get(label, 1)
            user_scores[user_id][correct_answer] = min(user_scores[user_id].get(correct_answer, 1) + delta_score, 4)

            label_score = get_label_score(label)
            y = 5 - score
            e = y * label_score * (user_streaks[user_id] ** 3)

            
            # 日付チェック
            today = time.strftime("%Y-%m-%d")
            last_date_str = user_daily_e[user_id].get("date")
            if last_date_str:
                last_date = datetime.datetime.strptime(last_date_str, "%Y-%m-%d").date()
            else:
    # 初回なら今日で初期化
                last_date = datetime.date.today()

            current_date = datetime.date.today()

            if (current_date - last_date).days >= 7:
                user_daily_e[user_id]["total_e"] = 0
                user_daily_e[user_id]["date"] = today


            # トータル e 更新
            user_daily_e[user_id]["total_e"] += e
            try:
                db.collection("users").document(user_id).set({
                    "total_e": user_daily_e[user_id]["total_e"],
                    "total_e_date": today
                }, merge=True)
            except Exception as ex:
                print(f"Error saving total_e for {user_id}: {ex}")

        else:
            # 不正解時は0
            user_streaks[user_id] = max(user_streaks[user_id] - 3, 0)
            user_scores[user_id][correct_answer] = 0

        # q を取得して meaning を渡す
        questions = get_questions_by_range(range_str, bot_type, user_id)
        q = next((x for x in questions if x["answer"] == correct_answer), None)

        flex_feedback = build_feedback_flex(
            user_id, is_correct, score, elapsed,
            correct_answer=correct_answer,
            label=label if is_correct else None,
            meaning=meaning
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
