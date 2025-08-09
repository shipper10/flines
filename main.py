#!/usr/bin/env python3
import os
import json
import logging
from typing import Dict, Any, Optional, List

import requests
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    CallbackQueryHandler,
)

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


# mapping short command -> enka API path
GAME_ENDPOINTS = {
    "gen": "api/uid/{uid}",        # Genshin
    "hsr": "api/hsr/uid/{uid}",    # Honkai Star Rail
    "zzz": "api/zzz/uid/{uid}",    # Zenless Zone Zero
}

ENKA_BASE = "https://enka.network/"  # primary base - fallback handled in code


def build_enka_url(game: str, uid: str) -> str:
    path_template = GAME_ENDPOINTS.get(game)
    if not path_template:
        raise ValueError("Unsupported game")
    return ENKA_BASE.rstrip("/") + "/" + path_template.format(uid=uid).lstrip("/")


def fetch_enka_data(game: str, uid: str, timeout: int = 10) -> Optional[Dict[str, Any]]:
    """Fetch raw JSON from Enka API. Return dict or None on failure."""
    url = build_enka_url(game, uid)
    try:
        resp = requests.get(url, timeout=timeout)
        if resp.status_code != 200:
            logger.warning("Enka returned status %s for %s", resp.status_code, url)
            return None
        return resp.json()
    except Exception as e:
        logger.exception("Failed to fetch Enka data: %s", e)
        return None


