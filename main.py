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
        [InlineKeyboardButton(text="🐌 𝚂ʟᴏᴡᴇᴅ", callback_data="fx:slowed"),
         InlineKeyboardButton(text="🎧 𝚂ʟᴏᴡᴇᴅ + ʀᴇᴠᴇʀʙ", callback_data="fx:slowed_reverb")],
        [InlineKeyboardButton(text="🌃 Nɪɢʜᴛᴄᴏʀᴇ", callback_data="fx:nightcore"),
         InlineKeyboardButton(text="⚡ Sᴘᴇᴇᴅ Uᴘ", callback_data="fx:speedup")],
        [InlineKeyboardButton(text="🔊 Bᴀss Bᴏᴏsᴛ", callback_data="fx:bass"),
         InlineKeyboardButton(text="🌊 Rᴇᴠᴇʀʙ", callback_data="fx:reverb")],
        [InlineKeyboardButton(text="🎩 𝟾𝙳", callback_data="fx:8d")],
        [InlineKeyboardButton(text="✎ ᴀʀᴛɪsᴛ", callback_data="set_artist"),
         InlineKeyboardButton(text="◍ ᴄᴏᴠᴇʀ", callback_data="set_cover")],
    ])
def get_chain_buttons():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🐌 𝚂ʟᴏᴡᴇᴅ", callback_data="chain:slowed"),
         InlineKeyboardButton(text="🎧 𝚂ʟᴏᴡᴇᴅ + ʀᴇᴠᴇʀʙ", callback_data="chain:slowed_reverb")],
        [InlineKeyboardButton(text="🌃 Nɪɢʜᴛᴄᴏʀᴇ", callback_data="chain:nightcore"),
         InlineKeyboardButton(text="⚡ Sᴘᴇᴇᴅ Uᴘ", callback_data="chain:speedup")],
        [InlineKeyboardButton(text="🔊 Bᴀss Bᴏᴏsᴛ", callback_data="chain:bass"),
         InlineKeyboardButton(text="🌊 Rᴇᴠᴇʀʙ", callback_data="chain:reverb")],
        [InlineKeyboardButton(text="🎩 𝟾𝙳", callback_data="chain:8d")],
        [InlineKeyboardButton(text="✓ ᴅᴏɴᴇ ─ تحویل بده", callback_data="chain_done")],
    ])
def get_admin_panel():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◍ sᴛᴀᴛs ─ آمار", callback_data="admin_stats")],
        [InlineKeyboardButton(text="✉ ʙʀᴏᴀᴅᴄᴀsᴛ ─ همگانی", callback_data="admin_broadcast")]
    ])
def get_share_kb():
    if BOT_USERNAME:
        url = f"https://t.me/share/url?url=https://t.me/{BOT_USERNAME}&text=این آهنگو با این ربات درست کردم 🎧"
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="↗ sʜᴀʀᴇ", url=url)],
            [InlineKeyboardButton(text="♫ ᴍᴀᴋᴇ ɴᴇᴡ", url=f"https://t.me/{BOT_USERNAME}")]
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
EFFECT_STYLED = {"slowed": "𝚂ʟᴏᴡᴇᴅ", "slowed_reverb": "𝚂ʟᴏᴡᴇᴅ + ʀᴇᴠᴇʀʙ", "speedup": "Sᴘᴇᴇᴅ Uᴘ", "nightcore": "Nɪɢʜᴛᴄᴏʀᴇ", "bass": "Bᴀss Bᴏᴏsᴛ", "reverb": "Rᴇᴠᴇʀʙ", "8d": "𝟾𝙳"}

def format_time(s: int) -> str:
    try: s = int(s or 0)
    except: s = 0
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
        line=line.strip()
        if not line: continue
        try:
            j = json.loads(line)
            vid = j.get("id","")
            title = j.get("title","Unknown")
            dur = j.get("duration") or 0
            uploader = j.get("uploader") or j.get("channel") or ""
            url = j.get("url") or (f"https://www.youtube.com/watch?v={vid}" if vid else "")
            if vid and "://" not in url:
                url = f"https://www.youtube.com/watch?v={vid}"
            out.append({"id": vid, "title": title[:80], "duration": int(dur or 0), "uploader": str(uploader)[:50], "url": url})
        except: continue
        if len(out)>=5: break
    return out

