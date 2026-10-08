
import asyncio
import os
import json
import html
import subprocess
from datetime import datetime

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    BotCommand,
    FSInputFile,
)
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiohttp import web


# =========================================================
# CONFIG
# =========================================================

TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise ValueError("BOT_TOKEN ست نشده!")

ADMIN_IDS = {
    int(x.strip())
    for x in os.getenv("ADMIN_ID", "").split(",")
    if x.strip().isdigit()
}

WATERMARK_SOUND = os.getenv("WATERMARK", "on").lower()
YTDLP_COOKIES_FILE = os.getenv("YTDLP_COOKIES_FILE", "").strip()

bot = Bot(
    token=TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)

dp = Dispatcher()

user_files = {}
user_settings = {}
user_languages = {}
awaiting = {}
broadcast_mode = set()
search_cache = {}

BOT_USERNAME = ""
USERS_FILE = "users.json"


# =========================================================
# USERS
# =========================================================

def load_users():
    try:
        if os.path.exists(USERS_FILE):
            with open(USERS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)

            return (
                set(data.get("ids", [])),
                data.get("dates", {}),
            )
    except Exception:
        pass

    return set(), {}


def save_users():
    try:
        with open(USERS_FILE, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "ids": list(all_users),
                    "dates": first_seen,
                },
                f,
                ensure_ascii=False,
            )
    except Exception:
        pass


all_users, first_seen = load_users()


def is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS


def add_user(uid: int):
    if uid not in all_users:
        all_users.add(uid)
        first_seen[str(uid)] = datetime.now().strftime("%Y-%m-%d")
        save_users()


def get_settings(uid: int):
    if uid not in user_settings:
        user_settings[uid] = {
            "artist": None,
            "cover": None,
        }

    return user_settings[uid]


def get_lang(uid: int) -> str:
    return user_languages.get(uid, "fa")


# =========================================================
# MESSAGE DESIGN
# =========================================================

def esc(value) -> str:
    return html.escape(str(value or ""))


def make_message(title: str, body: str) -> str:
    return (
        f"╭── 🎧 <b>{title}</b> ──╮\n"
        f"{body}\n"
        "╰──────────────────╯"
    )


