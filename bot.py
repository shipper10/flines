import os
import json
import threading
import traceback
import logging
from typing import Any, Dict, List, Optional

from flask import Flask
from dotenv import load_dotenv

# telegram imports (v20+)
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

import genshin

load_dotenv()

# ----- Config & Logging -----
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("genshin-bot")

BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise SystemExit("Missing BOT_TOKEN environment variable")

PORT = int(os.environ.get("PORT", 8000))
DATA_FILE = "users.json"

# Ensure users file exists
if not os.path.exists(DATA_FILE):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump({}, f, ensure_ascii=False, indent=2)


# ----- helpers: load/save users -----
def load_users() -> Dict[str, Dict[str, Any]]:
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_users(users: Dict[str, Dict[str, Any]]) -> None:
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(users, f, ensure_ascii=False, indent=2)


# ----- helper: create genshin client (flexible) -----
def make_genshin_client(creds: Dict[str, Any], uid: Optional[str] = None) -> genshin.Client:
    """
    creds may include ltuid+ltoken, ltuid_v2+ltoken_v2, OR cookie_token.
    Pass all provided cookies to genshin.Client to support full cookie auth.
    """
    cookies = {}

    if creds.get("ltuid") and creds.get("ltoken"):
        cookies["ltuid"] = creds["ltuid"]
        cookies["ltoken"] = creds["ltoken"]

    if creds.get("ltuid_v2") and creds.get("ltoken_v2"):
        cookies["ltuid_v2"] = creds["ltuid_v2"]
        cookies["ltoken_v2"] = creds["ltoken_v2"]

    if creds.get("cookie_token"):
        cookies["cookie_token"] = creds["cookie_token"]

    if not cookies:
        raise ValueError("No stored credentials for this user.")

    try:
        if uid:
            return genshin.Client(cookies, uid=int(uid))
        return genshin.Client(cookies)
    except TypeError:
        # fallback: different kwarg style
        try:
            if uid:
                return genshin.Client(cookies=cookies, uid=int(uid))
        except Exception:
            pass
        return genshin.Client(cookies)


# ----- helper: try multiple async call names -----
async def try_calls(obj: Any, names: List[str], *args, **kwargs):
    """
    Try several coroutine attribute names on obj and return first success result.
    If none work, raise last exception.
    """
    last_exc = None
    for name in names:
        fn = getattr(obj, name, None)
        if callable(fn):
            try:
                return await fn(*args, **kwargs)
            except TypeError:
                try:
                    return await fn()
                except Exception as e2:
                    last_exc = e2
                    continue
            except Exception as e:
                last_exc = e
                continue
    if last_exc:
        raise last_exc
    raise RuntimeError(f"No callable found among: {names}")


# ----- Telegram command handlers -----
async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "مرحبًا! هذه الأوامر المدعومة (إن كانت مكتبتك تدعمها):\n\n"
        "🔧 إعداد:\n"
        "/link <ltuid> <ltoken> — ربط باستخدام ltuid & ltoken\n"
        "/link_cookie <cookie_token> — ربط باستخدام cookie_token\n"
        "/link_full_cookie <ltuid> <ltoken> <ltuid_v2> <ltoken_v2> — ربط باستخدام الكوكيز كاملة\n"
        "/unlink — حذف الربط\n\n"
        "📊 الحساب:\n"
        "/stats — إحصائيات الحساب\n"
        "/characters — قائمة الشخصيات\n"
        "/notes — Resin و Expedition وغيرها\n"
        "/transactions — آخر المعاملات\n\n"
        "🌀 الابيس:\n"
        "/abyss — Spiral Abyss الحالي\n"
        "/previous_abyss — Spiral Abyss السابق (إن توفّر)\n\n"
        "📅 يومي:\n"
        "/daily — بيانات المكافآت اليومية (إن توفّر)\n"
        "/check_in — محاولة المطالبة اليومية (إن تدعم المكتبة)\n\n"
        "/help — هذه الرسالة"
    )


# ---- link/unlink ----
async def cmd_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) != 2:
        await update.message.reply_text("❌ الصيغة: /link <ltuid> <ltoken>")
        return
    ltuid, ltoken = args
    users = load_users()
    key = str(update.effective_user.id)
    users.setdefault(key, {})
    users[key]["ltuid"] = ltuid
    users[key]["ltoken"] = ltoken
    # احذف الكوكيز القديمة اذا موجودة كاملة لتفادي التعارض
    users[key].pop("ltuid_v2", None)
    users[key].pop("ltoken_v2", None)
    users[key].pop("cookie_token", None)
    save_users(users)
    await update.message.reply_text("✅ تم حفظ ltuid و ltoken.")


