import asyncio
import os
import sqlite3
import time
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile, BotCommand
from aiogram.filters import CommandStart, Command
from aiohttp import web

TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise ValueError("BOT_TOKEN تنظیم نشده است.")

ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_ID", "0").split(",") if x.strip().isdigit()]
DAILY_LIMIT = int(os.getenv("DAILY_LIMIT", "20"))

bot = Bot(token=TOKEN)
dp = Dispatcher()
user_files = {}
broadcast_wait = set()
user_nav = {}
processing = set()

DB = "bot.db"
con = sqlite3.connect(DB, check_same_thread=False)
cur = con.cursor()
cur.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, username TEXT, name TEXT, start_count INTEGER DEFAULT 0)")
cur.execute("CREATE TABLE IF NOT EXISTS stats (key TEXT PRIMARY KEY, value INTEGER DEFAULT 0)")
cur.execute("INSERT OR IGNORE INTO stats VALUES ('processed', 0)")
cur.execute("CREATE TABLE IF NOT EXISTS effect_stats (effect TEXT PRIMARY KEY, count INTEGER DEFAULT 0)")
cur.execute("""CREATE TABLE IF NOT EXISTS history (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER, file_id TEXT, track TEXT, performer TEXT,
  file_name TEXT, thumb_id TEXT, duration INTEGER,
  effect TEXT DEFAULT '', created INTEGER
)""")
cur.execute("""CREATE TABLE IF NOT EXISTS favorites (
  user_id INTEGER, hist_id INTEGER, created INTEGER,
  PRIMARY KEY (user_id, hist_id)
)""")
cur.execute("CREATE TABLE IF NOT EXISTS bans (user_id INTEGER PRIMARY KEY, reason TEXT, created INTEGER)")
con.commit()

try:
    cur.execute("SELECT joined_at FROM users LIMIT 1")
except Exception:
    try:
        cur.execute("ALTER TABLE users ADD COLUMN joined_at INTEGER DEFAULT 0")
        con.commit()
    except Exception:
        pass

SUFFIX = {"slowed":"(slowed)","slowed_reverb":"(slowed + reverb)","speedup":"(sped up)","nightcore":"(nightcore)","bass":"(bass boosted)","reverb":"(reverb)","8d":"(8d audio)"}
EFFECT_EMOJI = {"slowed":"🐌","slowed_reverb":"🎧","speedup":"⚡️","nightcore":"🌃","bass":"🔊","reverb":"🌊","8d":"🎩"}
EFFECT_FA = {"slowed":"Slowed","slowed_reverb":"Slowed + Reverb","speedup":"Speed Up","nightcore":"Nightcore","bass":"Bass Boost","reverb":"Reverb","8d":"8D"}
FILTERS = {
    "slowed": "asetrate=44100*0.85,aresample=44100,volume=6dB,alimiter=limit=0.95",
    "slowed_reverb": "asetrate=44100*0.85,aresample=44100,aecho=0.8:0.7:60:0.3,volume=6dB,alimiter=limit=0.95,aresample=44100",
    "speedup": "asetrate=44100*1.25,aresample=44100,volume=3dB,alimiter=limit=0.95",
    "nightcore": "asetrate=44100*1.25,aresample=44100,volume=3dB,alimiter=limit=0.95",
    "bass": "bass=g=12:f=110:w=0.6,aresample=44100,volume=4dB,alimiter=limit=0.95",
    "reverb": "aecho=0.8:0.9:1000:0.3,aresample=44100,volume=5dB,alimiter=limit=0.95",
    "8d": "aformat=channel_layouts=stereo,apulsator=hz=0.125,volume=3dB,alimiter=limit=0.95"
}
DURATION_FACTOR = {"slowed":1/0.85,"slowed_reverb":1/0.85,"speedup":1/1.25,"nightcore":1/1.25,"bass":1.0,"reverb":1.0,"8d":1.0}

def box(stage, body, footer=""):
    t = f"{stage}\n\n<blockquote>{body}</blockquote>"
    if footer:
        t += f"\n\n{footer}"
    return t

def day_start_ts():
    d = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    return int(d.timestamp())

def add_user(u: types.User):
    now = int(time.time())
    cur.execute("INSERT OR IGNORE INTO users (user_id, username, name, start_count, joined_at) VALUES (?,?,?,?,?)", (u.id, u.username or "", u.first_name or "", 0, now))
    cur.execute("UPDATE users SET username=?, name=?, start_count=start_count+1 WHERE user_id=?", (u.username or "", u.first_name or "", u.id))
    cur.execute("UPDATE users SET joined_at=? WHERE user_id=? AND (joined_at IS NULL OR joined_at=0)", (now, u.id))
    con.commit()

def is_banned(uid):
    cur.execute("SELECT 1 FROM bans WHERE user_id=?", (uid,))
    return cur.fetchone() is not None

def ban_user(uid, reason=""):
    cur.execute("INSERT OR REPLACE INTO bans (user_id, reason, created) VALUES (?,?,?)", (uid, reason, int(time.time())))
    con.commit()

def unban_user(uid):
    cur.execute("DELETE FROM bans WHERE user_id=?", (uid,))
    con.commit()

def get_bans():
    cur.execute("SELECT user_id, reason FROM bans ORDER BY created DESC")
    return cur.fetchall()

def today_count(uid):
    ds = day_start_ts()
    cur.execute("SELECT COUNT(*) FROM history WHERE user_id=? AND created>=? AND effect!=''", (uid, ds))
    return cur.fetchone()[0] or 0

def check_limit(uid):
    if DAILY_LIMIT <= 0:
        return True, 0
    c = today_count(uid)
    return (c < DAILY_LIMIT), c

