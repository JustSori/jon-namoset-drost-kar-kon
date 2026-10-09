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

# ---------- دیتابیس ----------
DB = "bot.db"
con = sqlite3.connect(DB, check_same_thread=False)
cur = con.cursor()
cur.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, username TEXT, name TEXT, start_count INTEGER DEFAULT 0)")
cur.execute("CREATE TABLE IF NOT EXISTS stats (key TEXT PRIMARY KEY, value INTEGER DEFAULT 0)")
cur.execute("INSERT OR IGNORE INTO stats VALUES ('processed', 0)")
cur.execute("CREATE TABLE IF NOT EXISTS effect_stats (effect TEXT PRIMARY KEY, count INTEGER DEFAULT 0)")
cur.execute("CREATE TABLE IF NOT EXISTS daily_usage (user_id INTEGER, date TEXT, count INTEGER DEFAULT 0, PRIMARY KEY(user_id, date))")
cur.execute("CREATE TABLE IF NOT EXISTS daily_total (date TEXT PRIMARY KEY, count INTEGER DEFAULT 0)")
cur.execute("""CREATE TABLE IF NOT EXISTS history (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER,
  file_id TEXT,
  track TEXT,
  performer TEXT,
  file_name TEXT,
  thumb_id TEXT,
  duration INTEGER,
  effect TEXT DEFAULT '',
  created INTEGER
)""")
con.commit()

# ---------- قالب ----------
LINE = "﹏﹏﹏﹏﹏﹏﹏﹏﹏﹏"

def box(stage, body, footer=""):
    t = f"<b>{stage}</b>\n{LINE}\n{body}"
    if footer:
        t += f"\n\n👉 {footer}"
    return t

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
    return total, starts, proc, (row[0] if row else 0)

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

def add_history(user_id, info):
    cur.execute("INSERT INTO history (user_id, file_id, track, performer, file_name, thumb_id, duration, effect, created) VALUES (?,?,?,?,?,?,?,?,?)",
        (user_id, info["file_id"],
         info.get("title") or os.path.splitext(info.get("file_name","music"))[0],
         info.get("performer") or "ناشناس",
         info.get("file_name") or "", info.get("thumb_id") or "",
         info.get("duration") or 0, "", int(time.time())))
    con.commit()
    cur.execute("DELETE FROM history WHERE id NOT IN (SELECT id FROM history WHERE user_id=? ORDER BY created DESC LIMIT 10)", (user_id,))
    con.commit()

def set_last_effect(user_id, effect):
    cur.execute("UPDATE history SET effect=? WHERE id = (SELECT id FROM history WHERE user_id=? ORDER BY created DESC LIMIT 1)", (effect, user_id))
    con.commit()

def get_history(user_id):
    cur.execute("SELECT id, file_id, track, performer, file_name, thumb_id, duration, effect FROM history WHERE user_id=? ORDER BY created DESC", (user_id,))
    return cur.fetchall()

# ---------- کیبوردها ----------
def get_start_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📖 راهنما", callback_data="show_help")],
        [InlineKeyboardButton(text="🎧 لیست افکت‌ها", callback_data="show_effects")],
        [InlineKeyboardButton(text="🎶 موزیک‌های من", callback_data="show_history")],
    ])

def get_buttons():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🐌 Slowed", callback_data="prev_slowed"),
         InlineKeyboardButton(text="🎧 Slowed + Reverb", callback_data="prev_slowed_reverb")],
        [InlineKeyboardButton(text="🌃 Nightcore", callback_data="prev_nightcore"),
         InlineKeyboardButton(text="⚡️ Speed Up", callback_data="prev_speedup")],
        [InlineKeyboardButton(text="🔊 Bass Boost", callback_data="prev_bass"),
         InlineKeyboardButton(text="🌊 Reverb", callback_data="prev_reverb")],
        [InlineKeyboardButton(text="🎩 8D Audio", callback_data="prev_8d")],
        [InlineKeyboardButton(text="❌ کنسل", callback_data="cancel_action")],
    ])

