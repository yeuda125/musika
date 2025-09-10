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
    hours_map = {
        1: "אחת", 2: "שתיים", 3: "שלוש", 4: "ארבע", 5: "חמש",
        6: "שש", 7: "שבע", 8: "שמונה", 9: "תשע", 10: "עשר",
        11: "אחת עשרה", 12: "שתים עשרה"
    }
    minutes_map = {
        0: "", 1: "ודקה", 2: "ושתי דקות", 3: "ושלוש דקות", 4: "וארבע דקות", 5: "וחמש דקות",
        6: "ושש דקות", 7: "ושבע דקות", 8: "ושמונה דקות", 9: "ותשע דקות", 10: "ועשרה",
        11: "ואחת עשרה דקות", 12: "ושתים עשרה דקות", 13: "ושלוש עשרה דקות", 14: "וארבע עשרה דקות",
        15: "ורבע", 16: "ושש עשרה דקות", 17: "ושבע עשרה דקות", 18: "ושמונה עשרה דקות",
        19: "ותשע עשרה דקות", 20: "ועשרים", 21: "עשרים ואחת", 22: "עשרים ושתיים",
        23: "עשרים ושלוש", 24: "עשרים וארבע", 25: "עשרים וחמש",
        26: "עשרים ושש", 27: "עשרים ושבע", 28: "עשרים ושמונה",
        29: "עשרים ותשע", 30: "וחצי",
        31: "שלושים ואחת", 32: "שלושים ושתיים", 33: "שלושים ושלוש",
        34: "שלושים וארבע", 35: "שלושים וחמש", 36: "שלושים ושש",
        37: "שלושים ושבע", 38: "שלושים ושמונה", 39: "שלושים ותשע",
        40: "וארבעים דקות", 41: "ארבעים ואחת", 42: "ארבעים ושתיים",
        43: "ארבעים ושלוש", 44: "ארבעים וארבע", 45: "ארבעים וחמש",
        46: "ארבעים ושש", 47: "ארבעים ושבע", 48: "ארבעים ושמונה",
        49: "ארבעים ותשע", 50: "וחמישים דקות", 51: "חמישים ואחת",
        52: "חמישים ושתיים", 53: "חמישים ושלוש", 54: "חמישים וארבע",
        55: "חמישים וחמש", 56: "חמישים ושש", 57: "חמישים ושבע",
        58: "חמישים ושמונה", 59: "חמישים ותשע"
    }
    hour_12 = hour % 12 or 12
    return f"{hours_map[hour_12]} {minutes_map[minute]}"

def clean_text(text):
    BLOCKED_PHRASES = sorted([
        "חדשות המוקד • בטלגרם: t.me/hamoked_il",
        "בוואטסאפ: https://chat.whatsapp.com/LoxVwdYOKOAH2y2kaO8GQ7",
        "לעדכוני הפרגוד בטלגרם",
        "כל העדכונים בקבוצה",
        "https://chat.whatsapp.com/HRLme3RLzJX0WlaT1Fx9ol",
        "לשליחת חומר",
        "בוואצפ: 0526356326",
        "במייל",
        "r0527120704@gmail.com",
        "t.me/hamoked_il",
        "מיוזיק >>>> מה שמעניין",
        "מיוזיק",
        "שמרו לעצמכם",
        "לצפייה ביוטיוב",
        "לצפיה",
        "ביוטיוב",
        "t.me/music_ms2",
        "https://chat.whatsapp.com/CD7EpONUdKm7z7rAhfa6ZV",
        "http://t.me/music_ms2",
        "בטלגרם",
        "חדשות המוקד",
        "שש",
        "לכל העדכונים, ולכתבות נוספות הצטרפו לערוץ דרך הקישור",
        "לכל העדכונים",
        "להצטרפות מלאה לקבוצה לחצו על הצטרף",
    ], key=len, reverse=True)

    for phrase in BLOCKED_PHRASES:
        text = text.replace(phrase, '')

    # נשמור הכל להודעה, אבל TTS יקרא רק עברית
    text = re.sub(r'[^\w\s.,!?()\u0590-\u05FF:/]', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

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
    qquuid = str(uuid.uuid4())
    filename = os.path.basename(file_path)

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

def upload_to_ymot(wav_file_path):
    """העלאת קובץ רגיל או גדול לימות המשיח"""
    file_size = os.path.getsize(wav_file_path)
    if file_size > 20 * 1024 * 1024:
        print("⚠️ קובץ גדול – משתמש בהעלאה בחלקים...")
        return upload_large_to_ymot(wav_file_path)
    url = 'https://call2all.co.il/ym/api/UploadFile'
    with open(wav_file_path, 'rb') as f:
        files = {'file': (os.path.basename(wav_file_path), f, 'audio/wav')}
        data = {
            'token': YMOT_TOKEN,
            'path': YMOT_PATH,
            'convertAudio': '1',
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
    for chunk in resp.iter_content(1024 * 1024):
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
