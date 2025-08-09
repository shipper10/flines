#!/usr/bin/env python3
import os
import json
import logging
from typing import Dict, Any, List, Optional

import requests
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    CallbackQueryHandler,
)

# Load .env (optional on Koyeb if you use env vars)
load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("enka-bot")

BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise SystemExit("Missing BOT_TOKEN environment variable")

USERS_FILE = "users.json"
if not os.path.exists(USERS_FILE):
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump({}, f, ensure_ascii=False, indent=2)


def load_users() -> Dict[str, Dict[str, str]]:
    try:
        with open(USERS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_users(d: Dict[str, Dict[str, str]]) -> None:
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)


# short command -> enka API path
GAME_ENDPOINTS = {
    "gen": "api/uid/{uid}",        # Genshin
    "hsr": "api/hsr/uid/{uid}",    # Honkai Star Rail
    "zzz": "api/zzz/uid/{uid}",    # Zenless Zone Zero
}

ENKA_BASE = "https://enka.network"


def build_enka_url(game: str, uid: str) -> str:
    if game not in GAME_ENDPOINTS:
        raise ValueError("Unsupported game")
    path = GAME_ENDPOINTS[game].format(uid=uid)
    return f"{ENKA_BASE.rstrip('/')}/{path.lstrip('/')}"


def fetch_enka_data(game: str, uid: str, timeout: int = 10) -> Optional[Dict[str, Any]]:
    url = build_enka_url(game, uid)
    try:
        r = requests.get(url, timeout=timeout)
        if r.status_code != 200:
            logger.warning("Enka returned %s for %s", r.status_code, url)
            return None
        return r.json()
    except Exception as e:
        logger.exception("Error fetching Enka data: %s", e)
        return None


