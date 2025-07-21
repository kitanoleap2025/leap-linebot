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

# --- 英単語Bot状態 ---
user_states = {}  # user_id: (range_str, correct_answer)
user_scores = defaultdict(dict)  # user_id: {word: score}
user_stats = defaultdict(lambda: {"correct": 0, "total": 0})  # user_id: {"correct": x, "total": y}

# --- ロシアンルーレット状態 ---
user_sessions = {}  # user_id: game_state dict

# --- 成績連打カウンター(隠しゲーム起動用) ---
user_hidden_counter = defaultdict(int)

# --- 問題リスト（簡略版） ---
questions_1_1000 = [
    {"text": "001 I ___ with the idea that students should not be given too much homework.\n生徒に宿題を与えすぎるべきではないという考えに賛成です.",
     "answer": "agree"}
]
questions_1001_1935 = [
    {"text": "1001 The ___ made a critical discovery in the lab.\nその科学者は研究室で重大な発見をした。", "answer": "scientist"},
]

# --- ユーティリティ関数 ---
def get_rank(score):
    return {0: "D", 1: "C", 2: "B", 3: "A", 4: "S"}[score]

def score_to_weight(score):
    return {0: 5, 1: 4, 2: 3, 3: 2, 4: 1}.get(score, 5)

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

        if count == 0:
            text += f"（📝Performance{title}）\nNo data yet.\n\n"
            continue

        avg_score = round(total_score / count, 2)
        rate = round((total_score / count) * 2500)
        if rate >= 9900:
            rank = "S🤩"
        elif rate >= 7500:
            rank = "A😎"
        elif rate >= 5000:
            rank = "B😍"
        elif rate >= 2500:
            rank = "C😶‍🌫️"
        else:
            rank = "D😴"

        filtered_correct = sum(1 for ans in relevant_answers if scores.get(ans, 0) > 0)
        filtered_total = sum(1 for ans in relevant_answers if ans in scores)

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
        text += f"{rank}ランク: {rank_counts[rank]}語\n"
    return text

def choose_weighted_question(user_id, questions):
    scores = user_scores.get(user_id, {})
    weights = [score_to_weight(scores.get(q["answer"], 0)) for q in questions]
    return random.choices(questions, weights=weights, k=1)[0]

# --- ロシアンルーレット用関数 ---
def setup_chambers():
    chambers = [0] * 6
    bullet_count = random.randint(1, 3)
    bullet_positions = random.sample(range(6), bullet_count)
    for pos in bullet_positions:
        chambers[pos] = 1
    known_safe = random.choice([i for i in range(6) if chambers[i] == 0])
    return chambers, bullet_count, known_safe

def new_game_state():
    chambers, bullet_count, known_safe = setup_chambers()
    return {
        "player_hp": 2,
        "bot_hp": 2,
        "chambers": chambers,
        "bullet_count": bullet_count,
        "known_safe": known_safe,
        "turn": 0,
        "player_turn": True,
    }