TEXTS = {
    "fa": {
        "start": (
            "سلام! به ربات افکت آهنگ خوش اومدی ✨\n\n"
            "🎵 فایل صوتی بفرست یا اسم آهنگ و خواننده رو بنویس.\n\n"
            "🎛️ افکت‌ها:\n"
            "🐌 Slowed  •  🎧 Slowed + Reverb\n"
            "🌃 Nightcore  •  ⚡ Speed Up\n"
            "🔊 Bass Boost  •  🌊 Reverb  •  🎩 8D\n\n"
            "👇 برای شروع، آهنگت رو بفرست."
        ),
        "help": (
            "🔍 جست‌وجو: اسم آهنگ یا خواننده رو بفرست.\n"
            "🎵 فایل شخصی: فایل صوتی رو ارسال کن.\n"
            "🎛️ چند افکت: افکت‌های دلخواهت رو به‌ترتیب اضافه کن.\n"
            "🖼️ کاور و خواننده: از تنظیمات استفاده کن.\n\n"
            "⏱️ مدت آهنگ برای جست‌وجو حداکثر ۱۰ دقیقه است.\n"
            "لغو عملیات: /cancel"
        ),
        "choose_lang": "🌐 زبان ربات رو انتخاب کن:",
        "searching": "🔍 در حال جست‌وجو برای:",
        "not_found": "❌ آهنگی پیدا نشد. نام خواننده و آهنگ رو امتحان کن.",
        "downloaded": "✅ آهنگ دریافت شد!",
        "choose_fx": "👇 افکت موردنظرت رو انتخاب کن.",
        "processing": "🎛️ در حال اعمال افکت...\n⏳ لطفاً صبر کن.",
        "adding_fx": "🔗 در حال افزودن افکت...",
        "another_fx": "افکت دیگه‌ای هم اضافه کنم؟",
        "done": "✅ پردازش کامل شد!",
        "received": "✅ فایل صوتی دریافت شد!",
        "not_audio": "❌ لطفاً یک فایل صوتی معتبر بفرست.",
        "cancel": "❌ عملیات لغو شد.",
        "artist_prompt": "✏️ اسم خواننده‌ای که می‌خوای روی فایل باشه رو بفرست.",
        "cover_prompt": "🖼️ عکس کاور موردنظرت رو بفرست.",
        "artist_saved": "✅ نام خواننده ذخیره شد.",
        "cover_saved": "✅ کاور ذخیره شد.",
        "error": "❌ خطا:",
        "too_long": "❌ مدت آهنگ بیشتر از ۱۰ دقیقه است.",
        "too_large": "❌ حجم فایل بیشتر از حد مجاز است.",
        "choose_result": "👇 یکی از نتایج رو انتخاب کن:",
        "search_failed": "❌ جست‌وجو ناموفق بود.",
        "download_failed": "❌ دانلود ناموفق بود.",
        "no_file": "❌ ابتدا یک آهنگ ارسال کن.",
        "duplicate_fx": "این افکت قبلاً اضافه شده.",
        "admin_denied": "دسترسی نداری.",
        "stats": "📊 آمار ربات",
        "broadcast": "📢 پیام همگانی",
        "send_broadcast": "پیامت رو برای ارسال همگانی بفرست.",
        "broadcast_done": "ارسال همگانی تمام شد.",
        "saved": "ذخیره شد.",
        "unknown_artist": "خواننده نامشخص",
        "share": "این آهنگو با این ربات درست کردم 🎧",
        "headphones": "🎧 با هدفون گوش کن",
    },
    "en": {
        "start": (
            "Welcome to Music Effects! ✨\n\n"
            "🎵 Send an audio file or type a song and artist name.\n\n"
            "🎛️ Available effects:\n"
            "🐌 Slowed  •  🎧 Slowed + Reverb\n"
            "🌃 Nightcore  •  ⚡ Speed Up\n"
            "🔊 Bass Boost  •  🌊 Reverb  •  🎩 8D\n\n"
            "👇 Send a song to get started."
        ),
        "help": (
            "🔍 Search: type a song or artist name.\n"
            "🎵 Personal file: send an audio file.\n"
            "🎛️ Multiple effects: add effects one by one.\n"
            "🖼️ Cover and artist: use the settings buttons.\n\n"
            "⏱️ Search supports songs up to 10 minutes.\n"
            "Cancel an operation: /cancel"
        ),
        "choose_lang": "🌐 Choose your language:",
        "searching": "🔍 Searching for:",
        "not_found": "❌ No songs found. Try the artist and song name.",
        "downloaded": "✅ Song downloaded!",
        "choose_fx": "👇 Choose your desired effect.",
        "processing": "🎛️ Applying effect...\n⏳ Please wait.",
        "adding_fx": "🔗 Adding effect...",
        "another_fx": "Would you like to add another effect?",
        "done": "✅ Processing completed!",
        "received": "✅ Audio file received!",
        "not_audio": "❌ Please send a valid audio file.",
        "cancel": "❌ Operation cancelled.",
        "artist_prompt": "✏️ Send the artist name for the output file.",
        "cover_prompt": "🖼️ Send the cover image you want to use.",
        "artist_saved": "✅ Artist name saved.",
        "cover_saved": "✅ Cover saved.",
        "error": "❌ Error:",
        "too_long": "❌ The song is longer than 10 minutes.",
        "too_large": "❌ The file exceeds the allowed size.",
        "choose_result": "👇 Choose one of the results:",
        "search_failed": "❌ Search failed.",
        "download_failed": "❌ Download failed.",
        "no_file": "❌ Please send a song first.",
        "duplicate_fx": "This effect has already been added.",
        "admin_denied": "Access denied.",
        "stats": "📊 Bot statistics",
        "broadcast": "📢 Broadcast",
        "send_broadcast": "Send the message you want to broadcast.",
        "broadcast_done": "Broadcast completed.",
        "saved": "Saved.",
        "unknown_artist": "Unknown Artist",
        "share": "I made this song with this bot 🎧",
        "headphones": "🎧 Listen with headphones",
    },
}


def tr(uid: int, key: str) -> str:
    lang = get_lang(uid)
    return TEXTS.get(lang, TEXTS["fa"]).get(key, key)


# =========================================================
# EFFECTS
# =========================================================

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
        "asetrate=44100*0.85,"
        "aresample=44100"
    ),
    "slowed_reverb": (
        "asetrate=44100*0.85,"
        "aresample=44100,"
        "aecho=0.8:0.9:150:0.32,"
        "aecho=0.8:0.7:500:0.25,"
        "bass=g=3:f=110:w=0.6"
    ),
    "speedup": "atempo=1.20,aresample=44100",
    "nightcore": "asetrate=44100*1.20,aresample=44100",
    "bass": "bass=g=5:f=110:w=0.6,aresample=44100",
    "reverb": (
        "aecho=0.8:0.88:120:0.30,"
        "aecho=0.8:0.6:400:0.20,"
        "aresample=44100"
    ),
    "8d": (
        "extrastereo=m=1.4,"
        "apulsator=hz=0.15,"
        "aresample=44100"
    ),
}

EFFECT_EMOJI = {
    "slowed": "🐌",
    "slowed_reverb": "🎧",
    "speedup": "⚡",
    "nightcore": "🌃",
    "bass": "🔊",
    "reverb": "🌊",
    "8d": "🎩",
}

