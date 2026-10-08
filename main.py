
import asyncio
import logging
import os
import shutil
import tempfile
from pathlib import Path

import yt_dlp
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    BufferedInputFile,
)
from aiogram.exceptions import TelegramBadRequest

# ---------------- CONFIG ----------------

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
WATERMARK = os.getenv("WATERMARK", "").strip()

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is missing")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("music_bot")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ---------------- TRANSLATIONS ----------------

TEXTS = {
    "fa": {
        "welcome": "🎵 به بات موزیک خوش آمدی!\nیک آهنگ جست‌وجو کن.",
        "search": "🔎 جست‌وجوی آهنگ",
        "language": "🌐 تغییر زبان",
        "send_song": "اسم آهنگ یا نام خواننده را بفرست.",
        "results": "🎶 یکی از آهنگ‌ها را انتخاب کن:",
        "processing": "⏳ در حال دانلود و پردازش آهنگ...",
        "choose_effect": "🎛 افکت موردنظرت را انتخاب کن:",
        "error": "❌ مشکلی پیش آمد. دوباره امتحان کن.",
        "not_found": "آهنگی پیدا نشد. عبارت دیگری امتحان کن.",
        "language_changed": "✅ زبان تغییر کرد.",
        "choose_language": "زبان موردنظرت را انتخاب کن:",
        "stats": "👥 تعداد کاربران ثبت‌شده: {users}",
        "broadcast": "متن پیام همگانی را بعد از دستور وارد کن.",
        "broadcast_done": "📨 ارسال تمام شد.\nموفق: {ok}\nناموفق: {failed}",
        "not_admin": "⛔ این دستور مخصوص ادمین است.",
        "back": "🔙 بازگشت",
        "download_error": "❌ پردازش آهنگ ناموفق بود. آهنگ دیگری امتحان کن.",
    },
    "en": {
        "welcome": "🎵 Welcome to the music bot!\nSearch for a song.",
        "search": "🔎 Search songs",
        "language": "🌐 Change language",
        "send_song": "Send a song title or artist name.",
        "results": "🎶 Choose a song:",
        "processing": "⏳ Downloading and processing your song...",
        "choose_effect": "🎛 Choose an audio effect:",
        "error": "❌ Something went wrong. Please try again.",
        "not_found": "No songs found. Try another search.",
        "language_changed": "✅ Language changed.",
        "choose_language": "Choose your language:",
        "stats": "👥 Registered users: {users}",
        "broadcast": "Send the broadcast message after the command.",
        "broadcast_done": "📨 Broadcast finished.\nSuccess: {ok}\nFailed: {failed}",
        "not_admin": "⛔ Admin only.",
        "back": "🔙 Back",
        "download_error": "❌ Audio processing failed. Try another song.",
    },
}

# ---------------- STORAGE ----------------

DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)

USERS_FILE = DATA_DIR / "users.txt"
LANG_FILE = DATA_DIR / "languages.txt"

users = set()
languages = {}

def load_storage():
    global users, languages

    if USERS_FILE.exists():
        users = {
            line.strip()
            for line in USERS_FILE.read_text(encoding="utf-8").splitlines()
            if line.strip().isdigit()
        }

    if LANG_FILE.exists():
        for line in LANG_FILE.read_text(encoding="utf-8").splitlines():
            parts = line.split(":", 1)
            if len(parts) == 2:
                languages[parts[0]] = parts[1]

def save_users():
    USERS_FILE.write_text(
        "\n".join(sorted(users)),
        encoding="utf-8",
    )

def save_languages():
    LANG_FILE.write_text(
        "\n".join(f"{uid}:{lang}" for uid, lang in languages.items()),
        encoding="utf-8",
    )

def get_lang(user_id):
    return languages.get(str(user_id), "fa")

def tr(user_id, key, **kwargs):
    lang = get_lang(user_id)
    value = TEXTS.get(lang, TEXTS["fa"]).get(key, key)
    return value.format(**kwargs)

load_storage()

# ---------------- AUDIO EFFECTS ----------------

EFFECTS = {
    "normal": {
        "fa": "🎵 معمولی و تقویت صدا",
        "en": "🎵 Normal + Volume",
        "filter": "anull",
    },
    "slowed": {
        "fa": "🐢 اسلو",
        "en": "🐢 Slowed",
        "filter": "atempo=0.80",
    },
    "slowed_reverb": {
        "fa": "🌌 اسلو + ریورب",
        "en": "🌌 Slowed + Reverb",
        "filter": "atempo=0.80,aecho=0.8:0.7:80:0.25",
    },
    "nightcore": {
        "fa": "⚡ نایت‌کور",
        "en": "⚡ Nightcore",
        "filter": "asetrate=44100*1.20,aresample=44100,atempo=1.0",
    },
    "speed": {
        "fa": "🚀 سرعت بیشتر",
        "en": "🚀 Speed Up",
        "filter": "atempo=1.20",
    },
    "bass": {
        "fa": "🔊 بیس بوست",
        "en": "🔊 Bass Boost",
        "filter": "bass=g=6:f=100:w=0.5",
    },
    "reverb": {
        "fa": "🌊 ریورب",
        "en": "🌊 Reverb",
        "filter": "aecho=0.8:0.7:60:0.3",
    },
    "8d": {
        "fa": "🎧 صدای 8D",
        "en": "🎧 8D Audio",
        "filter": "apulsator=hz=0.08",
    },
}

