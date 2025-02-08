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
    username = data['message']['from']['username']
    
    # Check if message contains photo or video
    has_photo = 'photo' in data['message']
    has_video = 'video' in data['message']
    
    # Get text or caption
    text = data['message'].get('text', data['message'].get('caption', ''))

    is_command = (
        'message' in data
        and 'entities' in data['message']
        and len(data['message']['entities']) > 0
        and 'type' in data['message']['entities'][0]
        and data['message']['entities'][0]['type'] == 'bot_command'
    )

    try:
        user = supabase.table('users').select(
            '*').eq('username', username).single().execute().data
    except IndexError:
        user = None

    if not user:
        user = supabase.table('users').insert({
            'username': username,
            'first_name': data['message']['from']['first_name'],
            'last_name': data['message']['from']['last_name'],
        }).execute().data[0]

    if user["is_locking"]:
        await client.get(f"{BASE_URL}/sendMessage", params={
            "chat_id": chat_id,
            "text": "⏳ Please wait until I finish your previous request."
        })
        return

    supabase.table('users').update({
        'is_locking': True
    }).eq('username', username).execute()

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
        'from': data['message']['from'],
        'entities': data.get('message', {}).get('entities', []),
        'date': data['message']['date'],
        'message_id': data['message']['message_id'],
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
                            Please summarize the articles in a way that is easy to understand and provide a brief overview of the main points. Put the post link in the summary so I can click it to read the full article.
                        """
                    }
                ]
            )

            answer = completion.choices[0].message.content
    else:
        if has_photo:
            # Get the largest photo (last item in array)
            photo = data['message']['photo'][-1]
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
                            {"type": "text", "text": f"Here is the context that you have with me: {context}\n\nPlease analyze this image" + (f" with the following text: {text}" if text else "")},
                            {"type": "image_url", "image_url": photo_url}
                        ]
                    }
                ]
            )
            answer = completion.choices[0].message.content
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
                        "content": f"Here is the context that you have with me: {context}\n\nHere is the question that I'm asking: {text}"
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
        response = await client.get(f"{BASE_URL}/sendMessage", params={
            "chat_id": chat_id,
            "text": answer,
            "parse_mode": "Markdown"
        })

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

    supabase.table('users').update({
        'is_locking': False
    }).eq('username', username).execute()

    return data