def extract_characters_from_response(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Try to find a list of characters in Enka API response.
    Heuristics: keys like 'characters', 'avatars', 'player'->'characters', etc.
    Returns list of dicts with at least 'name' (or 'avatar') and an 'id' if available.
    """
    if not isinstance(data, dict):
        return []
    # Common Enka format uses 'avatars' or 'characters'
    for key in ("avatars", "characters", "data", "playerInfo", "player"):
        maybe = data.get(key)
        if isinstance(maybe, list) and maybe:
            # each item might contain name / avatar info
            out = []
            for item in maybe:
                if not isinstance(item, dict):
                    continue
                # name field: several possibilities
                name = item.get("name") or item.get("avatarName") or item.get("character") or item.get("icon", None)
                # fallback to any recognizable field
                if not name:
                    # try nested info
                    name = item.get("prop", {}).get("name") if isinstance(item.get("prop"), dict) else None
                out.append({"name": str(name) if name is not None else "Unknown", "raw": item})
            if out:
                return out
    # fallback: look for nested 'player'->'showcase' etc
    # final fallback: empty
    return []


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "مرحبًا! هذه الأوامر المدعومة:\n"
        "/set <game> <uid> — احفظ UID لحسابك (game: gen | hsr | zzz)\n"
        "/account — عرض الحسابات المحفوظة\n"
        "/gen — Genshin (اكتب /gen للحصول على قائمة الشخصيات)\n"
        "/hsr — Honkai Star Rail\n"
        "/zzz — Zenless Zone Zero\n\n"
        "مثال: /set gen 700000001\n"
        "بعد حفظ UID، اكتب /gen ثم اختر شخصية من الأزرار."
    )


async def cmd_set(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) != 2:
        await update.message.reply_text("❌ الصيغة: /set <game> <uid>  — مثال: /set gen 700000001")
        return
    game = args[0].lower()
    uid = args[1].strip()
    if game not in GAME_ENDPOINTS:
        await update.message.reply_text("❌ اللعبة غير مدعومة. استخدم: gen, hsr, zzz")
        return
    users = load_users()
    key = str(update.effective_user.id)
    users.setdefault(key, {})
    users[key][game] = uid
    save_users(users)
    await update.message.reply_text(f"✅ تم حفظ UID للحساب ({game}): {uid}")


async def cmd_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
    users = load_users()
    key = str(update.effective_user.id)
    u = users.get(key, {})
    if not u:
        await update.message.reply_text("ℹ️ لا توجد حسابات محفوظة. استخدم /set <game> <uid>")
        return
    lines = []
    for g, uid in u.items():
        lines.append(f"{g}: {uid}")
    await update.message.reply_text("حساباتك المحفوظة:\n" + "\n".join(lines))


async def cmd_game_generic(update: Update, context: ContextTypes.DEFAULT_TYPE, game: str):
    """
    Common handler for /gen, /hsr, /zzz
    If args provided (character name), try to show that character immediately.
    Otherwise list characters as inline buttons.
    """
    users = load_users()
    key = str(update.effective_user.id)
    u = users.get(key, {})
    uid = u.get(game)
    # allow: /gen <uid> to set on the fly (convenience)
    if not uid and context.args:
        # if first arg is numeric, treat as uid set+proceed
        first = context.args[0]
        if first.isdigit():
            uid = first
            users.setdefault(key, {})[game] = uid
            save_users(users)
            await update.message.reply_text(f"✅ حفظت UID {uid} لحساب {game}.")
        else:
            # if user typed a character name but no UID saved:
            await update.message.reply_text("❌ لم تحفظ UID بعد. استخدم /set <game> <uid> أو أرسل UID بعد الأمر.")
            return

    if not uid:
        await update.message.reply_text("❌ لم تحفظ UID بعد. استخدم /set <game> <uid> أو أعطِ UID مباشرة بعد الأمر.")
        return

    # fetch data
    await update.message.reply_text("⏳ جلب البيانات من Enka... انتظر لحظة.")
    data = fetch_enka_data(game, uid)
    if not data:
        await update.message.reply_text("❌ فشل في جلب البيانات من Enka. قد تكون الخدمة معطّلة أو UID غير صحيح.")
        return

    chars = extract_characters_from_response(data)
    if not chars:
        await update.message.reply_text("ℹ️ لم يتم العثور على شخصيات في هذا الحساب (أو تنسيق الرد غير متوقع).")
        return

    # if user provided a character name as argument, try to match and show directly
    if context.args:
        name_query = " ".join(context.args).strip().lower()
        # if first arg was UID we already handled; now match by name
        for ch in chars:
            if name_query == str(ch.get("name", "")).strip().lower():
                # show details
                await show_character_details(update, context, game, uid, ch)
                return
        # not found -> continue to listing
        await update.message.reply_text("ℹ️ لم أجد شخصية بنفس الاسم ـ سأعرض لك القائمة لاختيار واحد منها.")

    # build inline keyboard of character names (max per row 2)
    keyboard = []
    for ch in chars:
        name = ch.get("name", "Unknown")
        # callback_data: game|uid|index (index to find raw later)
        idx = chars.index(ch)
        cb = f"enkact|{game}|{uid}|{idx}"
        keyboard.append([InlineKeyboardButton(text=name, callback_data=cb)])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("اختر شخصية:", reply_markup=reply_markup)


async def show_character_details(update_or_query, context, game: str, uid: str, char_entry: Dict[str, Any]):
    """
    Send a message with character details. char_entry is from extract_characters_from_response (with 'raw').
    update_or_query may be Update (message) or CallbackQuery.
    """
    # get raw data
    raw = char_entry.get("raw", {}) if isinstance(char_entry, dict) else {}
    # Try to extract useful fields
    name = char_entry.get("name") or raw.get("name") or raw.get("avatarName") or "Unknown"
    level = raw.get("level") or raw.get("rarity") or raw.get("fetter") or raw.get("levelText") or "?"
    # attack stats or power may be present
    info_lines = [f"🔸 الاسم: {name}", f"🔸 مستوى / مستوى تقدّم: {level}"]
    # Add some more details when available
    if isinstance(raw.get("weapon"), dict):
        w = raw["weapon"]
        info_lines.append(f"⚔️ سلاح: {w.get('name') or w.get('icon') or 'N/A'}")
    # artifacts / relics - heuristic keys
    artifacts = raw.get("reliquaries") or raw.get("artifacts") or raw.get("relics")
    if isinstance(artifacts, list) and artifacts:
        info_lines.append(f"🛡️ مجموعات آثار: {len(artifacts)}")
    # image
    image_url = None
    # common Enka fields for images
    if isinstance(raw.get("icon"), str) and raw.get("icon").startswith("http"):
        image_url = raw.get("icon")
    elif isinstance(raw.get("avatarIcon"), str) and raw.get("avatarIcon").startswith("http"):
        image_url = raw.get("avatarIcon")
    elif isinstance(raw.get("image"), str) and raw.get("image").startswith("http"):
        image_url = raw.get("image")
    text = "\n".join(info_lines)

    # send either as answer to callback query or new message
    if hasattr(update_or_query, "answer"):  # it's a CallbackQuery
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
        # regular update (message)
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
    # Our callback_data format: enkact|game|uid|index
    if not data.startswith("enkact|"):
        await query.answer()
        return
    try:
        _, game, uid, idx_str = data.split("|", 3)
        idx = int(idx_str)
    except Exception:
        await query.answer("خطأ في البيانات.")
        return

    # fetch enka data and extract again
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

    # game handlers
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