def run_download(url: str, out_path: str):
    cmd = ["yt-dlp", "-x", "--audio-format", "mp3", "--audio-quality", "192K", "--no-playlist", "--no-warnings", "-o", out_path, url]
    r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=180)
    if not os.path.exists(out_path):
        base = out_path.rsplit(".",1)[0]
        for f in os.listdir("."):
            if f.startswith(os.path.basename(base)):
                return os.path.join(".", f)
        raise RuntimeError("دانلود ناموفق بود.")
    return out_path

async def fix_thumb(src: str, dst: str) -> bool:
    cmd = ["ffmpeg", "-y", "-i", src, "-vf", "scale=320:320:force_original_aspect_ratio=increase,crop=320:320", "-q:v", "3", dst]
    await asyncio.to_thread(subprocess.run, cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if os.path.exists(dst):
        try:
            if os.path.getsize(dst) > 190*1024:
                tmp = dst+".tmp.jpg"
                await asyncio.to_thread(subprocess.run, ["ffmpeg","-y","-i",dst,"-vf","scale=320:320","-q:v","8",tmp], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                if os.path.exists(tmp): os.replace(tmp,dst)
        except: pass
        return True
    return False

async def apply_effect_to_file(inp: str, outp: str, effect: str):
    cmd = ["ffmpeg","-y","-i",inp,"-filter:a",FILTERS[effect],"-ar","44100","-ac","2","-c:a","libmp3lame","-b:a","192k",outp]
    await asyncio.to_thread(subprocess.run, cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if not os.path.exists(outp):
        raise RuntimeError("خطا در پردازش فایل.")

async def add_audio_watermark(inp: str, outp: str):
    if WATERMARK_SOUND=="off":
        if inp!=outp:
            try: os.replace(inp,outp)
            except: pass
        return
    wm = outp+".wm.mp3"
    cmd = ["ffmpeg","-y","-i",inp,"-filter:a","sine=frequency=880:duration=0.25:beep_factor=2,volume=0.12[beep];[0:a][beep]amix=inputs=2:duration=first:dropout_transition=0:weights=10 1,aresample=44100,aecho=0.8:0.3:40:0.15","-c:a","libmp3lame","-b:a","192k",wm]
    await asyncio.to_thread(subprocess.run, cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if os.path.exists(wm):
        try: os.replace(wm,outp)
        except: pass

START_TXT = ("╭─── <b>♫ ᴍᴜsɪᴄ ᴇғғᴇᴄᴛs</b> ───╮\n│ سلام، خوش اومدی ✦\n│ فایل بفرست یا اسم آهنگو بنویس.\n╰───────────────╯\n\n◍ <b>ᴇғғᴇᴄᴛs :</b>\n🐌 𝚂ʟᴏᴡᴇᴅ ┆ 🎧 𝚂ʟᴏᴡᴇᴅ + ʀᴇᴠᴇʀʙ\n🌃 Nɪɢʜᴛᴄᴏʀᴇ ┆ ⚡ Sᴘᴇᴇᴅ Uᴘ\n🔊 Bᴀss Bᴏᴏsᴛ ┆ 🌊 Rᴇᴠᴇʀʙ ┆ 🎩 𝟾𝙳\n\n─ ─ ─ ─ ─ ─ ─ ─\n🔍 اسم آهنگو بفرست تا سرچ کنم\n🔗 ᴄʜᴀɪɴ افکت‌ها ┆ ◍ ᴄᴏᴠᴇʀ دلخواه\n👇 ─ فایل یا اسم بفرست")
HELP_TXT = ("╭── <b>◍ ʜᴇʟᴘ</b> ──╮\n│ 𝟷 ─ فایل بفرست یا اسم بنویس 🎵\n│ 𝟸 ─ از لیست سرچ انتخاب کن 🔍\n│ 𝟹 ─ افکت رو بزن 🎛️\n│ 𝟺 ─ افکت بعدی؟ یا تحویل 🔗\n╰──────────╯\n<i>ғᴏʀᴍᴀᴛs : ᴍᴘ𝟹 ┆ ᴍ𝟺ᴀ ┆ ᴡᴀᴠ ┆ ᴏɢɢ ┆ ғʟᴀᴄ</i>")

@dp.message(CommandStart())
async def start_cmd(message: types.Message):
    add_user(message.from_user.id)
    await message.reply(START_TXT)
@dp.message(Command("help"))
async def help_cmd(message: types.Message):
    await message.reply(HELP_TXT)
@dp.message(Command("admin"))
async def admin_cmd(message: types.Message):
    if not is_admin(message.from_user.id): return
    await message.reply(f"╭── <b>◍ ᴀᴅᴍɪɴ ᴘᴀɴᴇʟ</b> ──╮\n│ 👥 ᴜsᴇʀs : <b>{len(all_users)}</b>\n╰──────────╯", reply_markup=get_admin_panel())
@dp.callback_query(F.data.startswith("admin_"))
async def admin_callback(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("دسترسی نداری.", show_alert=True); return
    await callback.answer()
    if callback.data=="admin_stats":
        today = datetime.now().strftime("%Y-%m-%d")
        tc = sum(1 for v in first_seen.values() if v==today)
        await callback.message.edit_text(f"◍ <b>sᴛᴀᴛs</b>\n─ ─ ─\n👥 ᴛᴏᴛᴀʟ : <b>{len(all_users)}</b>\n✦ ᴛᴏᴅᴀʏ : <b>{tc}</b>", reply_markup=get_admin_panel())
    elif callback.data=="admin_broadcast":
        broadcast_mode.add(callback.from_user.id)
        await callback.message.edit_text("✉ <b>ʙʀᴏᴀᴅᴄᴀsᴛ ᴍᴏᴅᴇ ᴏɴ</b>\nپیامت رو بفرست.\n<i>ʟɢᴏ : /cancel</i>")
@dp.message(Command("cancel"))
async def cancel_cmd(message: types.Message):
    broadcast_mode.discard(message.from_user.id)
    awaiting.pop(message.from_user.id, None)
    await message.reply("─ ʟɢᴏ ✓ ─")
@dp.callback_query(F.data=="set_artist")
async def ask_artist(callback: types.CallbackQuery):
    await callback.answer()
    awaiting[callback.from_user.id]="artist"
    await callback.message.reply("✎ <b>ᴀʀᴛɪsᴛ ɴᴀᴍᴇ ؟</b>\nاسم آرتیست رو بفرست.\n<i>ʟɢᴏ : /cancel</i>")
@dp.callback_query(F.data=="set_cover")
async def ask_cover(callback: types.CallbackQuery):
    await callback.answer()
    awaiting[callback.from_user.id]="cover"
    await callback.message.reply("◍ <b>ᴄᴏᴠᴇʀ ؟</b>\nعکس کاور رو بفرست.\n<i>ʟɢᴏ : /cancel</i>")

@dp.message(F.photo)
async def handle_photo(message: types.Message):
    uid = message.from_user.id
    if uid in broadcast_mode and is_admin(uid):
        await do_broadcast(message); return
    if awaiting.get(uid)=="cover":
        get_settings(uid)["cover"]=message.photo[-1].file_id
        awaiting.pop(uid,None)
        await message.reply("◍ <b>ᴄᴏᴠᴇʀ sᴀᴠᴇᴅ ✓</b>\n─ حالا افکت رو بزن 👇", reply_markup=get_buttons())

@dp.message(F.text)
async def handle_text(message: types.Message):
    uid = message.from_user.id
    txt = (message.text or "").strip()
    if uid in broadcast_mode and is_admin(uid):
        if not txt.startswith("/"): await do_broadcast(message)
        return
    if awaiting.get(uid)=="artist":
        get_settings(uid)["artist"]=txt[:100]
        awaiting.pop(uid,None)
        await message.reply("✎ <b>ᴀʀᴛɪsᴛ sᴀᴠᴇᴅ ✓</b>\n─ حالا افکت رو بزن 👇", reply_markup=get_buttons())
        return
    if txt.startswith("/"): return
    if len(txt)<2: return
    add_user(uid)
    wait = await message.reply("🔍 <b>sᴇᴀʀᴄʜɪɴɢ ...</b>\n<i>دارم می‌گردم، چند ثانیه صبر کن</i>")
    try:
        results = await asyncio.to_thread(run_search, txt)
    except Exception as e:
        await wait.edit_text(f"✕ <b>سرچ نشد :</b> <i>{e}</i>")
        return
    if not results:
        await wait.edit_text("✕ ─ چیزی پیدا نکرد
