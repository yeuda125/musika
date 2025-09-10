import os
import json
import subprocess
import requests
import base64
import uuid
from datetime import datetime
import pytz
import asyncio
import re
import time

from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes
from google.cloud import texttospeech

# 🟡 כתיבת קובץ מפתח Google מ־BASE64
key_b64 = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS_B64")
if not key_b64:
    raise Exception("❌ משתנה GOOGLE_APPLICATION_CREDENTIALS_B64 לא מוגדר או ריק")

try:
    with open("google_key.json", "wb") as f:
        f.write(base64.b64decode(key_b64))
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "google_key.json"
except Exception as e:
    raise Exception("❌ נכשל בכתיבת קובץ JSON מ־BASE64: " + str(e))

# 🛠 משתנים מ־Render
BOT_TOKEN = os.getenv("BOT_TOKEN")
YMOT_TOKEN = os.getenv("YMOT_TOKEN")
YMOT_PATH = os.getenv("YMOT_PATH", "ivr2:/988")

# 🔢 המרת מספרים לעברית
def num_to_hebrew_words(hour, minute):
    # ... (הקוד נשאר כפי שהיה)

def clean_text(text):
    BLOCKED_PHRASES = sorted([  # ... (הקוד נשאר כפי שהיה)
    ], key=len, reverse=True)
    # ... (הקוד נשאר כפי שהיה)

def create_full_text(text):
    return text

def text_to_mp3(text, filename='output.mp3'):
    client = texttospeech.TextToSpeechClient()
    synthesis_input = texttospeech.SynthesisInput(text=text)
    voice = texttospeech.VoiceSelectionParams(
        language_code="he-IL",
        name="he-IL-Wavenet-B",
        ssml_gender=texttospeech.SsmlVoiceGender.MALE
    )
    audio_config = texttospeech.AudioConfig(
        audio_encoding=texttospeech.AudioEncoding.MP3,
        speaking_rate=1.2
    )
    response = client.synthesize_speech(
        input=synthesis_input,
        voice=voice,
        audio_config=audio_config
    )
    with open(filename, "wb") as out:
        out.write(response.audio_content)

def convert_to_wav(input_file, output_file='output.wav'):
    subprocess.run([
        'ffmpeg', '-i', input_file, '-ar', '8000', '-ac', '1', '-f', 'wav',
        output_file, '-y'
    ])

def upload_large_to_ymot(file_path):
    """העלאת קובץ גדול (מעל 20MB) לימות המשיח בחלקים"""
    url = "https://call2all.co.il/ym/api/UploadFile"
    file_size = os.path.getsize(file_path)
    chunk_size = 4 * 1024 * 1024  # 4MB
    total_parts = (file_size + chunk_size - 1) // chunk_size
    qquuid = str(uuid.uuid4())  # יצירת UUID ייחודי
    filename = os.path.basename(file_path)

    with open(file_path, "rb") as f:
        for part_index in range(total_parts):
            chunk = f.read(chunk_size)
            offset = part_index * chunk_size
            files = {"qqfile": (filename, chunk, "application/octet-stream")}
            data = {
                "token": YMOT_TOKEN,
                "path": YMOT_PATH,
                "convertAudio": "1",  # המרת הקובץ ל־WAV
                "autoNumbering": "true",  # מספור אוטומטי
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
        "path": YMOT_PATH,  # אותו נתיב כמו בהתחלה
        "convertAudio": "1",  # המרת הקובץ ל־WAV
        "autoNumbering": "true",
        "qquuid": qquuid,
        "qqfilename": filename,
        "qqtotalfilesize": file_size,
        "qqtotalparts": total_parts,
    }
    done_resp = requests.post(url + "?done", data=done_data)
    print("✅ סיום העלאה:", done_resp.text)

def upload_to_ymot(wav_file_path):
    """העלאת קובץ רגיל או גדול לימות המשיח"""
    file_size = os.path.getsize(wav_file_path)
    if file_size > 20 * 1024 * 1024:  # קובץ מעל 20MB
        print("⚠️ קובץ גדול – משתמש בהעלאה בחלקים...")
        return upload_large_to_ymot(wav_file_path)

    url = 'https://call2all.co.il/ym/api/UploadFile'
    with open(wav_file_path, 'rb') as f:
        files = {'file': (os.path.basename(wav_file_path), f, 'audio/wav')}
        data = {
            'token': YMOT_TOKEN,
            'path': YMOT_PATH,
            'convertAudio': '1',  # המרת הקובץ ל־WAV
            'autoNumbering': 'true'
        }
        response = requests.post(url, data=data, files=files)
    print("📞 תגובת ימות:", response.text)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
            for chunk in resp.iter_content(1024*1024):  # הורדה ב־1MB chunks
                f.write(chunk)

        convert_to_wav("video.mp4", "video.wav")
        upload_to_ymot("video.wav")
        os.remove("video.mp4")
        os.remove("video.wav")

    if has_audio:
        audio_file = await (message.voice or message.audio).get_file()
        await audio_file.download_to_drive("audio.ogg")
        convert_to_wav("audio.ogg", "audio.wav")
        upload_to_ymot("audio.wav")
        os.remove("audio.ogg")
        os.remove("audio.wav")

    if text:
        original_text = text
        cleaned_for_tts = re.sub(r'[^א-ת\s.,!?()\u0590-\u05FF]', '', original_text)
        cleaned_for_tts = re.sub(r'\s+', ' ', cleaned_for_tts).strip()

        full_text = create_full_text(cleaned_for_tts)
        text_to_mp3(full_text, "output.mp3")
        convert_to_wav("output.mp3", "output.wav")
        upload_to_ymot("output.wav")
        os.remove("output.mp3")
        os.remove("output.wav")

from keep_alive import keep_alive
keep_alive()

app = ApplicationBuilder().token(BOT_TOKEN).build()
app.add_handler(MessageHandler(filters.ALL & (~filters.COMMAND), handle_message))

print("🚀 הבוט מאזין לערוץ ומעלה לשלוחה 🎧")

while True:
    try:
        app.run_polling(
            poll_interval=2.0,
            timeout=30,
            allowed_updates=Update.ALL_TYPES
        )
    except Exception as e:
        print("❌ שגיאה כללית בהרצת הבוט:", e)
        time.sleep(5)
