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
     "answer": "agree"},
    {"text": "002 He strongly ___ corruption until he was promoted.\n昇進するまでは,彼は汚職に強く反対していた.",
     "answer": "opposed"},
    {"text": "003 The teacher ___ me to study English vocabulary.\n先生は私に英単語を勉強するよう助言した.",
     "answer": "advised"},
    {"text": "004 ___: Don’t argue with fools. From a distance, people might not be able to tell who is who.\nヒント：ばかとは口論するな.遠くから見たら,どっちがどっちか分からないから.",
     "answer": "tip"},
    {"text": "005 We ___ the problem so much, we forgot to solve it.\n私たちはその問題についてあまりに議論しすぎて,解決するのを忘れていた.",
     "answer": "discussed"},
    {"text": "006 He ___ the train for his lateness.\n彼は遅刻したことを電車のせいにした.",
     "answer": "blamed"},
    {"text": "007 He ___ that sleep wasn’t necessary for eaxms.\n彼は試験のために睡眠は必要ないと主張した.",
     "answer": "argued"},
    {"text": "008 I ___ that learning classical Japanese in high school is unnecessary.\n高校で古文を学ぶことは不必要だと主張する.",
     "answer": "claim"},
    {"text": "009 He ___ about having to buy a math textbook he would never use.\n彼は使うことのない数学の教科書を買わされることに不満を言っていました.",
     "answer": "complained"},
    {"text": "010 The company ___ him a job after the interview.\n面接の後,会社は彼に仕事を申し出た.",
     "answer": "offered"},
    {"text": "013 He said he was ___ to her for the feedback, but he ignored all of it.\n彼は彼女のフィードバックに感謝していると言ったが,すべて無視した.",
     "answer": "grateful"},
    {"text": "016 His family ___ his finally being accepted into college.\n彼の家族は,彼がついに大学に合格したことを祝った.",
     "answer": "celebrated"},
    {"text": """019 She was ___ "Best Excuse Maker" for always avoiding responsibility.\n彼女は常に責任を避けたことで「最高の言い訳メーカー」を受賞した.""",
     "answer": "awarded"},
    {"text": """020 They ___ ignoring the group project as "respecting individual effort."\n彼らはグループ課題を無視することを「個人の努力を尊重する」と表現しました.""",
     "answer": "described"},
    {"text": "021 He ___ why he had missed the deadline.\n彼はなぜ締め切りを過ぎたのか説明した.",
     "answer": "explained"},
    {"text": "022 It is important to ___ effectively with others in a team.\nチームで効果的にコミュ二ケーションをとることは重要だ.",
     "answer": "communicate"},
    {"text": "024 The man running ahead is the one I ___ to run with.\n前を走っている男は,一緒に走ると約束した人だ.",
     "answer": "promised"},
    {"text": "025 He provided a lot of ___, none of which was useful.\n彼はたくさんの情報を提供したが,役に立つものはひとつもなかった.",
     "answer": "information"},
    {"text": "026 With modern ___, we can talk to anyone in the world except the person next to you.\n現代のテクノロジーでは,隣にいる人以外の誰とでも話すことができる.",
     "answer": "technology"},
    {"text": "027 ___ shows that sunlight improves mental health.\n研究によると,日光はメンタルヘルスを改善する.",
     "answer": "research"},
    {"text": "029 ___ intelligence is changing the world rapidly.\n人工知能は急速に世界を変えている.",
     "answer": "artificial"},
    {"text": "034 He had the ___ to disappear whenever work started.\n彼は仕事が始まるといつも消える技術があった.",
     "answer": "skill"},
    {"text": "035 No less important than knowledge is the ___ to question it.\n知識に劣らず重要なのは,それを疑問視する能力です.",
     "answer": "ability"},
    {"text": "037 Success often comes after continuous ___.\n成功はたいてい継続的な努力の後にやってくる.",
     "answer": "effort"},
    {"text": "043 This machine can ___ 10 parts in one minute.\nこの機械は１分で10個の部品を生産出来る.",
     "answer": "produce"},
    {"text": "044 ___ LINE stickers using the teather's face\n先生の顔でLINEスタンプを作る",
     "answer": "create"},
    {"text": "045 Kitano high school was ___ in 1873.\n北野高校は1873年に設立された.",
     "answer": "established"},
    {"text": "066 Even a small change can have a great effect on ___.\n小さな変化でも社会に大きな影響を与える.",
     "answer": "society"},
    {"text": "068 We do not inherit the Earth from our ancestors; we borrow it from our children.\n私たちは先祖から地球を受け継ぐのではなく,子供たちから借りています.",
     "answer": "ancestors"},
    {"text": "074 the key ___ that led to the suspension \n停学への決定打となる証拠",
     "answer": "evidence"},
    {"text": "079 They ___ for confidence without thinking.\n彼らは考えずに信任に投票した.",
     "answer": "voted"},
    {"text": "098 What you said ___ more than you think.\n君が言ったことは,君が思っているよりも傷ついたよ.",
     "answer": "hurt"},
    {"text": "101 ___ the pen of the person sitting next to me\n隣の席の人のペンを破壊する",
     "answer": "destroy"},
    {"text": "111 The captain rescued only the ___ from his own country.\n船長は自国の人だけを救出しました.",
     "answer": "passengers"},
    {"text": "115 He climbed the ladder of success, then kicked it away so no one else could ___.\n彼は成功のはしごを登り,それを蹴飛ばし,他の誰も追随できないようにした.",
     "answer": "follow"},
    {"text": "116 Not all who ___ are lost.\n彷徨う人全員が迷っているわけではない.",
     "answer": "wander"},
    {"text": """124 She was awarded "Best Excuse Maker" for always ___ responsibility.\n彼女は常に責任を避けたことで「最高の言い訳メーカー」を受賞した.""",
     "answer": "avoiding"},
    {"text": "135 He explaind why he had ___ the deadline.\n彼はなぜ締め切りを過ぎたのか説明した.",
     "answer": "missed"},
    {"text": "137 He ___ silence for wisdom, and loudness for leadership.\n彼は沈黙を賢さと勘違いし,声の大きさをリーダーシップと勘違いした.",
     "answer": "mistook"},
    {"text": "150 ___ to understand\nわかっているふりをする",
     "answer": "pretend"},
    {"text": "154 It is not what ___ that matters. It is how you respond.\n大事なのは何が起きたかではない.どう応じるかだ.",
     "answer": "happened"},
    {"text": "153 ___ Juso after school\n放課後,十三を探検する",
     "answer": "explore"},
    {"text": "155 More and more problems ___.\nますます多くの問題が現れた.",
     "answer": "appeared"},
    {"text": "163 The captain rescued only the passengers from his ___ country.\n船長は自国の人だけを救出しました.",
     "answer": "own"},
    {"text": "167 ___ is written by the victors.\n歴史は勝者によって書かれる.",
     "answer": "history"}, 
    {"text": "170 No less important than ___ is the ability to question it.\n知識に劣らず重要なのは,それを疑問視する能力です.",
     "answer": "knowledge"},
    {"text": "189 His family celebrated his finally being ___ into college.\n彼の家族は,彼がついに大学に合格したことを祝った.",
     "answer": "accepted"},
    {"text": "209 He ___ to side with the insects.\n彼はその虫の味方をするようだ.",
     "answer": "seems"},
    {"text": "241 It is not what happened that ____. It is how you respond.\n大事なのは何が起きたかではない.どう応じるかだ.",
     "answer": "matters"},
    {"text": "258 People tend to accept ideas not because they are true, but because they are ___.\n人々はアイデアが真実だからではなく,馴染みがあるから受け入れる傾向があります.",
     "answer": "familiar"},
    {"text": "311 If you put ___ on a grandma, can you call it a bicycle?\nおばあちゃんに車輪を付けたら,自転車と呼べるのか.",
     "answer": "wheels"},
    {"text":"335 __, __, __ your boat\nGently down the stream\nMerrily, merrily, merrily, merrily\nLife is but a dream\n\nボートを漕げ、漕げ、漕げ\nそっと流れを下って\n陽気に、陽気に、陽気に、陽気に\n人生は夢に過ぎない",
     "answer": "row"},
    {"text": "338 I want to transfer to the ___ course.\n美術コースに転向したい.",
     "answer": "art"},
    {"text": "344 the challenge of having to create example ___ to protect copyright\n著作権保護のため例文を作らなければならないという課題",
     "answer": "sentences"},
    {"text": "347 The teacher advised me to study English ___.\n先生は私に英単語を勉強するよう助言した.",
     "answer": "vocabulary"},
    {"text": "356 What we see ___ not only on what we look at, but also on where we look from.\n私たちが見るものは,何を見るかだけでなく,どこから見るかによっても異なります.",
     "answer": "depends"},
    {"text": "359 The locals were amazed by the car they had never seen before and ___, but it was a driverless\n現地の人々は初めての車に驚き,物乞いをしたが,無人自動車だった.",
     "answer": "begged"},
    {"text": "360 The truth is often simple, but people ___ complex answers.\n真実はしばしば単純ですが,人々は複雑な答えを好みます.",
     "answer": "prefer"},
    {"text": "378 Even a small change can have a great ___ on society.\n小さな変化でも社会に大きな影響を与える.",
     "answer": "effect"},
    {"text": "393 ___ a small change can have a great effect on society.\n小さな変化でも社会に大きな影響を与える.",
     "answer": "even"},
    {"text": "400 With modern technology, we can talk to anyone in the world ___ the person next to you.\n現代のテクノロジーでは,隣にいる人以外の誰とでも話すことができる.",
     "answer": "except"},
    {"text": "420 It is not what happened that matters. It is how you ___.\n大事なのは何が起きたかではない.どう応じるかだ.",
     "answer": "respond"},
    {"text": "434 He’s been ___ her aunt for months\n彼は何か月も彼女のおばを狙っています.",
     "answer": "pursuing"},
    {"text": "440 the ___ of having to create example sentences to protect copyright\n著作権保護のため例文を作らなければならないという課題",
     "answer": "challenge"},
    {"text": "443 Is his face ___ or has it always been ___?\n彼は青ざめているのか,いつも青白いのか.",
     "answer": "pale"},
    {"text": "500 The consumption tax should be ___.\n消費税は廃止されるべきだ.",
     "answer": "abolished"},
    {"text": "539 The road to success is under ___.\n成功への道は工事中だ.",
     "answer": "construction"},
    {"text": "610 I can ___ everything except temptation.\n私は誘惑以外の全てに耐えうる.",
     "answer": "resist"},
    {"text": "694 What is taken for ___ today was once a revolutionary idea.\n今日当たり前のように考えられているものは,かつては革新的なアイデアでした.",
     "answer": "granted"},
    {"text": "763 The truth is often simple, but people prefer ___ answers.\n真実はしばしば単純ですが,人々は複雑な答えを好みます.",
     "answer": "complex"},
    {"text": "820 People ___ to accept ideas not because they are true, but because they are familiar.\n人々はアイデアが真実だからではなく,馴染みがあるから受け入れる傾向があります.",
     "answer": "tend"},
    {"text": "901 I want to ___ to the art course.\n美術コースに転向したい.",
     "answer": "transfer"},
    {"text": """978 They described ___ the group project as "respecting individual effort".\n彼らはグループ課題を無視することを「個人の努力を尊重する」と表現しました.""",
     "answer": "ignoring"},
    {"text": "992 We shape our tools, and ___, our tools shape us.\n私たちは道具を作るが,結果として,道具が私たちを作る.",
     "answer": "eventually"},
    {"text": "993 He argued that sleep wasn’t ___ for eaxms.\n彼は試験のために睡眠は必要ないと主張した.",
     "answer": "necessary"},
    {"text": "1000 ___ __ capitalism, your value peaks at checkout.\n資本主義によると,あなたの価値はチェックアウト時にピークに達する.",
     "answer": "according to"},
    {"text": "782 ___ woman\n熟女",
     "answer": "mature"}

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
            rank = "C😶‍\u200d🌫️"
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

# --- 以下、LINEハンドラ（略）---


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
