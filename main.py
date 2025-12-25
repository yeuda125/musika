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
import logging

from pyrogram import Client, filters
from google.cloud import texttospeech
# 💎 תוספת: ספריית גמיני
import google.generativeai as genai

# הגדרת לוגים בסיסית (כדי שנראה שגיאות אם יש)
logging.basicConfig(level=logging.INFO)

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
# נתיב ברירת מחדל (נשאר כמשתנה סביבה אך לא בשימוש כ-Fallback בקוד הזה לאור הבקשה)
DEFAULT_YMOT_PATH = os.getenv("YMOT_PATH", "ivr2:/988/")

# 💎 תוספת: הגדרת מפתח גמיני
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
else:
    print("⚠️ אזהרה: מפתח GEMINI_API_KEY לא מוגדר. התמלול לא יפעל.")

# ---------------------------------------------------------
# ⚙️ הגדרות ניתוב ערוצים (ימות המשיח)
# רק ערוצים שמופיעים כאן יטופלו עבור העלאה לימות המשיח.
# ---------------------------------------------------------
CHANNEL_SETTINGS = {
    # דוגמא: ID של ערוץ : נתיב בימות המשיח
    -1002710964688: "ivr2:/988/",  # ערוץ קיים (דוגמה מהקוד שלך)
    -1003482327489: "ivr2:/11/",   # דוגמה לערוץ A
    -1003579694794: "ivr2:/22/",   # דוגמה לערוץ B
    -1003562922585: "ivr2:/33/",   # דוגמה לערוץ C
}

# ---------------------------------------------------------
# 🎙️ הגדרות ערוץ תמלול (גמיני)
# ערוץ זה ישמש אך ורק לתמלול (לא יעלה קבצים לימות המשיח)
# ---------------------------------------------------------
# ✏️ החלף את המספר כאן ב-ID של הערוץ שמיועד לתמלול בלבד!
TRANSCRIBE_CHANNEL_ID = -1003472877496 

# 🟡 הגדרות קבועות
CHUNK_SIZE = 1 * 1024 * 1024  # 1MB
UPLOAD_URL = "https://call2all.co.il/ym/api/UploadFile"

# 💎 פונקציה חדשה לתמלול (לא נוגעת בלוגיקה של ימות המשיח)
async def transcribe_with_gemini(client, chat_id, message_id, file_path):
    if not GEMINI_API_KEY:
        return

    try:
        print(f"🎙️ מתחיל תמלול גמיני לקובץ: {file_path}")
        
        # הרצת גמיני ב-Thread נפרד כדי לא לתקוע את הבוט
        # שימוש במודל Flash המהיר
        model = genai.GenerativeModel("gemini-2.0-flash")
        
        # פונקציה פנימית לביצוע הפעולה מול גוגל
        def run_sync_api():
            uploaded = genai.upload_file(file_path)
            # המתנה לעיבוד הקובץ בגוגל
            while uploaded.state.name == "PROCESSING":
                time.sleep(1)
                uploaded = genai.get_file(uploaded.name)
            
            prompt = """
            תפקידך: אתה מערכת תמלול לדיווחים.
            בצע תמלול מלא של האודיו לעברית, ונסח אותו מחדש כפי הבנתך בצורה קריאה ונכונה.
            אל תנהל שיחה. פלוט אך ורק את הטקסט המתומלל.
            אם אין דיבור, כתוב: "לא זוהה דיבור".
            """
            result = model.generate_content([prompt, uploaded])
            return result.text

        # הרצה א-סינכרונית
        text_result = await asyncio.to_thread(run_sync_api)
        
        # שליחת התגובה לטלגרם
        if text_result:
            await client.send_message(
                chat_id, 
                f"🎙️ **תמלול אוטומטי:**\n\n{text_result}",
                reply_to_message_id=message_id
            )
            print("✅ תמלול נשלח בהצלחה.")

    except Exception as e:
        print(f"❌ שגיאה בתהליך התמלול: {e}")


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
        "בטלגרם",
        "הכי חם ברשת",
        "הערינג",
        "055-675-3075",
        "לשליחת חומרים",
        "וואטצפ",
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
    text = re.sub(r'[^\w\s.,!?()\u0590-\u05FF]', '', text)
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
    ], check=True)


