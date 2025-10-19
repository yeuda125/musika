יש לי קוד כזה
import os
import json
import subprocess
import requests
import base64
import uuid
import math
from datetime import datetime
import pytz
import asyncio
import re
import time

from pyrogram import Client, filters
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
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
YMOT_TOKEN = os.getenv("YMOT_TOKEN")
YMOT_PATH = os.getenv("YMOT_PATH", "ivr2:/988/")

# 🟡 הגדרות קבועות
CHUNK_SIZE = 1 * 1024 * 1024  # 1MB
UPLOAD_URL = "https://call2all.co.il/ym/api/UploadFile"


def clean_text(text):
    BLOCKED_PHRASES = sorted([
        "חדשות המוקד • בטלגרם: t.me/hamoked_il",
        "בוואטסאפ: https://chat.whatsapp.com/LoxVwdYOKOAH2y2kaO8GQ7",
        "לעדכוני הפרגוד בטלגרם",
        "ידיעות בני ברק",
        "לכל העדכונים, ולכתבות נוספות הצטרפו לערוץ דרך הקישור",
        "להצטרפות מלאה לקבוצה לחצו על הצטרף",
        "לכל העדכונים",
        "לשיתוף",
        "בWhatsApp",
        "מה שמעניין",
        "בוואטסאפ",
        "ובטלגרם",
        "צאפ מגזין",
        "מה שמעניין בוואטצאפ",
        "מצטרפים בקישור",
        "סקופים",
        "צפו",
        "לכל העדכונים - ראשוני",
        "תאריך שידור",
    ], key=len, reverse=True)

    # 🛑 מחיקת ביטויים אסורים
    for phrase in BLOCKED_PHRASES:
        text = text.replace(phrase, '')

    # 🛑 מחיקת קישורים (http / https / www)
    text = re.sub(r'https?://\S+', '', text)
    text = re.sub(r'www\.\S+', '', text)

    # 🛑 מחיקת תווים לא עבריים
    text = re.sub(r'[^\w\s.,!?()\u0590-\u05FF:/]', '', text)
    text = re.sub(r'\s+', ' ', text).strip()

    return text


def create_full_text(text):
    return text


def text_to_mp3(text, filename="output.mp3"):
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


def convert_to_wav(input_file, output_file="output.wav"):
    subprocess.run([
        "ffmpeg", "-i", input_file, "-ar", "8000", "-ac", "1", "-f", "wav",
        output_file, "-y"
    ])


def upload_to_ymot(file_path):
    file_size = os.path.getsize(file_path)

    if file_size <= 50 * 1024 * 1024:
        # 🔹 העלאה רגילה
        with open(file_path, "rb") as f:
            files = {"file": (os.path.basename(file_path), f, "audio/wav")}
            data = {
                "token": YMOT_TOKEN,
                "path": YMOT_PATH,
                "convertAudio": 1,
                "autoNumbering": "true",
                "uploader": "yemot-admin"
            }
            response = requests.post(UPLOAD_URL, data=data, files=files)
        print("📞 תגובת ימות (upload רגיל):", response.text)

    else:
        # 🔹 העלאה ב־Chunks
        qquuid = str(uuid.uuid4())
        total_parts = math.ceil(file_size / CHUNK_SIZE)
        filename = os.path.basename(file_path)
        offset = 0

        with open(file_path, "rb") as f:
            for part_index in range(total_parts):
                chunk = f.read(CHUNK_SIZE)

                files = {"qqfile": chunk}
                data = {
                    "token": YMOT_TOKEN,
                    "path": YMOT_PATH,
                    "convertAudio": 0,
                    "autoNumbering": "true",
                    "uploader": "yemot-admin",
                    "qquuid": qquuid,
                    "qqfilename": filename,
                    "qqtotalfilesize": file_size,
                    "qqtotalparts": total_parts,
                    "qqchunksize": len(chunk),
                    "qqpartbyteoffset": offset,
                    "qqpartindex": part_index,
                }

                for attempt in range(3):
                    try:
                        response = requests.post(
                            UPLOAD_URL,
                            data=data,
                            files=files,
                            timeout=180
                        )
                        response.raise_for_status()
                        print(f"⬆️ חלק {part_index+1}/{total_parts} הועלה:", response.text)
                        break
                    except Exception as e:
                        print(f"❌ כשל בחלק {part_index+1}, ניסיון {attempt+1}: {e}")
                        if attempt == 2:
                            raise
                        time.sleep(5)

                offset += len(chunk)

        # 🔹 בקשת סיום
        data = {
            "token": YMOT_TOKEN,
            "path": YMOT_PATH,
            "convertAudio": 0,
            "autoNumbering": "true",
            "uploader": "yemot-admin",
            "qquuid": qquuid,
            "qqfilename": filename,
            "qqtotalfilesize": file_size,
            "qqtotalparts": total_parts
        }
        response = requests.post(UPLOAD_URL + "?done", data=data)

        texts = response.text.split("}{")
        for i, txt in enumerate(texts):
            if len(texts) > 1:
                if i == 0:
                    txt = txt + "}"
                elif i == len(texts) - 1:
                    txt = "{" + txt
                else:
                    txt = "{" + txt + "}"
            try:
                print("✅ סיום העלאה:", json.loads(txt))
            except Exception as e:
                print("⚠️ שגיאה בפענוח JSON:", e, txt)


