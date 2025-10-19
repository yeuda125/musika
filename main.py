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
CHUNK_SIZE = 1 * 1024 * 1024  # 1MB
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
    # שינוי קטן: הוספת תווי ':' ו־'/' לניקוי, כי הם היו מופיעים כחלק מקישורים שנמחקו
    text = re.sub(r'[^\w\s.,!?()\u0590-\u05FF]', '', text)
    text = re.sub(r'\s+', ' ', text).strip()

    return text


def create_full_text(text):
    # הפונקציה הזו כרגע מחזירה את הטקסט כמות שהוא,
    # אך מיועדת להוספת תוספות כמו שעה או כותרת במידת הצורך
    return text


def text_to_mp3(text, filename="output.mp3"):
    # ... (פונקציית TTS) ...
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
    """
    פונקציית המרה ל־WAV בפורמט ימות (8000Hz, מונו).
    הוספת check=True לוודא שההמרה מצליחה.
    """
    subprocess.run([
        "ffmpeg", "-i", input_file, "-ar", "8000", "-ac", "1", "-f", "wav",
        output_file, "-y"
    ], check=True) # 🔑 הוספת check=True


def concat_wav_files(file1, file2, output_file="merged.wav"):
    """
    🔗 מחבר שני קבצי WAV לקובץ פלט אחד, תוך המרה לפורמט 8000Hz מונו.
    file1 יושמע ראשון, ואחריו file2.
    """
    tmp1 = "tmp1_ymot.wav"
    tmp2 = "tmp2_ymot.wav"
    
    # ודא ששני הקבצים מומרים לפורמט הנדרש (8000Hz, מונו)
    # `-y` מחליף קבצים קיימים
    convert_to_wav(file1, tmp1)
    convert_to_wav(file2, tmp2)

    # כתיבת קובץ רשימה ל־ffmpeg concat
    list_file = "list.txt"
    with open(list_file, "w", encoding="utf-8") as f:
        f.write(f"file '{tmp1}'\n")
        f.write(f"file '{tmp2}'\n")

    # ביצוע החיבור
    subprocess.run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", list_file, "-c", "copy", output_file
    ], check=True) # check=True יוודא שגיאות

    # ניקוי קבצי עזר
    os.remove(tmp1)
    os.remove(tmp2)
    os.remove(list_file)


def maybe_remove_files(*filenames):
    """
    פונקציית עזר למחיקת קבצים זמניים בבטחה.
    """
    for f in filenames:
        if os.path.exists(f):
            try:
                os.remove(f)
            except OSError as e:
                print(f"⚠️ שגיאה במחיקת קובץ {f}: {e}")


