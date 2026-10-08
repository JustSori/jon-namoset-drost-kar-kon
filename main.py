
import asyncio
import html
import json
import os
import subprocess
from datetime import datetime

from aiohttp import web
from aiogram import Bot, Dispatcher, F, types
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    BotCommand,
    FSInputFile,
)

# ==================================================
# SETTINGS
# ==================================================

TOKEN = os.getenv("BOT_TOKEN", "").strip()
if not TOKEN:
    raise ValueError("Please set BOT_TOKEN in your environment variables.")

ADMIN_IDS = {
    int(x.strip())
    for x in os.getenv("ADMIN_ID", "").split(",")
    if x.strip().isdigit()
}

WATERMARK_SOUND = os.getenv("WATERMARK", "on").lower()
YTDLP_COOKIES_FILE = os.getenv("YTDLP_COOKIES_FILE", "").strip()
USERS_FILE = "users.json"

bot = Bot(
    token=TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)
dp = Dispatcher()

BOT_USERNAME = ""
user_files = {}
user_settings = {}
awaiting = {}
broadcast_mode = set()
search_cache = {}
processing_users = set()


# ==================================================
# CONSISTENT MESSAGE DESIGN
# ==================================================

SEPARATOR = "━━━━━━━━━━━━━━━━━━"


def message_box(title, lines=None, footer=None):
    result = [f"🎧 <b>{title}</b>", SEPARATOR]
    if lines:
        result.extend(lines)
    if footer:
        result.extend(["", footer])
    result.append(SEPARATOR)
    return "\n".join(result)


def error_message(text):
    return message_box("Operation Failed", [f"❌ {text}"])


def loading_message(text):
    return message_box("Please Wait", [f"⏳ {text}"])


def success_message(text):
    return message_box("Success", [f"✅ {text}"])


def safe(value):
    return html.escape(str(value or ""))


# ==================================================
# EFFECTS
# ==================================================

EFFECT_TITLE = {
    "slowed": "Slowed",
    "slowed_reverb": "Slowed + Reverb",
    "nightcore": "Nightcore",
    "speedup": "Speed Up",
    "bass": "Bass Boost",
    "reverb": "Reverb",
    "8d": "8D",
}

EFFECT_EMOJI = {
    "slowed": "🐌",
    "slowed_reverb": "🎧",
    "nightcore": "🌃",
    "speedup": "⚡",
    "bass": "🔊",
    "reverb": "🌊",
    "8d": "🎩",
}

SUFFIX = {
    "slowed": "(slowed)",
    "slowed_reverb": "(slowed + reverb)",
    "speedup": "(speed up)",
    "nightcore": "(nightcore)",
    "bass": "(bass boosted)",
    "reverb": "(reverb)",
    "8d": "(8d)",
}

FILTERS = {
    "slowed": (
        "asetrate=44100*0.85,aresample=44100,"
        "loudnorm=I=-16:TP=-1.5:LRA=11,volume=1.1"
    ),
    "slowed_reverb": (
        "asetrate=44100*0.85,aresample=44100,"
        "aecho=0.8:0.9:150:0.32,"
        "aecho=0.8:0.7:500:0.25,"
        "bass=g=4:f=110:w=0.6,volume=1.15,"
        "loudnorm=I=-16:TP=-1.5:LRA=11"
    ),
    "speedup": "atempo=1.20,aresample=44100,loudnorm",
    "nightcore": "asetrate=44100*1.20,aresample=44100,volume=1.1",
    "bass": "bass=g=8:f=110:w=0.6,volume=1.2,aresample=44100",
    "reverb": (
        "aecho=0.8:0.88:120:0.35,"
        "aecho=0.8:0.6:400:0.25,aresample=44100,volume=1.1"
    ),
    "8d": "extrastereo=m=1.6,apulsator=hz=0.15,aresample=44100",
}


def format_time(seconds):
    try:
        seconds = int(seconds or 0)
    except (ValueError, TypeError):
        seconds = 0
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def calc_duration(duration, effect):
    duration = int(duration or 0)
    if effect in ("slowed", "slowed_reverb"):
        return int(duration / 0.85)
    if effect in ("speedup", "nightcore"):
        return int(duration / 1.2)
    return duration


# ==================================================
# USERS AND SETTINGS
# ==================================================

def load_users():
    try:
        with open(USERS_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)
            return set(data.get("ids", [])), data.get("dates", {})
    except (OSError, ValueError, TypeError):
        return set(), {}


