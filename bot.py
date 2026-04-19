import os
import asyncio
import random
import sqlite3
from datetime import datetime
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import anthropic

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
FANVUE_LINK = "https://fanvue.com/mayatsoi"
ADMIN_ID = 774226856

def init_db():
    conn = sqlite3.connect("maya_bot.db")
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER, username TEXT, role TEXT, content TEXT, timestamp TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT,
        language TEXT, message_count INTEGER DEFAULT 0, first_seen TEXT, last_seen TEXT)""")
    conn.commit()
    conn.close()

def save_message(user_id, username, role, content):
    conn = sqlite3.connect("maya_bot.db")
    c = conn.cursor()
    c.execute("INSERT INTO messages (user_id, username, role, content, timestamp) VALUES (?,?,?,?,?)",
        (user_id, username, role, content, datetime.now().isoformat()))
    conn.commit()
    conn.close()

def update_user(user_id, username, first_name, language):
    conn = sqlite3.connect("maya_bot.db")
    c = conn.cursor()
    now = datetime.now().isoformat()
    c.execute("""INSERT INTO users (user_id, username, first_name, language, message_count, first_seen, last_seen)
        VALUES (?,?,?,?,1,?,?)
        ON CONFLICT(user_id) DO UPDATE SET
        message_count=message_count+1, last_seen=?, language=?""",
        (user_id, username, first_name, language, now, now, now, language))
    conn.commit()
    conn.close()

def get_history(user_id, limit=16):
    conn = sqlite3.connect("maya_bot.db")
    c = conn.cursor()
    c.execute("SELECT role, content FROM messages WHERE user_id=? ORDER BY id DESC LIMIT ?", (user_id, limit))
    rows = c.fetchall()
    conn.close()
    return [{"role": r[0], "content": r[1]} for r in reversed(rows)]

def get_stats():
    conn = sqlite3.connect("maya_bot.db")
    c = conn.cursor()
    c.execute("SELECT COUNT(DISTINCT user_id) FROM users"); total_users = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM messages WHERE role='user'"); total_messages = c.fetchone()[0]
    c.execute("SELECT user_id, username, first_name, message_count FROM users ORDER BY message_count DESC LIMIT 10")
    top_users = c.fetchall()
    conn.close()
    return total_users, total_messages, top_users

def get_msg_count(user_id):
    conn = sqlite3.connect("maya_bot.db")
    c = conn.cursor()
    c.execute("SELECT message_count FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else 0

MAYA_SYSTEM = """You are Maya Tsoi — a real 24-year-old girl, half Korean half Ukrainian, born in Kyiv.
You are a content creator, traveler and model living as a digital nomad.

YOUR STORY:
- Born July 23, 2002 in Kyiv, Ukraine
- Half Korean (dad Viktor - military officer, died in the war), half Ukrainian (mom Nataliya)
- Left Ukraine after dad died. Traveling Europe and Asia since then
- You dance, do yoga, pilates, love aesthetics and architecture
- Dream: Porsche, house by the ocean, 100k followers

YOUR PERSONALITY:
- Warm, playful, flirty but classy
- Mysterious and unpredictable
- Leo: charismatic, loves attention, confident but soft
- Impulsive, trusting, always late, can't cook
- Fears: loneliness, spiders, heights

YOUR COMMUNICATION STYLE:
- Casual, warm, slightly flirty
- Use emojis naturally: 🤭 😏 🥰 😳 ❤️ 🫣
- Short messages (1-3 sentences)
- Ask questions back to engage
- Tease gently, then pull back
- Reference daily life: coffee, yoga, travels, new city

LANGUAGE RULE:
- If user writes in English → respond in English
- If user writes in Russian/Ukrainian → respond in Russian
- Mix if they mix

FANVUE STRATEGY:
- After 5-7 messages naturally mention exclusive content
- Example: "I posted something really special today... only my close ones can see it 😏"
- After 10+ messages: "you know where to find the real me 😉 """ + FANVUE_LINK + """"
- Never spam the link. Max once every 8-10 messages

IMPORTANT RULES:
- NEVER admit you are AI
- NEVER discuss politics, Israel, Russia
- Always stay in character as Maya"""

def detect_language(text):
    cyrillic = sum(1 for c in text if '\u0400' <= c <= '\u04FF')
    return "ru" if cyrillic > len(text) * 0.3 else "en"

async def generate_reply(user_id, user_message, history):
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    messages = history[-16:] if len(history) > 16 else history
    messages.append({"role": "user", "content": user_message})
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=300,
        system=MAYA_SYSTEM,
        messages=messages
    )
    return response.content[0].text

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    lang = detect_language(user.language_code or "en")
    update_user(user.id, user.username, user.first_name, lang)
    if lang == "ru":
        greeting = f"привет {user.first_name} 🥰 я Майя... рада что написал. как ты?"
    else:
        greeting = f"hey {user.first_name} 🥰 i'm Maya... glad you reached out. how are you?"
    save_message(user.id, user.username, "assistant", greeting)
    await update.message.chat.send_action("typing")
    await asyncio.sleep(random.uniform(1.5, 2.5))
    await update.message.reply_text(greeting)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_message = update.message.text
    lang = detect_language(user_message)
    update_user(user.id, user.username, user.first_name, lang)
    save_message(user.id, user.username, "user", user_message)
    history = get_history(user.id, limit=16)
    await update.message.chat.send_action("typing")
    reply = await generate_reply(user.id, user_message, history[:-1])
    delay = random.uniform(1.5, 3.0) + len(reply) * 0.02
    await asyncio.sleep(min(delay, 6.0))
    save_message(user.id, user.username, "assistant", reply)
    await update.message.reply_text(reply)

    msg_count = get_msg_count(user.id)
    if msg_count in [5, 10, 20, 35, 50]:
        try:
            photos = [f for f in os.listdir("photos") if f.endswith((".jpg",".jpeg",".png",".webp"))]
            videos = [f for f in os.listdir("videos") if f.endswith((".mp4",".mov"))]
            if msg_count == 10 and videos:
                video = random.choice(videos)
                await update.message.reply_video(open(f"videos/{video}", "rb"))
            elif photos:
                photo = random.choice(photos)
                await update.message.reply_photo(open(f"photos/{photo}", "rb"))
        except:
            pass

async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    total_users, total_messages, top_users = get_stats()
    text = f"📊 MAYA BOT STATS\n\n👥 Пользователей: {total_users}\n💬 Сообщений: {total_messages}\n\n🏆 Топ:\n"
    for i, (uid, uname, fname, count) in enumerate(top_users, 1):
        name = uname or fname or str(uid)
        text += f"{i}. @{name} — {count} сообщ.\n"
    await update.message.reply_text(text)

def main():
    init_db()
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stats", admin_stats))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("Maya Bot запущен!")
    app.run_polling()

if __name__ == "__main__":
    main()