# ---------------- KEYBOARDS ----------------

def main_keyboard(user_id):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=tr(user_id, "search"),
                    callback_data="search",
                )
            ],
            [
                InlineKeyboardButton(
                    text=tr(user_id, "language"),
                    callback_data="language",
                )
            ],
        ]
    )

def language_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🇮🇷 فارسی",
                    callback_data="setlang:fa",
                ),
                InlineKeyboardButton(
                    text="🇬🇧 English",
                    callback_data="setlang:en",
                ),
            ]
        ]
    )

def effects_keyboard(user_id, video_id):
    lang = get_lang(user_id)
    rows = []

    for key, effect in EFFECTS.items():
        rows.append([
            InlineKeyboardButton(
                text=effect[lang],
                callback_data=f"effect:{video_id}:{key}",
            )
        ])

    rows.append([
        InlineKeyboardButton(
            text=tr(user_id, "back"),
            callback_data="home",
        )
    ])

    return InlineKeyboardMarkup(inline_keyboard=rows)

# ---------------- YOUTUBE SEARCH ----------------

def search_youtube(query):
    options = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
        "skip_download": True,
        "default_search": "ytsearch5",
    }

    with yt_dlp.YoutubeDL(options) as ydl:
        data = ydl.extract_info(f"ytsearch5:{query}", download=False)

    entries = data.get("entries") or []
    results = []

    for item in entries:
        if not item:
            continue

        video_id = item.get("id")
        title = item.get("title", "Unknown title")
        duration = item.get("duration")

        if not video_id:
            continue

        # Skip very long content
        if duration and duration > 900:
            continue

        results.append({
            "id": video_id,
            "title": title,
            "duration": duration,
        })

    return results

def search_keyboard(results):
    rows = []

    for item in results:
        title = item["title"]
        if len(title) > 55:
            title = title[:52] + "..."

        duration = item["duration"]
        if duration:
            minutes, seconds = divmod(int(duration), 60)
            title = f"{title} [{minutes}:{seconds:02d}]"

        rows.append([
            InlineKeyboardButton(
                text=title,
                callback_data=f"song:{item['id']}",
            )
        ])

    return InlineKeyboardMarkup(inline_keyboard=rows)

# ---------------- DOWNLOAD AND PROCESS ----------------

def download_audio(video_id, workdir):
    output_template = str(Path(workdir) / "source.%(ext)s")

    options = {
        "format": "bestaudio/best",
        "outtmpl": output_template,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": 30,
        "retries": 2,
        "max_filesize": 50 * 1024 * 1024,
    }

    with yt_dlp.YoutubeDL(options) as ydl:
        ydl.download([f"https://www.youtube.com/watch?v={video_id}"])

    candidates = [
        p for p in Path(workdir).glob("source.*")
        if p.is_file() and p.suffix.lower() not in {".part", ".ytdl"}
    ]

    if not candidates:
        raise RuntimeError("Audio file was not downloaded")

    return str(max(candidates, key=lambda p: p.stat().st_size))

def run_ffmpeg(input_file, output_file, effect_key):
    import subprocess

    effect = EFFECTS.get(effect_key)
    if not effect:
        raise ValueError("Invalid effect")

    # Apply the chosen effect, boost volume, then limit peaks.
    audio_filter = (
        f"{effect['filter']},"
        "volume=1.8,"
        "loudnorm=I=-12:LRA=9:TP=-1.0"
    )

    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel", "error",
        "-y",
        "-i", input_file,
        "-vn",
        "-af", audio_filter,
        "-codec:a", "libmp3lame",
        "-b:a", "192k",
        "-ar", "44100",
        output_file,
    ]

    result = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=300,
    )

    if result.returncode != 0 or not os.path.isfile(output_file):
        logger.error(
            "FFmpeg failed: %s",
            result.stderr.decode("utf-8", errors="ignore")[-2500:],
        )
        raise RuntimeError("FFmpeg audio processing failed")

    return output_file

# ---------------- COMMANDS ----------------

@dp.message(CommandStart())
async def start_handler(message: Message):
    user_id = message.from_user.id
    users.add(str(user_id))
    save_users()

    await message.answer(
        tr(user_id, "welcome"),
        reply_markup=main_keyboard(user_id),
    )

@dp.message(Command("help"))
async def help_handler(message: Message):
    await message.answer(
        tr(message.from_user.id, "welcome"),
        reply_markup=main_keyboard(message.from_user.id),
    )

