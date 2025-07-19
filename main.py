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

    def new_chamber(self):
        self.live = random.randint(1, 3)
        self.empty = random.randint(1, 3)
        self.bullets = ['live'] * self.live + ['empty'] * self.empty
        random.shuffle(self.bullets)
        self.current_index = 0

    def player_action(self, choice):
        result_text = ""

        if self.current_index >= len(self.bullets):
            result_text += "🔄装填完了："
            self.new_chamber()
            result_text += f"実弾{self.live}発、空砲{self.empty}発\n"

        bullet = self.bullets[self.current_index]
        self.current_index += 1

        if choice == "1":  # 自分に撃つ
            if bullet == 'live':
                self.player_hp -= 1
                result_text += "💥自分に撃った！実弾だった…ダメージ！"
                self.turn = "dealer"
            else:
                result_text += "💨自分に撃った！空砲！ノーダメージ。ターン継続！"
                # ターンは変えない
        elif choice == "2":  # 相手に撃つ
            if bullet == 'live':
                self.dealer_hp -= 1
                result_text += "🔫相手に撃った！実弾命中！"
            else:
                result_text += "💨相手に撃った！空砲！ノーダメージ。"
            self.turn = "dealer"
        else:
            return "1 か 2 を入力してください。", False

        return result_text, True

    def dealer_action(self):
        result_text = ""

        if self.current_index >= len(self.bullets):
            result_text += "🔄ディーラーが再装填："
            self.new_chamber()
            result_text += f"実弾{self.live}発、空砲{self.empty}発\n"

        bullet = self.bullets[self.current_index]
        self.current_index += 1

        # 戦略性：プレイヤーHP1なら攻撃、それ以外は確率で自分撃ち or プレイヤー撃ちを決定
        if self.player_hp == 1 or (self.player_hp == 2 and random.random() < 0.7):
            choice = "shoot"
        else:
            choice = "self"

        if choice == "shoot":
            if bullet == 'live':
                self.player_hp -= 1
                result_text += "💥ディーラーはあなたに撃った！実弾命中！"
            else:
                result_text += "💨ディーラーはあなたに撃った！空砲！ノーダメージ。"
            self.turn = "player"
        else:
            if bullet == 'live':
                self.dealer_hp -= 1
                result_text += "💥ディーラーは自分に撃った！実弾だった…ダメージ！"
                self.turn = "player"
            else:
                result_text += "💨ディーラーは自分に撃った！空砲！ノーダメージ。ターン継続！"
                # ターン継続（ディーラー続行）
                self.turn = "dealer"
                return result_text, True

        return result_text, True

    def get_status(self):
        return f"HP - YOU: {'🔥' * self.player_hp} / DEALER: {'🔥' * self.dealer_hp}"

    def is_game_over(self):
        if self.player_hp <= 0:
            return "dealer"
        elif self.dealer_hp <= 0:
            return "player"
        return None


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
    msg = event.message.text.strip().lower()

    # --- ゲーム処理 ---
    if msg == "game":
        # ゲーム開始。既にゲーム中なら上書き。
        game = ShotgunRussianRoulette()
        active_games[user_id] = game
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(
                text=(
                    f"🎲 BackShot Roulette\n"
                    f"新しい装填：実弾{game.live}発、空砲{game.empty}発\n"
                    f"{game.get_status()}\n"
                    "1: 自分を撃つ / 2: 相手を撃つ"
                )
            )
        )
        return

    if user_id in active_games:
        game = active_games[user_id]
        result = ""

        if game.turn == "player":
            if msg in ["1", "2"]:
                player_result, _ = game.player_action(msg)
                result += player_result

                # プレイヤーのターン後、ディーラーターンならディーラー行動
                while not game.is_game_over() and game.turn == "dealer":
                    dealer_result, _ = game.dealer_action()
                    result += f"\n\n{dealer_result}"
                    # ディーラーが空砲で自分撃ちしたらターン継続なのでループする

            else:
                line_bot_api.reply_message(
                    event.reply_token,
                    TextSendMessage(text="1 か 2 を入力してください。")
                )
                return

        else:
            # プレイヤー以外のターン（基本はディーラー）
            dealer_result, _ = game.dealer_action()
            result += dealer_result

        winner = game.is_game_over()
        if winner:
            final_msg = "🎉 あなたの勝ち！" if winner == "player" else "😵 ディーラーの勝ち…"
            del active_games[user_id]
            reply = f"{result}\n\n{final_msg}"
        else:
            reply = f"{result}\n\n{game.get_status()}\n1: 自分を撃つ / 2: 相手を撃つ"

        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))
        return

    # --- 成績表示処理 ---
    if msg == "成績":
        # ゲーム中は強制終了してから成績表示
        if user_id in active_games:
            del active_games[user_id]
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="🎮ゲームを強制終了しました。成績を表示します。")
            )
            return

        def build_result_text(history, title):
            count = len(history)
            correct = sum(history)
            if count == 0:
                return f"【🤔Your Performance\n（{title}）】\nNo questions solved, but you expect a grade?"
            accuracy = correct / 100  # 常に100問換算
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

        h1 = user_histories.get(user_id + "_1_1000", [])
        h2 = user_histories.get(user_id + "_1000_1935", [])
        result_text = build_result_text(h1, "1-1000") + "\n\n" + build_result_text(h2, "1000-1935")
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=result_text))
        return

    # --- 英単語問題出題処理 ---
    if msg == "1-1000":
        if user_id in active_games:
            del active_games[user_id]
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="🎮ゲームを強制終了しました。問題を出題します。")
            )
            return

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
            return

        q = random.choice(questions_1000_1935)
        user_states[user_id] = ("1000-1935", q["answer"])
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=q["text"]))
        return

    # --- 英単語回答処理 ---
    if user_id in user_states:
        question_range, correct_answer = user_states[user_id]
        is_correct = (msg == correct_answer.lower())

        key = user_id + ("_1_1000" if question_range == "1-1000" else "_1000_1935")
        history = user_histories.get(key, [])
        history.append(1 if is_correct else 0)
        if len(history) > 100:
            history.pop(0)
        user_histories[key] = history

        feedback = (
            "Correct answer✅\n\nNext：" if is_correct else f"Incorrect❌ The correct answer is 「{correct_answer}」.\nNext："
        )

        # 次の問題（同じ範囲から）
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