async def cmd_link_cookie(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) != 1:
        await update.message.reply_text("❌ الصيغة: /link_cookie <cookie_token>")
        return
    cookie = args[0]
    users = load_users()
    key = str(update.effective_user.id)
    users.setdefault(key, {})
    users[key]["cookie_token"] = cookie
    # احذف الكوكيز القديمة لتفادي التعارض
    users[key].pop("ltuid", None)
    users[key].pop("ltoken", None)
    users[key].pop("ltuid_v2", None)
    users[key].pop("ltoken_v2", None)
    save_users(users)
    await update.message.reply_text("✅ تم حفظ cookie_token.")


async def cmd_link_full_cookie(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) != 4:
        await update.message.reply_text(
            "❌ الصيغة: /link_full_cookie <ltuid> <ltoken> <ltuid_v2> <ltoken_v2>"
        )
        return
    ltuid, ltoken, ltuid_v2, ltoken_v2 = args
    users = load_users()
    key = str(update.effective_user.id)
    users.setdefault(key, {})
    users[key]["ltuid"] = ltuid
    users[key]["ltoken"] = ltoken
    users[key]["ltuid_v2"] = ltuid_v2
    users[key]["ltoken_v2"] = ltoken_v2
    # احذف الكوكيز القديمة الأخرى
    users[key].pop("cookie_token", None)
    save_users(users)
    await update.message.reply_text("✅ تم حفظ الكوكيز كاملة.")


async def cmd_unlink(update: Update, context: ContextTypes.DEFAULT_TYPE):
    users = load_users()
    key = str(update.effective_user.id)
    if key in users:
        users.pop(key, None)
        save_users(users)
        await update.message.reply_text("✅ تم إلغاء الربط وحذف بياناتك محلياً.")
    else:
        await update.message.reply_text("ℹ️ لا يوجد حساب مربوط.")


# ---- account / notes / characters / transactions ----
async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    users = load_users()
    key = str(update.effective_user.id)
    u = users.get(key)
    if not u:
        await update.message.reply_text("⚠️ لم تربط حسابك بعد. استخدم /link أو /link_cookie")
        return
    try:
        client = make_genshin_client(u, uid=u.get("uid"))
        user = await try_calls(client, ["get_genshin_user", "get_user", "get_user_data"])
        stats = getattr(user, "stats", None) or (user.get("stats") if isinstance(user, dict) else None)
        if stats:
            ar = getattr(stats, "adventure_rank", None) or stats.get("adventure_rank", None)
            wl = getattr(stats, "world_level", None) or stats.get("world_level", None)
            chars = getattr(stats, "character_number", None) or stats.get("character_number", None) or "?"
            await update.message.reply_text(f"🏷 Adventure Rank: {ar}\n🌍 World Level: {wl}\n👥 Characters: {chars}")
            return
        await update.message.reply_text(str(user))
    except Exception as e:
        await update.message.reply_text(f"❌ خطأ في جلب البيانات:\n{e}")


async def cmd_characters(update: Update, context: ContextTypes.DEFAULT_TYPE):
    users = load_users()
    key = str(update.effective_user.id)
    u = users.get(key)
    if not u:
        await update.message.reply_text("⚠️ لم تربط حسابك بعد. استخدم /link أو /link_cookie")
        return
    try:
        client = make_genshin_client(u, uid=u.get("uid"))
        characters = await try_calls(client, ["get_characters"])
        msg = "👥 الشخصيات:\n"
        for char in characters:
            msg += f"- {char.name} (Level {char.level})\n"
        await update.message.reply_text(msg)
    except Exception as e:
        await update.message.reply_text(f"❌ خطأ في جلب الشخصيات:\n{e}")


async def cmd_notes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    users = load_users()
    key = str(update.effective_user.id)
    u = users.get(key)
    if not u:
        await update.message.reply_text("⚠️ لم تربط حسابك بعد. استخدم /link أو /link_cookie")
        return
    try:
        client = make_genshin_client(u, uid=u.get("uid"))
        notes = await try_calls(client, ["get_notes"])
        resin = getattr(notes, "current_resin", None) or notes.get("current_resin")
        max_resin = getattr(notes, "max_resin", None) or notes.get("max_resin")
        realm_currency = getattr(notes, "realm_currency", None) or notes.get("realm_currency")
        expeditions = getattr(notes, "expeditions", None) or notes.get("expeditions")
        msg = (
            f"📝 Resin: {resin}/{max_resin}\n"
            f"💰 Realm Currency: {realm_currency}\n"
            f"🚀 Expeditions:\n"
        )
        if expeditions:
            for e in expeditions:
                msg += f"- {e['avatar_name']}: {e['status']}\n"
        await update.message.reply_text(msg)
    except Exception as e:
        await update.message.reply_text(f"❌ خطأ في جلب الملاحظات:\n{e}")


