import asyncio
import os
import subprocess
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, BotCommand
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiohttp import web

TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise ValueError("BOT_TOKEN ست نشده!")

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
user_files = {}

def get_buttons():
    buttons = [
        [InlineKeyboardButton(text="🐌 Slowed 0.8x", callback_data="slowed"),
         InlineKeyboardButton(text="🎧 Slowed + Reverb", callback_data="slowed_reverb")],
        [InlineKeyboardButton(text="🌃 Nightcore", callback_data="nightcore"),
         InlineKeyboardButton(text="⚡ Speed Up 1.25x", callback_data="speedup")],
        [InlineKeyboardButton(text="🔊 Bass Boost", callback_data="bass"),
         InlineKeyboardButton(text="🌊 Reverb Only", callback_data="reverb")],
        [InlineKeyboardButton(text="🎩 8D", callback_data="8d")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

@dp.message(CommandStart())
async def start_cmd(message: types.Message):
    name = message.from_user.first_name
    await message.reply(
        f"👋 سلام <b>{name}</b> عزیز!\n\n"
        f"به <b>🎧 ربات افکت موزیک</b> خوش اومدی\n"
        f"<blockquote>جایی که آهنگات یه وایب جدید می‌گیرن ✨</blockquote>\n\n"
        f"🎵 فقط کافیه یه آهنگ بفرستی...\n\n"
        f"<b>افکت‌هایی که دارم:</b>\n"
        f"🐌 اسلو | 🎧 اسلو + ریورب\n"
        f"🌃 نایتکور | ⚡ تند\n"
        f"🔊 بیس بوست | 🌊 ریورب | 🎩 هشت‌بعدی\n\n"
        f"<i>👇 بزن بریم، یه موزیک بفرست</i>"
    )

@dp.message(Command("help"))
async def help_cmd(message: types.Message):
    await message.reply(
        f"<b>📖 راهنمای ربات</b>\n"
        f"<blockquote expandable>اگه گیج شدی فقط این ۳ قدم رو برو:</blockquote>\n\n"
        f"1️⃣ یه فایل <b>موزیک mp3</b> بفرست 🎵\n"
        f"2️⃣ یه دکمه افکت انتخاب کن 🎛️\n"
        f"3️⃣ چند ثانیه صبر کن تا نسخه جدید بیاد ⚡\n\n"
        f"<i>💡 اگه بات جواب نداد یه بار /start بزن</i>"
    )

@dp.message(F.audio | F.voice | F.document)
async def handle_music(message: types.Message):
    file_id = None
    file_name = "music.mp3"
    if message.audio:
        file_id = message.audio.file_id
        file_name = message.audio.file_name or "music.mp3"
    elif message.voice:
        file_id = message.voice.file_id
    elif message.document:
        if "audio" in (message.document.mime_type or ""):
            file_id = message.document.file_id

    if not file_id:
        await message.reply(
            "⚠️ <b>این فایل موزیک نیست!</b>\n"
            "<blockquote>لطفاً یه فایل mp3 بفرست 🎵</blockquote>"
        )
        return

    user_files[message.from_user.id] = file_id
    await message.reply(
        f"✅ <b>آهنگت رسید!</b>\n"
        f"<blockquote>{file_name}</blockquote>\n"
        f"حالا انتخاب کن باهاش چیکار کنم؟ 👇",
        reply_markup=get_buttons()
    )

@dp.callback_query()
async def process_effect(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    if user_id not in user_files:
        await callback.answer("اول یه آهنگ بفرست! 🎵", show_alert=True)
        return

    effect = callback.data
    await callback.message.edit_text(
        "⏳ <b>دارم پردازش می‌کنم...</b>\n"
        "<blockquote>چند ثانیه صبر کن، داره جادو میشه ✨</blockquote>"
    )

    file_id = user_files[user_id]
    file = await bot.get_file(file_id)
    input_path = f"input_{user_id}.mp3"
    output_path = f"output_{user_id}.mp3"
    await bot.download_file(file.file_path, input_path)

    captions = {
        "slowed": "🐌 <b>Slowed شد!</b>\n<blockquote>نسخه آروم و لوفایش آماده‌ست، بگیر بخواب باهاش 🌙</blockquote>",
        "slowed_reverb": "🎧 <b>Slowed + Reverb شد!</b>\n<blockquote>وایب بارون پشت پنجره رو میده 🌧️</blockquote>",
        "speedup": "⚡ <b>Speed Up شد!</b>\n<blockquote>انرژی گرفت، بزن زیرش برو باشگاه 🏋️</blockquote>",
        "nightcore": "🌃 <b>Nightcore شد!</b>\n<blockquote>شب، نور شهر، سرعت بالا 🌃✨</blockquote>",
        "bass": "🔊 <b>Bass Boost شد!</b>\n<blockquote>باسش قلبتو میلرزونه، با هندزفری گوش بده 🎧💥</blockquote>",
        "reverb": "🌊 <b>Reverb شد!</b>\n<blockquote>انگار داری توی یه سالن بزرگ گوش میدی 🏛️</blockquote>",
        "8d": "🎩 <b>8D شد!</b>\n<blockquote>هندزفری بذار، صدا دور سرت می‌چرخه��🎧</blockquote>"
    }

    filters = {
        "slowed": "atempo=0.8",
        "slowed_reverb": "atempo=0.8,aecho=0.8:0.9:1000:0.3",
        "speedup": "atempo=1.25",
        "nightcore": "asetrate=44100*1.25,aresample=44100",
        "bass": "bass=g=12:f=110:w=0.6",
        "reverb": "aecho=0.8:0.9:1000:0.3",
        "8d": "apulsator=hz=0.125"
    }

    try:
        cmd = f'ffmpeg -y -i "{input_path}" -filter:a "{filters[effect]}" "{output_path}"'
        subprocess.run(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        await callback.message.answer_audio(types.FSInputFile(output_path), caption=captions.get(effect, "<b>تموم شد! ✨</b>"))
        await callback.message.delete()
    except Exception as e:
        await callback.message.edit_text(f"❌ <b>خطا خورد:</b>\n<blockquote>{e}</blockquote>")
    finally:
        if os.path.exists(input_path):
            os.remove(input_path)
        if os.path.exists(output_path):
            os.remove(output_path)

async def handle(request):
    return web.Response(text="Bot is alive!")

async def main():
    await bot.set_my_commands([
        BotCommand(command="start", description="شروع بات 🚀"),
        BotCommand(command="help", description="راهنما 📖"),
    ])
    app = web.Application()
    app.router.add_get("/", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", 10000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print("بات روشن شد...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