all_users, first_seen = load_users()


def save_users():
    try:
        with open(USERS_FILE, "w", encoding="utf-8") as file:
            json.dump(
                {"ids": list(all_users), "dates": first_seen},
                file,
                ensure_ascii=False,
            )
    except OSError:
        pass


def add_user(uid):
    if uid not in all_users:
        all_users.add(uid)
        first_seen[str(uid)] = datetime.now().strftime("%Y-%m-%d")
        save_users()


def is_admin(uid):
    return uid in ADMIN_IDS


def get_settings(uid):
    if uid not in user_settings:
        user_settings[uid] = {"artist": None, "cover": None}
    return user_settings[uid]


# ==================================================
# KEYBOARDS
# ==================================================

def get_buttons():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🐌 Slowed", callback_data="fx:slowed"),
            InlineKeyboardButton(
                text="🎧 Slowed + Reverb",
                callback_data="fx:slowed_reverb",
            ),
        ],
        [
            InlineKeyboardButton(text="🌃 Nightcore", callback_data="fx:nightcore"),
            InlineKeyboardButton(text="⚡ Speed Up", callback_data="fx:speedup"),
        ],
        [
            InlineKeyboardButton(text="🔊 Bass Boost", callback_data="fx:bass"),
            InlineKeyboardButton(text="🌊 Reverb", callback_data="fx:reverb"),
        ],
        [InlineKeyboardButton(text="🎩 8D", callback_data="fx:8d")],
        [
            InlineKeyboardButton(
                text="✏️ تنظیم خواننده",
                callback_data="set_artist",
            ),
            InlineKeyboardButton(
                text="🖼️ تنظیم کاور",
                callback_data="set_cover",
            ),
        ],
    ])


def get_chain_buttons():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🐌 Slowed", callback_data="chain:slowed"),
            InlineKeyboardButton(
                text="🎧 Slowed + Reverb",
                callback_data="chain:slowed_reverb",
            ),
        ],
        [
            InlineKeyboardButton(
                text="🌃 Nightcore",
                callback_data="chain:nightcore",
            ),
            InlineKeyboardButton(
                text="⚡ Speed Up",
                callback_data="chain:speedup",
            ),
        ],
        [
            InlineKeyboardButton(text="🔊 Bass Boost", callback_data="chain:bass"),
            InlineKeyboardButton(text="🌊 Reverb", callback_data="chain:reverb"),
        ],
        [InlineKeyboardButton(text="🎩 8D", callback_data="chain:8d")],
        [
            InlineKeyboardButton(
                text="✅ پایان افکت‌ها و دریافت",
                callback_data="chain_done",
            )
        ],
    ])


def get_admin_panel():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 آمار ربات", callback_data="admin_stats")],
        [InlineKeyboardButton(text="📢 پیام همگانی", callback_data="admin_broadcast")],
    ])


def get_share_kb():
    if not BOT_USERNAME:
        return None

    share_url = (
        f"https://t.me/share/url?url=https://t.me/{BOT_USERNAME}"
        "&text=این آهنگو با این ربات درست کردم 🎧"
    )
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="↗️ اشتراک‌گذاری", url=share_url)],
        [
            InlineKeyboardButton(
                text="🎧 ساخت آهنگ جدید",
                url=f"https://t.me/{BOT_USERNAME}",
            )
        ],
    ])


# ==================================================
# YOUTUBE SEARCH AND DOWNLOAD
# ==================================================

def cookie_args():
    if YTDLP_COOKIES_FILE and os.path.isfile(YTDLP_COOKIES_FILE):
        return ["--cookies", YTDLP_COOKIES_FILE]
    return []


def run_search(query):
    cmd = [
        "yt-dlp",
        "--ignore-config",
        "--no-playlist",
        "--no-warnings",
        "--sleep-requests", "1",
        "--extractor-args", "youtube:player_client=tv,web_safari",
        "ytsearch5:" + query,
        "--flat-playlist",
        "--dump-json",
    ]
    cmd.extend(cookie_args())

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=45,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("yt-dlp نصب نیست.") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("زمان جست‌وجو تمام شد؛ دوباره تلاش کن.") from exc

    if result.returncode != 0 and not result.stdout.strip():
        raise RuntimeError((result.stderr or "جست‌وجو ناموفق بود.")[-1000:])

    results = []
    for line in result.stdout.splitlines():
        try:
            item = json.loads(line)
            video_id = item.get("id")
            if not video_id:
                continue

            results.append({
                "id": video_id,
                "title": str(item.get("title") or "Unknown")[:80],
                "duration": int(item.get("duration") or 0),
                "uploader": str(
                    item.get("uploader") or item.get("channel") or "YouTube"
                )[:50],
                "url": f"https://www.youtube.com/watch?v={video_id}",
            })
        except (ValueError, TypeError):
            continue

        if len(results) >= 5:
            break

    return results