EFFECT_STYLED = {
    "slowed": "Slowed",
    "slowed_reverb": "Slowed + Reverb",
    "speedup": "Speed Up",
    "nightcore": "Nightcore",
    "bass": "Bass Boost",
    "reverb": "Reverb",
    "8d": "8D",
}


def format_time(seconds: int) -> str:
    try:
        seconds = int(seconds or 0)
    except (TypeError, ValueError):
        seconds = 0

    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def calc_duration(base: int, effect: str) -> int:
    if effect in ("slowed", "slowed_reverb"):
        return int(base / 0.85) if base else 0

    if effect in ("speedup", "nightcore"):
        return int(base / 1.2) if base else 0

    return base or 0


def get_buttons(uid: int):
    lang = get_lang(uid)

    if lang == "en":
        artist_text = "✏️ Set artist"
        cover_text = "🖼️ Set cover"
    else:
        artist_text = "✏️ تنظیم خواننده"
        cover_text = "🖼️ تنظیم کاور"

    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="🐌 Slowed",
                callback_data="fx:slowed",
            ),
            InlineKeyboardButton(
                text="🎧 Slowed + Reverb",
                callback_data="fx:slowed_reverb",
            ),
        ],
        [
            InlineKeyboardButton(
                text="🌃 Nightcore",
                callback_data="fx:nightcore",
            ),
            InlineKeyboardButton(
                text="⚡ Speed Up",
                callback_data="fx:speedup",
            ),
        ],
        [
            InlineKeyboardButton(
                text="🔊 Bass Boost",
                callback_data="fx:bass",
            ),
            InlineKeyboardButton(
                text="🌊 Reverb",
                callback_data="fx:reverb",
            ),
        ],
        [
            InlineKeyboardButton(
                text="🎩 8D",
                callback_data="fx:8d",
            ),
        ],
        [
            InlineKeyboardButton(
                text=artist_text,
                callback_data="set_artist",
            ),
            InlineKeyboardButton(
                text=cover_text,
                callback_data="set_cover",
            ),
        ],
        [
            InlineKeyboardButton(
                text="🌐 Language / زبان",
                callback_data="language",
            ),
        ],
    ])


def get_chain_buttons(uid: int):
    lang = get_lang(uid)

    done_text = (
        "✅ Finish and receive"
        if lang == "en"
        else "✅ پایان افکت‌ها و دریافت"
    )

    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="🐌 Slowed",
                callback_data="chain:slowed",
            ),
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
            InlineKeyboardButton(
                text="🔊 Bass Boost",
                callback_data="chain:bass",
            ),
            InlineKeyboardButton(
                text="🌊 Reverb",
                callback_data="chain:reverb",
            ),
        ],
        [
            InlineKeyboardButton(
                text="🎩 8D",
                callback_data="chain:8d",
            ),
        ],
        [
            InlineKeyboardButton(
                text=done_text,
                callback_data="chain_done",
            ),
        ],
    ])


def get_language_buttons():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="🇮🇷 فارسی",
                callback_data="lang:fa",
            ),
            InlineKeyboardButton(
                text="🇬🇧 English",
                callback_data="lang:en",
            ),
        ],
    ])


def get_admin_panel():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="📊 آمار ربات",
                callback_data="admin_stats",
            ),
        ],
        [
            InlineKeyboardButton(
                text="📢 پیام همگانی",
                callback_data="admin_broadcast",
            ),
        ],
    ])


def get_share_kb(uid: int):
    if not BOT_USERNAME:
        return None

    share_text = tr(uid, "share")

    share_url = (
        "https://t.me/share/url"
        f"?url=https://t.me/{BOT_USERNAME}"
        f"&text={share_text.replace(' ', '%20')}"
    )

    new_url = f"https://t.me/{BOT_USERNAME}"

    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="↗️ Share / اشتراک",
                url=share_url,
            ),
        ],
        [
            InlineKeyboardButton(
                text="🎧 New Song / آهنگ جدید",
                url=new_url,
            ),
        ],
    ])


# =========================================================
# YOUTUBE SEARCH
# =========================================================

def run_search(query: str):
    cmd = [
        "yt-dlp",
        "--ignore-config",
        "--no-playlist",
        "--no-warnings",
        "--sleep-requests", "1",
        "--extractor-args",
        "youtube:player_client=tv,web_safari",
        "ytsearch5:" + query,
        "--flat-playlist",
        "--dump-json",
    ]

    if (
        YTDLP_COOKIES_FILE
        and os.path.isfile(YTDLP_COOKIES_FILE)
    ):
        cmd.extend(["--cookies", YTDLP_COOKIES_FILE])

    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=45,
    )

    if result.returncode != 0 and not result.stdout.strip():
        raise RuntimeError(
            (result.stderr or "YouTube search failed")[-1000:]
        )

    results = []

    for line in result.stdout.splitlines():
        try:
            data = json.loads(line)

            video_id = data.get("id", "")
            if not video_id:
                continue

            url = data.get("url") or (
                f"https://www.youtube.com/watch?v={video_id}"
            )

            if "://" not in url:
                url = f"https://www.youtube.com/watch?v={video_id}"

            results.append({
                "id": video_id,
                "title": str(data.get("title") or "Unknown")[:80],
                "duration": int(data.get("duration") or 0),
                "uploader": str(
                    data.get("uploader")
                    or data.get("channel")
                    or ""
                )[:50],
                "url": url,
            })

            if len(results) >= 5:
                break

        except (ValueError, TypeError):
            continue

    return results


