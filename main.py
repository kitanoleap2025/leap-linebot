from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.models import MessageEvent, TextMessage, TextSendMessage
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

load_dotenv()
app = Flask(__name__)

# Firebase初期化
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
user_stats = defaultdict(lambda: {
    "1-1000": {"correct": 0, "total": 0},
    "1001-1935": {"correct": 0, "total": 0}
})
user_recent_questions = defaultdict(lambda: deque(maxlen=10))
user_names = {}  # user_id: name
user_times = defaultdict(lambda: float('inf'))  # ベストタイムはユーザー単位でfloat管理

DEFAULT_NAME = "名無し"

def load_user_data(user_id):
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

            best_time = data.get("best_time")
            if best_time is not None:
                user_times[user_id] = float(best_time)
            else:
                user_times[user_id] = float('inf')
        else:
            user_names[user_id] = DEFAULT_NAME
    except Exception as e:
        print(f"Error loading user data for {user_id}: {e}")
        user_names[user_id] = DEFAULT_NAME

def save_user_data(user_id):
    data = {
        "scores": dict(user_scores[user_id]),
        "stats": user_stats[user_id],
        "recent": list(user_recent_questions[user_id]),
        "name": user_names.get(user_id, DEFAULT_NAME),
        "best_time": user_times.get(user_id, float('inf'))
    }
    try:
        db.collection("users").document(user_id).set(data)
    except Exception as e:
        print(f"Error saving user data for {user_id}: {e}")

def async_save_user_data(user_id):
    threading.Thread(target=save_user_data, args=(user_id,), daemon=True).start()

