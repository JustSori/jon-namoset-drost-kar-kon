import asyncio
import os
import sqlite3
import time
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from aiogram.filters import CommandStart, Command
from aiohttp import web

TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise ValueError("BOT_TOKEN ست نشده!")

ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_ID", "0").split(",") if x.strip().isdigit()]
DAILY_LIMIT = int(os.getenv("DAILY_LIMIT", "30"))

bot = Bot(token=TOKEN)
dp = Dispatcher()
user_files = {}
broadcast_wait = set()

DB = "bot.db"
con = sqlite3.connect(DB, check_same_thread=False)
cur = con.cursor()
cur.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, username TEXT, name TEXT, start_count INTEGER DEFAULT 0)")
cur.execute("CREATE TABLE IF NOT EXISTS stats (key TEXT PRIMARY KEY, value INTEGER DEFAULT 0)")
cur.execute("INSERT OR IGNORE INTO stats VALUES ('processed', 0)")
cur.execute("CREATE TABLE IF NOT EXISTS effect_stats (effect TEXT PRIMARY KEY, count INTEGER DEFAULT 0)")
cur.execute("CREATE TABLE IF NOT EXISTS daily_usage (user_id INTEGER, date TEXT, count INTEGER DEFAULT 0, PRIMARY KEY(user_id, date))")
cur.execute("CREATE TABLE IF NOT EXISTS daily_total (date TEXT PRIMARY KEY, count INTEGER DEFAULT 0)")
con.commit()

def today_str():
    return datetime.now().strftime("%Y-%m-%d")

def add_user(u: types.User):
    cur.execute("INSERT OR IGNORE INTO users (user_id, username, name, start_count) VALUES (?,?,?,0)",
                (u.id, u.username or "", u.first_name or ""))
    cur.execute("UPDATE users SET username=?, name=?, start_count=start_count+1 WHERE user_id=?",
                (u.username or "", u.first_name or "", u.id))
    con.commit()

def get_stats():
    cur.execute("SELECT COUNT(*) FROM users")
    total = cur.fetchone()[0]
    cur.execute("SELECT SUM(start_count) FROM users")
    starts = cur.fetchone()[0] or 0
    cur.execute("SELECT value FROM stats WHERE key='processed'")
    proc = cur.fetchone()[0]
    cur.execute("SELECT count FROM daily_total WHERE date=?", (today_str(),))
    row = cur.fetchone()
    today_proc = row[0] if row else 0
    return total, starts, proc, today_proc

def get_all_users():
    cur.execute("SELECT user_id FROM users")
    return [r[0] for r in cur.fetchall()]

def get_effect_stats():
    cur.execute("SELECT effect, count FROM effect_stats ORDER BY count DESC")
    return cur.fetchall()

def check_limit(user_id: int):
    if user_id in ADMIN_IDS:
        return True, 999
    d = today_str()
    cur.execute("SELECT count FROM daily_usage WHERE user_id=? AND date=?", (user_id, d))
    row = cur.fetchone()
    used = row[0] if row else 0
    return used < DAILY_LIMIT, max(DAILY_LIMIT - used, 0)

def inc_usage(user_id: int, effect: str):
    d = today_str()
    cur.execute("INSERT OR IGNORE INTO daily_usage (user_id, date, count) VALUES (?,?,0)", (user_id, d))
    cur.execute("UPDATE daily_usage SET count=count+1 WHERE user_id=? AND date=?", (user_id, d))
    cur.execute("INSERT OR IGNORE INTO daily_total (date, count) VALUES (?,0)", (d,))
    cur.execute("UPDATE daily_total SET count=count+1 WHERE date=?", (d,))
    cur.execute("UPDATE stats SET value=value+1 WHERE key='processed'")
    cur.execute("INSERT OR IGNORE INTO effect_stats (effect, count) VALUES (?,0)", (effect,))
    cur.execute("UPDATE effect_stats SET count=count+1 WHERE effect=?", (effect,))
    con.commit()

def get_buttons():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="\U0001F40C Slowed", callback_data="prev_slowed"),
         InlineKeyboardButton(text="\U0001F3A7 Slowed + Reverb", callback_data="prev_slowed_reverb")],
        [InlineKeyboardButton(text="\U0001F303 Nightcore", callback_data="prev_nightcore"),
         InlineKeyboardButton(text="\u26A1 Speed Up", callback_data="prev_speedup")],
        [InlineKeyboardButton(text="\U0001F50A Bass Boost", callback_data="prev_bass"),
         InlineKeyboardButton(text="\U0001F30A Reverb", callback_data="prev_reverb")],
        [InlineKeyboardButton(text="\U0001F3A9 8D", callback_data="prev_8d")]
    ])

def get_admin_panel():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="\U0001F4CA آمار کامل", callback_data="admin_stats")],
        [InlineKeyboardButton(text="\U0001F3AF محبوب‌ترین افکت‌ها", callback_data="admin_effects")],
        [InlineKeyboardButton(text="\U0001F4E3 پیام همگانی", callback_data="admin_broadcast")]
    ])

