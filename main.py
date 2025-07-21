from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

import os
import random

app = Flask(__name__)

# 環境変数などで設定しておく
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# ユーザーごとのセッション管理（簡易版、実運用はDB推奨）
user_sessions = {}

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
        "first_round": True
    }

def game_status_message(state):
    return (f"{state['turn'] + 1}発目\n"
            f"PLAYERのHP: {state['player_hp']}, DEALERのHP: {state['bot_hp']}\n"
            f"6発中...実弾{state['bullet_count']}発.\n"
            f"📱古い携帯から声が聞こえる...{state['known_safe'] + 1}発目...空砲.\n")

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

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']

    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)

    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_id = event.source.user_id
    text = event.message.text.strip()

    # ユーザーセッション取得または初期化
    state = user_sessions.get(user_id)
    if state is None:
        state = new_game_state()
        user_sessions[user_id] = state
        reply = ("=== Russian Roulette ===\n"
                 "6発装填のショットガンを交互に撃ち合う.ライフは1人2つ.\n\n"
                 f"6発中...実弾{state['bullet_count']}発.\n"
                 f"📱古い携帯から声が聞こえる...\n{state['known_safe'] + 1}発目...空砲.\n\n"
                 f"{state['turn'] + 1}発目\n"
                 f"PLAYER        DEALER\n{'⚡' * state['player_hp']}          {'⚡' * state['bot_hp']}\n"
                 "自分に撃つ(1) / 相手に撃つ(2)")
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))
        return

    # プレイヤーの入力処理
    if text not in ['1', '2']:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="1か2"))
        return

    turn = state['turn']
    chambers = state['chambers']
    player_hp = state['player_hp']
    bot_hp = state['bot_hp']
    player_turn = state['player_turn']

    messages = []

    if not player_turn:
        messages.append("今はあなたのターンではありません。")
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="\n".join(messages)))
        return

    # プレイヤーのターン処理
    if text == '1':
        messages.append( f"{state['turn'] + 1}発目\n")
        messages.append("こめかみに銃口を当てた。")
        if chambers[turn] == 1:
            state['player_hp'] -= 1
            messages.append(f"💥 実弾だ!アドレナリンが全身を駆け巡る.\nPLAYER: {'⚡' * state['player_hp']}　DEALER: {'⚡' * state['bot_hp']}\n")
            if state['player_hp'] == 0:
                messages.append("HPが0になった。")
                user_sessions.pop(user_id)  # セッション削除
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text="\n".join(messages)))
                return
            state['player_turn'] = False
        else:
            messages.append("カチッ。空砲だ。あなたのターン続行！")
            # player_turnは変えず
        state['turn'] += 1

    else:  # text == '2'
        messages.append( f"{state['turn'] + 1}発目\n")
        messages.append("相手に撃った。")
        if chambers[turn] == 1:
            state['bot_hp'] -= 1
            messages.append(f"💥 DEALERを撃ち抜いた! \nPLAYER: {'⚡' * state['player_hp']}　DEALER: {'⚡' * state['bot_hp']}\n")
            if state['bot_hp'] == 0:
                messages.append("DEALERに勝った")
                user_sessions.pop(user_id)
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text="\n".join(messages)))
                return
        else:
            messages.append("カチッ。空砲だ。")
        state['player_turn'] = False
        state['turn'] += 1

    # ボットのターン処理
    if not state['player_turn'] and state['turn'] < 6:
        messages.append( f"{state['turn'] + 1}発目\n")
        messages.append("\n\nDEALERのターン")
        bot_act = bot_action(state)
        if bot_act == '1':
            messages.append("DEALERはこめかみに銃口を当てた。")
            if chambers[state['turn']] == 1:
                state['bot_hp'] -= 1
                messages.append(f"💥 DEALERが被弾！\nPLAYER: {'⚡' * state['player_hp']}　DEALER: {'⚡' * state['bot_hp']}\n")
                if state['bot_hp'] == 0:
                    messages.append("DEALERに勝った")
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
                messages.append(f"💥 あなたが被弾！⚡️ アドレナリンが全身を駆け巡る。\nPLAYER: {'⚡' * state['player_hp']}　DEALER: {'⚡' * state['bot_hp']}\n")
                if state['player_hp'] == 0:
                    messages.append("HPが0になった。起きろ。夜はまだ浅い。")
                    user_sessions.pop(user_id)
                    line_bot_api.reply_message(event.reply_token, TextSendMessage(text="\n".join(messages)))
                    return
            else:
                messages.append("カチッ。空砲だ。")
            state['player_turn'] = True
            state['turn'] += 1

    # 6発終了したらリロード（弾倉再生成）
    if state['turn'] >= 6:
        messages.append("\n💥 リロードします...\n")
        chambers, bullet_count, known_safe = setup_chambers()
        state['chambers'] = chambers
        state['bullet_count'] = bullet_count
        state['known_safe'] = known_safe
        state['turn'] = 0
        state['player_turn'] = True

    user_sessions[user_id] = state

    line_bot_api.reply_message(event.reply_token, TextSendMessage(text="\n".join(messages)))

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