async def cmd_transactions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    users = load_users()
    key = str(update.effective_user.id)
    u = users.get(key)
    if not u:
        await update.message.reply_text("⚠️ لم تربط حسابك بعد. استخدم /link أو /link_cookie")
        return
    try:
        client = make_genshin_client(u, uid=u.get("uid"))
        transactions = await try_calls(client, ["get_transactions"])
        if not transactions:
            await update.message.reply_text("لا توجد معاملات حديثة.")
            return
        msg = "💳 المعاملات الأخيرة:\n"
        for t in transactions[:10]:
            msg += f"- {t['name']} | {t['count']}x | {t['time']}\n"
        await update.message.reply_text(msg)
    except Exception as e:
        await update.message.reply_text(f"❌ خطأ في جلب المعاملات:\n{e}")


# ---- abyss / previous_abyss ----
async def cmd_abyss(update: Update, context: ContextTypes.DEFAULT_TYPE):
    users = load_users()
    key = str(update.effective_user.id)
    u = users.get(key)
    if not u:
        await update.message.reply_text("⚠️ لم تربط حسابك بعد. استخدم /link أو /link_cookie")
        return
    try:
        client = make_genshin_client(u, uid=u.get("uid"))
        abyss = await try_calls(client, ["get_abyss"])
        msg = f"🌀 Spiral Abyss (Current):\n"
        for floor in abyss["floors"]:
            msg += f"Floor {floor['index']} - {floor['rewards']['mora']} Mora\n"
        await update.message.reply_text(msg)
    except Exception as e:
        await update.message.reply_text(f"❌ خطأ في جلب Spiral Abyss:\n{e}")


async def cmd_previous_abyss(update: Update, context: ContextTypes.DEFAULT_TYPE):
    users = load_users()
    key = str(update.effective_user.id)
    u = users.get(key)
    if not u:
        await update.message.reply_text("⚠️ لم تربط حسابك بعد. استخدم /link أو /link_cookie")
        return
    try:
        client = make_genshin_client(u, uid=u.get("uid"))
        abyss = await try_calls(client, ["get_previous_abyss"])
        if not abyss:
            await update.message.reply_text("لا توجد بيانات Spiral Abyss سابقة.")
            return
        msg = f"🌀 Spiral Abyss (Previous):\n"
        for floor in abyss["floors"]:
            msg += f"Floor {floor['index']} - {floor['rewards']['mora']} Mora\n"
        await update.message.reply_text(msg)
    except Exception as e:
        await update.message.reply_text(f"❌ خطأ في جلب Spiral Abyss السابقة:\n{e}")


# ---- daily / check_in (if supported) ----
async def cmd_daily(update: Update, context: ContextTypes.DEFAULT_TYPE):
    users = load_users()
    key = str(update.effective_user.id)
    u = users.get(key)
    if not u:
        await update.message.reply_text("⚠️ لم تربط حسابك بعد. استخدم /link أو /link_cookie")
        return
    try:
        client = make_genshin_client(u, uid=u.get("uid"))
        daily = await try_calls(client, ["get_daily_note", "get_daily"])
        await update.message.reply_text(str(daily))
    except Exception as e:
        await update.message.reply_text(f"❌ خطأ في جلب البيانات اليومية:\n{e}")


async def cmd_check_in(update: Update, context: ContextTypes.DEFAULT_TYPE):
    users = load_users()
    key = str(update.effective_user.id)
    u = users.get(key)
    if not u:
        await update.message.reply_text("⚠️ لم تربط حسابك بعد. استخدم /link أو /link_cookie")
        return
    try:
        client = make_genshin_client(u, uid=u.get("uid"))
        check_in = await try_calls(client, ["check_in"])
        await update.message.reply_text(f"تم المطالبة اليومية: {check_in}")
    except Exception as e:
        await update.message.reply_text(f"❌ خطأ في المطالبة اليومية:\n{e}")


# ----- main bot setup -----
app = Flask(__name__)


@app.route("/")
def home():
    return "Bot is running."


def run_flask():
    app.run(host="0.0.0.0", port=PORT)


def main():
    application = ApplicationBuilder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("help", cmd_help))
    application.add_handler(CommandHandler("link", cmd_link))
    application.add_handler(CommandHandler("link_cookie", cmd_link_cookie))
    application.add_handler(CommandHandler("link_full_cookie", cmd_link_full_cookie))
    application.add_handler(CommandHandler("unlink", cmd_unlink))

    application.add_handler(CommandHandler("stats", cmd_stats))
    application.add_handler(CommandHandler("characters", cmd_characters))
    application.add_handler(CommandHandler("notes", cmd_notes))
    application.add_handler(CommandHandler("transactions", cmd_transactions))

    application.add_handler(CommandHandler("abyss", cmd_abyss))
    application.add_handler(CommandHandler("previous_abyss", cmd_previous_abyss))

    application.add_handler(CommandHandler("daily", cmd_daily))
    application.add_handler(CommandHandler("check_in", cmd_check_in))

    # تشغيل Flask في خيط منفصل (للمضيفات التي تحتاج ذلك)
    threading.Thread(target=run_flask).start()

    application.run_polling()


if __name__ == "__main__":
    main()
