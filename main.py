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

    completion = openai.chat.completions.create(
        model="deepseek/deepseek-r1-distill-llama-70b:free",
        messages=[
            {
                "role": "user",
                "content": text
            }
        ]
    )

    print("Question: ", text)
    print("Answer: ", completion.choices[0])

    await client.get(f"{BASE_URL}/sendMessage?chat_id={chat_id}&text={completion.choices[0].message.content}")

    return data
