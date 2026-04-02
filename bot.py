import asyncio
import os
import json
import logging
import time
from aiohttp import web

from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackQueryHandler, ContextTypes

# ====================== CONFIG ======================
BOT_TOKEN = "8016499618:AAFuMAsws27GBEnOGpufm1vI4UeBfE7yAf4"
OWNER_ID = 5297630438
PORT = int(os.environ.get("PORT", 8080))

WELCOME_IMAGE = "https://i.postimg.cc/nczX6L6f/file-000000008f987230882c6568d09ed6e3-640x360.png"

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# ====================== LOAD APIS ======================
def load_apis():
    try:
        with open('api.json', 'r') as f:
            apis = json.load(f)
            logger.info(f"Loaded {len(apis)} APIs from api.json")
            return apis
    except Exception as e:
        logger.error(f"api.json error: {e}")
        return []

APIS = load_apis()

# ====================== SIMPLE DB ======================
class Database:
    def __init__(self):
        self.temp_attack_data = {}

    def add_user(self, user_id): pass
    def is_premium(self, user_id): return True

    def set_attack_data(self, user_id, phone):
        self.temp_attack_data[user_id] = phone

    def get_attack_data(self, user_id):
        return self.temp_attack_data.get(user_id)

    def clear_attack_data(self, user_id):
        self.temp_attack_data.pop(user_id, None)

db = Database()

# ====================== ATTACK MANAGER ======================
class AttackManager:
    def __init__(self):
        self.active_attacks = {}

    async def start_attack(self, user_id, phone, duration):
        if user_id in self.active_attacks:
            return False
        self.active_attacks[user_id] = {"phone": phone}
        logger.info(f"🚀 Attack started on {phone} for {duration} min")
        return True

manager = AttackManager()

# ====================== KEYBOARDS ======================
def main_kb():
    return ReplyKeyboardMarkup([
        [KeyboardButton("🚀 Call"), KeyboardButton("📊 Status")]
    ], resize_keyboard=True)

def duration_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("5 Min", callback_data="dur_5")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel")]
    ])

# ====================== HANDLERS ======================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_photo(WELCOME_IMAGE, caption="👋 Welcome to Premium Bomber!", reply_markup=main_kb())

async def handle_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.effective_user.id

    if text == "🚀 Call":
        await update.message.reply_text("📞 Enter 10-digit phone number:")
        context.user_data['waiting_number'] = True

    elif context.user_data.get('waiting_number') and len(text) == 10 and text.isdigit():
        context.user_data.pop('waiting_number', None)
        db.set_attack_data(user_id, text)
        await update.message.reply_text(f"Target: `{text}`\nSelect duration:", reply_markup=duration_kb(), parse_mode="Markdown")

    elif text == "📊 Status":
        status = "🔥 Attack Running!" if user_id in manager.active_attacks else "💤 No active attack"
        await update.message.reply_text(status)

async def btn_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    uid = query.from_user.id

    if data.startswith("dur_"):
        phone = db.get_attack_data(uid)
        if phone:
            await manager.start_attack(uid, phone, 5)
            await query.edit_message_text(f"🚀 Attack Started on `{phone}`!")
        db.clear_attack_data(uid)

    elif data == "cancel":
        db.clear_attack_data(uid)
        await query.edit_message_text("❌ Cancelled")

# ====================== WEB SERVER ======================
async def web_server():
    async def handle(request):
        return web.Response(text="Bot is Alive! 🚀")
    app = web.Application()
    app.router.add_get('/', handle)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    logger.info(f"🌐 Web server running on port {PORT}")

# ====================== MAIN (Sabse Safe) ======================
async def main():
    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_msg))
    application.add_handler(CallbackQueryHandler(btn_handler))

    asyncio.create_task(web_server())

    logger.info("🔥 PREMIUM BOMBER Starting...")
    logger.info(f"📊 APIs Loaded: {len(APIS)} | PORT: {PORT}")

    # Yeh line sabse important hai - v20.7 ke liye recommended
    await application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    asyncio.run(main())
