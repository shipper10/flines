import os
import json
import genshin
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# تحميل المتغيرات من .env
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

# ملف تخزين بيانات المستخدمين
DATA_FILE = "users.json"

# تحميل أو إنشاء ملف المستخدمين
if not os.path.exists(DATA_FILE):
    with open(DATA_FILE, "w") as f:
        json.dump({}, f)

def load_users():
    with open(DATA_FILE, "r") as f:
        return json.load(f)

def save_users(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)

# أمر /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 مرحبًا! أنا بوت Genshin Impact.\n"
        "اربط حسابك باستخدام:\n"
        "`/link ltuid ltoken`\n"
        "ثم سجل UID الخاص بك بـ `/setuid UID`",
        parse_mode="Markdown"
    )

# أمر /link لربط الحساب
async def link_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
    users = load_users()
    args = context.args
    if len(args) != 2:
        await update.message.reply_text("❌ الصيغة الصحيحة: `/link ltuid ltoken`", parse_mode="Markdown")
        return
    ltuid, ltoken = args
    user_id = str(update.effective_user.id)
    if user_id not in users:
        users[user_id] = {}
    users[user_id]["ltuid"] = ltuid
    users[user_id]["ltoken"] = ltoken
    save_users(users)
    await update.message.reply_text("✅ تم ربط حسابك بنجاح!")

# أمر /setuid
async def set_uid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    users = load_users()
    args = context.args
    if len(args) != 1:
        await update.message.reply_text("❌ الصيغة الصحيحة: `/setuid UID`", parse_mode="Markdown")
        return
    uid = args[0]
    user_id = str(update.effective_user.id)
    if user_id not in users:
        users[user_id] = {}
    users[user_id]["uid"] = uid
    save_users(users)
    await update.message.reply_text(f"✅ تم حفظ UID الخاص بك: {uid}")

# أمر /resin
async def get_resin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    users = load_users()
    user_id = str(update.effective_user.id)
    if user_id not in users or "ltuid" not in users[user_id] or "ltoken" not in users[user_id]:
        await update.message.reply_text("⚠️ لم تربط حسابك بعد.\nاستخدم `/link ltuid ltoken`", parse_mode="Markdown")
        return
    creds = users[user_id]
    client = genshin.Client({"ltuid": creds["ltuid"], "ltoken": creds["ltoken"]})
    try:
        notes = await client.get_genshin_notes(uid=users[user_id]["uid"])
        await update.message.reply_text(f"🔋 لديك {notes.current_resin}/{notes.max_resin} Resin")
    except Exception as e:
        await update.message.reply_text(f"❌ حدث خطأ: {e}")

# أمر /abyss
async def abyss(update: Update, context: ContextTypes.DEFAULT_TYPE):
    users = load_users()
    user_id = str(update.effective_user.id)
    if user_id not in users or "ltuid" not in users[user_id] or "ltoken" not in users[user_id] or "uid" not in users[user_id]:
        await update.message.reply_text("⚠️ تأكد أنك ربطت حسابك وأضفت UID.")
        return
    creds = users[user_id]
    client = genshin.Client({"ltuid": creds["ltuid"], "ltoken": creds["ltoken"]})
    try:
        data = await client.get_spiral_abyss(users[user_id]["uid"])
        await update.message.reply_text(
            f"🌀 Spiral Abyss:\nStars: {data.total_stars}\nFloors: {len(data.floors)}"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ حدث خطأ: {e}")

# أمر /stygian
async def stygian(update: Update, context: ContextTypes.DEFAULT_TYPE):
    users = load_users()
    user_id = str(update.effective_user.id)
    if user_id not in users or "ltuid" not in users[user_id] or "ltoken" not in users[user_id] or "uid" not in users[user_id]:
        await update.message.reply_text("⚠️ تأكد أنك ربطت حسابك وأضفت UID.")
        return
    creds = users[user_id]
    client = genshin.Client({"ltuid": creds["ltuid"], "ltoken": creds["ltoken"]})
    try:
        data = await client.get_stygian(users[user_id]["uid"])
        await update.message.reply_text(f"⚔️ Stygian Onslaught: {data}")
    except Exception as e:
        await update.message.reply_text(f"❌ حدث خطأ: {e}")

# أمر /lobby
async def lobby(update: Update, context: ContextTypes.DEFAULT_TYPE):
    users = load_users()
    user_id = str(update.effective_user.id)
    if user_id not in users or "ltuid" not in users[user_id] or "ltoken" not in users[user_id] or "uid" not in users[user_id]:
        await update.message.reply_text("⚠️ تأكد أنك ربطت حسابك وأضفت UID.")
        return
    creds = users[user_id]
    client = genshin.Client({"ltuid": creds["ltuid"], "ltoken": creds["ltoken"]})
    try:
        data = await client.get_theater(users[user_id]["uid"])
        await update.message.reply_text(f"🎭 Theater Lobby: {data}")
    except Exception as e:
        await update.message.reply_text(f"❌ حدث خطأ: {e}")

# تشغيل البوت
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("link", link_account))
    app.add_handler(CommandHandler("setuid", set_uid))
    app.add_handler(CommandHandler("resin", get_resin))
    app.add_handler(CommandHandler("abyss", abyss))
    app.add_handler(CommandHandler("stygian", stygian))
    app.add_handler(CommandHandler("lobby", lobby))
    print("🚀 البوت يعمل الآن...")
    app.run_polling()

if __name__ == "__main__":
    main()
