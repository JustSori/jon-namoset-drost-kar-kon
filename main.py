import asyncio
import os
import sqlite3
from aiogram import Bot, Dispatcher, types, F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from aiogram.filters import CommandStart, Command
from aiohttp import web

TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise ValueError("BOT_TOKEN ست نشده!")

ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_ID", "0").split(",") if x.strip().isdigit()]

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
con.commit()

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
    return total, starts, proc

def get_all_users():
    cur.execute("SELECT user_id FROM users")
    return [r[0] for r in cur.fetchall()]

def inc_processed():
    cur.execute("UPDATE stats SET value=value+1 WHERE key='processed'")
    con.commit()

def get_buttons():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="\U0001F40C Slowed", callback_data="slowed"),
         InlineKeyboardButton(text="\U0001F3A7 Slowed + Reverb", callback_data="slowed_reverb")],
        [InlineKeyboardButton(text="\U0001F303 Nightcore", callback_data="nightcore"),
         InlineKeyboardButton(text="\u26A1 Speed Up", callback_data="speedup")],
        [InlineKeyboardButton(text="\U0001F50A Bass Boost", callback_data="bass"),
         InlineKeyboardButton(text="\U0001F30A Reverb", callback_data="reverb")],
        [InlineKeyboardButton(text="\U0001F3A9 8D", callback_data="8d")]
    ])

def get_admin_panel():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="\U0001F4CA آمار", callback_data="admin_stats")],
        [InlineKeyboardButton(text="\U0001F4E3 پیام همگانی", callback_data="admin_broadcast")]
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

@dp.message(CommandStart())
async def start(message: types.Message):
    add_user(message.from_user)
    await message.answer(
        f"\U0001F3A7 <b>Music Effects</b>\n"
        f"{LINE}\n"
        f"سلام! به ربات افکت آهنگ خوش اومدی \u2728\n\n"
        f"\U0001F3B5 <b>چطور استفاده کنی؟</b>\n"
        f"\u2022 فایل صوتی رو همین‌جا بفرست\n\n"
        f"\U0001F39B <b>افکت‌های قابل انتخاب</b>\n"
        f"\U0001F40C Slowed  \u2022  \U0001F3A7 Slowed + Reverb\n"
        f"\U0001F303 Nightcore  \u2022  \u26A1 Speed Up\n"
        f"\U0001F50A Bass Boost  \u2022  \U0001F30A Reverb  \u2022  \U0001F3A9 8D\n"
        f"{LINE}\n"
        f"\U0001F447 برای شروع، فایل بفرست.",
        parse_mode="HTML"
    )