def get_admin_panel():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 آمار کامل", callback_data="admin_stats")],
        [InlineKeyboardButton(text="🎯 محبوب‌ترین افکت‌ها", callback_data="admin_effects")],
        [InlineKeyboardButton(text="📣 پیام همگانی", callback_data="admin_broadcast")]
    ])

def get_quality_keyboard(effect):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🟢 128k | سبک", callback_data=f"go_{effect}_128")],
        [InlineKeyboardButton(text="🟡 192k | متعادل", callback_data=f"go_{effect}_192")],
        [InlineKeyboardButton(text="🔴 320k | بهترین", callback_data=f"go_{effect}_320")],
        [InlineKeyboardButton(text="🔙 برگشت", callback_data="back_effects")],
    ])

def get_after_full_buttons(bot_username):
    share_url = f"https://t.me/share/url?url=https://t.me/{bot_username}&text=ببین آهنگمو چطور خفن کردم 😎🔥"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔥 بفرست برای رفیقت", url=share_url)],
        [InlineKeyboardButton(text="🎶 یه افکت دیگه", callback_data="back_effects")],
        [InlineKeyboardButton(text="🎧 آهنگ جدید", callback_data="new_song")],
    ])

def get_cancel_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ کنسل و خروج", callback_data="cancel_broadcast")]
    ])

