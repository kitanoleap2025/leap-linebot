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

DEFAULT_NAME = "イキイキした毎日"

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
     "answer": "agree",
    "meaning": "agree	[自] ①賛成する ②（主語の中で）意見が一致する ③（with ～）（気候，食べ物が）（～に）合う"},
    {"text": "002 He strongly o___ corruption until he was promoted.\n昇進するまでは,彼は汚職に強く反対していた.",
     "answer": "opposed",
    "meaning": "oppose	[他] ～に反対する"},
    {"text": "003 The teacher a___ me to study English vocabulary.\n先生は私に英単語を勉強するよう助言した.",
     "answer": "advised",
    "meaning": "advise	[他] ～に忠告する"},
    {"text": "004 I’ll give you a t__.\nヒントをあげるよ.",
     "answer": "tip",
    "meaning": "tip	[名] ①助言，ヒント ②チップ ③（足や山などの）先，先端（いずれも〈可算〉）"},
    {"text": "005 We d___ the problem so much, we forgot to solve it.\n私たちはその問題についてあまりに議論しすぎて,解決するのを忘れていた.",
     "answer": "discussed",
    "meaning": "discuss	[他] ①～について話し合う，議論する ②～を話題に出す"},
    {"text": "006 He b___ the train for his lateness.\n彼は遅刻したことを電車のせいにした.",
     "answer": "blamed",
    "meaning": "blame	[他] ～に責任があるとする"},
    {"text": "007 Einstein a___ that time is relative.\nアインシュタインは時間は相対的だと論じた.",
     "answer": "argued",
    "meaning": "argue	[他] ①（that SV）～と主張する [自] ②（with ～）（～と）言い争う"},
    {"text": "008 He c___ that sleep wasn’t necessary for eaxms.\n彼は試験のために睡眠は必要ないと主張した.",
     "answer": "claimed",
    "meaning": "claim	[他] ①（that SV）～と主張する ②～を要求する，主張する [名] ③主張，要求"},
    {"text": "009 He c___ about buying a math textbook he’d never use.\n彼は使うことのない数学の教科書を買うことに不満を言っていた.",
     "answer": "complained",
    "meaning": "complain	[自] ①文句を言う，苦情を言う ②（of ～）（病気などを）訴える"},
    {"text": "010 Einstein was o___ the presidency of Israel.\nアインシュタインはイスラエル大統領の職を申し出られた.",
     "answer": "offered",
    "meaning": "offer	[他] ①～を申し出る [名] ②申し出 ③値引き"},
    {"text": "011 He s___ that he was gay.\n彼は自身がゲイであることをほのめかした。",
     "answer": "suggested",
    "meaning": "suggest	[他] ①～を示唆する ②～を提案する"},
    {"text": "012 I was r___ to the local volunteer club.\n私は地元のボランティアクラブに推薦された。",
     "answer": "recommended",
    "meaning": "recommend	[他] ～を推薦する，勧める"},
    {"text": "013 He said he was g___ to her for the feedback, but he ignored all of it.\n彼は彼女のフィードバックに感謝していると言ったが,すべて無視した.",
     "answer": "grateful",
    "meaning": "grateful	[形] 感謝している"},
    {"text": "014 I a___ for criticizing.\n私は批判したことを謝った.",
     "answer": "apologized",
    "meaning": "apologize	[自] （to ～）（～に）謝る"},
    {"text": "015 I won’t use a disorder as an e___.\n 不調を言い訳にしない.", 
     "answer": "excuse",
    "meaning": "excuse	[名] ①言い訳 [他] ②～を許す ③（A from B）（B からA）を免除する"},
    {"text": "016 c___ her birthday\n彼女の誕生日を祝う🎂",
     "answer": "celebrate",
    "meaning": "celebrate	[他] ①（特別な日、出来事）を祝う ②（儀式など）を挙行する，執り行う"},
    {"text": "017 His family c___ his finally being accepted into college.\n彼の家族は,彼がついに大学に合格したことを祝った.㊗️",
     "answer": "congratulated",
    "meaning": "congratulate	[他] （人）を祝う，～にお祝いを述べる"},
    {"text": "018 Everyone a___ his remarkable idea.\n誰もが彼の注目すべきアイデアに感心した.",
     "answer": "admired",
    "meaning": "admire	[他] ～を称賛する，～に感心する"},
    {"text": "019 His outstanding presentation i___ everyone.\n彼の傑出したプレゼンは,みんなに感銘を与えた.",
     "answer": "impressed",
    "meaning": "impress	[他] ～に感銘を与える，～を感心させる"},
    {"text": """020 She was a___ "Best Excuse Maker" for always avoiding responsibility.\n彼女は常に責任を避けたことで「最高の言い訳メーカー」を受賞した.🏆""",
     "answer": "awarded",
    "meaning": "award	[名] ①賞 [他] ②～を授与する"},
    {"text": "021 He e___ why he had missed the deadline.\n彼はなぜ締め切りを過ぎたのか説明した.",
     "answer": "explained",
    "meaning": "explain	[他] ～を説明する"},
    {"text": """022 They d___ ignoring the group project as "respecting individual effort."\n彼らはグループ課題を無視することを「個人の努力を尊重する」と表現しました.""",
     "answer": "described",
    "meaning": "describe	[他] ～を説明する"},
    {"text": "023 It is important to c___ effectively with others in a team.\nチームで効果的にコミュ二ケーションをとることは重要だ.",
     "answer": "communicate",
    "meaning": "communicate	[自] ①（with ～）（～と）意思の疎通をはかる [他] ②～を伝える"},
    {"text": "024 This feeling I can’t e___\n表せないこの気持ち",
     "answer": "express",
    "meaning": "express	[他] ①（意見，気持ち）を表現する [名] ②急行（列車，バス）"},
    {"text": "025 The man running ahead is the one I p___ to run with.\n前を走っている男は,一緒に走ると約束した人だ.🏃‍➡️",
     "answer": "promised",
    "meaning": "promise	[名] ①約束 [他] ②～を約束する"},
    {"text": "026 He provided a lot of i___, none of which was useful.\n彼はたくさんの情報を提供したが,役に立つものはひとつもなかった.",
     "answer": "information",
    "meaning": "information	[名] 情報〈不可算〉"},
    {"text": "027 With modern t___, we can talk to anyone in the world except the person next to you.\n現代のテクノロジーでは,隣にいる人以外の誰とでも話すことができる.",
     "answer": "technology",
    "meaning": "technology	[名] （科学）技術"},
    {"text": "028 r___ shows that sunlight improves mental health.\n研究によると,日光はメンタルヘルスを改善する.🌞",
     "answer": "research",
    "meaning": "research	[名] ①（学術）研究 [他] ②～を研究する"},
    {"text": "030 People who can be replaced by a___ Intelligence\nAIに代替可能な人.",
     "answer": "artificial",
    "meaning": "artificial	[形] 人工的な"},
    {"text": "031 Everyone was distracted by his noisy e___ eraser.\n彼のうるさい電動消しゴムにみんな気を散らされた.",
     "answer": "electric",
    "meaning": "electric	[形] 電気の，電動の"},
    {"text": "032 Ancient Egyptians i___ the 365-day calendar.\n古代エジプト人は365日カレンダーを発明した。",
     "answer": "invented",
    "meaning": "invent	[他] ①～を発明する ②（話など）をでっち上げる"},
    {"text": "033 d___ that the speed of light is constant, regardless of the observer’s motion\n光の速度は観測者の運動にかかわらず一定であることを発見する🤪",
     "answer": "discover",
    "meaning": "discover	[他] ①～を発見する ②（that SV）～を知る，～に気がつく ③（知るという意味で）～に出会う"},
    {"text": "034 rapidly d___ city\n急速に発達した都市",
     "answer": "developing",
    "meaning": "develop	[自] ①発達する [他] ②～を発達させる ③～を開発する ④（話，考え）を発展させる ⑤（病気）にかかる"},
    {"text": "035 He had the s___ to disappear whenever work started.\n彼は仕事が始まるといつも消える技術を持っていた.",
     "answer": "skill",
    "meaning": "skill	[名] 技術，力"},
    {"text": "036 No less important than knowledge is the a___ to question it.\n知識に劣らず重要なのは,それを疑問視する能力です.",
     "answer": "ability",
    "meaning": "ability	[名] 能力"},
    {"text": "037 overwhelming t___\n圧倒的な才能🧬",
     "answer": "talent",
    "meaning": "talent	[名] 才能"},
    {"text": "038 Success often comes after continuous e___.\n成功はたいてい継続的な努力の後にやってくる.",
     "answer": "effort",
    "meaning": "effort	[名] 努力"},
    {"text": "040 a___ my ambition to be a pilot\nパイロットになるという望みを叶える🧑‍✈️",
     "answer": "achieve",
    "meaning": "achieve	[他] ～を達成する"},
    {"text": "043 This machine can p___ 10 parts in one minute.\nこの機械は１分で10個の部品を生産出来る.",
     "answer": "produce",
    "meaning": "produce	[他] ①～を生産する，産出する ②（見せるために）～を取り出す [名] ③農作物〈不可算〉"},
    {"text": "044 c___ LINE stickers using the teather's face\n先生の顔でLINEスタンプを作る😱",
     "answer": "create",
    "meaning": "create	[他] ①～を創造する ②～を引き起こす"},
    {"text": "045 Kitano high school was e___ in 1873.\n北野高校は1873年に設立された.",
     "answer": "established",
    "meaning": "establish	[他] ①～を確立する，定着させる ②～を設立する"},
    {"text": "058 She said she had a high f___.\n彼女は高熱らしい.",
     "answer": "fever",
    "meaning": ""},
    {"text": "067 Even a small change can have a significant effect on s___.\n小さな変化でも社会に大きな影響を与える.",
     "answer": "society",
    "meaning": "society	[名] ①社会〈不可算〉 ②（ある具体的な）社会〈可算〉 ③（one's ―）～と同席すること ④協会"},
    {"text": "068 The code of Hammurabi is one of the oldest l___.\nハンムラビ法典(規定)は最古の法律の一つ。",
     "answer": "laws",
    "meaning": "law	[名] ①（the ―）（集合的に）法律，国法 ②（個々の）法律 ③（科学などの）法則"},
    {"text": "069 We don't inherit the Earth from our a___, we borrow it from our children.\n私たちは先祖から地球を受け継ぐのではなく,子供たちから借りています.🌍",
     "answer": "ancestors",
    "meaning": "ancestor	[名] 祖先"},
    {"text": "072 I want to study a___ after graduating from high school.高校を卒業したら留学したい.",
     "answer": "abroad",
    "meaning": ""},
    {"text": "078 I use p___ transportation to get to school.(不可算)\n私は学校に行くのに公共交通機関を利用しています.",
     "answer": "public",
    "meaning": "public	[名] ①（the ―）大衆 [形] ②公共の，公の"},
    {"text": "079 the key e___ that led to the suspension \n停学への決定打となる証拠",
     "answer": "evidence",
    "meaning": "evidence	[名] 証拠〈不可算〉"},
    {"text": "080 They v___ for confidence without thinking.\n彼らは考えずに信任に投票した.",
     "answer": "voted",
    "meaning": "vote	[名] ①投票（数)[自] ②投票する"},
    {"text": "086 The p___ is determined by supply and demand.\n価格は需要と供給で決まる.",
     "answer": "price",
    "meaning": "price	[名] ①価格 ②（―s）物価 ③代償"},
    {"text": "095 It will c___ fifty dollars extra a month.\nそれは毎月50ドル余分にかかる.",
     "answer": "cost",
    "meaning": ""},
    {"text": "097 During World War II, British chess masters were assigned to codebreaking t___ involving the Enigma machine.\n\n第二次世界大戦中,イギリスのチェスマスターたちはエニグマ機に関わる暗号解読の仕事に就いていました.",
     "answer": "tasks",
    "meaning": "task	[名] 仕事〈可算〉"},
    {"text": "098 What you said h___ more than you think.\n君が言ったことは,君が思っているよりも傷ついたよ.😢",
     "answer": "hurt",
    "meaning": ""},
    {"text": "101 d___ the pen of the person sitting next to me\n隣の席の人のペンを破壊する",
     "answer": "destroy",
    "meaning": ""},
    {"text": "111 The captain rescued only the p___ from his own country.\n船長は自国の乗客だけを救出しました.",
     "answer": "passengers",
    "meaning": ""},
    {"text": "115 He climbed the ladder of success, then kicked it away so no one else could f___.\n彼は成功のはしごを登り,それを蹴飛ばし,他の誰も追随できないようにした.",
     "answer": "follow"},
    {"text": "116 Not all who w___ are lost.\n彷徨う人全員が迷っているわけではない.",
     "answer": "wander",
    "meaning": ""},
    {"text": """125 She was awarded "Best Excuse Maker" for always a___ responsibility.\n彼女は常に責任を避けたことで「最高の言い訳メーカー」を受賞した.🏆""",
     "answer": "avoiding",
    "meaning": ""},
    {"text": "128 Complex i___ compose themselves of simple, ignored mistakes.\n複雑な問題は,無視された単純なミスから成り立っている.",
     "answer": "issues",
    "meaning": ""},
    {"text": "135 s___ in escaping from prison\n脱獄に成功する",
     "answer": "succeed",
    "meaning": ""},
    {"text": "136 m___ the last train\n終電を逃す",
     "answer": "miss",
    "meaning": ""},
    {"text": "137 He m___ silence for wisdom, and loudness for leadership.\n彼は沈黙を賢さと勘違いし,声の大きさをリーダーシップと勘違いした.",
     "answer": "mistook",
    "meaning": ""},
    {"text": "140 They h__ Jews from the Nazis.\n彼らはナチスからユダヤ人を隠した.",
     "answer": "hid"},
    {"text": "141 d___ her portrait\n彼女の似顔絵を描く🎨",
     "answer": "draw",
    "meaning": ""},
    {"text": "146 At dawn, the LGBTQ flag was r___ from his house.\n夜が明けると、彼の家からLGBTQフラッグが上がった。🏳️‍🌈",
     "answer": "raised",
    "meaning": ""},
    {"text": "150 p___ to understand\nわかっているふりをする",
     "answer": "pretend",
    "meaning": ""},
    {"text": "151 He said something shallow, p___ to be profound.\n彼は深そうに見せかけて浅いことを言った",
     "answer": "pretending",
    "meaning": ""},
    {"text": "154 It is not what h___ that matters. It is how you respond.\n大事なのは何が起きたかではない.どう応じるかだ.",
     "answer": "happened",
    "meaning": ""},
    {"text": "153 e___ Juso after school\n放課後,十三を探検する",
     "answer": "explore",
    "meaning": ""},
    {"text": "155 More and more problems a___.\nますます多くの問題が現れた.",
     "answer": "appeared",
    "meaning": ""},
    {"text": "162 Do you think Takeshi is i___ in humanity?\nタケシは人類に含まれると思いますか？", 
     "answer": "included",
    "meaning": "include	[他] ～を含む"},
    {"text": "163 The captain rescued only the passengers from his o___ country.\n船長は自国の乗客だけを救出しました.",
     "answer": "own",
    "meaning": ""},
    {"text": "167 h___ is written by the victors.\n歴史は勝者によって書かれる.",
     "answer": "history",
    "meaning": ""}, 
    {"text": "170 comulsory e___\n義務教育",
     "answer": "education",
    "meaning": "compulsory	[形] ①義務的な ②規定の"},
    {"text": "171 No less important than k___ is the ability to question it.\n知識に劣らず重要なのは,それを疑問視する能力です.",
     "answer": "knowledge",
    "meaning": ""},
    {"text": "175 I want to study abroad after g___ from high school.高校を卒業したら留学したい.",
     "answer": "graduating",
    "meaning": ""},
    {"text": "177 J___ by appearances, he is selfish.\n見た目で判断すると、彼は自分勝手だ。",
     "answer": "judging",
    "meaning": ""},
    {"text": "189 His family celebrated his finally being ___ into college.\n彼の家族は,彼がついに大学に合格したことを祝った.㊗️",
     "answer": "accepted",
    "meaning": ""},
    {"text": "197 First Olympic games a___ only naked men.\n初期オリンピックは裸の男性だけ参加できた。",
     "answer": "allowed",
    "meaning": ""},
    {"text": "194 He s___ to side with the insects.\n彼はその虫の味方をするようだ.🐛",
     "answer": "seems",
    "meaning": ""},
    {"text": "205 rich n___\n豊かな自然",
     "answer": "nature",
    "meaning": ""},
    {"text": "209 This year's h___ will fall short of the average.\n今年の収穫は平年の収穫に及ばないだろう.",
     "answer": "harvest",
    "meaning": ""},
    {"text": "211 If there is an e___, get under a table.\n地震の際にはテーブルの下にもぐれ.",
     "answer": "earthquake",
    "meaning": ""},
    {"text": "215 The pond f___ over.\n池が一面凍った.",
     "answer": "froze",
    "meaning": ""},
    {"text": "228 Takeshi's a___ implies betrayal.\nタケシは裏切りをほのめかす態度だ。",
     "answer": "attitude",
    "meaning": ""},
    {"text": "239 a___ clothes for an apology press conference\n謝罪会見にふさわしい服装🦹",
     "answer": "appropriate",
    "meaning": ""},
    {"text": "241 recall my e___ school memories\n小学校の思い出を思い出す",
     "answer": "elementary",
    "meaning": ""},
    {"text": "243 It is not what happened that m____. It is how you respond.\n大事なのは何が起きたかではない.どう応じるかだ.",
     "answer": "matters",
    "meaning": ""},
    {"text": "245 I came up with a b___ idea!\n天才的なアイデアを思いついた!",
     "answer": "brilliant",
    "meaning": ""},
    {"text": "248 a p___ breeze\n心地よいそよかぜ",
     "answer": "pleasant",
    "meaning": ""},
    {"text": "258 People tend to accept ideas not because they are true, but because they are f___.\n人々はアイデアが真実だからではなく,馴染みがあるから受け入れる傾向があります.",
     "answer": "familiar",
    "meaning": ""},
    {"text": "269 Don’t c___ your chickens before they hatch.\n卵がかえる前にヒヨコを数えるな",
     "answer": "count",
    "meaning": ""},
    {"text": "279 It will cost fifty dollars e___ a month.\nそれは毎月50ドル余分にかかる.",
     "answer": "extra",
    "meaning": ""},
    {"text": "284 Did you have your hair cut? It s___ you!\n髪切った？似合ってるよ！",
     "answer": "suits",
    "meaning": ""},
    {"text": "286 A:What movie has no kissing s___?\nB:Your life.\nA:キスシーンの無い映画は？",
     "answer": "scenes"},
    {"text": "291 S___ has come.\n春が来た.",
     "answer": "spring"},
    {"text": "293 Children under six must be accomanied by someone a___ 18 or older.\n6歳未満のお子様には18歳以上の人の付き添いが必要です.",
     "answer": "aged"},
    {"text": "294 a g___ gap\n世代間格差",
     "answer": "generation"},
    {"text": "309 A:Teacher, I feel like I might be a g___ can.\nB:What a trashy joke.\n\nA:先生、私は自分がゴミ箱なんじゃないかと思っているのですが。\nB:そんなゴミみたいな冗談を。🗑️",
     "answer": "garbage"},
    {"text": "311 If you put w___ on a grandma, can you call it a bicycle?\nおばあちゃんに車輪を付けたら,自転車と呼べるのか.👵",
     "answer": "wheels"},
    {"text": "315 Omitting the tale of the Straw Millionaire, trying to exchange a s___ for a Benz.\nわらしべ長者の物語を省略して,ひもをベンツと交換しようとする.",
     "answer": "string"},
    {"text": "321 This r___ is in the way.\nこの冷蔵庫は邪魔だ.",
     "answer": "refrigerator"},
    {"text": "324 He p___ more than just money to buy his daughter an instrument.\n彼は娘に楽器を買うためにお金以上のものを支払った。",
     "answer": "paid"},
    {"text":"336 r__, r__, r__ your boat\nGently down the stream\nMerrily, merrily, merrily, merrily\nLife is but a dream\n\nボートを漕げ、漕げ、漕げ\nそっと流れを下って\n陽気に、陽気に、陽気に、陽気に\n人生は夢に過ぎない",
     "answer": "row"},
    {"text": "338 The rook moves in the same d___ as the hisha.\nルークは飛車と同じ方向に進む.♟️",
     "answer": "directions"},
    {"text": "340 I want to transfer to the a___ course.\n美術コースに転向したい.🎨",
     "answer": "art"},
    {"text": "343 He paid more than just money to buy his daughter an i___.\n彼は娘に楽器を買うためにお金以上のものを支払った。",
     "answer": "instrument"},
    {"text": "345 the challenge of having to create example s___ to protect copyright\n著作権保護のため例文を作らなければならないという課題",
     "answer": "sentences"},
    {"text": "347 The teacher advised me to study English v___.\n先生は私に英単語を勉強するよう助言した.",
     "answer": "vocabulary"},
    {"text": "351 s___ of an earthquake\n地震の兆候",
     "answer": "signs"},
    {"text": "356 What we see d___ not only on what we look at, but also on where we look from.\n私たちが見るものは,何を見るかだけでなく,どこから見るかによっても異なります.",
     "answer": "depends"},
    {"text": "361 The truth is often simple, but people p___ complex answers.\n真実はしばしば単純ですが,人々は複雑な答えを好みます.",
     "answer": "prefer"},
    {"text": "362 All America w___.\n全米が泣いた.😢",
     "answer": "wept"},
    {"text": "374 What a p___.\n残念だ。",
     "answer": "pity",
    "meaning": ""},
    {"text": "866 I am not s___ with my current salary.\n私は今の給料に満足していない.",
     "answer": "satisfied"},
    {"text": "378 Even a small change can have a significant e___ on society.\n小さな変化でも社会に大きな影響を与える.",
     "answer": "effect"},
    {"text": "393 e___ a small change can have a significant effect on society.\n小さな変化でも社会に大きな影響を与える.",
     "answer": "even"},
    {"text": "400 With modern technology, we can talk to anyone in the world e___ the person next to you.\n現代のテクノロジーでは,隣にいる人以外の誰とでも話すことができる.",
     "answer": "except"},
    {"text": "402 I apologized for c___.\n私は批判したことを謝った.",
     "answer": "criticizing"},
    {"text": "410 d___ something special\n特別なことを要求する",
     "answer": "demand"},
    {"text": "411 We have a strong d___ to finish our homework.\n私たちは宿題を終わらせたいという強い願望を持っている.",
     "answer": "desire"},
    {"text": "418 d___ my great wisdom\n自分が賢いということを示す",
     "answer": "demonstrate"},
    {"text": "420 It is not what happened that matters. It is how you r___.\n大事なのは何が起きたかではない.どう応じるかだ.",
     "answer": "respond"},
    {"text": "434 He’s been p___ her aunt for months\n彼は何か月も彼女のおばを狙っています.😱",
     "answer": "pursuing"},
    {"text": "438 f___ my duties\n義務を果たす",
     "answer": "fulfill"},
    {"text": "440 the c___ of having to create example sentences to protect copyright\n著作権保護のため例文を作らなければならないという課題",
     "answer": "challenge"},
    {"text": "443 Is his face p___ or has it always been p___?\n彼は青ざめているのか,いつも青白いのか.🥶",
     "answer": "pale"},
    {"text": "448 It is best to get a lot of r___.\n休養を十分にとるのが一番だ.",
     "answer": "rest"},
    {"text": "449 He was conscious during the entire s___.\n彼は手術中ずっと意識があった.😱",
     "answer": "surgery"},
    {"text": "453 breast c___ screening will be offered for free.\n 乳がんの検査が無料で提供される。", 
     "answer": "cancer",
    "meaning": ""},
    {"text": "454 Call an a___!\n救急車を呼んで!",
     "answer": "ambulance"},
    {"text": "461 By the time we reached the top of the mountain, we were all e___.\n山頂に着くころまでには,私たちはみんなへとへとになっていた.",
     "answer": "exhausted"},
    {"text": "465 train the chest m___\n 胸筋を鍛える", 
     "answer": "muscles",
    "meaning": ""},
    {"text": "471 r___ discrimination\n人種差別",
     "answer": "racial"},
    {"text": "479 All animals are e___, but some animals are more e___ than others.\n全ての動物は平等だが、中には他よりもっと平等な動物もいる。",
     "answer": "equal"},
    {"text": "483 Social Networking S___\nソーシャル・ネットワーキング・サービス",
     "answer": "service"},
    {"text": "490 Mankind has achieved great p___ over the past few centuries.\n人類はここ数百年で大きな繁栄を遂げた.", 
     "answer": "prosperity",
    "meaning": "prosperity	[名] 繁栄"},
    {"text": "490 racial d___\n人種差別",
     "answer": "discrimination"},
    {"text": """495 They described ignoring the group project as "respecting ___ effort."\n彼らはグループ課題を無視することを「個人の努力を尊重する」と表現しました.""",
     "answer": "individual"},
    {"text": "502 People i___ with others in many ways.\n人々はいろいろな形で他人と関わり合っている.",
     "answer": "interact"},
    {"text": "504 The consumption tax should be a___.\n消費税は廃止されるべきだ.",
     "answer": "abolished"},
    {"text": "507 fulfill my d___\n義務を果たす",
     "answer": "duties"},
    {"text": "509 The one-child p___ in China is successful to some extent.",
     "answer": "policy",
    "meaning": ""},
    {"text": "512 Scholarships help students pay for college tuition and e___.\n奨学金は学生が大学の授業料や費用を支払うのを助ける.",
     "answer": "expenses"},
    {"text": "513 D___ collection notice\n借金の督促状",
     "answer": "debt",
    "meaning": "debt	[名] 借金"},
    {"text": "514 The consumption t__ should be abolished.\n消費税は廃止されるべきだ.",
     "answer": "tax"},
    {"text": "522 Don't w___ your precious time.\n貴重な時間を浪費するな.⌛",
     "answer": "waste"},
    {"text": "527 During World War II, British chess masters were a___ to codebreaking tasks involving the Enigma machine.\n第二次世界大戦中,イギリスのチェスマスターたちはエニグマ機に関わる暗号解読の仕事に就いていました.",
     "answer": "assigned"},
    {"text": "599 He refused to sign the d___.\n彼はその書類にサインするのを拒んだ.",
     "answer": "document"},
    {"text": "539 The road to success is under c___.\n成功への道は工事中だ.🚧",
     "answer": "construction"},
    {"text": "545 Complex issues c___ themselves of simple, ignored mistakes.\n複雑な問題は,無視された単純なミスから成り立っている.",
     "answer": "compose"},
    {"text": "546 Ideas a___ quickest to the minds already half convinced.\n考えは半分納得した心に一番早くくっつく.",
     "answer": "attach"},
    {"text": "553 perfect c___\n完全犯罪",
     "answer": "crime"},
    {"text": "555 s___ posters on the wall\n壁にポスターを貼る",
     "answer": "stick"},
    {"text": "568 Instagram does more h___ than good.\nインスタグラムは益より害になる.",
     "answer": "harm"},
    {"text": "572 Honey never s___.\nはちみつは腐りません.(台無しにならない.)🍯",
     "answer": "spoils"},
    {"text": "573 The Colosseum could hold up to 50,000 s___.\nコロッセオは5万人まで収容可能だった。",
     "answer": "spectators"},
    {"text": "574 a distant r___, that is, a stranger\n遠い親戚,つまり他人",
     "answer": "relative"},
    {"text": "577 I use public t___ to get to school.(不可算)\n私は学校に行くのに公共交通機関を利用しています.",
     "answer": "transportation"},
    {"text": "583 like the f___ of a river\n川の流れのように",
     "answer": "flow"},
    {"text": "586 c___ time\n通学時間",
     "answer": "commuting"},
    {"text": "587 Children under six must be a___ by someone aged 18 or older.\n6歳未満のお子様には18歳以上の人の付き添いが必要です.",
     "answer": "accompanied"},
    {"text": "597 He was f___ to go out for nearly a decade.\n彼は10年近く外出を禁止された.",
     "answer": "forbidden"},
    {"text": "599 He r___ to sign the document.\n彼はその書類にサインするのを拒んだ.",
     "answer": "refused"},
    {"text": "602 Ideas attach quickest to the minds already half c___.\n考えは半分納得した心に一番早くくっつく.",
     "answer": "convinced"},
    {"text": "604 Fake news s___ faster than real news.\n フェイクニュースは本当のニュースより速く拡散する.",
     "answer": "spreads"},
    {"text": "610 I can r___ everything except temptation.\n私は誘惑以外の全てに耐えうる.",
     "answer": "resist"},
    {"text": "618 Takeshi often b___ his forehead into utility poles.\n タケシはよく電柱に額をぶつける。", 
     "answer": "bumps",
    "meaning": ""},
    {"text": "627 appropriate clothes for an apology p___ conference\n謝罪会見にふさわしい服装🦹",
     "answer": "press"},
    {"text": "626 There are times when I s___.\nつまずく時もある.",
     "answer": "stumble"},
    {"text": "630 I got s___ on the arm by a kitten.\n子猫に腕をひっかかれた.😼",
     "answer": "scratched"},
    {"text": "631 A job that requires constant b___\nおじぎし続ける仕事",
     "answer": "bowing"},
    {"text": "633 She s___.\n彼女はためいきをついた.😮‍💨",
     "answer": "sighed"},
    {"text": "638 r___ the people from the swimming make-up class\n人々を水泳補講から解放する🏊",
     "answer": "release"},
    {"text": "639 succeed in e___ from prison\n脱獄に成功する",
     "answer": "escaping"},
    {"text": "642 The picture was h___ upside down.\nその絵は逆さまに掛かっていた.",
     "answer": "hung"},
    {"text": "644 s___ while the iron is hot\n鉄は熱いうちに打て",
     "answer": "strike"},
    {"text": "646 Squids have a membrane that p___ their internal organs.\n イカは内臓を守る膜を持つ。", 
     "answer": "protects",
    "meaning": ""},
    {"text": "647 I t___ my ankle in P.E.\n私は体育の授業で足首をひねった。", 
     "answer": "twisted",
    "meaning": ""},
    {"text": "648 s___ school\n学校をサボる",
     "answer": "skip"},
    {"text": "660 Sharks e___ before trees on Earth.\nサメは地球上に木より先に存在した.",
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
    {"text": "691 He was c___ during the entire surgery.\n彼は手術中ずっと意識があった.😱",
     "answer": "conscious"},
    {"text": "693 She is r___ as the best teacher in the school.\n彼女は学校で一番の教師とみなされている.",
     "answer": "regarded"},
    {"text": "694 He c___ himself to finishing the marathon.\n彼はマラソンを完走する事を決意した.",
     "answer": "committed"},
    {"text": "696 m___ the times tables\n九九を暗記する",
     "answer": "memorize"},
    {"text": "697 f___ Gandhi\nガンジーを許す",
     "answer": "forgive"},
    {"text": "698 What is taken for g___ today was once a revolutionary idea.\n今日当たり前のように考えられているものは,かつては革新的なアイデアでした.",
     "answer": "granted"},
    {"text": "699 r___ my elementary school memories\n小学校の思い出を思い出す",
     "answer": "recall",
    "meaning": ""},
    {"text": "717 There are w___ here and there.\nあちらこちらに雑草がある",
     "answer": "weeds",
    "meaning": ""},
    {"text": "720 s___ power generation\n太陽光発電🌞",
     "answer": "solar"},
    {"text": "723 according to the weather f___\n天気予報によれば",
     "answer": "forecast"},
    {"text": "724 The summer in Juso is hot and h___.\n十三の夏は蒸し暑い.",
     "answer": "humid"},
    {"text": "725 t___ rainforests\n熱帯雨林",
     "answer": "tropical"},
    {"text": "738 I wish we could a___ to eat whatever we want.\n食べたいものを何でも食べられる余裕があればいいのに.",
     "answer": "afford"},
    {"text": "740 Judging by appearances, he is s___.\n見た目で判断すると、彼は自分勝手だ",
     "answer": "selfish",
    "meaning": ""},
    {"text": "744 a s___ old man next door\nお隣の頑固な老人",
     "answer": "stubborn"},
    {"text": "747 I am i___ to you.\n私はあなたに無関心です",
     "answer": "indifferent"},
    {"text": "751 a___ clock\n正確な時計⌚",
     "answer": "accurate"},
    {"text": "760 Even a small change can have a s___ effect on society.\n小さな変化でも社会に大きな影響を与える.",
     "answer": "significant",
    "meaning": "society	[名] ①社会〈不可算〉 ②（ある具体的な）社会〈可算〉 ③（one's ―）～と同席すること ④協会"},
    {"text": "761 Don't waste your p___ time.\n貴重な時間を浪費するな.⌛",
     "answer": "precious"},
    {"text": "765 The scientist made a c___ discovery in the laboratory.\nその科学者は研究室で重大な発見をした,",
     "answer": "critical"},
    {"text": "766 He suddenly put on a s___ face.\n彼は急に真剣な顔になった.😐",
     "answer": "serious"},
    {"text": "767 C___ issues compose themselves of simple, ignored mistakes.\n複雑な問題は,無視された単純なミスから成り立っている.",
     "answer": "complex"},
    {"text": "768 a c___ maze\n複雑な迷路",
     "answer": "complicated"},
    {"text": "772 Everyone admired his remarkable idea.\n誰もが彼の注目すべきアイデアに感心した.",
     "answer": "remarkable",
    "meaning": "admire	[他] ～を称賛する，～に感心する"},
    {"text": "773 His o___ presentation impressed everyone.\n彼の傑出したプレゼンは,みんなに感銘を与えた.",
     "answer": "outstanding",
    "meaning": "impress	[他] ～に感銘を与える，～を感心させる"},
    {"text": "779 He simply finds pleasure in the s___ walk.\n彼はただ着実な歩みを楽しんでいるのです。",
     "answer": "steady"},
    {"text": "783 r___ mango\n熟したマンゴー🥭",
     "answer": "ripe",
    "meaning": ""},
    {"text": "791 F___ news spreads faster than real news.\n フェイクニュースは本当のニュースより速く拡散する.",
     "answer": "fake"},
    {"text": "803 b___ shoes\n新品の靴👟",
     "answer": "brand-new"},
    {"text": "807 He said something s___, pretending to be profound.\n彼は深そうに見せかけて浅いことを言った",
     "answer": "shallow",
    "meaning": ""},
    {"text": "808 First Olympic games allowed only n___ men.\n初期オリンピックは裸の男性だけ参加できた.🔥",
     "answer": "naked"},
    {"text": "811 Many African countries became i___ in 1960.\n1960年に多くのアフリカの国が独立した",
     "answer": "independent"},
    {"text": "816 an a___ walk\nぎこちない歩き方",
     "answer": "awkward"},
    {"text": "820 People t___ to accept ideas not because they are true, but because they are familiar.\n人々はアイデアが真実だからではなく,馴染みがあるから受け入れる傾向がある.",
     "answer": "tend"},
    {"text": "823 glass f___\nガラスの破片",
     "answer": "fragments"},
    {"text": "839 an enormous a___ of fat\n莫大な(量の)脂肪",
     "answer": "amount"},
    {"text": "842 an e___ amount of fat\n莫大な(量の)脂肪",
     "answer": "enormous"},
    {"text": "848 Go out through the e___ exit on the right.\n右の非常口から出てください.",
     "answer": "emergency"},
    {"text": "851 I am not satisfied with my c___ salary.\n私は今の給料に満足していない.",
     "answer": "current"},
    {"text": "857 I have noy heard from her l___.\n最近彼女から連絡がない.",
     "answer": "lately"},
    {"text": "860 He was forbidden to go out for nearly a d___.\n彼は10年近く外出を禁止された.",
     "answer": "decade"},
    {"text": "861 The price is determined by s___ and demand.\n価格は需要と供給で決まる.",
     "answer": "supply"},
    {"text": "862 People who can be r___ by Artificial Intelligence\nAIに代替可能な人.",
     "answer": "replaced"},
    {"text": "863 Omitting the tale of the Straw Millionaire, trying to e___ a string for a Benz.\nわらしべ長者の物語を省略して,ひもをベンツと交換しようとする.",
     "answer": "exchange"},
    {"text": "867 d___ drugs\nクスリを配達する🌿",
     "answer": "deliver"},
    {"text": "869 an e___ with a cute design\n可愛らしい柄の封筒",
     "answer": "envelope"},
    {"text": "877 answer a q___\nアンケートに答える",
     "answer": "questionnaire",
    "meaning": ""},
    {"text": "890 It's okay to take a n__.\n昼寝しても大丈夫だよ.💤",
     "answer": "nap",
    "meaning": ""},
    {"text": "892 v___ m___\n 自動販売機",
     "answer": "vending machine",
    "meaning": ""},
    {"text": "894 Liberty is g___.\n 自由が保障される。", 
     "answer": "guaranteed",
    "meaning": ""},
    {"text": "898 get d___ at 21\n21で離婚する🤰",
     "answer": "divorced",
    "meaning": ""},
    {"text": "901 I want to t___ to the art course.\n美術コースに転向したい.🎨",
     "answer": "transfer",
    "meaning": ""},
    {"text": "906 cover one’s t___\n足跡を消す👣",
     "answer": "tracks",
    "meaning": ""},
    {"text": "907 the Airin d___ in Osaka\n大阪のあいりん地区",
     "answer": "district",
    "meaning": ""},
    {"text": "910 a d___ relative, that is, a stranger",
     "answer": "distant"},
    {"text": "915 Mesopotamian c___\nメソポタミア文明",
     "answer": "civilization",
    "meaning": ""},
    {"text": "919 Russian l___\nロシア文学",
     "answer": "literature",
    "meaning": ""},
    {"text": "924 p___\nことわざ",
     "answer": "proverb",
    "meaning": ""},
    {"text": "925 Omitting the t___ of the Straw Millionaire, trying to exchange a string for a Benz.\nわらしべ長者の物語を省略して,ひもをベンツと交換しようとする.",
     "answer": "tale",
    "meaning": ""},
    {"text": "924 to p___ E = mc²\nE=mc²を証明する",
     "answer": "prove",
    "meaning": ""},
    {"text": "942 The pop star’s cheating scandal a___ media attention.\n人気スターの不倫騒動はマスコミの関心を引き付けた.",
     "answer": "attracted",
    "meaning": ""},
    {"text": "949 be a___ in programming\nプログラミングに没頭する",
     "answer": "absorbed",
    "meaning": ""},
    {"text": "950 I am f___ of reading books.\n本を読むことが好きだ.📚",
     "answer": "fond",
    "meaning": ""},
    {"text": "953 b___ feast\nつまらない宴会",
     "answer": "bored",
    "meaning": ""},
    {"text": "956 I feel e___ when I hear compliments.\n褒め言葉を聞いて照れる.",
     "answer": "embarrassed",
    "meaning": ""},
    {"text": "959 Don’t h___ to go all in.\nオールインするのをためらうな💸",
     "answer": "hesitate",
    "meaning": ""},
    {"text": "960 I’m r___ to study Japanese.\n国語を勉強するのは気が進まない.",
     "answer": "reluctant",
    "meaning": ""},
    {"text": "968 show my e___\n感情をむき出しにする🤬",
     "answer": "emotions",
    "meaning": ""},
    {"text": "972 have the c___ to say no\n断る勇気を持つ",
     "answer": "courage",
    "meaning": ""},
    {"text": """978 They described i___ the group project as "respecting individual effort".\n彼らはグループ課題を無視することを「個人の努力を尊重する」と表現しました.""",
     "answer": "ignoring",
    "meaning": ""},
    {"text": "983 The one-child policy in China is successful to some e___.",
     "answer": "extent",
    "meaning": ""},
    {"text": "992 We shape our tools, and e___, our tools shape us.\n私たちは道具を作るが,結果として,道具が私たちを作る.",
     "answer": "eventually",
    "meaning": ""},
    {"text": "993 He argued that sleep wasn’t n___ for eaxms.\n彼は試験のために睡眠は必要ないと主張した.",
     "answer": "necessary",
    "meaning": ""},
    {"text": "994 F___ speaking,\n率直に言うと,",
     "answer": "frankly",
    "meaning": ""},
    {"text": "978 Complex issues compose themselves of simple, i___ mistakes.\n複雑な問題は,無視された単純なミスから成り立っている.",
     "answer": "ignored",
    "meaning": ""},
    {"text": "998 discover that the speed of light is constant, r___ of the observer’s motion\n光の速度は観測者の運動にかかわらず一定であることを発見する🤪",
     "answer": "regardless",
    "meaning": "regardless	[副] （of ～）（～とは）無関係に"},
    {"text": "1000 a___ t__ capitalism, your value peaks at checkout.\n資本主義によると,あなたの価値はチェックアウト時にピークに達する.",
     "answer": "according to",
    "meaning": "according to	[前] ①（調査，人の話など）によれば ②（能力など）に応じて"},
]
questions_1001_2000 = [
    {"text": "1001 ___ travel plan\n旅行の計画を提案する",
     "answer": "propose",
    "meaning": "propose　[他] ①～を提案する [自] ②（to ～）（～に）結婚を申し込む"},
    {"text": "1002 ___ Takeshi's idea as impossible\n不可能だとしてタケシの考えを退ける",
     "answer": "dismiss",
    "meaning": "dismiss　[他] ①（意見や考えなど）を退ける ②～を解雇する"},
    {"text": "1003 I ___ you.\n私はあなたを祝福する.",
     "answer": "bless",
    "meaning": "bless　[他] ～を祝福する"},
    {"text": "1004 remember the past ___\n過去の栄光を思い出す",
     "answer": "glory",
    "meaning": "glory　[名] 栄光"},
    {"text": "1005 I feel embarrassed when I hear ___.\n褒め言葉を聞いて照れる.",
     "answer": "compliments",
    "meaning": "compliment	[名] ①褒め言葉，賛辞 [他] ②～を褒める"},
    {"text": "1006 bored ___\nつまらない宴会",
     "answer": "feast",
    "meaning": "feast　[名] ①宴会，祝宴 ②とても楽しいこと，喜ばせるもの"},
    {"text": "1007 Takeshi ___ that he has never lied.\nタケシは嘘をついたことがないとはっきりと述べた.",
     "answer": "declared",
    "meaning": "declare	[他] ①～を宣言する ②（税関や税務署で）～を申告する"},
    {"text": "1008 ___ an important part\n重要な部分を強調する",
     "answer": "highlight",
    "meaning": "highlight　[他] ①～を強調する [名] ②呼び物，目玉商品，ハイライト"},
    {"text": "1009 Takeshi's attitude ___ betrayal.\nタケシは裏切りをほのめかす態度だ.",
     "answer": "implies",
    "meaning": "imply　[他] ～をほのめかす，（暗に）～を意味する"},
    {"text": "1010 ___ the school song\n校歌を暗唱する",
     "answer": "recite",
    "meaning": "recite	[他] ～を暗唱する"},
    {"text": "1011 research the sun's ___\n太陽光線を研究する🌞",
     "answer": "rays",
    "meaning": "ray	[名] ①光線 ②放射線 ③（a ― of）一縷の，わずかな"},
    {"text": "1012 ___ is not necessarily dangerous.\n放射線は必ずしも危険なものではない.",
     "answer": "radiation",
    "meaning": "radiation	[名] 放射線"},
    {"text": "1013 The scientist made a critical discovery in the ___.\nその科学者は研究室で重大な発見をした.",
     "answer": "laboratory",
    "meaning": "laboratory	[名] 研究室，研究所"},
    {"text": "1014 Plants produce ___.\n植物は酸素を作り出す.🌳",
     "answer": "oxygen",
    "meaning": "oxygen	[名] 酸素"},
    {"text": "1015 You can’t see ___ with the naked eye.\n分子は肉眼で見ることができない.",
     "answer": "molecules",
    "meaning": "molecule	[名] 分子"},
    {"text": "1016 A lot of substances are ___.\n多くの物質は化合物である.",
     "answer": "compounds",
    "meaning": "compound	[名] ①化合物 [形] ②複合的な"},
    {"text": "1017 Attempt to regenerate muscle ___.\n筋組織の再生を試みる.",
     "answer": "tissue",
    "meaning": "tissue	[名] ①組織 ②ティッシュペーパー"},
    {"text": "1018 There are several types of ___.\n細胞にはいくつか種類がある.",
     "answer": "cells",
    "meaning": "cell	[名] ①細胞 ②電池 ③独房 （①②③いずれも〈可算〉)"},
    {"text": "1019 No ___ is better or worse than another.\n遺伝子に優劣はない.",
     "answer": "gene",
    "meaning": "gene	[名] 遺伝子〈可算〉"},
    {"text": "1020 A lot of ___ are compounds.\n多くの物質は化合物である.",
     "answer": "substances",
    "meaning": "substance	[名] ①物質 ②本質，根拠 <不可算>"},
    {"text": "1021 A ___ becomes a liquid when heated.\n固体は加熱すると液体になる.💧",
     "answer": "solid",
     "meaning": "solid	[形] ①固体の ②ぎっしり詰まった [名] ③固体"},
    {"text": "1022 A ___ falls to Earth.\n人工衛星が墜落する.🛰️",
     "answer": "satellite",
     "meaning": "satellite	[名] ①（月などの）衛星 ②人工衛星"},
    {"text": "1023 The Earth’s ___ changes.\n地球の軌道が変わる.🌍",
     "answer": "orbit",
    "meaning": "orbit	[名] ①軌道 [他] ②（惑星などが）～を周回する"},
    {"text": "1024 ___ a plastic bottle rocket\nペットボトルロケットを打ち上げる",
     "answer": "launch",
    "meaning": "launch	[他] ①（ロケットなど）を打ち上げる ②（運動，事業など）を始める [名] ③打ち上げ，開始，発売"},
    {"text": "1025 ___ to regenerate muscle tissue.\n筋組織の再生を試みる.",
     "answer": "attempt",
    "meaning": "attempt	[名] ①試み [他] ②（to do）（～しようと）試みる"},
    {"text": "1026 Takeshi has a hidden ___.\nタケシには隠された能力がある.",
     "answer": "capacity",
    "meaning": "capacity	[名] ①能力 ②容量，収容力"},
    {"text": "1027 It seems that all Kitano students are ___ of studying well.\n北野生は全員勉強がよくできるらしい.",
     "answer": "capable",
    "meaning": "capable	[形] ①（of ～）（～する）力がある ②有能な"},
    {"text": "1028 ___ a short-term goal\n目先の目標を達成する",
     "answer": "attain",
    "meaning": "attain	[他] ①（人が主語）～を達成する ②（物，人が主語）～に到達"},
    {"text": "1029 be ___ to finish my homework\n宿題を終わらせるのに必死になる",
     "answer": "desperate",
    "meaning": "desperate	[形] ①必死の ②（状況が）絶望的な"},
    {"text": "1030 I ___ my youth to studying.\n私は青春を勉強に捧げた.🤓",
     "answer": "dedicated",
    "meaning": "dedicate	[他] （A to B）（A）を（B に）捧げる"}, 
    {"text": "1031 There is no success without ___.\n苦しみなくして成功なし.",
     "answer": "pain",
    "meaning": "pain	[名] ①苦痛 ②（―s）苦労"}, 
    {"text": "1032 It puts a ___ on the body.\nそれは身体に負担がかかる.",
     "answer": "strain",
    "meaning": "strain	[名] ①（心身の）負担，無理 [他] ②（目や筋肉など）を痛める"}, 
    {"text": "1033 find a ___ for a serious illness\n深刻な病気の治療法を見つける",
     "answer": "remedy",
    "meaning": "remedy	[名] ①治療法，治療薬 ②改善策，対策（①②いずれも〈可算〉）"}, 
    {"text": "1034 I will go to the nearby ___.\n私は近くの薬局に行くつもりだ.",
     "answer": "pharmacy",
    "meaning": "pharmacy	[名] （調剤）薬局"}, 
    {"text": "1035 I aspire to become a ___.\n 医師になることを目指す.🧑‍⚕️",
     "answer": "physician",
    "meaning": "physician	[名] ①〈米〉医師 ②〈英〉内科医"},
    {"text": "1036 I won’t use a ___ as an excuse.\n不調を言い訳にしない.", 
     "answer": "disorder",
    "meaning": "disorder	[名] （心身の）不調"},
    {"text": "1037 give up my seat for a ___ woman\n妊婦さんに席を譲る🤰", 
     "answer": "pregnant",
    "meaning": "pregnant	[形] 妊娠した"},
    {"text": "1038 ___ research has shown that stress is harmful.\n臨床研究では、ストレスは有害であることが示されている.", 
     "answer": "clinical",
    "meaning": "clinical	[形] 臨床の"},
    {"text": "1039 ___ emotional wounds\n心の傷を回復する💗", 
     "answer": "heal",
    "meaning": "heal	[他] ①～を治す [自] ②治る"}, 
    {"text": "1040 Takeshi was ___ with COVID-19.\nタケシはコロナに感染した.🦠", 
     "answer": "infected",
    "meaning": "infect	[他] （人，動物，地域）に感染させる，伝染する"},
    {"text": "1041 I twisted my ___ in P.E.\n私は体育の授業で足首をひねった。", 
     "answer": "ankle",
    "meaning": "ankle	[名] 足首"}, 
    {"text": "1042 support the body with the ___\n親指で身体を支える", 
     "answer": "thumb",
    "meaning": "thumb	[名] 親指"},
    {"text": "1043 Takeshi often bumps his ___ into utility poles.\n タケシはよく電柱に額をぶつける", 
     "answer": "forehead",
    "meaning": "forehead	[名] 額，おでこ"},
    {"text": "1044 Keep your ___ up！\n 元気を出して！(あごをあげて！)", 
     "answer": "chin",
    "meaning": "chin	[名] 下あご，あごの先端"},
    {"text": "1045 train the ___ muscles\n 胸筋を鍛える", 
     "answer": "chest",
    "meaning": "chest	[名] ①胸（部)②（大きな木の）箱，密閉容器"},
    {"text": "1046 ___ cancer screening will be offered for free.\n 乳がんの検査が無料で提供される。", 
     "answer": "breast",
    "meaning": "breast	[名] （主に女性の）胸，乳房"},
    {"text": "1047 I’m confident in my ___ capacity.\n 私は肺活量に自信がある.🫁", 
     "answer": "lung",
    "meaning": "lung	[名] 肺〈可算〉"},
    {"text": "1048 Squids have a membrane that protects their internal ___.\n イカは内臓を守る膜を持つ.🦑", 
     "answer": "organs",
    "meaning": "organ	[名] ①臓器，(動植物の)器官 ②(楽器)オルガン（①②ともに<可算>）"}, 
    #1049
    {"text": "1050 draw the human ___.\n 人の骨格を描く🦴", 
     "answer": "skeleton",
    "meaning": "skeleton	[名] 骸骨，骨格"}, 
    {"text": "1051 Takeshi’s ___ is beyond the understanding of others.\n タケシの感覚は他の人には理解できない。", 
     "answer": "sensation",
    "meaning": "sensation	[名] ①感覚 ②（説明し難い）感情"},
    {"text": "1052 pay attention to the dress ___\n 服装の規定に注意を払う", 
     "answer": "code",
    "meaning": "code	[名] ①（服装などの）規定 ②暗号"},
    {"text": "1053 Environmental issues are on the ___ at the United Nations.\n 環境問題が国連の議題に上がる。", 
     "answer": "agenda",
    "meaning": "agenda	[名] 議題，協議事項"},
    {"text": "1054 ___ is guaranteed.\n 自由が保障される.", 
     "answer": "liberty",
    "meaning": "liberty	[名] 自由"},
    {"text": "1055 No one is running for the ___.\n 誰も委員会に立候補しない.😶‍🌫️", 
     "answer": "committee",
    "meaning": "committee	[名] 委員会"},
    {"text": "1056 Do you think Takeshi is included in ___?\n タケシは人類に含まれると思いますか？🤔", 
     "answer": "humanity",
    "meaning": "humanity	[名] ①（集合的に）人類 ②（the ―ies）人文科学 ③人間性"},
    {"text": "1057 ___ has achieved great prosperity over the past few centuries.\n 人類はここ数百年で大きな繁栄を遂げた。", 
     "answer": "mankind",
    "meaning": "mankind	[名] （集合的に）人類"},
    {"text": "1110 Logic is the ___ of clear thinking and good arguments.\n論理は明晰な思考と良い議論の基礎である。",
     "answer": "basis",
    "meaning": "basis	[名] ①基礎，根拠 ②（on a ～ basis）（～を）基準（として）"},
    {"text": "1117 succeed in escaping from ___\n脱獄に成功する",
     "answer": "prison",
    "meaning": "prison	[名] 刑務所"},
    {"text": "1122 heal emotional ___\n 心の傷を回復する💗", 
     "answer": "wounds",
    "meaning": "wound	[名] ①傷 [他] ②～を傷つける"}, 
    {"text": "1221 a pleasant ___\n心地よいそよかぜ🍃",
     "answer": "breeze",
    "meaning": "breeze	[名] そよ風"},
    {"text": "1236 I was bitten by ___ in 13 places.\n蚊に13か所刺された.😱",
     "answer": "mosquitoes",
    "meaning": "mosquito	[名] 蚊"},
    {"text": "1238 I got scratched on the arm by a ___.\n子猫に腕をひっかかれた.😼",
     "answer": "kitten",
    "meaning": "kitten	[名] 子ネコ"},
    {"text": "1279 Squids have a membrane that protects their ___ organs.\n イカは内臓を守る膜を持つ.🦑", 
     "answer": "internal",
    "meaning": "internal	[形] ①内部の，体内の ②国内の"}, 
    {"text": "1321 Takeshi often bumps his forehead into utility ___.\n タケシはよく電(柱)に額をぶつける.", 
     "answer": "poles",
    "meaning": "pole	[名] ①棒，さお，柱 ②（天体，地球の）極"},
    {"text": "1359 achieve my ___ to be a pilot\nパイロットになるという望みを叶える🧑‍✈️",
     "answer": "ambition",
    "meaning": "ambition	[名] （強い）願望，野望"},
    {"text": "1370 He was allegedly ___ by the teacher\n彼は先生に怒られたらしい",
     "answer": "scolded",
    "meaning": "scold	[他] ～を叱る"},
    {"text": "1385 ___ talent\n圧倒的な才能🧬",
     "answer": "overwhelming",
    "meaning": "talent	[名] 才能"},
    {"text": "1386 He was conscious during the ___ surgery.\n彼は手術中ずっと意識があった.😱",
     "answer": "entire",
    "meaning": "entire	[形] すべての"},
    {"text": "1475 appropriate clothes for an apology press ___\n謝罪会見にふさわしい服装🦹",
     "answer": "conference",
    "meaning": "conference	[名] (on ～)(～に関する)会議"},
    {"text": "1692 Scholarships help students pay for college ___ and expenses.\n奨学金は学生が大学の授業料や費用を支払うのを助ける.",
     "answer": "tuition",
    "meaning": "tuition	[名] ①〈米〉授業料 ②(少人数での)授業"},
    {"text": "1728 c___ education\n義務教育",
     "answer": "compulsory",
    "meaning": "compulsory	[形] ①義務的な ②規定の"},
    {"text": "1795 He said something shallow, pretending to be p___.\n彼は深そうに見せかけて浅いことを言った",
     "answer": "profound",
    "meaning": ""},
    {"text": "1803 ___ woman\n熟女👵",
     "answer": "mature",
    "meaning": "mature	[形] ①成熟した，熟成した [自] ②成熟する，熟成する"},
    {"text": "1870 At ___, the LGBTQ flag was raised from his house.\n夜が明けると,彼の家からLGBTQフラッグが上がった.🏳️‍🌈",
     "answer": "dawn",
    "meaning": "dawn	[名] ①夜明け [自] ②夜が明ける ③(on ～)(～に)わかり始める"},
    {"text": "1892 wet ___\n濡れたコンセント😱",
     "answer": "outlet",
    "meaning": "outlet	[名] ①(電気の)コンセント ②(販売)店 ③(感情などの)はけ口"},
    {"text": "1950 Everyone was ___ by his noisy electric eraser.\n彼のうるさい電動消しゴムにみんな気を散らされた.",
     "answer": "distracted",
    "meaning": "electric	[形] 電気の，電動の"},
    {"text": "1980 Hard work usually leads to a positive ___\n努力はたいてい良い結果につながる",
     "answer": "outcome",
    "meaning": "outcome	[名] 結果"},
    {"text": "1981 Hard work was a major ___ in the success\n彼の成功における大きな要因は彼の努力だ",
     "answer": "factor",
    "meaning": "factor	[名] 要因"},
    {"text": "1982 He is ___ to make mistakes when he is sleepy\n彼は眠いとき、間違いをしがちだ",
     "answer": "liable",
    "meaning": "liable	[形] ①（to do）～しがちだ ②（to ～）（病気などに）かかりやすい ③（for ～）（～に対して）（法的に）責任がある"},
    {"text": "1983 She did a ___ job cleaning the house\n彼女は家の掃除を徹底的にした",
     "answer": "thorough",
    "meaning": "thorough	[形] 完全な，徹底的な"},
    {"text": "1984 I don’t have ___ time to finish my homework\n私には宿題を終わらせる十分な時間がない",
     "answer": "adequate",
    "meaning": "adequate	[形] 十分な，適切な"},
    {"text": "1985 ___, I’m happy the result of the exam\n全体的に見て,私は試験の結果に満足だ",
     "answer": "overall",
    "meaning": "overall	[形] ①全体的な，全面的な [副] ②全体的に，全面的に"},
    {"text": "1986 We decided the ___ goal\n私たちは最終的な目標を決めた",
     "answer": "ultimate",
    "meaning": "ultimate	[形] 究極の，最終の"},
    {"text": "1987 She gave me a ___ smile \n彼女は私に心からの笑顔を見せた",
     "answer": "genuine",
    "meaning": "genuine	[形] ①（感情が）心からの ②（絵画などが）本物の"},
    {"text": "1988 There is a only ___ chance that he will get a girlfriend\n彼に彼女ができる可能性はわずかしかない",
     "answer": "slight",
    "meaning": "slight	[形] わずかな"},
    {"text": "1989 We decided to make a ___ change to make the school better\n私たちは学校をよりよくするために抜本的な変更をすることに決めた",
     "answer": "radical",
    "meaning": "radical	[形] ①根本的な，抜本的な ②過激な"},
    {"text": "1990 The mistake was so ___\nその間違いはとても些細なものだ",
     "answer": "trivial",
    "meaning": "trivial	[形] ささいな"},
    {"text": "1991 This drug is very ___\nこのクスリはとても強力だ🌿",
     "answer": "potent",
    "meaning": "potent	[形] 強力な"},
    {"text": "1992 She plays tennis, and he ___ enjoys it\n彼女はテニスをし、彼も同様にテニスを楽しむ🎾",
     "answer": "likewise",
    "meaning": "likewise	[副] 同様に，同じように"},
    {"text": "1993 This project is ___ impossible\nこのプロジェクトは事実上不可能だ",
     "answer": "virtually",
    "meaning": "virtually	[副] 事実上，ほとんど"},
    {"text": "1994 He ___ screamed in the classroom\n彼は突然教室で叫んだ🤪",
     "answer": "abruptly",
    "meaning": "abruptly	[副] 不意に，突然"},
    {"text": "1995 The door was ___ left open \n扉は故意的に開けられたままだった",
     "answer": "deliberately",
    "meaning": "deliberately	[副] ①故意に ②慎重に"},
    {"text": "1996 This toilet is reserved ___ for teachers\nこのトイレは教員専用です.",
     "answer": "exclusively",
    "meaning": "exclusively	[副] もっぱら，～専用で"},
    {"text": "1997 He was sleepy, ___ his poor performance\n彼は眠かった。それゆえに成績が悪かった",
     "answer": "hence",
    "meaning": "hence	[副] だから，それゆえに"},
    {"text": "1998 Two students were late, ___ Bob and Mike\n2人の生徒が遅刻した。すなわちボブとマイクだ",
     "answer": "namely",
    "meaning": "namely	[副] すなわち"},
    {"text": "1999 He was ___ scolded by the teacher\n彼は先生に怒られたらしい😢",
     "answer": "allegedly ",
    "meaning": "allegedly	[副] (本当かどうかはわからないが)伝えられるところによると"},
    {"text": "2000 Some students study hard, ___ others do the bare minimum\n熱心に勉強する生徒もいれば、最低限しかしない生徒もいる🤓🤪",
     "answer": "whereas",
    "meaning": "whereas	[接] ～だが一方"},
]
questions_2001_2300 = [
    {"text": "2013 Don’t count your chickens before they ___.\n卵がかえる前にヒヨコを数えるな🐣",
     "answer": "hatch",
    "meaning": "hatch	[自] ①（卵から）かえる，孵化する [他] ②（卵から）～をかえす ③（計画など）を企てる"},
    {"text": "2043 ___ the tale of the Straw Millionaire, trying to exchange a string for a Benz.\nわらしべ長者の物語を省略して,ひもをベンツと交換しようとする.",
     "answer": "Omitting",
    "meaning": "omit	[他] ～を省く"},
   
]
#Dreams are free; reality charges you interest every day.

