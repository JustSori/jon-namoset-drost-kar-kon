import asyncio
import os
import json
import subprocess
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, BotCommand, FSInputFile
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiohttp import web

TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise ValueError("BOT_TOKEN ست نشده!")

ADMIN_IDS = set()
for x in os.getenv("ADMIN_ID", "").split(","):
    x = x.strip()
    if x.isdigit():
        ADMIN_IDS.add(int(x))

WATERMARK_SOUND = os.getenv("WATERMARK", "on")

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
user_files = {}
user_settings = {}
awaiting = {}
broadcast_mode = set()
search_cache = {}
BOT_USERNAME = ""
USERS_FILE = "users.json"

def load_users():
    try:
        if os.path.exists(USERS_FILE):
            with open(USERS_FILE, "r") as f:
                d = json.load(f)
                return set(d.get("ids", [])), d.get("dates", {})
    except:
        pass
    return set(), {}

def save_users():
    try:
        with open(USERS_FILE, "w") as f:
            json.dump({"ids": list(all_users), "dates": first_seen}, f)
    except:
        pass

all_users, first_seen = load_users()

def is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS

def add_user(uid: int):
    s = str(uid)
    if uid not in all_users:
        all_users.add(uid)
        first_seen[s] = datetime.now().strftime("%Y-%m-%d")
        save_users()

def get_settings(uid: int):
    if uid not in user_settings:
        user_settings[uid] = {"artist": None, "cover": None}
    return user_settings[uid]

def get_buttons():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🐌 اسلو | Slowed", callback_data="fx:slowed"),
         InlineKeyboardButton(text="🎧 اسلو + ریورب", callback_data="fx:slowed_reverb")],
        [InlineKeyboardButton(text="🌃 نایتکور | Nightcore", callback_data="fx:nightcore"),
         InlineKeyboardButton(text="⚡ افزایش سرعت", callback_data="fx:speedup")],
        [InlineKeyboardButton(text="🔊 تقویت بیس", callback_data="fx:bass"),
         InlineKeyboardButton(text="🌊 ریورب | Reverb", callback_data="fx:reverb")],
        [InlineKeyboardButton(text="🎩 8D", callback_data="fx:8d")],
        [InlineKeyboardButton(text="✏️ تنظیم خواننده", callback_data="set_artist"),
         InlineKeyboardButton(text="🖼️ تنظیم کاور", callback_data="set_cover")],
    ])

def get_chain_buttons():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🐌 اسلو | Slowed", callback_data="chain:slowed"),
         InlineKeyboardButton(text="🎧 اسلو + ریورب", callback_data="chain:slowed_reverb")],
        [InlineKeyboardButton(text="🌃 نایتکور | Nightcore", callback_data="chain:nightcore"),
         InlineKeyboardButton(text="⚡ افزایش سرعت", callback_data="chain:speedup")],
        [InlineKeyboardButton(text="🔊 تقویت بیس", callback_data="chain:bass"),
         InlineKeyboardButton(text="🌊 ریورب | Reverb", callback_data="chain:reverb")],
        [InlineKeyboardButton(text="🎩 8D", callback_data="chain:8d")],
        [InlineKeyboardButton(text="✅ پایان افکت‌ها و دریافت", callback_data="chain_done")],
    ])

def get_admin_panel():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 آمار ربات", callback_data="admin_stats")],
        [InlineKeyboardButton(text="📢 پیام همگانی", callback_data="admin_broadcast")]
    ])

def get_share_kb():
    if BOT_USERNAME:
        url = f"https://t.me/share/url?url=https://t.me/{BOT_USERNAME}&text=این آهنگو با این ربات درست کردم 🎧"
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="↗️ اشتراک‌گذاری", url=url)],
            [InlineKeyboardButton(text="🎧 ساخت آهنگ جدید", url=f"https://t.me/{BOT_USERNAME}")]
        ])
    return None

