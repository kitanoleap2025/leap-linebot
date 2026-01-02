import os
from flask import Flask, request

from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    ReplyMessageRequest,
    TextMessage
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent

app = Flask(__name__)

# import 時に外部サービスへ触らない
handler = None
configuration = None


def init_line():
    """
    Cloud Run / Gunicorn 対応
    worker 起動後に必要になったタイミングで初期化する
    """
    global handler, configuration

    if handler is not None and configuration is not None:
        return

    channel_secret = os.environ.get("LINE_CHANNEL_SECRET")
    channel_access_token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")

    if not channel_secret or not channel_access_token:
        raise RuntimeError("LINE環境変数が設定されていません")

    handler = WebhookHandler(channel_secret)
    configuration = Configuration(access_token=channel_access_token)


@app.route("/callback", methods=["POST"])
def callback():
    init_line()

    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        # LINEは200以外を返すと面倒
        return "OK", 200

    return "OK", 200


@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    # handler は callback で初期化済み
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=event.message.text)]
            )
        )


@app.route("/", methods=["GET"])
def health():
    # Cloud Run のヘルスチェック用
    return "OK", 200
