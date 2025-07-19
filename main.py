from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.models import MessageEvent, TextMessage, TextSendMessage
from linebot.exceptions import InvalidSignatureError
import os
import random
from dotenv import load_dotenv

load_dotenv()
app = Flask(__name__)

line_bot_api = LineBotApi(os.getenv("LINE_CHANNEL_ACCESS_TOKEN"))
handler = WebhookHandler(os.getenv("LINE_CHANNEL_SECRET"))

user_states = {}        # 出題中のユーザーと正解
user_histories = {}     # 出題範囲ごとの正誤履歴（最大100件）
active_games = {}       # ゲーム進行中のユーザーとゲームオブジェクト

# --- 英単語問題リスト ---
questions_1_1000 = [
    {"text": "001 I ___ with the idea that students should not be given too much homework.\n生徒に宿題を与えすぎるべきではないという考えに賛成です.", "answer": "agree"},
    # 必要に応じて追加
]

questions_1000_1935 = [
    {"text": "1001 The ___ made a critical discovery in the lab.\nその科学者は研究室で重大な発見をした。", "answer": "scientist"},
    # 必要に応じて追加
]

# --- ショットガンロシアンルーレットゲームクラス ---
class ShotgunRussianRoulette:
    def __init__(self):
        self.player_hp = 2
        self.dealer_hp = 2
        self.new_chamber()
        self.turn = "player"
        self.items = ["手錠", "アドレナリン", "携帯", "タバコ", "爆弾", "空砲"]
        self.player_items = [random.choice(self.items) for _ in range(3)]
        self.dealer_items = [random.choice(self.items) for _ in range(3)]
        self.used_phone = False
        self.adrenaline_used = False

    def new_chamber(self):
        self.live = random.randint(1, 3)
        self.empty = random.randint(1, 3)
        self.bullets = ['live'] * self.live + ['empty'] * self.empty
        random.shuffle(self.bullets)
        self.current_index = 0

    def get_item_display(self):
        return (
            f"🧰 Your items: {', '.join(self.player_items)}\n"
            f"🤖 Dealer items: {', '.join(self.dealer_items)}"
        )

    def player_action(self, choice):
        result = ""
        if self.current_index >= len(self.bullets):
            result += f"🔄再装填：実弾{self.live}発、空砲{self.empty}発\n"
            self.new_chamber()

        if choice.startswith("use "):
            item = choice[4:].strip()
            if item not in self.player_items:
                return "そんなアイテムは持っていません。", False

            effect = self.use_item("player", item)
            self.player_items.remove(item)
            result += f"🧪 {item}を使った！効果：{effect}"
            return result, False  # アイテム使用はターン消費しない

        bullet = self.bullets[self.current_index]
        self.current_index += 1

        if choice == "1":
            if bullet == 'live':
                if self.adrenaline_used:
                    self.adrenaline_used = False
                    result += "💥自分に撃ったが、アドレナリンで耐えた！\n"
                else:
                    self.player_hp -= 1
                    result += "💥自分に撃った！実弾だった…ダメージ！\n"
                self.turn = "dealer"
            else:
                result += "💨自分に撃った！空砲！ノーダメージ。\n"
        elif choice == "2":
            if bullet == 'live':
                self.dealer_hp -= 1
                result += "🔫相手に撃った！実弾命中！\n"
            else:
                result += "💨相手に撃った！空砲！ノーダメージ。\n"
            self.turn = "dealer"
        else:
            return "1 か 2 または 'use アイテム名' を入力してください。", False

        return result, True

    def use_item(self, who, item):
        if item == "手錠":
            # 相手のターンをスキップさせる
            self.turn = who  # 自分のターン継続
            return "相手のターンをスキップ！"
        if item == "アドレナリン":
            if who == "player":
                self.adrenaline_used = True
            return "次の自傷実弾を1HPで耐える！"
        if item == "携帯":
            if who == "player":
                self.used_phone = True
            return "助けを呼んだ！（効果なし）"
        if item == "タバコ":
            if who == "player":
                if self.player_hp < 2:
                    self.player_hp += 1
                    return "HP+1"
                else:
                    return "効果なし（HP満タン）"
            else:
                return "効果なし（ディーラー）"
        if item == "爆弾":
            if who == "player":
                self.dealer_hp -= 1
                return "相手にダメージ！"
            else:
                self.player_hp -= 1
                return "自爆ダメージ！"
        if item == "空砲":
            self.bullets.insert(self.current_index, 'empty')
            return "次弾が確定で空砲に！"
        return "効果なし"

    def dealer_action(self):
        result = ""
        if self.current_index >= len(self.bullets):
            result += f"🔄ディーラーが再装填：実弾{self.live}発、空砲{self.empty}発\n"
            self.new_chamber()

        bullet = self.bullets[self.current_index]
        self.current_index += 1

        # AI行動ロジック
        if self.player_hp == 1 or random.random() < 0.7:
            target = "player"
        else:
            target = "self"

        if target == "player":
            if bullet == 'live':
                self.player_hp -= 1
                result += "💥ディーラーはあなたに撃った！実弾命中！\n"
            else:
                result += "💨ディーラーはあなたに撃った！空砲！\n"
            self.turn = "player"
        else:
            if bullet == 'live':
                self.dealer_hp -= 1
                result += "💥ディーラーは自分に撃った！実弾！\n"
                self.turn = "player"
            else:
                result += "💨ディーラーは自分に撃った！空砲！ターン継続。\n"
                self.turn = "dealer"
                return result, True

        return result, True

    def get_status(self):
        return f"HP - YOU: {'🔥' * self.player_hp} / DEALER: {'🔥' * self.dealer_hp}"

    def is_game_over(self):
        if self.player_hp <= 0:
            return "dealer"
        elif self.dealer_hp <= 0:
            return "player"
        return None