SUFFIX = {"slowed": "(slowed)", "slowed_reverb": "(slowed + reverb)", "speedup": "(speed up)", "nightcore": "(nightcore)", "bass": "(bass boosted)", "reverb": "(reverb)", "8d": "(8d)"}
FILTERS = {
    "slowed": "asetrate=44100*0.85,aresample=44100,loudnorm=I=-16:TP=-1.5:LRA=11,volume=1.1",
    "slowed_reverb": "asetrate=44100*0.85,aresample=44100,aecho=0.8:0.9:150:0.32,aecho=0.8:0.7:500:0.25,bass=g=4:f=110:w=0.6,volume=1.15,loudnorm=I=-16:TP=-1.5:LRA=11",
    "speedup": "atempo=1.20,aresample=44100,loudnorm",
    "nightcore": "asetrate=44100*1.20,aresample=44100,volume=1.1",
    "bass": "bass=g=8:f=110:w=0.6,volume=1.2,aresample=44100",
    "reverb": "aecho=0.8:0.88:120:0.35,aecho=0.8:0.6:400:0.25,aresample=44100,volume=1.1",
    "8d": "extrastereo=m=1.6,apulsator=hz=0.15,aresample=44100"
}
EFFECT_EMOJI = {"slowed": "🐌", "slowed_reverb": "🎧", "speedup": "⚡", "nightcore": "🌃", "bass": "🔊", "reverb": "🌊", "8d": "🎩"}
EFFECT_TITLE_FA = {"slowed": "اسلو", "slowed_reverb": "اسلو + ریورب", "speedup": "اسپید آپ", "nightcore": "نایتکور", "bass": "بیس بوست", "reverb": "ریورب", "8d": "هشت‌بعدی"}
EFFECT_STYLED = {"slowed": "Slᴏᴡᴇᴅ", "slowed_reverb": "Slᴏᴡᴇᴅ + Rᴇᴠᴇʀʙ", "speedup": "Sᴘᴇᴇᴅ Up", "nightcore": "Nɪɢʜᴛᴄᴏʀᴇ", "bass": "Bᴀss Bᴏᴏsᴛ", "reverb": "Rᴇᴠᴇʀʙ", "8d": "8D"}

def format_time(s: int) -> str:
    try:
        s = int(s or 0)
    except:
        s = 0
    return f"{s // 60:02d}:{s % 60:02d}"

def calc_duration(base: int, effect: str) -> int:
    if effect in ["slowed", "slowed_reverb"]:
        return int((base or 0) / 0.85) if base else 0
    if effect in ["speedup", "nightcore"]:
        return int((base or 0) / 1.2) if base else 0
    return base or 0

def run_search(query: str):
    cmd = ["yt-dlp", f"ytsearch5:{query}", "--flat-playlist", "--dump-json", "--no-playlist", "--no-warnings"]
    r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=30)
    out = []
    for line in r.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            j = json.loads(line)
            vid = j.get("id", "")
            title = j.get("title", "Unknown")
            dur = j.get("duration") or 0
            uploader = j.get("uploader") or j.get("channel") or ""
            url = j.get("url") or (f"https://www.youtube.com/watch?v={vid}" if vid else "")
            if vid and "://" not in url:
                url = f"https://www.youtube.com/watch?v={vid}"
            out.append({"id": vid, "title": title[:80], "duration": int(dur or 0), "uploader": str(uploader)[:50], "url": url})
        except:
            continue
        if len(out) >= 5:
            break
    return out

def run_download(url: str, out_path: str):
    base = os.path.splitext(out_path)[0]
    template = base + ".%(ext)s"
    cmd = [
        "yt-dlp",
        "--no-playlist",
        "--no-warnings",
        "--no-progress",
        "--extract-audio",
        "--audio-format", "mp3",
        "--audio-quality", "192K",
        "-o", template,
        url,
    ]

    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=180,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("yt-dlp نصب نیست یا در PATH قرار ندارد.") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("زمان دانلود تمام شد؛ دوباره تلاش کن.") from exc

    final_path = base + ".mp3"
    if result.returncode != 0 or not os.path.isfile(final_path):
        error = (result.stderr or result.stdout or "خطای نامشخص از yt-dlp").strip()
        raise RuntimeError(error[-1200:])

    return final_path