def get_rank(score):
    return {0: "0%", 1: "25%", 2: "50%", 3: "75%", 4: "100%"}.get(score, "0%")

def score_to_weight(score):
    return {0: 16, 1: 8, 2: 4, 3: 2, 4: 1}.get(score, 16)

def build_result_flex(user_id):
    name = user_names.get(user_id, DEFAULT_NAME)

    # 各範囲の評価計算
    parts = []
    for title, questions in [("1-1000", questions_1_1000), ("1001-2000", questions_1001_2000)]:
        scores = user_scores.get(user_id, {})
        relevant_answers = [q["answer"] for q in questions]
        total_score = sum(scores.get(ans, 0) for ans in relevant_answers)
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
                {"type": "text", "text": f"Rating: {rate} %", "size": "md", "color": "#333333"},
                {"type": "text", "text": f"{rank}", "size": "md", "color": "#333333"},
            ],
        })

    # ランク別単語数・割合計算
    scores = user_scores.get(user_id, {})
    rank_counts = {"100%": 0, "75%": 0, "50%": 0, "25%": 0, "0%": 0}
    all_answers = [q["answer"] for q in questions_1_1000 + questions_1001_2000]
    for word in all_answers:
        score = scores.get(word, 0)
        rank_counts[get_rank(score)] += 1

    total_words = sum(rank_counts.values())
    rank_ratios = {rank: rank_counts[rank]/total_words for rank in rank_counts}

    # ランク別割合グラフ
    graph_components = []
    max_width = 200  # 最大横幅 px
    for rank in ["100%", "75%", "50%", "25%", "0%"]:
        width_percent = int(rank_ratios[rank]*100)  # 0〜100%
        color_map = {"100%": "#000000", "75%": "#b22222", "50%": "#4682b4", "25%": "#ffd700", "0%": "#c0c0c0"}
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
    rate1 = round((sum(user_scores.get(user_id, {}).get(q["answer"], 0) for q in questions_1_1000) / c1) * 2500) if c1 else 0
    rate2 = round((sum(user_scores.get(user_id, {}).get(q["answer"], 0) for q in questions_1001_2000) / c2) * 2500) if c2 else 0
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
def build_feedback_flex(is_correct, score, elapsed, correct_answer=None, label=None, meaning=None):
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
    questions = questions_1_1000 if range_str == "1-1000" else questions_1001_2000

    if range_str == "1001-2000":
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

    else:
        q = choose_weighted_question(user_id, questions)
        user_states[user_id] = (range_str, q["answer"])
        user_answer_start_times[user_id] = time.time()
        message = TextSendMessage(text=q["text"])

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
    "ヒント\n私は5回に1回出てきます。",
    "ヒント\n私は5回に1回出てきます。",
    "ヒント\n継続は力なり。",
    "ヒント\n継続は力なり。",
    "ヒント\n継続は力なり。",
    "ヒント\n勉強して下さい。",
    "ヒント\n勉強して下さい。",
    "ヒント\n勉強して下さい。",
    "ヒント\n雲外蒼天",
    "ヒント\n百聞は一見に如かず",
    "ヒント\nあなたが今電車の中なら、外の景色を見てみて下さい。",
    "ヒント\n最高のSランクに到達するためには、少なくとも2000問近く解く必要があります。",
    "ヒント\n木々は栄養を分け合ったり、病気の木に助け舟を出したりします。",
    "ヒント\n「ゆっくり行くものは、遠くまで行ける」ということわざがあります。",
    "ヒント\nWBGTをチェックして、熱中症に気を付けて下さい。",
    "ヒント\nすべての単語には5段階の把握度が付けられています。",
    "ヒント\n1回スカイダビングしたいのならばパラシュートは不要ですが、2回なら必要です。",
    "ヒント\nアメリカはルークを失い、イギリスはクイーンを失いました。",
    "ヒント\n@新しい名前　でランキングに表示される名前を変更できます。",
    "ヒント\n辞書に載っている最長単語は「pneumonoultramicroscopicsilicovolcanoconiosis」（超微細な火山性シリカの粉塵による肺の病気）。",
    "ヒント\n「set」は約430の意味を持っていて、最も多様な意味を持つ英単語と言われています。",
    "ヒント\n口を大きく開けずに済むので「I am」→「I'm」となりました。",
    "ヒント\n昔の英語では「knight」は「k」をちゃんと発音していました。",
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
    answer_length = 0 if is_multiple_choice else len(answer)
    X = elapsed**1.7 + score**1.5 - answer_length

    if X <= 8:
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
        score = user_scores[user_id].get(correct_answer, 0)

        elapsed = time.time() - user_answer_start_times.get(user_id, time.time())
        is_multiple_choice = (range_str == "1001-2000")
        label, delta = evaluate_X(elapsed, score, correct_answer, is_multiple_choice=is_multiple_choice)

        # q を取得して meaning を渡す
        questions = questions_1_1000 if range_str == "1-1000" else questions_1001_2000
        q = next((x for x in questions if x["answer"] == correct_answer), None)

        flex_feedback = build_feedback_flex(
            is_correct, score, elapsed,
            correct_answer=correct_answer,
            label=label if is_correct else None,
            meaning=q.get("meaning") if q else None
        )

        # 次の問題
        next_question_msg = send_question(user_id, range_str)

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
