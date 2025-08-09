import os
import json
import genshin
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# تحميل المتغيرات من .env في الوضع المحلي
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
DATA_FILE = "users.json"

# تحميل بيانات المستخدمين
if os.path.exists(DATA_FILE):
    with open(DATA_FILE, "r") as f:
        users = json.load(f)
else:
    users = {}

# حفظ البيانات
def save_users():
    with open(DATA_FILE, "w") as f:
        json.dump(users, f)

# أمر بدء البوت
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "أهلاً! أنا بوت Genshin.\n"
        "استخدم /link لربط حسابك.\n"
        "أوامر أخرى:\n"
        "/resin - عرض الريزن\n"
        "/abyss - عرض Spiral Abyss\n"
        "/stygian - عرض Stygian Onslaught\n"
        "/lobby - عرض Theater Lobby"
    )

# ربط الحساب (Token HoYoLAB)
async def link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 1:
        await update.message.reply_text("❌ أرسل التوكين فقط مثل:\n/link your_cookie_token")
        return

    cookie_token = context.args[0]
    user_id = str(update.effective_user.id)
    users[user_id] = {"cookie_token": cookie_token, "uid": None}
    save_users()
    await update.message.reply_text("✅ تم حفظ التوكين الخاص بك.")

# حفظ UID
async def set_uid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 1:
        await update.message.reply_text("❌ أرسل UID مثل:\n/setuid 700000000")
        return

    uid = context.args[0]
    user_id = str(update.effective_user.id)
    if user_id not in users:
        await update.message.reply_text("❌ اربط التوكين أولاً باستخدام /link")
        return

    users[user_id]["uid"] = uid
    save_users()
    await update.message.reply_text(f"✅ تم حفظ UID: {uid}")

# عرض الريزن
async def resin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if user_id not in users or not users[user_id]["uid"]:
        await update.message.reply_text("❌ اربط التوكين و UID أولاً.")
        return

    client = genshin.Client({"cookie_token": users[user_id]["cookie_token"]})
    data = await client.get_notes(uid=users[user_id]["uid"])
    await update.message.reply_text(f"🔋 Resin: {data.current_resin}/{data.max_resin}")

# Spiral Abyss
async def abyss(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if user_id not in users or not users[user_id]["uid"]:
        await update.message.reply_text("❌ اربط التوكين و UID أولاً.")
        return

    client = genshin.Client({"cookie_token": users[user_id]["cookie_token"]})
    data = await client.get_spiral_abyss(uid=users[user_id]["uid"])
    await update.message.reply_text(f"🏰 Spiral Abyss:\nFloors: {data.max_floor}\nStars: {data.total_stars}")

# Stygian Onslaught
async def stygian(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⚔ بيانات Stygian Onslaught ستتم إضافتها لاحقًا.")

# Theater Lobby
async def lobby(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🎭 بيانات Theater Lobby ستتم إضافتها لاحقًا.")

# تشغيل البوت
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("link", link))
    app.add_handler(CommandHandler("setuid", set_uid))
    app.add_handler(CommandHandler("resin", resin))
    app.add_handler(CommandHandler("abyss", abyss))
    app.add_handler(CommandHandler("stygian", stygian))
    app.add_handler(CommandHandler("lobby", lobby))

    app.run_polling()

if __name__ == "__main__":
    main()
