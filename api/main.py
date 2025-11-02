import os
from linebot import LineBotApi, WebhookHandler
from linebot.models import MessageEvent, TextMessage, TextSendMessage
from linebot.exceptions import InvalidSignatureError

# LINE SDK 初期化
line_bot_api = LineBotApi(os.environ["LINE_CHANNEL_ACCESS_TOKEN_LEAP"])
handler = WebhookHandler(os.environ["LINE_CHANNEL_SECRET_LEAP"])

# LINEイベント処理
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    # 受け取ったテキストをそのまま返すだけ
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=f"あなたは「{event.message.text}」と言いました")
    )

# Vercelサーバーレス用エントリーポイント
def handler_main(request):
    if request.method != "POST":
        return "Method Not Allowed", 405

    body = request.get_data(as_text=True)
    signature = request.headers.get("X-Line-Signature", "")
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        return "Invalid signature", 400

    return "OK", 200