@dp.message(Command("admin"))
async def admin(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    total, starts, proc = get_stats()
    await message.answer(
        f"\U0001F451 <b>Music Effects | Admin</b>\n"
        f"{LINE}\n"
        f"\U0001F465 کاربران: <b>{total}</b>\n"
        f"\u25B6\uFE0F استارت: <b>{starts}</b>\n"
        f"\U0001F3A7 پردازش شده: <b>{proc}</b>\n"
        f"{LINE}\n"
        f"یه گزینه رو انتخاب کن \U0001F447",
        reply_markup=get_admin_panel(),
        parse_mode="HTML"
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
        await status.edit_text(
            f"\U0001F3A7 <b>Music Effects</b>\n{LINE}\n"
            f"\u2705 ارسال همگانی تموم شد\n\n"
            f"\U0001F4D7 موفق: <b>{ok}</b>\n\U0001F4D5 ناموفق: <b>{fail}</b>",
            parse_mode="HTML"
        )
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
        await message.reply(
            f"\U0001F3A7 <b>Music Effects</b>\n{LINE}\n"
            f"\u26A0\uFE0F فایل نامعتبره! لطفا یه فایل صوتی بفرست \U0001F3B5",
            parse_mode="HTML"
        )
        return

    user_files[message.from_user.id] = {
        "file_id": file_id, "title": title, "performer": performer,
        "duration": duration, "thumb_id": thumb_id, "file_name": file_name
    }
    show_name = title or os.path.splitext(file_name)[0]
    await message.answer(
        f"\U0001F3A7 <b>Music Effects</b>\n"
        f"{LINE}\n"
        f"\u2705 فایل دریافت شد!\n\n"
        f"\U0001F3B5 <b>{show_name}</b>\n\n"
        f"\U0001F39B حالا افکت رو انتخاب کن \U0001F447",
        reply_markup=get_buttons(),
        parse_mode="HTML"
    )

@dp.callback_query()
async def callbacks(callback: types.CallbackQuery):
    if callback.data.startswith("admin_"):
        if callback.from_user.id not in ADMIN_IDS:
            await callback.answer("دسترسی نداری!", show_alert=True)
            return
        if callback.data == "admin_stats":
            total, starts, proc = get_stats()
            await callback.message.edit_text(
                f"\U0001F3A7 <b>Music Effects | Stats</b>\n{LINE}\n"
                f"\U0001F465 کاربر یکتا: <b>{total}</b>\n"
                f"\u25B6\uFE0F استارت: <b>{starts}</b>\n"
                f"\U0001F3A7 خروجی: <b>{proc}</b>\n{LINE}",
                reply_markup=get_admin_panel(), parse_mode="HTML"
            )
        elif callback.data == "admin_broadcast":
            broadcast_wait.add(callback.from_user.id)
            await callback.message.edit_text(
                f"\U0001F3A7 <b>Music Effects</b>\n{LINE}\n"
                f"\U0001F4E3 حالت پیام همگانی فعال شد\n\n"
                f"حالا پیامت رو بفرست تا به همه ارسال کنم.\n"
                f"برای لغو /admin رو بزن.",
                parse_mode="HTML"
            )
        await callback.answer()
        return

    await callback.answer()
    user_id = callback.from_user.id
    if user_id not in user_files:
        await callback.answer("اول یه آهنگ بفرست!", show_alert=True)
        return
    effect = callback.data
    if effect not in FILTERS:
        return

    emoji = EFFECT_EMOJI.get(effect, "\U0001F3A7")
    suffix = SUFFIX.get(effect, effect)

    await callback.message.edit_text(
        f"\U0001F3A7 <b>Music Effects</b>\n{LINE}\n"
        f"{emoji} در حال ساخت نسخه <b>{suffix}</b>...\n"
        f"\u23F3 چند ثانیه صبر کن...",
        parse_mode="HTML"
    )

    info = user_files[user_id]
    file = await bot.get_file(info["file_id"])
    input_path = f"input_{user_id}_{callback.id}.mp3"
    output_path = f"output_{user_id}_{callback.id}.mp3"
    thumb_path = f"thumb_{user_id}_{callback.id}.jpg"
    has_thumb = False
    await bot.download_file(file.file_path, input_path)
    if info.get("thumb_id"):
        try:
            tfile = await bot.get_file(info["thumb_id"])
            await bot.download_file(tfile.file_path, thumb_path)
            has_thumb = True
        except:
            has_thumb = False

    try:
        cmd = ["ffmpeg", "-y", "-i", input_path, "-filter:a", FILTERS[effect], "-ar", "44100", "-b:a", "320k", output_path]
        proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        await proc.communicate()
        if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
            await callback.message.edit_text("خطا در پردازش! ffmpeg روی سرور نصب نیست.")
            return
        orig = info.get("title") or os.path.splitext(info.get("file_name", "music"))[0]
        orig = orig.strip()
        new_title = f"{orig} {suffix}"
        new_performer = info.get("performer") or orig
        new_filename = f"{new_title}.mp3"
        orig_dur = info.get("duration") or 0
        factor = DURATION_FACTOR.get(effect, 1.0)
        new_duration = int(orig_dur * factor) if orig_dur else None
        audio_file = FSInputFile(output_path, filename=new_filename)
        thumb_file = FSInputFile(thumb_path) if has_thumb else None
        bot_info = await bot.get_me()
        caption = (
            f"\U0001F3A7 <b>Music Effects</b>\n{LINE}\n"
            f"{emoji} <b>{new_title}</b>\n\n"
            f"\u2705 آماده شد! enjoy \U0001F60C\n"
            f"\U0001F916 @{bot_info.username}"
        )
        await callback.message.answer_audio(
            audio_file, title=new_title, performer=new_performer,
            duration=new_duration, thumbnail=thumb_file,
            caption=caption, parse_mode="HTML"
        )
        await callback.message.delete()
        inc_processed()
    except Exception as e:
        await callback.message.edit_text(f"خطا: {e}")
    finally:
        for p in [input_path, output_path, thumb_path]:
            if os.path.exists(p):
                os.remove(p)

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
