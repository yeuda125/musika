import os
import uuid
import requests
from pyrogram import Client
from pyrogram.types import InputFile
import subprocess
import time
import re

# משתנים
YMOT_TOKEN = os.getenv("YMOT_TOKEN")
YMOT_PATH = os.getenv("YMOT_PATH", "ivr2:/988")
API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")

# יצירת אובייקט של Pyrogram
app = Client("my_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

async def upload_large_to_ymot(file_path):
    """העלאת קובץ גדול לימות המשיח בחלקים"""
    url = "https://call2all.co.il/ym/api/UploadFile"
    file_size = os.path.getsize(file_path)
    chunk_size = 4 * 1024 * 1024  # גודל כל חלק (4MB)
    total_parts = (file_size + chunk_size - 1) // chunk_size
    qquuid = str(uuid.uuid4())
    filename = os.path.basename(file_path)

    # העלאה בחלקים
    with open(file_path, "rb") as f:
        for part_index in range(total_parts):
            chunk = f.read(chunk_size)
            offset = part_index * chunk_size
            files = {"qqfile": (filename, chunk, "application/octet-stream")}
            data = {
                "token": YMOT_TOKEN,
                "path": YMOT_PATH,
                "convertAudio": "1",
                "autoNumbering": "true",
                "qquuid": qquuid,
                "qqpartindex": part_index,
                "qqpartbyteoffset": offset,
                "qqchunksize": len(chunk),
                "qqtotalparts": total_parts,
                "qqtotalfilesize": file_size,
                "qqfilename": filename,
                "uploader": "yemot-admin"
            }
            resp = requests.post(url, data=data, files=files)
            print(f"📤 חלק {part_index+1}/{total_parts} הועלה:", resp.text)

    # סיום העלאה
    done_data = {
        "token": YMOT_TOKEN,
        "path": YMOT_PATH,
        "convertAudio": "1",
        "autoNumbering": "true",
        "qquuid": qquuid,
        "qqfilename": filename,
        "qqtotalfilesize": file_size,
        "qqtotalparts": total_parts,
    }
    done_resp = requests.post(url + "?done", data=done_data)
    print("✅ סיום העלאה:", done_resp.text)

async def upload_to_ymot(file_path):
    """העלאת קובץ רגיל או גדול לימות המשיח"""
    file_size = os.path.getsize(file_path)
    if file_size > 50 * 1024 * 1024:  # אם הקובץ גדול מ-50MB
        print("⚠️ קובץ גדול – משתמש בהעלאה בחלקים...")
        await upload_large_to_ymot(file_path)
        return

    url = 'https://call2all.co.il/ym/api/UploadFile'
    with open(file_path, 'rb') as f:
        files = {'file': (os.path.basename(file_path), f, 'audio/wav')}
        data = {
            'token': YMOT_TOKEN,
            'path': YMOT_PATH,
            'convertAudio': '1',  # המרת הקובץ ל־WAV
            'autoNumbering': 'true'
        }
        response = requests.post(url, data=data, files=files)
    print("📞 תגובת ימות:", response.text)

async def handle_message(update, context):
    message = update.message
    if not message:
        return

    text = message.text or message.caption
    has_video = message.video is not None
    has_audio = message.voice or message.audio

    if has_video:
        video_file = await message.video.get_file()
        url = video_file.file_path
        resp = requests.get(url, stream=True)
        with open("video.mp4", "wb") as f:
            for chunk in resp.iter_content(1024 * 1024):  # הורדה ב־1MB chunks
                f.write(chunk)

        convert_to_wav("video.mp4", "video.wav")
        await upload_to_ymot("video.wav")
        os.remove("video.mp4")
        os.remove("video.wav")

    if has_audio:
        audio_file = await (message.voice or message.audio).get_file()
        await audio_file.download_to_drive("audio.ogg")
        convert_to_wav("audio.ogg", "audio.wav")
        await upload_to_ymot("audio.wav")
        os.remove("audio.ogg")
        os.remove("audio.wav")

    if text:
        original_text = text
        cleaned_for_tts = re.sub(r'[^א-ת\s.,!?()\u0590-\u05FF]', '', original_text)
        cleaned_for_tts = re.sub(r'\s+', ' ', cleaned_for_tts).strip()

        full_text = create_full_text(cleaned_for_tts)
        text_to_mp3(full_text, "output.mp3")
        convert_to_wav("output.mp3", "output.wav")
        await upload_to_ymot("output.wav")
        os.remove("output.mp3")
        os.remove("output.wav")

# הפעלת הבוט
app.add_handler(MessageHandler(filters.ALL & (~filters.COMMAND), handle_message))

print("🚀 הבוט מאזין לערוץ ומעלה לשלוחה 🎧")
app.run()
