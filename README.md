# 🚀 FREE BOMBER - Telegram Bot

A completely FREE Telegram bot for SMS, Call, and WhatsApp attacks with 234+ APIs.

## 🎯 Features

✅ **SMS Attacks** - Send unlimited SMS  
✅ **Call Attacks** - Make continuous calls  
✅ **WhatsApp Attacks** - Send WhatsApp messages  
✅ **Duration Control** - 1 min to 8 hours  
✅ **Number Protection** - Protect your number from attacks  
✅ **Admin Panel** - Broadcast and stats  
✅ **Completely FREE** - No premium gating

---

## 📦 Local Development

### Install dependencies:
```bash
npm install
```

### Run locally:
```bash
npm start
```

### Configuration
Create a `.env` file in the project root with these values:
```bash
BOT_TOKEN="your_bot_token"
OWNER_ID="6684734209"
```

You can also copy `.env.example` and update it with your token.

### Notes
- The bot uses polling by default.
- A simple health endpoint is available at `/`.

---

## 📊 Files Structure

```
.
├── index.js             # Main Node.js bot
├── package.json         # Node.js package definition
├── api.json             # Attack API definitions
├── fusion_premium.db    # SQLite database
└── README.md            # Project documentation
```

---

## 🆘 Troubleshooting

**Q: Bot not responding?**
A: Verify `BOT_TOKEN` is correct and the bot is running.

**Q: I changed api.json but the bot still uses old APIs?**
A: Restart the bot after editing `api.json`.

---

## ⚠️ Legal Notice

This bot is for educational purposes only. Unauthorized SMS/Call bombing may be illegal in your jurisdiction. Use responsibly!

---

## 📧 Support

Need help? Create an issue or contact the owner.