def upload_to_ymot(file_path):
    # ... (פונקציית העלאה לימות המשיח) ...
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
    
    # 🛑 תיקון 2: התעלמות מהודעות תגובה כדי למנוע KeyError ב-Pyrogram
    if message.reply_to_message:
        print("⏭️ מדלג על הודעה: זוהי תגובה להודעה אחרת.")
        return

    text = message.text or message.caption
    has_video = message.video is not None
    has_voice = message.voice is not None
    has_audio = message.audio is not None

    # הגדרת שמות קבצים זמניים
    VIDEO_FILE = "video.mp4"
    VIDEO_WAV = "video.wav"
    TTS_MP3 = "text.mp3"
    TTS_WAV = "text.wav"
    FINAL_WAV = "final_concat.wav"
    OUTPUT_MP3 = "output.mp3"
    OUTPUT_WAV = "output.wav"

    # 1. 🎥 וידאו עם טקסט (משולב) - מטופל ראשון
    if has_video and text:
        print("▶️ מטפל בווידאו וטקסט משולב...")

        try:
            # 1. הורדת הווידאו והמרתו ל־WAV
            # הפונקציה convert_to_wav מעכשיו עם check=True - תיקון 1
            await message.download(file_name=VIDEO_FILE)
            convert_to_wav(VIDEO_FILE, VIDEO_WAV)

            # 2. עיבוד הטקסט והמרתו ל־WAV (TTS)
            cleaned_text = clean_text(text)
            # ניקוי נוסף עבור TTS
            cleaned_for_tts = re.sub(r"[^0-9א-ת\s]", "", cleaned_text)
            cleaned_for_tts = re.sub(r"\s+", " ", cleaned_for_tts).strip()

            if cleaned_for_tts:
                full_text = create_full_text(cleaned_for_tts)
                text_to_mp3(full_text, TTS_MP3)
                convert_to_wav(TTS_MP3, TTS_WAV)

                # 3. חיבור TTS ואודיו הווידאו
                concat_wav_files(TTS_WAV, VIDEO_WAV, FINAL_WAV)

                # 4. העלאה לימות המשיח
                upload_to_ymot(FINAL_WAV)
                print("✅ וידאו וטקסט משולבים הועלו בהצלחה!")
            else:
                # אם אין טקסט נקי, מטפל בזה רק כווידאו רגיל
                print("⚠️ הטקסט נוקה לחלוטין (ריק). מעלה רק את הווידאו.")
                upload_to_ymot(VIDEO_WAV)
                print("✅ וידאו בלבד הועלה בהצלחה.")

        except Exception as e:
            print(f"❌ שגיאה בטיפול בווידאו וטקסט משולב: {e}")

        finally:
            # ניקוי כל הקבצים הזמניים
            maybe_remove_files(VIDEO_FILE, VIDEO_WAV, TTS_MP3, TTS_WAV, FINAL_WAV)
        
        return # יציאה מהפונקציה כדי למנוע כפילויות

    # 2. 🎥 וידאו בלבד
    if has_video:
        print("▶️ מטפל בווידאו בלבד...")
        try:
            video_file = await message.download(file_name=VIDEO_FILE)
            wav_file = VIDEO_WAV
            convert_to_wav(video_file, wav_file)
            upload_to_ymot(wav_file)
            print("✅ וידאו בלבד הועלה בהצלחה.")
        except Exception as e:
            print(f"❌ שגיאה בטיפול בווידאו בלבד: {e}")
        finally:
            maybe_remove_files(VIDEO_FILE, VIDEO_WAV)


    # 3. 🎤 קול (voice)
    if has_voice:
        print("▶️ מטפל בהודעת קול...")
        try:
            voice_file = await message.download(file_name="voice.ogg")
            wav_file = OUTPUT_WAV
            convert_to_wav(voice_file, wav_file)
            upload_to_ymot(wav_file)
            print("✅ קול הועלה בהצלחה.")
        except Exception as e:
            print(f"❌ שגיאה בטיפול בהודעת קול: {e}")
        finally:
            maybe_remove_files("voice.ogg", OUTPUT_WAV)

    # 4. 🎵 אודיו רגיל (audio)
    if has_audio:
        print("▶️ מטפל בקובץ אודיו...")
        try:
            audio_file = await message.download(file_name=message.audio.file_name or "audio.mp3")
            wav_file = OUTPUT_WAV
            convert_to_wav(audio_file, wav_file)
            upload_to_ymot(wav_file)
            print("✅ אודיו הועלה בהצלחה.")
        except Exception as e:
            print(f"❌ שגיאה בטיפול בקובץ אודיו: {e}")
        finally:
            maybe_remove_files(audio_file, OUTPUT_WAV)

    # 5. 📝 טקסט בלבד
    if text:
        print("▶️ מטפל בטקסט בלבד...")
        try:
            cleaned_text = clean_text(text)
            cleaned_for_tts = re.sub(r"[^0-9א-ת\s]", "", cleaned_text)
            cleaned_for_tts = re.sub(r"\s+", " ", cleaned_for_tts).strip()

            if cleaned_for_tts:
                full_text = create_full_text(cleaned_for_tts)
                text_to_mp3(full_text, OUTPUT_MP3)
                convert_to_wav(OUTPUT_MP3, OUTPUT_WAV)
                upload_to_ymot(OUTPUT_WAV)
                print("✅ טקסט הועלה בהצלחה.")
        except Exception as e:
            print(f"❌ שגיאה בטיפול בטקסט בלבד: {e}")
        finally:
            maybe_remove_files(OUTPUT_MP3, OUTPUT_WAV)


from keep_alive import keep_alive
keep_alive()

print("🚀 הבוט מאזין לערוץ ומעלה לשלוחה 🎧")

while True:
    try:
        app.run()
    except Exception as e:
        print("❌ הבוט נפל:", e)
        time.sleep(20)
