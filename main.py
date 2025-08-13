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

DEFAULT_NAME = "名前はまだない。"

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
    {"text": "002 He strongly o___ corruption until he was promoted.\n昇進するまでは,彼は汚職に強く反対していた.",
     "answer": "opposed"},
    {"text": "003 The teacher a___ me to study English vocabulary.\n先生は私に英単語を勉強するよう助言した.",
     "answer": "advised"},
    {"text": "004 I’ll give you a t__.\nヒントをあげるよ.",
     "answer": "tip"},
    {"text": "005 We d___ the problem so much, we forgot to solve it.\n私たちはその問題についてあまりに議論しすぎて,解決するのを忘れていた.",
     "answer": "discussed"},
    {"text": "006 He b___ the train for his lateness.\n彼は遅刻したことを電車のせいにした.",
     "answer": "blamed"},
    {"text": "007 Einstein a___ that time is relative.\nアインシュタインは時間は相対的だと論じた.",
     "answer": "argued"},
    {"text": "008 He c___ that sleep wasn’t necessary for eaxms.\n彼は試験のために睡眠は必要ないと主張した.",
     "answer": "claimed"},
    {"text": "009 He c___ about buying a math textbook he’d never use.\n彼は使うことのない数学の教科書を買うことに不満を言っていた.",
     "answer": "complained"},
    {"text": "010 Einstein was o___ the presidency of Israel but he refused.\nアインシュタインはイスラエル大統領の職を申し出られたが、断った。",
     "answer": "offered"},
    {"text": "011 He s___ that he was gay.\n彼は自身がゲイであることをほのめかした。",
     "answer": "suggested"},
    {"text": "012 I was r___ to the local volunteer club.\n私は地元のボランティアクラブに推薦された。",
     "answer": "recommended"},
    {"text": "013 He said he was g___ to her for the feedback, but he ignored all of it.\n彼は彼女のフィードバックに感謝していると言ったが,すべて無視した.",
     "answer": "grateful"},
    {"text": "014 I a___ for criticizing.\n私は批判したことを謝った.",
     "answer": "apologized"},
    {"text": "016 His family c___ his finally being accepted into college.\n彼の家族は,彼がついに大学に合格したことを祝った.",
     "answer": "celebrated"},
    {"text": """019 She was a___ "Best Excuse Maker" for always avoiding responsibility.\n彼女は常に責任を避けたことで「最高の言い訳メーカー」を受賞した.""",
     "answer": "awarded"},
    {"text": """020 They d___ ignoring the group project as "respecting individual effort."\n彼らはグループ課題を無視することを「個人の努力を尊重する」と表現しました.""",
     "answer": "described"},
    {"text": "021 He e___ why he had missed the deadline.\n彼はなぜ締め切りを過ぎたのか説明した.",
     "answer": "explained"},
    {"text": "022 It is important to c___ effectively with others in a team.\nチームで効果的にコミュ二ケーションをとることは重要だ.",
     "answer": "communicate"},
    {"text": "024 The man running ahead is the one I p___ to run with.\n前を走っている男は,一緒に走ると約束した人だ.",
     "answer": "promised"},
    {"text": "025 He provided a lot of i___, none of which was useful.\n彼はたくさんの情報を提供したが,役に立つものはひとつもなかった.",
     "answer": "information"},
    {"text": "026 With modern t___, we can talk to anyone in the world except the person next to you.\n現代のテクノロジーでは,隣にいる人以外の誰とでも話すことができる.",
     "answer": "technology"},
    {"text": "027 r___ shows that sunlight improves mental health.\n研究によると,日光はメンタルヘルスを改善する.",
     "answer": "research"},
    {"text": "029 People who can be replaced by a___ Intelligence\nAIに代替可能な人.",
     "answer": "artificial"},
    {"text": "031 Ancient Egyptians i___ the 365-day calendar.\n古代エジプト人は365日カレンダーを発明した。",
     "answer": "invented"},
    {"text": "034 He had the s___ to disappear whenever work started.\n彼は仕事が始まるといつも消える技術があった.",
     "answer": "skill"},
    {"text": "035 No less important than knowledge is the a___ to question it.\n知識に劣らず重要なのは,それを疑問視する能力です.",
     "answer": "ability"},
    {"text": "037 Success often comes after continuous e___.\n成功はたいてい継続的な努力の後にやってくる.",
     "answer": "effort"},
    {"text": "043 This machine can p___ 10 parts in one minute.\nこの機械は１分で10個の部品を生産出来る.",
     "answer": "produce"},
    {"text": "044 c___ LINE stickers using the teather's face\n先生の顔でLINEスタンプを作る",
     "answer": "create"},
    {"text": "045 Kitano high school was e___ in 1873.\n北野高校は1873年に設立された.",
     "answer": "established"},
    {"text": "058 War is peace. Freedom is slavery. Ignorance is s___.\n戦争は平和。自由は隷従。無知は力。(1984年)",
     "answer": "strength"},
    {"text": "066 Even a small change can have a great effect on s___.\n小さな変化でも社会に大きな影響を与える.",
     "answer": "society"},
    {"text": "067 The code of Hammurabi is one of the oldest l___.\nハンムラビ法典(規定)は最古の法律の一つ。",
     "answer": "laws"},
    {"text": "068 We don't inherit the Earth from our a___, we borrow it from our children.\n私たちは先祖から地球を受け継ぐのではなく,子供たちから借りています.",
     "answer": "ancestors"},
    {"text": "074 the key e___ that led to the suspension \n停学への決定打となる証拠",
     "answer": "evidence"},
    {"text": "079 They v___ for confidence without thinking.\n彼らは考えずに信任に投票した.",
     "answer": "voted"},
    {"text": "085 The p___ is determined by supply and demand.\n価格は需要と供給で決まる.",
     "answer": "price"},
    {"text": "096 During World War II, British chess masters were assigned to codebreaking t___ involving the Enigma machine.\n\n第二次世界大戦中,イギリスのチェスマスターたちはエニグマ機に関わる暗号解読の仕事に就いていました.",
     "answer": "tasks"},
    {"text": "098 What you said h___ more than you think.\n君が言ったことは,君が思っているよりも傷ついたよ.",
     "answer": "hurt"},
    {"text": "101 d___ the pen of the person sitting next to me\n隣の席の人のペンを破壊する",
     "answer": "destroy"},
    {"text": "111 The captain rescued only the p___ from his own country.\n船長は自国の乗客だけを救出しました.",
     "answer": "passengers"},
    {"text": "115 He climbed the ladder of success, then kicked it away so no one else could f___.\n彼は成功のはしごを登り,それを蹴飛ばし,他の誰も追随できないようにした.",
     "answer": "follow"},
    {"text": "116 Not all who w___ are lost.\n彷徨う人全員が迷っているわけではない.",
     "answer": "wander"},
    {"text": """124 She was awarded "Best Excuse Maker" for always a___ responsibility.\n彼女は常に責任を避けたことで「最高の言い訳メーカー」を受賞した.""",
     "answer": "avoiding"},
    {"text": "127 Complex i___ compose themselves of simple, ignored mistakes.\n複雑な問題は,無視された単純なミスから成り立っている.",
     "answer": "issues"},
    {"text": "135 He explaind why he had m___ the deadline.\n彼はなぜ締め切りを過ぎたのか説明した.",
     "answer": "missed"},
    {"text": "137 He m___ silence for wisdom, and loudness for leadership.\n彼は沈黙を賢さと勘違いし,声の大きさをリーダーシップと勘違いした.",
     "answer": "mistook"},
    {"text": "150 p___ to understand\nわかっているふりをする",
     "answer": "pretend"},
    {"text": "154 It is not what h___ that matters. It is how you respond.\n大事なのは何が起きたかではない.どう応じるかだ.",
     "answer": "happened"},
    {"text": "153 e___ Juso after school\n放課後,十三を探検する",
     "answer": "explore"},
    {"text": "155 More and more problems a___.\nますます多くの問題が現れた.",
     "answer": "appeared"},
    {"text": "163 The captain rescued only the passengers from his o___ country.\n船長は自国の乗客だけを救出しました.",
     "answer": "own"},
    {"text": "167 h___ is written by the victors.\n歴史は勝者によって書かれる.",
     "answer": "history"}, 
    {"text": "170 No less important than k___ is the ability to question it.\n知識に劣らず重要なのは,それを疑問視する能力です.",
     "answer": "knowledge"},
    {"text": "189 His family celebrated his finally being ___ into college.\n彼の家族は,彼がついに大学に合格したことを祝った.",
     "answer": "accepted"},
    {"text": "197 First Olympic games a___ only naked men.\n初期オリンピックは裸の男性だけ参加できた。",
     "answer": "allowed"},
    {"text": "209 He s___ to side with the insects.\n彼はその虫の味方をするようだ.",
     "answer": "seems"},
    {"text": "241 It is not what happened that m____. It is how you respond.\n大事なのは何が起きたかではない.どう応じるかだ.",
     "answer": "matters"},
    {"text": "258 People tend to accept ideas not because they are true, but because they are f___.\n人々はアイデアが真実だからではなく,馴染みがあるから受け入れる傾向があります.",
     "answer": "familiar"},
    {"text": "269 Don’t c___ your chickens before they hatch.\n卵がかえる前にヒヨコを数えるな",
     "answer": "count"},
    {"text": "284 A:What movie has no kissing s___?\nB:Your life.\n\nA:キスシーンの無い映画は？",
     "answer": "scenes"},
    {"text": "311 If you put w___ on a grandma, can you call it a bicycle?\nおばあちゃんに車輪を付けたら,自転車と呼べるのか.",
     "answer": "wheels"},
    {"text":"335 r__, r__, r__ your boat\nGently down the stream\nMerrily, merrily, merrily, merrily\nLife is but a dream\n\nボートを漕げ、漕げ、漕げ\nそっと流れを下って\n陽気に、陽気に、陽気に、陽気に\n人生は夢に過ぎない",
     "answer": "row"},
    {"text": "323 He p___ more than just money to buy his daughter an instrument.\n彼は娘に楽器を買うためにお金以上のものを支払った。",
     "answer": "paid"},
    {"text": "338 I want to transfer to the a___ course.\n美術コースに転向したい.",
     "answer": "art"},
    {"text": "342 He paid more than just money to buy his daughter an i___.\n彼は娘に楽器を買うためにお金以上のものを支払った。",
     "answer": "instrument"},
    {"text": "344 the challenge of having to create example s___ to protect copyright\n著作権保護のため例文を作らなければならないという課題",
     "answer": "sentences"},
    {"text": "347 The teacher advised me to study English v___.\n先生は私に英単語を勉強するよう助言した.",
     "answer": "vocabulary"},
    {"text": "356 What we see d___ not only on what we look at, but also on where we look from.\n私たちが見るものは,何を見るかだけでなく,どこから見るかによっても異なります.",
     "answer": "depends"},
    {"text": "359 The locals were amazed by the car they had never seen before and b___, but it was a driverless\n\n現地の人々は初めての車に驚き,物乞いをしたが,無人自動車だった.",
     "answer": "begged"},
    {"text": "360 The truth is often simple, but people p___ complex answers.\n真実はしばしば単純ですが,人々は複雑な答えを好みます.",
     "answer": "prefer"},
    {"text": "378 Even a small change can have a great e___ on society.\n小さな変化でも社会に大きな影響を与える.",
     "answer": "effect"},
    {"text": "393 e___ a small change can have a great effect on society.\n小さな変化でも社会に大きな影響を与える.",
     "answer": "even"},
    {"text": "400 With modern technology, we can talk to anyone in the world e___ the person next to you.\n現代のテクノロジーでは,隣にいる人以外の誰とでも話すことができる.",
     "answer": "except"},
    {"text": "402 I apologized for c___.\n私は批判したことを謝った.",
     "answer": "criticizing"},
    {"text": "420 It is not what happened that matters. It is how you r___.\n大事なのは何が起きたかではない.どう応じるかだ.",
     "answer": "respond"},
    {"text": "434 He’s been p___ her aunt for months\n彼は何か月も彼女のおばを狙っています.",
     "answer": "pursuing"},
    {"text": "440 the c___ of having to create example sentences to protect copyright\n著作権保護のため例文を作らなければならないという課題",
     "answer": "challenge"},
    {"text": "443 Is his face p___ or has it always been p___?\n彼は青ざめているのか,いつも青白いのか.",
     "answer": "pale"},
    {"text": "449 He was conscious during the entire s___.\n彼は手術中ずっと意識があった.\n😱",
     "answer": "surgery"},
    {"text": "479 All animals are e___, but some animals are more e___ than others.\n全ての動物は平等だが、中には他よりもっと平等な動物もいる。",
     "answer": "equal"},
    {"text": """495 They described ignoring the group project as "respecting ___ effort."\n彼らはグループ課題を無視することを「個人の努力を尊重する」と表現しました.""",
     "answer": "individual"},
    {"text": "500 The consumption tax should be a___.\n消費税は廃止されるべきだ.",
     "answer": "abolished"},
    {"text": "512 Scholarships help students pay for college tuition and e___.\n奨学金は学生が大学の授業料や費用を支払うのを助ける。",
     "answer": "expenses"},
    {"text": "527 During World War II, British chess masters were a___ to codebreaking tasks involving the Enigma machine.\n第二次世界大戦中,イギリスのチェスマスターたちはエニグマ機に関わる暗号解読の仕事に就いていました.",
     "answer": "assigned"},
    {"text": "539 The road to success is under c___.\n成功への道は工事中だ.",
     "answer": "construction"},
    {"text": "545 Complex issues c___ themselves of simple, ignored mistakes.\n複雑な問題は,無視された単純なミスから成り立っている.",
     "answer": "compose"},
    {"text": "546 Ideas a___ quickest to the minds already half convinced.\n考えは半分納得した心に一番早くくっつく.",
     "answer": "attach"},
    {"text": "567 Honey never s___.\nはちみつは腐りません.",
     "answer": "spoils"},
    {"text": "568 The Colosseum could hold up to 50,000 s___.\nコロッセオは5万人まで収容可能だった。",
     "answer": "spectators"},
    {"text": "569 [2]Einstein argued that time is r___.\nアインシュタインは時間は相対的だと論じた.",
     "answer": "relative"},
    {"text": "594 Einstein was offered the presidency of Israel but he r___.\nアインシュタインはイスラエル大統領の職を申し出られたが、断った。",
     "answer": "refused"},
    {"text": "597 Ideas attach quickest to the minds already half c___.\n考えは半分納得した心に一番早くくっつく.",
     "answer": "convinced"},
    {"text": "604 Fake news s___ faster than real news.\n フェイクニュースは本当のニュースより速く拡散する.",
     "answer": "spreads"},
    {"text": "610 I can r___ everything except temptation.\n私は誘惑以外の全てに耐えうる.",
     "answer": "resist"},
    {"text": "627  A job that requires constant b___\nおじぎし続ける仕事",
     "answer": "bowing"},
    {"text": "639 s___ while the iron is hot\n鉄は熱いうちに打て",
     "answer": "strike"},
    {"text": "654 Sharks e___ before trees on Earth.\nサメは地球上に木より先に存在した。",
     "answer": "existed"},
    {"text": "658 During World War II, British chess masters were assigned to codebreaking tasks i___ the Enigma machine.\n第二次世界大戦中,イギリスのチェスマスターたちはエニグマ機に関わる暗号解読の仕事に就いていました.",
     "answer": "involving"},
    {"text": "659 A job that r___ constant bowing\nおじぎし続ける仕事",
     "answer": "requires"},
    {"text": "662 The shortest war l___ 38 minutes.\n最短の戦争は38分間だった.",
     "answer": "lasted"},
    {"text": "669 r___ invitation\n同窓会の案内状",
     "answer": "reunion"},
    {"text": "671 L___ is the basis of clear thinking and good arguments.\n論理は明晰な思考と良い議論の基礎である。",
     "answer": "logic"},
    {"text": "673 The price is d___ by supply and demand.\n価格は需要と供給で決まる.",
     "answer": "determined"},
    {"text": "685 Did you n___ the changes in the schedule?\nスケジュールの変更には気付いた？",
     "answer": "notice"},
    {"text": "687 He was c___ during the entire surgery.\n彼は手術中ずっと意識があった.\n😱",
     "answer": "conscious"},
    {"text": "689 She is r___ as the best teacher in the school.\n彼女は学校で一番の教師とみなされている.",
     "answer": "regarded"},
    {"text": "690 He committed himself to finishing the marathon.\n彼はマラソンを完走する事を決意した.",
     "answer": "committed"},
    {"text": "694 What is taken for g___ today was once a revolutionary idea.\n今日当たり前のように考えられているものは,かつては革新的なアイデアでした.",
     "answer": "granted"},
    {"text": "709 Eurasia developed faster because it stretches east to west, so c___ could spread in similar climates.\nユーラシアは東西に広がっているため、作物が似た気候の中で広まりやすく、より早く発展した。",
     "answer": "crops"},
    {"text": "714 Eurasia developed faster because it stretches east to west, so crops could spread in similar c___.\nユーラシアは東西に広がっているため、作物が似た気候の中で広まりやすく、より早く発展した。",
     "answer": "climates"},
    {"text": "762 The turtle is not s___ about who gets first in the contest. He simply finds pleasure in the steady walk.\nカメはコンテストで誰が一番になるかを気にしていません。ただ、着実な歩みを楽しんでいるのです。",
     "answer": "serious"},
    {"text": "763 C___ issues compose themselves of simple, ignored mistakes.\n複雑な問題は,無視された単純なミスから成り立っている.",
     "answer": "complex"},
    {"text": "779 The turtle is not serious about who gets first in the contest. He simply finds pleasure in the s___ walk.\nカメはコンテストで誰が一番になるかを気にしていません。ただ、着実な歩みを楽しんでいるのです。",
     "answer": "steady"},
    {"text": "791 F___ news spreads faster than real news.\n フェイクニュースは本当のニュースより速く拡散する.",
     "answer": "fake"},
    {"text": "808 First Olympic games allowed only n___ men.\n初期オリンピックは裸の男性だけ参加できた。",
     "answer": "naked"},
    {"text": "820 People t___ to accept ideas not because they are true, but because they are familiar.\n人々はアイデアが真実だからではなく,馴染みがあるから受け入れる傾向があります.",
     "answer": "tend"},
    {"text": "860 The price is determined by s___ and demand.\n価格は需要と供給で決まる.",
     "answer": "supply"},
    {"text": "861 People who can be r___ by Artificial Intelligence\nAIに代替可能な人.",
     "answer": "replaced"},
    {"text": "892 v___ m___\n 自動販売機",
     "answer": "vending machine"},
    {"text": "901 I want to t___ to the art course.\n美術コースに転向したい.",
     "answer": "transfer"},
    {"text": """978 They described i___ the group project as "respecting individual effort".\n彼らはグループ課題を無視することを「個人の努力を尊重する」と表現しました.""",
     "answer": "ignoring"},
    {"text": "992 We shape our tools, and e___, our tools shape us.\n私たちは道具を作るが,結果として,道具が私たちを作る.",
     "answer": "eventually"},
    {"text": "993 He argued that sleep wasn’t n___ for eaxms.\n彼は試験のために睡眠は必要ないと主張した.",
     "answer": "necessary"},
    {"text": "978 Complex issues compose themselves of simple, i___ mistakes.\n複雑な問題は,無視された単純なミスから成り立っている.",
     "answer": "ignored"},
    {"text": "1000 a___ t__ capitalism, your value peaks at checkout.\n資本主義によると,あなたの価値はチェックアウト時にピークに達する.",
     "answer": "according to"},
    {"text": "782 m___ woman\n大物熟女",
     "answer": "mature"},
]
questions_1001_1935 = [
    {"text": "1001 The ___ made a critical discovery in the lab.\nその科学者は研究室で重大な発見をした。",
     "answer": "scientist"},
    {"text": "1054 The ___ of Hammurabi is one of the oldest laws.\nハンムラビ法典(規定)は最古の法律の一つ。",
     "answer": "code"},
    {"text": "1110 Logic is the ___ of clear thinking and good arguments.\n論理は明晰な思考と良い議論の基礎である。",
     "answer": "basis"},
    {"text": "1247 Don’t count your chickens before they ___.\n卵がかえる前にヒヨコを数えるな",
     "answer": "hatch"},
    {"text": "1386 He was conscious during the ___ surgery.\n彼は手術中ずっと意識があった.\n😱",
     "answer": "entire"},
    {"text": "1671 Scholarships help students pay for college ___ and expenses.\n奨学金は学生が大学の授業料や費用を支払うのを助ける。",
     "answer": "tuition"},
    
]
#Dreams are free; reality charges you interest every day.