def build_history_keyboard(rows):
    kb = []
    for (hid, fid, track, perf, fn, th, dur, eff) in rows:
        kb.append([InlineKeyboardButton(text=f"🎵 {track[:25]}", callback_data=f"hist_{hid}")])
    kb.append([InlineKeyboardButton(text="❌ کنسل", callback_data="cancel_action")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def format_history_text(rows):
    lines = []
    for i, (hid, fid, track, perf, fn, th, dur, eff) in enumerate(rows, 1):
        if eff:
            em = EFFECT_EMOJI.get(eff, "🎧")
            fa = EFFECT_FA.get(eff, eff)
            lines.append(f"{i}. {em} <b>{track}</b>\n   👤 {perf} | 🎛 {fa}")
        else:
            lines.append(f"{i}. 🎵 <b>{track}</b>\n   👤 {perf} | بدون افکت")
    return "\n\n".join(lines)

SUFFIX = {"slowed":"(slowed)","slowed_reverb":"(slowed + reverb)","speedup":"(sped up)","nightcore":"(nightcore)","bass":"(bass boosted)","reverb":"(reverb)","8d":"(8d audio)"}
EFFECT_EMOJI = {"slowed":"🐌","slowed_reverb":"🎧","speedup":"⚡️","nightcore":"🌃","bass":"🔊","reverb":"🌊","8d":"🎩"}
EFFECT_FA = {"slowed":"Slowed","slowed_reverb":"Slowed + Reverb","speedup":"Speed Up","nightcore":"Nightcore","bass":"Bass Boost","reverb":"Reverb","8d":"8D"}
FILTERS = {
    "slowed": "asetrate=44100*0.8,aresample=44100,volume=6dB,alimiter=limit=0.95",
    "slowed_reverb": "asetrate=44100*0.8,aresample=44100,aecho=0.8:0.7:60:0.25,volume=8dB,alimiter=limit=0.95,aresample=44100",
    "speedup": "atempo=1.25,aresample=44100,volume=3dB,alimiter=limit=0.95",
    "nightcore": "asetrate=44100*1.25,aresample=44100,volume=3dB,alimiter=limit=0.95",
    "bass": "bass=g=12:f=110:w=0.6,aresample=44100,volume=4dB,alimiter=limit=0.95",
    "reverb": "aecho=0.8:0.9:1000:0.3,aresample=44100,volume=5dB,alimiter=limit=0.95",
    "8d": "aformat=channel_layouts=stereo,apulsator=hz=0.125,volume=3dB,alimiter=limit=0.95"
}
DURATION_FACTOR = {"slowed":1/0.8,"slowed_reverb":1/0.8,"speedup":1/1.25,"nightcore":1/1.25,"bass":1.0,"reverb":1.0,"8d":1.0}

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
        cmd = ["ffmpeg","-y","-i",raw,"-vf","scale=320:320:force_original_aspect_ratio=increase,crop=320:320","-q:v","5",fixed]
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

async def animate_progress(message: types.Message, emoji: str, suffix: str, stop_event: asyncio.Event):
    frames = ["◐","◑","◒","◓"]
    bars = ["▱▱▱▱▱","▰▱▱▱▱","▰▰▱▱▱","▰▰▰▱▱","▰▰▰▰▱","▰▰▰▰▰"]
    i = 0
    while not stop_event.is_set():
        f = frames[i % len(frames)]
        b = bars[(i // 2) % len(bars)]
        try:
            await message.edit_text(box("⏳ داره ساخته می‌شه", f"{emoji} <b>{suffix}</b>\n\n{f} {b}", "صبر کن، پیام رو پاک نکن 🙏"), parse_mode="HTML")
        except:
            pass
        i += 1
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=0.8)
        except asyncio.TimeoutError:
            pass

@dp.message(CommandStart())
async def start(message: types.Message):
    add_user(message.from_user)
    await message.answer(
        box("👋 سلام رفیق",
            "اینجا قراره آهنگ‌هات یه حس دیگه بگیرن 🚀\n\n🐌 دپ و آروم\n🌃 پرانرژی\n🔊 بیس‌دار\n🎩 سه‌بعدی",
            "همین الان یه موزیک بفرست"),
        reply_markup=get_start_keyboard(), parse_mode="HTML")

@dp.message(Command("help"))
async def help_cmd(message: types.Message):
    await message.answer(box("📖 چطور غوغا کنیم؟",
        "🎵 <b>قدم اول:</b> یه آهنگ بفرست\n🎛 <b>قدم دوم:</b> وایب موردتو انتخاب کن\n⚡️ <b>قدم سوم:</b> پیش‌نمایش ۳۰ ثانیه‌ای گوش کن\n🔥 <b>قدم آخر:</b> کیفیت رو بزن و نسخه کامل رو قاب کن",
        "با «🎶 یه افکت دیگه» همه وایب‌ها رو روی یه آهنگ تست کن"), parse_mode="HTML")

@dp.message(Command("cancel"))
async def cancel_cmd(message: types.Message):
    broadcast_wait.discard(message.from_user.id)
    user_files.pop(message.from_user.id, None)
    await message.answer(box("❌ لغو شد", "همه‌چی پاک شد.", "یه آهنگ جدید بفرست"), parse_mode="HTML")

@dp.message(Command("mymusic"))
@dp.message(Command("my"))
async def mymusic_cmd(message: types.Message):
    rows = get_history(message.from_user.id)
    if not rows:
        await message.answer(box("🍃 هنوز چیزی نساختی", "هنوز هیچ آهنگی نفرستادی!\nبفرست تا اولین شاهکارتو بسازیم 🎶", "یه آهنگ بفرست"), parse_mode="HTML")
        return
    await message.answer(box(f"🎶 موزیک‌های تو ({len(rows)})", format_history_text(rows), "بزن روش تا دوباره افکت بزنی"),
        reply_markup=build_history_keyboard(rows), parse_mode="HTML")

@dp.message(Command("admin"))
async def admin(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    total, starts, proc, today = get_stats()
    await message.answer(box("👑 پنل ادمین", f"👥 کاربران: <b>{total}</b>\n▶️ استارت: <b>{starts}</b>\n🎧 کل خروجی: <b>{proc}</b>\n📅 امروز: <b>{today}</b>", ""),
        reply_markup=get_admin_panel(), parse_mode="HTML")

@dp.message(F.audio | F.voice | F.document)
async def handle_music(message: types.Message):
    if message.from_user.id in broadcast_wait and message.from_user.id in ADMIN_IDS:
        broadcast_wait.discard(message.from_user.id)
        users = get_all_users()
        status = await message.reply(f"📣 <b>در حال ارسال به {len(users)} نفر...</b>", parse_mode="HTML")
        ok = fail = 0
        for uid in users:
            try:
                await bot.copy_message(uid, message.chat.id, message.message_id)
                ok += 1
            except:
                fail += 1
            await asyncio.sleep(0.05)
        await status.edit_text(f"✅ تموم شد\n📗 موفق: <b>{ok}</b>\n📕 ناموفق: <b>{fail}</b>", parse_mode="HTML")
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
        if "audio" in (message.document.mime_type or ""):
            file_id = message.document.file_id
            file_name = message.document.file_name or "music.mp3"
            if message.document.thumbnail:
                thumb_id = message.document.thumbnail.file_id
    if not file_id:
        await message.reply("فایل نامعتبره! یه فایل صوتی بفرست.")
        return
    user_files[message.from_user.id] = {"file_id": file_id, "title": title, "performer": performer, "duration": duration, "thumb_id": thumb_id, "file_name": file_name}
    add_history(message.from_user.id, user_files[message.from_user.id])
    show_name = title or os.path.splitext(file_name)[0]
    show_perf = performer or "ناشناس"
    await message.answer(box("✅ آهنگ رسید", f"🎵 <b>{show_name}</b>\n👤 {show_perf}\n\nعجب انتخابی! بذار ببینیم کدوم وایب بهش میاد 🤔", "یه افکت انتخاب کن"),
        reply_markup=get_buttons(), parse_mode="HTML")

@dp.callback_query()
async def callbacks(callback: types.CallbackQuery):
    data = callback.data or ""
    if data == "cancel_action":
        user_files.pop(callback.from_user.id, None)
        await callback.message.edit_text(box("❌ لغو شد", "همه‌چی پاک شد.", "یه آهنگ جدید بفرست"), parse_mode="HTML")
        await callback.answer()
        return
    if data == "cancel_broadcast":
        broadcast_wait.discard(callback.from_user.id)
        await callback.message.edit_text("❌ پیام همگانی لغو شد.", reply_markup=get_admin_panel())
        await callback.answer()
        return
    if data == "show_help":
        await callback.message.answer(box("📖 چطور غوغا کنیم؟", "یه فایل بفرست، افکت انتخاب کن، پیش‌نمایش بگیر، کیفیت رو بزن.", "راهنمای کامل: /help"), parse_mode="HTML")
        await callback.answer()
        return
    if data == "show_effects":
        await callback.message.answer(box("🎧 وایب‌ها", "🐌 Slowed\n🎧 Slowed + Reverb\n🌃 Nightcore\n⚡️ Speed Up\n🔊 Bass Boost\n🌊 Reverb\n🎩 8D", "یه آهنگ بفرست تا امتحانشون کنی"), parse_mode="HTML")
        await callback.answer()
        return
    if data == "show_history":
        rows = get_history(callback.from_user.id)
        if not rows:
            await callback.answer("هنوز چیزی نفرستادی!", show_alert=True)
            return
        await callback.message.answer(box(f"🎶 موزیک‌های تو ({len(rows)})", format_history_text(rows), "بزن روش تا دوباره افکت بزنی"),
            reply_markup=build_history_keyboard(rows), parse_mode="HTML")
        await callback.answer()
        return
    if data.startswith("hist_"):
        try:
            hid = int(data.split("_")[1])
            rows = get_history(callback.from_user.id)
            row = next((r for r in rows if r[0] == hid), None)
            if not row:
                await callback.answer("پیداش نکردم!", show_alert=True)
                return
            _, fid, track, perf, fn, th, dur, eff = row
            user_files[callback.from_user.id] = {"file_id": fid, "title": track, "performer": perf if perf != "ناشناس" else None, "duration": dur, "thumb_id": th, "