def get_stats():
    cur.execute("SELECT COUNT(*) FROM users")
    total = cur.fetchone()[0]
    cur.execute("SELECT SUM(start_count) FROM users")
    starts = cur.fetchone()[0] or 0
    cur.execute("SELECT value FROM stats WHERE key='processed'")
    proc = cur.fetchone()[0]
    return total, starts, proc

def get_daily_stats():
    ds = day_start_ts()
    cur.execute("SELECT COUNT(*) FROM users WHERE joined_at>=?", (ds,))
    new_users = cur.fetchone()[0] or 0
    cur.execute("SELECT COUNT(*) FROM history WHERE created>=?", (ds,))
    songs_today = cur.fetchone()[0] or 0
    cur.execute("SELECT COUNT(*) FROM history WHERE created>=? AND effect!=''", (ds,))
    made_today = cur.fetchone()[0] or 0
    cur.execute("SELECT COUNT(DISTINCT user_id) FROM history WHERE created>=?", (ds,))
    active = cur.fetchone()[0] or 0
    cur.execute("SELECT effect, COUNT(*) c FROM history WHERE created>=? AND effect!='' GROUP BY effect ORDER BY c DESC LIMIT 3", (ds,))
    top = cur.fetchall()
    return new_users, songs_today, made_today, active, top

def get_all_users():
    cur.execute("SELECT user_id FROM users")
    return [r[0] for r in cur.fetchall()]

def get_effect_stats():
    cur.execute("SELECT effect, count FROM effect_stats ORDER BY count DESC")
    return cur.fetchall()

def inc_usage(effect: str):
    cur.execute("UPDATE stats SET value=value+1 WHERE key='processed'")
    cur.execute("INSERT OR IGNORE INTO effect_stats (effect, count) VALUES (?,0)", (effect,))
    cur.execute("UPDATE effect_stats SET count=count+1 WHERE effect=?", (effect,))
    con.commit()

def add_history(user_id, info):
    cur.execute("INSERT INTO history (user_id, file_id, track, performer, file_name, thumb_id, duration, effect, created) VALUES (?,?,?,?,?,?,?,?,?)",
        (user_id, info["file_id"],
         info.get("title") or os.path.splitext(info.get("file_name","music"))[0],
         info.get("performer") or "نامشخص",
         info.get("file_name") or "", info.get("thumb_id") or "",
         info.get("duration") or 0, "", int(time.time())))
    con.commit()
    cur.execute("DELETE FROM history WHERE user_id=? AND id NOT IN (SELECT id FROM history WHERE user_id=? ORDER BY created DESC LIMIT 10)", (user_id, user_id))
    con.commit()

def set_last_effect(user_id, effect):
    cur.execute("UPDATE history SET effect=? WHERE id = (SELECT id FROM history WHERE user_id=? ORDER BY created DESC LIMIT 1)", (effect, user_id))
    con.commit()

def get_history(user_id):
    cur.execute("SELECT id, file_id, track, performer, file_name, thumb_id, duration, effect FROM history WHERE user_id=? ORDER BY created DESC", (user_id,))
    return cur.fetchall()

def is_fav(uid, hid):
    cur.execute("SELECT 1 FROM favorites WHERE user_id=? AND hist_id=?", (uid, hid))
    return cur.fetchone() is not None

def toggle_fav(uid, hid):
    if is_fav(uid, hid):
        cur.execute("DELETE FROM favorites WHERE user_id=? AND hist_id=?", (uid, hid))
        con.commit()
        return False
    cur.execute("INSERT OR IGNORE INTO favorites (user_id, hist_id, created) VALUES (?,?,?)", (uid, hid, int(time.time())))
    con.commit()
    return True

def get_favs(uid):
    cur.execute("""SELECT h.id, h.file_id, h.track, h.performer, h.file_name, h.thumb_id, h.duration, h.effect
      FROM favorites f JOIN history h ON h.id=f.hist_id WHERE f.user_id=? ORDER BY f.created DESC""", (uid,))
    return cur.fetchall()

def get_user_profile(user_id):
    cur.execute("SELECT username, name, start_count, joined_at FROM users WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    if not row:
        return None
    username, name, starts, joined = row
    cur.execute("SELECT COUNT(*) FROM history WHERE user_id=?", (user_id,))
    songs = cur.fetchone()[0] or 0
    cur.execute("SELECT COUNT(*) FROM history WHERE user_id=? AND effect!=''", (user_id,))
    made = cur.fetchone()[0] or 0
    cur.execute("SELECT effect, COUNT(*) c FROM history WHERE user_id=? AND effect!='' GROUP BY effect ORDER BY c DESC LIMIT 1", (user_id,))
    top = cur.fetchone()
    top_effect = top[0] if top else ""
    cur.execute("SELECT COUNT(*) FROM favorites WHERE user_id=?", (user_id,))
    favc = cur.fetchone()[0] or 0
    try:
        jdate = datetime.fromtimestamp(joined).strftime("%Y/%m/%d") if joined else "نامشخص"
    except:
        jdate = "نامشخص"
    ok, tc = check_limit(user_id)
    left = max(DAILY_LIMIT - tc, 0) if DAILY_LIMIT > 0 else "نامحدود"
    return {"username": username or "", "name": name or "", "starts": starts or 0, "joined": jdate, "songs": songs, "made": made, "top": top_effect, "favc": favc, "left": left}

def build_profile_text(p, user_id):
    if not p:
        return "هنوز پروفایلی ثبت نشده. /start رو بزن."
    fav = f"{EFFECT_EMOJI.get(p['top'],'🎧')} {EFFECT_FA.get(p['top'], p['top'])}" if p["top"] else "—"
    uname = f"@{p['username']}" if p["username"] else "—"
    body = (f"👤 نام: <b>{p['name']}</b>\n"
            f"🆔 آیدی: <code>{user_id}</code>\n"
            f"🔗 یوزرنیم: {uname}\n"
            f"📅 عضویت: {p['joined']}\n"
            f"🎶 آهنگ‌ها: {p['songs']} | 🎧 ساخته‌ها: {p['made']}\n"
            f"❤️ علاقه‌مندی‌ها: {p['favc']}\n"
            f"⭐ محبوب‌ترین افکت: {fav}\n"
            f"📊 سهم امروز: {p['left']}")
    return box("👤 پروفایل من", body, "👇 از دکمه‌ها استفاده کن:")

def get_profile_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎶 آهنگ‌های من", callback_data="show_history")],
        [InlineKeyboardButton(text="❤️ علاقه‌مندی‌ها", callback_data="show_favs")],
        [InlineKeyboardButton(text="🎧 مشاهده افکت‌ها", callback_data="show_effects")],
        [InlineKeyboardButton(text="❌ بستن", callback_data="cancel_action")],
    ])