def get_rank(score):
    return {0: "D", 1: "C", 2: "B", 3: "A", 4: "S"}.get(score, "D")

def score_to_weight(score):
    return {0: 16, 1: 8, 2: 4, 3: 2, 4: 1}.get(score, 16)

from linebot.models import BoxComponent, TextComponent

def build_result_flex(user_id):
    name = user_names.get(user_id, DEFAULT_NAME)

    # 各範囲の評価計算
    parts = []
    for title, questions in [("1-1000", questions_1_1000), ("1001-1935", questions_1001_1935)]:
        scores = user_scores.get(user_id, {})
        relevant_answers = [q["answer"] for q in questions]
        total_score = sum(scores.get(ans, 0) for ans in relevant_answers)
        count = len(relevant_answers)

        rate = round((total_score / count) * 2500) if count else 0
        if rate >= 9900:
            rank = "S🤯"
        elif rate >= 9000:
            rank = "A+🤩"
        elif rate >= 8000:
            rank = "A🤩"
        elif rate >= 7000:
            rank = "A-🤩"
        elif rate >= 6000:
            rank = "B+😎"
        elif rate >= 5000:
            rank = "B😎"
        elif rate >= 4000:
            rank = "B-😎"
        elif rate >= 3000:
            rank = "C+😍"
        elif rate >= 2000:
            rank = "C😍"
        elif rate >= 1000:
            rank = "C-😍"
        else:
            rank = "D🫠"

        parts.append({
            "type": "box",
            "layout": "vertical",
            "margin": "md",
            "contents": [
                {"type": "text", "text": title, "weight": "bold", "size": "sm", "color": "#000000"},
                {"type": "text", "text": f"Rating: {rate}", "size": "md", "color": "#333333"},
                {"type": "text", "text": f"{rank}", "size": "md", "color": "#333333"},
            ],
        })

    # 合計レート計算
    c1 = len(questions_1_1000)
    c2 = len(questions_1001_1935)
    rate1 = round((sum(user_scores.get(user_id, {}).get(q["answer"], 0) for q in questions_1_1000) / c1) * 2500) if c1 else 0
    rate2 = round((sum(user_scores.get(user_id, {}).get(q["answer"], 0) for q in questions_1001_1935) / c2) * 2500) if c2 else 0
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
                    {
                        "type": "separator",
                        "margin": "md"
                    },
                    {
                        "type": "text",
                        "text": f"Total Rating: {total_rate}",
                        "weight": "bold",
                        "size": "md",
                        "color": "#000000",
                        "margin": "md"
                    },
                    {
                        "type": "text",
                        "text": "名前変更は「@(新しい名前)」で送信してください。",
                        "size": "sm",
                        "color": "#666666",
                        "margin": "lg",
                        "wrap": True
                    }
                ]
            }
        }
    )
    return flex_message

