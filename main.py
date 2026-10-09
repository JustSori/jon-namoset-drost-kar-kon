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

def get_start_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="\U0001F4D6 راهنما", callback_data="show_help")],
        [InlineKeyboardButton(text="\U0001F3B5 لیست افکت‌ها", callback_data="show_effects")],
    ])

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
        f"سلام رفیق! خوش اومدی \U0001F44B\u2728\n\n"
        f"اینجا آهنگت رو به سبک اینستا خفن می‌کنم \U0001F60E\n"
        f"\U0001F3AB سهم امروزت: <b>{remaining}</b>\n"
        f"{LINE}\n"
        f"\U0001F447 یه فایل موزیک بفرست تا شروع کنیم",
        reply_markup=get_start_keyboard(),
        parse_mode="HTML"
    )

@dp.message(Command("help"))
async def help_cmd(message: types.Message):
    await message.answer(
        f"\U0001F3A7 <b>Music Effects</b>\n{LINE}\n"
        f"سلام! به ربات افکت آهنگ خوش اومدی \u2728\n\n"
        f"\U0001F3B5 <b>چطور استفاده کنی؟</b>\n"
        f"\u2022 فایل صوتی رو همین‌جا بفرست\n"
        f"\u2022 یه افکت انتخاب کن\n"
        f"\u2022 اول پیش‌نمایش 30 ثانیه‌ای میاد\n"
        f"\u2022 اگه خوشت اومد بزن «نسخه کاملشو بده»\n\n"
        f"\U0001F39B <b>افکت‌های قابل انتخاب</b>\n"
        f"\U0001F40C Slowed  \u2022  \U0001F3A7 Slowed + Reverb\n"
        f"\U0001F303 Nightcore  \u2022  \u26A1 Speed Up\n"
        f"\U0001F50A Bass Boost  \u2022  \U0001F30A Reverb  \u2022  \U0001F3A9 8D\n"
        f"{LINE}\n"
        f"\U0001F501 با دکمه «یه افکت دیگه» می‌تونی بدون ارسال دوباره افکت عوض کنی\n"
        f"\U0001F3AB سهم روزانه: <b>30</b> افکت\n"
        f"\U0001F447 برای شروع، فایل بفرست.",
        parse_mode="HTML"
    )