async def send_profile(user_id, chat_id, from_cb=False, message=None):
    p = get_user_profile(user_id)
    txt = build_profile_text(p, user_id)
    if from_cb and message is not None:
        await try_delete(chat_id, message.message_id)
    await clear_nav(user_id, chat_id)
    m = await bot.send_message(chat_id, txt, reply_markup=get_profile_keyboard(), parse_mode="HTML")
    await nav_push(user_id, m.message_id)

def build_names(info, effect):
    suffix = SUFFIX.get(effect, effect)
    orig = info.get("title") or os.path.splitext(info.get("file_name", "music"))[0]
    orig = orig.strip() or "music"
    return f"{orig} {suffix}", info.get("performer") or orig, f"{orig} {suffix}.mp3"

def cleanup(*paths):
    for p in paths:
        try:
            if p and os.path.exists(p):
                os.remove(p)
        except:
            pass

async def clear_nav(user_id, chat_id, keep_id=None):
    lst = user_nav.get(user_id, [])
    for mid in lst:
        if keep_id and mid == keep_id:
            continue
        try:
            await bot.delete_message(chat_id, mid)
        except:
            pass
    if keep_id:
        user_nav[user_id] = [keep_id]
    else:
        user_nav[user_id] = []

async def nav_push(user_id, msg_id):
    lst = user_nav.get(user_id, [])
    lst.append(msg_id)
    user_nav[user_id] = lst[-5:]

async def try_delete(chat_id, msg_id):
    try:
        await bot.delete_message(chat_id, msg_id)
    except:
        pass

def get_start_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👤 پروفایل من", callback_data="show_profile")],
        [InlineKeyboardButton(text="🎶 آهنگ‌های من", callback_data="show_history"),
         InlineKeyboardButton(text="❤️ علاقه‌مندی‌ها", callback_data="show_favs")],
        [InlineKeyboardButton(text="📖 راهنما", callback_data="show_help")],
        [InlineKeyboardButton(text="🎧 مشاهده افکت‌ها", callback_data="show_effects")],
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
        [InlineKeyboardButton(text="❌ انصراف", callback_data="cancel_action")],
    ])

def get_admin_panel():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 آمار کلی", callback_data="admin_stats")],
        [InlineKeyboardButton(text="📅 آمار امروز", callback_data="admin_daily")],
        [InlineKeyboardButton(text="🎯 تحلیل افکت‌ها", callback_data="admin_effects")],
        [InlineKeyboardButton(text="⛔ لیست بن", callback_data="admin_bans")],
        [InlineKeyboardButton(text="📣 ارسال همگانی", callback_data="admin_broadcast")]
    ])

def get_quality_keyboard(effect):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🟢 کیفیت 128 | حجم کم", callback_data=f"go_{effect}_128")],
        [InlineKeyboardButton(text="🟡 کیفیت 192 | استاندارد", callback_data=f"go_{effect}_192")],
        [InlineKeyboardButton(text="🔴 کیفیت 320 | حداکثر", callback_data=f"go_{effect}_320")],
        [InlineKeyboardButton(text="🔙 بازگشت", callback_data="back_effects")],
    ])

def get_after_full_buttons(bot_username):
    share_url = f"https://t.me/share/url?url=https://t.me/{bot_username}&text=این موزیک را با افکت گوش کنید 🎧"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="↗️ اشتراک‌گذاری", url=share_url)],
        [InlineKeyboardButton(text="🎶 اعمال افکت دیگر", callback_data="back_effects")],
        [InlineKeyboardButton(text="🎧 فایل جدید", callback_data="new_song")],
    ])

def get_cancel_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ انصراف", callback_data="cancel_broadcast")]
    ])

