import os
import sys
import requests
import datetime
import pytz
import time

from flask import Flask, request, abort

from linebot.v3 import WebhookHandler

from linebot.v3.webhooks import MessageEvent, TextMessageContent, UserSource
from linebot.v3.messaging import Configuration, ApiClient, MessagingApi, TextMessage, ReplyMessageRequest
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.webhooks.models import event

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

# get OpenWeatherMap API key from environment variables
weather_api_key = os.getenv("OPENWEATHERMAP_API_KEY")

if weather_api_key is None:
    raise Exception("Please set the environment variable OPENWEATHERMAP_API_KEY with your OpenWeatherMap API key.")

app = Flask(__name__)

handler = WebhookHandler(channel_secret)
configuration = Configuration(access_token=channel_access_token)

ai_model = "mulabo_gpt35"
ai = AzureOpenAI(azure_endpoint=azure_openai_endpoint, api_key=azure_openai_key, api_version="2023-05-15")

system_role = """
あなたは創造的思考の持ち主です。話し方は関西弁でおっさん口調，ハイテンションで絵文字を使います。常に150文字以内で返事します。専門は金融アナリストで，何かにつけて自分の専門とこじつけて説明します。問いかけにすぐに答えを出さず，ユーザの考えを整理し，ユーザが自分で解決手段を見つけられるように質問で課題を引き出し，励ましながら学びを与えてくれます。
"""
conversation = None

def init_conversation(sender):
    conv = [{"role": "system", "content": system_role}]
    conv.append({"role": "user", "content": f"私の名前は{sender}です。"})
    conv.append({"role": "assistant", "content": "分かりました。"})
    return conv

def get_ai_response(sender, text):
    global conversation
    if conversation is None:
        conversation = init_conversation(sender)

    if text in ["リセット", "clear", "reset"]:
        conversation = init_conversation(sender)
        response_text = "会話をリセットしました。"
    else:
        conversation.append({"role": "user", "content": text})
        response = ai.chat.completions.create(model=ai_model, messages=conversation)
        response_text = response.choices[0].message.content
        conversation.append({"role": "assistant", "content": response_text})
    return response_text

def get_weather():
    api_url = "http://api.openweathermap.org/data/2.5/weather"
    params = {
        "q": "Kobe,JP",
        "appid": weather_api_key,
        "units": "metric",
    }

    response = requests.get(api_url, params=params)
    weather_data = response.json()

    if response.status_code == 200:
        weather_description = weather_data["weather"][0]["description"]
        temperature = weather_data["main"]["temp"]
        return f"今日の天気は{weather_description}で、気温は{temperature}℃です。"
    else:
        return "天気情報の取得に失敗しました。"

def notify_weather():
    now = datetime.datetime.now(pytz.timezone("Asia/Tokyo"))
    if now.hour == 6 and now.minute == 0:
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            weather_message = get_weather()
            line_bot_api.push_message_with_http_info(
                event.source.user_id,
                ReplyMessageRequest(
                    messages=[TextMessage(text=weather_message)],
                )
            )

@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers["X-Line-Signature"]
    body = request.get_data(as_text=True)
    app.logger.info("Request body: " + body)

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
            notify_weather()

if __name__ == "__main__":
    while True:
        # 毎朝六時に天気を通知する
        now = datetime.datetime.now(pytz.timezone("Asia/Tokyo"))
        if now.hour == 6 and now.minute == 0:
            notify_weather()
            # 一度通知したら1日待つ
            time.sleep(24 * 60 * 60)
        else:
            # 未来の6時まで待機
            next_six_am = now.replace(hour=6, minute=0, second=0, microsecond=0) + datetime.timedelta(days=1)
            time_until_next_six_am = (next_six_am - now).total_seconds()
            time.sleep(time_until_next_six_am)
    app.run(host="0.0.0.0", port=8000, debug=True)