async def fix_thumb(src: str, dst: str) -> bool:
    cmd = ["ffmpeg", "-y", "-i", src, "-vf", "scale=320:320:force_original_aspect_ratio=increase,crop=320:320", "-q:v", "3", dst]
    await asyncio.to_thread(subprocess.run, cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if os.path.exists(dst):
        try:
            if os.path.getsize(dst) > 190 * 1024:
                tmp = dst + ".tmp.jpg"
                await asyncio.to_thread(subprocess.run, ["ffmpeg", "-y", "-i", dst, "-vf", "scale=320:320", "-q:v", "8", tmp], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                if os.path.exists(tmp):
                    os.replace(tmp, dst)
        except:
            pass
        return True
    return False

async def apply_effect_to_file(inp: str, outp: str, effect: str):
    cmd = ["ffmpeg", "-y", "-i", inp, "-filter:a", FILTERS[effect], "-ar", "44100", "-ac", "2", "-c:a", "libmp3lame", "-b:a", "192k", outp]
    await asyncio.to_thread(subprocess.run, cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if not os.path.exists(outp):
        raise RuntimeError("خطا در پردازش فایل.")

async def add_audio_watermark(inp: str, outp: str):
    if WATERMARK_SOUND == "off":
        if inp != outp:
            try:
                os.replace(inp, outp)
            except:
                pass
        return
    wm = outp + ".wm.mp3"
    cmd = ["ffmpeg", "-y", "-i", inp, "-filter:a", "sine=frequency=880:duration=0.25:beep_factor=2,volume=0.12[beep];[0:a][beep]amix=inputs=2:duration=first:dropout_transition=0:weights=10 1,aresample=44100,aecho=0.8:0.3:40:0.15", "-c:a", "libmp3lame", "-b:a", "192k", wm]
    await asyncio.to_thread(subprocess.run, cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if os.path.exists(wm):
        try:
            os.replace(wm, outp)
        except:
            pass

START_TXT = (
    "🎧 <b>Music Effects</b>\n"
    "━━━━━━━━━━━━━━━━━━\n"
    "سلام! به ربات افکت آهنگ خوش اومدی ✨\n\n"
    "🎵 <b>چطور استفاده کنی؟</b>\n"
    "• فایل صوتی رو همین‌جا بفرست؛ یا\n"
    "• اسم خواننده و آهنگ رو بنویس تا جست‌وجو کنم. 🔍\n\n"
    "🎛️ <b>افکت‌های قابل انتخاب</b>\n"
    "🐌 اسلو  •  🎧 اسلو + ریورب\n"
    "🌃 نایتکور  •  ⚡ افزایش سرعت\n"
    "🔊 تقویت بیس  •  🌊 ریورب  •  🎩 صدای 8D\n\n"
    "━━━━━━━━━━━━━━━━━━\n"
    "👇 <b>برای شروع، فایل بفرست یا اسم آهنگ رو بنویس.</b>"
)

HELP_TXT = (
    "📖 <b>راهنمای Music Effects</b>\n"
    "━━━━━━━━━━━━━━━━━━\n"
    "🔍 <b>جست‌وجوی آهنگ</b>\n"
    "۱. نام خواننده و آهنگ رو بفرست.\n"
    "۲. یکی از نتایج رو انتخاب کن.\n"
    "۳. بعد از دانلود، افکت دلخواهت رو بزن.\n\n"
    "🎵 <b>استفاده از فایل شخصی</b>\n"
    "فایل صوتی رو مستقیم برای ربات ارسال کن.\n\n"
    "🎛️ <b>اعمال چند افکت</b>\n"
    "بعد از افکت اول، می‌تونی افکت‌های بیشتری اضافه کنی؛ سپس «پایان افکت‌ها و دریافت» رو بزن.\n\n"
    "🖼️ <b>تنظیمات اختیاری</b>\n"
    "از دکمه‌های «تنظیم خواننده» و «تنظیم کاور» استفاده کن.\n\n"
    "⚠️ مدت آهنگ برای جست‌وجو و دانلود باید حداکثر ۱۰ دقیقه باشه.\n"
    "━━━━━━━━━━━━━━━━━━\n"
    "برای لغو عملیات در حال انتظار: /cancel"
)

@dp.message(CommandStart())
async def start_cmd(message: types.Message):
    add_user(message.from_user.id)
    await message.reply(START_TXT)

@dp.message(Command("help"))
async def help_cmd(message: types.Message):
    await message.reply(HELP_TXT)

@dp.message(Command("admin"))
async def admin_cmd(message: types.Message):
    if not is_admin(message.from_user.id):
        return
    await message.reply(f"╭── <b>🛠️ Aᴅᴍɪɴ Pᴀɴᴇʟ</b> ──╮\n│ 👥 Usᴇʀs: <b>{len(all_users)}</b>\n╰──────────╯", reply_markup=get_admin_panel())

@dp.callback_query(F.data.startswith("admin_"))
async def admin_callback(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("دسترسی نداری.", show_alert=True)
        return
    await callback.answer()
    if callback.data == "admin_stats":
        today = datetime.now().strftime("%Y-%m-%d")
        tc = sum(1 for v in first_seen.values() if v == today)
        await callback.message.edit_text(f"📊 <b>Sᴛᴀᴛs</b>\n─ ─ ─\n👥 Tᴏᴛᴀʟ: <b>{len(all_users)}</b>\n🆕 Tᴏᴅᴀʏ: <b>{tc}</b>", reply_markup=get_admin_panel())
    elif callback.data == "admin_broadcast":
        broadcast_mode.add(callback.from_user.id)
        await callback.message.edit_text("📢 <b>Bʀᴏᴀᴅᴄᴀsᴛ Mᴏᴅᴇ Oɴ</b>\nپیامت رو بفرست.\n<i>لغو با /cancel</i>")

@dp.message(Command("cancel"))
async def cancel_cmd(message: types.Message):
    broadcast_mode.discard(message.from_user.id)
    awaiting.pop(message.from_user.id, None)
    await message.reply("❌ Lɢᴏ ✓")

@dp.callback_query(F.data == "set_artist")
async def ask_artist(callback: types.CallbackQuery):
    await callback.answer()
    awaiting[callback.from_user.id] = "artist"
    await callback.message.reply("✏️ <b>تنظیم نام خواننده</b>\nنامی که می‌خوای روی فایل نهایی نمایش داده بشه رو بفرست.\nبرای لغو: /cancel")

@dp.callback_query(F.data == "set_cover")
async def ask_cover(callback: types.CallbackQuery):
    await callback.answer()
    awaiting[callback.from_user.id] = "cover"
    await callback.message.reply("🖼️ <b>تنظیم کاور آهنگ</b>\nعکس موردنظرت رو ارسال کن.\nبرای لغو: /cancel")

@dp.message(F.photo)
async def handle_photo(message: types.Message):
    uid = message.from_user.id
    if uid in broadcast_mode and is_admin(uid):
        await do_broadcast(message)
        return
    if awaiting.get(uid) == "cover":
        get_settings(uid)["cover"] = message.photo[-1].file_id
        awaiting.pop(uid, None)
        await message.reply("🖼️ <b>Cᴏᴠᴇʀ Sᴀᴠᴇᴅ ✅</b>\n─ حالا افکت رو بزن 👇", reply_markup=get_buttons())

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
        await message.reply("✏️ <b>Aʀᴛɪsᴛ Sᴀᴠᴇᴅ ✅</b>\n─ حالا افکت رو بزن 👇", reply_markup=get_buttons())
        return
    if txt.startswith("/"):
        return
    if len(txt) < 2:
        return
    add_user(uid)
    wait = await message.reply("🔍 <b>Sᴇᴀʀᴄʜɪɴɢ...</b>\n<i>دارم برای</i> <b>«" + txt + "»</b> <i>می‌گردم ⏳</i>")
    try:
        results = await asyncio.to_thread(run_search, txt)
    except Exception as e:
        await wait.edit_text(f"❌ <b>سرچ نشد:</b> <i>{e}</i>\n<i>دوباره با اسم خواننده + آهنگ امتحان کن</i>")
        return
    if not results:
        await wait.edit_text("❌ چیزی پیدا نکردم 🔍\n<i>خواننده + آهنگ بنویس، انگلیسی بهتره</i>")
        return
    search_cache[uid] = results
    rows = []
    for i, r in enumerate(results):
        rows.append([InlineKeyboardButton(text=f"{i+1}. {r['title'][:40]} ⏱ {format_time(r['duration'])}", callback_data=f"sr:{i}")])
    kb = InlineKeyboardMarkup(inline_keyboard=rows)
    txt_list = f"╭── <b>🔍 برای «{txt}» اینا رو پیدا کردم</b> ──╮\n"
    for i, r in enumerate(results):
        txt_list += f"│ <b>{i+1}.</b> {r['title']}\n│ <i>{r['uploader']} ┆ ⏱ {format_time(r['duration'])}</i>\n"
    txt_list += "╰──────────╯\n─ یکیشو انتخاب کن تا دانلود کنم 👇"
    await wait.edit_text(txt_list, reply_markup=kb)

@dp.callback_query(F.data.startswith("sr:"))
async def pick_search(callback: types.CallbackQuery):
    await callback.answer()
    uid = callback.from_user.id
    if uid not in search_cache:
        await callback.answer("اول اسم آهنگو بفرست 🔍", show_alert=True)
        return
    try:
        idx = int(callback.data.split(":")[1])
    except:
        return
    results = search_cache[uid]
    if idx < 0 or idx >= len(results):
        return
    item = results[idx]
    if item.get("duration", 0) > 600:
        await callback.answer("بیشتر از ۱۰ دقیقه‌ست، یکی دیگه انتخاب کن.", show_alert=True)
        return
    await callback.message.edit_text(f"⏳ <b>Dᴏᴡɴʟᴏᴀᴅɪɴɢ...</b>\n│ 🎵 <b>{item['title']}</b>\n│ <i>دارم دانلودش می‌کنم ⏳</i>")
    try:
        await bot.send_chat_action(callback.message.chat.id, "upload_voice")
    except:
        pass
    dl_path = f"dl_{uid}.mp3"
    try:
        try:
            if os.path.exists(dl_path):
                os.remove(dl_path)
        except:
            pass
        got = await asyncio.to_thread(run_download, item["url"], dl_path)
        if got != dl_path and os.path.exists(got):
            try:
                os.replace(got, dl_path)
            except:
                pass
        if not os.path.exists(dl_path):
            raise RuntimeError("دانلود نشد.")
        if os.path.getsize(dl_path) > 19 * 1024 * 1024:
            try:
                os.remove(dl_path)
            except:
                pass
            await callback.message.edit_text("❌ حجمش بیشتر از ۲۰ مگه.")
            return
        st = get_settings(uid)
        base_title = item["title"]
        user_files[uid] = {"file_id": None, "title": base_title, "performer": item.get("uploader") or "YouTube", "duration": item.get("duration") or 0, "thumb_id": None, "file_name": f"{base_title}.mp3", "effects": [], "chain_path": None, "base_title": base_title, "base_duration": item.get("duration") or 0, "dl_path": dl_path, "from_search": True}
        extra = ""
        if st.get("artist"):
            extra += f"\n✏️ تنظیم خواننده: <b>{st['artist']}</b>"
        if st.get("cover"):
            extra += "\n🖼️ تنظیم کاور: <b>Oɴ ✅</b>"
        await callback.message.edit_text(f"╭── <b>✅ دانلود شد، حالا افکت بزن</b> ──╮\n│ 🎵 <b>{base_title}</b>{extra}\n╰──────────╯\n─ افکت رو انتخاب کن 👇", reply_markup=get_buttons())
    except Exception as e:
        await callback.message.edit_text(f"❌ <b>دانلود نشد:</b> <i>{e}</i>")

@dp.message(F.audio | F.voice | F.document)
async def handle_music(message: types.Message):
    if message.from_user.id in broadcast_mode and is_admin(message.from_user.id):
        await do_broadcast(message)
        return
    file_id = title = performer = duration = thumb_id = None
    file_name = "music.mp3"
    if message.audio:
        file_id = message.audio.file_id
        title = message.audio.title
        performer = message.audio.performer
        duration = message.audio.duration
        file_name = message.audio.file_name or "music.mp3"
        if message.audio.thumbnail:
            thumb_id = message.audio.thumbnail.file_id
    elif message.voice:
        file_id = message.voice.file_id
        duration = message.voice.duration
        file_name = "voice.ogg"
    elif message.document:
        fname = message.document.file_name or ""
        mime = message.document.mime_type or ""
        if "audio" in mime or fname.lower().endswith((".mp3", ".m4a", ".wav", ".ogg", ".flac", ".mp4", ".wma")):
            file_id = message.document.file_id
            file_name = fname or "music.mp3"
            if message.document.thumbnail:
                thumb_id = message.document.thumbnail.file_id
    if not file_id:
        await message.reply("❌ فایل صوتی نیست 🎵\n<i>یا فایل بفرست یا اسم آهنگو بنویس 🔍</i>")
        return
    st = get_settings(message.from_user.id)
    user_files[message.from_user.id] = {"file_id": file_id, "title": title, "performer": performer, "duration": duration, "thumb_id": thumb_id, "file_name": file_name, "effects": [], "chain_path": None, "base_title": title or os.path.splitext(file_name)[0], "base_duration": duration or 0, "from_search": False}
    show_name = title or os.path.splitext(file_name)[0]
    extra = ""
    if st.get("artist"):
        extra += f"\n✏️ تنظیم خواننده: <b>{st['artist']}</b>"
    if st.get("cover"):
        extra += "\n🖼️ تنظیم کاور: <b>Oɴ ✅</b>"
    await message.reply(f"╭── <b>✅ Rᴇᴄᴇɪᴠᴇᴅ</b> ──╮\n│ 🎵 <b>{show_name}</b>{extra}\n╰──────────╯\n─ افکت رو انتخاب کن 👇", reply_markup=get_buttons())

@dp.message(F.video)
async def handle_video(message: types.Message):
    if message.from_user.id in broadcast_mode and is_admin(message.from_user.id):
        await do_broadcast(message)

async def do_broadcast(message: types.Message):
    broadcast_mode.discard(message.from_user.id)
    await message.reply(f"📢 Sᴇɴᴅɪɴɢ ᴛᴏ {len(all_users)}...")
    ok = fail = 0
    for uid in list(all_users):
        try:
            await bot.copy_message(chat_id=uid, from_chat_id=message.chat.id, message_id=message.message_id)
            ok += 1
        except:
            fail += 1
        if ok % 20 == 0:
            await asyncio.sleep(0.5)
    await message.reply(f"📢 <b>Dᴏɴᴇ</b>\n✅: <b>{ok}</b>\n❌: <b>{fail}</b>", reply_markup=get_admin_panel())

async def send_final(uid: int, chat_id: int, reply_to: types.Message):
    info = user_files[uid]
    st = get_settings(uid)
    effects = info["effects"]
    chain_path = info["chain_path"]
    final_path = f"output_{uid}.mp3"
    try:
        if os.path.exists(chain_path):
            os.replace(chain_path, final_path)
        else:
            final_path = chain_path
    except:
        final_path = chain_path
    await add_audio_watermark(final_path, final_path)
    suffix_full = " ".join([SUFFIX.get(e, "") for e in effects]).strip()
    base = info["base_title"]
    new_title = base if (suffix_full and base.lower().endswith(suffix_full.lower())) else f"{base} {suffix_full}".strip()
    new_performer = st.get("artist") or info.get("performer") or "Unknown Artist"
    safe_name = "".join(c for c in new_title if c not in '/\\:*?"<>|').strip() or "music"
    duration = info["base_duration"]
    for e in effects:
        duration = calc_duration(duration, e)
    thumb_file = None
    t1 = f"thumb_{uid}.jpg"
    t2 = f"thumb_{uid}_fixed.jpg"
    try:
        cid = st.get("cover") or info.get("thumb_id")
        if cid:
            tf = await bot.get_file(cid)
            await bot.download_file(tf.file_path, t1)
            if await fix_thumb(t1, t2):
                thumb_file = FSInputFile(t2)
            elif os.path.exists(t1):
                thumb_file = FSInputFile(t1)
    except:
        thumb_file = None
    styled_fx = " + ".join([EFFECT_STYLED.get(e, e) for e in effects])
    emoji = EFFECT_EMOJI.get(effects[-1], "🎧") if effects else "🎧"
    wm = f"\n🤖 @{BOT_USERNAME}" if BOT_USERNAME else ""
    caption = f"╭── {emoji} <b>{styled_fx}</b> ──╮\n│ 🎵 <b>{new_title}</b>\n│ 👤 {new_performer}\n│ ⏱️ {format_time(duration)}{wm}\n╰──────────╯\n<i>🎧 Wɪᴛʜ Hᴇᴀᴅᴘʜᴏɴᴇs</i>"
    audio_file = FSInputFile(final_path, filename=f"{safe_name}.mp3")
    await bot.send_audio(chat_id, audio_file, title=new_title, performer=new_performer, duration=duration if duration else None, thumbnail=thumb_file, caption=caption, reply_markup=get_share_kb())
    for p in [t1, t2, final_path, info.get("dl_path")]:
        try:
            if p and os.path.exists(p):
                os.remove(p)
        except:
            pass
    try:
        await reply_to.delete()
    except:
        pass
    user_files.pop(uid, None)

async def prepare_chain_input(uid: int):
    info = user_files[uid]
    if info.get("from_search") and not info.get("chain_path") and not info.get("file_id"):
        return info.get("dl_path")
    if info.get("file_id") and not info.get("chain_path"):
        inp = f"input_{uid}.tmp"
        f = await bot.get_file(info["file_id"])
        await bot.download_file(f.file_path, inp)
        return inp
    return info.get("chain_path")

@dp.callback_query(F.data.startswith("fx:"))
async def first_effect(callback: types.CallbackQuery):
    await callback.answer()
    uid = callback.from_user.id
    if uid not in user_files:
        await callback.answer("اول فایل بفرست یا اسم بنویس 🔍", show_alert=True)
        return
    effect = callback.data.split(":", 1)[1]
    if effect not in FILTERS:
        return
    await callback.message.edit_text("🎛️ <b>در حال اعمال افکت</b>\n━━━━━━━━━━━━━━━━━━\n⏳ لطفاً صبر کن...")
    try:
        await bot.send_chat_action(callback.message.chat.id, "upload_voice")
    except:
        pass
    info = user_files[uid]
    outp = f"chain_{uid}.mp3"
    try:
        src = await prepare_chain_input(uid)
        if not src or not os.path.exists(src):
            raise RuntimeError("فایل پیدا نشد، دوباره بفرست.")
        await apply_effect_to_file(src, outp, effect)
        if src != outp and src.startswith("input_"):
            try:
                os.remove(src)
            except:
                pass
        info["effects"] = [effect]
        info["chain_path"] = outp
        await callback.message.edit_text(f"╭── <b>✅ {EFFECT_STYLED.get(effect, effect)}</b> ──╮\n│ 🔗 یه افکت دیگه هم اضافه کنم؟\n╰──────────╯", reply_markup=get_chain_buttons())
    except Exception as e:
        await callback.message.edit_text(f"❌ <b>Eʀʀᴏʀ:</b> <i>{e}</i>")

@dp.callback_query(F.data.startswith("chain:"))
async def chain_effect(callback: types.CallbackQuery):
    await callback.answer()
    uid = callback.from_user.id
    if uid not in user_files or not user_files[uid].get("chain_path"):
        await callback.answer("فایلی نیست.", show_alert=True)
        return
    effect = callback.data.split(":", 1)[1]
    if effect not in FILTERS:
        return
    info = user_files[uid]
    if effect in info["effects"]:
        await callback.answer("این افکت قبلاً اضافه شده.", show_alert=True)
        return
    await callback.message.edit_text("🔗 <b>در حال افزودن افکت</b>\n━━━━━━━━━━━━━━━━━━\n⏳ لطفاً صبر کن...")
    old = info["chain_path"]
    new = f"chain_{uid}_2.mp3"
    try:
        await apply_effect_to_file(old, new, effect)
        try:
            os.remove(old)
        except:
            pass
        info["chain_path"] = new
        info["effects"].append(effect)
        label = " + ".join([EFFECT_STYLED.get(e, e) for e in info["effects"]])
        await callback.message.edit_text(f"╭── <b>✅ {label}</b> ──╮\n│ 🔗 باز هم اضافه کنم؟\n╰──────────╯", reply_markup=get_chain_buttons())
    except Exception as e:
        await callback.message.edit_text(f"❌ <b>Eʀʀᴏʀ:</b> <i>{e}</i>")

@dp.callback_query(F.data == "chain_done")
async def chain_done(callback: types.CallbackQuery):
    await callback.answer()
    uid = callback.from_user.id
    if uid not in user_files or not user_files[uid].get("chain_path"):
        await callback.answer("فایلی نیست.", show_alert=True)
        return
    try:
        await send_final(uid, callback.message.chat.id, callback.message)
    except Exception as e:
        await callback.message.edit_text(f"❌ <b>Eʀʀᴏʀ:</b> <i>{e}</i>")

async def handle(request):
    return web.Response(text="Bot is alive!")

async def main():
    global BOT_USERNAME
    try:
        me = await bot.get_me()
        BOT_USERNAME = me.username or ""
    except:
        pass
    try:
        await bot.set_my_commands([BotCommand(command="start", description="شروع 🚀"), BotCommand(command="help", description="راهنما 📖")])
    except:
        pass
    app = web.Application()
    app.router.add_get("/", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", int(os.getenv("PORT", 10000)))
    await site.start()
    print("بات روشن شد...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
