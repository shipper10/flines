#!/usr/bin/env python3
import os
import json
import logging
import asyncio
import time
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

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("enka-bot")

BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise SystemExit("Missing BOT_TOKEN environment variable")

ACCOUNTS_FILE = "accounts.json"
IMAGES_DIR = "images"

# ensure files/dirs exist
if not os.path.exists(ACCOUNTS_FILE):
    with open(ACCOUNTS_FILE, "w", encoding="utf-8") as f:
        json.dump({}, f, ensure_ascii=False, indent=2)

os.makedirs(IMAGES_DIR, exist_ok=True)

def load_accounts() -> Dict[str, Dict[str, str]]:
    try:
        with open(ACCOUNTS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_accounts(d: Dict[str, Dict[str, str]]) -> None:
    with open(ACCOUNTS_FILE, "w", encoding="utf-8") as f:
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

def fetch_enka_data_sync(game: str, uid: str, timeout: int = 30, retries: int = 3, backoff: float = 1.5) -> Optional[Dict[str, Any]]:
    """Blocking synchronous fetch with retries. Designed to be called inside asyncio.to_thread."""
    url = build_enka_url(game, uid)
    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(url, timeout=timeout)
            if resp.status_code != 200:
                logger.warning(\"Enka returned status %s for %s\", resp.status_code, url)
                return None
            return resp.json()
        except requests.exceptions.RequestException as e:
            logger.warning(\"Attempt %s: error fetching Enka data: %s\", attempt, e)
            if attempt < retries:
                time.sleep(backoff * attempt)
                continue
            return None

async def fetch_enka_data(game: str, uid: str, timeout: int = 30, retries: int = 3) -> Optional[Dict[str, Any]]:
    # run blocking I/O in thread to avoid blocking event loop
    return await asyncio.to_thread(fetch_enka_data_sync, game, uid, timeout, retries)

def extract_characters_from_response(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    if not isinstance(data, dict):
        return []

    # 1) common Genshin format: avatarInfoList
    if \"avatarInfoList\" in data and isinstance(data[\"avatarInfoList\"], list):
        out = []
        for item in data[\"avatarInfoList\"]:
            if not isinstance(item, dict):
                continue
            name = item.get(\"name\") or item.get(\"avatarName\") or item.get(\"icon\") or item.get(\"id\") or \"Unknown\"
            out.append({\"name\": str(name), \"raw\": item})
        if out:
            return out

    # 2) other common keys
    for key in (\"avatars\", \"characters\", \"data\", \"playerInfo\", \"player\"):
        maybe = data.get(key)
        if isinstance(maybe, list) and maybe:
            out = []
            for item in maybe:
                if not isinstance(item, dict):
                    continue
                name = item.get(\"name\") or item.get(\"avatarName\") or item.get(\"character\") or item.get(\"icon\") or \"Unknown\"
                out.append({\"name\": str(name), \"raw\": item})
            if out:
                return out

    # 3) recursive search for a list of dicts with candidate keys
    def search_for_list(d):
        if isinstance(d, list):
            candidates = []
            for el in d:
                if isinstance(el, dict):
                    if any(k in el for k in (\"name\", \"avatarName\", \"icon\", \"id\", \"avatarId\", \"character\")):
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
            name = item.get(\"name\") or item.get(\"avatarName\") or item.get(\"icon\") or \"Unknown\"
            out.append({\"name\": str(name), \"raw\": item})
        if out:
            return out

    return []

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        \"مرحبًا! أوامر البوت:\n\"
        \"/set <game> <uid> — حفظ UID (game: gen | hsr | zzz)\n\"
        \"/account — عرض الحسابات المحفوظة\n\"
        \"/gen — Genshin\n\"
        \"/hsr — Honkai: Star Rail\n\"
        \"/zzz — Zenless Zone Zero\n\n\"
        \"مثال: /set gen 700000001\n\"
        \"بعد حفظ UID اكتب /gen لعرض شخصياتك (زر لاختيار الشخصية سيظهر).\"
    )

async def cmd_set(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) != 2:
        await update.message.reply_text(\"❌ الصيغة: /set <game> <uid> — مثال: /set gen 700000001\")
        return
    game = args[0].lower()
    uid = args[1].strip()
    if game not in GAME_ENDPOINTS:
        await update.message.reply_text(\"❌ اللعبة غير مدعومة. استخدم: gen, hsr, zzz\")
        return
    accounts = load_accounts()
    key = str(update.effective_user.id)
    accounts.setdefault(key, {})[game] = uid
    save_accounts(accounts)
    await update.message.reply_text(f\"✅ تم حفظ UID للحساب ({game}): {uid}\")

async def cmd_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
    accounts = load_accounts()
    key = str(update.effective_user.id)
    u = accounts.get(key, {})
    if not u:
        await update.message.reply_text(\"ℹ️ لا توجد حسابات محفوظة. استخدم /set <game> <uid>\")
        return
    lines = [f\"{g}: {uid}\" for g, uid in u.items()]
    await update.message.reply_text(\"حساباتك المحفوظة:\\n\" + \"\\n\".join(lines))

async def cmd_game_generic(update: Update, context: ContextTypes.DEFAULT_TYPE, game: str):
    accounts = load_accounts()
    key = str(update.effective_user.id)
    u = accounts.get(key, {})
    uid = u.get(game)

    # allow: /gen <uid> to set on the fly
    if not uid and context.args:
        first = context.args[0]
        if first.isdigit():
            uid = first
            accounts.setdefault(key, {})[game] = uid
            save_accounts(accounts)
            await update.message.reply_text(f\"✅ حفظت UID {uid} لحساب {game}.\")
        else:
            await update.message.reply_text(\"❌ لم تحفظ UID بعد. استخدم /set <game> <uid> أو أرسل UID بعد الأمر.\")
            return

    if not uid:
        await update.message.reply_text(\"❌ لم تحفظ UID بعد. استخدم /set <game> <uid> أو أعطِ UID مباشرة بعد الأمر.\")
        return

    await update.message.reply_text(\"⏳ جلب البيانات من Enka... انتظر لحظة.\")
    data = await fetch_enka_data(game, uid, timeout=30, retries=3)
    if not data:
        await update.message.reply_text(
            \"❌ فشل في جلب البيانات من Enka. تحقق من الـ UID أو أعد المحاولة لاحقًا.\"
        )
        return

    chars = extract_characters_from_response(data)
    if not chars:
        msg = (
            \"ℹ️ لم أجد شخصيات في هذا الحساب.\\n\\n\"
            \"خطوات التحقق:\\n\"
            \"1) تأكد أن الـ UID صحيح.\\n\"
            \"2) افتح اللعبة وانتقل إلى Profile > Showcase، ضع الشخصيات التي تريد عرضها.\\n\"
            \"3) في إعدادات الخصوصية فعّل 'Show Character Details' أو ما يماثلها.\\n\"
            \"4) أعد تشغيل اللعبة أو انتظر 5-10 دقائق ثم جرّب مرة أخرى.\\n\\n\"
            \"إذا كنت متأكدًا أرسل لي الـ UID هنا لأتفقد الرد الخام من Enka.\"
        )
        await update.message.reply_text(msg)
        return

    # if user provided name try match
    if context.args:
        name_query = \" \".join(context.args).strip().lower()
        for i, ch in enumerate(chars):
            if name_query == str(ch.get(\"name\", \"\")).strip().lower():
                await show_character_details(update, context, game, uid, ch)
                return
        await update.message.reply_text(\"ℹ️ لم أجد شخصية بنفس الاسم ـ سأعرض لك القائمة لاختيار واحد منها.\")

    # build inline keyboard
    keyboard = []
    for i, ch in enumerate(chars):
        name = ch.get(\"name\", \"Unknown\")
        cb = f\"enk|{game}|{uid}|{i}\"
        keyboard.append([InlineKeyboardButton(text=name, callback_data=cb)])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(\"اختر شخصية:\", reply_markup=reply_markup)

async def show_character_details(update_or_query, context, game: str, uid: str, char_entry: Dict[str, Any]):
    raw = char_entry.get(\"raw\", {}) if isinstance(char_entry, dict) else {}
    name = char_entry.get(\"name\") or raw.get(\"name\") or raw.get(\"avatarName\") or \"Unknown\"
    level = raw.get(\"level\") or raw.get(\"rarity\") or raw.get(\"fetter\") or raw.get(\"levelText\") or \"?\"
    info_lines = [f\"🔸 الاسم: {name}\", f\"🔸 مستوى / تقدّم: {level}\"]

    # weapon
    weapon = raw.get(\"weapon\") or raw.get(\"equipment\") or {}
    if isinstance(weapon, dict) and (weapon.get(\"name\") or weapon.get(\"icon\")):
        info_lines.append(f\"⚔️ سلاح: {weapon.get('name') or weapon.get('icon')}\")

    # relics
    relics = raw.get(\"reliquaries\") or raw.get(\"artifacts\") or raw.get(\"relics\")
    if isinstance(relics, list) and relics:
        info_lines.append(f\"🛡️ آثار: {len(relics)} قطع\")

    # image heuristics
    image_url = None
    for k in (\"icon\", \"avatarIcon\", \"image\", \"avatarIconUrl\", \"iconUrl\"):
        v = raw.get(k)
        if isinstance(v, str) and v.startswith(\"http"):
            image_url = v
            break

    text = \"\\n\".join(info_lines)

    # send response (handle both CallbackQuery and Message)
    if hasattr(update_or_query, \"answer\"):  # callback query
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
    if not data.startswith(\"enk|\"):
        await query.answer()
        return
    try:
        _, game, uid, idx_str = data.split(\"|\", 3)
        idx = int(idx_str)
    except Exception:
        await query.answer(\"خطأ في البيانات.\")
        return

    enka = await fetch_enka_data(game, uid, timeout=30, retries=3)
    if not enka:
        await query.answer(\"فشل في جلب بيانات Enka.\")
        return

    chars = extract_characters_from_response(enka)
    if idx < 0 or idx >= len(chars):
        await query.answer(\"خيار غير صالح.\")
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