def run_download(url, output_path):
    base = os.path.splitext(output_path)[0]
    template = base + ".%(ext)s"

    cmd = [
        "yt-dlp",
        "--ignore-config",
        "--no-playlist",
        "--no-warnings",
        "--no-progress",
        "--sleep-requests", "1",
        "--extractor-args", "youtube:player_client=tv,web_safari",
        "--extract-audio",
        "--audio-format", "mp3",
        "--audio-quality", "192K",
        "-o", template,
    ]
    cmd.extend(cookie_args())
    cmd.append(url)

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=180,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("yt-dlp نصب نیست یا در PATH قرار ندارد.") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("زمان دانلود تمام شد؛ دوباره تلاش کن.") from exc

    final_path = base + ".mp3"
    if result.returncode != 0 or not os.path.isfile(final_path):
        error = (result.stderr or result.stdout or "خطای نامشخص").strip()
        raise RuntimeError(error[-1000:])

    return final_path


# ==================================================
# AUDIO PROCESSING
# ==================================================

async def run_ffmpeg(cmd):
    result = await asyncio.to_thread(
        subprocess.run,
        cmd,
        capture_output=True,
        text=True,
    )
    return result


async def apply_effect_to_file(input_path, output_path, effect):
    if effect not in FILTERS:
        raise RuntimeError("افکت انتخاب‌شده معتبر نیست.")

    result = await run_ffmpeg([
        "ffmpeg", "-y",
        "-i", input_path,
        "-filter:a", FILTERS[effect],
        "-ar", "44100",
        "-ac", "2",
        "-c:a", "libmp3lame",
        "-b:a", "192k",
        output_path,
    ])

    if result.returncode != 0 or not os.path.isfile(output_path):
        raise RuntimeError("پردازش فایل صوتی ناموفق بود.")


async def fix_thumb(source, destination):
    result = await run_ffmpeg([
        "ffmpeg", "-y",
        "-i", source,
        "-vf",
        "scale=320:320:force_original_aspect_ratio=increase,crop=320:320",
        "-q:v", "4",
        destination,
    ])

    if result.returncode != 0 or not os.path.isfile(destination):
        return False

    return True


async def add_audio_watermark(input_path, output_path):
    if WATERMARK_SOUND == "off":
        if input_path != output_path:
            os.replace(input_path, output_path)
        return

    # Short audible beep mixed with the original audio.
    result = await run_ffmpeg([
        "ffmpeg", "-y",
        "-i", input_path,
        "-f", "lavfi",
        "-i", "sine=frequency=880:duration=0.25",
        "-filter_complex",
        "[1:a]volume=0.08[beep];"
        "[0:a][beep]amix=inputs=2:duration=first:dropout_transition=0[a]",
        "-map", "[a]",
        "-c:a", "libmp3lame",
        "-b:a", "192k",
        output_path,
    ])

    if result.returncode != 0 or not os.path.isfile(output_path):
        raise RuntimeError("ساخت واترمارک صوتی ناموفق بود.")


# ==================================================
# START AND HELP MESSAGES
# ==================================================

START_TXT = message_box(
    "Music Effects",
    [
        "سلام! به ربات افکت آهنگ خوش اومدی ✨",
        "",
        "🎵 <b>روش استفاده</b>",
        "• فایل صوتی رو بفرست؛ یا",
        "• اسم خواننده و آهنگ رو بنویس تا جست‌وجو کنم.",
        "",
        "🎛️ <b>Available Effects</b>",
        "🐌 Slowed  •  🎧 Slowed + Reverb",
        "🌃 Nightcore  •  ⚡ Speed Up",
        "🔊 Bass Boost  •  🌊 Reverb  •  🎩 8D",
    ],
    "👇 فایل بفرست یا اسم آهنگ رو بنویس.",
)

