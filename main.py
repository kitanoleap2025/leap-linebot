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
    {"text": "016 His family c___ his finally being accepted into college.\n彼の家族は,彼がついに大学に合格したことを祝った.㊗️",
     "answer": "celebrated"},
    {"text": """019 She was a___ "Best Excuse Maker" for always avoiding responsibility.\n彼女は常に責任を避けたことで「最高の言い訳メーカー」を受賞した.🏆""",
     "answer": "awarded"},
    {"text": """020 They d___ ignoring the group project as "respecting individual effort."\n彼らはグループ課題を無視することを「個人の努力を尊重する」と表現しました.""",
     "answer": "described"},
    {"text": "021 He e___ why he had missed the deadline.\n彼はなぜ締め切りを過ぎたのか説明した.",
     "answer": "explained"},
    {"text": "022 It is important to c___ effectively with others in a team.\nチームで効果的にコミュ二ケーションをとることは重要だ.",
     "answer": "communicate"},
    {"text": "024 The man running ahead is the one I p___ to run with.\n前を走っている男は,一緒に走ると約束した人だ.🏃‍➡️",
     "answer": "promised"},
    {"text": "025 He provided a lot of i___, none of which was useful.\n彼はたくさんの情報を提供したが,役に立つものはひとつもなかった.",
     "answer": "information"},
    {"text": "026 With modern t___, we can talk to anyone in the world except the person next to you.\n現代のテクノロジーでは,隣にいる人以外の誰とでも話すことができる.",
     "answer": "technology"},
    {"text": "027 r___ shows that sunlight improves mental health.\n研究によると,日光はメンタルヘルスを改善する.🌞",
     "answer": "research"},
    {"text": "029 People who can be replaced by a___ Intelligence\nAIに代替可能な人.",
     "answer": "artificial"},
    {"text": "031 Ancient Egyptians i___ the 365-day calendar.\n古代エジプト人は365日カレンダーを発明した。",
     "answer": "invented"},
    {"text": "034 He had the s___ to disappear whenever work started.\n彼は仕事が始まるといつも消える技術を持っていた.",
     "answer": "skill"},
    {"text": "035 No less important than knowledge is the a___ to question it.\n知識に劣らず重要なのは,それを疑問視する能力です.",
     "answer": "ability"},
    {"text": "037 Success often comes after continuous e___.\n成功はたいてい継続的な努力の後にやってくる.",
     "answer": "effort"},
    {"text": "040 a___ my ambition to be a pilot\nパイロットになるという望みを叶える🧑‍✈️",
     "answer": "achieve"},
    {"text": "043 This machine can p___ 10 parts in one minute.\nこの機械は１分で10個の部品を生産出来る.",
     "answer": "produce"},
    {"text": "044 c___ LINE stickers using the teather's face\n先生の顔でLINEスタンプを作る😱",
     "answer": "create"},
    {"text": "045 Kitano high school was e___ in 1873.\n北野高校は1873年に設立された.",
     "answer": "established"},
    {"text": "066 Even a small change can have a great effect on s___.\n小さな変化でも社会に大きな影響を与える.",
     "answer": "society"},
    {"text": "067 The code of Hammurabi is one of the oldest l___.\nハンムラビ法典(規定)は最古の法律の一つ。",
     "answer": "laws"},
    {"text": "068 We don't inherit the Earth from our a___, we borrow it from our children.\n私たちは先祖から地球を受け継ぐのではなく,子供たちから借りています.🌍",
     "answer": "ancestors"},
    {"text": "074 the key e___ that led to the suspension \n停学への決定打となる証拠",
     "answer": "evidence"},
    {"text": "078 I use p___ transportation to get to school.(不可算)\n私は学校に行くのに公共交通機関を利用しています.",
     "answer": "public"},
    {"text": "079 They v___ for confidence without thinking.\n彼らは考えずに信任に投票した.",
     "answer": "voted"},
    {"text": "085 The p___ is determined by supply and demand.\n価格は需要と供給で決まる.",
     "answer": "price"},
    {"text": "096 During World War II, British chess masters were assigned to codebreaking t___ involving the Enigma machine.\n\n第二次世界大戦中,イギリスのチェスマスターたちはエニグマ機に関わる暗号解読の仕事に就いていました.",
     "answer": "tasks"},
    {"text": "098 What you said h___ more than you think.\n君が言ったことは,君が思っているよりも傷ついたよ.😢",
     "answer": "hurt"},
    {"text": "101 d___ the pen of the person sitting next to me\n隣の席の人のペンを破壊する",
     "answer": "destroy"},
    {"text": "111 The captain rescued only the p___ from his own country.\n船長は自国の乗客だけを救出しました.",
     "answer": "passengers"},
    {"text": "115 He climbed the ladder of success, then kicked it away so no one else could f___.\n彼は成功のはしごを登り,それを蹴飛ばし,他の誰も追随できないようにした.",
     "answer": "follow"},
    {"text": "116 Not all who w___ are lost.\n彷徨う人全員が迷っているわけではない.",
     "answer": "wander"},
    {"text": """124 She was awarded "Best Excuse Maker" for always a___ responsibility.\n彼女は常に責任を避けたことで「最高の言い訳メーカー」を受賞した.🏆""",
     "answer": "avoiding"},
    {"text": "127 Complex i___ compose themselves of simple, ignored mistakes.\n複雑な問題は,無視された単純なミスから成り立っている.",
     "answer": "issues"},
    {"text": "135 s___ in escaping from prison\n脱獄に成功する",
     "answer": "succeed"},
    {"text": "136 m___ the last train\n終電を逃す",
     "answer": "miss"},
    {"text": "137 He m___ silence for wisdom, and loudness for leadership.\n彼は沈黙を賢さと勘違いし,声の大きさをリーダーシップと勘違いした.",
     "answer": "mistook"},
    {"text": "140 They h__ Jews from the Nazis.\n彼らはナチスからユダヤ人を隠した.",
     "answer": "hid"},
    {"text": "141 d___ her portrait\n彼女の似顔絵を描く🎨",
     "answer": "draw"},
    {"text": "146 At dawn, the LGBTQ flag was r___ from his house.\n夜が明けると、彼の家からLGBTQフラッグが上がった。🏳️‍🌈",
     "answer": "raised"},
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
    {"text": "189 His family celebrated his finally being ___ into college.\n彼の家族は,彼がついに大学に合格したことを祝った.㊗️",
     "answer": "accepted"},
    {"text": "197 First Olympic games a___ only naked men.\n初期オリンピックは裸の男性だけ参加できた。",
     "answer": "allowed"},
    {"text": "209 He s___ to side with the insects.\n彼はその虫の味方をするようだ.🐛",
     "answer": "seems"},
    {"text": "210 signs of an e___\n地震の兆候",
     "answer": "earthquake"},
    {"text": "215 The pond f___ over.\n池が一面凍った.",
     "answer": "froze"},
    {"text": "228 Takeshi's a___ implies betrayal.\nタケシは裏切りをほのめかす態度だ。",
     "answer": "attitude"},
    {"text": "239 a___ clothes for an apology press conference\n謝罪会見にふさわしい服装🦹",
     "answer": "appropriate"},
    {"text": "241 e___ school memories\n小学校の思い出",
     "answer": "elementary"},
    {"text": "243 It is not what happened that m____. It is how you respond.\n大事なのは何が起きたかではない.どう応じるかだ.",
     "answer": "matters"},
    {"text": "248 a p___ breeze\n心地よいそよかぜ",
     "answer": "pleasant"},
    {"text": "258 People tend to accept ideas not because they are true, but because they are f___.\n人々はアイデアが真実だからではなく,馴染みがあるから受け入れる傾向があります.",
     "answer": "familiar"},
    {"text": "269 Don’t c___ your chickens before they hatch.\n卵がかえる前にヒヨコを数えるな",
     "answer": "count"},
    {"text": "284 A:What movie has no kissing s___?\nB:Your life.\nA:キスシーンの無い映画は？",
     "answer": "scenes"},
    {"text": "291 S___ has come.\n春が来た.",
     "answer": "spring"},
    #{"text": "291(2) hot s___ \n温泉♨️",
     #"answer": "spring"},
    {"text": "294 a g___ gap\n世代間格差",
     "answer": "generation"},
    {"text": "309 A:Teacher, I feel like I might be a g___ can.\nB:What a trashy joke.\n\nA:先生、私は自分がゴミ箱なんじゃないかと思っているのですが。\nB:そんなゴミみたいな冗談を。🗑️",
     "answer": "garbage"},
    {"text": "311 If you put w___ on a grandma, can you call it a bicycle?\nおばあちゃんに車輪を付けたら,自転車と呼べるのか.👵",
     "answer": "wheels"},
    {"text": "315 Omitting the tale of the Straw Millionaire, trying to exchange a s___ for a Benz.\nわらしべ長者の物語を省略して,ひもをベンツと交換しようとする.",
     "answer": "string"},
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
    {"text": "360 The truth is often simple, but people p___ complex answers.\n真実はしばしば単純ですが,人々は複雑な答えを好みます.",
     "answer": "prefer"},
    {"text": "362 All America w___.\n全米が泣いた.😢",
     "answer": "wept"},
    {"text": "378 Even a small change can have a great e___ on society.\n小さな変化でも社会に大きな影響を与える.",
     "answer": "effect"},
    {"text": "393 e___ a small change can have a great effect on society.\n小さな変化でも社会に大きな影響を与える.",
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
    {"text": "449 He was conscious during the entire s___.\n彼は手術中ずっと意識があった.😱",
     "answer": "surgery"},
    {"text": "454 Call an a___!\n救急車を呼んで!",
     "answer": "ambulance"},
    {"text": "465 attempt to regenerate m___ tissue.\n筋組織の再生を試みる.",
     "answer": "muscle"},
    {"text": "471 r___ discrimination\n人種差別",
     "answer": "racial"},
    {"text": "479 All animals are e___, but some animals are more e___ than others.\n全ての動物は平等だが、中には他よりもっと平等な動物もいる。",
     "answer": "equal"},
    {"text": "483 Social Networking S___\nソーシャル・ネットワーキング・サービス",
     "answer": "service"},
    {"text": "490 racial d___\n人種差別",
     "answer": "discrimination"},
    {"text": """495 They described ignoring the group project as "respecting ___ effort."\n彼らはグループ課題を無視することを「個人の努力を尊重する」と表現しました.""",
     "answer": "individual"},
    {"text": "500 The consumption tax should be a___.\n消費税は廃止されるべきだ.",
     "answer": "abolished"},
    {"text": "507 fulfill my d___\n義務を果たす",
     "answer": "duties"},
    {"text": "512 Scholarships help students pay for college tuition and e___.\n奨学金は学生が大学の授業料や費用を支払うのを助ける.",
     "answer": "expenses"},
    {"text": "522 Don't w___ your precious time.\n貴重な時間を浪費するな.⌛",
     "answer": "waste"},
    {"text": "527 During World War II, British chess masters were a___ to codebreaking tasks involving the Enigma machine.\n第二次世界大戦中,イギリスのチェスマスターたちはエニグマ機に関わる暗号解読の仕事に就いていました.",
     "answer": "assigned"},
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
    {"text": "572 Honey never s___.\nはちみつは腐りません.(台無しにならない.)🍯",
     "answer": "spoils"},
    {"text": "573 The Colosseum could hold up to 50,000 s___.\nコロッセオは5万人まで収容可能だった。",
     "answer": "spectators"},
    {"text": "574 [2]Einstein argued that time is r___.\nアインシュタインは時間は相対的だと論じた.",
     "answer": "relative"},
    {"text": "577 I use public t___ to get to school.(不可算)\n私は学校に行くのに公共交通機関を利用しています.",
     "answer": "transportation"},
    {"text": "594 Einstein was offered the presidency of Israel but he r___.\nアインシュタインはイスラエル大統領の職を申し出られたが、断った。",
     "answer": "refused"},
    {"text": "597 He was f___ to go out for nearly a decade.\n彼は10年近く外出を禁止された.",
     "answer": "forbidden"},
    {"text": "602 Ideas attach quickest to the minds already half c___.\n考えは半分納得した心に一番早くくっつく.",
     "answer": "convinced"},
    {"text": "604 Fake news s___ faster than real news.\n フェイクニュースは本当のニュースより速く拡散する.",
     "answer": "spreads"},
    {"text": "610 I can r___ everything except temptation.\n私は誘惑以外の全てに耐えうる.",
     "answer": "resist"},
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
    {"text": "644 s___ while the iron is hot\n鉄は熱いうちに打て",
     "answer": "strike"},
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
    {"text": "720 s___ power generation\n太陽光発電🌞",
     "answer": "solar"},
    {"text": "723 according to the weather f___\n天気予報によれば",
     "answer": "forecast"},
    {"text": "724 The summer in Juso is hot and h___.\n十三の夏は蒸し暑い.",
     "answer": "humid"},
    {"text": "725 t___ rainforests\n熱帯雨林",
     "answer": "tropical"},
    {"text": "751 a___ clock\n正確な時計⌚",
     "answer": "accurate"},
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
    {"text": "779 He simply finds pleasure in the s___ walk.\n彼はただ着実な歩みを楽しんでいるのです。",
     "answer": "steady"},
    {"text": "791 F___ news spreads faster than real news.\n フェイクニュースは本当のニュースより速く拡散する.",
     "answer": "fake"},
    {"text": "803 b___ shoes\n新品の靴👟",
     "answer": "brand-new"},
    {"text": "808 First Olympic games allowed only n___ men.\n初期オリンピックは裸の男性だけ参加できた.🔥",
     "answer": "naked"},
    {"text": "820 People t___ to accept ideas not because they are true, but because they are familiar.\n人々はアイデアが真実だからではなく,馴染みがあるから受け入れる傾向がある.",
     "answer": "tend"},
    {"text": "823 glass f___\nガラスの破片",
     "answer": "fragments"},
    {"text": "839 an enormous a___ of fat\n莫大な(量の)脂肪",
     "answer": "amount"},
    {"text": "842 an e___ amount of fat\n莫大な(量の)脂肪",
     "answer": "enormous"},
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
    {"text": "877 answer a q___\nアンケートに答える",
     "answer": "questionnaire"},
    {"text": "890 It's okay to take a n__.\n昼寝しても大丈夫だよ.💤",
     "answer": "nap"},
    {"text": "892 v___ m___\n 自動販売機",
     "answer": "vending machine"},
    {"text": "898 get d___ at 21\n21で離婚する🤰",
     "answer": "divorced"},
    {"text": "901 I want to t___ to the art course.\n美術コースに転向したい.🎨",
     "answer": "transfer"},
    {"text": "906 cover one’s t___\n足跡を消す👣",
     "answer": "tracks"},
    {"text": "907 the Airin d___ in Osaka\n大阪のあいりん地区",
     "answer": "district"},
    {"text": "915 Mesopotamian c___\nメソポタミア文明",
     "answer": "civilization"},
    {"text": "924 p___\nことわざ",
     "answer": "proverb"},
    {"text": "925 Omitting the t___ of the Straw Millionaire, trying to exchange a string for a Benz.\nわらしべ長者の物語を省略して,ひもをベンツと交換しようとする.",
     "answer": "tale"},
    {"text": "924 to p___ E = mc²\nE=mc²を証明する",
     "answer": "prove"},
    {"text": "942 The pop star’s cheating scandal a___ media attention.\n人気スターの不倫騒動はマスコミの関心を引き付けた.",
     "answer": "attracted"},
    {"text": "949 be a___ in programming\nプログラミングに没頭する",
     "answer": "absorbed"},
    {"text": "950 I am f___ of reading books.\n本を読むことが好きだ.📚",
     "answer": "fond"},
    {"text": "953 b___ feast\nつまらない宴会",
     "answer": "bored"},
    {"text": "956 I feel e___ when I hear compliments.\n褒め言葉を聞いて照れる.",
     "answer": "embarrassed"},
    {"text": "960 I’m r___ to study Japanese.\n国語を勉強するのは気が進まない.",
     "answer": "reluctant"},
    {"text": "968 show my e___\n感情をむき出しにする🤬",
     "answer": "emotions"},
    {"text": "972 have the c___ to say no\n断る勇気を持つ",
     "answer": "courage"},
    {"text": """978 They described i___ the group project as "respecting individual effort".\n彼らはグループ課題を無視することを「個人の努力を尊重する」と表現しました.""",
     "answer": "ignoring"},
    {"text": "992 We shape our tools, and e___, our tools shape us.\n私たちは道具を作るが,結果として,道具が私たちを作る.",
     "answer": "eventually"},
    {"text": "993 He argued that sleep wasn’t n___ for eaxms.\n彼は試験のために睡眠は必要ないと主張した.",
     "answer": "necessary"},
    {"text": "994 F___ speaking,\n率直に言うと,",
     "answer": "frankly"},
    {"text": "978 Complex issues compose themselves of simple, i___ mistakes.\n複雑な問題は,無視された単純なミスから成り立っている.",
     "answer": "ignored"},
    {"text": "1000 a___ t__ capitalism, your value peaks at checkout.\n資本主義によると,あなたの価値はチェックアウト時にピークに達する.",
     "answer": "according to"},
    {"text": "782 m___ woman\n熟女👵",
     "answer": "mature"},
]
questions_1001_1935 = [
    {"text": "1001 ___ travel plan\n旅行の計画を提案する",
     "answer": "propose",
    "meaning": "propose\n[他] ①～を提案する [自] ②（to ～）（～に）結婚を申し込む"},
    {"text": "1002 ___ Takeshi's idea as impossible\n不可能だとしてタケシの考えを退ける",
     "answer": "dismiss",
    "meaning": "dismiss\n[他] ①（意見や考えなど）を退ける ②～を解雇する"},
    {"text": "1003 I ___ you.\n私はあなたを祝福する.",
     "answer": "bless",
    "meaning": "bless\n[他] ～を祝福する"},
    {"text": "1004 remember the past ___\n過去の栄光を思い出す",
     "answer": "glory",
    "meaning": "glory\n[名] 栄光"},
    {"text": "1005 I feel embarrassed when I hear ___.\n褒め言葉を聞いて照れる.",
     "answer": "compliments",
    "meaning": "compliment	[名] ①褒め言葉，賛辞 [他] ②～を褒める"},
    {"text": "1006 bored ___\nつまらない宴会",
     "answer": "feast",
    "meaning": "feast	[名] ①宴会，祝宴 ②とても楽しいこと，喜ばせるもの"},
    {"text": "1007 Takeshi ___ that he has never lied.\nタケシは嘘をついたことがないとはっきりと述べた.",
     "answer": "declared",
    "meaning": "declare	[他] ①～を宣言する ②（税関や税務署で）～を申告する"},
    {"text": "1008 ___ an important part\n重要な部分を強調する",
     "answer": "highlight",
    "meaning": "highlight	[他] ①～を強調する [名] ②呼び物，目玉商品，ハイライト"},
    {"text": "1009 Takeshi's attitude ___ betrayal.\nタケシは裏切りをほのめかす態度だ.",
     "answer": "implies",
    "meaning": "imply	[他] ～をほのめかす，（暗に）～を意味する"},
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
    {"text": "1021 A ___ becomes a liquid when heated.\n固体は加熱すると液体になる.",
     "answer": "solid",
     "meaning": ""},
    {"text": "1022 A ___ falls to Earth.\n人工衛星が墜落する.",
     "answer": "satellite",
     "meaning": ""},
    {"text": "1023 The Earth’s ___ changes.\n地球の軌道が変わる.",
     "answer": "orbit",
    "meaning": ""},
    {"text": "1024 ___ a plastic bottle rocket\nペットボトルロケットを打ち上げる",
     "answer": "launch",
    "meaning": ""},
    {"text": "1025 ___ to regenerate muscle tissue.\n筋組織の再生を試みる.",
     "answer": "attempt",
    "meaning": "attempt	[名] ①試み [他] ②（to do）（～しようと）試みる"},
    {"text": "1026 Takeshi has a hidden ___.\nタケシには隠された能力がある.",
     "answer": "capacity",
    "meaning": ""},
    {"text": "1027 It seems that all Kitano students are ___ of studying well.\n北野生は全員勉強がよくできるらしい.",
     "answer": "capable",
    "meaning": ""},
    {"text": "1028 ___ a short-term goal\n目先の目標を達成する",
     "answer": "attain",
    "meaning": ""},
    {"text": "1029 be ___ to finish my homework\n宿題を終わらせるのに必死になる",
     "answer": "desperate",
    "meaning": ""},
    {"text": "1030 I ___ my youth to studying.\n私は青春を勉強に捧げた.",
     "answer": "dedicated",
    "meaning": ""}, 
    {"text": "1031 There is no success without ___.\n苦しみなくして成功なし.",
     "answer": "pain",
    "meaning": ""}, 
    {"text": "1032 It puts a ___ on the body.\nそれは身体に負担がかかる.",
     "answer": "strain",
    "meaning": ""}, 
    {"text": "1033 find a ___ for a serious illness\n深刻な病気の治療法を見つける",
     "answer": "remedy",
    "meaning": ""}, 
    {"text": "1034 I will go to the nearby ___.\n私は近くの薬局に行くつもりだ.",
     "answer": "pharmacy",
    "meaning": ""}, 
    {"text": "1052 The ___ of Hammurabi is one of the oldest laws.\nハンムラビ法典(規定)は最古の法律の一つ。",
     "answer": "code",
    "meaning": "code	[名] ①（服装などの）規定 ②暗号"},
    
     {"text": "",
     "answer": "",
    "meaning": ""}, 
    
    {"text": "1110 Logic is the ___ of clear thinking and good arguments.\n論理は明晰な思考と良い議論の基礎である。",
     "answer": "basis",
    "meaning": "basis	[名] ①基礎，根拠 ②（on a ～ basis）（～を）基準（として）"},
    {"text": "1117 succeed in escaping from ___\n脱獄に成功する",
     "answer": "prison",
    "meaning": "prison	[名] 刑務所"},
    {"text": "1221 a pleasant ___\n心地よいそよかぜ🍃",
     "answer": "breeze",
    "meaning": "breeze	[名] そよ風"},
     {"text": "1236 I was bitten by ___ in 13 places.\n蚊に13か所刺された.😱",
     "answer": "mosquitoes",
     "meaning": "mosquito	[名] 蚊"},
    {"text": "1238 I got scratched on the arm by a ___.\n子猫に腕をひっかかれた.😼",
     "answer": "kitten",
    "meaning": "kitten	[名] 子ネコ"},
    {"text": "1359 achieve my ___ to be a pilot\nパイロットになるという望みを叶える🧑‍✈️",
     "answer": "ambition",
    "meaning": "ambition	[名] （強い）願望，野望"},
    {"text": “1370 He was allegedly ___ by the teacher\n彼は先生に怒られたらしい",
     "answer": "scolded",
    "meaning": ""},
    {"text": "1386 He was conscious during the ___ surgery.\n彼は手術中ずっと意識があった.😱",
     "answer": "entire",
    "meaning": "entire	[形] すべての"},
    {"text": "1475 appropriate clothes for an apology press ___\n謝罪会見にふさわしい服装🦹",
     "answer": "conference",
    "meaning": "conference	[名] (on ～)(～に関する)会議"},
    {"text": "1692 Scholarships help students pay for college ___ and expenses.\n奨学金は学生が大学の授業料や費用を支払うのを助ける.",
     "answer": "tuition",
    "meaning": "tuition	[名] ①〈米〉授業料 ②(少人数での)授業"},
    {"text": "1870 At ___, the LGBTQ flag was raised from his house.\n夜が明けると,彼の家からLGBTQフラッグが上がった.🏳️‍🌈",
     "answer": "dawn",
    "meaning": "dawn	[名] ①夜明け [自] ②夜が明ける ③(on ～)(～に)わかり始める"},
    {"text": "1892 wet ___\n濡れたコンセント😱",
     "answer": "outlet",
    "meaning": "outlet	[名] ①(電気の)コンセント ②(販売)店 ③(感情などの)はけ口"},
    {"text": "1996 This toilet is reserved ___ for teachers\nこのトイレは教員専用です.",
     "answer": "exclusively",
    "meaning": ""},
    {"text": “1997 He was sleepy, ___ his poor performance\n彼は眠かった。それゆえに成績が悪かった",
     "answer": "hence",
    "meaning": ""},
    {"text": “1998 Two students were late, ___ Bob and Mike\n2人の生徒が遅刻した。すなわちボブとマイクだ",
     "answer": "namely",
    "meaning": ""},
    {"text": “1999 He was ___ scolded by the teacher\n彼は先生に怒られたらしい",
     "answer": "allegedly ",
    "meaning": ""},
    {"text": "2000 Some students study hard, ___ others do the bare minimum\n熱心に勉強する生徒もいれば、最低限しかしない生徒もいる",
     "answer": "whereas",
    "meaning": ""},
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
    for title, questions in [("1-1000", questions_1_1000), ("1001-1935", questions_1001_1935)]:
        scores = user_scores.get(user_id, {})
        relevant_answers = [q["answer"] for q in questions]
        total_score = sum(scores.get(ans, 0) for ans in relevant_answers)
        count = len(relevant_answers)

        rate = round((total_score / count) * 2500) if count else 0
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
                {"type": "text", "text": f"Rating: {rate}", "size": "md", "color": "#333333"},
                {"type": "text", "text": f"{rank}", "size": "md", "color": "#333333"},
            ],
        })

    # ランク別単語数・割合計算
    scores = user_scores.get(user_id, {})
    rank_counts = {"100%": 0, "75%": 0, "50%": 0, "25%": 0, "0%": 0}
    all_answers = [q["answer"] for q in questions_1_1000 + questions_1001_1935]
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
    total_score2 = sum(scores.get(q["answer"], 0) for q in questions_1001_1935)

    c1 = len(questions_1_1000)
    c2 = len(questions_1001_1935)

    rate1 = round((total_score1 / c1) * 2500) if c1 else 0
    rate2 = round((total_score2 / c2) * 2500) if c2 else 0

    total_rate = round((rate1 + rate2) / 2)

    try:
        db.collection("users").document(user_id).update({"total_rate": total_rate})
    except Exception as e:
        print(f"Error updating total_rate for {user_id}: {e}")

    return total_rate


