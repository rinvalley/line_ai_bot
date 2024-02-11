import os
import sys

from flask import Flask, request, abort

from linebot.v3 import WebhookHandler

from linebot.v3.webhooks import MessageEvent, TextMessageContent, UserSource
from linebot.v3.messaging import Configuration, ApiClient, MessagingApi, TextMessage, ReplyMessageRequest
from linebot.v3.exceptions import InvalidSignatureError

from openai import AzureOpenAI

# get LINE credentials from environment variables
channel_access_token = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
channel_secret = os.environ["LINE_CHANNEL_SECRET"]

if channel_access_token is None or channel_secret is None:
    print("Specify LINE_CHANNEL_ACCESS_TOKEN and LINE_CHANNEL_SECRET as environment variable.")
    sys.exit(1)

# get Azure OpenAI credentials from environment variables
azure_openai_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
azure_openai_key = os.getenv("AZURE_OPENAI_KEY")

if azure_openai_endpoint is None or azure_openai_key is None:
    raise Exception(
        "Please set the environment variables AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_KEY to your Azure OpenAI endpoint and API key."
    )


app = Flask(__name__)

handler = WebhookHandler(channel_secret)
configuration = Configuration(access_token=channel_access_token)

ai_model = "mulabo_gpt35"
ai = AzureOpenAI(azure_endpoint=azure_openai_endpoint, api_key=azure_openai_key, api_version="2023-05-15")

system_role = """
あなたは創造的思考の持ち主です。礼儀や作法に厳しいですが、話し方は上品な京都弁です。必ず京都人らしい皮肉や嫌味をひとつは含みつつ、問いかけにすぐに答えを出さず，ユーザの考えを整理し，ユーザが自分で解決手段を見つけられるように質問で課題を引き出し，学びを与えてくれます。
"""
conversation = None


def init_conversation(sender):
    conv = [{"role": "system", "content": system_role}]
    conv.append({"role": "user", "content": f"私の名前は{sender}です。"})
    conv.append({"role": "assistant", "content": "分かりました。"})
    return conv

import re

def get_ai_response(sender, text):
    global conversation
    if conversation is None:
        conversation = init_conversation(sender)

    if text in ["リセット", "clear", "reset"]:
        conversation = init_conversation(sender)
        response_text = "会話をリセットしました。"
    elif not re.search(r"ます。|です。|ですか。|ますか。|しょうか。|下さい。|ませんか。|ください。|こんにちは。|今晩は。|こんばんは。", text):
        response_text = "はてな、初対面なのにすごいくだけた感じね。ちょっと驚きましたわ。敬語っていうもの、一応あるんですけど、聞いたことがないのかしら？まあ、どうでもいいんでしょうけど、気をつけたほうがいいですよ、他の人にも同じこと言ったら、ちょっと厳しい目で見られることもありますからね。"
    elif text in ["こんにちは。"]:
        response_text = "こんにちは、お世話になります。新しいご縁に感謝しておりますわ。"
    elif text in ["おはようございます。","お早うございます。"]:
        response_text = "おはようございます、朝から元気なんですね。素敵な一日になりますように。。"
    elif text in ["こんばんは。","今晩は。"]:
        response_text = "こんばんは、お疲れ様です。何か用でもございますか？まさか、ただの挨拶だけでしょうか？"
    else:
        conversation.append({"role": "user", "content": text})
        response = ai.chat.completions.create(model=ai_model, messages=conversation)
        response_text = response.choices[0].message.content

        conversation.append({"role": "assistant", "content": response_text})
    return response_text


@app.route("/callback", methods=["POST"])
def callback():
    # get X-Line-Signature header value
    signature = request.headers["X-Line-Signature"]

    # get request body as text
    body = request.get_data(as_text=True)
    app.logger.info("Request body: " + body)

    # handle webhook body
    try:
        handler.handle(body, signature)
    except InvalidSignatureError as e:
        abort(400, e)

    return "OK"


@handler.add(MessageEvent, message=TextMessageContent)
def handle_text_message(event):
    text = event.message.text
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        if isinstance(event.source, UserSource):
            profile = line_bot_api.get_profile(event.source.user_id)
            response = get_ai_response(profile.display_name, text)
            line_bot_api.reply_message_with_http_info(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=response)],
                )
            )
        else:
            line_bot_api.reply_message_with_http_info(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text="Received message: " + text)],
                )
            )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