HELP_TXT = message_box(
    "راهنمای Music Effects",
    [
        "🔍 <b>جست‌وجوی آهنگ</b>",
        "۱. اسم خواننده و آهنگ رو بفرست.",
        "۲. یکی از نتایج رو انتخاب کن.",
        "۳. بعد از دانلود، افکت دلخواهت رو انتخاب کن.",
        "",
        "🎵 <b>فایل شخصی</b>",
        "فایل صوتی رو مستقیم برای ربات ارسال کن.",
        "",
        "🎛️ <b>چند افکت</b>",
        "بعد از افکت اول، افکت‌های بیشتری اضافه کن.",
        "در پایان، «پایان افکت‌ها و دریافت» رو بزن.",
        "",
        "🖼️ <b>تنظیمات اختیاری</b>",
        "از دکمه‌های تنظیم خواننده و کاور استفاده کن.",
        "",
        "⚠️ مدت آهنگ‌های جست‌وجوشده باید حداکثر ۱۰ دقیقه باشه.",
    ],
    "لغو عملیات: /cancel",
)


# ==================================================
# COMMAND HANDLERS
# ==================================================

@dp.message(CommandStart())
async def start_cmd(message: types.Message):
    add_user(message.from_user.id)
    await message.reply(START_TXT)


@dp.message(Command("help"))
async def help_cmd(message: types.Message):
    await message.reply(HELP_TXT)


@dp.message(Command("cancel"))
async def cancel_cmd(message: types.Message):
    uid = message.from_user.id
    broadcast_mode.discard(uid)
    awaiting.pop(uid, None)
    await message.reply(success_message("عملیات لغو شد."))


@dp.message(Command("admin"))
async def admin_cmd(message: types.Message):
    uid = message.from_user.id
    if not is_admin(uid):
        return

    await message.reply(
        message_box(
            "Admin Panel",
            [
                f"👥 تعداد کاربران: <b>{len(all_users)}</b>",
                "یکی از گزینه‌های زیر رو انتخاب کن.",
            ],
        ),
        reply_markup=get_admin_panel(),
    )