def bot_action(state):
    turn = state['turn']
    chambers = state['chambers']
    bot_hp = state['bot_hp']

    bullets_left = sum(chambers[turn:])
    if bot_hp == 1 or bullets_left == 1:
        return '2'
    elif bullets_left <= 2:
        return random.choices(['2', '1'], weights=[0.8, 0.2])[0]
    else:
        return random.choice(['1', '2'])

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

    # 1. ロシアンルーレットプレイ中はそちらの処理のみ行う（ただし英単語コマンドが来たらゲーム強制終了）
    if user_id in user_sessions:
        if msg in ["1-1000", "1001-1935"]:
            # ロシアンゲーム強制終了
            user_sessions.pop(user_id)
            # ここでreturnしない＝続けて英単語Bot処理を実行
        else:
            state = user_sessions[user_id]
            messages = []

            # 入力は「1」か「2」のみ有効
            if msg not in ['1', '2']:
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text="1か2で答えてください。"))
                return

            turn = state['turn']
            chambers = state['chambers']
            player_hp = state['player_hp']
            bot_hp = state['bot_hp']
            player_turn = state['player_turn']

            if not player_turn:
                messages.append("今はあなたのターンではありません。")
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text="\n".join(messages)))
                return

            # プレイヤーのターン処理
            if msg == '1':
                messages.append(f"{state['turn'] + 1}発目")
                messages.append("こめかみに銃口を当てた。")
                if chambers[turn] == 1:
                    state['player_hp'] -= 1
                    messages.append(f"💥 実弾だ!アドレナリンが全身を駆け巡る。\nPLAYER: {'⚡' * state['player_hp']}　DEALER: {'⚡' * state['bot_hp']}\n")
                    if state['player_hp'] == 0:
                        messages.append("HPが0になった。ゲーム終了。")
                        user_sessions.pop(user_id)  # セッション削除
                        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="\n".join(messages)))
                        return
                    state['player_turn'] = False
                else:
                    messages.append("カチッ。空砲だ。あなたのターン続行！")
                    # player_turnは変えず
                state['turn'] += 1

            else:  # msg == '2'
                messages.append(f"{state['turn'] + 1}発目")
                messages.append("相手に撃った。")
                if chambers[turn] == 1:
                    state['bot_hp'] -= 1
                    messages.append(f"💥 DEALERを撃ち抜いた!\nPLAYER: {'⚡' * state['player_hp']}　DEALER: {'⚡' * state['bot_hp']}\n")
                    if state['bot_hp'] == 0:
                        messages.append("DEALERに勝った！ゲーム終了。")
                        user_sessions.pop(user_id)
                        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="\n".join(messages)))
                        return
                else:
                    messages.append("カチッ。空砲だ。")
                state['player_turn'] = False
                state['turn'] += 1

            # ボットのターン処理
            if not state['player_turn'] and state['turn'] < 6:
                messages.append(f"{state['turn'] + 1}発目")
                messages.append("DEALERのターン")
                bot_act = bot_action(state)
                if bot_act == '1':
                    messages.append("DEALERはこめかみに銃口を当てた。")
                    if chambers[state['turn']] == 1:
                        state['bot_hp'] -= 1
                        messages.append(f"💥 DEALERが被弾！\nPLAYER: {'⚡' * state['player_hp']}　DEALER: {'⚡' * state['bot_hp']}\n")
                        if state['bot_hp'] == 0:
                            messages.append("DEALERに勝った！ゲーム終了。")
                            user_sessions.pop(user_id)
                            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="\n".join(messages)))
                            return
                        state['player_turn'] = True
                    else:
                        messages.append("カチッ。空砲だ。DEALERのターン続行。")
                    state['turn'] += 1
                else:
                    messages.append("DEALERはあなたに撃った！")
                    if chambers[state['turn']] == 1:
                        state['player_hp'] -= 1
                        messages.append(f"💥 あなたが被弾！アドレナリンが全身を駆け巡る。\nPLAYER: {'⚡' * state['player_hp']}　DEALER: {'⚡' * state['bot_hp']}\n")
                        if state['player_hp'] == 0:
                            messages.append("HPが0になった。ゲーム終了。")
                            user_sessions.pop(user_id)
                            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="\n".join(messages)))
                            return
                    else:
                        messages.append("カチッ。空砲だ。")
                    state['player_turn'] = True
                    state['turn'] += 1

            # 6発終了でリロード
            if state['turn'] >= 6:
                messages.append("\n💥 リロードします...\n")
                chambers, bullet_count, known_safe = setup_chambers()
                state['chambers'] = chambers
                state['bullet_count'] = bullet_count
                state['known_safe'] = known_safe
                state['turn'] = 0
                state['player_turn'] = True
                reply = (
                    f"6発中...実弾{state['bullet_count']}発.\n"
                    f"📱古い携帯から声が聞こえる...{state['known_safe'] + 1}発目...空砲.\n\n"
                    f"{state['turn'] + 1}発目\n"
                    f"PLAYER        DEALER\n{'⚡' * state['player_hp']}          {'⚡' * state['bot_hp']}\n"
                    "自分に撃つ(1) / 相手に撃つ(2)"
                )

            user_sessions[user_id] = state
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="\n".join(messages)))
            return

    # 2. ここから英単語Bot処理

    # 「成績」連打でロシアンルーレットを開始判定
    if msg == "成績":
        user_hidden_counter[user_id] += 1
        if user_hidden_counter[user_id] >= 5:
            # ロシアンゲーム開始
            user_hidden_counter[user_id] = 0
            user_sessions[user_id] = new_game_state()
            state = user_sessions[user_id]
            reply = (
                "=== Russian Roulette ===\n"
                "6発装填のショットガンを交互に撃ち合う.ライフは1人2つ.\n\n"
                f"6発中...実弾{state['bullet_count']}発.\n"
                f"📱古い携帯から声が聞こえる...{state['known_safe'] + 1}発目...空砲.\n\n"
                f"{state['turn'] + 1}発目\n"
                f"PLAYER        DEALER\n{'⚡' * state['player_hp']}          {'⚡' * state['bot_hp']}\n"
                "自分に撃つ(1) / 相手に撃つ(2)"
            )
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))
            return
        else:
            # 普通の成績表示
            text = build_result_text(user_id)
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=text))
            return
    else:
        # 「成績」以外のメッセージはカウンターリセット
        user_hidden_counter[user_id] = 0

    if msg == "把握度":
        text = build_grasp_text(user_id)
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=text))
        return

    if msg in ["1-1000", "1001-1935"]:
        if msg == "1-1000":
            q = choose_weighted_question(user_id, questions_1_1000)
        else:
            q = choose_weighted_question(user_id, questions_1001_1935)
        user_states[user_id] = (msg, q["answer"])
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=q["text"]))
        return

    # 回答処理
    if user_id in user_states:
        range_str, correct_answer = user_states[user_id]
        is_correct = (msg.lower() == correct_answer.lower())

        # スコア処理
        score = user_scores[user_id].get(correct_answer, 0)
        if is_correct:
            user_scores[user_id][correct_answer] = min(4, score + 1)
            user_stats[user_id]["correct"] += 1
        else:
            user_scores[user_id][correct_answer] = max(0, score - 1)
        user_stats[user_id]["total"] += 1

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

    # 初期メッセージ案内
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text="1-1000 または 1001-1935 を送信してね！")
    )

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port)