@dp.message(Command("admin"))
async def admin(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    total, starts, proc, today = get_stats()
    await message.answer(
        f"\U0001F451 <b>Music Effects | Admin</b>\n{LINE}\n"
        f"\U0001F465 کاربران: <b>{total}</b>\n"
        f"\u25B6\uFE0F استارت: <b>{starts}</b>\n"
        f"\U0001F3A7 کل خروجی: <b>{proc}</b>\n"
        f"\U0001F4C5 خروجی امروز: <b>{today}</b>\n{LINE}",
        reply_markup=get_admin_panel(), parse_mode="HTML"
    )

@dp.message(F.audio | F.voice | F.document)
async def handle_music(message: types.Message):
    if message.from_user.id in broadcast_wait and message.from_user.id in ADMIN_IDS:
        broadcast_wait.discard(message.from_user.id)
        users = get_all_users()
        status = await message.reply(f"\U0001F4E3 <b>در حال ارسال به {len(users)} نفر...</b>", parse_mode="HTML")
        ok = fail = 0
        for uid in users:
            try:
                await bot.copy_message(uid, message.chat.id, message.message_id)
                ok += 1
            except:
                fail += 1
            await asyncio.sleep(0.05)
        await status.edit_text(f"\u2705 تموم شد\n\U0001F4D7 موفق: <b>{ok}</b>\n\U0001F4D5 ناموفق: <b>{fail}</b>", parse_mode="HTML")
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

    user_files[message.from_user.id] = {
        "file_id": file_id, "title": title, "performer": performer,
        "duration": duration, "thumb_id": thumb_id, "file_name": file_name
    }
    show_name = title or os.path.splitext(file_name)[0]
    _, remaining = check_limit(message.from_user.id)
    await message.answer(
        f"\U0001F3A7 <b>Music Effects</b>\n{LINE}\n"
        f"\u2705 فایل دریافت شد!\n\n\U0001F3B5 <b>{show_name}</b>\n\n"
        f"\U0001F3AB سهم امروزت: <b>{remaining}</b>\n"
        f"\U0001F39B افکت رو انتخاب کن \U0001F447\n"
        f"\u23F3 اول پیش‌نمایش 30 ثانیه‌ای می‌فرستم",
        reply_markup=get_buttons(), parse_mode="HTML"
    )

@dp.callback_query()
async def callbacks(callback: types.CallbackQuery):
    data = callback.data or ""

    if data == "show_help":
        await callback.message.answer(
            f"\U0001F3A7 <b>Music Effects</b>\n{LINE}\n"
            f"\U0001F3B5 یه فایل بفرست، افکت انتخاب کن، پیش‌نمایش بگیر، بعد نسخه کامل رو دانلود کن.\n\n"
            f"\U0001F3AB سهم روزانه: <b>30</b>\n"
            f"راهنمای کامل: /help",
            parse_mode="HTML"
        )
        await callback.answer()
        return

    if data == "show_effects":
        await callback.message.answer(
            f"\U0001F39B <b>افکت‌ها</b>\n{LINE}\n"
            f"\U0001F40C Slowed\n\U0001F3A7 Slowed + Reverb\n\U0001F303 Nightcore\n"
            f"\u26A1 Speed Up\n\U0001F50A Bass Boost\n\U0001F30A Reverb\n\U0001F3A9 8D\n"
            f"{LINE}\n\U0001F447 یه آهنگ بفرست تا امتحانشون کنی",
            parse_mode="HTML"
        )
        await callback.answer()
        return

    if data.startswith("admin_"):
        if callback.from_user.id not in ADMIN_IDS:
            await callback.answer("دسترسی نداری!", show_alert=True)
            return
        if data == "admin_stats":
            total, starts, proc, today = get_stats()
            await callback.message.edit_text(
                f"\U0001F3A7 <b>Music Effects | Stats</b>\n{LINE}\n"
                f"\U0001F465 کاربر یکتا: <b>{total}</b>\n"
                f"\u25B6\uFE0F استارت: <b>{starts}</b>\n"
                f"\U0001F3A7 کل خروجی: <b>{proc}</b>\n"
                f"\U0001F4C5 خروجی امروز: <b>{today}</b>\n"
                f"\U0001F3AB سقف روزانه: <b>{DAILY_LIMIT}</b>\n{LINE}",
                reply_markup=get_admin_panel(), parse_mode="HTML"
            )
        elif data == "admin_effects":
            rows = get_effect_stats()
            if not rows:
                txt = "هنوز هیچ افکتی استفاده نشده."
            else:
                total_e = sum(c for _, c in rows)
                lines = []
                for eff, cnt in rows:
                    pct = round(cnt * 100 / total_e) if total_e else 0
                    fa = EFFECT_FA.get(eff, eff)
                    em = EFFECT_EMOJI.get(eff, "")
                    lines.append(f"{em} {fa}: <b>{cnt}</b> ({pct}٪)")
                txt = "\n".join(lines)
            await callback.message.edit_text(
                f"\U0001F3AF <b>محبوب‌ترین افکت‌ها</b>\n{LINE}\n{txt}\n{LINE}",
                reply_markup=get_admin_panel(), parse_mode="HTML"
            )
        elif data == "admin_broadcast":
            broadcast_wait.add(callback.from_user.id)
            await callback.message.edit_text(
                f"\U0001F3A7 <b>Music Effects</b>\n{LINE}\n\U0001F4E3 حالت پیام همگانی فعال شد.\nحالا پیامت رو بفرست.",
                parse_mode="HTML"
            )
        await callback.answer()
        return

    if data == "back_effects":
        await callback.message.edit_text(
            f"\U0001F3A7 <b>Music Effects</b>\n{LINE}\n\U0001F501 یه افکت دیگه انتخاب کن \U0001F447",
            reply_markup=get_buttons(), parse_mode="HTML"
        )
        await callback.answer()
        return

    if data == "new_song":
        await callback.message.answer("\U0001F3B5 یه آهنگ جدید بفرست \U0001F447")
        await callback.answer()
        return

    if data.startswith("prev_"):
        await do_preview(callback, data.replace("prev_", "", 1))
        return
    if data.startswith("full_"):
        await do_full(callback, data.replace("full_", "", 1))
        return

async def do_preview(callback: types.CallbackQuery, effect: str):
    await callback.answer()
    user_id = callback.from_user.id
    if user_id not in user_files:
        await callback.answer("اول یه آهنگ بفرست!", show_alert=True)
        return
    if effect not in FILTERS:
        return
    allowed, remaining = check_limit(user_id)
    if not allowed:
        await callback.message.edit_text(
            f"\U0001F3A7 <b>Music Effects</b>\n{LINE}\n"
            f"\U0001F6AB <b>سهم امروزت تموم شد!</b>\n\n"
            f"فردا دوباره بیا، {DAILY_LIMIT} تا سهم داری \U0001F60C",
            parse_mode="HTML"
        )
        return
    emoji = EFFECT_EMOJI.get(effect, "\U0001F3A7")
    suffix = SUFFIX.get(effect, effect)
    try:
        await callback.message.edit_text(
            f"\U0001F3A7 <b>Music Effects</b>\n{LINE}\n"
            f"{emoji} دارم پیش‌نمایش <b>{suffix}</b> رو می‌سازم...\n"
            f"\U0001F3AB باقی‌مونده امروز: <b>{remaining}</b>",
            parse_mode="HTML"
        )
    except:
        pass
    info = user_files[user_id]
    tag = f"{user_id}_{int(time.time())}"
    input_path = f"input_{tag}.mp3"
    preview_path = f"prev_{tag}.mp3"
    thumb_fixed = None
    thumb_raw = f"thumb_raw_{tag}.jpg"
    try:
        f = await bot.get_file(info["file_id"])
        await bot.download_file(f.file_path, input_path)
        cmd = ["ffmpeg", "-y", "-i", input_path, "-t", "30", "-filter:a", FILTERS[effect], "-ar", "44100", "-b:a", "192k", preview_path]
        p = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        await p.communicate()
        if not os.path.exists(preview_path) or os.path.getsize(preview_path) == 0:
            await callback.message.edit_text("خطا در پردازش! ffmpeg روی سرور نصب نیست.")
            cleanup(input_path, preview_path, thumb_raw)
            return
        new_title, new_performer, new_filename = build_names(info, effect)
        thumb_fixed = await make_thumb(info, tag)
        thumb_file = FSInputFile(thumb_fixed) if thumb_fixed and os.path.exists(thumb_fixed) else None
        inc_usage(user_id, effect)
        _, rem_after = check_limit(user_id)
        caption = (
            f"\U0001F3A7 <b>Music Effects</b>\n{LINE}\n"
            f"{emoji} <b>{new_title}</b>\n\n"
            f"\u23F3 پیش‌نمایش 30 ثانیه‌ست\n"
            f"\U0001F3AB باقی‌مونده امروز: <b>{rem_after}</b>\n"
            f"اگه خوشت اومد نسخه کامل رو بگیر \U0001F447"
        )
        await callback.message.answer_audio(
            FSInputFile(preview_path, filename=new_filename),
            title=new_title, performer=new_performer, duration=30,
            thumbnail=thumb_file, caption=caption,
            parse_mode="HTML", reply_markup=get_preview_buttons(effect)
        )
        await callback.message.delete()
    except Exception as e:
        try:
            await callback.message.edit_text(f"خطا: {e}")
        except:
            pass
    finally:
        cleanup(input_path, preview_path, thumb_raw, thumb_fixed)

async def do_full(callback: types.CallbackQuery, effect: str):
    await callback.answer()
    user_id = callback.from_user.id
    if user_id not in user_files:
        await callback.answer("اول یه آهنگ بفرست!", show_alert=True)
        return
    if effect not in FILTERS:
        return
    emoji = EFFECT_EMOJI.get(effect, "\U0001F3A7")
    suffix = SUFFIX.get(effect, effect)
    status = await callback.message.reply(
        f"\U0001F3A7 <b>Music Effects</b>\n{LINE}\n"
        f"{emoji} دارم نسخه کامل <b>{suffix}</b> رو می‌سازم...",
        parse_mode="HTML"
    )
    info = user_files[user_id]
    tag = f"{user_id}_{int(time.time())}_full"
    input_path = f"input_{tag}.mp3"
    output_path = f"output_{tag}.mp3"
    thumb_fixed = None
    thumb_raw = f"thumb_raw_{tag}.jpg"
    try:
        f = await bot.get_file(info["file_id"])
        await bot.download_file(f.file_path, input_path)
        cmd = ["ffmpeg", "-y", "-i", input_path, "-filter:a", FILTERS[effect], "-ar", "44100", "-b:a", "320k", output_path]
        p = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        await p.communicate()
        if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
            await status.edit_text("خطا در پردازش!")
            cleanup(input_path, output_path, thumb_raw)
            return
        new_title, new_performer, new_filename = build_names(info, effect)
        orig_dur = info.get("duration") or 0
        new_duration = int(orig_dur * DURATION_FACTOR.get(effect, 1.0)) if orig_dur else None
        thumb_fixed = await make_thumb(info, tag)
        thumb_file = FSInputFile(thumb_fixed) if thumb_fixed and os.path.exists(thumb_fixed) else None
        bot_info = await bot.get_me()
        caption = (
            f"\U0001F3A7 <b>Music Effects</b>\n{LINE}\n"
            f"{emoji} <b>{new_title}</b>\n\n"
            f"\u2705 نسخه کامل آماده شد! enjoy \U0001F60C\n"
            f"\U0001F916 @{bot_info.username}"
        )
        await callback.message.answer_audio(
            FSInputFile(output_path, filename=new_filename),
            title=new_title, performer=new_performer, duration=new_duration,
            thumbnail=thumb_file, caption=caption,
            parse_mode="HTML", reply_markup=get_after_full_buttons()
        )
        await status.delete()
        try:
            await callback.message.delete()
        except:
            pass
    except Exception as e:
        try:
            await status.edit_text(f"خطا: {e}")
        except:
            pass
    finally:
        cleanup(input_path, output_path, thumb_raw, thumb_fixed)

async def handle(request):
    return web.Response(text="Bot is alive!")

async def main():
    app = web.Application()
    app.router.add_get("/", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", 10000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print("Bot started...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
