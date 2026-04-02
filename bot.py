import asyncio
import aiohttp
import time
import sqlite3
import random
import string
import os
import json
import logging
from datetime import datetime, timedelta

from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters, CallbackQueryHandler
from aiohttp import web

# ========================= CONFIG =========================
BOT_TOKEN = "8016499618:AAFuMAsws27GBEnOGpufm1vI4UeBfE7yAf4"
OWNER_ID = 5297630438
PORT = int(os.environ.get("PORT", 8080))

WELCOME_IMAGE = "https://i.postimg.cc/nczX6L6f/file-000000008f987230882c6568d09ed6e3-640x360.png"

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# ========================= LOAD APIS =========================
def load_apis():
    try:
        with open('api.json', 'r') as f:
            apis = json.load(f)
            logger.info(f"Loaded {len(apis)} APIs from api.json")
            return apis
    except Exception as e:
        logger.error(f"api.json load failed: {e}")
        return []

APIS = load_apis()

# ========================= DATABASE (Minimal) =========================
class Database:
    def __init__(self):
        self.conn = sqlite3.connect('fusion_premium.db', check_same_thread=False)
        self.create_tables()
        self.temp_attack_data = {}

    def create_tables(self):
        c = self.conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS users 
                    (user_id INTEGER PRIMARY KEY, premium_expiry TEXT, protected_number TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS redeem_codes 
                    (code TEXT PRIMARY KEY, days INTEGER, is_used INTEGER DEFAULT 0)''')
        self.conn.commit()

    def add_user(self, user_id):
        c = self.conn.cursor()
        c.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
        self.conn.commit()

    def is_premium(self, user_id):
        return True  # Change to full logic later

    def set_attack_data(self, user_id, phone):
        self.temp_attack_data[user_id] = {'phone': phone, 'ts': time.time()}

    def get_attack_data(self, user_id):
        data = self.temp_attack_data.get(user_id)
        if data and time.time() - data['ts'] < 300:
            return data['phone']
        return None

    def clear_attack_data(self, user_id):
        self.temp_attack_data.pop(user_id, None)

db = Database()

# ========================= ATTACK MANAGER =========================
class AttackManager:
    def __init__(self):
        self.active_attacks = {}

    async def start_attack(self, user_id, phone, duration):
        if user_id in self.active_attacks:
            return False
        self.active_attacks[user_id] = {"phone": phone, "running": True}
        logger.info(f"Attack started on {phone} for {duration} minutes")
        return True

manager = AttackManager()

# ========================= KEYBOARDS =========================
def main_kb():
    return ReplyKeyboardMarkup([
        [KeyboardButton("🚀 Call"), KeyboardButton("📊 Status")],
        [KeyboardButton("👤 Account"), KeyboardButton("❓ Help")]
    ], resize_keyboard=True)

def duration_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("5 Min", callback_data="dur_5")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel")]
    ])

# ========================= HANDLERS =========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    db.add_user(user_id)
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
        msg = "🔥 Attack Running!" if user_id in manager.active_attacks else "💤 No active attack"
        await update.message.reply_text(msg)

async def btn_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    uid = query.from_user.id

    if data.startswith("dur_"):
        phone = db.get_attack_data(uid)
        if phone:
            success = await manager.start_attack(uid, phone, 5)
            await query.edit_message_text(f"🚀 Attack Started on `{phone}`!" if success else "Failed")
        db.clear_attack_data(uid)

    elif data == "cancel":
        db.clear_attack_data(uid)
        await query.edit_message_text("❌ Cancelled")

# ========================= WEB SERVER =========================
async def web_server():
    async def handle(request):
        return web.Response(text="Bot is Alive! 🚀")
    app = web.Application()
    app.router.add_get('/', handle)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    logger.info(f"🌐 Web server started on port {PORT}")

# ========================= MAIN (Clean v20+ way) =========================
async def main():
    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_msg))
    application.add_handler(CallbackQueryHandler(btn_handler))

    asyncio.create_task(web_server())

    logger.info("✅ Bot is starting...")
    await application.initialize()
    await application.start()

    # Correct & Stable way for v20.7
    await application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    print("=" * 70)
    print("🔥 PREMIUM BOMBER Starting on Render")
    print(f"📊 APIs Loaded: {len(APIS)}")
    print(f"🌐 PORT: {PORT}")
    print("=" * 70)
    asyncio.run(main())