@dp.message(Command("stats"))
async def stats_handler(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer(tr(message.from_user.id, "not_admin"))
        return

    await message.answer(
        tr(message.from_user.id, "stats", users=len(users))
    )

@dp.message(Command("broadcast"))
async def broadcast_handler(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer(tr(message.from_user.id, "not_admin"))
        return

    text = (message.text or "").partition(" ")[2].strip()

    if not text:
        await message.answer(tr(message.from_user.id, "broadcast"))
        return

    ok = 0
    failed = 0

    for user_id in list(users):
        try:
            await bot.send_message(int(user_id), text)
            ok += 1
        except Exception as exc:
            logger.warning("Broadcast failed for %s: %s", user_id, exc)
            failed += 1

        await asyncio.sleep(0.05)

    await message.answer(
        tr(message.from_user.id, "broadcast_done", ok=ok, failed=failed)
    )

# ---------------- CALLBACKS ----------------

@dp.callback_query(F.data == "home")
async def home_callback(callback: CallbackQuery):
    await callback.message.edit_text(
        tr(callback.from_user.id, "welcome"),
        reply_markup=main_keyboard(callback.from_user.id),
    )
    await callback.answer()

@dp.callback_query(F.data == "search")
async def search_callback(callback: CallbackQuery):
    await callback.message.answer(tr(callback.from_user.id, "send_song"))
    await callback.answer()

@dp.callback_query(F.data == "language")
async def language_callback(callback: CallbackQuery):
    await callback.message.answer(
        tr(callback.from_user.id, "choose_language"),
        reply_markup=language_keyboard(),
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("setlang:"))
async def set_language_callback(callback: CallbackQuery):
    lang = callback.data.split(":", 1)[1]

    if lang not in ("fa", "en"):
        await callback.answer()
        return

    languages[str(callback.from_user.id)] = lang
    save_languages()

    await callback.message.answer(
        tr(callback.from_user.id, "language_changed"),
        reply_markup=main_keyboard(callback.from_user.id),
    )
    await callback.answer()

@dp.message(F.text)
async def search_handler(message: Message):
    user_id = message.from_user.id
    query = (message.text or "").strip()

    if not query or query.startswith("/"):
        return

    users.add(str(user_id))
    save_users()

    status = await message.answer(tr(user_id, "processing"))

    try:
        results = await asyncio.to_thread(search_youtube, query)
    except Exception:
        logger.exception("YouTube search failed")
        await status.edit_text(tr(user_id, "error"))
        return

    if not results:
        await status.edit_text(tr(user_id, "not_found"))
        return

    await status.edit_text(
        tr(user_id, "results"),
        reply_markup=search_keyboard(results),
    )

@dp.callback_query(F.data.startswith("song:"))
async def song_callback(callback: CallbackQuery):
    video_id = callback.data.split(":", 1)[1]

    await callback.message.answer(
        tr(callback.from_user.id, "choose_effect"),
        reply_markup=effects_keyboard(callback.from_user.id, video_id),
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("effect:"))
async def effect_callback(callback: CallbackQuery):
    parts = callback.data.split(":", 2)

    if len(parts) != 3:
        await callback.answer()
        return

    _, video_id, effect_key = parts

    if effect_key not in EFFECTS:
        await callback.answer()
        return

    user_id = callback.from_user.id
    status = await callback.message.answer(tr(user_id, "processing"))

    try:
        with tempfile.TemporaryDirectory(prefix="musicbot_") as workdir:
            input_file = await asyncio.to_thread(
                download_audio,
                video_id,
                workdir,
            )

            output_file = str(Path(workdir) / "processed.mp3")

            await asyncio.to_thread(
                run_ffmpeg,
                input_file,
                output_file,
                effect_key,
            )

            file_size = os.path.getsize(output_file)

            # Telegram Bot API has file-size limits.
            if file_size > 49 * 1024 * 1024:
                await status.edit_text(tr(user_id, "download_error"))
                return

            with open(output_file, "rb") as audio_file:
                audio_bytes = audio_file.read()

            filename = f"{effect_key}_{video_id}.mp3"

            caption = WATERMARK or None

            audio = BufferedInputFile(
                audio_bytes,
                filename=filename,
            )

            await bot.send_audio(
                chat_id=user_id,
                audio=audio,
                caption=caption,
                title=f"Processed music - {effect_key}",
            )

        await status.delete()

    except Exception:
        logger.exception("Audio processing failed")
        try:
            await status.edit_text(tr(user_id, "download_error"))
        except TelegramBadRequest:
            pass

    await callback.answer()

# ---------------- RENDER WEB SERVER ----------------

async def start_health_server():
    try:
        from aiohttp import web

        async def health(_request):
            return web.Response(text="Music bot is running.")

        app = web.Application()
        app.router.add_get("/", health)
        app.router.add_get("/health", health)

        runner = web.AppRunner(app)
        await runner.setup()

        port = int(os.getenv("PORT", "10000"))
        site = web.TCPSite(runner, "0.0.0.0", port)
        await site.start()

        logger.info("Health server started on port %s", port)
        return runner

    except Exception:
        logger.exception("Could not start health server")
        return None

# ---------------- MAIN ----------------

async def main():
    runner = await start_health_server()

    try:
        await dp.start_polling(bot)
    finally:
        if runner:
            await runner.cleanup()
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
