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

user_states = {}  # 出題中のユーザーと正解
user_scores = defaultdict(dict)  # user_scores[user_id][単語] = 0~4のスコア（初期値0）
user_total_questions = defaultdict(lambda: {"1-1000": 0, "1000-1935": 0})
user_total_corrects = defaultdict(lambda: {"1-1000": 0, "1000-1935": 0})

# --- 問題リスト ---
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

questions_1000_1935 = [
    {"text": "1001 The ___ made a critical discovery in the lab.\nその科学者は研究室で重大な発見をした。", "answer": "scientist"},
]

def get_rank(score):
    return {0: "D", 1: "C", 2: "B", 3: "A", 4: "S"}[score]

def score_to_weight(score):
    return {0: 5, 1: 4, 2: 3, 3: 2, 4: 1}.get(score, 5)

def build_result_text(user_id):
    result = ""
    for title, questions in [("1-1000", questions_1_1000), ("1000-1935", questions_1000_1935)]:
        scores = user_scores.get(user_id, {})
        total_score = 0
        word_count = 0
        for q in questions:
            ans = q["answer"]
            s = scores.get(ans, 0)
            total_score += s
            word_count += 1

        correct = user_total_corrects[user_id][title]
        total = user_total_questions[user_id][title]

        if word_count == 0:
            result += f"📑成績（{title}）\nNo data\n\n"
            continue

        rate = round((total_score / word_count) * 10000)
        if rate >= 9700:
            rank = "S"
        elif rate >= 9000:
            rank = "A"
        elif rate >= 8000:
            rank = "B"
        elif rate >= 5000:
            rank = "C"
        else:
            rank = "D"

        result += (
            f"📑成績（{title}）\n"
            f"✅ 総正解数 / 総出題数：{correct} / {total}\n"
            f"📈 レート：{rate}\n"
            f"🏆 ランク：{rank}\n\n"
        )
    return result.strip()

def build_grasp_text(user_id):
    scores = user_scores.get(user_id, {})
    rank_counts = {"S": 0, "A": 0, "B": 0, "C": 0, "D": 0}
    all_answers = [q["answer"] for q in questions_1_1000 + questions_1000_1935]

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

    if msg == "成績":
        text = build_result_text(user_id)
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=text))
        return

    if msg == "把握度":
        text = build_grasp_text(user_id)
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=text))
        return

    if msg == "1-1000":
        q = choose_weighted_question(user_id, questions_1_1000)
        user_states[user_id] = ("1-1000", q["answer"])
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=q["text"]))
        return

    if msg == "1000-1935":
        q = choose_weighted_question(user_id, questions_1000_1935)
        user_states[user_id] = ("1000-1935", q["answer"])
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=q["text"]))
        return

    if user_id in user_states:
        question_range, correct_answer = user_states[user_id]
        is_correct = (msg.lower() == correct_answer.lower())
        scores = user_scores[user_id]

        if correct_answer not in scores:
            scores[correct_answer] = 0

        # 出題数 +1（回答したらカウント）
        user_total_questions[user_id][question_range] += 1

        if is_correct:
            scores[correct_answer] = min(4, scores[correct_answer] + 1)
            user_total_corrects[user_id][question_range] += 1
        else:
            scores[correct_answer] = max(0, scores[correct_answer] - 1)

        user_scores[user_id] = scores

        feedback = (
            "Correct✅\nNext:" if is_correct else f"Wrong❌\nAnswer: {correct_answer}\n\nNext:"
        )

        next_q = choose_weighted_question(
            user_id, questions_1_1000 if question_range == "1-1000" else questions_1000_1935
        )
        user_states[user_id] = (question_range, next_q["answer"])

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
        TextSendMessage(text="1-1000 または 1000-1935 を送信してね！")
    )

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port)
