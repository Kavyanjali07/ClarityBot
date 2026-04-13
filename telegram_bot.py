from dotenv import load_dotenv
load_dotenv()  # loads tokens from .env file
import os
import requests
import json
import time
from pathlib import Path
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)

import db  # SQLite language storage

# === Config / Env ===
CONFIG_FILE = "claritybot_config.json"
PROMPT_FILE = "system-prompt.txt"

MODEL_CONFIG = {
    "name": "deepseek/deepseek-chat",  # or keep original: "tngtech/deepseek-r1t2-chimera:free"
    "base_url": "https://openrouter.ai/api/v1",
    "key": os.getenv("OPENROUTER_KEY"),
}

SITE_URL = "https://github.com/Kavyanjali07/ClarityBot"
SITE_NAME = "ClarityBot – Clear & Helpful AI Assistant"
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

# === Anti-Flood (3 seconds between messages) ===
LAST_MESSAGE_TIME = {}
FLOOD_DELAY = 3

# === Rate Limiting (10 messages per minute) ===
RATE_LIMIT = 10
RATE_WINDOW = 60
user_message_timestamps = {}

def check_rate_limit(user_id: int) -> bool:
    now = time.time()
    timestamps = user_message_timestamps.get(user_id, [])
    timestamps = [t for t in timestamps if now - t < RATE_WINDOW]
    if len(timestamps) >= RATE_LIMIT:
        return False
    timestamps.append(now)
    user_message_timestamps[user_id] = timestamps
    return True

# === Load base system prompt (optional) ===
if os.path.exists(PROMPT_FILE):
    with open(PROMPT_FILE, "r", encoding="utf-8") as f:
        BASE_PROMPT = f.read()
else:
    BASE_PROMPT = "You are ClarityBot, a helpful, ethical, and friendly AI assistant."

# === Memory System (conversation history) ===
MEMORY_FILE = "chat_memory.json"

def load_memory():
    if not os.path.exists(MEMORY_FILE):
        return {}
    try:
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}

def save_memory(data):
    try:
        with open(MEMORY_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print("Failed to save memory:", e)

CHAT_MEMORY = load_memory()

def add_to_history(user_id: str, role: str, content: str):
    if user_id not in CHAT_MEMORY:
        CHAT_MEMORY[user_id] = []
    CHAT_MEMORY[user_id].append({"role": role, "content": content})
    # Keep last 20 messages to avoid token overload
    if len(CHAT_MEMORY[user_id]) > 20:
        CHAT_MEMORY[user_id] = CHAT_MEMORY[user_id][-20:]
    save_memory(CHAT_MEMORY)

# === Build safe system prompt (multi-language) ===
def make_system_prompt(lang_code: str) -> str:
    if lang_code == "en":
        safety = (
            "You are ClarityBot, a helpful, ethical, and friendly assistant. "
            "Always answer in English. Be informative, respectful, and refuse harmful requests.\n\n"
        )
    else:
        safety = (
            "Kamu adalah ClarityBot, asisten yang membantu, etis, dan ramah. "
            "Selalu jawab dalam Bahasa Indonesia. Berikan informasi yang bermanfaat, "
            "hormati pengguna, dan tolak permintaan berbahaya.\n\n"
        )
    return safety + BASE_PROMPT

# === /start handler ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot_user = await context.bot.get_me()
    context.bot_data["username"] = bot_user.username

    keyboard = [
    [
        InlineKeyboardButton("🇮🇩 Indonesian", callback_data="lang_id"),
        InlineKeyboardButton("🇺🇸 English", callback_data="lang_en"),
    ],
    [
        InlineKeyboardButton("🇪🇸 Spanish", callback_data="lang_es"),
        InlineKeyboardButton("🇮🇳 Hindi", callback_data="lang_hi"),
    ],
    [
        InlineKeyboardButton("🇫🇷 French", callback_data="lang_fr"),
        InlineKeyboardButton("🇸🇦 Arabic", callback_data="lang_ar"),
    ],
]

    msg = (
        f"👋 Welcome to {SITE_NAME}\n"
        f"\n"
        f"🤖 Model: DeepSeek\n"
        f"💡 I provide clear, safe, and helpful answers.\n"
        f"\n"
        f"Please choose your language / Silakan pilih bahasa:"
    )

    await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard))

