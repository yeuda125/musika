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
    # שורה זו הכילה רווח קשיח לפני 'raise'
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
CHUNK_SIZE = 1 * 1024 * 1024  # 1MB
# ✅ הכתובת תוקנה כבר לשם הדומיין הנכון (co.il)
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
    # שימוש ב-subprocess.run הוא אסינכרוני וזה בסדר כאן
    subprocess.run([
        "ffmpeg", "-i", input_file, "-ar", "8000", "-ac", "1", "-f", "wav",
        output_file, "-y"
    ])


def concat_wav_files(input1, input2, output_file):
    """
    מצרף שני קבצי WAV לקובץ פלט אחד באמצעות FFmpeg.
    input1 - הקובץ הראשון (הטקסט)
    input2 - הקובץ השני (הווידאו/קול)
    """
    # יצירת קובץ ליסט זמני עבור FFmpeg עם שם ייחודי
    list_file = "concat_list_" + str(uuid.uuid4()) + ".txt"
    try:
        with open(list_file, "w") as f:
            f.write(f"file '{input1}'\n")
            f.write(f"file '{input2}'\n")

        subprocess.run([
            "ffmpeg", 
            "-f", "concat", 
            "-safe", "0", 
            "-i", list_file, 
            "-c", "copy", 
            output_file, 
            "-y"
        ], check=True)
    finally:
        if os.path.exists(list_file):
            os.remove(list_file)


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

    # 1. 🎥 טיפול במקרה מיוחד: וידאו עם טקסט (איחוד)
    if has_video and text:
        # שימוש בשמות קבצים ייחודיים למניעת התנגשויות
        video_orig_file = str(uuid.uuid4()) + "_video.mp4"
        video_wav_file = str(uuid.uuid4()) + "_video.wav"
        text_mp3_file = str(uuid.uuid4()) + "_text.mp3"
        text_wav_file = str(uuid.uuid4()) + "_text.wav"
        final_wav_file = str(uuid.uuid4()) + "_final.wav"
        
        cleaned_text = clean_text(text)
        cleaned_for_tts = re.sub(r"[^0-9א-ת\s]", "", cleaned_text)
        cleaned_for_tts = re.sub(r"\s+", " ", cleaned_for_tts).strip()

        temp_files = []
        upload_path = None

        try:
            # 1.1 הורדת וידאו והמרה ל-WAV
            # ✅ שימוש בשיטה הנכונה של Pyrogram
            await message.download(file_name=video_orig_file)
            convert_to_wav(video_orig_file, video_wav_file)
            temp_files.extend([video_orig_file, video_wav_file])

            is_text_valid = False
            # 1.2 עיבוד טקסט והמרה ל-WAV
            if cleaned_for_tts:
                full_text = create_full_text(cleaned_for_tts)
                text_to_mp3(full_text, text_mp3_file)
                convert_to_wav(text_mp3_file, text_wav_file)
                temp_files.extend([text_mp3_file, text_wav_file])
                is_text_valid = True
            
            if is_text_valid:
                # 1.3 איחוד קבצים (טקסט קודם, אח"כ וידאו)
                print("🔗 מאחד טקסט ו-וידאו לקובץ אחד...")
                concat_wav_files(text_wav_file, video_wav_file, final_wav_file)
                upload_path = final_wav_file
            else:
                # אם הטקסט לא תקני, מעלה רק את הוידאו המומר
                print("⚠️ נמצא וידאו עם טקסט לא תקני. מעלה רק וידאו.")
                upload_path = video_wav_file
            
            # 1.4 העלאה
            if upload_path:
                upload_to_ymot(upload_path)

        except Exception as e:
            print(f"❌ שגיאה בטיפול וידאו+טקסט: {e}")

        finally:
            # 1.5 ניקוי כל הקבצים הזמניים שנוצרו
            for f in temp_files + [final_wav_file]:
                if os.path.exists(f):
                    os.remove(f)
            return # חשוב לצאת כדי לא להגיע לטיפול הנפרד בהמשך

    # 🎥 וידאו (רק וידאו)
    if has_video:
        # ✅ שימוש בשיטה הנכונה של Pyrogram וניקוי
        video_file = str(uuid.uuid4()) + "_video.mp4"
        wav_file = str(uuid.uuid4()) + "_video.wav"
        
        await message.download(file_name=video_file)
        convert_to_wav(video_file, wav_file)
        upload_to_ymot(wav_file)
        
        if os.path.exists(video_file): os.remove(video_file)
        if os.path.exists(wav_file): os.remove(wav_file)

    # 🎤 קול (voice)
    if has_voice:
        # ✅ שימוש בשיטה הנכונה של Pyrogram
        voice_file = str(uuid.uuid4()) + "_voice.ogg"
        wav_file = str(uuid.uuid4()) + "_voice.wav"
        
        await message.download(file_name=voice_file)
        convert_to_wav(voice_file, wav_file)
        upload_to_ymot(wav_file)
        
        if os.path.exists(voice_file): os.remove(voice_file)
        if os.path.exists(wav_file): os.remove(wav_file)

    # 🎵 אודיו רגיל (audio)
    if has_audio:
        # ✅ שימוש בשיטה הנכונה של Pyrogram
        audio_file = await message.download(file_name=message.audio.file_name or (str(uuid.uuid4()) + "_audio.mp3"))
        wav_file = str(uuid.uuid4()) + "_audio.wav"

        convert_to_wav(audio_file, wav_file)
        upload_to_ymot(wav_file)
        
        if os.path.exists(audio_file): os.remove(audio_file)
        if os.path.exists(wav_file): os.remove(wav_file)


    # 📝 טקסט (רק טקסט)
    if text:
        cleaned_text = clean_text(text)
        cleaned_for_tts = re.sub(r"[^0-9א-ת\s]", "", cleaned_text)
        cleaned_for_tts = re.sub(r"\s+", " ", cleaned_for_tts).strip()
        
        mp3_file = str(uuid.uuid4()) + "_output.mp3"
        wav_file = str(uuid.uuid4()) + "_output.wav"


        if cleaned_for_tts:
            full_text = create_full_text(cleaned_for_tts)
            text_to_mp3(full_text, mp3_file)
            convert_to_wav(mp3_file, wav_file)
            upload_to_ymot(wav_file)
            
            if os.path.exists(mp3_file): os.remove(mp3_file)
            if os.path.exists(wav_file): os.remove(wav_file)


from keep_alive import keep_alive
keep_alive()

print("🚀 הבוט מאזין לערוץ ומעלה לשלוחה 🎧")

while True:
    try:
        app.run()
    except Exception as e:
        print("❌ הבוט נפל:", e)
        time.sleep(20)