# 🟡 UserBot
app = Client("my_account", api_id=API_ID, api_hash=API_HASH)


@app.on_message(filters.chat(-1002710964688))
async def handle_message(client, message):
    text = message.text or message.caption
    has_video = message.video is not None
    has_voice = message.voice is not None
    has_audio = message.audio is not None

    # 🎥 וידאו
    if has_video:
        video_file = await message.download(file_name="video.mp4")
        wav_file = "video.wav"
        convert_to_wav(video_file, wav_file)
        upload_to_ymot(wav_file)
        os.remove(video_file)
        os.remove(wav_file)

    # 🎤 קול (voice)
    if has_voice:
        voice_file = await message.download(file_name="voice.ogg")
        wav_file = "voice.wav"
        convert_to_wav(voice_file, wav_file)
        upload_to_ymot(wav_file)
        os.remove(voice_file)
        os.remove(wav_file)

    # 🎵 אודיו רגיל (audio)
    if has_audio:
        audio_file = await message.download(file_name=message.audio.file_name or "audio.mp3")
        wav_file = "audio.wav"
        convert_to_wav(audio_file, wav_file)
        upload_to_ymot(wav_file)
        os.remove(audio_file)
        os.remove(wav_file)

    # 📝 טקסט
    if text:
        cleaned_text = clean_text(text)
        cleaned_for_tts = re.sub(r"[^0-9א-ת\s]", "", cleaned_text)
        cleaned_for_tts = re.sub(r"\s+", " ", cleaned_for_tts).strip()

        if cleaned_for_tts:
            full_text = create_full_text(cleaned_for_tts)
            text_to_mp3(full_text, "output.mp3")
            convert_to_wav("output.mp3", "output.wav")
            upload_to_ymot("output.wav")
            os.remove("output.mp3")
            os.remove("output.wav")


from keep_alive import keep_alive
keep_alive()

print("🚀 הבוט מאזין לערוץ ומעלה לשלוחה 🎧")

while True:
    try:
        app.run()
    except Exception as e:
        print("❌ הבוט נפל:", e)
        time.sleep(20)

אני רוצה שכאשר אני מעלה הודעה בטלגרם של וידאו ויש גם טקסט בהודעה, כעת הוא מעלה את הוידאו ואחר כך קובץ של הטקסט, אני רוצה שהוא יאחד את הטקסט והוידאו לקובץ אחד, שקודם שומעים את הטקסט ואחר כך את הוידאו.

אל תשנה את הקוד עדיין. אני רוצה להעתיק לך קוד אחר שעושה את זה כדי שתראה איך לעשות את זה.
הקוד שעושה את זה הוא
    # 🎥 וידאו עם טקסט
    if has_video and text:
        video_file = await message.video.get_file()
        await video_file.download_to_drive("video.mp4")
        convert_to_wav("video.mp4", "video.wav")
        cleaned = clean_text(text)
        full_text = create_full_text(cleaned)
        text_to_mp3(full_text, "text.mp3")
        convert_to_wav("text.mp3", "text.wav")
        concat_wav_files("text.wav", "video.wav", "final.wav")
        upload_to_ymot("final.wav")

        # ✅ לוגיקת צינתוק חכמה
        maybe_send_tzintuk()

        for f in ["video.mp4", "video.wav", "text.mp3", "text.wav", "final.wav"]:
            if os.path.exists(f): os.remove(f)
        return

    if has_video:
        video_file = await message.video.get_file()
        await video_file.download_to_drive("video.mp4")
        convert_to_wav("video.mp4", "video.wav")
        upload_to_ymot("video.wav")

        maybe_send_tzintuk()    

        os.remove("video.mp4")
        os.remove("video.wav")

    if has_audio:
        audio_file = await (message.audio or message.voice).get_file()
        await audio_file.download_to_drive("audio.ogg")
        convert_to_wav("audio.ogg", "audio.wav")
        upload_to_ymot("audio.wav")

        maybe_send_tzintuk()    

        os.remove("audio.ogg")
        os.remove("audio.wav")

    if text:
        cleaned = clean_text(text)
        full_text = create_full_text(cleaned)
        text_to_mp3(full_text, "output.mp3")
        convert_to_wav("output.mp3", "output.wav")
        upload_to_ymot("output.wav")

        maybe_send_tzintuk()        

        os.remove("output.mp3")
        os.remove("output.wav"
