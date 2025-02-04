from fastapi import FastAPI
from pydantic import BaseModel
from openai import OpenAI
from dotenv import load_dotenv
import os

load_dotenv()

app = FastAPI()

openai = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.getenv("OPENROUTER_API_KEY"),
)


@app.get("/health")
def healthcheck():
    return {"status": "healthy"}


class MessageRequest(BaseModel):
    message: str


@app.post("/message")
def post_message(request: MessageRequest):
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
