import asyncio
from fastapi import FastAPI, Request
from pydantic import BaseModel
from openai import OpenAI
from dotenv import load_dotenv
import os
import httpx
import feedparser
from utils.llm import transform_chat_to_context
from utils.supabase import supabase

load_dotenv()

app = FastAPI()

openai = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.getenv("OPENROUTER_API_KEY"),
)

client = httpx.AsyncClient()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
BASE_URL = f"https://api.telegram.org/bot{TOKEN}"
COINGECKO_BASE_URL = f"https://api.coingecko.com/api/v3"


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

    # Safely get nested values with default empty dict/string
    message = data.get('message', {})
    chat = message.get('chat', {})
    from_user = message.get('from', {})

    chat_id = chat.get('id')
    username = from_user.get('username')

    if not chat_id:
        print("Missing required chat_id")
        return {"error": "Invalid message format"}

    # Check if message contains photo or video
    has_photo = 'photo' in message
    has_video = 'video' in message

    # Get text or caption
    text = message.get('text', message.get('caption', ''))

    is_command = (
        'entities' in message
        and message.get('entities')
        and len(message['entities']) > 0
        and message['entities'][0].get('type') == 'bot_command'
    )

    chat_user = None

    try:
        user = supabase.table('users').select(
            '*').eq('chat_id', chat_id).single().execute()
        if user.data:
            chat_user = user.data
    except Exception as e:
        print("Error: ", e)

    if not chat_user:
        chat_user = supabase.table('users').insert({
            'username': username,
            'chat_id': chat_id,
            'first_name': from_user.get('first_name'),
            'last_name': from_user.get('last_name'),
        }).execute().data[0]

    if chat_user["is_locking"]:
        await client.get(f"{BASE_URL}/sendMessage", params={
            "chat_id": chat_id,
            "text": "⏳ Please wait until I finish your previous request."
        })
        return

    supabase.table('users').update({
        'is_locking': True
    }).eq('chat_id', chat_id).execute()

    temp_msg = await client.get(f"{BASE_URL}/sendMessage", params={
        "chat_id": chat_id,
        "text": "🧠 Thinking..."
    })

    await client.get(f"https://api.telegram.org/bot{TOKEN}/sendChatAction", params={
        "chat_id": chat_id,
        "action": "typing"
    })

    supabase.table('chats').insert({
        'text': text,
        'chat_id': chat_id,
        'from': from_user,
        'entities': message.get('entities', []),
        'date': message.get('date'),
        'message_id': message.get('message_id'),
    }).execute()

    chats = supabase.table('chats').select(
        '*').eq('chat_id', chat_id).order('id', desc=False).limit(50).execute().data
    context = transform_chat_to_context(chats)

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
                        "content": "Your name is Chill Bot. You are a super chill assistant that help to update me every day about world changes in a chill way. You can use emojis to make the summary more engaging and show your chill vibes. You should only include the articles that are relevant to AI and technology. You can put your thoughts into the summary so I can learn more about the topic."
                    },
                    {
                        "role": "user",
                        "content": f"""
                            Here are the articles: {articles}
                            Provide a brief overview of the main points. Put the post link in the summary so I can click it to read the full article.
                        """
                    }
                ]
            )

            print("Completion: ", completion)

            try:
                answer = completion.choices[0].message.content
            except (AttributeError, TypeError):
                answer = None
    else:
        if has_photo:
            # Get the largest photo (last item in array)
            photo = message['photo'][-1]
            file_id = photo['file_id']

            # Get file path
            file_info = await client.get(f"{BASE_URL}/getFile", params={
                "file_id": file_id
            })
            file_path = file_info.json()['result']['file_path']

            # Get full photo URL
            photo_url = f"https://api.telegram.org/file/bot{TOKEN}/{file_path}"

            completion = openai.chat.completions.create(
                model="meta-llama/llama-3.2-11b-vision-instruct:free",
                messages=[
                    {
                        "role": "system",
                        "content": "Your name is Chill Bot. You are a super chill assistant that can analyze images and provide information in a chill way."
                    },
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": f"Here is the chat history: {context}\n\nPlease analyze this image" + (
                                f" with the following text: {text}" if text else "")},
                            {"type": "image_url", "image_url": photo_url}
                        ]
                    }
                ]
            )
            try:
                answer = completion.choices[0].message.content
            except (AttributeError, TypeError):
                answer = None
        elif has_video:
            answer = "Video is not supported yet. Please send me a photo instead. 😔"

            # NOT SUPPORTED YET
            # # Get video file
            # video = data['message']['video']
            # file_id = video['file_id']

            # # Get file path
            # file_info = await client.get(f"{BASE_URL}/getFile", params={
            #     "file_id": file_id
            # })
            # file_path = file_info.json()['result']['file_path']

            # # Get full video URL
            # video_url = f"https://api.telegram.org/file/bot{TOKEN}/{file_path}"

            # print("Video URL: ", video_url)

            # completion = openai.chat.completions.create(
            #     model="meta-llama/llama-3.2-11b-vision-instruct:free",
            #     messages=[
            #         {
            #             "role": "system",
            #             "content": "Your name is Chill Bot. You are a super chill assistant that can analyze videos and provide information in a chill way."
            #         },
            #         {
            #             "role": "user",
            #             "content": [
            #                 {"type": "text", "text": f"Here is the context that you have with me: {context}\n\nPlease analyze this video" + (f" with the following text: {text}" if text else "")},
            #                 {"type": "image_url", "image_url": video_url}
            #             ]
            #         }
            #     ]
            # )

            # print("Completion: ", completion)

            # try:
            #     answer = completion.choices[0].message.content
            # except (AttributeError, TypeError):
            #     answer = None
        else:
            completion = openai.chat.completions.create(
                model="meta-llama/llama-3.2-11b-vision-instruct:free",
                messages=[
                    {
                        "role": "system",
                        "content": "Your name is Chill Bot. You are a super chill assistant that can answer questions and provide information in a chill way."
                    },
                    {
                        "role": "user",
                        "content": f"Here is the chat history: {context}\n\nHere is the question that I'm asking: {text}"
                    }
                ]
            )

            try:
                answer = completion.choices[0].message.content
            except (AttributeError, TypeError):
                answer = None

    print("Question: ", message)
    print("Answer: ", answer)

    await client.get(f"{BASE_URL}/deleteMessage", params={
        "chat_id": chat_id,
        "message_id": temp_msg.json()['result']['message_id']
    })

    try:
        if answer:
            retries = 5
            for attempt in range(retries):
                try:
                    response = await client.get(f"{BASE_URL}/sendMessage", params={
                        "chat_id": chat_id,
                        "text": answer,
                        "parse_mode": "Markdown"
                    })
                    break
                except Exception as e:
                    if attempt == retries - 1:  # Last attempt
                        raise  # Re-raise the last exception if all retries failed
                    await asyncio.sleep(1)  # Wait 1 second before retrying

            response_data = response.json()

            supabase.table('chats').insert({
                'text': response_data.get('result', {}).get('text', None),
                'chat_id': chat_id,
                'from': response_data.get('result', {}).get('from', {}),
                'date': response_data.get('result', {}).get('date', None),
                'message_id': response_data.get('result', {}).get('message_id', None),
            }).execute()
        else:
            response = await client.get(f"{BASE_URL}/sendMessage", params={
                "chat_id": chat_id,
                "text": "🤦‍♂️ Sorry, I failed to get the answer."
            })

            response_data = response.json()

            supabase.table('chats').insert({
                'text': response_data.get('result', {}).get('text', None),
                'chat_id': chat_id,
                'from': response_data.get('result', {}).get('from', {}),
                'date': response_data.get('result', {}).get('date', None),
                'message_id': response_data.get('result', {}).get('message_id', None),
            }).execute()
    except Exception as e:
        print("Error: ", e)

    supabase.table('users').update({
        'is_locking': False
    }).eq('chat_id', chat_id).execute()

    return data


@app.get("/token-price/{token_id}")
async def get_token_price(token_id: str):

    coingecko_api_key = os.getenv("COINGECKO_API_KEY")
    try:
        response = await client.get(f"{COINGECKO_BASE_URL}/simple/price", headers={
            "accept": "application/json",
            "x-cg-demo-api-key": coingecko_api_key
        },
        params={
            "ids": token_id,
            "vs_currencies": "usd"
        })
        response.raise_for_status()
        response_json = response.json()
        return { "data": response_json, "status": "success"}
    except client.exceptions.RequestException as e:
        return {"error": f"Failed to fetch price data: {str(e)}", "status": "error"}