"""Telegram Text-to-Voice Bot (free, edge-tts).

User sends any text -> bot replies with a voice message.
Voices: Bangla female (bn-BD-NabanitaNeural), Bangla male
(bn-BD-PradeepNeural), English female (en-US-AriaNeural).
User picks a voice with buttons; default is Bangla female.

Run:  python bot.py
Required env: TELEGRAM_BOT_TOKEN
Optional env: PORT (set automatically on Render)
"""

import logging
import os
import shutil
import subprocess
import tempfile
from threading import Thread

import edge_tts
from flask import Flask
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("tg-tts-bot")

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip().strip('"').strip("'")
PORT = int(os.environ.get("PORT", "8080"))
MAX_CHARS = 800

VOICES = {
    "bn_f": ("🇧🇩 বাংলা (মহিলা কণ্ঠ)", "bn-BD-NabanitaNeural"),
    "bn_m": ("🇧🇩 বাংলা (পুরুষ কণ্ঠ)", "bn-BD-PradeepNeural"),
    "en_f": ("🇬🇧 English (Female)", "en-US-AriaNeural"),
}
USER_VOICE = {}  # chat_id -> voice key


def voice_keyboard():
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(label, callback_data=f"v:{key}")]
         for key, (label, _) in VOICES.items()]
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "আসসালামু আলাইকুম! 🎙️ আমি Text-to-Voice বট।\n\n"
        "আমাকে যেকোনো লেখা পাঠান — আমি সেটা ভয়েস মেসেজ বানিয়ে দেব।\n"
        "প্রথমে নিচে থেকে কণ্ঠ বেছে নিন (না বাছলেও চলবে, ডিফল্ট বাংলা মহিলা কণ্ঠ):",
        reply_markup=voice_keyboard(),
    )


async def voice_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("কণ্ঠ বেছে নিন:", reply_markup=voice_keyboard())


async def on_voice_pick(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    key = q.data.split(":", 1)[1]
    if key in VOICES:
        USER_VOICE[q.message.chat_id] = key
        await q.edit_message_text(f"✅ কণ্ঠ সেট হয়েছে: {VOICES[key][0]}\nএবার লেখা পাঠান!")


def _ffmpeg():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return shutil.which("ffmpeg")


async def make_voice(text, voice, out_ogg):
    """Create an OGG/Opus voice file from text with edge-tts."""
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
        mp3_path = f.name
    try:
        await edge_tts.Communicate(text, voice).save(mp3_path)
        ff = _ffmpeg()
        if ff:
            subprocess.run(
                [ff, "-y", "-i", mp3_path, "-c:a", "libopus", "-b:a", "32k", out_ogg],
                check=True, capture_output=True,
            )
            return out_ogg
        return mp3_path  # fall back to mp3 (sent as audio)
    except Exception:
        try:
            os.unlink(mp3_path)
        except OSError:
            pass
        raise


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    text = update.message.text.strip()
    chat_id = update.effective_chat.id
    if len(text) > MAX_CHARS:
        await update.message.reply_text(
            f"⚠️ লেখাটা বড় হয়ে গেছে ({len(text)} অক্ষর)। একবারে সর্বোচ্চ {MAX_CHARS} অক্ষর পাঠান — বড় লেখা ভাগ করে পাঠান।"
        )
        return
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.RECORD_VOICE)
    voice = VOICES[USER_VOICE.get(chat_id, "bn_f")][1]
    out = os.path.join(tempfile.gettempdir(), f"tts_{chat_id}.ogg")
    try:
        path = await make_voice(text, voice, out)
        with open(path, "rb") as fh:
            if path.endswith(".ogg"):
                await update.message.reply_voice(voice=fh)
            else:
                await update.message.reply_audio(audio=fh, title="Text to Voice")
    except Exception as e:
        log.error("TTS error: %s", e)
        await update.message.reply_text("দুঃখিত, ভয়েস বানাতে সমস্যা হয়েছে। আরেকবার চেষ্টা করুন। 🙏")
    finally:
        for p in {out}:
            try:
                os.unlink(p)
            except OSError:
                pass


# --- tiny web server so Render keeps the service "web" ---
web = Flask(__name__)


@web.route("/")
def home():
    return "Text-to-Voice bot is running."


def run_web():
    web.run(host="0.0.0.0", port=PORT)


def main():
    if not TOKEN:
        raise SystemExit("TELEGRAM_BOT_TOKEN must be set.")
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("voice", voice_cmd))
    app.add_handler(CallbackQueryHandler(on_voice_pick, pattern=r"^v:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    Thread(target=run_web, daemon=True).start()
    log.info("Starting polling mode")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