def extract_characters_from_response(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Return list of character entries: each entry is dict with 'name' and 'raw' (the original object).
    Try several known keys used by Enka API.
    """
    if not isinstance(data, dict):
        return []

    # Known Enka response fields for Genshin: 'playerInfo' and 'avatarInfoList'
    # For other games it might be 'avatars' or 'characters'
    # Search common places:
    # 1) avatarInfoList
    if "avatarInfoList" in data and isinstance(data["avatarInfoList"], list):
        out = []
        for item in data["avatarInfoList"]:
            if not isinstance(item, dict):
                continue
            name = item.get("name") or item.get("avatarName") or item.get("icon") or item.get("id") or "Unknown"
            out.append({"name": str(name), "raw": item})
        if out:
            return out

    # 2) try top-level keys
    for key in ("avatars", "characters", "data", "playerInfo", "player"):
        maybe = data.get(key)
        if isinstance(maybe, list) and maybe:
            out = []
            for item in maybe:
                if not isinstance(item, dict):
                    continue
                name = item.get("name") or item.get("avatarName") or item.get("character") or item.get("icon") or "Unknown"
                out.append({"name": str(name), "raw": item})
            if out:
                return out

    # 3) sometimes nested inside 'player' or others
    # try to search recursively for a list of dicts that contain 'name' or 'avatarId'
    def search_for_list(d):
        if isinstance(d, list):
            # detect if this list looks like characters
            candidates = []
            for el in d:
                if isinstance(el, dict):
                    if any(k in el for k in ("name", "avatarName", "icon", "id", "avatarId", "character")):
                        candidates.append(el)
            if candidates:
                return candidates
        elif isinstance(d, dict):
            for v in d.values():
                res = search_for_list(v)
                if res:
                    return res
        return None

    found = search_for_list(data)
    if found:
        out = []
        for item in found:
            name = item.get("name") or item.get("avatarName") or item.get("icon") or "Unknown"
            out.append({"name": str(name), "raw": item})
        if out:
            return out

    return []


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "مرحبًا! أوامر البوت:\n"
        "/set <game> <uid> — حفظ UID (game: gen | hsr | zzz)\n"
        "/account — عرض الحسابات المحفوظة\n"
        "/gen — Genshin\n"
        "/hsr — Honkai: Star Rail\n"
        "/zzz — Zenless Zone Zero\n\n"
        "مثال: /set gen 700000001\n"
        "بعد حفظ UID اكتب /gen لعرض شخصياتك (زر لاختيار الشخصية سيظهر)."
    )


async def cmd_set(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) != 2:
        await update.message.reply_text("❌ الصيغة: /set <game> <uid> — مثال: /set gen 700000001")
        return
    game = args[0].lower()
    uid = args[1].strip()
    if game not in GAME_ENDPOINTS:
        await update.message.reply_text("❌ اللعبة غير مدعومة. استخدم: gen, hsr, zzz")
        return
    users = load_users()
    key = str(update.effective_user.id)
    users.setdefault(key, {})[game] = uid
    save_users(users)
    await update.message.reply_text(f"✅ تم حفظ UID للحساب ({game}): {uid}")


async def cmd_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
    users = load_users()
    key = str(update.effective_user.id)
    u = users.get(key, {})
    if not u:
        await update.message.reply_text("ℹ️ لا توجد حسابات محفوظة. استخدم /set <game> <uid>")
        return
    lines = [f"{g}: {uid}" for g, uid in u.items()]
    await update.message.reply_text("حساباتك المحفوظة:\n" + "\n".join(lines))


async def cmd_game_generic(update: Update, context: ContextTypes.DEFAULT_TYPE, game: str):
    users = load_users()
    key = str(update.effective_user.id)
    u = users.get(key, {})
    uid = u.get(game)

    # allow: /gen <uid> to set on the fly
    if not uid and context.args:
        first = context.args[0]
        if first.isdigit():
            uid = first
            users.setdefault(key, {})[game] = uid
            save_users(users)
            await update.message.reply_text(f"✅ حفظت UID {uid} لحساب {game}.")
        else:
            await update.message.reply_text("❌ لم تحفظ UID بعد. استخدم /set <game> <uid> أو أرسل UID بعد الأمر.")
            return

    if not uid:
        await update.message.reply_text("❌ لم تحفظ UID بعد. استخدم /set <game> <uid> أو أعطِ UID مباشرة بعد الأمر.")
        return

    # fetch
    await update.message.reply_text("⏳ جلب البيانات من Enka... انتظر لحظة.")
    data = fetch_enka_data(game, uid)
    if not data:
        await update.message.reply_text(
            "❌ فشل في جلب البيانات من Enka. تحقق من الـ UID أو أعد المحاولة لاحقًا."
        )
        return

    chars = extract_characters_from_response(data)
    if not chars:
        # More specific checks: maybe response exists but no avatar list
        # Helpful message with action steps
        msg = (
            "ℹ️ لم أجد شخصيات في هذا الحساب.\n\n"
            "التحقّق خطوة بخطوة:\n"
            "1) تأكد أن الـ UID صحيح.\n"
            "2) افتح اللعبة وانتقل للـ Profile > Showcase، ضع الشخصيات التي تريد عرضها.\n"
            "3) في إعدادات الخصوصية فعّل 'Show Character Details' أو ما يماثلها.\n"
            "4) أعد تشغيل اللعبة أو انتظر 5-10 دقائق ثم جرّب مرة أخرى.\n\n"
            "إذا كنت متأكدًا أن كل شيء مفعل وما زالت المشكلة مستمرة، أرسل لي الـ UID هنا لأتأكد منه."
        )
        await update.message.reply_text(msg)
        return

    # If user passed a character name as argument try to match immediately
    if context.args:
        name_query = " ".join(context.args).strip().lower()
        for i, ch in enumerate(chars):
            if name_query == str(ch.get("name", "")).strip().lower():
                await show_character_details(update, context, game, uid, ch)
                return
        # not found, continue to list

    # build inline keyboard
    keyboard = []
    for i, ch in enumerate(chars):
        name = ch.get("name", "Unknown")
        cb = f"enk|{game}|{uid}|{i}"
        keyboard.append([InlineKeyboardButton(text=name, callback_data=cb)])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("اختر شخصية:", reply_markup=reply_markup)


async def show_character_details(update_or_query, context, game: str, uid: str, char_entry: Dict[str, Any]):
    raw = char_entry.get("raw", {}) if isinstance(char_entry, dict) else {}
    name = char_entry.get("name") or raw.get("name") or raw.get("avatarName") or "Unknown"
    # level heuristics
    level = raw.get("level") or raw.get("rarity") or raw.get("fetter") or raw.get("levelText") or "?"
    info_lines = [f"🔸 الاسم: {name}", f"🔸 مستوى / تقدّم: {level}"]

    # weapon
    weapon = raw.get("weapon") or raw.get("equipment") or {}
    if isinstance(weapon, dict) and (weapon.get("name") or weapon.get("icon")):
        info_lines.append(f"⚔️ سلاح: {weapon.get('name') or weapon.get('icon')}")

    # artifacts / reliquaries
    relics = raw.get("reliquaries") or raw.get("artifacts") or raw.get("relics")
    if isinstance(relics, list) and relics:
        info_lines.append(f"🛡️ آثار: {len(relics)} قطع")

    # image heuristics
    image_url = None
    for k in ("icon", "avatarIcon", "image", "avatarIconUrl", "iconUrl"):
        v = raw.get(k)
        if isinstance(v, str) and v.startswith("http"):
            image_url = v
            break

    text = "\n".join(info_lines)

    # send response (handle both CallbackQuery and Message)
    if hasattr(update_or_query, "answer"):  # callback query
        cq = update_or_query
        try:
            await cq.answer()
        except Exception:
            pass
        chat = cq.message.chat_id
        if image_url:
            await context.bot.send_photo(chat_id=chat, photo=image_url, caption=text)
        else:
            await context.bot.send_message(chat_id=chat, text=text)
    else:
        upd = update_or_query
        if image_url:
            await upd.message.reply_photo(photo=image_url, caption=text)
        else:
            await upd.message.reply_text(text)


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query or not query.data:
        return
    data = query.data
    if not data.startswith("enk|"):
        await query.answer()
        return
    try:
        _, game, uid, idx_str = data.split("|", 3)
        idx = int(idx_str)
    except Exception:
        await query.answer("خطأ في البيانات.")
        return

    enka = fetch_enka_data(game, uid)
    if not enka:
        await query.answer("فشل في جلب بيانات Enka.")
        return

    chars = extract_characters_from_response(enka)
    if idx < 0 or idx >= len(chars):
        await query.answer("خيار غير صالح.")
        return
    ch = chars[idx]
    await show_character_details(query, context, game, uid, ch)


def register_handlers(app):
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("set", cmd_set))
    app.add_handler(CommandHandler("account", cmd_account))

    # game commands
    app.add_handler(CommandHandler("gen", lambda u, c: cmd_game_generic(u, c, "gen")))
    app.add_handler(CommandHandler("hsr", lambda u, c: cmd_game_generic(u, c, "hsr")))
    app.add_handler(CommandHandler("zzz", lambda u, c: cmd_game_generic(u, c, "zzz")))

    app.add_handler(CallbackQueryHandler(callback_handler))


def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    register_handlers(app)
    logger.info("Starting Enka bot...")
    app.run_polling()


if __name__ == "__main__":
    main()
