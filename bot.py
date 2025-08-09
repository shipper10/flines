# bot.py
import os
import json
import asyncio
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
    creds may include ltuid+ltoken OR cookie_token.
    Try different constructor signatures for genshin.Client.
    """
    cookies = None
    if creds.get("ltuid") and creds.get("ltoken"):
        cookies = {"ltuid": creds["ltuid"], "ltoken": creds["ltoken"]}
    elif creds.get("cookie_token"):
        cookies = {"cookie_token": creds["cookie_token"]}
    else:
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
                # try without args if TypeError (many genshin.py signatures differ)
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
    save_users(users)
    await update.message.reply_text("✅ تم حفظ cookie_token.")


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
        logger.error(traceback.format_exc())
        await update.message.reply_text(f"❌ فشل جلب الإحصائيات: {e}")


async def cmd_characters(update: Update, context: ContextTypes.DEFAULT_TYPE):
    users = load_users()
    key = str(update.effective_user.id)
    u = users.get(key)
    if not u:
        await update.message.reply_text("⚠️ لم تربط حسابك بعد.")
        return
    try:
        client = make_genshin_client(u, uid=u.get("uid"))
        data = await try_calls(client, ["get_characters", "get_genshin_user", "get_characters_list"])
        chars = None
        if isinstance(data, dict):
            chars = data.get("avatars") or data.get("characters") or data.get("data")
        else:
            chars = getattr(data, "avatars", None) or getattr(data, "characters", None)
        if not chars:
            await update.message.reply_text("ℹ️ لم أتمكن من استخراج قائمة الشخصيات من هذه النسخة من genshin.py.")
            return
        lines = []
        for c in chars[:30]:
            name = getattr(c, "name", None) or (c.get("name") if isinstance(c, dict) else str(c))
            level = getattr(c, "level", None) or (c.get("level") if isinstance(c, dict) else "?")
            lines.append(f"{name} — Lv {level}")
        await update.message.reply_text("\n".join(lines) if lines else "لا توجد شخصيات.")
    except Exception as e:
        logger.error(traceback.format_exc())
        await update.message.reply_text(f"❌ خطأ في جلب الشخصيات: {e}")


async def cmd_notes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    users = load_users()
    key = str(update.effective_user.id)
    u = users.get(key)
    if not u:
        await update.message.reply_text("⚠️ لم تربط حسابك بعد.")
        return
    try:
        client = make_genshin_client(u, uid=u.get("uid"))
        notes = await try_calls(client, ["get_notes", "get_genshin_notes", "get_daily_notes"])
        current_resin = getattr(notes, "current_resin", None) or (notes.get("current_resin") if isinstance(notes, dict) else None)
        max_resin = getattr(notes, "max_resin", None) or (notes.get("max_resin") if isinstance(notes, dict) else None)
        expeditions = getattr(notes, "expeditions", None) or (notes.get("expeditions") if isinstance(notes, dict) else None)
        lines = []
        if current_resin is not None:
            lines.append(f"🔋 Resin: {current_resin}/{max_resin}")
        if expeditions:
            lines.append(f"🚩 Expeditions: {len(expeditions)} active")
        if lines:
            await update.message.reply_text("\n".join(lines))
            return
        await update.message.reply_text(str(notes))
    except Exception as e:
        logger.error(traceback.format_exc())
        await update.message.reply_text(f"❌ خطأ في جلب الملاحظات: {e}")


async def cmd_transactions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    users = load_users()
    key = str(update.effective_user.id)
    u = users.get(key)
    if not u:
        await update.message.reply_text("⚠️ لم تربط حسابك بعد.")
        return
    try:
        client = make_genshin_client(u, uid=u.get("uid"))
        data = await try_calls(client, ["get_transactions", "get_transaction_history", "get_wallet_records"])
        entries = None
        if isinstance(data, dict):
            entries = data.get("transactions") or data.get("items") or data.get("data")
        else:
            entries = getattr(data, "transactions", None) or getattr(data, "items", None)
        if not entries:
            await update.message.reply_text("ℹ️ لا توجد بيانات معاملات متاحة مع هذه النسخة.")
            return
        lines = []
        for e in entries[:10]:
            if isinstance(e, dict):
                kind = e.get("type") or e.get("name") or str(e)
            else:
                kind = getattr(e, "type", None) or str(e)
            lines.append(f"- {kind}")
        await update.message.reply_text("\n".join(lines))
    except Exception as e:
        logger.error(traceback.format_exc())
        await update.message.reply_text(f"❌ خطأ في جلب المعاملات: {e}")


# ---- Abyss ----
async def cmd_abyss(update: Update, context: ContextTypes.DEFAULT_TYPE):
    users = load_users()
    key = str(update.effective_user.id)
    u = users.get(key)
    if not u:
        await update.message.reply_text("⚠️ لم تربط حسابك بعد.")
        return
    try:
        client = make_genshin_client(u, uid=u.get("uid"))
        abyss = await try_calls(client, ["get_spiral_abyss", "get_abyss", "spiral_abyss"], u.get("uid"))
        total_stars = getattr(abyss, "total_stars", None) or (abyss.get("total_stars") if isinstance(abyss, dict) else None)
        floors = getattr(abyss, "floors", None) or (abyss.get("floors") if isinstance(abyss, dict) else None)
        lines = []
        if total_stars is not None:
            lines.append(f"⭐ إجمالي النجوم: {total_stars}")
        if floors:
            try:
                for f in floors:
                    idx = getattr(f, "index", None) or (f.get("index") if isinstance(f, dict) else "?")
                    stars = getattr(f, "stars", None) or (f.get("stars") if isinstance(f, dict) else "?")
                    lines.append(f"🔸 Floor {idx}: {stars}⭐")
            except Exception:
                lines.append(f"Floors: {len(floors)}")
        if not lines:
            lines = [str(abyss)]
        await update.message.reply_text("\n".join(lines))
    except Exception as e:
        logger.error(traceback.format_exc())
        await update.message.reply_text(f"❌ خطأ في جلب Abyss: {e}")


async def cmd_prev_abyss(update: Update, context: ContextTypes.DEFAULT_TYPE):
    users = load_users()
    key = str(update.effective_user.id)
    u = users.get(key)
    if not u:
        await update.message.reply_text("⚠️ لم تربط حسابك بعد.")
        return
    try:
        client = make_genshin_client(u, uid=u.get("uid"))
        prev = await try_calls(client, ["get_prev_spiral_abyss", "get_previous_spiral_abyss", "get_spiral_abyss_previous"])
        await update.message.reply_text(str(prev))
    except Exception as e:
        logger.error(traceback.format_exc())
        await update.message.reply_text("ℹ️ هذه الوظيفة غير مدعومة في نسخة المكتبة أو حدث خطأ.")


# ---- Daily / check-in (best-effort) ----
async def cmd_daily(update: Update, context: ContextTypes.DEFAULT_TYPE):
    users = load_users()
    key = str(update.effective_user.id)
    u = users.get(key)
    if not u:
        await update.message.reply_text("⚠️ لم تربط حسابك بعد.")
        return
    try:
        client = make_genshin_client(u, uid=u.get("uid"))
        daily = await try_calls(client, ["get_daily_rewards", "get_signin_rewards", "get_daily_info"])
        await update.message.reply_text(str(daily))
    except Exception as e:
        logger.error(traceback.format_exc())
        await update.message.reply_text("ℹ️ مكتبتك لا تدعم بيانات المكافآت اليومية.")


async def cmd_check_in(update: Update, context: ContextTypes.DEFAULT_TYPE):
    users = load_users()
    key = str(update.effective_user.id)
    u = users.get(key)
    if not u:
        await update.message.reply_text("⚠️ لم تربط حسابك بعد.")
        return
    try:
        client = make_genshin_client(u, uid=u.get("uid"))
        res = await try_calls(client, ["claim_daily_reward", "do_sign_in", "signin"])
        await update.message.reply_text(f"✅ نتيجة الطلب:\n{res}")
    except Exception as e:
        logger.error(traceback.format_exc())
        await update.message.reply_text("ℹ️ مكتبتك لا تدعم المطالبة التلقائية.")


# ----- Bot runner (async) -----
async def run_bot_async():
    logger.info("Building telegram Application...")
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # register handlers
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("start", cmd_help))
    app.add_handler(CommandHandler("link", cmd_link))
    app.add_handler(CommandHandler("link_cookie", cmd_link_cookie))
    app.add_handler(CommandHandler("unlink", cmd_unlink))

    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("characters", cmd_characters))
    app.add_handler(CommandHandler("notes", cmd_notes))
    app.add_handler(CommandHandler("transactions", cmd_transactions))

    app.add_handler(CommandHandler("abyss", cmd_abyss))
    app.add_handler(CommandHandler("previous_abyss", cmd_prev_abyss))

    app.add_handler(CommandHandler("daily", cmd_daily))
    app.add_handler(CommandHandler("check_in", cmd_check_in))

    logger.info("Starting polling...")
    # run_polling is a coroutine-friendly blocking call
    await app.run_polling()


# ----- Flask health server -----
server = Flask("health_server")


@server.route("/", methods=["GET"])
def health():
    return "OK", 200


def run_flask():
    logger.info(f"Starting Flask server on port {PORT}")
    # Use threaded dev server — fine for Koyeb health-check purpose
    server.run(host="0.0.0.0", port=PORT)


# ----- Main: start Flask thread then asyncio loop for bot -----
def main():
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()

    try:
        asyncio.run(run_bot_async())
    except Exception:
        logger.error("Bot crashed:\n" + traceback.format_exc())


if __name__ == "__main__":
    main()