# =========================================================
# YOUTUBE DOWNLOAD
# =========================================================

def run_download(url: str, out_path: str):
    base = os.path.splitext(out_path)[0]
    template = base + ".%(ext)s"

    cmd = [
        "yt-dlp",
        "--ignore-config",
        "--no-playlist",
        "--no-warnings",
        "--no-progress",
        "--sleep-requests", "1",
        "--extractor-args",
        "youtube:player_client=tv,web_safari",
        "--extract-audio",
        "--audio-format", "mp3",
        "--audio-quality", "192K",
        "-o", template,
    ]

    if (
        YTDLP_COOKIES_FILE
        and os.path.isfile(YTDLP_COOKIES_FILE)
    ):
        cmd.extend(["--cookies", YTDLP_COOKIES_FILE])

    cmd.append(url)

    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=180,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            "yt-dlp نصب نیست یا در PATH قرار ندارد."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            "زمان دانلود تمام شد؛ دوباره تلاش کن."
        ) from exc

    final_path = base + ".mp3"

    if result.returncode != 0 or not os.path.isfile(final_path):
        error = (
            result.stderr
            or result.stdout
            or "Unknown yt-dlp error"
        ).strip()

        raise RuntimeError(error[-1200:])

    return final_path


# =========================================================
# AUDIO PROCESSING
# =========================================================