# ここに問題リストを入れてください
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
    {"text": "011 He ___ that he was gay.\n彼は自身がゲイであることをほのめかした。",
     "answer": "suggested"},
    {"text": "012 I was ___ to the local volunteer club.\n私は地元のボランティアクラブに推薦された。",
     "answer": "recommended"},
    {"text": "013 He said he was ___ to her for the feedback, but he ignored all of it.\n彼は彼女のフィードバックに感謝していると言ったが,すべて無視した.",
     "answer": "grateful"},
    {"text": "014 I ___ for criticizing.\n私は批判したことを謝った.",
     "answer": "apologized"},
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
    {"text": "029 People who can be replaced by ___ Intelligence\nAIに代替可能な人.",
     "answer": "artificial"},
    {"text": "033 Eurasia developed faster because it stretches east to west, so crops could spread in similar climates.\nユーラシアは東西に広がっているため、作物が似た気候の中で広まりやすく、より早く発展した。",
     "answer": "developed"},
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
    {"text": "058 War is peace. Freedom is slavery. Ignorance is ___.\n戦争は平和。自由は隷従。無知は力。",
     "answer": "strength"},
    {"text": "066 Even a small change can have a great effect on ___.\n小さな変化でも社会に大きな影響を与える.",
     "answer": "society"},
    {"text": "068 We do not inherit the Earth from our ___, we borrow it from our children.\n私たちは先祖から地球を受け継ぐのではなく,子供たちから借りています.",
     "answer": "ancestors"},
    {"text": "074 the key ___ that led to the suspension \n停学への決定打となる証拠",
     "answer": "evidence"},
    {"text": "079 They ___ for confidence without thinking.\n彼らは考えずに信任に投票した.",
     "answer": "voted"},
    {"text": "085 The ___ is determined by supply and demand.\n価格は需要と供給で決まる.",
     "answer": "price"},
    {"text": "098 What you said ___ more than you think.\n君が言ったことは,君が思っているよりも傷ついたよ.",
     "answer": "hurt"},
    {"text": "101 ___ the pen of the person sitting next to me\n隣の席の人のペンを破壊する",
     "answer": "destroy"},
    {"text": "111 The captain rescued only the ___ from his own country.\n船長は自国の乗客だけを救出しました.",
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
    {"text": "163 The captain rescued only the passengers from his ___ country.\n船長は自国の乗客だけを救出しました.",
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
    {"text": "259 Eurasia developed faster because it stretches east to west, so crops could spread in ___ climates.\nユーラシアは東西に広がっているため、作物が似た気候の中で広まりやすく、より早く発展した。",
     "answer": "similar"},
    {"text": "269 Don’t ___ your chickens before they hatch.\n卵がかえる前にヒヨコを数えるな",
     "answer": "count"},
    {"text": "311 If you put ___ on a grandma, can you call it a bicycle?\nおばあちゃんに車輪を付けたら,自転車と呼べるのか.",
     "answer": "wheels"},
    {"text":"335 __, __, __ your boat\nGently down the stream\nMerrily, merrily, merrily, merrily\nLife is but a dream\n\nボートを漕げ、漕げ、漕げ\nそっと流れを下って\n陽気に、陽気に、陽気に、陽気に\n人生は夢に過ぎない",
     "answer": "row"},
    {"text": "323 He ___ more than just money to buy his daughter an instrument.\n彼は娘に楽器を買うためにお金以上のものを支払った。",
     "answer": "paid"},
    {"text": "338 I want to transfer to the ___ course.\n美術コースに転向したい.",
     "answer": "art"},
    {"text": "342 He paid more than just money to buy his daughter an ___.\n彼は娘に楽器を買うためにお金以上のものを支払った。",
     "answer": "instrument"},
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
    {"text": "402 I apologized for ___.\n私は批判したことを謝った.",
     "answer": "criticizing"},
    {"text": "420 It is not what happened that matters. It is how you ___.\n大事なのは何が起きたかではない.どう応じるかだ.",
     "answer": "respond"},
    {"text": "434 He’s been ___ her aunt for months\n彼は何か月も彼女のおばを狙っています.",
     "answer": "pursuing"},
    {"text": "440 the ___ of having to create example sentences to protect copyright\n著作権保護のため例文を作らなければならないという課題",
     "answer": "challenge"},
    {"text": "443 Is his face ___ or has it always been ___?\n彼は青ざめているのか,いつも青白いのか.",
     "answer": "pale"},
    {"text": "479 All animals are ___, but some animals are more ___ than others.\n全ての動物は平等だが、中には他よりもっと平等な動物もいる。",
     "answer": "equal"},
    {"text": "500 The consumption tax should be ___.\n消費税は廃止されるべきだ.",
     "answer": "abolished"},
    {"text": "539 The road to success is under ___.\n成功への道は工事中だ.",
     "answer": "construction"},
    {"text": "604 Eurasia developed faster because it stretches east to west, so crops could ___ in similar climates.\nユーラシアは東西に広がっているため、作物が似た気候の中で広まりやすく、より早く発展した。",
     "answer": "spread"},
    {"text": "610 I can ___ everything except temptation.\n私は誘惑以外の全てに耐えうる.",
     "answer": "resist"},
    {"text": "627  A job that requires constant ___\nおじぎし続ける仕事",
     "answer": "bowing"},
    {"text": "033 Eurasia developed faster because it ___ east to west, so crops could spread in similar climates.\nユーラシアは東西に広がっているため、作物が似た気候の中で広まりやすく、より早く発展した。",
     "answer": "stretches"},
    {"text": "639 ___ while the iron is hot\n鉄は熱いうちに打て",
     "answer": "strike"},
    {"text": "659  A job that ___ constant bowing\nおじぎし続ける仕事",
     "answer": "requires"},
    {"text": "673 The price is ___ by supply and demand.\n価格は需要と供給で決まる.",
     "answer": "determined"},
    {"text": "694 What is taken for ___ today was once a revolutionary idea.\n今日当たり前のように考えられているものは,かつては革新的なアイデアでした.",
     "answer": "granted"},
    {"text": "709 Eurasia developed faster because it stretches east to west, so ___ could spread in similar climates.\nユーラシアは東西に広がっているため、作物が似た気候の中で広まりやすく、より早く発展した。",
     "answer": "crops"},
    {"text": "714 Eurasia developed faster because it stretches east to west, so crops could spread in similar ___.\nユーラシアは東西に広がっているため、作物が似た気候の中で広まりやすく、より早く発展した。",
     "answer": "climates"},
    {"text": "762 The turtle is not ___ about who gets first in the contest. He simply finds pleasure in the steady walk.\nカメはコンテストで誰が一番になるかを気にしていません。ただ、着実な歩みを楽しんでいるのです。",
     "answer": "serious"},
    {"text": "763 The truth is often simple, but people prefer ___ answers.\n真実はしばしば単純ですが,人々は複雑な答えを好みます.",
     "answer": "complex"},
    {"text": "779 The turtle is not serious about who gets first in the contest. He simply finds pleasure in the ___ walk.\nカメはコンテストで誰が一番になるかを気にしていません。ただ、着実な歩みを楽しんでいるのです。",
     "answer": "steady"},
    {"text": "820 People ___ to accept ideas not because they are true, but because they are familiar.\n人々はアイデアが真実だからではなく,馴染みがあるから受け入れる傾向があります.",
     "answer": "tend"},
    {"text": "860 The price is determined by ___ and demand.\n価格は需要と供給で決まる.",
     "answer": "supply"},
    {"text": "861 People who can be ___ by Artificial Intelligence\nAIに代替可能な人.",
     "answer": "replaced"},
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
    {"text": "782 \n熟女",
     "answer": "mature"},

    # 他の問題...
]
questions_1001_1935 = [
    {"text": "1001 The ___ made a critical discovery in the lab.\nその科学者は研究室で重大な発見をした。",
     "answer": "scientist"},
    {"text": "1247 Don’t count your chickens before they ___.\n卵がかえる前にヒヨコを数えるな",
     "answer": "hatch"},
]

def get_rank(score):
    return {0: "D", 1: "C", 2: "B", 3: "A", 4: "S"}.get(score, "D")

def score_to_weight(score):
    return {0: 16, 1: 8, 2: 4, 3: 2, 4: 1}.get(score, 5)

def build_result_text(user_id):
    name = user_names.get(user_id, DEFAULT_NAME)
    text = f"{name}\n\n"
    
    scores = user_scores.get(user_id, {})

    for title, questions in [("1-1000", questions_1_1000), ("1001-1935", questions_1001_1935)]:
        relevant_answers = [q["answer"] for q in questions]
        total_score = sum(scores.get(ans, 0) for ans in relevant_answers)
        count = len(relevant_answers)

        stat = user_stats.get(user_id, {}).get(title, {"correct": 0, "total": 0})
        filtered_correct = stat["correct"]
        filtered_total = stat["total"]

        # ★ No data yet を削除して、常にレートとランクを表示
        rate = round((total_score / count) * 2500) if count > 0 else 0
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
            f"Correct:{filtered_correct}/Total:{filtered_total}\n"
            f"Rating:{rate}\n"
            f"Rank:{rank}\n\n"
        )

    # 合計レート計算
    rate1 = None
    rate2 = None
    c1 = len(questions_1_1000)
    c2 = len(questions_1001_1935)

    if c1 > 0:
        total_score1 = sum(scores.get(q["answer"], 0) for q in questions_1_1000)
        rate1 = round((total_score1 / c1) * 2500)

    if c2 > 0:
        total_score2 = sum(scores.get(q["answer"], 0) for q in questions_1001_1935)
        rate2 = round((total_score2 / c2) * 2500)

    valid_rates = [r for r in [rate1, rate2] if r is not None]
    total_rate = round(sum(valid_rates) / len(valid_rates)) if valid_rates else 0

    # ベストタイム
    best_time = user_times.get(user_id, float('inf'))
    time_text = f"{best_time:.2f}s" if best_time != float('inf') else "未記録"

    text += f"🔥Total Rating:{total_rate}\n"
    text += f"⏱️Best Time:{time_text}\n\n"
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