#FEEDBACK　flex
def build_feedback_flex(is_correct, score, elapsed, rank, correct_answer=None, label=None, meaning=None):
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
            "text": f"意味: {meaning}",
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

#1001-1935を4択
def send_question(user_id, range_str):
    questions = questions_1_1000 if range_str == "1-1000" else questions_1001_1935

    if range_str == "1001-1935":
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
                f"{my_name}:#{user_pos}\nTotal Rate:{my_rate}\n"
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

    if msg in ["1-1000", "1001-1935"]:
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
        is_multiple_choice = (range_str == "1001-1935")
        label, delta = evaluate_X(elapsed, score, correct_answer, is_multiple_choice=is_multiple_choice)

        if is_correct:
            rank = get_rank(score)
            user_scores[user_id][correct_answer] = min(4, score + delta)
        else:
            rank = get_rank(score)
            user_scores[user_id][correct_answer] = max(0, score - 1)

        # q を取得して meaning を渡す
        questions = questions_1_1000 if range_str == "1-1000" else questions_1001_1935
        q = next((x for x in questions if x["answer"] == correct_answer), None)

        flex_feedback = build_feedback_flex(
            is_correct, score, elapsed, rank,
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
        TextSendMessage(text="1-1000 または 1001-1935 を押してね。")
    )

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port)