async def apply_effect_to_file(
    inp: str,
    outp: str,
    effect: str,
):
    if effect not in FILTERS:
        raise RuntimeError("افکت انتخاب‌شده معتبر نیست.")

    # Normalize loudness after applying the selected effect.
    # True peak limit helps reduce clipping.
    audio_filter = (
        f"{FILTERS[effect]},"
        "loudnorm=I=-14:TP=-1.0:LRA=11"
    )

    cmd = [
        "ffmpeg",
        "-y",
        "-i", inp,
        "-af", audio_filter,
        "-ar", "44100",
        "-ac", "2",
        "-c:a", "libmp3lame",
        "-b:a", "192k",
        outp,
    ]

    result = await asyncio.to_thread(
        subprocess.run,
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    if result.returncode != 0 or not os.path.isfile(outp):
        raise RuntimeError(
            "پردازش صدا ناموفق بود: "
            + (result.stderr or "خطای نامشخص")[-700:]
        )


async def add_audio_watermark(inp: str, outp: str):
    if WATERMARK_SOUND == "off":
        if inp != outp:
            os.replace(inp, outp)
        return

    temp_output = outp + ".wm.mp3"

    cmd = [
        "ffmpeg",
        "-y",
        "-i", inp,
        "-filter_complex",
        (
            "[0:a]volume=1.0[main];"
            "sine=frequency=880:duration=0.25,"
            "volume=0.04[beep];"
            "[main][beep]amix=inputs=2:"
            "duration=first:dropout_transition=0,"
            "loudnorm=I=-14:TP=-1.0:LRA=11[a]"
        ),
        "-map", "[a]",
        "-ar", "44100",
        "-ac", "2",
        "-c:a", "libmp3lame",
        "-b:a", "192k",
        temp_output,
    ]

    result = await asyncio.to_thread(
        subprocess.run,
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    if result.returncode == 0 and os.path.isfile(temp_output):
        os.replace(temp_output, outp)
    else:
        if os.path.exists(temp_output):
            os.remove(temp_output)


async def fix_thumb(src: str, dst: str) -> bool:
    cmd = [
        "ffmpeg", "-y",
        "-i", src,
        "-vf",
        (
            "scale=320:320:"
            "force_original_aspect_ratio=increase,"
            "crop=320:320"
        ),
        "-q:v", "4",
        dst,
    ]

    result = await asyncio.to_thread(
        subprocess.run,
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    return result.returncode == 0 and os.path.exists(dst)


# =========================================================
# START / HELP / LANGUAGE
# =========================================================

@dp.message(CommandStart())
async def start_cmd(message: types.Message):
    uid = message.from_user.id
    add_user(uid)

    body = tr(uid, "start")

    await message.reply(
        make_message("Music Effects", body),
        reply_markup=get_buttons(uid),
    )


@dp.message(Command("help"))
async def help_cmd(message: types.Message):
    uid = message.from_user.id

    await message.reply(
        make_message("Help / راهنما", tr(uid, "help")),
        reply_markup=get_buttons(uid),
    )


@dp.callback_query(F.data == "language")
async def language_menu(callback: types.CallbackQuery):
    await callback.answer()

    await callback.message.reply(
        make_message(
            "Language / زبان",
            tr(callback.from_user.id, "choose_lang"),
        ),
        reply_markup=get_language_buttons(),
    )


@dp.callback_query(F.data.startswith("lang:"))
async def set_language(callback: types.CallbackQuery):
    lang = callback.data.split(":", 1)[1]

    if lang not in ("fa", "en"):
        await callback.answer()
        return

    user_languages[callback.from_user.id] = lang

    await callback.answer(
        "Language updated!" if lang == "en" else "زبان تغییر کرد!"
    )

    await callback.message.edit_text(
        make_message(
            "Music Effects",
            tr(callback.from_user.id, "start"),
        ),
        reply_markup=get_buttons(callback.from_user.id),
    )


# =========================================================
# ADMIN
# =========================================================

@dp.message(Command("admin"))
async def admin_cmd(message: types.Message):
    uid = message.from_user.id

    if not is_admin(uid):
        await message.reply(tr(uid, "admin_denied"))
        return

    await message.reply(
        make_message(
            "Admin Panel",
            f"👥 Users: <b>{len(all_users)}</b>",
        ),
        reply_markup=get_admin_panel(),
    )


@dp.callback_query(F.data.startswith("admin_"))
async def admin_callback(callback: types.CallbackQuery):
    uid = callback.from_user.id

    if not is_admin(uid):
        await callback.answer(
            tr(uid, "admin_denied"),
            show_alert=True,
        )
        return

    await callback.answer()

    if callback.data == "admin_stats":
        today = datetime.now().strftime("%Y-%m-%d")

        today_count = sum(
            1 for date in first_seen.values()
            if date == today
        )

        body = (
            f"👥 Total users: <b>{len(all_users)}</b>\n"
            f"🆕 Today: <b>{today_count}</b>"
        )

        await callback.message.edit_text(
            make_message("Statistics", body),
            reply_markup=get_admin_panel(),
        )

    elif callback.data == "admin_broadcast":
        broadcast_mode.add(uid)

        await callback.message.edit_text(
            make_message(
                "Broadcast",
                tr(uid, "send_broadcast")
                + "\n\n/cancel",
            )
        )


@dp.message(Command("cancel"))
async def cancel_cmd(message: types.Message):
    uid = message.from_user.id

    broadcast_mode.discard(uid)
    awaiting.pop(uid, None)

    await message.reply(
        make_message("Music Effects", tr(uid, "cancel"))
    )


# =========================================================
# ARTIST / COVER SETTINGS
# =========================================================

@dp.callback_query(F.data == "set_artist")
async def ask_artist(callback: types.CallbackQuery):
    await callback.answer()

    uid = callback.from_user.id
    awaiting[uid] = "artist"

    await callback.message.reply(
        make_message("Artist Settings", tr(uid, "artist_prompt"))
    )


@dp.callback_query(F.data == "set_cover")
async def ask_cover(callback: types.CallbackQuery):
    await callback.answer()

    uid = callback.from_user.id
    awaiting[uid] = "cover"

    await callback.message.reply(
        make_message("Cover Settings", tr(uid, "cover_prompt"))
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
            make_message("Music Effects", tr(uid, "cover_saved")),
            reply_markup=get_buttons(uid),
        )


# =========================================================
# TEXT / SEARCH
# =========================================================

@dp.message(F.text)
async def handle_text(message: types.Message):
    uid = message.from_user.id
    txt = (message.text or "").strip()

    if uid in broadcast_mode and is_admin(uid):
        if not txt.startswith("/"):
            await do_broadcast(message)
        return

    if awaiting.get(uid) == "artist":
        get_settings(uid)["artist"] = txt[:100]
        awaiting.pop(uid, None)

        await message.reply(
            make_message("Music Effects", tr(uid, "artist_saved")),
            reply_markup=get_buttons(uid),
        )
        return

    if txt.startswith("/"):
        return

    if len(txt) < 2:
        return

    add_user(uid)

    wait = await message.reply(
        make_message(
            "Search",
            f"{tr(uid, 'searching')}\n🎵 <b>{esc(txt)}</b>\n⏳",
        )
    )

    try:
        results = await asyncio.to_thread(run_search, txt)

    except Exception as exc:
        await wait.edit_text(
            make_message(
                "Search",
                f"{tr(uid, 'search_failed')}\n"
                f"<code>{esc(str(exc)[-500:])}</code>",
            )
        )
        return

    if not results:
        await wait.edit_text(
            make_message("Search", tr(uid, "not_found"))
        )
        return

    search_cache[uid] = results
    rows = []

    for index, item in enumerate(results):
        title = item["title"][:38]

        rows.append([
            InlineKeyboardButton(
                text=(
                    f"{index + 1}. {title} "
                    f"⏱ {format_time(item['duration'])}"
                ),
                callback_data=f"sr:{index}",
            )
        ])

    await wait.edit_text(
        make_message(
            "Search Results",
            "\n".join(
                f"🎵 <b>{index + 1}.</b> {esc(item['title'])}\n"
                f"👤 {esc(item['uploader'])} "
                f"• ⏱ {format_time(item['duration'])}"
                for index, item in enumerate(results)
            )
            + "\n\n"
            + tr(uid, "choose_result"),
        ),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


# =========================================================
# SEARCH RESULT / DOWNLOAD
# =========================================================

@dp.callback_query(F.data.startswith("sr:"))
async def pick_search(callback: types.CallbackQuery):
    uid = callback.from_user.id

    if uid not in search_cache:
        await callback.answer(
            tr(uid, "no_file"),
            show_alert=True,
        )
        return

    try:
        index = int(callback.data.split(":", 1)[1])
        results = search_cache[uid]
        item = results[index]
    except (ValueError, IndexError):
        await callback.answer("Invalid selection", show_alert=True)
        return

    await callback.answer()

    if item.get("duration", 0) > 600:
        await callback.message.edit_text(
            make_message("Download", tr(uid, "too_long"))
        )
        return

    await callback.message.edit_text(
        make_message(
            "Download",
            f"🎵 <b>{esc(item['title'])}</b>\n"
            "⏳ Downloading...",
        )
    )

    dl_path = f"dl_{uid}.mp3"

    try:
        if os.path.exists(dl_path):
            os.remove(dl_path)

        got = await asyncio.to_thread(
            run_download,
            item["url"],
            dl_path,
        )

        if got != dl_path and os.path.exists(got):
            os.replace(got, dl_path)

        if not os.path.isfile(dl_path):
            raise RuntimeError("فایل دانلودشده پیدا نشد.")

        if os.path.getsize(dl_path) > 19 * 1024 * 1024:
            os.remove(dl_path)

            await callback.message.edit_text(
                make_message("Download", tr(uid, "too_large"))
            )
            return

        user_files[uid] = {
            "file_id": None,
            "title": item["title"],
            "performer": item.get("uploader") or "YouTube",
            "duration": item.get("duration") or 0,
            "thumb_id": None,
            "file_name": f"{item['title']}.mp3",
            "effects": [],
            "chain_path": None,
            "base_title": item["title"],
            "base_duration": item.get("duration") or 0,
            "dl_path": dl_path,
            "from_search": True,
        }

        await callback.message.edit_text(
            make_message(
                "Music Effects",
                f"✅ <b>{esc(item['title'])}</b>\n\n"
                f"{tr(uid, 'downloaded')}\n"
                f"{tr(uid, 'choose_fx')}",
            ),
            reply_markup=get_buttons(uid),
        )

    except Exception as exc:
        await callback.message.edit_text(
            make_message(
                "Download",
                f"{tr(uid, 'download_failed')}\n"
                f"<code>{esc(str(exc)[-500:])}</code>",
            )
        )


# =========================================================
# AUDIO FILE RECEIVING
# =========================================================

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
        file_id = message.audio.file_id
        title = message.audio.title
        performer = message.audio.performer
        duration = message.audio.duration or 0
        file_name = message.audio.file_name or "music.mp3"

        if message.audio.thumbnail:
            thumb_id = message.audio.thumbnail.file_id

    elif message.voice:
        file_id = message.voice.file_id
        duration = message.voice.duration or 0
        file_name = "voice.ogg"

    elif message.document:
        fname = message.document.file_name or ""
        mime = message.document.mime_type or ""

        supported = (
            ".mp3", ".m4a", ".wav", ".ogg",
            ".flac", ".mp4", ".wma", ".aac",
        )

        if "audio" in mime or fname.lower().endswith(supported):
            file_id = message.document.file_id
            file_name = fname or "music.mp3"

            if message.document.thumbnail:
                thumb_id = message.document.thumbnail.file_id

    if not file_id:
        await message.reply(
            make_message("Music Effects", tr(uid, "not_audio"))
        )
        return

    st = get_settings(uid)
    show_name = title or os.path.splitext(file_name)[0]

    user_files[uid] = {
        "file_id": file_id,
        "title": title,
        "performer": performer,
        "duration": duration,
        "thumb_id": thumb_id,
        "file_name": file_name,
        "effects": [],
        "chain_path": None,
        "base_title": show_name,
        "base_duration": duration,
        "from_search": False,
    }

    await message.reply(
        make_message(
            "Music Effects",
            f"{tr(uid, 'received')}\n"
            f"🎵 <b>{esc(show_name)}</b>\n\n"
            f"{tr(uid, 'choose_fx')}",
        ),
        reply_markup=get_buttons(uid),
    )


@dp.message(F.video)
async def handle_video(message: types.Message):
    uid = message.from_user.id

    if uid in broadcast_mode and is_admin(uid):
        await do_broadcast(message)


# =========================================================
# BROADCAST
# =========================================================

async def do_broadcast(message: types.Message):
    admin_uid = message.from_user.id

    broadcast_mode.discard(admin_uid)

    status = await message.reply(
        make_message(
            "Broadcast",
            f"📤 Sending to {len(all_users)} users...",
        )
    )

    ok = 0
    fail = 0

    for index, uid in enumerate(list(all_users), start=1):
        try:
            await bot.copy_message(
                chat_id=uid,
                from_chat_id=message.chat.id,
                message_id=message.message_id,
            )
            ok += 1
        except Exception:
            fail += 1

        if index % 20 == 0:
            await asyncio.sleep(0.5)

    await status.edit_text(
        make_message(
            "Broadcast Results",
            f"✅ Sent: <b>{ok}</b>\n"
            f"❌ Failed: <b>{fail}</b>",
        ),
        reply_markup=get_admin_panel(),
    )


# =========================================================
# PREPARE INPUT
# =========================================================

async def prepare_chain_input(uid: int):
    info = user_files[uid]

    if (
        info.get("from_search")
        and not info.get("chain_path")
        and not info.get("file_id")
    ):
        return info.get("dl_path")

    if info.get("file_id") and not info.get("chain_path"):
        inp = f"input_{uid}.tmp"

        telegram_file = await bot.get_file(info["file_id"])

        await bot.download_file(
            telegram_file.file_path,
            inp,
        )

        return inp

    return info.get("chain_path")


# =========================================================
# FIRST EFFECT
# =========================================================

@dp.callback_query(F.data.startswith("fx:"))
async def first_effect(callback: types.CallbackQuery):
    uid = callback.from_user.id

    if uid not in user_files:
        await callback.answer(
            tr(uid, "no_file"),
            show_alert=True,
        )
        return

    effect = callback.data.split(":", 1)[1]

    if effect not in FILTERS:
        await callback.answer()
        return

    await callback.answer()

    await callback.message.edit_text(
        make_message("Music Effects", tr(uid, "processing"))
    )

    info = user_files[uid]
    outp = f"chain_{uid}.mp3"

    try:
        src = await prepare_chain_input(uid)

        if not src or not os.path.exists(src):
            raise RuntimeError("فایل پیدا نشد؛ دوباره ارسال کن.")

        await apply_effect_to_file(src, outp, effect)

        if src != outp and src.startswith("input_"):
            try:
                os.remove(src)
            except OSError:
                pass

        info["effects"] = [effect]
        info["chain_path"] = outp

        await callback.message.edit_text(
            make_message(
                "Music Effects",
                f"✅ {EFFECT_EMOJI[effect]} "
                f"<b>{EFFECT_STYLED[effect]}</b>\n\n"
                f"{tr(uid, 'another_fx')}",
            ),
            reply_markup=get_chain_buttons(uid),
        )

    except Exception as exc:
        await callback.message.edit_text(
            make_message(
                "Music Effects",
                f"{tr(uid, 'error')}\n"
                f"<code>{esc(str(exc)[-500:])}</code>",
            )
        )


# =========================================================
# ADD MORE EFFECTS
# =========================================================

@dp.callback_query(F.data.startswith("chain:"))
async def chain_effect(callback: types.CallbackQuery):
    uid = callback.from_user.id

    if (
        uid not in user_files
        or not user_files[uid].get("chain_path")
    ):
        await callback.answer(
            tr(uid, "no_file"),
            show_alert=True,
        )
        return

    effect = callback.data.split(":", 1)[1]

    if effect not in FILTERS:
        await callback.answer()
        return

    info = user_files[uid]

    if effect in info["effects"]:
        await callback.answer(
            tr(uid, "duplicate_fx"),
            show_alert=True,
        )
        return

    await callback.answer()

    await callback.message.edit_text(
        make_message("Music Effects", tr(uid, "adding_fx"))
    )

    old = info["chain_path"]
    new = f"chain_{uid}_next.mp3"

    try:
        await apply_effect_to_file(old, new, effect)

        if os.path.exists(old):
            os.remove(old)

        info["chain_path"] = new
        info["effects"].append(effect)

        label = " + ".join(
            EFFECT_STYLED.get(e, e)
            for e in info["effects"]
        )

        await callback.message.edit_text(
            make_message(
                "Music Effects",
                f"✅ <b>{esc(label)}</b>\n\n"
                f"{tr(uid, 'another_fx')}",
            ),
            reply_markup=get_chain_buttons(uid),
        )

    except Exception as exc:
        await callback.message.edit_text(
            make_message(
                "Music Effects",
                f"{tr(uid, 'error')}\n"
                f"<code>{esc(str(exc)[-500:])}</code>",
            )
        )


# =========================================================
# FINAL AUDIO
# =========================================================

async def send_final(
    uid: int,
    chat_id: int,
    reply_to: types.Message,
):
    info = user_files[uid]
    settings = get_settings(uid)

    effects = info["effects"]
    chain_path = info["chain_path"]

    if not chain_path or not os.path.isfile(chain_path):
        raise RuntimeError("فایل خروجی پیدا نشد.")

    final_path = f"output_{uid}.mp3"

    if os.path.exists(final_path):
        os.remove(final_path)

    os.replace(chain_path, final_path)

    # Watermark is optional. Final output is normalized
    # after the effects have been processed.
    await add_audio_watermark(final_path, final_path)

    suffix_full = " ".join(
        SUFFIX.get(effect, "")
        for effect in effects
    ).strip()

    base = info["base_title"]

    if suffix_full and not base.lower().endswith(suffix_full.lower()):
        new_title = f"{base} {suffix_full}".strip()
    else:
        new_title = base

    new_performer = (
        settings.get("artist")
        or info.get("performer")
        or tr(uid, "unknown_artist")
    )

    safe_name = "".join(
        char
        for char in new_title
        if char not in '/\\:*?"<>|'
    ).strip() or "music"

    duration = info["base_duration"]

    for effect in effects:
        duration = calc_duration(duration, effect)

    thumb_file = None
    thumb_original = f"thumb_{uid}.jpg"
    thumb_fixed = f"thumb_{uid}_fixed.jpg"

    try:
        cover_id = settings.get("cover") or info.get("thumb_id")

        if cover_id:
            telegram_file = await bot.get_file(cover_id)

            await bot.download_file(
                telegram_file.file_path,
                thumb_original,
            )

            if await fix_thumb(thumb_original, thumb_fixed):
                thumb_file = FSInputFile(thumb_fixed)

    except Exception:
        thumb_file = None

    effect_label = " + ".join(
        EFFECT_STYLED.get(effect, effect)
        for effect in effects
    )

    emoji = (
        EFFECT_EMOJI.get(effects[-1], "🎧")
        if effects else "🎧"
    )

    caption = make_message(
        f"{emoji} {effect_label}",
        f"🎵 <b>{esc(new_title)}</b>\n"
        f"👤 {esc(new_performer)}\n"
        f"⏱️ {format_time(duration)}\n\n"
        f"{tr(uid, 'headphones')}",
    )

    audio_file = FSInputFile(
        final_path,
        filename=f"{safe_name}.mp3",
    )

    await bot.send_audio(
        chat_id=chat_id,
        audio=audio_file,
        title=new_title,
        performer=new_performer,
        duration=duration or None,
        thumbnail=thumb_file,
        caption=caption,
        reply_markup=get_share_kb(uid),
    )

    for path in (
        thumb_original,
        thumb_fixed,
        final_path,
        info.get("dl_path"),
    ):
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


# =========================================================
# FINISH PROCESSING
# =========================================================

@dp.callback_query(F.data == "chain_done")
async def chain_done(callback: types.CallbackQuery):
    uid = callback.from_user.id

    if (
        uid not in user_files
        or not user_files[uid].get("chain_path")
    ):
        await callback.answer(
            tr(uid, "no_file"),
            show_alert=True,
        )
        return

    await callback.answer()

    await callback.message.edit_text(
        make_message("Music Effects", "⏳ Preparing your audio...")
    )

    try:
        await send_final(
            uid,
            callback.message.chat.id,
            callback.message,
        )

    except Exception as exc:
        await callback.message.edit_text(
            make_message(
                "Music Effects",
                f"{tr(uid, 'error')}\n"
                f"<code>{esc(str(exc)[-500:])}</code>",
            )
        )


# =========================================================
# WEB SERVER / START BOT
# =========================================================

async def health_check(request):
    return web.Response(text="Music Effects Bot is running!")


async def main():
    global BOT_USERNAME

    try:
        me = await bot.get_me()
        BOT_USERNAME = me.username or ""
    except Exception as exc:
        print("Could not fetch bot information:", exc)

    try:
        await bot.set_my_commands([
            BotCommand(
                command="start",
                description="شروع / Start",
            ),
            BotCommand(
                command="help",
                description="راهنما / Help",
            ),
            BotCommand(
                command="cancel",
                description="لغو / Cancel",
            ),
        ])
    except Exception as exc:
        print("Could not set bot commands:", exc)

    app = web.Application()
    app.router.add_get("/", health_check)

    runner = web.AppRunner(app)
    await runner.setup()

    site = web.TCPSite(
        runner,
        "0.0.0.0",
        int(os.getenv("PORT", "10000")),
    )

    await site.start()

    print("Music Effects Bot is running...")

    try:
        await dp.start_polling(bot)
    finally:
        await runner.cleanup()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