def build_ranking_text(user_id=None):
    docs = db.collection("users").stream()
    rating_ranking = []
    time_ranking = []
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

        best_time = data.get("best_time")
        if best_time is None:
            best_time_val = float('inf')
        else:
            best_time_val = float(best_time)

        rating_ranking.append((doc.id, name, total_rate))
        time_ranking.append((doc.id, name, best_time_val))

    rating_ranking.sort(key=lambda x: x[2], reverse=True)
    time_ranking.sort(key=lambda x: x[2])  # タイムは小さい方が良い

    text = "\n🏆 Rating Ranking 🏆\n"
    user_index_rate = None
    for i, (uid, name, rate) in enumerate(rating_ranking, 1):
        if i <= 3:
            text += f"{i}. {name} - {rate}\n"
        if user_id and uid == user_id:
            user_index_rate = i - 1

    if user_index_rate is not None:
        my_rank = user_index_rate + 1
        my_name = rating_ranking[user_index_rate][1]
        my_rate = rating_ranking[user_index_rate][2]
        text += "\n---------------------\n"
        text += f"あなたの順位: {my_rank}位  {my_rate}\n"
        if my_rank <= 3:
            text += "あなたは表彰台に乗っています！\n"
        elif my_rank > 3:
            above_name = rating_ranking[user_index_rate - 1][1]
            above_rate = rating_ranking[user_index_rate - 1][2]
            diff = above_rate - my_rate
            text += f"↑次の順位の {above_name} まで {diff} レート差\n"

    text += "\n⏱️ Time Ranking ⏱️\n"
    user_index_time = None
    for i, (uid, name, t) in enumerate(time_ranking, 1):
        if i <= 3:
            if t == float('inf'):
                time_display = "未記録"
            else:
                time_display = f"{t:.2f}秒"
            text += f"{i}. {name} - {time_display}\n"
        if user_id and uid == user_id:
            user_index_time = i - 1

    if user_index_time is not None:
        my_rank = user_index_time + 1
        my_name = time_ranking[user_index_time][1]
        my_time = time_ranking[user_index_time][2]
        text += "\n---------------------\n"
        time_display = "未記録" if my_time == float('inf') else f"{my_time:.2f}秒"
        text += f"あなたの順位: {my_rank}位  {time_display}\n"
        if my_rank <= 3:
            text += "あなたは表彰台に乗っています！\n"
        elif my_rank > 3 and my_time != float('inf'):
            above_name = time_ranking[user_index_time - 1][1]
            above_time = time_ranking[user_index_time - 1][2]
            diff = above_time - my_time
            text += f"↑次の順位の {above_name} まで {diff:.2f}秒差\n"

    return text.strip()