def build_history_keyboard(rows, uid):
    kb = []
    for (hid, fid, track, perf, fn, th, dur, eff) in rows:
        em = EFFECT_EMOJI.get(eff, "🎵") if eff else "🎵"
        heart = "❤️" if is_fav(uid, hid) else "🤍"
        kb.append([InlineKeyboardButton(text=f"{em} {track[:22]}", callback_data=f"hist_{hid}"),
                   InlineKeyboardButton(text=heart, callback_data=f"fav_{hid}")])
    kb.append([InlineKeyboardButton(text="❌ انصراف", callback_data="cancel_action")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def format_history_text(rows):
    lines = []
    for i, (hid, fid, track, perf, fn, th, dur, eff) in enumerate(rows, 1):
        if eff:
            fa = EFFECT_FA.get(eff, eff)
            em = EFFECT_EMOJI.get(eff, "🎧")
            lines.append(f"{i}. {em} <b>{track}</b>\n👤 {perf}\n🎛 افکت: {fa}")
        else:
            lines.append(f"{i}. 🎵 <b>{track}</b>\n👤 {perf}\n⏳ بدون افکت")
    return "🎶 <b>آهنگ‌های من</b>\n\nبرای انتخاب روی اسم بزن، برای علاقه‌مندی روی 🤍 بزن.\n\n" + "\n\n🤍\n\n".join(lines)

def format_fav_text(rows):
    if not rows:
        return "❤️ هنوز چیزی به علاقه‌مندی‌ها اضافه نکردی."
    lines = []
    for i, (hid, fid, track, perf, fn, th, dur, eff) in enumerate(rows, 1):
        em = EFFECT_EMOJI.get(eff, "🎵") if eff else "🎵"
        lines.append(f"{i}. {em} <b>{track}</b>\n👤 {perf}")
    return "❤️ <b>علاقه‌مندی‌ها</b>\n\n" + "\n\n".join(lines)

def format_daily_text():
    nu, songs, made, active, top = get_daily_stats()
    if top:
        t = "\n".join([f"{EFFECT_EMOJI.get(e,'🎧')} {EFFECT_FA.get(e,e)}: {c}" for e, c in top])
    else:
        t = "هنوز فعالیتی ثبت نشده."
    return box("📅 آمار امروز", f"🆕 کاربران جدید: {nu}\n🎶 آهنگ امروز: {songs}\n🎧 خروجی امروز: {made}\n🔥 کاربران فعال: {active}\n\n⭐ تاپ امروز:\n{t}")

async def extract_cover_from_input(in_path, tag):
    out = f"thumb_embed_{tag}.jpg"
    cmd = ["ffmpeg","-y","-i",in_path,"-map","0:v","-vframes","1","-q:v","5",out]
    p = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
    await p.communicate()
    if os.path.exists(out) and os.path.getsize(out) > 0:
        return out
    cleanup(out)
    return None

async def make_thumb(info, tag, in_path=None):
    raw = f"thumb_raw_{tag}.jpg"
    fixed = f"thumb_{tag}.jpg"
    try:
        src = None
        if info.get("thumb_id"):
            tfile = await bot.get_file(info["thumb_id"])
            await bot.download_file(tfile.file_path, raw)
            src = raw
        elif in_path and os.path.exists(in_path):
            ext = await extract_cover_from_input(in_path, tag)
            if ext:
                cmd = ["ffmpeg","-y","-i",ext,"-vf","scale=320:320:force_original_aspect_ratio=increase,crop=320:320","-q:v","9",fixed]
                p = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
                await p.communicate()
                cleanup(ext, raw)
                if os.path.exists(fixed) and 0 < os.path.getsize(fixed) < 200*1024:
                    return fixed
                return None
            else:
                return None
        if not src or not os.path.exists(src):
            return None
        cmd = ["ffmpeg","-y","-i",src,"-vf","scale=320:320:force_original_aspect_ratio=increase,crop=320:320","-q:v","9",fixed]
        p = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        await p.communicate()
        if os.path.exists(fixed) and 0 < os.path.getsize(fixed) < 200*1024:
            cleanup(raw)
            return fixed
        return None
    except:
        return None

async def animate_progress(message: types.Message, effect: str, bitrate: str, stop_event: asyncio.Event):
    emoji = EFFECT_EMOJI.get(effect, "🎧")
    fa = EFFECT_FA.get(effect, effect)
    spinners = ["⠋","⠙","⠹","⠸","⠼","⠴","⠦","⠧","⠇","⠏"]
    i = 0
    total = 12
    while not stop_event.is_set():
        pct = min(5 + i * 4, 97)
        filled = int(pct / 100 * total)
        bar = "▰" * filled + "▱" * (total - filled)
        spin = spinners[i % len(spinners)]
        txt = (f"{emoji} <b>در حال ساخت آهنگ...</b> {spin}\n\n"
               f"<blockquote>🎛 افکت: <b>{fa}</b>\n📀 کیفیت: <b>{bitrate}kbps</b></blockquote>\n\n"
               f"{bar}  <b>{pct}٪</b>\n\n🎶 لطفا صبر کنید...")
        try:
            await message.edit_text(txt, parse_mode="HTML")
        except:
            pass
        i += 1
        await asyncio.sleep(0.6)
    try:
        full = "▰" * total
        await message.edit_text(f"✅ <b>تکمیل شد!</b> 🎉\n\n{full}  <b>۱۰۰٪</b>\n\n🎧 در حال ارسال...", parse_mode="HTML")
    except:
        pass

async def process_effect(chat_id, user_id, status_msg, info, effect, bitrate):
    if user_id in processing:
        try:
            await status_msg.edit_text("⏳ یه پردازش در حال انجامه، صبر کن تموم بشه بعد دوباره بزن.")
        except:
            pass
        return
    processing.add(user_id)
    tag = f"{user_id}_{int(time.time())}"
    in_path = f"in_{tag}.mp3"
    out_path = f"out_{tag}.mp3"
    thumb_path = None
    raw_thumb = f"thumb_raw_{tag}.jpg"
    embed_thumb = f"thumb_embed_{tag}.jpg"
    stop = asyncio.Event()
    anim = asyncio.create_task(animate_progress(status_msg, effect, bitrate, stop))
    try:
        f = await bot.get_file(info["file_id"])
        await bot.download_file(f.file_path, in_path)
        thumb_path = await make_thumb(info, tag, in_path)
        filt = FILTERS[effect]
        if thumb_path and os.path.exists(thumb_path):
            cmd = ["ffmpeg","-y","-i",in_path,"-i",thumb_path,"-filter:a",filt,"-map","0:a","-map","1:v",
                   "-c:a","libmp3lame","-b:a",f"{bitrate}k","-c:v","mjpeg","-disposition:v","attached_pic",
                   "-id3v2_version","3","-write_id3v2","1",out_path]
        else:
            cmd = ["ffmpeg","-y","-i",in_path,"-filter:a",filt,"-c:a","libmp3lame","-b:a",f"{bitrate}k","-id3v2_version","3",out_path]
        p = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        await p.communicate()
        if not os.path.exists(out_path) or os.path.getsize(out_path) == 0:
            stop.set()
            await anim
            await status_msg.edit_text("❌ خطا در پردازش فایل. لطفا فایل دیگری بفرستید.")
            cleanup(in_path, out_path)
            return
        title, performer, fname = build_names(info, effect)
        dur = int((info.get("duration") or 0) * DURATION_FACTOR.get(effect, 1.0))
        me = await bot.get_me()
        inc_usage(effect)
        set_last_effect(user_id, effect)
        stop.set()
        await anim
        await asyncio.sleep(0.5)
        try:
            await status_msg.delete()
        except:
            pass
        await clear_nav(user_id, chat_id)
        audio = FSInputFile(out_path, filename=fname)
        thumb = FSInputFile(thumb_path) if thumb_path and os.path.exists(thumb_path) else None
        await bot.send_audio(chat_id, audio=audio, title=title, performer=performer,
            duration=dur if dur > 0 else None, thumbnail=thumb,
            caption=f"{EFFECT_EMOJI.get(effect,'🎧')} {title}\n👤 {performer}",
            reply_markup=get_after_full_buttons(me.username))
    except Exception as e:
        stop.set()
        try:
            await anim
        except:
            pass
        try:
            await status_msg.edit_text(f"❌ خطا: {e}")
        except:
            pass
    finally:
        processing.discard(user_id)
        cleanup(in_path, out_path, thumb_path, raw_thumb, embed_thumb, f"thumb_{tag}.jpg")

async def send_history(user_id, chat_id):
    rows = get_history(user_id)
    if not rows:
        m = await bot.send_message(chat_id, "🎶 هنوز آهنگی نفرستادی. یه موزیک بفرست تا اینجا ذخیره بشه.")
        await nav_push(user_id, m.message_id)
        return
    await clear_nav(user_id, chat_id)
    m = await bot.send_message(chat_id, format_history_text(rows), reply_markup=build_history_keyboard(rows, user_id), parse_mode="HTML")
    await nav_push(user_id, m.message_id)

async def send_favs(user_id, chat_id):
    rows = get_favs(user_id)
    await clear_nav(user_id, chat_id)
    if not rows:
        m = await bot.send_message(chat_id, "❤️ هنوز علاقه‌مندی نداری. از لیست آهنگ‌ها روی 🤍 بزن.")
        await nav_push(user_id, m.message_id)
        return
    m = await bot.send_message(chat_id, format_fav_text(rows), reply_markup=build_history_keyboard(rows, user_id), parse_mode="HTML")
    await nav_push(user_id, m.message_id)

@dp.message(CommandStart())
async def cmd_start(m: types.Message):
    if is_banned(m.from_user.id):
        await m.answer("⛔ شما از استفاده از بات محروم شده‌اید.")
        return
    add_user(m.from_user)
    await clear_nav(m.from_user.id, m.chat.id)
    msg = await m.answer(box("🎧 خوش آمدید!", f"سلام {m.from_user.first_name} 👋\n\nیک فایل موزیک بفرست تا افکت بزنم.\n\n🚀 بدون محدودیت! هرچقدر خواستی بساز.", "👇 از دکمه‌ها یا کامندها استفاده کن:"),
        reply_markup=get_start_keyboard(), parse_mode="HTML")
    await nav_push(m.from_user.id, msg.message_id)

@dp.message(Command("help"))
async def cmd_help(m: types.Message):
    await clear_nav(m.from_user.id, m.chat.id)
    msg = await m.answer(box("📖 راهنما", "1️⃣ یک موزیک بفرست\n2️⃣ افکت را انتخاب کن\n3️⃣ کیفیت را انتخاب کن\n\n📌 کامندها:\n/start شروع\n/profile پروفایل\n/mysongs آهنگ‌های من\n/favs علاقه‌مندی‌ها\n/effects افکت‌ها\n/help راهنما"), parse_mode="HTML")
    await nav_push(m.from_user.id, msg.message_id)

@dp.message(Command("profile"))
async def cmd_profile(m: types.Message):
    if is_banned(m.from_user.id):
        return
    add_user(m.from_user)
    await send_profile(m.from_user.id, m.chat.id)

@dp.message(Command("mysongs"))
async def cmd_mysongs(m: types.Message):
    await send_history(m.from_user.id, m.chat.id)

@dp.message(Command("history"))
async def cmd_history(m: types.Message):
    await send_history(m.from_user.id, m.chat.id)

@dp.message(Command("songs"))
async def cmd_songs(m: types.Message):
    await send_history(m.from_user.id, m.chat.id)

@dp.message(Command("favs"))
async def cmd_favs(m: types.Message):
    await send_favs(m.from_user.id, m.chat.id)

@dp.message(Command("today"))
async def cmd_today(m: types.Message):
    if m.from_user.id not in ADMIN_IDS:
        return
    await m.answer(format_daily_text(), parse_mode="HTML")

@dp.message(Command("effects"))
async def cmd_effects(m: types.Message):
    if is_banned(m.from_user.id):
        await m.answer("⛔ شما بن شده‌اید.")
        return
    if m.from_user.id not in user_files:
        rows = get_history(m.from_user.id)
        if rows:
            hid, fid, track, perf, fn, th, dur, eff = rows[0]
            user_files[m.from_user.id] = {"file_id": fid, "title": track, "performer": perf, "file_name": fn or "music.mp3", "thumb_id": th or None, "duration": dur or 0}
        else:
            await m.answer("اول یک موزیک بفرست 🎧")
            return
    await clear_nav(m.from_user.id, m.chat.id)
    msg = await m.answer("🎛 یک افکت انتخاب کن:", reply_markup=get_buttons())
    await nav_push(m.from_user.id, msg.message_id)

@dp.message(Command("admin"))
async def cmd_admin(m: types.Message):
    if m.from_user.id not in ADMIN_IDS:
        return
    await m.answer("👑 پنل مدیریت:", reply_markup=get_admin_panel())

@dp.message(Command("stats"))
async def cmd_stats(m: types.Message):
    if m.from_user.id not in ADMIN_IDS:
        return
    total, starts, proc = get_stats()
    await m.answer(box("📊 آمار کلی", f"👥 کاربران: {total}\n🚀 استارت‌ها: {starts}\n🎧 پردازش‌ها: {proc}"), parse_mode="HTML")

@dp.message(Command("ban"))
async def cmd_ban(m: types.Message):
    if m.from_user.id not in ADMIN_IDS:
        return
    parts = (m.text or "").split()
    if len(parts) < 2 or not parts[1].isdigit():
        await m.answer("استفاده: /ban آیدی [دلیل]\nمثال: /ban 123456 اسپم")
        return
    uid = int(parts[1])
    reason = " ".join(parts[2:]) if len(parts) > 2 else ""
    ban_user(uid, reason)
    processing.discard(uid)
    await m.answer(f"⛔ کاربر {uid} بن شد.\nدلیل: {reason or '—'}")

@dp.message(Command("unban"))
async def cmd_unban(m: types.Message):
    if m.from_user.id not in ADMIN_IDS:
        return
    parts = (m.text or "").split()
    if len(parts) < 2 or not parts[1].isdigit():
        await m.answer("استفاده: /unban آیدی")
        return
    unban_user(int(parts[1]))
    await m.answer(f"✅ کاربر {parts[1]} آنبن شد.")

@dp.message(Command("banlist"))
async def cmd_banlist(m: types.Message):
    if m.from_user.id not in ADMIN_IDS:
        return
    rows = get_bans()
    if not rows:
        await m.answer("لیست بن خالیه.")
        return
    txt = "\n".join([f"⛔ <code>{u}</code> — {r or '—'}" for u, r in rows])
    await m.answer(box("⛔ لیست بن", txt), parse_mode="HTML")

@dp.message(F.audio | F.document)
async def on_music(m: types.Message):
    if is_banned(m.from_user.id):
        await m.answer("⛔ شما از استفاده از بات محروم شده‌اید.")
        return
    if m.from_user.id in broadcast_wait and m.from_user.id in ADMIN_IDS:
        broadcast_wait.discard(m.from_user.id)
        users = get_all_users()
        await m.answer(f"📣 شروع ارسال به {len(users)} کاربر...")
        ok = fail = 0
        for uid in users:
            try:
                await m.copy_to(uid)
                ok += 1
            except:
                fail += 1
            await asyncio.sleep(0.05)
        await m.answer(f"✅ تمام شد.\nموفق: {ok}\nناموفق: {fail}")
        return
    if m.from_user.id in processing:
        await m.answer("⏳ صبر کن پردازش قبلی تموم بشه بعد فایل جدید بفرست.")
        return
    file = m.audio or m.document
    if m.document and not (m.document.mime_type or "").startswith("audio"):
        await m.answer("⚠️ لطفا فقط فایل صوتی / موزیک بفرستید.")
        return
    info = {
        "file_id": file.file_id,
        "title": getattr(file, "title", None) or (m.audio.title if m.audio else None),
        "performer": getattr(file, "performer", None) or (m.audio.performer if m.audio else None),
        "file_name": file.file_name or "music.mp3",
        "thumb_id": None,
        "duration": getattr(file, "duration", 0) or 0,
    }
    if m.audio and m.audio.thumbnail:
        info["thumb_id"] = m.audio.thumbnail.file_id
    elif m.document and m.document.thumbnail:
        info["thumb_id"] = m.document.thumbnail.file_id
    if not info["title"]:
        info["title"] = os.path.splitext(info["file_name"])[0]
    user_files[m.from_user.id] = info
    add_history(m.from_user.id, info)
    await clear_nav(m.from_user.id, m.chat.id)
    msg = await m.answer(box("🎵 فایل دریافت شد", f"<b>{info['title']}</b>\n👤 {info['performer'] or 'نامشخص'}\n\n🎛 حالا یک افکت انتخاب کن:"), reply_markup=get_buttons(), parse_mode="HTML")
    await nav_push(m.from_user.id, msg.message_id)

@dp.message(F.text)
async def on_text(m: types.Message):
    if is_banned(m.from_user.id):
        return
    if m.from_user.id in broadcast_wait and m.from_user.id in ADMIN_IDS:
        broadcast_wait.discard(m.from_user.id)
        users = get_all_users()
        await m.answer(f"📣 شروع ارسال به {len(users)} کاربر...")
        ok = fail = 0
        for uid in users:
            try:
                await bot.send_message(uid, m.text)
                ok += 1
            except:
                fail += 1
            await asyncio.sleep(0.05)
        await m.answer(f"✅ تمام شد.\nموفق: {ok}\nناموفق: {fail}")
        return
    if m.text.startswith("/"):
        return
    await m.answer("🎧 یک فایل موزیک بفرست تا شروع کنیم.", reply_markup=get_start_keyboard())

@dp.callback_query(F.data == "show_help")
async def cb_help(c: types.CallbackQuery):
    await try_delete(c.message.chat.id, c.message.message_id)
    await clear_nav(c.from_user.id, c.message.chat.id)
    msg = await c.message.answer(box("📖 راهنما", "1️⃣ یک موزیک بفرست\n2️⃣ افکت را انتخاب کن\n3️⃣ کیفیت را انتخاب کن\n\n⏳ بعد چند ثانیه فایل نهایی را می‌گیری."), parse_mode="HTML")
    await nav_push(c.from_user.id, msg.message_id)
    await c.answer()

@dp.callback_query(F.data == "show_profile")
async def cb_profile(c: types.CallbackQuery):
    if is_banned(c.from_user.id):
        await c.answer("⛔ بن شده‌اید.", show_alert=True)
        return
    add_user(c.from_user)
    await send_profile(c.from_user.id, c.message.chat.id, from_cb=True, message=c.message)
    await c.answer()

@dp.callback_query(F.data == "show_effects")
async def cb_show_fx(c: types.CallbackQuery):
    if is_banned(c.from_user.id):
        await c.answer("⛔ بن شده‌اید.", show_alert=True)
        return
    if c.from_user.id not in user_files:
        rows = get_history(c.from_user.id)
        if rows:
            hid, fid, track, perf, fn, th, dur, eff = rows[0]
            user_files[c.from_user.id] = {"file_id": fid, "title": track, "performer": perf, "file_name": fn or "music.mp3", "thumb_id": th or None, "duration": dur or 0}
        else:
            await c.answer("اول یک موزیک بفرست 🎧", show_alert=True)
            return
    await try_delete(c.message.chat.id, c.message.message_id)
    await clear_nav(c.from_user.id, c.message.chat.id)
    msg = await c.message.answer("🎛 یک افکت انتخاب کن:", reply_markup=get_buttons())
    await nav_push(c.from_user.id, msg.message_id)
    await c.answer()

@dp.callback_query(F.data == "show_history")
async def cb_history(c: types.CallbackQuery):
    await try_delete(c.message.chat.id, c.message.message_id)
    await send_history(c.from_user.id, c.message.chat.id)
    await c.answer()

@dp.callback_query(F.data == "show_favs")
async def cb_favs(c: types.CallbackQuery):
    await try_delete(c.message.chat.id, c.message.message_id)
    await send_favs(c.from_user.id, c.message.chat.id)
    await c.answer()

@dp.callback_query(F.data == "back_effects")
async def cb_back(c: types.CallbackQuery):
    await try_delete(c.message.chat.id, c.message.message_id)
    await clear_nav(c.from_user.id, c.message.chat.id)
    msg = await c.message.answer("🎛 یک افکت انتخاب کن:", reply_markup=get_buttons())
    await nav_push(c.from_user.id, msg.message_id)
    await c.answer()

@dp.callback_query(F.data == "new_song")
async def cb_new(c: types.CallbackQuery):
    await try_delete(c.message.chat.id, c.message.message_id)
    await clear_nav(c.from_user.id, c.message.chat.id)
    msg = await c.message.answer("🎧 یک فایل موزیک جدید بفرست.")
    await nav_push(c.from_user.id, msg.message_id)
    await c.answer()

@dp.callback_query(F.data == "cancel_action")
async def cb_cancel(c: types.CallbackQuery):
    try:
        await c.message.delete()
    except:
        pass
    await c.answer("انصراف داده شد ❌")

@dp.callback_query(F.data.startswith("fav_"))
async def cb_fav(c: types.CallbackQuery):
    hid = int(c.data.split("_")[1])
    added = toggle_fav(c.from_user.id, hid)
    await c.answer("❤️ به علاقه‌مندی‌ها اضافه شد." if added else "🤍 از علاقه‌مندی‌ها حذف شد.")
    try:
        rows = get_history(c.from_user.id)
        if rows:
            await c.message.edit_reply_markup(reply_markup=build_history_keyboard(rows, c.from_user.id))
    except:
        pass

@dp.callback_query(F.data.startswith("prev_"))
async def cb_prev(c: types.CallbackQuery):
    effect = c.data.replace("prev_", "", 1)
    if effect not in FILTERS:
        await c.answer()
        return
    if is_banned(c.from_user.id):
        await c.answer("⛔ بن شده‌اید.", show_alert=True)
        return
    if c.from_user.id in processing:
        await c.answer("⏳ صبر کن پردازش قبلی تموم بشه.", show_alert=True)
        return
    if c.from_user.id not in user_files:
        await c.answer("فایل پیدا نشد! دوباره موزیک بفرست.", show_alert=True)
        return
    await try_delete(c.message.chat.id, c.message.message_id)
    await clear_nav(c.from_user.id, c.message.chat.id)
    msg = await c.message.answer(f"{EFFECT_EMOJI.get(effect,'🎧')} افکت <b>{EFFECT_FA.get(effect, effect)}</b>\n\nکیفیت خروجی را انتخاب کن:", reply_markup=get_quality_keyboard(effect), parse_mode="HTML")
    await nav_push(c.from_user.id, msg.message_id)
    await c.answer()

@dp.callback_query(F.data.startswith("go_"))
async def cb_go(c: types.CallbackQuery):
    parts = c.data.split("_")
    bitrate = parts[-1]
    effect = "_".join(parts[1:-1])
    if effect not in FILTERS or bitrate not in ("128", "192", "320"):
        await c.answer()
        return
    if is_banned(c.from_user.id):
        await c.answer("⛔ بن شده‌اید.", show_alert=True)
        return
    if c.from_user.id in processing:
        await c.answer("⏳ یه پردازش در حال انجامه، صبر کن.", show_alert=True)
        return
    ok, tc = check_limit(c.from_user.id)
    if not ok:
        await c.answer(f"⚠️ سقف روزانه‌ات تموم شد ({DAILY_LIMIT} تا در روز). فردا دوباره بیا.", show_alert=True)
        return
    if c.from_user.id not in user_files:
        await c.answer("فایل پیدا نشد! دوباره بفرست.", show_alert=True)
        return
    info = user_files[c.from_user.id]
    await try_delete(c.message.chat.id, c.message.message_id)
    await clear_nav(c.from_user.id, c.message.chat.id)
    status = await c.message.answer(f"{EFFECT_EMOJI.get(effect,'🎧')} در حال شروع پردازش...", parse_mode="HTML")
    await c.answer()
    await process_effect(c.message.chat.id, c.from_user.id, status, info, effect, bitrate)

@dp.callback_query(F.data.startswith("hist_"))
async def cb_hist(c: types.CallbackQuery):
    hid = int(c.data.split("_")[1])
    cur.execute("SELECT file_id, track, performer, file_name, thumb_id, duration FROM history WHERE id=?", (hid,))
    row = cur.fetchone()
    if not row:
        await c.answer()
        return
    fid, track, perf, fn, th, dur = row
    user_files[c.from_user.id] = {"file_id": fid, "title": track, "performer": perf, "file_name": fn or "music.mp3", "thumb_id": th or None, "duration": dur or 0}
    await try_delete(c.message.chat.id, c.message.message_id)
    await clear_nav(c.from_user.id, c.message.chat.id)
    msg = await c.message.answer(f"🎵 <b>{track}</b>\n👤 {perf}\n\nحالا افکت انتخاب کن:", reply_markup=get_buttons(), parse_mode="HTML")
    await nav_push(c.from_user.id, msg.message_id)
    await c.answer()

@dp.callback_query(F.data == "admin_stats")
async def cb_astats(c: types.CallbackQuery):
    if c.from_user.id not in ADMIN_IDS:
        return
    total, starts, proc = get_stats()
    await c.message.answer(box("📊 آمار کلی", f"👥 کاربران: {total}\n🚀 استارت‌ها: {starts}\n🎧 پردازش‌ها: {proc}"), parse_mode="HTML")
    await c.answer()

@dp.callback_query(F.data == "admin_daily")
async def cb_adaily(c: types.CallbackQuery):
    if c.from_user.id not in ADMIN_IDS:
        return
    await c.message.answer(format_daily_text(), parse_mode="HTML")
    await c.answer()

@dp.callback_query(F.data == "admin_effects")
async def cb_aeffects(c: types.CallbackQuery):
    if c.from_user.id not in ADMIN_IDS:
        return
    rows = get_effect_stats()
    if not rows:
        await c.message.answer("هنوز افکتی استفاده نشده.")
    else:
        txt = "\n".join([f"{EFFECT_EMOJI.get(e,'🎧')} {EFFECT_FA.get(e,e)}: {cnt}" for e, cnt in rows])
        await c.message.answer(box("🎯 تحلیل افکت‌ها", txt), parse_mode="HTML")
    await c.answer()

@dp.callback_query(F.data == "admin_bans")
async def cb_abans(c: types.CallbackQuery):
    if c.from_user.id not in ADMIN_IDS:
        return
    rows = get_bans()
    if not rows:
        await c.message.answer("لیست بن خالیه.")
    else:
        txt = "\n".join([f"⛔ <code>{u}</code> — {r or '—'}" for u, r in rows])
        await c.message.answer(box("⛔ لیست بن", txt + "\n\nبرای آنبن: /unban آیدی"), parse_mode="HTML")
    await c.answer()

@dp.callback_query(F.data == "admin_broadcast")
async def cb_abroad(c: types.CallbackQuery):
    if c.from_user.id not in ADMIN_IDS:
        return
    broadcast_wait.add(c.from_user.id)
    await c.message.answer("📣 پیام همگانی را بفرست (متن یا فایل):", reply_markup=get_cancel_keyboard())
    await c.answer()

@dp.callback_query(F.data == "cancel_broadcast")
async def cb_cancelb(c: types.CallbackQuery):
    broadcast_wait.discard(c.from_user.id)
    await c.message.answer("❌ برادکست لغو شد.")
    await c.answer()

async def handle_health(request):
    return web.Response(text="OK")

async def start_web():
    port = int(os.getenv("PORT", "8080"))
    app = web.Application()
    app.router.add_get("/", handle_health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

async def setup_commands():
    await bot.set_my_commands([
        BotCommand(command="start", description="🎧 شروع"),
        BotCommand(command="profile", description="👤 پروفایل من"),
        BotCommand(command="mysongs", description="🎶 آهنگ‌های من"),
        BotCommand(command="favs", description="❤️ علاقه‌مندی‌ها"),
        BotCommand(command="effects", description="🎛 افکت‌ها"),
        BotCommand(command="help", description="📖 راهنما"),
    ])

async def main():
    try:
        await start_web()
    except:
        pass
    try:
        await setup_commands()
    except:
        pass
    print("Bot started...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