#FEEDBACK　flex
def build_feedback_flex(is_correct, score, elapsed, rank, correct_answer=None, label=None):
    body_contents = []

    if is_correct:
        if label is None:
            label, color = "?", "#000000"
        else:
            color_map = {"!!":"#40e0d0", "!":"#6495ed", "✓":"#32cd32", "?":"#ffd700"}
            color = color_map.get(label, "#000000")

        body_contents.append({
            "type": "text",
            "text": label,
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

    body_contents.extend([
        {
            "type": "text",
            "text": f"解く前:{rank}",
            "size": "md",
            "color": "#000000",
            "margin": "md"
        },
        {
            "type": "text",
            "text": f"{elapsed:.1f}s",
            "size": "md",
            "color": "#000000",
            "margin": "sm"
        }
    ])

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
    "🎅低浮上サンタ\n私は5回に1回出てきます。",
    "🎅低浮上サンタ\n私は5回に1回出てきます。",
    "🎅低浮上サンタ\n継続は力なり。",
    "🎅低浮上サンタ\n継続は力なり。",
    "🎅低浮上サンタ\n勉強して下さい。",
    "🎅低浮上サンタ\n勉強して下さい。",
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
    "🎅低浮上サンタ\n@新しい名前　でランキングに表示される名前を変更できます。",
    "🎅低浮上サンタ\n辞書に載っている最長単語は「pneumonoultramicroscopicsilicovolcanoconiosis」（超微細な火山性シリカの粉塵による肺の病気）。",
    "🎅低浮上サンタ\n「set」は約430の意味を持っていて、最も多様な意味を持つ英単語と言われています。",
    "🎅低浮上サンタ\n口を大きく開けずに済むので「I am」→「I'm」となりました。",
    "🎅低浮上サンタ\n昔の英語では「knight」は「k」をちゃんと発音していました。",
]

def evaluate_label(elapsed, score):
    """
    ラベルと加算deltaを返す
    elapsed: 回答までの秒数
    score: 現在のスコア
    """
    # 例: 超高速は !!、速めは !、普通は ✓、遅いと ?
    if elapsed < 5:
        return "!!", 3
    elif elapsed < 20:
        return "!", 2
    elif elapsed > 60:
        return "?", 0
    else:
        return "✓", 1


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
            size = "md"
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
                {"type": "text", "text": f"#{i}", "flex": 1, "weight": "bold", "size": size, "color": color},
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
                    {"type": "text", "text": "あなたは表彰台に乗っています!", "flex": 3, "weight": "bold","size": "sm"},
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
                    {"type": "text", "text": f"{user_index+1}位 {name}", "flex": 3, "weight": "bold"},
                    {"type": "text", "text": str(rate), "flex": 1, "align": "end"}
                ]
            })
            contents.append({
                "type": "text",
                "text": f"{user_index}位の{above_name}まで {diff} 差",
                "margin": "md",
                "size": "sm",
                "color": "#000000"
            })

    flex_message = FlexSendMessage(
        alt_text="Rating",
        contents={
            "type": "bubble",
            "body": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {"type": "text", "text": "Rating", "weight": "bold", "size": "xl", "align": "center"},
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

def send_question(user_id, reply_token, questions, range_str):
    q = choose_weighted_question(user_id, questions)
    user_states[user_id] = (range_str, q["answer"])
    user_answer_start_times[user_id] = time.time()  # 出題時刻記録
    line_bot_api.reply_message(reply_token, TextSendMessage(text=q["text"]))

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
        user_answer_start_times[user_id] = time.time() 
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=q["text"]))
        return

    if msg == "成績":
        flex_msg = build_result_flex(user_id)
        line_bot_api.reply_message(event.reply_token, flex_msg)
        return

    if msg == "把握度":
        text = build_grasp_text(user_id)
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=text))
        return

    if user_id in user_states:
        range_str, correct_answer = user_states[user_id]
        is_correct = (msg.lower() == correct_answer.lower())
        score = user_scores[user_id].get(correct_answer, 0)

        start_time = user_answer_start_times.get(user_id)
        elapsed = time.time() - start_time if start_time else 0

    # ここを evaluate_X → evaluate_label に変更
        label, delta = evaluate_label(elapsed, score)

        if is_correct:
            rank = get_rank(score)
            user_scores[user_id][correct_answer] = min(4, score + delta)
        else:
            rank = get_rank(score)
            user_scores[user_id][correct_answer] = max(0, score - 1)

        # フィードバックを作成
        flex_feedback = build_feedback_flex(
            is_correct, score, elapsed, rank,
            correct_answer, label if is_correct else None
        )

        # 次の問題を出題
        questions = questions_1_1000 if range_str == "1-1000" else questions_1001_1935
        next_q = choose_weighted_question(user_id, questions)
        user_states[user_id] = (range_str, next_q["answer"])
        user_answer_start_times[user_id] = time.time()
        user_answer_counts[user_id] += 1

        if user_answer_counts[user_id] % 5 == 0:
            trivia = random.choice(trivia_messages)
            line_bot_api.reply_message(
                event.reply_token,
                messages=[
                    flex_feedback,
                    TextSendMessage(text=trivia),
                    TextSendMessage(text=next_q["text"])
                ],
            )
        else:
            line_bot_api.reply_message(
                event.reply_token,
                messages=[
                    flex_feedback,
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