def get_preview_buttons(effect):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="\U0001F4E5 نسخه کاملشو بده", callback_data=f"full_{effect}")],
        [InlineKeyboardButton(text="\U0001F501 یه افکت دیگه روی همین آهنگ", callback_data="back_effects")],
    ])

def get_after_full_buttons():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="\U0001F501 یه افکت دیگه روی همین آهنگ", callback_data="back_effects")],
        [InlineKeyboardButton(text="\U0001F3B5 آهنگ جدید", callback_data="new_song")],
    ])

SUFFIX = {
    "slowed": "(slowed)",
    "slowed_reverb": "(slowed + reverb)",
    "speedup": "(sped up)",
    "nightcore": "(nightcore)",
    "bass": "(bass boosted)",
    "reverb": "(reverb)",
    "8d": "(8d audio)"
}

EFFECT_EMOJI = {
    "slowed": "\U0001F40C",
    "slowed_reverb": "\U0001F3A7",
    "speedup": "\u26A1",
    "nightcore": "\U0001F303",
    "bass": "\U0001F50A",
    "reverb": "\U0001F30A",
    "8d": "\U0001F3A9"
}

EFFECT_FA = {
    "slowed": "Slowed",
    "slowed_reverb": "Slowed + Reverb",
    "speedup": "Speed Up",
    "nightcore": "Nightcore",
    "bass": "Bass Boost",
    "reverb": "Reverb",
    "8d": "8D"
}

FILTERS = {
    "slowed": "asetrate=44100*0.8,aresample=44100,volume=6dB,alimiter=limit=0.95",
    "slowed_reverb": "asetrate=44100*0.8,aresample=44100,aecho=0.8:0.7:60:0.25,volume=8dB,alimiter=limit=0.95,aresample=44100",
    "speedup": "atempo=1.25,aresample=44100,volume=3dB,alimiter=limit=0.95",
    "nightcore": "asetrate=44100*1.25,aresample=44100,volume=3dB,alimiter=limit=0.95",
    "bass": "bass=g=12:f=110:w=0.6,aresample=44100,volume=4dB,alimiter=limit=0.95",
    "reverb": "aecho=0.8:0.9:1000:0.3,aresample=44100,volume=5dB,alimiter=limit=0.95",
    "8d": "aformat=channel_layouts=stereo,apulsator=hz=0.125,volume=3dB,alimiter=limit=0.95"
}

DURATION_FACTOR = {
    "slowed": 1/0.8, "slowed_reverb": 1/0.8,
    "speedup": 1/1.25, "nightcore": 1/1.25,
    "bass": 1.0, "reverb": 1.0, "8d": 1.0
}

LINE = "\u2501" * 18

def build_names(info, effect):
    suffix = SUFFIX.get(effect, effect)
    orig = info.get("title") or os.path.splitext(info.get("file_name", "music"))[0]
    orig = orig.strip()
    return f"{orig} {suffix}", info.get("performer") or orig, f"{orig} {suffix}.mp3"

async def make_thumb(info, tag):
    if not info.get("thumb_id"):
        return None
    raw = f"thumb_raw_{tag}.jpg"
    fixed = f"thumb_{tag}.jpg"
    try:
        tfile = await bot.get_file(info["thumb_id"])
        await bot.download_file(tfile.file_path, raw)
        cmd = ["ffmpeg", "-y", "-i", raw, "-vf", "scale=320:320:force_original_aspect_ratio=increase,crop=320:320", "-q:v", "5", fixed]
        p = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        await p.communicate()
        if os.path.exists(fixed) and os.path.getsize(fixed) > 0:
            return fixed
        return raw if os.path.exists(raw) else None
    except:
        return None

def cleanup(*paths):
    for p in paths:
        try:
            if p and os.path.exists(p):
                os.remove(p)
        except:
            pass

@dp.message(CommandStart())
async def start(message: types.Message):
    add_user(message.from_user)
    _, remaining = check_limit(message.from_user.id)
    await message.answer(
        f"\U0001F3A7 <b>Music Effects</b>\n{LINE}\n"
        f"سلام! به ربات افکت آهنگ خوش اومدی \u2728\n\n"
        f"\U0001F3B5 <b>چطور استفاده کنی؟</b>\n"
        f"\u2022 فایل صوتی رو همین‌جا بفرست\n\n"
        f"\U0001F39B <b>افکت‌ها</b>\n"
        f"\U0001F40C Slowed  \u2022  \U0001F3A7 Slowed + Reverb\n"
        f"\U0001F303 Nightcore  \u2022  \u26A1 Speed Up\n"
        f"\U0001F50A Bass Boost  \u2022  \U0001F30A Reverb  \u2022  \U0001F3A9 8D\n"
        f"{LINE}\n"
        f"\U0001F3AB سهم امروزت: <b>{remaining}</b> افکت\n"
        f"\U0001F447 برای شروع،