# --- 成績テキスト生成関数 ---
def build_result_text(user_id):
    h1 = user_histories.get(user_id + "_1_1000", [])
    h2 = user_histories.get(user_id + "_1000_1935", [])

    def score_text(history, title):
        count = len(history)
        correct = sum(history)
        if count == 0:
            return f"【🤔Your Performance\n（{title}）】\nNo questions solved, but you expect a grade?"
        accuracy = correct / 100
        rate = round(accuracy * 1000)
        if rate >= 970:
            rank = "S Rank🤩"
        elif rate >= 900:
            rank = "A Rank😎"
        elif rate >= 800:
            rank = "B Rank😤"
        elif rate >= 500:
            rank = "C Rank🫠"
        else:
            rank = "D Rank😇"
        return (
            f"【✏️Your Performance\n（{title}）】\n"
            f"✅ Score: {correct} / {count}\n"
            f"📈 Rating: {rate}\n"
            f"🏆 Grade: {rank}"
        )

    return score_text(h1, "1-1000") + "\n\n" + score_text(h2, "1000-1935")

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

    # 成績表示
    if msg == "成績":
        if user_id in active_games:
            del active_games[user_id]
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="🎮ゲームを強制終了しました。成績を表示します。")
            )
        result_text = build_result_text(user_id)
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=result_text))
        return

    # ゲーム開始コマンド
    if msg == "game":
        if user_id in active_games:
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="すでにゲーム中です。")
            )
            return
        game = ShotgunRussianRoulette()
        active_games[user_id] = game
        reply_text = "🎮ゲーム開始！\n" + game.get_item_display() + "\n" + game.get_status() + "\n1：自分に撃つ 2：相手に撃つ\nアイテムは 'use アイテム名' で使用可能。"
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
        return

    # ゲーム中の操作
    if user_id in active_games:
        game = active_games[user_id]
        if game.turn != "player":
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="今はあなたのターンではありません。")
            )
            return

        result, turn_consumed = game.player_action(msg)
        reply_text = result + "\n" + game.get_status()

        # ゲーム終了判定
        winner = game.is_game_over()
        if winner:
            if winner == "player":
                reply_text += "\n🎉あなたの勝ちです！"
            else:
                reply_text += "\n😭あなたの負けです。"
            del active_games[user_id]
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
            return

        # ターンがディーラーに移ったらディーラー行動
        if game.turn == "dealer":
            dealer_result, _ = game.dealer_action()
            reply_text += "\n" + dealer_result + game.get_status()
            winner = game.is_game_over()
            if winner:
                if winner == "player":
                    reply_text += "\n🎉あなたの勝ちです！"
                else:
                    reply_text += "\n😭あなたの負けです。"
                del active_games[user_id]
            else:
                game.turn = "player"
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
        return

    # --- 英単語問題出題処理 ---
    if msg == "1-1000":
        if user_id in active_games:
            del active_games[user_id]
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="🎮ゲームを強制終了しました。問題を出題します。")
            )

        q = random.choice(questions_1_1000)
        user_states[user_id] = ("1-1000", q["answer"])
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=q["text"]))
        return

    if msg == "1000-1935":
        if user_id in active_games:
            del active_games[user_id]
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="🎮ゲームを強制終了しました。問題を出題します。")
            )

        q = random.choice(questions_1000_1935)
        user_states[user_id] = ("1000-1935", q["answer"])
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=q["text"]))
        return

    # --- 英単語回答処理 ---
    if user_id in user_states:
        question_range, correct_answer = user_states[user_id]
        is_correct = (msg.lower() == correct_answer.lower())

        key = user_id + ("_1_1000" if question_range == "1-1000" else "_1000_1935")
        history = user_histories.get(key, [])
        history.append(1 if is_correct else 0)
        if len(history) > 100:
            history.pop(0)
        user_histories[key] = history

        feedback = (
            "Correct answer✅\n\nNext：" if is_correct else f"Incorrect❌ The correct answer is 「{correct_answer}」.\nNext："
        )

        q = random.choice(questions_1_1000 if question_range == "1-1000" else questions_1000_1935)
        user_states[user_id] = (question_range, q["answer"])

        line_bot_api.reply_message(
            event.reply_token,
            messages=[
                TextSendMessage(text=feedback),
                TextSendMessage(text=q["text"])
            ]
        )
        return

    # --- 1 または 2 がゲーム中以外で送られた場合の案内 ---
    if msg in ["1", "2"]:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="まず「game」と送ってゲームを開始して下さい。")
        )
        return

    # --- 未対応コマンドのデフォルト応答 ---
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text="Press button 1-1000 or 1000-1935!")
    )

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port)