# 10問クイズの進捗とペナルティ時間を管理
user_quiz_progress = defaultdict(lambda: {"count": 0, "start_time": None, "penalty_time": 0})

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
        text = build_ranking_text(user_id)
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=text))
        return

    if msg in ["1-1000", "1001-1935"]:
        questions = questions_1_1000 if msg == "1-1000" else questions_1001_1935
        q = choose_weighted_question(user_id, questions)
        user_states[user_id] = (msg, q["answer"])

        # クイズ進捗・開始時間などを初期化（リセットはしない）
        user_quiz_progress[user_id] = {"count": 0, "start_time": time.time(), "penalty_time": 0}

        progress_text = "🔥Go!\n1/10\n"
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=f"{progress_text}\n{q['text']}")
        )
        return

    if msg == "成績":
        text = build_result_text(user_id)
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=text))
        return

    if msg == "把握度":
        text = build_grasp_text(user_id)
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=text))
        return
    # クイズ回答処理
    if user_id in user_states:
        range_str, correct_answer = user_states[user_id]
        user_answer = msg.strip().lower()
        
        # 回答統計
        if user_id not in user_stats:
            user_stats[user_id] = {"correct": 0, "incorrect": 0}
        if user_id not in user_quiz_progress:
            user_quiz_progress[user_id] = {"count": 0, "start_time": None, "penalty_time": 0}

        progress = user_quiz_progress[user_id]

        response = ""

        if user_answer == correct_answer:
                user_stats[user_id][range_str]["correct"] += 1
                response = "✅Correct！"
        else:
                penalty = 10
                user_quiz_progress[user_id]["penalty_time"] += penalty
                correct_answer = user_states[user_id][1]  # 正解を取得
                response = f"❌Wrong +{penalty}s\nCorrect answer: {correct_answer}"

        user_stats[user_id][range_str]["total"] += 1

        # 正誤問わずカウント進める
        user_quiz_progress[user_id]["count"] += 1
        count = user_quiz_progress[user_id]["count"]

        elapsed_time = time.time() - user_quiz_progress[user_id]["start_time"] + user_quiz_progress[user_id]["penalty_time"]
        if count < 10:
            response += f"\n{count + 1}/10\n{elapsed_time:.2f}s"

        if count >= 10:
                total_time = elapsed_time
                best_time = user_times.get(user_id, float('inf'))
                if total_time < best_time:
                        user_times[user_id] = total_time
                        async_save_user_data(user_id)
                        response += f"\n🎉おめでとう！ベストタイム更新"

                response += f"\n\nFINISH！\nTime: {total_time:.2f}秒"
                response += "\n「ランキング」でランキング表示、「1-1000」か「1001-1935」で新しいクイズ開始。"
                user_states.pop(user_id, None)
                user_quiz_progress.pop(user_id, None)

                line_bot_api.reply_message(event.reply_token, TextSendMessage(text=response))
                return

        # 次の問題を出題
        questions = questions_1_1000 if range_str == "1-1000" else questions_1001_1935
        next_q = choose_weighted_question(user_id, questions)
        user_states[user_id] = (range_str, next_q["answer"])

        # ✅ progress_text を使わず、直接テキスト構成
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=response + "\n\n" + next_q["text"])
        )
        return


    # 未知のメッセージはヘルプ案内
    help_text = (
        "コマンド一覧:\n"
        "「1-1000」または「1001-1935」でクイズ開始\n"
        "「成績」で現在の成績表示\n"
        "「把握度」で単語把握度表示\n"
        "「ランキング」でランキング表示\n"
        "「@(名前)」で名前変更\n"
    )
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=help_text))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port)
