from fastapi import FastAPI, Request
from pydantic import BaseModel
from openai import OpenAI
from dotenv import load_dotenv
import os
import httpx
import feedparser

load_dotenv()

app = FastAPI()

openai = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.getenv("OPENROUTER_API_KEY"),
)

client = httpx.AsyncClient()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
BASE_URL = f"https://api.telegram.org/bot{TOKEN}"

processing_users = set()  # Store users currently being processed


@app.get("/health")
def healthcheck():
    return {"status": "healthy"}


class MessageRequest(BaseModel):
    message: str


@app.post("/message")
async def post_message(request: MessageRequest):
    completion = openai.chat.completions.create(
        model="deepseek/deepseek-r1-distill-llama-70b:free",
        messages=[
            {
                "role": "user",
                "content": request.message
            }
        ]
    )

    return completion.choices[0].message


@app.post("/webhook/")
async def webhook(req: Request):
    data = await req.json()
    print("Event: ", data)

    chat_id = data['message']['chat']['id']
    text = data['message']['text']

    is_command = (
        'message' in data
        and 'entities' in data['message']
        and len(data['message']['entities']) > 0
        and 'type' in data['message']['entities'][0]
        and data['message']['entities'][0]['type'] == 'bot_command'
    )

    if chat_id in processing_users:
        await client.get(f"{BASE_URL}/sendMessage", params={
            "chat_id": chat_id,
            "text": "⏳ Please wait until I finish your previous request."
        })
        return

    processing_users.add(chat_id)

    temp_msg = await client.get(f"{BASE_URL}/sendMessage", params={
        "chat_id": chat_id,
        "text": "🧠 Thinking..."
    })

    answer = None

    if is_command:
        if text.startswith('/verge'):
            rss_url = "https://www.theverge.com/rss/index.xml"
            feed = feedparser.parse(rss_url)

            articles = []
            for entry in feed.entries:
                articles.append({
                    "author": entry.author,
                    "title": entry.title,
                    "link": entry.link,
                    "summary": entry.summary,
                    "content": entry.content[0].value,
                    "published": entry.published,
                })

            completion = openai.chat.completions.create(
                model="meta-llama/llama-3.2-11b-vision-instruct:free",
                messages=[
                    {
                        "role": "system",
                        "content": "You are a super chill assistant that can answer questions and provide information in a chill way. You can use emojis to make the summary more engaging and show your chill vibes. You should only include the articles that are relevant to AI and technology. You can put your thoughts into the summary so I can learn more about the topic."
                    },
                    {
                        "role": "user",
                        "content": f"""
                            Here are the articles: {articles}
                            Please summarize the articles in a way that is easy to understand and provide a brief overview of the main points. Put the post link in the summary so I can click it to read the full article.
                        """
                    }
                ]
            )

            answer = completion.choices[0].message.content
    else:
        completion = openai.chat.completions.create(
            model="meta-llama/llama-3.2-11b-vision-instruct:free",
            messages=[
                {
                    "role": "system",
                    "content": "You are a super chill assistant that can answer questions and provide information in a chill way."
                },
                {
                    "role": "user",
                    "content": text
                }
            ]
        )

        answer = completion.choices[0].message.content

    print("Question: ", data['message']['chat'])
    print("Answer: ", answer)

    await client.get(f"{BASE_URL}/deleteMessage", params={
        "chat_id": chat_id,
        "message_id": temp_msg.json()['result']['message_id']
    })

    if answer:
        await client.get(f"{BASE_URL}/sendMessage", params={
            "chat_id": chat_id,
            "text": answer,
            "parse_mode": "Markdown"
        })
    else:
        await client.get(f"{BASE_URL}/sendMessage", params={
            "chat_id": chat_id,
            "text": "🤦‍♂️ Sorry, I failed to get the answer."
        })

    processing_users.remove(chat_id)

    return data