def concat_wav_files(file1, file2, output_file="merged.wav"):
    tmp1 = "tmp1_ymot.wav"
    tmp2 = "tmp2_ymot.wav"
    
    convert_to_wav(file1, tmp1)
    convert_to_wav(file2, tmp2)

    list_file = "list.txt"
    with open(list_file, "w", encoding="utf-8") as f:
        f.write(f"file '{tmp1}'\n")
        f.write(f"file '{tmp2}'\n")

    subprocess.run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", list_file, "-c", "copy", output_file
    ], check=True)

    os.remove(tmp1)
    os.remove(tmp2)
    os.remove(list_file)


def maybe_remove_files(*filenames):
    for f in filenames:
        if os.path.exists(f):
            try:
                os.remove(f)
            except OSError as e:
                print(f"⚠️ שגיאה במחיקת קובץ {f}: {e}")


def upload_to_ymot(file_path, target_path):
    print(f"📡 מעלה קובץ לשלוחה: {target_path}")
    file_size = os.path.getsize(file_path)

    if file_size <= 50 * 1024 * 1024:
        # 🔹 העלאה רגילה
        with open(file_path, "rb") as f:
            files = {"file": (os.path.basename(file_path), f, "audio/wav")}
            data = {
                "token": YMOT_TOKEN,
                "path": target_path,
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
                    "path": target_path,
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
            "path": target_path,
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

@app.on_message(filters.channel)
async def handle_message(client, message):
    
    chat_id = message.chat.id
    
    # 📌 בדיקה לאיזה סוג ערוץ שייכת ההודעה
    is_ymot_channel = chat_id in CHANNEL_SETTINGS
    is_transcribe_channel = chat_id == TRANSCRIBE_CHANNEL_ID
    
    # אם הערוץ לא מוגדר באף אחת מהרשימות - מתעלמים
    if not is_ymot_channel and not is_transcribe_channel:
        print(f"🚫 הודעה מערוץ לא מוגדר ({chat_id}) - מתעלם.")
        return

    # שליפת נתיב לימות (רק אם זה ערוץ ימות)
    target_ymot_path = CHANNEL_SETTINGS.get(chat_id)
    
    if is_ymot_channel:
        print(f"📩 ימות המשיח: הודעה מערוץ {chat_id} | מעביר לשלוחה: {target_ymot_path}")
    elif is_transcribe_channel:
        print(f"📩 תמלול: הודעה מערוץ {chat_id} | מעביר לגמיני")

    # 🛑 התעלמות מהודעות תגובה
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

    # נתיב הורדה בפועל
    downloaded_video_path = None
    downloaded_audio_path = None

    # 1. 🎥 וידאו עם טקסט (משולב) - מטופל ראשון
    if has_video and text:
        print("▶️ מטפל בווידאו וטקסט משולב...")

        try:
            # 1. הורדת הווידאו והמרתו ל־WAV
            downloaded_video_path = await message.download(file_name=VIDEO_FILE)
            convert_to_wav(downloaded_video_path, VIDEO_WAV)

            # --- לוגיקת תמלול ---
            if is_transcribe_channel:
                await transcribe_with_gemini(client, chat_id, message.id, VIDEO_WAV)

            # --- לוגיקת ימות המשיח ---
            if is_ymot_channel:
                # 2. עיבוד הטקסט והמרתו ל־WAV (TTS)
                cleaned_text = clean_text(text)
                cleaned_for_tts = re.sub(r"[^0-9א-ת\s]", "", cleaned_text)
                cleaned_for_tts = re.sub(r"\s+", " ", cleaned_for_tts).strip()

                if cleaned_for_tts:
                    full_text = create_full_text(cleaned_for_tts)
                    text_to_mp3(full_text, TTS_MP3)
                    convert_to_wav(TTS_MP3, TTS_WAV)

                    # העלאה בנפרד (קודם וידאו ואז טקסט)
                    print("⬆️ מעלה את קובץ האודיו של הוידאו...")
                    upload_to_ymot(VIDEO_WAV, target_ymot_path)
                    
                    print("⬆️ מעלה את קובץ הטקסט (TTS)...")
                    upload_to_ymot(TTS_WAV, target_ymot_path)
                    
                    print("✅ וידאו וטקסט הועלו כשני קבצים נפרדים בהצלחה!")
                else:
                    print("⚠️ הטקסט נוקה לחלוטין (ריק). מעלה רק את הווידאו.")
                    upload_to_ymot(VIDEO_WAV, target_ymot_path)
                    print("✅ וידאו בלבד הועלה בהצלחה.")

        except Exception as e:
            print(f"❌ שגיאה בטיפול בווידאו וטקסט משולב: {e}")

        finally:
            cleanup_files = [VIDEO_WAV, TTS_MP3, TTS_WAV, FINAL_WAV]
            if downloaded_video_path:
                cleanup_files.append(downloaded_video_path)
            maybe_remove_files(*cleanup_files)
        
        return # יציאה מהפונקציה

    # 2. 🎥 וידאו בלבד
    if has_video:
        print("▶️ מטפל בווידאו בלבד...")
        try:
            downloaded_video_path = await message.download(file_name=VIDEO_FILE)
            wav_file = VIDEO_WAV
            convert_to_wav(downloaded_video_path, wav_file)
            
            # --- לוגיקת תמלול ---
            if is_transcribe_channel:
                await transcribe_with_gemini(client, chat_id, message.id, wav_file)
            
            # --- לוגיקת ימות המשיח ---
            if is_ymot_channel:
                upload_to_ymot(wav_file, target_ymot_path)
                print("✅ וידאו בלבד הועלה בהצלחה.")
                
        except Exception as e:
            print(f"❌ שגיאה בטיפול בווידאו בלבד: {e}")
        finally:
            cleanup_files = [VIDEO_WAV]
            if downloaded_video_path:
                cleanup_files.append(downloaded_video_path)
            maybe_remove_files(*cleanup_files)


    # 3. 🎤 קול (voice)
    if has_voice:
        print("▶️ מטפל בהודעת קול...")
        try:
            downloaded_audio_path = await message.download(file_name="voice.ogg")
            wav_file = OUTPUT_WAV
            convert_to_wav(downloaded_audio_path, wav_file)
            
            # --- לוגיקת תמלול ---
            if is_transcribe_channel:
                await transcribe_with_gemini(client, chat_id, message.id, wav_file)

            # --- לוגיקת ימות המשיח ---
            if is_ymot_channel:
                upload_to_ymot(wav_file, target_ymot_path)
                print("✅ קול הועלה בהצלחה.")
                
        except Exception as e:
            print(f"❌ שגיאה בטיפול בהודעת קול: {e}")
        finally:
            cleanup_files = [OUTPUT_WAV]
            if downloaded_audio_path:
                cleanup_files.append(downloaded_audio_path)
            maybe_remove_files(*cleanup_files)

    # 4. 🎵 אודיו רגיל (audio)
    if has_audio:
        print("▶️ מטפל בקובץ אודיו...")
        try:
            downloaded_audio_path = await message.download(file_name=message.audio.file_name or "audio.mp3")
            wav_file = OUTPUT_WAV
            convert_to_wav(downloaded_audio_path, wav_file)
            
            # --- לוגיקת תמלול ---
            if is_transcribe_channel:
                await transcribe_with_gemini(client, chat_id, message.id, wav_file)
            
            # --- לוגיקת ימות המשיח ---
            if is_ymot_channel:
                upload_to_ymot(wav_file, target_ymot_path)
                print("✅ אודיו הועלה בהצלחה.")
                
        except Exception as e:
            print(f"❌ שגיאה בטיפול בקובץ אודיו: {e}")
        finally:
            cleanup_files = [OUTPUT_WAV]
            if downloaded_audio_path:
                cleanup_files.append(downloaded_audio_path)
            maybe_remove_files(*cleanup_files)

    # 5. 📝 טקסט בלבד
    if text:
        # טקסט בלבד מטופל רק עבור ימות המשיח (המרת TTS)
        # עבור תמלול, אין מה לתמלל בהודעת טקסט, אז מתעלמים
        if is_ymot_channel:
            print("▶️ מטפל בטקסט בלבד (ימות)...")
            try:
                cleaned_text = clean_text(text)
                cleaned_for_tts = re.sub(r"[^0-9א-ת\s]", "", cleaned_text)
                cleaned_for_tts = re.sub(r"\s+", " ", cleaned_for_tts).strip()

                if cleaned_for_tts:
                    full_text = create_full_text(cleaned_for_tts)
                    text_to_mp3(full_text, OUTPUT_MP3)
                    convert_to_wav(OUTPUT_MP3, OUTPUT_WAV)
                    upload_to_ymot(OUTPUT_WAV, target_ymot_path)
                    print("✅ טקסט הועלה בהצלחה.")
            except Exception as e:
                print(f"❌ שגיאה בטיפול בטקסט בלבד: {e}")
            finally:
                maybe_remove_files(OUTPUT_MP3, OUTPUT_WAV)


from keep_alive import keep_alive
keep_alive()

print("🚀 הבוט מאזין לערוץ ומעלה לשלוחה/מתמלל 🎧")

while True:
    try:
        app.run()
    except Exception as e:
        print("❌ הבוט נפל:", e)
        time.sleep(20)
