import asyncio
import os
import subprocess
from aiogram import Bot, Dispatcher, types, F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiohttp import web

TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise ValueError("BOT_TOKEN ست نشده!")

bot = Bot(token=TOKEN)
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
        await message.reply("لطفاً یه فایل موزیک (mp3) بفرست 🎵")
        return

    user_files[message.from_user.id] = file_id
    await message.reply(
        f"آهنگت رسید: {file_name}\nحالا انتخاب کن چی کارش کنم؟ 👇",
        reply_markup=get_buttons()
    )

@dp.callback_query()
async def process_effect(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    if user_id not in user_files:
        await callback.answer("اول یه آهنگ بفرست!", show_alert=True)
        return

    effect = callback.data
    await callback.message.edit_text("⏳ دارم پردازش می‌کنم... چند ثانیه صبر کن...")

    file_id = user_files[user_id]
    file = await bot.get_file(file_id)
    input_path = f"input_{user_id}.mp3"
    output_path = f"output_{user_id}.mp3"
    await bot.download_file(file.file_path, input_path)

    captions = {
        "slowed": "🐌 Slowed شد!",
        "slowed_reverb": "🎧 Slowed + Reverb شد!",
        "speedup": "⚡ Speed Up شد!",
        "nightcore": "🌃 Nightcore شد!",
        "bass": "🔊 Bass Boost شد!",
        "reverb": "🌊 Reverb شد!",
        "8d": "🎩 8D شد!"
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

        await callback.message.answer_audio(types.FSInputFile(output_path), caption=captions.get(effect, "تموم شد!"))
        await callback.message.delete()
    except Exception as e:
        await callback.message.edit_text(f"خطا خورد: {e}")
    finally:
        if os.path.exists(input_path):
            os.remove(input_path)
        if os.path.exists(output_path):
            os.remove(output_path)

# وب‌سرور برای زنده موندن روی Render رایگان
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
    print("بات روشن شد...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())