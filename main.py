from fastapi import FastAPI, Request
from pydantic import BaseModel
from openai import OpenAI
from dotenv import load_dotenv
import os
import httpx

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
    chat_id = data['message']['chat']['id']
    text = data['message']['text']

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

    completion = openai.chat.completions.create(
        model="meta-llama/llama-3.2-11b-vision-instruct:free",
        messages=[
            {
                "role": "user",
                "content": text
            }
        ]
    )

    print("Question: ", text)
    print("Answer: ", completion.choices[0])

    await client.get(f"{BASE_URL}/deleteMessage", params={
        "chat_id": chat_id,
        "message_id": temp_msg.json()['result']['message_id']
    })

    if completion.choices[0].message.content:
        await client.get(f"{BASE_URL}/sendMessage", params={
            "chat_id": chat_id,
            "text": completion.choices[0].message.content,
        })
    else:
        await client.get(f"{BASE_URL}/sendMessage", params={
            "chat_id": chat_id,
            "text": "🤦‍♂️ Sorry, I failed to get the answer."
        })

    processing_users.remove(chat_id)

    return data