# === Language Callback (uses SQLite) ===
async def language_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id

    if query.data == "lang_id":
        db.set_lang(user_id, "id")
        await query.edit_message_text("✅ Bahasa Indonesia dipilih.")
    elif query.data == "lang_en":
        db.set_lang(user_id, "en")
        await query.edit_message_text("✅ English selected.")
    else:
        await query.edit_message_text("Error. Use /start again.")

# === /setlang command ===
async def setlang_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        return await update.message.reply_text("Usage: /setlang id | en")

    user_id = update.message.from_user.id
    code = args[0].lower()

    if code not in ("id", "en"):
        return await update.message.reply_text("Unknown language.")

    db.set_lang(user_id, code)
    await update.message.reply_text(f"✅ Language set: {code}")

# === /reset command ===
async def reset_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.message.from_user.id)
    if user_id in CHAT_MEMORY:
        del CHAT_MEMORY[user_id]
        save_memory(CHAT_MEMORY)
    await update.message.reply_text("🔄 Your conversation history has been cleared.")

# === Message Handler ===
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot_username = context.bot_data.get("username", "")
    user_id = update.message.from_user.id
    user_msg = update.message.text or ""
    chat_type = update.message.chat.type

    # === Anti-Flood (3 sec) ===
    now = time.time()
    last = LAST_MESSAGE_TIME.get(user_id, 0)
    if now - last < FLOOD_DELAY:
        await update.message.reply_text("⏳ Slow mode (3 sec). Please wait...")
        return
    LAST_MESSAGE_TIME[user_id] = now

    # === Rate Limit (10 msg/min) ===
    if not check_rate_limit(user_id):
        await update.message.reply_text(f"⏳ Rate limit: {RATE_LIMIT} messages per minute. Please slow down.")
        return

    # === In groups, require mention ===
    if chat_type in ["group", "supergroup"]:
        if not user_msg.startswith("/") and f"@{bot_username}" not in user_msg:
            return  # ignore

    # === Get user language from SQLite ===
    lang = db.get_lang(user_id)  # returns "id" or "en"

    # === Build system prompt ===
    system_prompt = make_system_prompt(lang)

    # === Add user message to memory ===
    user_id_str = str(user_id)
    add_to_history(user_id_str, "user", user_msg)

    # === Retrieve recent history (last 6 exchanges) ===
    history = CHAT_MEMORY.get(user_id_str, [])[-6:]

    # === Build payload with system prompt + history ===
    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(history)

    payload = {
        "model": MODEL_CONFIG["name"],
        "messages": messages,
    }

    headers = {
        "Authorization": f"Bearer {MODEL_CONFIG['key']}",
        "Content-Type": "application/json",
    }

    try:
        await update.message.chat.send_action("typing")
    except:
        pass

    try:
        res = requests.post(
            f"{MODEL_CONFIG['base_url']}/chat/completions",
            headers=headers,
            json=payload,
            timeout=30,
        )

        if res.status_code != 200:
            reply = f"⚠️ API ERROR {res.status_code}\n{res.text[:200]}"
        else:
            data = res.json()
            reply = data["choices"][0]["message"]["content"]
    except Exception as e:
        reply = f"❌ Request failed: {e}"

    # === Save assistant reply to memory ===
    add_to_history(user_id_str, "assistant", reply)

    await update.message.reply_text(reply)

# === Build App ===
app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CallbackQueryHandler(language_callback, pattern="^lang_"))
app.add_handler(CommandHandler("setlang", setlang_cmd))
app.add_handler(CommandHandler("reset", reset_cmd))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

# === Run Bot ===
def run_bot():
    print("🚀 ClarityBot is running... (Safe AI)")
    app.run_polling()

if __name__ == "__main__":
    run_bot()