@dp.callback_query(F.data.startswith("admin_"))
async def admin_callback(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("دسترسی نداری.", show_alert=True)
        return

    await callback.answer()

    if callback.data == "admin_stats":
        today = datetime.now().strftime("%Y-%m-%d")
        today_count = sum(1 for date in first_seen.values() if date == today)

        await callback.message.edit_text(
            message_box(
                "Bot Statistics",
                [
                    f"👥 کل کاربران: <b>{len(all_users)}</b>",
                    f"🆕 کاربران امروز: <b>{today_count}</b>",
                ],
            ),
            reply_markup=get_admin_panel(),
        )

    elif callback.data == "admin_broadcast":
        broadcast_mode.add(callback.from_user.id)
        await callback.message.edit_text(
            message_box(
                "Broadcast",
                [
                    "پیامی که می‌خوای برای کاربران ارسال بشه بفرست.",
                    "برای لغو از /cancel استفاده کن.",
                ],
            )
        )


# ==================================================
# ARTIST AND COVER SETTINGS
# ==================================================

@dp.callback_query(F.data == "set_artist")
async def ask_artist(callback: types.CallbackQuery):
    await callback.answer()
    awaiting[callback.from_user.id] = "artist"
    await callback.message.reply(
        message_box(
            "تنظیم خواننده",
            ["نام خواننده‌ای که می‌خوای روی فایل ثبت بشه بفرست."],
            "لغو: /cancel",
        )
    )


@dp.callback_query(F.data == "set_cover")
async def ask_cover(callback: types.CallbackQuery):
    await callback.answer()
    awaiting[callback.from_user.id] = "cover"
    await callback.message.reply(
        message_box(
            "تنظیم کاور",
            ["عکس موردنظرت رو ارسال کن."],
            "لغو: /cancel",
        )
    )


@dp.message(F.photo)
async def handle_photo(message: types.Message):
    uid = message.from_user.id

    if uid in broadcast_mode and is_admin(uid):
        await do_broadcast(message)
        return

    if awaiting.get(uid) == "cover":
        get_settings(uid)["cover"] = message.photo[-1].file_id
        awaiting.pop(uid, None)

        await message.reply(
            success_message("کاور ذخیره شد."),
            reply_markup=get_buttons(),
        )


# ==================================================
# TEXT HANDLER: ARTIST SETTING AND SEARCH
# ==================================================

@dp.message(F.text)
async def handle_text(message: types.Message):
    uid = message.from_user.id
    text_value = (message.text or "").strip()

    if uid in broadcast_mode and is_admin(uid):
        if not text_value.startswith("/"):
            await do_broadcast(message)
        return

    if awaiting.get(uid) == "artist":
        get_settings(uid)["artist"] = text_value[:100]
        awaiting.pop(uid, None)

        await message.reply(
            success_message("نام خواننده ذخیره شد."),
            reply_markup=get_buttons(),
        )
        return

    if text_value.startswith("/") or len(text_value) < 2:
        return

    add_user(uid)

    wait = await message.reply(
        loading_message(f"در حال جست‌وجوی «{safe(text_value)}» ...")
    )

    try:
        results = await asyncio.to_thread(run_search, text_value)
    except Exception as exc:
        await wait.edit_text(error_message(safe(str(exc))))
        return

    if not results:
        await wait.edit_text(
            error_message("نتیجه‌ای پیدا نشد. نام خواننده و آهنگ رو امتحان کن.")
        )
        return

    search_cache[uid] = results
    rows = []
    lines = []

    for index, item in enumerate(results):
        title = item["title"]
        duration = format_time(item["duration"])

        rows.append([
            InlineKeyboardButton(
                text=f"{index + 1}. {title[:40]} | {duration}",
                callback_data=f"sr:{index}",
            )
        ])

        lines.append(
            f"<b>{index + 1}.</b> {safe(title)}\n"
            f"👤 {safe(item['uploader'])} | ⏱ {duration}"
        )

    await wait.edit_text(
        message_box(
            "نتایج جست‌وجو",
            [f"🔍 عبارت: <b>{safe(text_value)}</b>", "", *lines],
            "یکی از نتایج رو انتخاب کن.",
        ),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


# ==================================================
# SELECT YOUTUBE RESULT
# ==================================================

@dp.callback_query(F.data.startswith("sr:"))
async def pick_search(callback: types.CallbackQuery):
    uid = callback.from_user.id

    if uid in processing_users:
        await callback.answer("یک عملیات در حال انجامه.", show_alert=True)
        return

    results = search_cache.get(uid)
    if not results:
        await callback.answer("اول اسم آهنگ رو جست‌وجو کن.", show_alert=True)
        return

    try:
        index = int(callback.data.split(":", 1)[1])
        item = results[index]
    except (ValueError, IndexError):
        await callback.answer("این نتیجه معتبر نیست.", show_alert=True)
        return

    if item["duration"] > 600:
        await callback.answer(
            "مدت این آهنگ بیشتر از ۱۰ دقیقه است.",
            show_alert=True,
        )
        return

    await callback.answer()
    processing_users.add(uid)

    try:
        await callback.message.edit_text(
            loading_message(f"در حال دانلود {safe(item['title'])} ...")
        )

        download_path = f"dl_{uid}.mp3"
        if os.path.exists(download_path):
            os.remove(download_path)

        downloaded = await asyncio.to_thread(
            run_download,
            item["url"],
            download_path,
        )

        if downloaded != download_path:
            os.replace(downloaded, download_path)

        if os.path.getsize(download_path) > 19 * 1024 * 1024:
            os.remove(download_path)
            raise RuntimeError("حجم فایل بیشتر از حد مجاز تلگرام است.")

        user_files[uid] = {
            "file_id": None,
            "title": item["title"],
            "performer": item["uploader"],
            "duration": item["duration"],
            "thumb_id": None,
            "file_name": item["title"] + ".mp3",
            "effects": [],
            "chain_path": None,
            "base_title": item["title"],
            "base_duration": item["duration"],
            "dl_path": download_path,
            "from_search": True,
        }

        settings = get_settings(uid)
        extra = []

        if settings.get("artist"):
            extra.append(f"✏️ خواننده: <b>{safe(settings['artist'])}</b>")
        if settings.get("cover"):
            extra.append("🖼️ کاور سفارشی: <b>فعال</b>")

        await callback.message.edit_text(
            message_box(
                "دانلود کامل شد",
                [
                    f"🎵 <b>{safe(item['title'])}</b>",
                    *extra,
                    "",
                    "حالا افکت موردنظرت رو انتخاب کن.",
                ],
            ),
            reply_markup=get_buttons(),
        )

    except Exception as exc:
        await callback.message.edit_text(error_message(safe(str(exc))))
    finally:
        processing_users.discard(uid)


# ==================================================
# RECEIVE AUDIO, VOICE AND AUDIO DOCUMENTS
# ==================================================

@dp.message(F.audio | F.voice | F.document)
async def handle_music(message: types.Message):
    uid = message.from_user.id

    if uid in broadcast_mode and is_admin(uid):
        await do_broadcast(message)
        return

    file_id = None
    title = None
    performer = None
    duration = 0
    thumb_id = None
    file_name = "music.mp3"

    if message.audio:
        audio = message.audio
        file_id = audio.file_id
        title = audio.title
        performer = audio.performer
        duration = audio.duration or 0
        file_name = audio.file_name or "music.mp3"
        if audio.thumbnail:
            thumb_id = audio.thumbnail.file_id

    elif message.voice:
        file_id = message.voice.file_id
        duration = message.voice.duration or 0
        file_name = "voice.ogg"

    elif message.document:
        document = message.document
        filename = document.file_name or ""
        mime_type = document.mime_type or ""

        allowed_extensions = (
            ".mp3", ".m4a", ".wav", ".ogg",
            ".flac", ".aac", ".wma", ".opus",
        )

        if "audio" in mime_type or filename.lower().endswith(allowed_extensions):
            file_id = document.file_id
            file_name = filename or "music.mp3"
            if document.thumbnail:
                thumb_id = document.thumbnail.file_id

    if not file_id:
        await message.reply(
            error_message("این فایل صوتی نیست. فایل صوتی بفرست.")
        )
        return

    add_user(uid)

    base_title = title or os.path.splitext(file_name)[0]

    user_files[uid] = {
        "file_id": file_id,
        "title": title,
        "performer": performer,
        "duration": duration,
        "thumb_id": thumb_id,
        "file_name": file_name,
        "effects": [],
        "chain_path": None,
        "base_title": base_title,
        "base_duration": duration,
        "from_search": False,
    }

    settings = get_settings(uid)
    extra = []

    if settings.get("artist"):
        extra.append(f"✏️ خواننده: <b>{safe(settings['artist'])}</b>")
    if settings.get("cover"):
        extra.append("🖼️ کاور سفارشی: <b>فعال</b>")

    await message.reply(
        message_box(
            "فایل دریافت شد",
            [
                f"🎵 <b>{safe(base_title)}</b>",
                *extra,
                "",
                "افکت موردنظرت رو انتخاب کن.",
            ],
        ),
        reply_markup=get_buttons(),
    )


# ==================================================
# ADMIN BROADCAST
# ==================================================

@dp.message(F.video)
async def handle_video(message: types.Message):
    uid = message.from_user.id
    if uid in broadcast_mode and is_admin(uid):
        await do_broadcast(message)


async def do_broadcast(message: types.Message):
    uid = message.from_user.id

    if not is_admin(uid):
        return

    broadcast_mode.discard(uid)

    status = await message.reply(
        loading_message(f"در حال ارسال پیام به {len(all_users)} کاربر...")
    )

    success_count = 0
    fail_count = 0

    for target_uid in list(all_users):
        try:
            await bot.copy_message(
                chat_id=target_uid,
                from_chat_id=message.chat.id,
                message_id=message.message_id,
            )
            success_count += 1
        except Exception:
            fail_count += 1

        if (success_count + fail_count) % 20 == 0:
            await asyncio.sleep(0.5)

    await status.edit_text(
        message_box(
            "Broadcast Complete",
            [
                f"✅ ارسال موفق: <b>{success_count}</b>",
                f"❌ ارسال ناموفق: <b>{fail_count}</b>",
            ],
        ),
        reply_markup=get_admin_panel(),
    )


# ==================================================
# PREPARE INPUT FOR EFFECTS
# ==================================================

async def prepare_chain_input(uid):
    info = user_files[uid]

    if info.get("chain_path"):
        return info["chain_path"]

    if info.get("from_search"):
        return info.get("dl_path")

    if info.get("file_id"):
        input_path = f"input_{uid}.audio"

        telegram_file = await bot.get_file(info["file_id"])
        await bot.download_file(telegram_file.file_path, input_path)

        return input_path

    return None


# ==================================================
# APPLY FIRST EFFECT
# ==================================================

@dp.callback_query(F.data.startswith("fx:"))
async def first_effect(callback: types.CallbackQuery):
    uid = callback.from_user.id

    if uid in processing_users:
        await callback.answer("یک عملیات در حال انجامه.", show_alert=True)
        return

    info = user_files.get(uid)
    if not info:
        await callback.answer("اول فایل بفرست یا آهنگ جست‌وجو کن.", show_alert=True)
        return

    effect = callback.data.split(":", 1)[1]
    if effect not in FILTERS:
        await callback.answer("افکت معتبر نیست.", show_alert=True)
        return

    await callback.answer()
    processing_users.add(uid)

    try:
        await callback.message.edit_text(
            loading_message(f"در حال اعمال {EFFECT_TITLE[effect]} ...")
        )

        source = await prepare_chain_input(uid)
        if not source or not os.path.isfile(source):
            raise RuntimeError("فایل پیدا نشد؛ دوباره ارسالش کن.")

        output_path = f"chain_{uid}.mp3"
        await apply_effect_to_file(source, output_path, effect)

        if source.startswith("input_") and os.path.exists(source):
            os.remove(source)

        info["effects"] = [effect]
        info["chain_path"] = output_path

        await callback.message.edit_text(
            message_box(
                "افکت اعمال شد",
                [
                    f"{EFFECT_EMOJI[effect]} <b>{EFFECT_TITLE[effect]}</b>",
                    "می‌تونی افکت‌های بیشتری اضافه کنی یا فایل رو دریافت کنی.",
                ],
            ),
            reply_markup=get_chain_buttons(),
        )

    except Exception as exc:
        await callback.message.edit_text(error_message(safe(str(exc))))
    finally:
        processing_users.discard(uid)


# ==================================================
# ADD ANOTHER EFFECT
# ==================================================

@dp.callback_query(F.data.startswith("chain:"))
async def chain_effect(callback: types.CallbackQuery):
    uid = callback.from_user.id

    if uid in processing_users:
        await callback.answer("یک عملیات در حال انجامه.", show_alert=True)
        return

    info = user_files.get(uid)
    if not info or not info.get("chain_path"):
        await callback.answer("فایلی برای پردازش وجود نداره.", show_alert=True)
        return

    effect = callback.data.split(":", 1)[1]
    if effect not in FILTERS:
        await callback.answer("افکت معتبر نیست.", show_alert=True)
        return

    if effect in info["effects"]:
        await callback.answer("این افکت قبلاً اضافه شده.", show_alert=True)
        return

    await callback.answer()
    processing_users.add(uid)

    old_path = info["chain_path"]
    new_path = f"chain_{uid}_next.mp3"

    try:
        await callback.message.edit_text(
            loading_message(f"در حال افزودن {EFFECT_TITLE[effect]} ...")
        )

        await apply_effect_to_file(old_path, new_path, effect)

        if os.path.exists(old_path):
            os.remove(old_path)

        info["chain_path"] = new_path
        info["effects"].append(effect)

        labels = [
            f"{EFFECT_EMOJI[item]} {EFFECT_TITLE[item]}"
            for item in info["effects"]
        ]

        await callback.message.edit_text(
            message_box(
                "افکت‌ها اعمال شدند",
                [
                    " + ".join(labels),
                    "",
                    "می‌تونی افکت دیگری اضافه کنی یا فایل رو دریافت کنی.",
                ],
            ),
            reply_markup=get_chain_buttons(),
        )

    except Exception as exc:
        await callback.message.edit_text(error_message(safe(str(exc))))
    finally:
        processing_users.discard(uid)


# ==================================================
# SEND FINAL AUDIO
# ==================================================

async def send_final(uid, chat_id, reply_to):
    info = user_files[uid]
    settings = get_settings(uid)

    source_path = info.get("chain_path")
    if not source_path or not os.path.isfile(source_path):
        raise RuntimeError("فایل پردازش‌شده پیدا نشد.")

    final_path = f"output_{uid}.mp3"
    if os.path.exists(final_path):
        os.remove(final_path)

    if WATERMARK_SOUND == "off":
        os.replace(source_path, final_path)
    else:
        await add_audio_watermark(source_path, final_path)
        if os.path.exists(source_path):
            os.remove(source_path)

    effects = info.get("effects", [])
    base_title = info.get("base_title") or "Music"
    suffix = " ".join(SUFFIX.get(effect, "") for effect in effects).strip()

    if suffix and not base_title.lower().endswith(suffix.lower()):
        title = f"{base_title} {suffix}"
    else:
        title = base_title

    performer = (
        settings.get("artist")
        or info.get("performer")
        or "Unknown Artist"
    )

    safe_filename = "".join(
        char for char in title
        if char not in '/\\:*?"<>|'
    ).strip() or "music"

    duration = info.get("base_duration", 0)
    for effect in effects:
        duration = calc_duration(duration, effect)

    thumbnail_file = None
    thumb_source = f"thumb_{uid}.jpg"
    thumb_fixed = f"thumb_{uid}_fixed.jpg"

    try:
        cover_id = settings.get("cover") or info.get("thumb_id")
        if cover_id:
            telegram_file = await bot.get_file(cover_id)
            await bot.download_file(telegram_file.file_path, thumb_source)

            if await fix_thumb(thumb_source, thumb_fixed):
                thumbnail_file = FSInputFile(thumb_fixed)
            elif os.path.isfile(thumb_source):
                thumbnail_file = FSInputFile(thumb_source)
    except Exception:
        thumbnail_file = None

    effect_text = " + ".join(
        EFFECT_TITLE.get(effect, effect) for effect in effects
    )
    emoji = EFFECT_EMOJI.get(effects[-1], "🎧") if effects else "🎧"
    watermark_text = f"\n🤖 @{BOT_USERNAME}" if BOT_USERNAME else ""

    caption = message_box(
        f"{emoji} {safe(effect_text)}",
        [
            f"🎵 <b>{safe(title)}</b>",
            f"👤 {safe(performer)}",
            f"⏱️ {format_time(duration)}",
            watermark_text.strip() if watermark_text else "",
        ],
        "🎧 Enjoy your music!",
    )

    audio_file = FSInputFile(final_path, filename=f"{safe_filename}.mp3")

    await bot.send_audio(
        chat_id=chat_id,
        audio=audio_file,
        title=title[:64],
        performer=performer[:64],
        duration=duration or None,
        thumbnail=thumbnail_file,
        caption=caption[:1024],
        reply_markup=get_share_kb(),
    )

    cleanup_paths = [
        thumb_source,
        thumb_fixed,
        final_path,
        info.get("dl_path"),
    ]

    for path in cleanup_paths:
        try:
            if path and os.path.isfile(path):
                os.remove(path)
        except OSError:
            pass

    try:
        await reply_to.delete()
    except Exception:
        pass

    user_files.pop(uid, None)


# ==================================================
# FINISH EFFECT CHAIN
# ==================================================

@dp.callback_query(F.data == "chain_done")
async def chain_done(callback: types.CallbackQuery):
    uid = callback.from_user.id

    if uid in processing_users:
        await callback.answer("در حال پردازش؛ کمی صبر کن.", show_alert=True)
        return

    info = user_files.get(uid)
    if not info or not info.get("chain_path"):
        await callback.answer("فایلی برای دریافت وجود نداره.", show_alert=True)
        return

    await callback.answer()
    processing_users.add(uid)

    try:
        await callback.message.edit_text(
            loading_message("در حال آماده‌سازی فایل نهایی...")
        )
        await send_final(uid, callback.message.chat.id, callback.message)

    except Exception as exc:
        await callback.message.edit_text(error_message(safe(str(exc))))
    finally:
        processing_users.discard(uid)


# ==================================================
# RENDER WEB SERVER AND STARTUP
# ==================================================

async def health_check(request):
    return web.Response(text="Music Effects Bot is running.")


async def main():
    global BOT_USERNAME

    try:
        me = await bot.get_me()
        BOT_USERNAME = me.username or ""
    except Exception as exc:
        print(f"Could not get bot username: {exc}")

    try:
        await bot.set_my_commands([
            BotCommand(command="start", description="شروع ربات"),
            BotCommand(command="help", description="راهنما"),
            BotCommand(command="cancel", description="لغو عملیات"),
        ])
    except Exception as exc:
        print(f"Could not set commands: {exc}")

    app = web.Application()
    app.router.add_get("/", health_check)

    runner = web.AppRunner(app)
    await runner.setup()

    port = int(os.getenv("PORT", "10000"))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

    print(f"Music Effects Bot started on port {port}")

    try:
        await dp.start_polling(bot)
    finally:
        await runner.cleanup()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
